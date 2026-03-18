"""AttentionRadar — detects pre-catalyst attention anomalies.

Built natively in ROT.  Formalizes the emergent behavior already observed
in live operation: the system's highest-confidence signals cluster on tickers
with UNKNOWN event classification and anomalous mention volume, days before
the market has language for what is happening.

Fire conditions (all three must be met):
  1. confidence >= 0.88
  2. event_type == "other" (ROT's catch-all for UNKNOWN)
  3. signal volume for this ticker is > 2 standard deviations above its
     30-day rolling baseline

Fired events are written to the ``attention_radar_events`` SQLite table
(via RadarMixin in rot/storage/radar_db.py) with a separate output track
from directional signals.

A background resolver (run nightly) checks each unresolved AttentionRadar
event older than 3 days: if a high-confidence directional signal has since
fired on the same ticker, the event is marked resolved with catalyst type
and lead time.

The lead time distribution across all resolved events is the primary
performance metric: it measures how far ahead of market-nameable catalysts
the system is operating.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional
from collections import deque

from rot.core.types import Event

log = logging.getLogger(__name__)

# Fire condition thresholds
_CONFIDENCE_THRESHOLD = 0.88
_UNKNOWN_EVENT_TYPES = {"other", "unknown"}
_VOLUME_ZSCORE_THRESHOLD = 2.0

# Rolling baseline window (seconds) for mention-volume z-score
_BASELINE_WINDOW_S = 30 * 86400  # 30 days
# Minimum samples before z-score is meaningful
_MIN_BASELINE_SAMPLES = 10


@dataclass
class RadarFireCondition:
    """Diagnostics explaining why an AttentionRadar event did or did not fire."""

    confidence_met: bool
    event_type_met: bool
    volume_met: bool
    confidence: float
    event_type: str
    volume_zscore: Optional[float]

    @property
    def fired(self) -> bool:
        """``True`` if all three trigger conditions (confidence, event type, volume) are met."""
        return self.confidence_met and self.event_type_met and self.volume_met


@dataclass
class AttentionRadarEvent:
    """A single AttentionRadar firing.

    Attributes:
        ticker: The ticker that triggered the radar.
        timestamp: Unix timestamp of the firing.
        confidence: Signal confidence at fire time.
        signal_volume_zscore: z-score of mention volume vs 30-day baseline.
        event_type: The event_type from the ROT signal (expected ``"other"``).
        stance: Signal stance at fire time.
        source_signal_id: ID of the ROT signal that triggered the radar.
        eventual_catalyst: Filled by resolver when a directional signal fires.
        lead_time_days: Days between this event and the eventual catalyst.
        resolved: True once the nightly resolver has matched a catalyst.
        resolved_at: Unix timestamp when the event was resolved.
        meta: Additional metadata (subreddit, etc.).
    """

    ticker: str
    timestamp: float
    confidence: float
    signal_volume_zscore: float
    event_type: str
    stance: str
    source_signal_id: str = ""
    eventual_catalyst: Optional[str] = None
    lead_time_days: Optional[float] = None
    resolved: bool = False
    resolved_at: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)


class _TickerVolumeBaseline:
    """Rolling 30-day mention volume baseline for one ticker.

    Maintains a deque of (timestamp, count) pairs and computes z-score
    of a new observation against the historical distribution using
    Welford's online algorithm for mean and variance.
    """

    def __init__(self, window_s: float = _BASELINE_WINDOW_S) -> None:
        self._window_s = window_s
        self._samples: Deque[tuple[float, float]] = deque()
        # Welford state
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0

    def record(self, ts: float, count: float) -> None:
        """Record a new observation and prune stale ones."""
        self._samples.append((ts, count))
        cutoff = ts - self._window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        # Recompute Welford from scratch when samples pruned (rare)
        self._recompute_welford()

    def zscore(self, count: float) -> Optional[float]:
        """Return z-score of count vs the rolling baseline.

        Returns None if fewer than MIN_BASELINE_SAMPLES are available.
        """
        if self._n < _MIN_BASELINE_SAMPLES:
            return None
        std = math.sqrt(self._m2 / self._n) if self._n > 1 else 0.0
        if std < 1e-9:
            return 0.0
        return (count - self._mean) / std

    def _recompute_welford(self) -> None:
        """Recompute Welford accumulators from the current sample window."""
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0
        for _, v in self._samples:
            self._n += 1
            delta = v - self._mean
            self._mean += delta / self._n
            self._m2 += delta * (v - self._mean)

    @property
    def sample_count(self) -> int:
        """Number of observations stored in the rolling window."""
        return len(self._samples)


class AttentionRadar:
    """Detects and logs pre-catalyst attention anomalies.

    One instance per application lifecycle.  Called from the signal pipeline
    after credibility scoring and suppression, before LLM reasoning.

    Usage::

        radar = AttentionRadar()
        event, radar_event = radar.check(rot_event, signal_volume=42)
        if radar_event is not None:
            await db.save_radar_event(radar_event)
    """

    def __init__(
        self,
        confidence_threshold: float = _CONFIDENCE_THRESHOLD,
        volume_zscore_threshold: float = _VOLUME_ZSCORE_THRESHOLD,
        enabled: bool = True,
    ) -> None:
        self._conf_threshold = confidence_threshold
        self._vol_threshold = volume_zscore_threshold
        self._enabled = enabled
        # Per-ticker volume baselines
        self._baselines: Dict[str, _TickerVolumeBaseline] = {}
        self._fired_count = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def record_volume(self, ticker: str, count: float, ts: Optional[float] = None) -> None:
        """Record a mention volume observation for a ticker.

        Called during ingestion/trend detection to build the baseline.
        ``count`` is the number of mentions in the current cycle.
        """
        if ticker not in self._baselines:
            self._baselines[ticker] = _TickerVolumeBaseline()
        self._baselines[ticker].record(ts or time.time(), count)

    def check(
        self,
        event: Event,
        signal_volume: float,
        source_signal_id: str = "",
        ts: Optional[float] = None,
    ) -> tuple[Event, Optional[AttentionRadarEvent]]:
        """Check whether an event triggers the AttentionRadar.

        Args:
            event: The ROT Event after credibility scoring.
            signal_volume: Mention volume for event.entities[0] this cycle.
            source_signal_id: Optional signal ID for tracing.
            ts: Override timestamp (defaults to now).

        Returns:
            (event, AttentionRadarEvent | None).  The event is returned
            unchanged.  A non-None radar event indicates the radar fired.
        """
        if not self._enabled:
            return event, None

        ticker = event.entities[0] if event.entities else "UNKNOWN"
        now = ts or time.time()

        condition = self._evaluate_conditions(event, ticker, signal_volume)

        if not condition.fired:
            return event, None

        self._fired_count += 1
        radar_event = AttentionRadarEvent(
            ticker=ticker,
            timestamp=now,
            confidence=event.confidence,
            signal_volume_zscore=condition.volume_zscore or 0.0,
            event_type=event.event_type,
            stance=event.stance,
            source_signal_id=source_signal_id,
            meta={
                "subreddit": (event.evidence[0].subreddit if event.evidence else ""),
                "fire_count": self._fired_count,
                "condition": {
                    "confidence_met": condition.confidence_met,
                    "event_type_met": condition.event_type_met,
                    "volume_met": condition.volume_met,
                },
            },
        )

        log.info(
            "AttentionRadar FIRED: ticker=%s confidence=%.2f vol_z=%.2f (fire #%d)",
            ticker, event.confidence, condition.volume_zscore or 0.0, self._fired_count,
        )

        return event, radar_event

    def evaluate_conditions(
        self, event: Event, signal_volume: float
    ) -> RadarFireCondition:
        """Public interface to evaluate fire conditions without firing.

        Useful for testing and dashboard display.
        """
        ticker = event.entities[0] if event.entities else "UNKNOWN"
        return self._evaluate_conditions(event, ticker, signal_volume)

    @property
    def fired_count(self) -> int:
        """Total number of times the radar has fired since instantiation."""
        return self._fired_count

    @property
    def enabled(self) -> bool:
        """``True`` if the radar is active and will evaluate incoming events."""
        return self._enabled

    # ── Internal ──────────────────────────────────────────────────────────────

    def _evaluate_conditions(
        self, event: Event, ticker: str, signal_volume: float
    ) -> RadarFireCondition:
        confidence_met = event.confidence >= self._conf_threshold
        event_type_met = (event.event_type or "").lower() in _UNKNOWN_EVENT_TYPES

        baseline = self._baselines.get(ticker)
        zscore: Optional[float] = None
        volume_met = False
        if baseline is not None:
            zscore = baseline.zscore(signal_volume)
            if zscore is not None:
                volume_met = zscore >= self._vol_threshold
            # If we don't have enough baseline data, do NOT fire on volume
            # condition — require evidence before classifying as anomalous
        else:
            # No baseline at all — record but don't fire
            volume_met = False

        return RadarFireCondition(
            confidence_met=confidence_met,
            event_type_met=event_type_met,
            volume_met=volume_met,
            confidence=event.confidence,
            event_type=event.event_type or "unknown",
            volume_zscore=zscore,
        )


# ── Background resolver ───────────────────────────────────────────────────────


class RadarResolver:
    """Nightly background resolver for unresolved AttentionRadar events.

    For each unresolved event older than ``min_age_days``, checks whether a
    high-confidence directional signal has since fired on the same ticker.
    If yes, marks the event resolved and records catalyst type and lead time.

    Usage::

        resolver = RadarResolver(db)
        await resolver.run_once()   # called from the nightly background loop
    """

    def __init__(
        self,
        db: Any,
        min_age_days: float = 3.0,
        directional_confidence_threshold: float = 0.7,
    ) -> None:
        self._db = db
        self._min_age_s = min_age_days * 86400
        self._dir_conf = directional_confidence_threshold

    async def run_once(self) -> int:
        """Resolve pending radar events.  Returns number of events resolved."""
        resolved = 0
        now = time.time()
        try:
            pending = await self._db.get_unresolved_radar_events(
                older_than_ts=now - self._min_age_s
            )
            for radar_ev in pending:
                result = await self._try_resolve(radar_ev, now)
                if result:
                    resolved += 1
        except Exception as exc:
            log.error("RadarResolver.run_once failed: %s", exc)
        log.info("RadarResolver: resolved %d events", resolved)
        return resolved

    async def _try_resolve(
        self, radar_ev: Dict[str, Any], now: float
    ) -> bool:
        """Try to find a directional signal for the radar event's ticker."""
        ticker = radar_ev["ticker"]
        fire_ts = radar_ev["timestamp"]

        try:
            directional = await self._db.get_directional_signals_after(
                ticker=ticker,
                after_ts=fire_ts,
                min_confidence=self._dir_conf,
            )
        except Exception as exc:
            log.warning("RadarResolver: DB query failed for %s: %s", ticker, exc)
            return False

        if not directional:
            return False

        catalyst = directional[0]
        lead_time_s = catalyst["created_at"] - fire_ts
        lead_time_days = lead_time_s / 86400

        try:
            await self._db.resolve_radar_event(
                event_id=radar_ev["id"],
                eventual_catalyst=catalyst.get("event_type", "unknown"),
                lead_time_days=lead_time_days,
                resolved_at=now,
            )
        except Exception as exc:
            log.error("RadarResolver: failed to resolve event %s: %s", radar_ev.get("id"), exc)
            return False

        log.info(
            "RadarResolver: resolved %s → catalyst=%s lead=%.1f days",
            ticker, catalyst.get("event_type"), lead_time_days,
        )
        return True
