"""AutoPaperTrader — automated paper-trading engine for the Strategy Builder.

Evaluates incoming signals against active strategies and automatically opens /
resolves paper trades when signal rules match.  Designed to run in the pipeline
callback path (``on_signal``) so that every new signal is tested against all
active user strategies in real time.

Typical usage::

    from rot.strategy.auto_trader import AutoPaperTrader
    from rot.strategy.types import Strategy

    trader = AutoPaperTrader(max_concurrent_per_strategy=10)
    trader.load_strategies([strat1, strat2])

    # Pipeline callback — called for each new signal
    new_trades = trader.evaluate_signal(signal_dict)

    # Periodic price-check callback
    closed = trader.resolve_trades({"AAPL": 195.50, "TSLA": 248.00})

All public methods are GIL-safe (simple list / dict mutations only).  No
background threads or asyncio required — the caller drives the lifecycle.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from typing import Any

from rot.strategy.rules import CompiledRule, RuleEngine
from rot.strategy.types import Strategy, StrategyResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------

_DEFAULT_STOP_LOSS_PCT: float = 10.0
"""Default stop-loss percentage if not specified in strategy config."""

_DEFAULT_TAKE_PROFIT_PCT: float = 20.0
"""Default take-profit percentage if not specified in strategy config."""

_HEALTH_AUTO_DISABLE_THRESHOLD: float = 0.3
"""Health score below which a strategy is recommended for auto-disable."""

_MIN_TRADES_FOR_SHARPE: int = 5
"""Minimum closed trades required before Sharpe ratio is computed."""

_ANNUALISATION_FACTOR: float = math.sqrt(252)
"""Annualisation factor for daily Sharpe ratio (trading days per year)."""

_TRADEABLE_STANCES: frozenset[str] = frozenset({"bullish", "bearish"})
"""Only these stances produce directional trades."""


# ---------------------------------------------------------------------------
# AutoPaperTrader
# ---------------------------------------------------------------------------


class AutoPaperTrader:
    """Automated paper-trading engine that matches signals to strategies.

    For each incoming signal the trader evaluates every active strategy's
    rules.  When all rules match *and* the signal has a directional stance
    (bullish or bearish), a new :class:`StrategyResult` trade is opened.
    Trades are later resolved by :meth:`resolve_trades` when fresh price
    data arrives.

    Args:
        max_concurrent_per_strategy: Maximum number of simultaneously open
            trades per strategy.  Prevents over-concentration.
        default_position_size: Notional position size in dollars.  Used for
            logging / future position-sizing extensions; does not affect
            P&L percentage calculations.
    """

    def __init__(
        self,
        max_concurrent_per_strategy: int = 10,
        default_position_size: float = 1000.0,
    ) -> None:
        if max_concurrent_per_strategy < 1:
            raise ValueError("max_concurrent_per_strategy must be >= 1")
        if default_position_size <= 0:
            raise ValueError("default_position_size must be positive")

        self._max_concurrent: int = max_concurrent_per_strategy
        self._default_position_size: float = default_position_size

        # Strategy state
        self._active_strategies: dict[str, Strategy] = {}
        self._compiled_rules: dict[str, list[CompiledRule]] = {}

        # Trade state
        self._open_trades: dict[str, list[StrategyResult]] = {}
        self._closed_trades: list[StrategyResult] = []

        # Engine (stateless — one instance is fine)
        self._rule_engine: RuleEngine = RuleEngine()

        logger.info(
            "AutoPaperTrader initialised: max_concurrent=%d, position_size=%.2f",
            self._max_concurrent,
            self._default_position_size,
        )

    # ------------------------------------------------------------------
    # Strategy management
    # ------------------------------------------------------------------

    def load_strategies(self, strategies: list[Strategy]) -> None:
        """Load active strategies and pre-compile their rules.

        Only strategies with ``is_active=True`` are loaded.  Any previously
        loaded strategies are replaced.  Open trades for removed strategies
        are preserved until resolved.

        Args:
            strategies: Full list of strategies (active and inactive).
        """

        new_active: dict[str, Strategy] = {}
        new_compiled: dict[str, list[CompiledRule]] = {}

        for strat in strategies:
            if not strat.is_active:
                continue

            try:
                compiled = self._rule_engine.compile_rules(strat.rules)
            except ValueError:
                logger.warning(
                    "Strategy '%s' (%s) has invalid rules — skipping",
                    strat.name,
                    strat.id,
                )
                continue

            new_active[strat.id] = strat
            new_compiled[strat.id] = compiled

            # Ensure open-trade list exists
            if strat.id not in self._open_trades:
                self._open_trades[strat.id] = []

        removed = set(self._active_strategies) - set(new_active)
        added = set(new_active) - set(self._active_strategies)

        self._active_strategies = new_active
        self._compiled_rules = new_compiled

        logger.info(
            "Loaded %d active strategies (+%d new, -%d removed)",
            len(new_active),
            len(added),
            len(removed),
        )

    # ------------------------------------------------------------------
    # Signal evaluation
    # ------------------------------------------------------------------

    def evaluate_signal(self, signal: dict) -> list[StrategyResult]:
        """Evaluate a signal dict against all active strategies.

        For each strategy whose rules all match *and* whose open trade
        count is below the concurrency cap, a new ``StrategyResult``
        (open trade) is created and appended to ``_open_trades``.

        Only signals with a directional stance (``bullish`` or ``bearish``)
        produce trades.  Mixed and unknown stances are skipped.

        Args:
            signal: A signal dict (typically the row dict emitted by the
                pipeline, with keys like ``ticker``, ``stance``,
                ``confidence``, ``event_type``, ``market_data``, etc.).

        Returns:
            A list of newly opened ``StrategyResult`` trades (may be empty).
        """

        if not self._active_strategies:
            return []

        stance = signal.get("stance", "")
        if stance not in _TRADEABLE_STANCES:
            return []

        ticker = signal.get("ticker", "")
        if not ticker:
            return []

        entry_price = self._extract_entry_price(signal)
        if entry_price is None or entry_price <= 0:
            logger.debug(
                "No valid entry price for signal %s/%s — skipping",
                ticker,
                signal.get("id", "?"),
            )
            return []

        signal_id = signal.get("id", "")
        if not signal_id:
            logger.debug("Signal has no id — skipping")
            return []

        opened: list[StrategyResult] = []

        for strat_id, strategy in self._active_strategies.items():
            # Concurrency cap
            current_open = self._open_trades.get(strat_id, [])
            if len(current_open) >= self._max_concurrent:
                logger.debug(
                    "Strategy '%s' at max concurrent (%d) — skipping signal",
                    strategy.name,
                    self._max_concurrent,
                )
                continue

            # Per-strategy max_concurrent override from config
            strat_max = strategy.config.get("max_concurrent", self._max_concurrent)
            if len(current_open) >= strat_max:
                logger.debug(
                    "Strategy '%s' at config max_concurrent (%d) — skipping",
                    strategy.name,
                    strat_max,
                )
                continue

            # Rule evaluation (pre-compiled for speed)
            compiled = self._compiled_rules.get(strat_id, [])
            if not self._rule_engine.evaluate_compiled(signal, compiled):
                continue

            # All rules matched — open a trade
            trade = StrategyResult(
                id=uuid.uuid4().hex,
                strategy_id=strat_id,
                signal_id=signal_id,
                ticker=ticker,
                stance=stance,
                entry_price=entry_price,
                exit_price=None,
                pnl_pct=None,
                created_at=time.time(),
                resolved_at=None,
            )

            if strat_id not in self._open_trades:
                self._open_trades[strat_id] = []
            self._open_trades[strat_id].append(trade)
            opened.append(trade)

            logger.info(
                "Opened trade %s: strategy='%s', ticker=%s, stance=%s, entry=%.2f",
                trade.id,
                strategy.name,
                ticker,
                stance,
                entry_price,
            )

        return opened

    # ------------------------------------------------------------------
    # Trade resolution
    # ------------------------------------------------------------------

    def resolve_trades(
        self, price_data: dict[str, float]
    ) -> list[StrategyResult]:
        """Check open trades against current prices and close if triggered.

        For each open trade whose ticker appears in *price_data*, computes
        the unrealised P&L percentage.  If the P&L exceeds the strategy's
        ``take_profit_pct`` or falls below the negative ``stop_loss_pct``,
        the trade is closed and moved to ``_closed_trades``.

        P&L direction is stance-aware:

        * **Bullish**: ``pnl = (current - entry) / entry * 100``
        * **Bearish**: ``pnl = (entry - current) / entry * 100``

        Args:
            price_data: Mapping of ticker symbol to current price.

        Returns:
            A list of ``StrategyResult`` trades that were closed in this
            call (with ``exit_price``, ``pnl_pct``, and ``resolved_at``
            populated).
        """

        if not price_data:
            return []

        resolved: list[StrategyResult] = []

        for strat_id in list(self._open_trades.keys()):
            strategy = self._active_strategies.get(strat_id)
            stop_loss_pct = _DEFAULT_STOP_LOSS_PCT
            take_profit_pct = _DEFAULT_TAKE_PROFIT_PCT

            if strategy is not None:
                stop_loss_pct = strategy.config.get(
                    "stop_loss_pct", _DEFAULT_STOP_LOSS_PCT
                )
                take_profit_pct = strategy.config.get(
                    "take_profit_pct", _DEFAULT_TAKE_PROFIT_PCT
                )

            remaining: list[StrategyResult] = []

            for trade in self._open_trades.get(strat_id, []):
                current_price = price_data.get(trade.ticker)
                if current_price is None or current_price <= 0:
                    remaining.append(trade)
                    continue

                pnl_pct = self._compute_pnl_pct(
                    trade.stance, trade.entry_price, current_price
                )

                # Check stop-loss (loss exceeds threshold)
                if pnl_pct <= -stop_loss_pct:
                    closed_trade = self._close_trade(
                        trade, current_price, pnl_pct, "stop_loss"
                    )
                    resolved.append(closed_trade)
                    continue

                # Check take-profit (gain exceeds threshold)
                if pnl_pct >= take_profit_pct:
                    closed_trade = self._close_trade(
                        trade, current_price, pnl_pct, "take_profit"
                    )
                    resolved.append(closed_trade)
                    continue

                # Trade remains open
                remaining.append(trade)

            self._open_trades[strat_id] = remaining

        return resolved

    # ------------------------------------------------------------------
    # Performance analytics
    # ------------------------------------------------------------------

    def get_strategy_performance(self, strategy_id: str) -> dict:
        """Compute aggregate performance statistics for a strategy.

        Uses only closed trades.  Returns an empty-ish dict if no trades
        have been resolved yet.

        Args:
            strategy_id: The strategy to analyse.

        Returns:
            A dict with keys:

            - ``total_trades``: Number of closed trades.
            - ``winning_trades``: Trades with pnl_pct > 0.
            - ``losing_trades``: Trades with pnl_pct <= 0.
            - ``win_rate``: Fraction of winning trades (0.0 if no trades).
            - ``total_pnl_pct``: Sum of all pnl_pct values.
            - ``avg_pnl_pct``: Mean pnl_pct per trade.
            - ``max_gain_pct``: Best single trade P&L.
            - ``max_loss_pct``: Worst single trade P&L.
            - ``sharpe_ratio``: Annualised Sharpe ratio (None if < 5 trades).
            - ``open_trades``: Number of currently open trades.
        """

        trades = self._get_closed_for_strategy(strategy_id)
        open_count = len(self._open_trades.get(strategy_id, []))

        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl_pct": 0.0,
                "avg_pnl_pct": 0.0,
                "max_gain_pct": 0.0,
                "max_loss_pct": 0.0,
                "sharpe_ratio": None,
                "open_trades": open_count,
            }

        pnls = [t.pnl_pct for t in trades if t.pnl_pct is not None]
        if not pnls:
            return {
                "total_trades": len(trades),
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl_pct": 0.0,
                "avg_pnl_pct": 0.0,
                "max_gain_pct": 0.0,
                "max_loss_pct": 0.0,
                "sharpe_ratio": None,
                "open_trades": open_count,
            }

        winning = sum(1 for p in pnls if p > 0)
        losing = len(pnls) - winning
        total_pnl = sum(pnls)
        avg_pnl = total_pnl / len(pnls)

        sharpe = self._compute_sharpe(pnls)

        return {
            "total_trades": len(pnls),
            "winning_trades": winning,
            "losing_trades": losing,
            "win_rate": winning / len(pnls) if pnls else 0.0,
            "total_pnl_pct": round(total_pnl, 4),
            "avg_pnl_pct": round(avg_pnl, 4),
            "max_gain_pct": round(max(pnls), 4),
            "max_loss_pct": round(min(pnls), 4),
            "sharpe_ratio": sharpe,
            "open_trades": open_count,
        }

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(
        self, strategy_id: str, lookback_trades: int = 20
    ) -> dict:
        """Evaluate the rolling health of a strategy.

        Compares recent performance (last *lookback_trades* closed trades)
        against the strategy's stored ``performance`` baseline.  Produces
        a ``health_score`` in [0.0, 1.0] and an ``auto_disable``
        recommendation.

        Args:
            strategy_id: Strategy to check.
            lookback_trades: Number of recent trades to consider.

        Returns:
            A dict with:

            - ``strategy_id``
            - ``strategy_name``
            - ``health_score``: 1.0 = healthy, degrades with
              underperformance.
            - ``rolling_win_rate``: Win rate over last N trades.
            - ``rolling_avg_pnl``: Avg P&L over last N trades.
            - ``rolling_sharpe``: Sharpe from last N trades (or None).
            - ``baseline_win_rate``: The strategy's stored win rate.
            - ``total_closed_trades``: How many closed trades exist.
            - ``auto_disable``: ``True`` if health_score < 0.3.
            - ``reason``: Human-readable explanation.
        """

        strategy = self._active_strategies.get(strategy_id)
        strategy_name = strategy.name if strategy else "unknown"

        all_closed = self._get_closed_for_strategy(strategy_id)
        recent = all_closed[-lookback_trades:] if all_closed else []

        # Not enough data — report healthy by default
        if len(recent) < 3:
            return {
                "strategy_id": strategy_id,
                "strategy_name": strategy_name,
                "health_score": 1.0,
                "rolling_win_rate": None,
                "rolling_avg_pnl": None,
                "rolling_sharpe": None,
                "baseline_win_rate": self._get_baseline_win_rate(strategy),
                "total_closed_trades": len(all_closed),
                "auto_disable": False,
                "reason": "Insufficient trade history for health assessment",
            }

        recent_pnls = [
            t.pnl_pct for t in recent if t.pnl_pct is not None
        ]
        if not recent_pnls:
            return {
                "strategy_id": strategy_id,
                "strategy_name": strategy_name,
                "health_score": 1.0,
                "rolling_win_rate": None,
                "rolling_avg_pnl": None,
                "rolling_sharpe": None,
                "baseline_win_rate": self._get_baseline_win_rate(strategy),
                "total_closed_trades": len(all_closed),
                "auto_disable": False,
                "reason": "No P&L data in recent trades",
            }

        rolling_win_rate = sum(1 for p in recent_pnls if p > 0) / len(recent_pnls)
        rolling_avg_pnl = sum(recent_pnls) / len(recent_pnls)
        rolling_sharpe = self._compute_sharpe(recent_pnls)

        # Compute health score by comparing to baseline
        health_score = self._compute_health_score(
            strategy, rolling_win_rate, rolling_avg_pnl, rolling_sharpe
        )

        auto_disable = health_score < _HEALTH_AUTO_DISABLE_THRESHOLD
        reason = self._build_health_reason(
            health_score, rolling_win_rate, rolling_avg_pnl, auto_disable
        )

        return {
            "strategy_id": strategy_id,
            "strategy_name": strategy_name,
            "health_score": round(health_score, 4),
            "rolling_win_rate": round(rolling_win_rate, 4),
            "rolling_avg_pnl": round(rolling_avg_pnl, 4),
            "rolling_sharpe": rolling_sharpe,
            "baseline_win_rate": self._get_baseline_win_rate(strategy),
            "total_closed_trades": len(all_closed),
            "auto_disable": auto_disable,
            "reason": reason,
        }

    def health_check_all(self) -> dict[str, dict]:
        """Run :meth:`health_check` for every active strategy.

        Returns:
            A mapping of ``strategy_id`` to the health check result dict.
        """

        results: dict[str, dict] = {}
        for strat_id in self._active_strategies:
            results[strat_id] = self.health_check(strat_id)
        return results

    # ------------------------------------------------------------------
    # Trade accessors
    # ------------------------------------------------------------------

    def get_open_trades(
        self, strategy_id: str | None = None
    ) -> list[StrategyResult]:
        """Return currently open trades.

        Args:
            strategy_id: If provided, return only trades for this strategy.
                Otherwise return all open trades across all strategies.

        Returns:
            A list of open ``StrategyResult`` objects.
        """

        if strategy_id is not None:
            return list(self._open_trades.get(strategy_id, []))

        result: list[StrategyResult] = []
        for trades in self._open_trades.values():
            result.extend(trades)
        return result

    def get_closed_trades(
        self, strategy_id: str | None = None
    ) -> list[StrategyResult]:
        """Return closed (resolved) trades.

        Args:
            strategy_id: If provided, filter to this strategy only.

        Returns:
            A list of closed ``StrategyResult`` objects.
        """

        if strategy_id is not None:
            return self._get_closed_for_strategy(strategy_id)
        return list(self._closed_trades)

    # ------------------------------------------------------------------
    # Summary / stats
    # ------------------------------------------------------------------

    def get_summary(self) -> dict:
        """Return a high-level summary of the trader's state.

        Returns:
            A dict with ``active_strategies``, ``total_open_trades``,
            ``total_closed_trades``, and per-strategy open counts.
        """

        per_strategy: dict[str, int] = {}
        total_open = 0
        for strat_id, trades in self._open_trades.items():
            count = len(trades)
            per_strategy[strat_id] = count
            total_open += count

        return {
            "active_strategies": len(self._active_strategies),
            "total_open_trades": total_open,
            "total_closed_trades": len(self._closed_trades),
            "open_per_strategy": per_strategy,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_entry_price(signal: dict) -> float | None:
        """Extract the best available entry price from a signal dict.

        Priority:
        1. ``price_at_signal`` (direct field — set by performance tracker)
        2. ``market_data.last_close`` (from market enrichment JSON blob)
        3. ``market_data`` parsed as JSON string if needed

        Args:
            signal: The signal dict.

        Returns:
            A positive float, or ``None`` if no price can be determined.
        """

        # Direct field (most common in DB rows)
        price = signal.get("price_at_signal")
        if price is not None:
            try:
                price = float(price)
                if price > 0:
                    return price
            except (ValueError, TypeError):
                pass  # Intentionally suppressed

        # Nested market_data dict
        market_data = signal.get("market_data")
        if isinstance(market_data, dict):
            last_close = market_data.get("last_close")
            if last_close is not None:
                try:
                    return float(last_close)
                except (ValueError, TypeError):
                    pass  # Intentionally suppressed

        # market_data as JSON string (some callers may not pre-parse)
        if isinstance(market_data, str):
            try:
                import json

                parsed = json.loads(market_data)
                if isinstance(parsed, dict):
                    last_close = parsed.get("last_close")
                    if last_close is not None:
                        return float(last_close)
            except (ValueError, TypeError):
                pass  # Intentionally suppressed

        return None

    @staticmethod
    def _compute_pnl_pct(
        stance: str, entry_price: float, current_price: float
    ) -> float:
        """Compute P&L percentage based on stance.

        Args:
            stance: ``"bullish"`` or ``"bearish"``.
            entry_price: Trade entry price.
            current_price: Current market price.

        Returns:
            P&L as a percentage (e.g. 5.0 means +5%).
        """

        if entry_price <= 0:
            return 0.0

        if stance == "bullish":
            return (current_price - entry_price) / entry_price * 100.0
        else:
            # Bearish: profit when price drops
            return (entry_price - current_price) / entry_price * 100.0

    def _close_trade(
        self,
        trade: StrategyResult,
        exit_price: float,
        pnl_pct: float,
        reason: str,
    ) -> StrategyResult:
        """Create a closed copy of an open trade and record it.

        Since ``StrategyResult`` is frozen, we create a new instance with
        the exit fields populated.

        Args:
            trade: The open trade to close.
            exit_price: The closing price.
            pnl_pct: Realised P&L percentage.
            reason: Why the trade was closed (``"stop_loss"`` or
                ``"take_profit"``).

        Returns:
            The closed ``StrategyResult``.
        """

        closed = StrategyResult(
            id=trade.id,
            strategy_id=trade.strategy_id,
            signal_id=trade.signal_id,
            ticker=trade.ticker,
            stance=trade.stance,
            entry_price=trade.entry_price,
            exit_price=exit_price,
            pnl_pct=round(pnl_pct, 4),
            created_at=trade.created_at,
            resolved_at=time.time(),
        )

        self._closed_trades.append(closed)

        strategy = self._active_strategies.get(trade.strategy_id)
        strategy_name = strategy.name if strategy else trade.strategy_id

        logger.info(
            "Closed trade %s (%s): strategy='%s', ticker=%s, "
            "entry=%.2f, exit=%.2f, pnl=%.2f%%, reason=%s",
            trade.id,
            trade.stance,
            strategy_name,
            trade.ticker,
            trade.entry_price,
            exit_price,
            pnl_pct,
            reason,
        )

        return closed

    def _get_closed_for_strategy(
        self, strategy_id: str
    ) -> list[StrategyResult]:
        """Return closed trades filtered to a single strategy.

        Args:
            strategy_id: The strategy to filter by.

        Returns:
            A list of closed ``StrategyResult`` for this strategy, in
            chronological order.
        """

        return [
            t for t in self._closed_trades if t.strategy_id == strategy_id
        ]

    @staticmethod
    def _compute_sharpe(pnls: list[float]) -> float | None:
        """Compute annualised Sharpe ratio from a list of trade P&L values.

        Uses zero as the risk-free rate (standard for short-horizon
        trading).  Returns ``None`` if fewer than ``_MIN_TRADES_FOR_SHARPE``
        trades or if standard deviation is zero.

        Args:
            pnls: List of per-trade P&L percentages.

        Returns:
            Annualised Sharpe ratio, or ``None``.
        """

        if len(pnls) < _MIN_TRADES_FOR_SHARPE:
            return None

        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return None

        sharpe = (mean_pnl / std_dev) * _ANNUALISATION_FACTOR
        return round(sharpe, 4)

    @staticmethod
    def _get_baseline_win_rate(strategy: Strategy | None) -> float | None:
        """Extract baseline win rate from a strategy's stored performance.

        Args:
            strategy: The strategy object (or ``None``).

        Returns:
            Win rate as a float, or ``None`` if unavailable.
        """

        if strategy is None:
            return None

        perf = strategy.performance
        if not perf:
            return None

        win_rate = perf.get("win_rate")
        if win_rate is not None:
            try:
                return float(win_rate)
            except (ValueError, TypeError):
                pass  # Intentionally suppressed

        return None

    def _compute_health_score(
        self,
        strategy: Strategy | None,
        rolling_win_rate: float,
        rolling_avg_pnl: float,
        rolling_sharpe: float | None,
    ) -> float:
        """Compute a 0.0-1.0 health score for a strategy.

        The score starts at 1.0 and is degraded by several factors:

        1. **Win rate penalty**: if rolling win rate < 40%, subtract up to
           0.3 proportionally.
        2. **Negative avg P&L penalty**: if avg P&L is negative, subtract
           up to 0.3 based on severity.
        3. **Baseline comparison**: if the strategy has a stored win rate
           and the rolling rate is significantly worse, subtract up to 0.2.
        4. **Sharpe penalty**: if rolling Sharpe is negative, subtract up
           to 0.2.

        Args:
            strategy: The strategy (for baseline comparison).
            rolling_win_rate: Recent win rate (0.0-1.0).
            rolling_avg_pnl: Recent average P&L percentage.
            rolling_sharpe: Recent Sharpe ratio (or None).

        Returns:
            Health score clamped to [0.0, 1.0].
        """

        score = 1.0

        # 1. Win rate penalty
        if rolling_win_rate < 0.40:
            # Linear degradation: 0% win rate -> -0.3, 40% -> 0
            penalty = (0.40 - rolling_win_rate) / 0.40 * 0.3
            score -= penalty

        # 2. Negative avg P&L penalty
        if rolling_avg_pnl < 0:
            # -10% avg pnl -> -0.3 penalty (capped)
            penalty = min(abs(rolling_avg_pnl) / 10.0 * 0.3, 0.3)
            score -= penalty

        # 3. Baseline comparison
        baseline_wr = self._get_baseline_win_rate(strategy)
        if baseline_wr is not None and baseline_wr > 0:
            degradation = baseline_wr - rolling_win_rate
            if degradation > 0.10:
                # Significant underperformance vs baseline
                penalty = min(degradation / 0.30 * 0.2, 0.2)
                score -= penalty

        # 4. Sharpe penalty
        if rolling_sharpe is not None and rolling_sharpe < 0:
            penalty = min(abs(rolling_sharpe) / 2.0 * 0.2, 0.2)
            score -= penalty

        return max(0.0, min(1.0, score))

    @staticmethod
    def _build_health_reason(
        health_score: float,
        rolling_win_rate: float,
        rolling_avg_pnl: float,
        auto_disable: bool,
    ) -> str:
        """Build a human-readable reason string for a health check.

        Args:
            health_score: Computed health score.
            rolling_win_rate: Recent win rate.
            rolling_avg_pnl: Recent average P&L.
            auto_disable: Whether auto-disable is recommended.

        Returns:
            A descriptive string.
        """

        parts: list[str] = []

        if health_score >= 0.8:
            parts.append("Strategy is performing well")
        elif health_score >= 0.5:
            parts.append("Strategy showing moderate performance")
        elif health_score >= 0.3:
            parts.append("Strategy underperforming — review recommended")
        else:
            parts.append("Strategy severely underperforming")

        parts.append(
            f"(win_rate={rolling_win_rate:.1%}, avg_pnl={rolling_avg_pnl:+.2f}%)"
        )

        if auto_disable:
            parts.append("— auto-disable recommended")

        return " ".join(parts)
