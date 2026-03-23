"""Multi-timeframe signal analysis for the ROT platform.

Provides :class:`MultiTimeframeAnalyzer` — a higher-level facade on top of
:class:`rot.strategy.timeframe_aggregator.TimeframeAggregator` that:

- Accepts raw signals in the ROT signal dict format (or simple dicts)
- Enforces a configurable required timeframe set (default: 1h, 4h, 1d)
- Only generates a trade idea when signals *align* across ALL required
  timeframes, reducing false positives significantly
- Exposes a synchronous ``analyze(ticker, signals)`` method suitable for
  direct use in the pipeline

Typical usage::

    from rot.analysis.multi_timeframe import MultiTimeframeAnalyzer

    analyzer = MultiTimeframeAnalyzer(required_timeframes=["1h", "4h", "1d"])
    result = analyzer.analyze(
        ticker="AAPL",
        signals=[
            {"timeframe": "1h",  "signal": "bullish", "confidence": 0.75},
            {"timeframe": "4h",  "signal": "bullish", "confidence": 0.80},
            {"timeframe": "1d",  "signal": "bullish", "confidence": 0.70},
        ],
    )
    if result.should_trade:
        print(f"Trade! Score={result.score:.2f} Alignment={result.alignment}")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

from rot.strategy.timeframe_aggregator import (
    CompositeResult,
    TimeframeAggregator,
    TimeframeAlignment,
    TimeframeSignal,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default required timeframe set
# ---------------------------------------------------------------------------

_DEFAULT_REQUIRED = ("1h", "4h", "1d")
_DEFAULT_MIN_CONFIDENCE = 0.60


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MultiTimeframeResult:
    """Result from :class:`MultiTimeframeAnalyzer`.

    Attributes:
        ticker: Ticker that was analysed.
        should_trade: ``True`` only when all required timeframes are present
            AND signals are aligned (FULL_ALIGN or PARTIAL_ALIGN with
            score >= min_score_threshold).
        score: Composite alignment-adjusted score (0.0–1.0).
        alignment: Alignment level from :class:`TimeframeAlignment`.
        dominant_signal: ``"bullish"``, ``"bearish"``, or ``"neutral"``.
        missing_timeframes: Timeframes that were absent from the input.
        suppressed_reason: Human-readable reason when ``should_trade`` is
            ``False`` (empty string when ``should_trade`` is ``True``).
        composite: The underlying :class:`CompositeResult` (may be ``None``
            if scoring was not possible).
    """

    ticker: str
    should_trade: bool
    score: float
    alignment: Optional[TimeframeAlignment]
    dominant_signal: str
    missing_timeframes: List[str]
    suppressed_reason: str
    composite: Optional[CompositeResult] = None


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class MultiTimeframeAnalyzer:
    """Aggregates signals across multiple timeframes and gates trade generation.

    A trade idea is only approved (``should_trade=True``) when:
    1. All *required_timeframes* have at least one valid signal.
    2. The composite alignment level is FULL_ALIGN or PARTIAL_ALIGN.
    3. The composite score meets *min_score_threshold*.

    This triple gate significantly reduces false-positive trade signals.

    Args:
        required_timeframes: Timeframes that must all be present.
            Defaults to ``("1h", "4h", "1d")``.
        min_score_threshold: Minimum composite score to approve a trade.
            Defaults to 0.60.
        max_signal_age_s: Maximum signal age in seconds.  Signals older
            than this are excluded from scoring.  Defaults to 4 hours.
    """

    def __init__(
        self,
        required_timeframes: tuple[str, ...] | list[str] = _DEFAULT_REQUIRED,
        min_score_threshold: float = _DEFAULT_MIN_CONFIDENCE,
        max_signal_age_s: float = 4 * 3600,
    ) -> None:
        self._required = list(required_timeframes)
        self._min_score = min_score_threshold
        self._aggregator = TimeframeAggregator(max_age_s=max_signal_age_s)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def analyze(
        self,
        ticker: str,
        signals: list[dict],
        now: Optional[float] = None,
    ) -> MultiTimeframeResult:
        """Analyse multi-timeframe signals for *ticker*.

        Args:
            ticker: Equity/options ticker symbol.
            signals: List of signal dicts.  Each dict must contain:
                - ``"timeframe"`` (str) — one of the valid timeframe keys
                - ``"signal"`` (str) — ``"bullish"``, ``"bearish"``, or ``"neutral"``
                - ``"confidence"`` (float) — in [0.0, 1.0]
                Optional keys: ``"source"`` (str), ``"timestamp"`` (float).
            now: Reference Unix timestamp (defaults to current time).

        Returns:
            A :class:`MultiTimeframeResult` describing whether a trade should
            be triggered and why.
        """
        if now is None:
            now = time.time()

        # Load signals into aggregator
        self._aggregator.clear(ticker)
        for raw in signals:
            sig = self._parse_signal(ticker, raw, now)
            if sig is not None:
                self._aggregator.add(sig)

        # Check required timeframes are present
        stored = {s.timeframe for s in self._aggregator.signals_for(ticker)}
        missing = [tf for tf in self._required if tf not in stored]

        if missing:
            reason = f"Missing required timeframes: {missing}"
            log.debug("multi_tf.suppressed ticker=%s reason=%s", ticker, reason)
            return MultiTimeframeResult(
                ticker=ticker,
                should_trade=False,
                score=0.0,
                alignment=None,
                dominant_signal="unknown",
                missing_timeframes=missing,
                suppressed_reason=reason,
            )

        # Compute composite score
        composite = self._aggregator.composite_score(ticker, now=now)
        if composite is None:
            return MultiTimeframeResult(
                ticker=ticker,
                should_trade=False,
                score=0.0,
                alignment=None,
                dominant_signal="unknown",
                missing_timeframes=missing,
                suppressed_reason="Composite scoring returned no result (all signals may be stale).",
            )

        # Gate on alignment and score
        if composite.alignment == TimeframeAlignment.DIVERGENT:
            reason = (
                f"Timeframes diverge — alignment={composite.alignment.value}, "
                f"score={composite.score:.2f}"
            )
            log.info("multi_tf.divergent ticker=%s score=%.2f", ticker, composite.score)
            return MultiTimeframeResult(
                ticker=ticker,
                should_trade=False,
                score=composite.score,
                alignment=composite.alignment,
                dominant_signal=composite.dominant_signal,
                missing_timeframes=missing,
                suppressed_reason=reason,
                composite=composite,
            )

        if composite.score < self._min_score:
            reason = (
                f"Score {composite.score:.2f} below minimum threshold {self._min_score:.2f}"
            )
            log.info(
                "multi_tf.below_threshold ticker=%s score=%.2f threshold=%.2f",
                ticker, composite.score, self._min_score,
            )
            return MultiTimeframeResult(
                ticker=ticker,
                should_trade=False,
                score=composite.score,
                alignment=composite.alignment,
                dominant_signal=composite.dominant_signal,
                missing_timeframes=missing,
                suppressed_reason=reason,
                composite=composite,
            )

        log.info(
            "multi_tf.approved ticker=%s score=%.2f alignment=%s signal=%s",
            ticker, composite.score, composite.alignment.value, composite.dominant_signal,
        )
        return MultiTimeframeResult(
            ticker=ticker,
            should_trade=True,
            score=composite.score,
            alignment=composite.alignment,
            dominant_signal=composite.dominant_signal,
            missing_timeframes=[],
            suppressed_reason="",
            composite=composite,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_signal(
        ticker: str,
        raw: dict,
        now: float,
    ) -> Optional[TimeframeSignal]:
        """Convert a raw signal dict to a :class:`TimeframeSignal`.

        Returns ``None`` if the dict is missing required keys or contains
        invalid values (errors are logged as warnings).
        """
        try:
            timeframe = str(raw["timeframe"])
            signal = str(raw["signal"]).lower()
            confidence = float(raw["confidence"])
            timestamp = float(raw.get("timestamp", now))
            source = str(raw.get("source", ""))
            return TimeframeSignal(
                ticker=ticker,
                timeframe=timeframe,
                signal=signal,
                confidence=confidence,
                timestamp=timestamp,
                source=source,
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("multi_tf.parse_error raw=%s error=%s", raw, exc)
            return None
