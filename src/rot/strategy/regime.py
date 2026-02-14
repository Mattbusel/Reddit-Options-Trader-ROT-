"""Market regime detection and strategy-regime performance mapping.

Classifies the current market environment into one of five regimes
(bull, bear, sideways, volatile, crisis) based on recent signal data,
then maps strategy performance to each regime so the system can
recommend which strategies work best under current conditions.

Indicators are derived entirely from signal metadata -- no external
market data feeds are required.  This keeps the module zero-dependency
and testable with synthetic signal dicts.
"""

from __future__ import annotations

import logging
import math
import statistics
import time
from uuid import uuid4

from rot.strategy.types import MarketRegime, RegimeStrategy, REGIME_TYPES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECONDS_PER_DAY: float = 86_400.0

# Thresholds for regime classification
_CRISIS_VELOCITY_MULTIPLIER: float = 3.0
_CRISIS_VOLATILITY_THRESHOLD: float = 0.8
_VOLATILE_VOLATILITY_THRESHOLD: float = 0.6
_BULL_RATIO_THRESHOLD: float = 0.65
_BEAR_RATIO_THRESHOLD: float = 0.35

# Minimum signals required for meaningful classification
_MIN_SIGNALS_FOR_DETECTION: int = 5

# Regime matrix recommendation thresholds
_RECOMMEND_WIN_RATE: float = 0.55
_RECOMMEND_MIN_TRADES: int = 5

# Walk-forward step size for regime history (fraction of window)
_HISTORY_STEP_FRACTION: float = 0.25

# Annualization factor for Sharpe ratio (approximate trading days)
_ANNUALIZATION_FACTOR: float = 252.0


# ---------------------------------------------------------------------------
# Helper: numeric stance conversion
# ---------------------------------------------------------------------------

def _stance_to_numeric(stance: str) -> float:
    """Convert a stance string to a numeric value for statistical analysis.

    Args:
        stance: Signal stance string (bullish, bearish, mixed, unknown).

    Returns:
        Numeric mapping: bullish=1.0, bearish=-1.0, mixed/unknown=0.0.
    """
    if stance == "bullish":
        return 1.0
    if stance == "bearish":
        return -1.0
    return 0.0


def _safe_stdev(values: list[float]) -> float:
    """Compute standard deviation, returning 0.0 for fewer than 2 values.

    Args:
        values: List of numeric values.

    Returns:
        Standard deviation, or 0.0 if the list has fewer than 2 elements.
    """
    if len(values) < 2:
        return 0.0
    try:
        return statistics.stdev(values)
    except (statistics.StatisticsError, ValueError):
        return 0.0


def _safe_mean(values: list[float]) -> float:
    """Compute mean, returning 0.0 for empty lists.

    Args:
        values: List of numeric values.

    Returns:
        Arithmetic mean, or 0.0 if the list is empty.
    """
    if not values:
        return 0.0
    return statistics.mean(values)


def _compute_sharpe(pnl_values: list[float]) -> float:
    """Compute an annualized Sharpe ratio from a list of per-trade P&L pcts.

    Uses zero as the risk-free rate (standard for short-horizon trading).

    Args:
        pnl_values: List of per-trade P&L percentages.

    Returns:
        Annualized Sharpe ratio, or 0.0 if insufficient data.
    """
    if len(pnl_values) < 2:
        return 0.0
    mean_ret = _safe_mean(pnl_values)
    std_ret = _safe_stdev(pnl_values)
    if std_ret == 0.0:
        return 0.0
    # Annualise assuming each trade is roughly daily
    return (mean_ret / std_ret) * math.sqrt(_ANNUALIZATION_FACTOR)


# ---------------------------------------------------------------------------
# RegimeDetector
# ---------------------------------------------------------------------------

class RegimeDetector:
    """Detects market regimes from signal data and maps strategy performance.

    The detector analyses signal metadata (stance, confidence, trend score,
    sector) to classify the market environment without requiring any external
    data feeds.  All computation is pure Python with no external dependencies.

    Args:
        window_days: Number of days of signal history to consider for
            regime detection.  Defaults to 30.
    """

    def __init__(self, window_days: int = 30) -> None:
        if window_days < 1:
            raise ValueError("window_days must be >= 1")
        self.window_days = window_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_regime(self, signals: list[dict]) -> MarketRegime:
        """Classify the current market regime from recent signal data.

        Analyses signals within ``self.window_days`` of the most recent
        signal timestamp and computes six indicators:

        * ``bullish_ratio`` -- fraction of directional signals that are
          bullish.
        * ``avg_confidence`` -- mean confidence across all signals in
          the window.
        * ``signal_velocity`` -- signals per day (volume indicator).
        * ``avg_trend_score`` -- mean trend score.
        * ``stance_volatility`` -- standard deviation of the numeric
          stance series.
        * ``sector_diversity`` -- number of distinct sectors observed.

        Classification priority (first match wins):

        1. **crisis** -- velocity > 3x normal AND stance volatility > 0.8
        2. **volatile** -- stance volatility > 0.6
        3. **bull** -- bullish ratio > 0.65
        4. **bear** -- bullish ratio < 0.35
        5. **sideways** -- everything else

        Args:
            signals: List of signal dicts.  Each dict should contain at
                least ``created_at`` (float), ``stance`` (str), ``confidence``
                (float).  ``trend_score``, ``sector``, and ``quality_score``
                are used when present.

        Returns:
            A :class:`MarketRegime` representing the detected regime.
            If fewer than ``_MIN_SIGNALS_FOR_DETECTION`` signals fall
            within the window the regime defaults to ``sideways`` with
            low confidence.
        """
        now = time.time()
        window_start = now - (self.window_days * _SECONDS_PER_DAY)

        recent = self._filter_window(signals, window_start, now)

        if len(recent) < _MIN_SIGNALS_FOR_DETECTION:
            logger.debug(
                "Insufficient signals for regime detection (%d < %d)",
                len(recent),
                _MIN_SIGNALS_FOR_DETECTION,
            )
            return self._make_regime(
                regime_type="sideways",
                start_ts=window_start,
                end_ts=None,
                indicators={
                    "bullish_ratio": 0.5,
                    "avg_confidence": 0.0,
                    "signal_velocity": 0.0,
                    "avg_trend_score": 0.0,
                    "stance_volatility": 0.0,
                    "sector_diversity": 0,
                    "signal_count": len(recent),
                },
                confidence=0.1,
            )

        indicators = self._compute_indicators(recent, window_start, now)
        normal_velocity = self._compute_normal_velocity(signals)
        regime_type, confidence = self._classify(indicators, normal_velocity)

        return self._make_regime(
            regime_type=regime_type,
            start_ts=window_start,
            end_ts=None,
            indicators=indicators,
            confidence=confidence,
        )

    def detect_regime_history(
        self,
        signals: list[dict],
        window_days: int | None = None,
    ) -> list[MarketRegime]:
        """Detect regime changes over the full signal history.

        Slides a window of ``window_days`` (defaults to ``self.window_days``)
        through the sorted signal list and emits a new :class:`MarketRegime`
        whenever the classification changes.  Adjacent windows with the same
        regime type are merged into a single period.

        Args:
            signals: Full signal history (unsorted is fine).
            window_days: Override window size for the sliding analysis.
                Defaults to ``self.window_days``.

        Returns:
            List of :class:`MarketRegime` ordered chronologically.  Each
            has ``start_ts`` and ``end_ts`` filled in (the final entry may
            have ``end_ts = None`` indicating an ongoing regime).
        """
        if not signals:
            return []

        win = window_days if window_days is not None else self.window_days
        window_s = win * _SECONDS_PER_DAY
        step_s = max(window_s * _HISTORY_STEP_FRACTION, _SECONDS_PER_DAY)

        sorted_signals = sorted(signals, key=lambda s: s.get("created_at", 0.0))
        earliest = sorted_signals[0].get("created_at", 0.0)
        latest = sorted_signals[-1].get("created_at", 0.0)

        if latest - earliest < window_s:
            # Not enough history to slide; detect a single regime
            indicators = self._compute_indicators(sorted_signals, earliest, latest)
            normal_velocity = self._compute_normal_velocity(sorted_signals)
            rtype, conf = self._classify(indicators, normal_velocity)
            return [
                self._make_regime(
                    regime_type=rtype,
                    start_ts=earliest,
                    end_ts=None,
                    indicators=indicators,
                    confidence=conf,
                )
            ]

        normal_velocity = self._compute_normal_velocity(sorted_signals)

        # Slide through time
        raw_regimes: list[tuple[str, float, float, dict, float]] = []
        cursor = earliest
        while cursor + window_s <= latest + step_s:
            w_start = cursor
            w_end = cursor + window_s
            window_signals = self._filter_window(sorted_signals, w_start, w_end)

            if len(window_signals) >= _MIN_SIGNALS_FOR_DETECTION:
                indicators = self._compute_indicators(window_signals, w_start, w_end)
                rtype, conf = self._classify(indicators, normal_velocity)
            else:
                rtype = "sideways"
                conf = 0.1
                indicators = {}

            raw_regimes.append((rtype, w_start, w_end, indicators, conf))
            cursor += step_s

        # Merge adjacent windows with the same regime type
        merged = self._merge_regimes(raw_regimes)
        return merged

    def build_regime_matrix(
        self,
        strategies: list[dict],
        trades: list[dict],
        regimes: list[MarketRegime],
    ) -> list[RegimeStrategy]:
        """Build a performance matrix mapping strategies to regimes.

        For every (strategy, regime) combination, finds trades that
        occurred during the regime period, computes performance metrics,
        and marks the combination as recommended when the win rate
        exceeds the threshold with sufficient trade count.

        Args:
            strategies: List of strategy dicts, each with at least an
                ``"id"`` key.
            trades: List of trade dicts with ``"strategy_id"``,
                ``"created_at"``, ``"pnl_pct"`` keys.
            regimes: List of :class:`MarketRegime` periods (from
                :meth:`detect_regime_history`).

        Returns:
            List of :class:`RegimeStrategy` objects.
        """
        if not strategies or not trades or not regimes:
            return []

        # Index trades by strategy_id for fast lookup
        trades_by_strategy: dict[str, list[dict]] = {}
        for trade in trades:
            sid = trade.get("strategy_id", "")
            if sid:
                trades_by_strategy.setdefault(sid, []).append(trade)

        results: list[RegimeStrategy] = []

        for strategy in strategies:
            strategy_id = strategy.get("id", "")
            if not strategy_id:
                continue

            strategy_trades = trades_by_strategy.get(strategy_id, [])
            if not strategy_trades:
                # Emit empty entries for each regime type so callers
                # always get a complete matrix.
                for regime in regimes:
                    results.append(
                        RegimeStrategy(
                            strategy_id=strategy_id,
                            regime_type=regime.regime_type,
                            win_rate=0.0,
                            sharpe=0.0,
                            total_trades=0,
                            avg_pnl_pct=0.0,
                            recommended=False,
                        )
                    )
                continue

            for regime in regimes:
                regime_trades = self._trades_in_regime(strategy_trades, regime)
                rs = self._compute_regime_strategy(
                    strategy_id, regime.regime_type, regime_trades
                )
                results.append(rs)

        return results

    def get_regime_recommendation(
        self,
        current_regime: MarketRegime,
        matrix: list[RegimeStrategy],
    ) -> list[str]:
        """Return recommended strategy IDs for the current regime.

        Filters the matrix for entries matching the current regime that
        are marked as ``recommended``, then sorts by Sharpe ratio in
        descending order.

        Args:
            current_regime: The current :class:`MarketRegime`.
            matrix: Full regime-strategy matrix from
                :meth:`build_regime_matrix`.

        Returns:
            List of strategy ID strings, best-first.
        """
        matching = [
            rs
            for rs in matrix
            if rs.regime_type == current_regime.regime_type and rs.recommended
        ]
        matching.sort(key=lambda rs: rs.sharpe, reverse=True)
        return [rs.strategy_id for rs in matching]

    # ------------------------------------------------------------------
    # Internal: indicator computation
    # ------------------------------------------------------------------

    def _compute_indicators(
        self,
        signals: list[dict],
        window_start: float,
        window_end: float,
    ) -> dict:
        """Compute the six regime indicators from a set of signals.

        Args:
            signals: Signals already filtered to the window.
            window_start: Start of the time window (unix ts).
            window_end: End of the time window (unix ts).

        Returns:
            Dict with keys: ``bullish_ratio``, ``avg_confidence``,
            ``signal_velocity``, ``avg_trend_score``, ``stance_volatility``,
            ``sector_diversity``, ``signal_count``.
        """
        n = len(signals)

        # Stance counts (directional only)
        bullish_count = 0
        bearish_count = 0
        stance_numeric: list[float] = []
        confidences: list[float] = []
        trend_scores: list[float] = []
        sectors: set[str] = set()

        for sig in signals:
            stance = sig.get("stance", "unknown")
            stance_val = _stance_to_numeric(stance)
            stance_numeric.append(stance_val)

            if stance == "bullish":
                bullish_count += 1
            elif stance == "bearish":
                bearish_count += 1

            conf = sig.get("confidence", 0.0)
            if isinstance(conf, (int, float)):
                confidences.append(float(conf))

            ts_val = sig.get("trend_score", 0.0)
            if isinstance(ts_val, (int, float)):
                trend_scores.append(float(ts_val))

            sector = sig.get("sector", "")
            if sector:
                sectors.add(sector)

        # Bullish ratio: only among directional signals
        directional = bullish_count + bearish_count
        if directional > 0:
            bullish_ratio = bullish_count / directional
        else:
            bullish_ratio = 0.5  # neutral when no directional signals

        # Signal velocity: signals per day
        window_days = max((window_end - window_start) / _SECONDS_PER_DAY, 1.0)
        signal_velocity = n / window_days

        return {
            "bullish_ratio": round(bullish_ratio, 4),
            "avg_confidence": round(_safe_mean(confidences), 4),
            "signal_velocity": round(signal_velocity, 4),
            "avg_trend_score": round(_safe_mean(trend_scores), 4),
            "stance_volatility": round(_safe_stdev(stance_numeric), 4),
            "sector_diversity": len(sectors),
            "signal_count": n,
        }

    def _compute_normal_velocity(self, signals: list[dict]) -> float:
        """Compute baseline signals-per-day from the full signal history.

        The baseline is the total signal count divided by the number of
        calendar days spanned by the data.  If fewer than two signals
        exist, returns 1.0 as a safe default.

        Args:
            signals: Full signal list (not just the current window).

        Returns:
            Baseline signals per day.
        """
        if len(signals) < 2:
            return 1.0

        timestamps = [
            s.get("created_at", 0.0)
            for s in signals
            if isinstance(s.get("created_at"), (int, float))
        ]
        if len(timestamps) < 2:
            return 1.0

        span_s = max(timestamps) - min(timestamps)
        if span_s <= 0:
            return 1.0

        span_days = span_s / _SECONDS_PER_DAY
        return len(timestamps) / max(span_days, 1.0)

    # ------------------------------------------------------------------
    # Internal: classification
    # ------------------------------------------------------------------

    def _classify(
        self,
        indicators: dict,
        normal_velocity: float,
    ) -> tuple[str, float]:
        """Classify indicators into a regime type with confidence.

        Classification priority (first match wins):

        1. crisis -- velocity > 3x normal AND stance_volatility > 0.8
        2. volatile -- stance_volatility > 0.6
        3. bull -- bullish_ratio > 0.65
        4. bear -- bullish_ratio < 0.35
        5. sideways -- default

        Confidence is computed based on how strongly the indicators
        point toward the selected regime.

        Args:
            indicators: Dict produced by :meth:`_compute_indicators`.
            normal_velocity: Baseline signals/day from full history.

        Returns:
            Tuple of (regime_type, confidence).
        """
        velocity = indicators.get("signal_velocity", 0.0)
        vol = indicators.get("stance_volatility", 0.0)
        br = indicators.get("bullish_ratio", 0.5)
        signal_count = indicators.get("signal_count", 0)

        # Base confidence scales with signal count
        base_confidence = min(signal_count / 50.0, 1.0)

        safe_normal = max(normal_velocity, 0.1)

        # 1. Crisis: extreme velocity + high stance disagreement
        velocity_ratio = velocity / safe_normal
        if (
            velocity_ratio > _CRISIS_VELOCITY_MULTIPLIER
            and vol > _CRISIS_VOLATILITY_THRESHOLD
        ):
            # Confidence increases with how extreme the readings are
            crisis_strength = min(
                (velocity_ratio / _CRISIS_VELOCITY_MULTIPLIER - 1.0) * 0.5
                + (vol - _CRISIS_VOLATILITY_THRESHOLD) * 2.0,
                1.0,
            )
            confidence = max(0.4, base_confidence * (0.6 + 0.4 * crisis_strength))
            return "crisis", round(min(confidence, 1.0), 4)

        # 2. Volatile: high stance disagreement
        if vol > _VOLATILE_VOLATILITY_THRESHOLD:
            vol_strength = min(
                (vol - _VOLATILE_VOLATILITY_THRESHOLD)
                / (_CRISIS_VOLATILITY_THRESHOLD - _VOLATILE_VOLATILITY_THRESHOLD),
                1.0,
            )
            confidence = max(0.3, base_confidence * (0.5 + 0.5 * vol_strength))
            return "volatile", round(min(confidence, 1.0), 4)

        # 3. Bull: dominant bullish signals
        if br > _BULL_RATIO_THRESHOLD:
            bull_strength = min(
                (br - _BULL_RATIO_THRESHOLD) / (1.0 - _BULL_RATIO_THRESHOLD),
                1.0,
            )
            confidence = max(0.3, base_confidence * (0.5 + 0.5 * bull_strength))
            return "bull", round(min(confidence, 1.0), 4)

        # 4. Bear: dominant bearish signals
        if br < _BEAR_RATIO_THRESHOLD:
            bear_strength = min(
                (_BEAR_RATIO_THRESHOLD - br) / _BEAR_RATIO_THRESHOLD,
                1.0,
            )
            confidence = max(0.3, base_confidence * (0.5 + 0.5 * bear_strength))
            return "bear", round(min(confidence, 1.0), 4)

        # 5. Sideways: default -- confidence is how close to 0.5 the ratio is
        sideways_strength = 1.0 - abs(br - 0.5) * 4.0  # peaks at br=0.5
        sideways_strength = max(sideways_strength, 0.0)
        confidence = max(0.2, base_confidence * (0.4 + 0.6 * sideways_strength))
        return "sideways", round(min(confidence, 1.0), 4)

    # ------------------------------------------------------------------
    # Internal: regime matrix helpers
    # ------------------------------------------------------------------

    def _trades_in_regime(
        self,
        trades: list[dict],
        regime: MarketRegime,
    ) -> list[dict]:
        """Filter trades that occurred during a regime period.

        A trade is considered part of a regime if its ``created_at``
        timestamp falls within ``[regime.start_ts, regime.end_ts]``.
        If the regime has no ``end_ts`` (ongoing), any trade after
        ``start_ts`` qualifies.

        Args:
            trades: List of trade dicts with ``"created_at"`` key.
            regime: The :class:`MarketRegime` to filter against.

        Returns:
            Filtered list of trade dicts.
        """
        result: list[dict] = []
        for trade in trades:
            ts = trade.get("created_at", 0.0)
            if not isinstance(ts, (int, float)):
                continue
            if ts < regime.start_ts:
                continue
            if regime.end_ts is not None and ts > regime.end_ts:
                continue
            result.append(trade)
        return result

    def _compute_regime_strategy(
        self,
        strategy_id: str,
        regime_type: str,
        trades: list[dict],
    ) -> RegimeStrategy:
        """Compute performance metrics for a strategy within a regime.

        Args:
            strategy_id: The strategy identifier.
            regime_type: The regime type string.
            trades: Trades that fell within this regime period.

        Returns:
            A :class:`RegimeStrategy` with computed metrics.
        """
        if not trades:
            return RegimeStrategy(
                strategy_id=strategy_id,
                regime_type=regime_type,
                win_rate=0.0,
                sharpe=0.0,
                total_trades=0,
                avg_pnl_pct=0.0,
                recommended=False,
            )

        pnl_values: list[float] = []
        wins = 0
        resolved = 0

        for trade in trades:
            pnl = trade.get("pnl_pct")
            if pnl is not None and isinstance(pnl, (int, float)):
                pnl_values.append(float(pnl))
                resolved += 1
                if pnl > 0:
                    wins += 1

        total_trades = len(trades)
        win_rate = wins / resolved if resolved > 0 else 0.0
        avg_pnl = _safe_mean(pnl_values)
        sharpe = _compute_sharpe(pnl_values)

        recommended = (
            win_rate > _RECOMMEND_WIN_RATE
            and total_trades >= _RECOMMEND_MIN_TRADES
        )

        return RegimeStrategy(
            strategy_id=strategy_id,
            regime_type=regime_type,
            win_rate=round(win_rate, 4),
            sharpe=round(sharpe, 4),
            total_trades=total_trades,
            avg_pnl_pct=round(avg_pnl, 4),
            recommended=recommended,
        )

    # ------------------------------------------------------------------
    # Internal: signal filtering and merging
    # ------------------------------------------------------------------

    def _filter_window(
        self,
        signals: list[dict],
        start_ts: float,
        end_ts: float,
    ) -> list[dict]:
        """Filter signals to those within [start_ts, end_ts].

        Args:
            signals: List of signal dicts.
            start_ts: Window start (inclusive).
            end_ts: Window end (inclusive).

        Returns:
            Filtered list.
        """
        result: list[dict] = []
        for sig in signals:
            ts = sig.get("created_at", 0.0)
            if isinstance(ts, (int, float)) and start_ts <= ts <= end_ts:
                result.append(sig)
        return result

    def _merge_regimes(
        self,
        raw: list[tuple[str, float, float, dict, float]],
    ) -> list[MarketRegime]:
        """Merge adjacent raw regime windows with the same type.

        Adjacent windows sharing the same regime type are collapsed
        into a single :class:`MarketRegime` with the start of the first
        and end of the last window.  Confidence and indicators are taken
        from the window with the highest confidence.

        Args:
            raw: List of (regime_type, start_ts, end_ts, indicators,
                confidence) tuples, in chronological order.

        Returns:
            Merged list of :class:`MarketRegime`.
        """
        if not raw:
            return []

        merged: list[MarketRegime] = []
        current_type, current_start, current_end, current_ind, current_conf = raw[0]

        for i in range(1, len(raw)):
            rtype, rstart, rend, rind, rconf = raw[i]

            if rtype == current_type:
                # Extend the current regime period
                current_end = rend
                # Keep the higher-confidence indicators
                if rconf > current_conf:
                    current_ind = rind
                    current_conf = rconf
            else:
                # Emit the completed regime and start a new one
                merged.append(
                    self._make_regime(
                        regime_type=current_type,
                        start_ts=current_start,
                        end_ts=current_end,
                        indicators=current_ind,
                        confidence=current_conf,
                    )
                )
                current_type = rtype
                current_start = rstart
                current_end = rend
                current_ind = rind
                current_conf = rconf

        # Emit the final regime (ongoing -- no end_ts)
        merged.append(
            self._make_regime(
                regime_type=current_type,
                start_ts=current_start,
                end_ts=None,
                indicators=current_ind,
                confidence=current_conf,
            )
        )

        return merged

    # ------------------------------------------------------------------
    # Internal: factory
    # ------------------------------------------------------------------

    @staticmethod
    def _make_regime(
        regime_type: str,
        start_ts: float,
        end_ts: float | None,
        indicators: dict,
        confidence: float,
    ) -> MarketRegime:
        """Create a MarketRegime with a fresh UUID.

        Args:
            regime_type: One of REGIME_TYPES.
            start_ts: Period start timestamp.
            end_ts: Period end timestamp (None = ongoing).
            indicators: Indicator values dict.
            confidence: Detection confidence 0.0-1.0.

        Returns:
            New :class:`MarketRegime` instance.
        """
        return MarketRegime(
            id=str(uuid4()),
            regime_type=regime_type,
            start_ts=start_ts,
            end_ts=end_ts,
            indicators=indicators,
            confidence=min(max(confidence, 0.0), 1.0),
        )
