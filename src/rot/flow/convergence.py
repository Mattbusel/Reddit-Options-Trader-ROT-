"""Signal-flow convergence detection engine.

Cross-references social media signals with institutional flow events
to find points of agreement (convergence) or disagreement (divergence).

Convergence types:
  - aligned: social signal and flow in same direction → high confidence
  - contradictory: social vs flow opposite → warning flag
  - amplified: multiple flow events reinforce social signal → extra boost

Design goals:
  - Time-window matching (configurable hours)
  - Direction alignment scoring
  - Premium-weighted convergence score
  - Batch processing for pipeline integration
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional

from rot.flow.types import FlowEvent, FlowSignalConvergence

log = logging.getLogger(__name__)

# ── Convergence Config ──────────────────────────────────


class ConvergenceConfig:
    """Configuration for convergence detection."""

    def __init__(
        self,
        window_hours: float = 6.0,
        min_score: float = 30.0,
        premium_scale: float = 100_000.0,
        min_flow_events: int = 1,
        aligned_base_score: float = 55.0,
        contradictory_base_score: float = 35.0,
        amplified_threshold: int = 3,
        amplified_base_score: float = 70.0,
    ) -> None:
        self.window_hours = window_hours
        self.min_score = min_score
        self.premium_scale = premium_scale  # $100k = 1.0 for premium factor
        self.min_flow_events = min_flow_events
        self.aligned_base_score = aligned_base_score
        self.contradictory_base_score = contradictory_base_score
        self.amplified_threshold = amplified_threshold
        self.amplified_base_score = amplified_base_score


# ── Convergence Detector ────────────────────────────────


class ConvergenceDetector:
    """Detect convergences between social signals and flow events.

    Example::

        detector = ConvergenceDetector()
        convergences = detector.find_convergences(flow_events, signals)
    """

    def __init__(self, config: Optional[ConvergenceConfig] = None) -> None:
        self._config = config or ConvergenceConfig()

    @property
    def config(self) -> ConvergenceConfig:
        return self._config

    def find_convergences(
        self,
        flow_events: List[FlowEvent],
        signals: List[Dict[str, Any]],
        timestamp: Optional[float] = None,
    ) -> List[FlowSignalConvergence]:
        """Find flow events that converge with social signals.

        Parameters
        ----------
        flow_events : list
            Detected flow events.
        signals : list
            Signal dicts from database (must have id, ticker, stance, created_at).
        timestamp : float, optional
            Detection timestamp. Defaults to now.

        Returns
        -------
        List[FlowSignalConvergence]
            Convergences above min_score.
        """
        if not flow_events or not signals:
            return []

        ts = timestamp or time.time()
        convergences: List[FlowSignalConvergence] = []

        # Index flow events by ticker
        flow_by_ticker: Dict[str, List[FlowEvent]] = defaultdict(list)
        for fe in flow_events:
            flow_by_ticker[fe.ticker].append(fe)

        for signal in signals:
            ticker = signal.get("ticker", "")
            signal_id = signal.get("id", "")
            signal_stance = signal.get("stance", "unknown")

            # Only match directional signals
            if signal_stance not in ("bullish", "bearish"):
                continue

            if ticker not in flow_by_ticker:
                continue

            # Find flow events within time window
            signal_time = _safe_float(signal.get("created_at"), 0)
            if signal_time <= 0:
                continue

            matching = self._find_matching_events(
                flow_by_ticker[ticker],
                signal_time,
            )

            if len(matching) < self._config.min_flow_events:
                continue

            # Compute convergence
            convergence = self._compute_convergence(
                signal_id=signal_id,
                ticker=ticker,
                signal_stance=signal_stance,
                flow_events=matching,
                ts=ts,
            )

            if convergence and convergence.convergence_score >= self._config.min_score:
                convergences.append(convergence)

        return convergences

    def check_signal(
        self,
        signal: Dict[str, Any],
        flow_events: List[FlowEvent],
        timestamp: Optional[float] = None,
    ) -> Optional[FlowSignalConvergence]:
        """Check a single signal against flow events.

        Convenience method for pipeline integration — checks one signal
        against a list of flow events.
        """
        results = self.find_convergences(flow_events, [signal], timestamp)
        return results[0] if results else None

    # ── Internal ────────────────────────────────────────

    def _find_matching_events(
        self,
        flow_events: List[FlowEvent],
        signal_time: float,
    ) -> List[FlowEvent]:
        """Find flow events within time window of signal."""
        window_s = self._config.window_hours * 3600.0
        matches = []
        for fe in flow_events:
            time_delta = abs(fe.timestamp - signal_time)
            if time_delta <= window_s:
                matches.append(fe)
        return matches

    def _compute_convergence(
        self,
        signal_id: str,
        ticker: str,
        signal_stance: str,
        flow_events: List[FlowEvent],
        ts: float,
    ) -> Optional[FlowSignalConvergence]:
        """Compute convergence score and type.

        Scoring:
          - Base score depends on convergence type
          - Premium factor: larger flow = higher score
          - Event count factor: more events = higher confidence
          - Cap at 100
        """
        # Aggregate flow direction
        bullish_premium = sum(
            e.premium for e in flow_events if e.direction == "bullish"
        )
        bearish_premium = sum(
            e.premium for e in flow_events if e.direction == "bearish"
        )
        net_premium = bullish_premium - bearish_premium

        # Determine flow direction
        if abs(net_premium) < 5000:  # $5k threshold
            flow_direction = "neutral"
        elif net_premium > 0:
            flow_direction = "bullish"
        else:
            flow_direction = "bearish"

        # Skip if flow is neutral
        if flow_direction == "neutral":
            return None

        # Determine convergence type
        if signal_stance == flow_direction:
            # Check for amplified (3+ events in same direction)
            aligned_events = sum(
                1 for e in flow_events if e.direction == signal_stance
            )
            if aligned_events >= self._config.amplified_threshold:
                convergence_type = "amplified"
                base_score = self._config.amplified_base_score
            else:
                convergence_type = "aligned"
                base_score = self._config.aligned_base_score
        else:
            convergence_type = "contradictory"
            base_score = self._config.contradictory_base_score

        # Premium factor: 0-20 points based on flow magnitude
        abs_premium = abs(net_premium)
        premium_factor = min(abs_premium / self._config.premium_scale, 1.0) * 20.0

        # Event count factor: 0-10 points
        count_factor = min(len(flow_events) * 2.0, 10.0)

        # Average event score factor: 0-10 points
        avg_event_score = sum(e.score for e in flow_events) / len(flow_events)
        score_factor = min(avg_event_score / 10.0, 10.0)

        convergence_score = min(
            base_score + premium_factor + count_factor + score_factor,
            100.0,
        )

        flow_event_ids = [e.id for e in flow_events if e.id]

        return FlowSignalConvergence(
            id=str(uuid.uuid4()),
            signal_id=signal_id,
            ticker=ticker,
            flow_event_ids=flow_event_ids,
            convergence_score=round(convergence_score, 1),
            convergence_type=convergence_type,
            signal_stance=signal_stance,
            flow_direction=flow_direction,
            net_flow_premium=round(net_premium, 2),
            details={
                "bullish_premium": round(bullish_premium, 2),
                "bearish_premium": round(bearish_premium, 2),
                "event_count": len(flow_events),
                "avg_event_score": round(avg_event_score, 1),
                "premium_factor": round(premium_factor, 1),
            },
            detected_at=ts,
        )


# ── Helpers ─────────────────────────────────────────────


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce to float, return default on failure."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if f != f else f  # NaN check
    except (TypeError, ValueError):
        return default
