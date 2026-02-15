"""Strategy Discoverer — automated search for profitable strategy rule combinations.

Scans a predefined parameter space of ``StrategyRule`` combinations, backtests
each candidate against historical signals, and returns the top-performing
strategies ranked by Sharpe ratio (or another metric).

Two search modes are supported:

* **exhaustive** — enumerates all rule combinations up to ``max_rules`` deep.
  Practical only when the search space is small (a few hundred combos).
* **random** — random sampling from the combinatorial space.  Much faster and
  the default.  Stops after ``max_candidates`` evaluations.

Optional **walk-forward validation** splits the signal history chronologically
into folds and reports average out-of-sample performance to guard against
overfitting.

Usage::

    from rot.strategy.discovery import StrategyDiscoverer
    from rot.backtest.config import BacktestConfig

    discoverer = StrategyDiscoverer(signals, default_config=BacktestConfig())
    result = discoverer.discover(
        search_config={
            "user_id": "u123",
            "max_rules": 3,
            "max_candidates": 500,
            "min_trades": 10,
            "min_win_rate": 0.5,
            "search_mode": "random",
        }
    )

    for strat in result.best_strategies:
        print(strat["name"], strat["sharpe"], strat["win_rate"])
"""

from __future__ import annotations

from rot.core.logging import sanitize_for_log
import itertools
import logging
import math
import random
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from rot.backtest.config import BacktestConfig
from rot.backtest.engine import BacktestEngine
from rot.strategy.rules import RuleEngine
from rot.strategy.types import DiscoveryResult, StrategyRule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Search-space definitions
# ---------------------------------------------------------------------------

#: Confidence thresholds to test as ``gte`` rules.
_CONFIDENCE_THRESHOLDS: List[float] = [0.3, 0.4, 0.5, 0.6, 0.7]

#: Stances to test as ``eq`` rules.
_STANCES: List[str] = ["bullish", "bearish"]

#: Event types from the ROT pipeline (``EventType`` enum values).
_EVENT_TYPES: List[str] = [
    "earnings_rumor",
    "product_news",
    "regulatory",
    "squeeze_chatter",
    "macro",
    "other",
]

#: Subreddits to test as ``eq`` rules on the ``subreddit`` field.
_SUBREDDITS: List[str] = ["wallstreetbets", "stocks", "options"]

#: Quality-score thresholds (``gte``).
_QUALITY_THRESHOLDS: List[float] = [0.3, 0.5, 0.7]

#: Trend-score thresholds (``gte``).
_TREND_THRESHOLDS: List[float] = [0.1, 0.3, 0.5]

#: Maximum number of best strategies to keep in results.
_TOP_N = 10

#: Default number of walk-forward folds.
_DEFAULT_WF_FOLDS = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_atomic_rules() -> List[StrategyRule]:
    """Create the full set of single rules that form the search space.

    Each rule is one filter condition.  Strategies are formed by combining
    one or more of these rules (AND logic).
    """
    rules: List[StrategyRule] = []

    # Confidence >= threshold
    for thresh in _CONFIDENCE_THRESHOLDS:
        rules.append(StrategyRule(field="confidence", operator="gte", value=thresh))

    # Stance == value
    for stance in _STANCES:
        rules.append(StrategyRule(field="stance", operator="eq", value=stance))

    # Event type == value
    for et in _EVENT_TYPES:
        rules.append(StrategyRule(field="event_type", operator="eq", value=et))

    # Subreddit == value
    for sub in _SUBREDDITS:
        rules.append(StrategyRule(field="subreddit", operator="eq", value=sub))

    # Quality score >= threshold
    for thresh in _QUALITY_THRESHOLDS:
        rules.append(StrategyRule(field="quality_score", operator="gte", value=thresh))

    # Trend score >= threshold
    for thresh in _TREND_THRESHOLDS:
        rules.append(StrategyRule(field="trend_score", operator="gte", value=thresh))

    return rules


def _rules_are_compatible(rules: Sequence[StrategyRule]) -> bool:
    """Check whether a combination of rules can logically co-exist.

    Filters out clearly contradictory combinations, e.g.:

    * Two ``eq`` rules on the same field with different values (impossible to
      satisfy both simultaneously).
    * Two ``gte`` rules on the same field — only the stricter one matters, so
      we keep the combination but the weaker rule is redundant (still valid,
      just wasteful).
    * Duplicate rules.

    Returns ``True`` if the combination is valid.
    """
    # Reject exact duplicates
    if len(set((r.field, r.operator, str(r.value)) for r in rules)) < len(rules):
        return False

    # Reject contradictory equality rules on the same field
    eq_values: Dict[str, Any] = {}
    for r in rules:
        if r.operator == "eq":
            if r.field in eq_values and eq_values[r.field] != r.value:
                return False
            eq_values[r.field] = r.value

    # Reject redundant gte rules on the same field (keep only the strictest).
    # We still allow the combination, but the candidate generator should have
    # pruned this earlier.  As a defence, reject if we see >1 gte on same
    # field — they produce identical results to the stricter one alone.
    gte_fields: Dict[str, int] = {}
    for r in rules:
        if r.operator in ("gte", "gt"):
            gte_fields[r.field] = gte_fields.get(r.field, 0) + 1
    for count in gte_fields.values():
        if count > 1:
            return False

    return True


def _describe_rules(rules: List[StrategyRule]) -> str:
    """Generate a short human-readable name from a list of rules.

    Examples:
        ``confidence>=0.5 AND stance=bullish``
    """
    parts: List[str] = []
    op_map = {
        "gt": ">",
        "lt": "<",
        "gte": ">=",
        "lte": "<=",
        "eq": "=",
        "neq": "!=",
        "in": " in ",
    }
    for r in sorted(rules, key=lambda x: x.field):
        op_str = op_map.get(r.operator, r.operator)
        parts.append(f"{r.field}{op_str}{r.value}")
    return " AND ".join(parts)


def _safe_sharpe(result: Any) -> float:
    """Extract a usable Sharpe from a ``BacktestResult``, defaulting to -inf."""
    sharpe = getattr(result, "sharpe_ratio", None)
    if sharpe is None or (isinstance(sharpe, float) and math.isnan(sharpe)):
        return float("-inf")
    return float(sharpe)


# ---------------------------------------------------------------------------
# StrategyDiscoverer
# ---------------------------------------------------------------------------


class StrategyDiscoverer:
    """Automatically discovers profitable strategy rule combinations.

    Given a corpus of historical signal dicts (as returned by
    ``database.get_backtest_signals()``), this class searches the combinatorial
    space of ``StrategyRule`` filters, backtests each candidate, and ranks the
    survivors by Sharpe ratio.

    Parameters
    ----------
    backtest_signals:
        Historical signal dicts with keys such as ``signal_id``, ``ticker``,
        ``stance``, ``strategy``, ``event_type``, ``confidence``,
        ``created_at``, ``price_at_signal``, ``price_1h``, ``price_4h``,
        ``price_1d``, ``max_gain_pct``, ``max_loss_pct``, ``subreddit``,
        ``quality_score``, ``trend_score``.
    default_config:
        Base ``BacktestConfig`` whose portfolio / exit settings are used for
        every candidate backtest.  Signal-level filters inside the config are
        ignored in favour of the strategy rules being tested.
    """

    def __init__(
        self,
        backtest_signals: list[dict],
        default_config: BacktestConfig | None = None,
    ) -> None:
        self._signals = list(backtest_signals)
        self._config = default_config or BacktestConfig()
        self._engine = BacktestEngine()
        self._rule_engine = RuleEngine()

        # Pre-sort signals chronologically once (avoids re-sorting per backtest)
        self._signals.sort(key=lambda s: s.get("created_at", 0))

        logger.info(
            "StrategyDiscoverer initialised with %d signals", len(self._signals)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(self, search_config: dict) -> DiscoveryResult:
        """Run a full discovery search.

        Parameters
        ----------
        search_config:
            Controls the search.  Recognised keys:

            * ``user_id`` (str, required) — owner.
            * ``max_rules`` (int, 1-5, default 3) — max rules per strategy.
            * ``max_candidates`` (int, default 1000) — budget for evaluations.
            * ``min_trades`` (int, default 10) — minimum trades for validity.
            * ``min_win_rate`` (float, default 0.5) — minimum win-rate filter.
            * ``min_sharpe`` (float, default 0.0) — minimum Sharpe filter.
            * ``search_mode`` (``"exhaustive"`` | ``"random"``, default
              ``"random"``).
            * ``walk_forward`` (bool, default False) — validate with
              walk-forward.
            * ``walk_forward_folds`` (int, default 3) — number of folds if
              ``walk_forward`` is True.

        Returns
        -------
        DiscoveryResult
            Contains the top strategies found, timing, and search metadata.
        """
        t0 = time.time()

        user_id: str = search_config.get("user_id", "system")
        max_rules: int = max(1, min(int(search_config.get("max_rules", 3)), 5))
        max_candidates: int = max(1, int(search_config.get("max_candidates", 1000)))
        min_trades: int = max(1, int(search_config.get("min_trades", 10)))
        min_win_rate: float = float(search_config.get("min_win_rate", 0.5))
        min_sharpe: float = float(search_config.get("min_sharpe", 0.0))
        search_mode: str = search_config.get("search_mode", "random")
        walk_forward: bool = bool(search_config.get("walk_forward", False))
        wf_folds: int = max(2, int(search_config.get("walk_forward_folds", _DEFAULT_WF_FOLDS)))

        logger.info(
            "Starting discovery: mode=%s max_rules=%d max_candidates=%d "
            "min_trades=%d min_win_rate=%.2f min_sharpe=%.2f walk_forward=%s",
            search_mode,
            max_rules,
            max_candidates,
            min_trades,
            min_win_rate,
            min_sharpe,
            walk_forward,
        )

        # 1. Generate candidate rule-sets
        candidates = self._generate_candidates(
            search_config={
                "max_rules": max_rules,
                "max_candidates": max_candidates,
                "search_mode": search_mode,
            }
        )

        logger.info("Generated %d candidate rule-sets to evaluate", len(candidates))

        # 2. Evaluate each candidate
        valid_results: List[dict] = []
        evaluated = 0

        for rule_set in candidates:
            evaluated += 1

            if evaluated % 100 == 0:
                logger.debug(
                    "Discovery progress: %d / %d evaluated, %d valid so far",
                    evaluated,
                    len(candidates),
                    len(valid_results),
                )

            result = self._backtest_candidate(
                rules=rule_set,
                min_trades=min_trades,
                min_win_rate=min_win_rate,
                min_sharpe=min_sharpe,
            )

            if result is not None:
                # Optional walk-forward validation
                if walk_forward:
                    wf_metrics = self._walk_forward_validate(
                        rules=rule_set,
                        n_folds=wf_folds,
                    )
                    result["walk_forward"] = wf_metrics

                    # Reject if OOS performance is too poor
                    oos_win_rate = wf_metrics.get("avg_win_rate", 0.0)
                    oos_sharpe = wf_metrics.get("avg_sharpe", float("-inf"))
                    if oos_win_rate < min_win_rate or oos_sharpe < min_sharpe:
                        logger.debug(
                            "Candidate rejected by walk-forward: OOS win_rate=%.3f "
                            "sharpe=%.3f",
                            oos_win_rate,
                            oos_sharpe,
                        )
                        continue

                valid_results.append(result)

        # 3. Rank and pick top N
        sort_key = search_config.get("sort_by", "sharpe")
        best = self.rank_strategies(valid_results, sort_by=sort_key)

        elapsed = time.time() - t0

        logger.info(
            "Discovery complete: %d candidates evaluated, %d valid, "
            "top %d returned in %.1fs",
            evaluated,
            len(valid_results),
            len(best),
            elapsed,
        )

        return DiscoveryResult(
            id=str(uuid4()),
            user_id=user_id,
            search_config=search_config,
            strategies_found=len(valid_results),
            best_strategies=best,
            elapsed_s=round(elapsed, 3),
        )

    def rank_strategies(
        self,
        results: list[dict],
        sort_by: str = "sharpe",
    ) -> list[dict]:
        """Sort strategy results by the specified metric, return top N.

        Parameters
        ----------
        results:
            List of candidate result dicts produced by
            ``_backtest_candidate()``.
        sort_by:
            Metric key to sort on.  Supported: ``"sharpe"``, ``"win_rate"``,
            ``"total_pnl"``, ``"profit_factor"``, ``"total_trades"``.
            Defaults to ``"sharpe"``.

        Returns
        -------
        list[dict]
            Top ``_TOP_N`` strategies, sorted descending by the chosen metric.
        """
        if not results:
            return []

        # Map sort_by to a safe key extractor (highest is best)
        def _sort_key(r: dict) -> float:
            val = r.get(sort_by, 0.0)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                return float("-inf")
            return float(val)

        ranked = sorted(results, key=_sort_key, reverse=True)
        return ranked[:_TOP_N]

    # ------------------------------------------------------------------
    # Candidate generation
    # ------------------------------------------------------------------

    def _generate_candidates(
        self,
        search_config: dict,
    ) -> list[list[StrategyRule]]:
        """Build the list of rule-set candidates to evaluate.

        Parameters
        ----------
        search_config:
            Must contain ``max_rules``, ``max_candidates``, ``search_mode``.

        Returns
        -------
        list[list[StrategyRule]]
            Each inner list is one candidate strategy (list of rules applied
            with AND logic).
        """
        max_rules: int = int(search_config.get("max_rules", 3))
        max_candidates: int = int(search_config.get("max_candidates", 1000))
        search_mode: str = search_config.get("search_mode", "random")

        atomic = _build_atomic_rules()

        if search_mode == "exhaustive":
            return self._exhaustive_candidates(atomic, max_rules, max_candidates)
        else:
            return self._random_candidates(atomic, max_rules, max_candidates)

    def _exhaustive_candidates(
        self,
        atomic: List[StrategyRule],
        max_rules: int,
        max_candidates: int,
    ) -> list[list[StrategyRule]]:
        """Enumerate all valid combinations up to ``max_rules`` deep.

        Stops once ``max_candidates`` valid combinations have been collected
        to bound memory and compute.
        """
        candidates: list[list[StrategyRule]] = []

        for depth in range(1, max_rules + 1):
            for combo in itertools.combinations(atomic, depth):
                combo_list = list(combo)
                if not _rules_are_compatible(combo_list):
                    continue
                candidates.append(combo_list)
                if len(candidates) >= max_candidates:
                    logger.info(
                        "Exhaustive search capped at %d candidates (depth %d)",
                        max_candidates,
                        depth,
                    )
                    return candidates

        return candidates

    def _random_candidates(
        self,
        atomic: List[StrategyRule],
        max_rules: int,
        max_candidates: int,
    ) -> list[list[StrategyRule]]:
        """Sample random valid combinations up to ``max_candidates``.

        Uses rejection sampling: draw a random depth and a random subset of
        atomic rules at that depth, check compatibility, and keep if valid.
        Gives up after ``max_candidates * 10`` attempts to avoid infinite
        loops with very small search spaces.
        """
        candidates: list[list[StrategyRule]] = []
        seen: set[frozenset[tuple[str, str, str]]] = set()
        max_attempts = max_candidates * 10
        attempts = 0

        while len(candidates) < max_candidates and attempts < max_attempts:
            attempts += 1

            # Pick a random depth between 1 and max_rules
            depth = random.randint(1, max_rules)

            # Sample without replacement from atomic rules
            if depth > len(atomic):
                depth = len(atomic)
            combo = random.sample(atomic, depth)

            # Dedup key
            key = frozenset(
                (r.field, r.operator, str(r.value)) for r in combo
            )
            if key in seen:
                continue

            if not _rules_are_compatible(combo):
                continue

            seen.add(key)
            candidates.append(combo)

        if attempts >= max_attempts:
            logger.warning(
                "Random sampling exhausted %d attempts; produced %d candidates",
                max_attempts,
                len(candidates),
            )

        return candidates

    # ------------------------------------------------------------------
    # Backtesting a single candidate
    # ------------------------------------------------------------------

    def _backtest_candidate(
        self,
        rules: list[StrategyRule],
        min_trades: int = 10,
        min_win_rate: float = 0.5,
        min_sharpe: float = 0.0,
    ) -> dict | None:
        """Backtest a single candidate rule-set against stored signals.

        Parameters
        ----------
        rules:
            The filter rules to apply (AND logic).
        min_trades:
            Minimum number of trades for the result to count.
        min_win_rate:
            Minimum win rate threshold.
        min_sharpe:
            Minimum Sharpe ratio threshold.

        Returns
        -------
        dict or None
            A result dict with keys: ``id``, ``name``, ``rules``,
            ``win_rate``, ``sharpe``, ``total_trades``, ``winning_trades``,
            ``losing_trades``, ``total_pnl``, ``total_return_pct``,
            ``max_drawdown_pct``, ``profit_factor``, ``expectancy``,
            ``avg_win_pct``, ``avg_loss_pct``, ``final_equity``.
            Returns ``None`` if the candidate doesn't meet the thresholds.
        """
        # 1. Filter signals through the rule engine
        filtered = self._rule_engine.batch_evaluate(self._signals, rules)

        # Quick reject: not enough signals to even attempt a backtest
        if len(filtered) < min_trades:
            return None

        # 2. Run the backtest engine
        try:
            bt_result = self._engine.run(filtered, self._config)
        except Exception:
            logger.debug(
                "Backtest failed for candidate: %s",
                _describe_rules(rules),
                exc_info=True,
            )
            return None

        # 3. Apply quality gates
        if bt_result.total_trades < min_trades:
            return None

        if bt_result.win_rate < min_win_rate:
            return None

        sharpe = _safe_sharpe(bt_result)
        if sharpe < min_sharpe:
            return None

        # 4. Build result dict
        return {
            "id": str(uuid4()),
            "name": _describe_rules(rules),
            "rules": [r.to_dict() for r in rules],
            "win_rate": round(bt_result.win_rate, 4),
            "sharpe": round(sharpe, 4),
            "total_trades": bt_result.total_trades,
            "winning_trades": bt_result.winning_trades,
            "losing_trades": bt_result.losing_trades,
            "total_pnl": round(bt_result.final_equity - self._config.starting_capital, 2),
            "total_return_pct": round(bt_result.total_return_pct, 2),
            "max_drawdown_pct": round(bt_result.max_drawdown_pct, 2),
            "profit_factor": round(bt_result.profit_factor, 4),
            "expectancy": round(bt_result.expectancy, 4),
            "avg_win_pct": round(bt_result.avg_win_pct, 2),
            "avg_loss_pct": round(bt_result.avg_loss_pct, 2),
            "final_equity": round(bt_result.final_equity, 2),
        }

    # ------------------------------------------------------------------
    # Walk-forward validation
    # ------------------------------------------------------------------

    def _walk_forward_validate(
        self,
        rules: list[StrategyRule],
        n_folds: int = _DEFAULT_WF_FOLDS,
    ) -> dict:
        """Walk-forward out-of-sample validation for a rule-set.

        Splits the signal history chronologically into ``n_folds`` segments.
        For each fold *k*, the in-sample (IS) set consists of folds
        ``0 .. k-1`` and the out-of-sample (OOS) set is fold ``k``.

        We only report metrics on the OOS portions — the IS portion is
        implicitly "used" to confirm that the rules would have been discovered
        (the rules are static, so no actual parameter fitting happens per
        fold, but this simulates the temporal validity check).

        Parameters
        ----------
        rules:
            Strategy rules to validate.
        n_folds:
            Number of chronological folds (minimum 2).

        Returns
        -------
        dict
            Aggregated OOS metrics:

            * ``avg_win_rate`` — mean OOS win rate across folds.
            * ``avg_sharpe`` — mean OOS Sharpe across folds.
            * ``avg_total_trades`` — mean OOS trade count.
            * ``avg_pnl_pct`` — mean OOS return percentage.
            * ``avg_max_drawdown_pct`` — mean OOS max drawdown.
            * ``folds`` — list of per-fold OOS metric dicts.
            * ``stability_score`` — 0.0-1.0 consistency measure (higher is
              better).  Based on the fraction of folds with positive Sharpe.
        """
        n_folds = max(2, n_folds)

        # Filter signals first, then split chronologically
        filtered = self._rule_engine.batch_evaluate(self._signals, rules)
        filtered.sort(key=lambda s: s.get("created_at", 0))

        if len(filtered) < n_folds * 2:
            # Not enough data for meaningful walk-forward
            return {
                "avg_win_rate": 0.0,
                "avg_sharpe": float("-inf"),
                "avg_total_trades": 0,
                "avg_pnl_pct": 0.0,
                "avg_max_drawdown_pct": 0.0,
                "folds": [],
                "stability_score": 0.0,
            }

        # Create folds
        fold_size = len(filtered) // n_folds
        folds: List[List[dict]] = []
        for i in range(n_folds):
            start_idx = i * fold_size
            end_idx = start_idx + fold_size if i < n_folds - 1 else len(filtered)
            folds.append(filtered[start_idx:end_idx])

        # Evaluate each OOS fold (folds 1..n-1; fold 0 is IS-only)
        fold_results: List[dict] = []

        for oos_idx in range(1, n_folds):
            oos_signals = folds[oos_idx]

            if len(oos_signals) < 2:
                continue

            try:
                bt_result = self._engine.run(oos_signals, self._config)
            except Exception:
                logger.debug(
                    "Walk-forward fold %d failed for: %s",
                    oos_idx,
                    _describe_rules(rules),
                    exc_info=True,
                )
                continue

            sharpe = _safe_sharpe(bt_result)

            fold_results.append({
                "fold": oos_idx,
                "total_trades": bt_result.total_trades,
                "win_rate": round(bt_result.win_rate, 4),
                "sharpe": round(sharpe, 4),
                "total_return_pct": round(bt_result.total_return_pct, 2),
                "max_drawdown_pct": round(bt_result.max_drawdown_pct, 2),
                "final_equity": round(bt_result.final_equity, 2),
            })

        if not fold_results:
            return {
                "avg_win_rate": 0.0,
                "avg_sharpe": float("-inf"),
                "avg_total_trades": 0,
                "avg_pnl_pct": 0.0,
                "avg_max_drawdown_pct": 0.0,
                "folds": [],
                "stability_score": 0.0,
            }

        # Aggregate
        n = len(fold_results)
        avg_win_rate = sum(f["win_rate"] for f in fold_results) / n
        avg_sharpe = sum(f["sharpe"] for f in fold_results) / n
        avg_trades = sum(f["total_trades"] for f in fold_results) / n
        avg_pnl = sum(f["total_return_pct"] for f in fold_results) / n
        avg_dd = sum(f["max_drawdown_pct"] for f in fold_results) / n

        # Stability score: fraction of folds with positive Sharpe
        positive_folds = sum(
            1 for f in fold_results if f["sharpe"] > 0
        )
        stability = positive_folds / n if n > 0 else 0.0

        return {
            "avg_win_rate": round(avg_win_rate, 4),
            "avg_sharpe": round(avg_sharpe, 4),
            "avg_total_trades": round(avg_trades, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
            "avg_max_drawdown_pct": round(avg_dd, 2),
            "folds": fold_results,
            "stability_score": round(stability, 4),
        }

    # ------------------------------------------------------------------
    # Batch helpers
    # ------------------------------------------------------------------

    def get_search_space_size(self, max_rules: int = 3) -> dict:
        """Estimate the size of the search space for reporting.

        Returns
        -------
        dict
            * ``atomic_rules`` — number of individual rules.
            * ``max_rules`` — depth parameter.
            * ``estimated_combinations`` — upper-bound of C(n, 1) + ... +
              C(n, max_rules).  Actual valid combinations are fewer after
              compatibility filtering.
        """
        atomic = _build_atomic_rules()
        n = len(atomic)
        total = 0
        for k in range(1, max_rules + 1):
            total += math.comb(n, k)
        return {
            "atomic_rules": n,
            "max_rules": max_rules,
            "estimated_combinations": total,
        }

    def preview_candidates(
        self,
        search_config: dict,
        limit: int = 20,
    ) -> list[str]:
        """Return human-readable descriptions of the first ``limit``
        candidates that would be generated.

        Useful for UI previews and debugging.
        """
        candidates = self._generate_candidates(search_config)
        return [_describe_rules(c) for c in candidates[:limit]]

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def result_to_strategy_dicts(
        self,
        discovery_result: DiscoveryResult,
    ) -> list[dict]:
        """Convert a DiscoveryResult's best_strategies into dicts compatible
        with ``Strategy.from_dict()``.

        Each entry gets ``source="discovered"`` and inherits the user_id from
        the discovery run.

        Returns
        -------
        list[dict]
            Ready-to-persist strategy dicts.
        """
        strategies: list[dict] = []
        user_id = discovery_result.user_id
        now = time.time()

        for candidate in discovery_result.best_strategies:
            strategy_dict = {
                "id": candidate.get("id", str(uuid4())),
                "user_id": user_id,
                "name": candidate.get("name", "Discovered Strategy"),
                "description": (
                    f"Auto-discovered strategy with "
                    f"{candidate.get('total_trades', 0)} trades, "
                    f"{candidate.get('win_rate', 0):.1%} win rate, "
                    f"Sharpe {candidate.get('sharpe', 0):.2f}"
                ),
                "rules": [
                    StrategyRule.from_dict(r).to_dict()
                    for r in candidate.get("rules", [])
                ],
                "config": {},
                "performance": {
                    "win_rate": candidate.get("win_rate", 0.0),
                    "sharpe": candidate.get("sharpe", 0.0),
                    "total_trades": candidate.get("total_trades", 0),
                    "total_pnl": candidate.get("total_pnl", 0.0),
                    "total_return_pct": candidate.get("total_return_pct", 0.0),
                    "max_drawdown_pct": candidate.get("max_drawdown_pct", 0.0),
                    "profit_factor": candidate.get("profit_factor", 0.0),
                    "expectancy": candidate.get("expectancy", 0.0),
                    "avg_win_pct": candidate.get("avg_win_pct", 0.0),
                    "avg_loss_pct": candidate.get("avg_loss_pct", 0.0),
                },
                "health_score": 1.0,
                "is_active": False,
                "source": "discovered",
                "created_at": now,
                "updated_at": now,
            }

            # Attach walk-forward data if present
            wf = candidate.get("walk_forward")
            if wf:
                strategy_dict["performance"]["walk_forward"] = wf

            strategies.append(strategy_dict)

        return strategies

    # ------------------------------------------------------------------
    # Single-strategy evaluation
    # ------------------------------------------------------------------

    def evaluate_rules(
        self,
        rules: list[StrategyRule],
        walk_forward: bool = False,
        walk_forward_folds: int = _DEFAULT_WF_FOLDS,
    ) -> dict | None:
        """Evaluate a specific set of rules against the stored signals.

        Convenience method for testing a hand-crafted or imported rule-set
        without running a full discovery search.

        Parameters
        ----------
        rules:
            Strategy rules to evaluate.
        walk_forward:
            Whether to include walk-forward validation.
        walk_forward_folds:
            Number of folds if walk_forward is True.

        Returns
        -------
        dict or None
            Result dict (same shape as ``_backtest_candidate`` output) or
            None if the strategy produces no trades.
        """
        result = self._backtest_candidate(
            rules=rules,
            min_trades=1,
            min_win_rate=0.0,
            min_sharpe=float("-inf"),
        )

        if result is not None and walk_forward:
            wf_metrics = self._walk_forward_validate(
                rules=rules,
                n_folds=walk_forward_folds,
            )
            result["walk_forward"] = wf_metrics

        return result

    # ------------------------------------------------------------------
    # Multi-signal-set support
    # ------------------------------------------------------------------

    def discover_for_subsets(
        self,
        search_config: dict,
        subsets: dict[str, list[dict]],
    ) -> dict[str, DiscoveryResult]:
        """Run discovery across multiple named subsets of signals.

        Useful for regime-aware discovery: pass different market-regime
        subsets as values and discover the best strategy for each.

        Parameters
        ----------
        search_config:
            Same as ``discover()``.
        subsets:
            Mapping of subset name to signal list.

        Returns
        -------
        dict[str, DiscoveryResult]
            One DiscoveryResult per subset name.
        """
        results: dict[str, DiscoveryResult] = {}

        for name, signals in subsets.items():
            logger.info(
                "Running discovery for subset '%s' with %d signals",
                name,
                len(signals),
            )
            # Create a temporary discoverer with this signal subset
            sub_discoverer = StrategyDiscoverer(
                backtest_signals=signals,
                default_config=self._config,
            )
            results[name] = sub_discoverer.discover(search_config)

        return results

    # ------------------------------------------------------------------
    # Summary / reporting
    # ------------------------------------------------------------------

    def summarise_result(self, discovery_result: DiscoveryResult) -> dict:
        """Produce a compact summary of a discovery run.

        Returns
        -------
        dict
            Keys: ``total_evaluated``, ``strategies_found``, ``top_sharpe``,
            ``top_win_rate``, ``top_pnl``, ``elapsed_s``,
            ``best_strategy_name``.
        """
        best = discovery_result.best_strategies
        if not best:
            return {
                "total_evaluated": discovery_result.search_config.get(
                    "max_candidates", 0
                ),
                "strategies_found": 0,
                "top_sharpe": None,
                "top_win_rate": None,
                "top_pnl": None,
                "elapsed_s": discovery_result.elapsed_s,
                "best_strategy_name": None,
            }

        top_by_sharpe = max(best, key=lambda s: s.get("sharpe", float("-inf")))
        top_by_wr = max(best, key=lambda s: s.get("win_rate", 0.0))
        top_by_pnl = max(best, key=lambda s: s.get("total_pnl", float("-inf")))

        return {
            "total_evaluated": discovery_result.search_config.get(
                "max_candidates", 0
            ),
            "strategies_found": discovery_result.strategies_found,
            "top_sharpe": round(top_by_sharpe.get("sharpe", 0.0), 4),
            "top_win_rate": round(top_by_wr.get("win_rate", 0.0), 4),
            "top_pnl": round(top_by_pnl.get("total_pnl", 0.0), 2),
            "elapsed_s": round(discovery_result.elapsed_s, 3),
            "best_strategy_name": top_by_sharpe.get("name", "Unknown"),
        }
