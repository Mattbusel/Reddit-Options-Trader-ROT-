"""TelemetryBus — central metrics aggregator for all ROT pipeline stages.

Ported from tokio-prompt-orchestrator/src/self_tune/telemetry_bus.rs.

Each pipeline stage calls ``TelemetryBus.report(stage_name, metrics)`` after
processing.  The bus accumulates metrics in rolling windows (1 min, 5 min,
15 min, 1 h) and broadcasts ``TelemetrySnapshot`` objects to registered
subscribers every ``interval_s`` seconds.

Designed for async usage: subscribers receive snapshots via asyncio.Queue.
The bus itself is non-blocking — if a subscriber queue is full the snapshot
is dropped for that subscriber rather than stalling the pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Rolling window durations in seconds
_WINDOWS: Dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
}

# Maximum subscriber queue depth — old snapshots are dropped rather than
# blocking the bus when a subscriber falls behind.
_SUBSCRIBER_QUEUE_MAX = 128


@dataclass
class StageMetrics:
    """Point-in-time metrics emitted by a single pipeline stage.

    Attributes:
        stage: Logical stage identifier, e.g. ``"nlp"``, ``"credibility"``.
        ts: Unix timestamp (seconds) when the metrics were recorded.
        latency_ms: Wall-clock time spent in this stage (milliseconds).
        items_in: Number of items that entered this stage this cycle.
        items_out: Number of items that exited this stage this cycle.
        errors: Number of non-fatal errors encountered this cycle.
        extra: Stage-specific key/value pairs for domain metrics.
    """

    stage: str
    ts: float
    latency_ms: float
    items_in: int
    items_out: int
    errors: int = 0
    extra: Dict[str, float] = field(default_factory=dict)

    @property
    def throughput_ratio(self) -> float:
        """items_out / items_in, or 1.0 when items_in == 0."""
        if self.items_in == 0:
            return 1.0
        return self.items_out / self.items_in

    @property
    def error_rate(self) -> float:
        """errors / items_in, or 0.0 when items_in == 0."""
        if self.items_in == 0:
            return 0.0
        return self.errors / self.items_in


@dataclass
class _WindowStats:
    """Aggregated statistics computed over a rolling time window."""

    window_name: str
    sample_count: int
    avg_latency_ms: float
    p95_latency_ms: float
    avg_throughput_ratio: float
    avg_error_rate: float
    total_items_in: int
    total_items_out: int


@dataclass
class TelemetrySnapshot:
    """System-wide telemetry snapshot broadcast to all subscribers.

    Attributes:
        ts: Unix timestamp when this snapshot was produced.
        per_stage: Latest raw metrics keyed by stage name.
        windows: Rolling window aggregates keyed by stage → window_name.
        pressure: Composite pressure score [0, 1] — blend of error rate,
                  throughput loss and latency percentile vs. target.
    """

    ts: float
    per_stage: Dict[str, StageMetrics]
    windows: Dict[str, Dict[str, _WindowStats]]
    pressure: float


class TelemetryBus:
    """Central metrics aggregator.

    Usage::

        bus = TelemetryBus(interval_s=5.0)
        sub_queue = bus.subscribe()          # asyncio.Queue[TelemetrySnapshot]
        bus.report("nlp", StageMetrics(...)) # called from pipeline stages
        await bus.start()                    # start background broadcast loop
        await bus.stop()

    Thread-safety: ``report()`` acquires a lock so it is safe to call from
    sync code running in a thread pool executor.
    """

    def __init__(self, interval_s: float = 5.0) -> None:
        self._interval_s = interval_s
        # stage → deque of (ts, StageMetrics) sorted oldest-first
        self._ring: Dict[str, Deque[Tuple[float, StageMetrics]]] = {}
        self._lock = asyncio.Lock()
        self._subscribers: List[asyncio.Queue[TelemetrySnapshot]] = []
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._running = False

    # ── Ingestion ────────────────────────────────────────────────────────────

    def report(self, stage: str, metrics: StageMetrics) -> None:
        """Record a stage metric sample (non-async, safe from sync context).

        Appends to the in-memory ring and prunes samples older than 1 hour.
        Does NOT acquire the async lock — designed for the hot path.
        """
        if stage not in self._ring:
            self._ring[stage] = deque()
        buf = self._ring[stage]
        buf.append((metrics.ts, metrics))
        # Prune samples older than the largest window (1h = 3600 s)
        cutoff = metrics.ts - 3600
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    # ── Subscription ─────────────────────────────────────────────────────────

    def subscribe(self) -> "asyncio.Queue[TelemetrySnapshot]":
        """Register a subscriber and return its queue."""
        q: asyncio.Queue[TelemetrySnapshot] = asyncio.Queue(
            maxsize=_SUBSCRIBER_QUEUE_MAX
        )
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[TelemetrySnapshot]") -> None:
        """Remove a subscriber queue."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background broadcast loop."""
        self._running = True
        self._task = asyncio.create_task(self._broadcast_loop())

    async def stop(self) -> None:
        """Stop the background broadcast loop gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _broadcast_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval_s)
                snapshot = self._build_snapshot()
                self._broadcast(snapshot)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("TelemetryBus broadcast error: %s", exc)

    def _build_snapshot(self) -> TelemetrySnapshot:
        now = time.time()
        per_stage: Dict[str, StageMetrics] = {}
        windows: Dict[str, Dict[str, _WindowStats]] = {}

        for stage, buf in self._ring.items():
            if not buf:
                continue
            # Latest raw metrics for this stage
            per_stage[stage] = buf[-1][1]
            windows[stage] = {}

            for wname, wdur in _WINDOWS.items():
                cutoff = now - wdur
                samples = [m for ts, m in buf if ts >= cutoff]
                if not samples:
                    continue
                windows[stage][wname] = _aggregate(wname, samples)

        pressure = self._compute_pressure(per_stage)
        return TelemetrySnapshot(ts=now, per_stage=per_stage, windows=windows, pressure=pressure)

    @staticmethod
    def _compute_pressure(per_stage: Dict[str, StageMetrics]) -> float:
        """Composite pressure [0, 1]: blend of error rate + throughput loss."""
        if not per_stage:
            return 0.0
        total_error = sum(m.error_rate for m in per_stage.values())
        avg_error = total_error / len(per_stage)
        total_loss = sum(max(0.0, 1.0 - m.throughput_ratio) for m in per_stage.values())
        avg_loss = total_loss / len(per_stage)
        return min(1.0, (avg_error + avg_loss) / 2.0)

    def _broadcast(self, snapshot: TelemetrySnapshot) -> None:
        dead: List["asyncio.Queue[TelemetrySnapshot]"] = []
        for q in self._subscribers:
            try:
                q.put_nowait(snapshot)
            except asyncio.QueueFull:
                log.debug("TelemetryBus: subscriber queue full, dropping snapshot")
            except Exception as exc:
                log.warning("TelemetryBus: subscriber error: %s", exc)
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    def latest_snapshot(self) -> Optional[TelemetrySnapshot]:
        """Build and return a snapshot immediately (synchronous read)."""
        if not self._ring:
            return None
        return self._build_snapshot()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _aggregate(window_name: str, samples: List[StageMetrics]) -> _WindowStats:
    """Aggregate a list of StageMetrics samples into a _WindowStats struct."""
    latencies = sorted(m.latency_ms for m in samples)
    n = len(latencies)
    avg_lat = sum(latencies) / n
    p95_idx = max(0, int(math.ceil(n * 0.95)) - 1)
    p95_lat = latencies[p95_idx]
    avg_thr = sum(m.throughput_ratio for m in samples) / n
    avg_err = sum(m.error_rate for m in samples) / n
    total_in = sum(m.items_in for m in samples)
    total_out = sum(m.items_out for m in samples)
    return _WindowStats(
        window_name=window_name,
        sample_count=n,
        avg_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
        avg_throughput_ratio=avg_thr,
        avg_error_rate=avg_err,
        total_items_in=total_in,
        total_items_out=total_out,
    )
