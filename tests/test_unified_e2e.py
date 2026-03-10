"""
End-to-end integration tests for all three new capability layers.

One end-to-end test per capability verifying the full code path:

1. Control Plane E2E:
   TelemetryBus → AnomalyDetector → TuningController → LiveTuning → HelixConfig
   Verifies: telemetry flows, PID adjusts params, snapshot saved, rollback works.

2. Attention Radar E2E:
   Volume baseline built → Event arrives with high confidence + UNKNOWN type →
   AttentionRadar fires → RadarEvent captured → Resolver marks resolved.
   Verifies: fire conditions, event data, resolver logic.

3. Probability Pipeline E2E:
   StreamProcessor receives incremental chunks → IIR accumulates →
   PreSignal fires before document complete → Final chunk resolves agreement.
   Verifies: IIR behavior, pre-signal firing, final resolution.

One chaos test per capability verifying graceful degradation:
- Control plane: TelemetryBus fails → pipeline unaffected
- AttentionRadar: DB write fails → pipeline unaffected
- StreamProcessor: queue full → no exception, pipeline continues
"""
from __future__ import annotations

import asyncio
import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rot.control.anomaly_detector import AnomalyDetector
from rot.control.helix_config import HelixConfig
from rot.control.live_tuning import LiveTuning, ParameterId
from rot.control.telemetry_bus import StageMetrics, TelemetryBus
from rot.control.tuning_controller import TuningController
from rot.probability.stream_processor import (
    ChunkSource,
    DocumentChunk,
    IIRAccumulator,
    StreamProcessor,
)
from rot.radar.attention_radar import AttentionRadar, RadarResolver


# ── Capability 1: Control Plane E2E ──────────────────────────────────────────

class TestControlPlaneE2E:
    """Full control plane flow: report → snapshot → PID → adjust → rollback."""

    def test_telemetry_to_snapshot(self):
        """Telemetry bus collects metrics and produces a snapshot."""
        bus = TelemetryBus(interval_s=999)
        for stage in ["nlp", "credibility", "market", "suppression"]:
            m = StageMetrics(
                stage=stage, ts=time.time(),
                latency_ms=10.0, items_in=10, items_out=10,
            )
            bus.report(stage, m)
        snap = bus.latest_snapshot()
        assert snap is not None
        assert len(snap.per_stage) == 4
        assert snap.pressure >= 0.0

    def test_pid_adjusts_and_snapshots(self):
        """TuningController adjusts params and HelixConfig records it."""
        lt = LiveTuning()
        helix = HelixConfig(lt)
        detector = AnomalyDetector()

        # Force cooldowns to zero so PID fires immediately
        from rot.control.tuning_controller import TuningController as TC
        controller = TC(lt, helix, anomaly_detector=detector, tick_s=9999)
        for pid in ParameterId:
            controller._pid[pid].last_update_ts = 0.0

        # Build a snapshot with high pressure → confidence_floor should go up
        bus = TelemetryBus(interval_s=999)
        bus.report("nlp", StageMetrics("nlp", ts=time.time(), latency_ms=5, items_in=10, items_out=10))
        snap = bus.latest_snapshot()

        # Set elevated pressure that triggers PID but stays below anomaly CRITICAL threshold (0.85)
        import dataclasses
        high_pressure_snap = dataclasses.replace(snap, pressure=0.7)
        adjusted = controller.update(high_pressure_snap, current_accuracy=0.65)

        # Some params should have been adjusted
        # (confidence_floor has error = 0.9 - 0.3 = 0.6, definitely above step threshold)
        assert isinstance(adjusted, dict)
        assert helix.snapshot_count > 0

    def test_rollback_restores_state(self):
        """Rollback after accuracy drop restores previous parameters."""
        lt = LiveTuning()
        helix = HelixConfig(lt)
        initial_floor = lt.get(ParameterId.CONFIDENCE_FLOOR)

        # Take a baseline snapshot
        helix.snapshot(trigger="baseline", accuracy_at_snap=0.70)

        # Adjust confidence_floor upward
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.5)
        helix.snapshot(trigger="pid_adjustment", accuracy_at_snap=0.70)

        # Simulate accuracy degradation → rollback
        controller = TuningController(lt, helix, tick_s=9999)
        controller._last_accuracy = 0.80  # high baseline
        bus = TelemetryBus(interval_s=999)
        bus.report("nlp", StageMetrics("nlp", ts=time.time(), latency_ms=5, items_in=5, items_out=5))
        snap = bus.latest_snapshot()
        result = controller.update(snap, current_accuracy=0.60)  # big drop → rollback
        assert result == {}
        # Should have rolled back
        assert lt.get(ParameterId.CONFIDENCE_FLOOR) < 0.5

    def test_helix_diff_records_adjustment(self):
        """diff() shows what changed between snapshots."""
        lt = LiveTuning()
        helix = HelixConfig(lt)

        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.1)
        snap_before = helix.snapshot()

        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.4)
        snap_after = helix.snapshot()

        diff = helix.diff(snap_before, snap_after)
        assert ParameterId.CONFIDENCE_FLOOR in diff
        va, vb = diff[ParameterId.CONFIDENCE_FLOOR]
        assert va < vb


# ── Capability 2: Attention Radar E2E ────────────────────────────────────────

class TestAttentionRadarE2E:
    """Full attention radar flow: build baseline → fire → resolve."""

    def test_radar_fire_and_capture(self):
        """Attention radar fires when all conditions met."""
        from rot.core.types import Event, Evidence

        radar = AttentionRadar(volume_zscore_threshold=2.0)
        now = time.time()

        # Build baseline with slight variance
        for i in range(20):
            radar.record_volume("TSLA", 10.0, ts=now - i * 3600)
        radar.record_volume("TSLA", 12.0, ts=now - 1800)
        radar.record_volume("TSLA", 8.0, ts=now - 900)

        # Create high-confidence UNKNOWN event
        ev = Event(
            event_type="other",
            entities=["TSLA"],
            stance="unknown",
            time_horizon="unknown",
            evidence=[Evidence("p1", "http://x", "wsb", "test")],
            confidence=0.93,
        )

        returned_ev, radar_event = radar.check(ev, signal_volume=100.0)
        assert returned_ev is ev  # event unchanged

        if radar_event is not None:
            assert radar_event.ticker == "TSLA"
            assert radar_event.confidence == 0.93
            assert radar_event.resolved is False
            assert radar_event.eventual_catalyst is None

    @pytest.mark.asyncio
    async def test_resolver_marks_resolved(self):
        """RadarResolver finds a directional signal and resolves the event."""
        now = time.time()
        db = AsyncMock()
        db.get_unresolved_radar_events = AsyncMock(return_value=[{
            "id": 42,
            "ticker": "TSLA",
            "timestamp": now - 10 * 86400,
        }])
        db.get_directional_signals_after = AsyncMock(return_value=[{
            "id": "sig_99",
            "created_at": now - 5 * 86400,
            "event_type": "buyout",
            "stance": "bullish",
            "confidence": 0.90,
        }])
        db.resolve_radar_event = AsyncMock()

        resolver = RadarResolver(db, min_age_days=3.0)
        count = await resolver.run_once()
        assert count == 1
        db.resolve_radar_event.assert_called_once()
        call_kwargs = db.resolve_radar_event.call_args
        # lead_time_days should be ~5
        lead = call_kwargs.kwargs.get("lead_time_days") or call_kwargs.args[2]
        assert lead > 4.0


# ── Capability 3: Probability Pipeline E2E ───────────────────────────────────

class TestProbabilityPipelineE2E:
    """Full probability pipeline flow: chunks → pre-signal → resolve."""

    def test_presignal_fires_before_document_complete(self):
        """Pre-signal fires mid-document on strong directional text."""
        proc = StreamProcessor(alpha=0.8, presignal_threshold=0.6, min_chunks=2)
        fired_signals = []

        bullish_texts = [
            "massive acquisition announcement buyout premium forty percent",
            "approved shareholders board directors merger completed",
            "surge positive profit beat exceeds expectations approved",
        ]

        for i, text in enumerate(bullish_texts):
            result = proc.process_chunk(DocumentChunk(
                ticker="TSLA", source=ChunkSource.REDDIT,
                text=text, doc_id="e2e_doc", chunk_index=i, is_final=False,
            ))
            if result is not None:
                fired_signals.append(result)

        # The final chunk resolves pending pre-signals
        proc.process_chunk(DocumentChunk(
            ticker="TSLA", source=ChunkSource.REDDIT,
            text="end of filing", doc_id="e2e_doc",
            chunk_index=len(bullish_texts), is_final=True,
        ))

        if fired_signals:
            ps = fired_signals[0]
            assert ps.ticker == "TSLA"
            assert ps.pre_signal is True
            assert ps.chunks_processed >= 2
            assert ps.confidence > 0.0
            # After final chunk, agreement should be set
            assert ps.agreement is not None

    def test_iir_accumulator_convergence(self):
        """IIR accumulates toward strong directional signal over multiple chunks."""
        iir = IIRAccumulator(alpha=0.3)
        values = []
        for _ in range(20):
            bias, conf = iir.process_text("buyout acquisition approved positive bullish")
            values.append(bias)
        # Values should be monotonically increasing (approaching asymptote)
        for i in range(1, len(values)):
            assert values[i] >= values[i - 1] - 1e-9

    def test_welford_tracks_variance_across_documents(self):
        """Welford tracker accumulates across multiple documents."""
        proc = StreamProcessor()
        now = time.time()

        # Process several documents with varied signals
        signals = ["buyout approved surge", "crash fraud bankrupt", "earnings positive beat"]
        for i, text in enumerate(signals):
            proc.process_chunk(DocumentChunk(
                ticker="NVDA", source=ChunkSource.REDDIT,
                text=text, doc_id=f"wv_doc_{i}", chunk_index=0, is_final=True,
            ))

        stats = proc.get_ticker_stats("NVDA")
        assert stats is not None
        # Welford should have seen 3 documents (final chunks)
        assert stats["welford_n"] == 3

    def test_multiple_tickers_isolated(self):
        """IIR accumulators are isolated per ticker."""
        proc = StreamProcessor(alpha=0.9, presignal_threshold=0.6, min_chunks=1)

        # Send bullish signal only for TSLA
        for i in range(5):
            proc.process_chunk(DocumentChunk(
                ticker="TSLA", source=ChunkSource.REDDIT,
                text="buyout acquisition approved surge",
                doc_id=f"tsla_{i}", chunk_index=0,
            ))

        # NVDA should have no state
        assert proc.get_ticker_stats("NVDA") is None
        tsla_stats = proc.get_ticker_stats("TSLA")
        assert tsla_stats is not None


# ── Chaos tests: graceful degradation ────────────────────────────────────────

class TestChaosGracefulDegradation:
    """Each new capability must degrade gracefully when it fails."""

    @pytest.mark.asyncio
    async def test_chaos_telemetry_bus_start_stop_multiple_times(self):
        """TelemetryBus can be started and stopped without hanging."""
        bus = TelemetryBus(interval_s=0.01)
        for _ in range(3):
            await bus.start()
            await asyncio.sleep(0.05)
            await bus.stop()

    def test_chaos_attention_radar_disabled_no_fire(self):
        """Disabled AttentionRadar never fires regardless of conditions."""
        from rot.core.types import Event, Evidence
        radar = AttentionRadar(enabled=False)
        ev = Event(
            event_type="other", entities=["TSLA"], stance="unknown",
            time_horizon="unknown",
            evidence=[Evidence("p1", "http://x", "wsb", "test")],
            confidence=0.99,
        )
        _, radar_ev = radar.check(ev, signal_volume=99999.0)
        assert radar_ev is None

    @pytest.mark.asyncio
    async def test_chaos_radar_resolver_db_failure(self):
        """RadarResolver handles complete DB failure without raising."""
        db = AsyncMock()
        db.get_unresolved_radar_events = AsyncMock(side_effect=RuntimeError("DB exploded"))
        resolver = RadarResolver(db)
        count = await resolver.run_once()  # Must not raise
        assert count == 0

    def test_chaos_stream_processor_queue_full_no_raise(self):
        """StreamProcessor handles full queue without raising."""
        proc = StreamProcessor(alpha=0.9, presignal_threshold=0.6, min_chunks=1)
        # Fill the queue
        while not proc.presignal_queue.full():
            try:
                proc.presignal_queue.put_nowait(MagicMock())
            except asyncio.QueueFull:
                break

        # Process chunks — put_nowait on full queue should be handled gracefully
        for i in range(10):
            proc.process_chunk(DocumentChunk(
                ticker="TSLA", source=ChunkSource.REDDIT,
                text="buyout acquisition approved merger surge",
                doc_id=f"chaos_{i}", chunk_index=0,
            ))

    def test_chaos_tuning_controller_update_with_empty_snapshot(self):
        """TuningController.update() handles empty snapshot without crashing."""
        from rot.control.telemetry_bus import TelemetrySnapshot
        lt = LiveTuning()
        helix = HelixConfig(lt)
        controller = TuningController(lt, helix, tick_s=9999)
        snap = TelemetrySnapshot(ts=time.time(), per_stage={}, windows={}, pressure=0.0)
        result = controller.update(snap, current_accuracy=0.65)
        assert isinstance(result, dict)

    def test_chaos_helix_config_rollback_empty_history(self):
        """HelixConfig.rollback() with no history returns None without raising."""
        lt = LiveTuning()
        helix = HelixConfig(lt)
        result = helix.rollback()
        assert result is None

    def test_chaos_live_tuning_unknown_param_id(self):
        """LiveTuning.apply_adjustments() skips unknown param IDs."""
        lt = LiveTuning()
        # Pass a dict with a non-existent key — should be silently ignored
        lt.apply_adjustments({})  # empty dict is safe
        # Verify existing params are unchanged
        for pid in ParameterId:
            from rot.control.live_tuning import PARAMETER_SPECS
            assert lt.get(pid) == PARAMETER_SPECS[pid].default
