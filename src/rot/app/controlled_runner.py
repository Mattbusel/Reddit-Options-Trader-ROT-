"""ControlledPipelineRunner — PipelineRunner extended with the Unified Control Plane.

Wraps the existing PipelineRunner with three new capability layers:

1. **Control Plane** (Capability 1)
   - Reports StageMetrics to TelemetryBus after each stage
   - Reads LiveTuning parameters at the start of each cycle and applies
     them to credibility scorer, NLP threshold, strategy selector, etc.
   - TuningController runs in background, adjusting params via PID

2. **AttentionRadar** (Capability 2)
   - Records mention volume per ticker during trend detection
   - Checks each scored event against fire conditions (confidence ≥ 0.88,
     event_type == "other", volume z-score > 2σ)
   - Enqueues radar events for async DB persistence

3. **StreamProcessor** (Capability 3)
   - Processes Reddit post content (title + body excerpt) as document
     chunks through the IIR/Welford pipeline
   - Fires Stage-0 pre-signals before the LLM reasoning stage
   - Enqueues pre-signals for async DB persistence

The base PipelineRunner is NEVER modified.  All new behavior is additive.
Existing tests continue to target PipelineRunner directly and are unaffected.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from rot.app.runner import PipelineRunner
from rot.control.telemetry_bus import TelemetryBus, StageMetrics
from rot.control.live_tuning import LiveTuning, ParameterId
from rot.control.helix_config import HelixConfig
from rot.control.tuning_controller import TuningController
from rot.radar.attention_radar import AttentionRadar, AttentionRadarEvent
from rot.probability.stream_processor import StreamProcessor, DocumentChunk, ChunkSource, PreSignal
from rot.core.types import Event

log = logging.getLogger(__name__)

# Approximate mention-volume multiplier: trend candidates are usually scored
# out of 100 Reddit snapshots per cycle.
_DEFAULT_CYCLE_VOLUME = 1.0


class ControlledPipelineRunner:
    """PipelineRunner instrumented with control plane, radar, and pre-signal pipeline.

    Usage::

        base = PipelineRunner(ingestor, trend, builder, cred, reasoner, trader, logger)
        runner = ControlledPipelineRunner(base, bus, live_tuning, helix, controller, radar, stream)
        await runner.start_background()   # start bus + controller tasks
        result = runner.run_once()        # synchronous, same interface as PipelineRunner
        await runner.stop_background()
    """

    def __init__(
        self,
        base: PipelineRunner,
        bus: TelemetryBus,
        live_tuning: LiveTuning,
        helix_config: HelixConfig,
        tuning_controller: TuningController,
        radar: AttentionRadar,
        stream_processor: StreamProcessor,
        current_accuracy_fn: Optional[Callable[[], Optional[float]]] = None,
        db: Optional[Any] = None,
    ) -> None:
        self._base = base
        self._bus = bus
        self._lt = live_tuning
        self._helix = helix_config
        self._controller = tuning_controller
        self._radar = radar
        self._stream = stream_processor
        self._accuracy_fn = current_accuracy_fn
        self._db = db

        # Queues for async DB persistence (filled synchronously, drained by bg tasks)
        self._radar_queue: asyncio.Queue[AttentionRadarEvent] = asyncio.Queue(maxsize=500)
        self._presignal_queue = stream_processor.presignal_queue

        # Background task handles
        self._bg_tasks: List[asyncio.Task] = []  # type: ignore[type-arg]
        self._running = False

        # Volume tracking: ticker → mention count this cycle (for radar)
        self._cycle_volumes: Dict[str, float] = {}

        # Circuit breaker: if new modules raise, log and continue
        self._control_enabled = True
        self._radar_enabled = True
        self._stream_enabled = True

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start_background(self) -> None:
        """Start background tasks: TelemetryBus, TuningController, DB writers."""
        self._running = True
        await self._bus.start()
        await self._controller.start()

        if self._db is not None:
            self._bg_tasks.append(asyncio.create_task(self._radar_db_writer()))
            self._bg_tasks.append(asyncio.create_task(self._presignal_db_writer()))

        log.info("ControlledPipelineRunner: background tasks started")

    async def stop_background(self) -> None:
        """Stop all background tasks gracefully."""
        self._running = False
        await self._controller.stop()
        await self._bus.stop()
        for t in self._bg_tasks:
            t.cancel()
            try:
                await t
            except Exception:
                pass
        self._bg_tasks.clear()
        log.info("ControlledPipelineRunner: background tasks stopped")

    # ── Main pipeline entry point ─────────────────────────────────────────────

    def run_once(self) -> dict:
        """Run one pipeline cycle with full instrumentation.

        Intercepts the base runner's data flow at two points:
        - After ingest/trend: pass snapshots to StreamProcessor + RadarVolumeTracker
        - After credibility scoring: check each event against AttentionRadar

        All interception is via temporary method patches that are restored
        before this method returns, so the base runner state is never mutated.
        """
        # 1. Apply live tuning parameters to pipeline stages
        if self._control_enabled:
            try:
                self._apply_live_tuning()
            except Exception as exc:
                log.warning("ControlledPipelineRunner: live_tuning apply failed: %s", exc)

        # 2. Instrument the trend engine to capture snapshot volumes and
        #    feed them to the StreamProcessor
        orig_detect = self._base.trend_engine.detect

        def patched_detect(snapshots: list) -> list:
            if self._stream_enabled:
                try:
                    self._stream_ingest_snapshots(snapshots)
                except Exception as exc:
                    log.warning("ControlledPipelineRunner: stream ingest failed: %s", exc)
            if self._radar_enabled:
                try:
                    self._record_radar_volumes(snapshots)
                except Exception as exc:
                    log.warning("ControlledPipelineRunner: radar volume record failed: %s", exc)
            return orig_detect(snapshots)

        self._base.trend_engine.detect = patched_detect  # type: ignore[method-assign]

        # 3. Instrument credibility scorer to check AttentionRadar
        orig_score = self._base.cred.score

        def patched_score(event: Event) -> Event:
            scored = orig_score(event)
            if self._radar_enabled:
                try:
                    ticker = scored.entities[0] if scored.entities else "UNKNOWN"
                    volume = self._cycle_volumes.get(ticker, _DEFAULT_CYCLE_VOLUME)
                    _, radar_event = self._radar.check(scored, signal_volume=volume)
                    if radar_event is not None:
                        try:
                            self._radar_queue.put_nowait(radar_event)
                        except asyncio.QueueFull:
                            log.debug("ControlledPipelineRunner: radar queue full")
                except Exception as exc:
                    log.warning("ControlledPipelineRunner: radar check failed: %s", exc)
            return scored

        self._base.cred.score = patched_score  # type: ignore[method-assign]

        # 4. Run the base pipeline
        t0 = time.time()
        try:
            result = self._base.run_once()
        finally:
            # Restore original methods — critical, must happen even on exception
            self._base.trend_engine.detect = orig_detect  # type: ignore[method-assign]
            self._base.cred.score = orig_score  # type: ignore[method-assign]

        latency_ms = (time.time() - t0) * 1000.0

        # 5. Report telemetry to the bus
        if self._control_enabled:
            try:
                self._report_telemetry(result, latency_ms)
            except Exception as exc:
                log.warning("ControlledPipelineRunner: telemetry report failed: %s", exc)

        # 6. Drive TuningController with latest snapshot + accuracy
        if self._control_enabled:
            try:
                snap = self._bus.latest_snapshot()
                if snap is not None:
                    accuracy = self._accuracy_fn() if self._accuracy_fn else None
                    self._controller.update(snap, accuracy)
            except Exception as exc:
                log.warning("ControlledPipelineRunner: controller update failed: %s", exc)

        return result

    # ── Live tuning parameter application ────────────────────────────────────

    def _apply_live_tuning(self) -> None:
        """Push LiveTuning parameter values into stage configurations.

        Each stage attribute update is wrapped in its own try/except so a
        missing attribute on one stage never blocks the others.
        """
        # Stage 6.5: suppress_threshold → SignalSuppressor.threshold
        suppress_t = self._lt.get(ParameterId.SUPPRESS_THRESHOLD)
        if self._base.suppressor is not None:
            try:
                self._base.suppressor.threshold = suppress_t
            except AttributeError:
                pass

        # Stage 3: source_weight_multiplier → CredibilityScorer
        src_mult = self._lt.get(ParameterId.SOURCE_WEIGHT_MULTIPLIER)
        try:
            self._base.cred._source_weight_mult = src_mult  # type: ignore[attr-defined]
        except AttributeError:
            pass

        # Stage 4: confidence_floor → PipelineRunner (applied in event filtering)
        # Stored on the runner itself so downstream logic can read it
        self._base._confidence_floor = self._lt.get(ParameterId.CONFIDENCE_FLOOR)  # type: ignore[attr-defined]

    # ── Stream processor integration ──────────────────────────────────────────

    def _stream_ingest_snapshots(self, snapshots: list) -> None:
        """Feed Reddit ThreadSnapshot content through the StreamProcessor."""
        for snap in snapshots:
            post = getattr(snap, "post", None)
            if post is None:
                continue

            ticker = _extract_primary_ticker(snap)
            if not ticker:
                continue

            doc_id = getattr(post, "id", "") or getattr(post, "permalink", "")
            title = getattr(post, "title", "") or ""
            body = getattr(post, "selftext", "") or ""
            full_text = f"{title} {body}".strip()

            if not full_text:
                continue

            words = full_text.split()
            n = len(words)
            for i, word in enumerate(words):
                is_final = i == n - 1
                chunk = DocumentChunk(
                    ticker=ticker,
                    source=ChunkSource.REDDIT,
                    text=word,
                    doc_id=doc_id,
                    chunk_index=i,
                    is_final=is_final,
                    ts=time.time(),
                )
                self._stream.process_chunk(chunk)

    # ── Radar volume tracking ─────────────────────────────────────────────────

    def _record_radar_volumes(self, snapshots: list) -> None:
        """Count mentions per ticker and record baseline for AttentionRadar."""
        counts: Dict[str, float] = {}
        for snap in snapshots:
            ticker = _extract_primary_ticker(snap)
            if ticker:
                counts[ticker] = counts.get(ticker, 0) + 1

        now = time.time()
        for ticker, count in counts.items():
            self._radar.record_volume(ticker, count, ts=now)

        self._cycle_volumes = counts

    # ── Telemetry reporting ───────────────────────────────────────────────────

    def _report_telemetry(self, result: dict, latency_ms: float) -> None:
        """Report pipeline-level StageMetrics to TelemetryBus."""
        now = time.time()

        # Overall pipeline stage
        self._bus.report("pipeline", StageMetrics(
            stage="pipeline",
            ts=now,
            latency_ms=latency_ms,
            items_in=result.get("snapshots", 0),
            items_out=result.get("trade_ideas", 0),
            errors=0,
            extra={
                "suppressed": float(result.get("suppressed", 0)),
                "candidates": float(result.get("candidates", 0)),
                "events": float(result.get("events", 0)),
                "stubs_skipped": float(result.get("stubs_skipped", 0)),
            },
        ))

        # Suppression gate (Stage 6.5)
        suppressed = result.get("suppressed", 0)
        total_events = result.get("events", 0)
        self._bus.report("suppression", StageMetrics(
            stage="suppression",
            ts=now,
            latency_ms=0.0,
            items_in=total_events,
            items_out=total_events - suppressed,
            errors=0,
            extra={"suppressed_count": float(suppressed)},
        ))

        # Stream processor stats
        if self._stream_enabled:
            self._bus.report("stream_processor", StageMetrics(
                stage="stream_processor",
                ts=now,
                latency_ms=0.0,
                items_in=self._stream.chunks_processed,
                items_out=self._stream.presignal_count,
                errors=0,
            ))

        # Radar stats
        if self._radar_enabled:
            self._bus.report("radar", StageMetrics(
                stage="radar",
                ts=now,
                latency_ms=0.0,
                items_in=total_events,
                items_out=self._radar.fired_count,
                errors=0,
            ))

    # ── Background DB writers ─────────────────────────────────────────────────

    async def _radar_db_writer(self) -> None:
        """Drain the radar event queue and persist to SQLite."""
        while self._running:
            try:
                radar_ev: AttentionRadarEvent = await asyncio.wait_for(
                    self._radar_queue.get(), timeout=1.0
                )
                if self._db is not None:
                    await self._db.save_radar_event(
                        ticker=radar_ev.ticker,
                        timestamp=radar_ev.timestamp,
                        confidence=radar_ev.confidence,
                        signal_volume_zscore=radar_ev.signal_volume_zscore,
                        event_type=radar_ev.event_type,
                        stance=radar_ev.stance,
                        source_signal_id=radar_ev.source_signal_id,
                        meta=radar_ev.meta,
                    )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("ControlledPipelineRunner._radar_db_writer: %s", exc)

    async def _presignal_db_writer(self) -> None:
        """Drain the presignal queue and persist to SQLite."""
        while self._running:
            try:
                ps: PreSignal = await asyncio.wait_for(
                    self._presignal_queue.get(), timeout=1.0
                )
                if self._db is not None:
                    await self._db.save_pre_signal(
                        ticker=ps.ticker,
                        timestamp=ps.ts,
                        source=ps.source.value,
                        doc_id=ps.doc_id,
                        pre_signal_confidence=ps.confidence,
                        pre_signal_direction=ps.direction,
                        iir_value=ps.iir_value,
                        variance=ps.variance,
                        chunks_at_fire=ps.chunks_processed,
                    )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("ControlledPipelineRunner._presignal_db_writer: %s", exc)

    # ── Circuit breaker controls ──────────────────────────────────────────────

    def disable_control_plane(self) -> None:
        """Disable PID tuning (control plane degrades gracefully)."""
        self._control_enabled = False

    def disable_radar(self) -> None:
        """Disable AttentionRadar (degrades gracefully)."""
        self._radar_enabled = False

    def disable_stream_processor(self) -> None:
        """Disable StreamProcessor (degrades gracefully)."""
        self._stream_enabled = False

    def enable_all(self) -> None:
        """Re-enable all capability layers."""
        self._control_enabled = True
        self._radar_enabled = True
        self._stream_enabled = True

    # ── Pass-through properties ───────────────────────────────────────────────

    @property
    def suppressor(self):  # type: ignore[return]
        return self._base.suppressor

    @suppressor.setter
    def suppressor(self, v: Any) -> None:
        self._base.suppressor = v

    @property
    def on_signal(self):  # type: ignore[return]
        return self._base.on_signal

    @on_signal.setter
    def on_signal(self, v: Any) -> None:
        self._base.on_signal = v


# ── Factory ───────────────────────────────────────────────────────────────────


def build_controlled_runner(
    base: PipelineRunner,
    db: Optional[Any] = None,
    current_accuracy_fn: Optional[Callable[[], Optional[float]]] = None,
) -> ControlledPipelineRunner:
    """Convenience factory: build a ControlledPipelineRunner with sensible defaults.

    Args:
        base: An already-constructed PipelineRunner.
        db: Optional Database instance for DB persistence.
        current_accuracy_fn: Callable returning current signal win rate [0,1].

    Returns:
        A ready-to-use ControlledPipelineRunner.  Call
        ``await runner.start_background()`` before the first ``run_once()``.
    """
    from rot.control.anomaly_detector import AnomalyDetector

    bus = TelemetryBus(interval_s=5.0)
    live_tuning = LiveTuning()
    helix = HelixConfig(live_tuning)
    anomaly_detector = AnomalyDetector()
    controller = TuningController(
        live_tuning=live_tuning,
        helix_config=helix,
        anomaly_detector=anomaly_detector,
        tick_s=30.0,
        rollback_threshold=0.05,
    )
    radar = AttentionRadar()
    stream_proc = StreamProcessor()

    return ControlledPipelineRunner(
        base=base,
        bus=bus,
        live_tuning=live_tuning,
        helix_config=helix,
        tuning_controller=controller,
        radar=radar,
        stream_processor=stream_proc,
        current_accuracy_fn=current_accuracy_fn,
        db=db,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_primary_ticker(snapshot: Any) -> Optional[str]:
    """Extract the primary ticker from a TrendCandidate or ThreadSnapshot."""
    # TrendCandidate has .snapshot.post or .ticker attribute
    try:
        return snapshot.ticker  # type: ignore[attr-defined]
    except AttributeError:
        pass
    try:
        return snapshot.snapshot.post.title  # type: ignore[attr-defined]
    except AttributeError:
        pass
    return None
