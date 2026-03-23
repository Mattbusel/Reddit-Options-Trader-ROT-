"""Multi-Timeframe Signal Aggregation.

Collects signals from multiple timeframes (1m, 5m, 15m, 1h, 4h, 1d)
for the same ticker and computes a composite score that rewards alignment
across timeframes.  When all timeframes agree on direction the score
receives a bonus multiplier; when they diverge the score is penalised.

Typical usage::

    agg = TimeframeAggregator()
    agg.add(TimeframeSignal(ticker="AAPL", timeframe="1h",
                            signal="bullish", confidence=0.75,
                            timestamp=time.time()))
    agg.add(TimeframeSignal(ticker="AAPL", timeframe="4h",
                            signal="bullish", confidence=0.80,
                            timestamp=time.time()))
    agg.add(TimeframeSignal(ticker="AAPL", timeframe="1d",
                            signal="bullish", confidence=0.70,
                            timestamp=time.time()))
    result = agg.composite_score("AAPL")
    # result.score  ─ e.g. 0.85 (boosted for full alignment)
    # result.alignment  ─ TimeframeAlignment.FULL_ALIGN
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── Timeframe weight schema ───────────────────────────────

TIMEFRAME_WEIGHTS: dict[str, float] = {
    "1m": 0.05,
    "5m": 0.10,
    "15m": 0.15,
    "1h": 0.25,
    "4h": 0.20,
    "1d": 0.25,
}

# Bonus multiplier applied to composite score when all timeframes align
_FULL_ALIGN_BONUS = 1.20

# Partial alignment: more than half but not all agree
_PARTIAL_ALIGN_BONUS = 1.05

# Penalty multiplier when timeframes diverge
_DIVERGENT_PENALTY = 0.80

# Minimum fraction of weighted signals that must agree on the dominant
# direction to be called "partially aligned"
_PARTIAL_ALIGN_THRESHOLD = 0.60

# Maximum age (seconds) for a signal to be included in aggregation
_DEFAULT_MAX_AGE_S = 4 * 3600  # 4 hours


# ── Enums ─────────────────────────────────────────────────


class TimeframeAlignment(Enum):
    """Describes how well signals across timeframes agree.

    FULL_ALIGN
        >= 90% of weighted signals point in the same direction.
    PARTIAL_ALIGN
        >= 60% of weighted signals point in the same direction.
    DIVERGENT
        < 60% agreement — signals contradict across timeframes.
    """

    FULL_ALIGN = "full_align"
    PARTIAL_ALIGN = "partial_align"
    DIVERGENT = "divergent"


# ── Data Classes ──────────────────────────────────────────


@dataclass(frozen=True)
class TimeframeSignal:
    """A single directional signal observed at a specific timeframe.

    Attributes:
        ticker: Ticker symbol (e.g. ``"AAPL"``).
        timeframe: One of ``"1m"``, ``"5m"``, ``"15m"``, ``"1h"``, ``"4h"``, ``"1d"``.
        signal: Direction — ``"bullish"``, ``"bearish"``, or ``"neutral"``.
        confidence: Signal strength in [0.0, 1.0].
        timestamp: Unix timestamp when the signal was generated.
        source: Optional label identifying the signal source.
    """

    ticker: str
    timeframe: str
    signal: str
    confidence: float
    timestamp: float
    source: str = ""

    def __post_init__(self) -> None:
        if self.timeframe not in TIMEFRAME_WEIGHTS:
            raise ValueError(
                f"timeframe must be one of {list(TIMEFRAME_WEIGHTS)}, "
                f"got '{self.timeframe}'"
            )
        if self.signal not in ("bullish", "bearish", "neutral"):
            raise ValueError(
                f"signal must be 'bullish', 'bearish', or 'neutral', got '{self.signal}'"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "ticker": self.ticker,
            "timeframe": self.timeframe,
            "signal": self.signal,
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp,
            "source": self.source,
        }


@dataclass(frozen=True)
class CompositeResult:
    """Output of ``TimeframeAggregator.composite_score()``.

    Attributes:
        ticker: Ticker that was analysed.
        score: Composite score in [0.0, 1.0] after alignment adjustment.
        raw_score: Weighted-average score before alignment multiplier.
        dominant_signal: The direction that commanded the highest weight sum.
        alignment: How well timeframes agree (``TimeframeAlignment``).
        contributing_timeframes: Timeframes that contributed to this score.
        signal_count: Total number of signals included.
        computed_at: Unix timestamp.
    """

    ticker: str
    score: float
    raw_score: float
    dominant_signal: str
    alignment: TimeframeAlignment
    contributing_timeframes: list[str]
    signal_count: int
    computed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "ticker": self.ticker,
            "score": round(self.score, 4),
            "raw_score": round(self.raw_score, 4),
            "dominant_signal": self.dominant_signal,
            "alignment": self.alignment.value,
            "contributing_timeframes": self.contributing_timeframes,
            "signal_count": self.signal_count,
            "computed_at": self.computed_at,
        }


# ── Aggregator ────────────────────────────────────────────


class TimeframeAggregator:
    """Collects multi-timeframe signals and computes alignment-aware composite scores.

    Signals are stored per-ticker.  For each ticker only the *most recent*
    signal per timeframe is retained; older signals for the same timeframe
    are automatically replaced when a newer one is added.

    Example::

        agg = TimeframeAggregator(max_age_s=14400)
        for sig in my_signal_stream:
            agg.add(sig)
        result = agg.composite_score("TSLA")
        if result and result.alignment == TimeframeAlignment.FULL_ALIGN:
            trigger_trade(result)
    """

    def __init__(self, max_age_s: float = _DEFAULT_MAX_AGE_S) -> None:
        """Create an aggregator.

        Parameters
        ----------
        max_age_s:
            Maximum signal age (seconds) before a signal is excluded from
            composite scoring.  Defaults to 4 hours.
        """
        self._max_age_s = max_age_s
        # ticker → timeframe → most-recent TimeframeSignal
        self._signals: dict[str, dict[str, TimeframeSignal]] = {}

    # ── Mutation ─────────────────────────────────────────

    def add(self, signal: TimeframeSignal) -> None:
        """Add (or replace) a signal for a ticker/timeframe pair.

        If a signal already exists for the same (ticker, timeframe) the newer
        one replaces it only if its timestamp is >= the existing timestamp.
        """
        ticker_store = self._signals.setdefault(signal.ticker, {})
        existing = ticker_store.get(signal.timeframe)
        if existing is None or signal.timestamp >= existing.timestamp:
            ticker_store[signal.timeframe] = signal

    def clear(self, ticker: Optional[str] = None) -> None:
        """Remove all signals.

        Parameters
        ----------
        ticker:
            When provided, clear only signals for that ticker.
            When ``None``, clear the entire store.
        """
        if ticker is None:
            self._signals.clear()
        else:
            self._signals.pop(ticker, None)

    # ── Scoring ───────────────────────────────────────────

    def composite_score(
        self,
        ticker: str,
        now: Optional[float] = None,
    ) -> Optional[CompositeResult]:
        """Compute the alignment-aware composite score for *ticker*.

        Algorithm
        ---------
        1. Collect all signals for *ticker* that are younger than *max_age_s*.
        2. Compute the timeframe-weighted average confidence.
        3. Compute weighted sum for each direction (bullish / bearish / neutral).
        4. Determine the dominant direction and alignment level.
        5. Apply alignment multiplier (bonus or penalty) to the raw score.

        Parameters
        ----------
        ticker:
            Ticker to score.
        now:
            Reference timestamp (defaults to ``time.time()``).  Useful for
            deterministic testing.

        Returns
        -------
        ``CompositeResult`` if at least one valid signal exists, else ``None``.
        """
        if now is None:
            now = time.time()

        raw_signals = self._signals.get(ticker)
        if not raw_signals:
            return None

        # Filter by age
        cutoff = now - self._max_age_s
        fresh: list[TimeframeSignal] = [
            s for s in raw_signals.values() if s.timestamp >= cutoff
        ]
        if not fresh:
            return None

        # Weighted-average confidence and direction weights
        total_weight = 0.0
        weighted_confidence = 0.0
        direction_weights: dict[str, float] = {
            "bullish": 0.0,
            "bearish": 0.0,
            "neutral": 0.0,
        }

        for sig in fresh:
            w = TIMEFRAME_WEIGHTS.get(sig.timeframe, 0.0)
            weighted_value = w * sig.confidence
            weighted_confidence += weighted_value
            total_weight += w
            direction_weights[sig.signal] += weighted_value

        if total_weight == 0.0:
            return None

        raw_score = weighted_confidence / total_weight

        # Dominant signal by weighted confidence contribution
        dominant_signal = max(direction_weights, key=lambda k: direction_weights[k])
        dominant_weight = direction_weights[dominant_signal]

        # Alignment calculation
        directional_weight = direction_weights["bullish"] + direction_weights["bearish"]
        if directional_weight == 0.0:
            alignment_ratio = 0.0
        else:
            dominant_directional = max(
                direction_weights["bullish"], direction_weights["bearish"]
            )
            alignment_ratio = dominant_directional / directional_weight if directional_weight > 0 else 0.0

        # Check overall agreement (dominant vs total)
        overall_agreement = dominant_weight / weighted_confidence if weighted_confidence > 0 else 0.0

        if overall_agreement >= 0.90:
            alignment = TimeframeAlignment.FULL_ALIGN
            multiplier = _FULL_ALIGN_BONUS
        elif overall_agreement >= _PARTIAL_ALIGN_THRESHOLD:
            alignment = TimeframeAlignment.PARTIAL_ALIGN
            multiplier = _PARTIAL_ALIGN_BONUS
        else:
            alignment = TimeframeAlignment.DIVERGENT
            multiplier = _DIVERGENT_PENALTY

        final_score = max(0.0, min(1.0, raw_score * multiplier))

        contributing = sorted({s.timeframe for s in fresh}, key=lambda t: list(TIMEFRAME_WEIGHTS).index(t))

        return CompositeResult(
            ticker=ticker,
            score=round(final_score, 4),
            raw_score=round(raw_score, 4),
            dominant_signal=dominant_signal,
            alignment=alignment,
            contributing_timeframes=contributing,
            signal_count=len(fresh),
            computed_at=now,
        )

    def tickers(self) -> list[str]:
        """Return all tickers that have stored signals."""
        return list(self._signals.keys())

    def signals_for(self, ticker: str) -> list[TimeframeSignal]:
        """Return all stored signals for *ticker* (any age)."""
        return list(self._signals.get(ticker, {}).values())
