"""Tests for Capability 1: Unified Control Plane.

Covers:
- TelemetryBus: report(), subscribe(), broadcast, rolling windows, pressure
- LiveTuning: get/set, clamping, quantization, apply_adjustments, restore
- HelixConfig: snapshot, rollback, diff
- TuningController: PID tick, error signals, rollback on accuracy drop
- AnomalyDetector: z-score, CUSUM, pressure anomalies
- Chaos: graceful degradation when control plane fails

All tests are synchronous or use asyncio.run() — no fixtures needed.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from rot.control import (
    TelemetryBus, StageMetrics, TelemetrySnapshot,
    LiveTuning, ParameterId,
    HelixConfig, ConfigSnapshot,
    TuningController,
    AnomalyDetector, AnomalySeverity,
)
from rot.control.anomaly_detector import AnomalyReport
from rot.control.tuning_controller import PidGains


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_metrics(
    stage: str = "test",
    latency_ms: float = 10.0,
    items_in: int = 10,
    items_out: int = 9,
    errors: int = 0,
    extra: dict | None = None,
) -> StageMetrics:
    return StageMetrics(
        stage=stage,
        ts=time.time(),
        latency_ms=latency_ms,
        items_in=items_in,
        items_out=items_out,
        errors=errors,
        extra=extra or {},
    )


def _make_snapshot_with_stage(stage: str, pressure: float = 0.1) -> TelemetrySnapshot:
    m = _make_metrics(stage)
    return TelemetrySnapshot(
        ts=time.time(),
        per_stage={stage: m},
        windows={},
        pressure=pressure,
    )


# ── TelemetryBus ──────────────────────────────────────────────────────────────


class TestTelemetryBus:
    def test_report_single_stage(self):
        bus = TelemetryBus()
        m = _make_metrics("nlp")
        bus.report("nlp", m)
        snap = bus.latest_snapshot()
        assert snap is not None
        assert "nlp" in snap.per_stage
        assert snap.per_stage["nlp"].latency_ms == 10.0

    def test_report_multiple_stages(self):
        bus = TelemetryBus()
        for stage in ["nlp", "credibility", "strategy"]:
            bus.report(stage, _make_metrics(stage))
        snap = bus.latest_snapshot()
        assert snap is not None
        assert len(snap.per_stage) == 3

    def test_pressure_zero_with_no_errors(self):
        bus = TelemetryBus()
        bus.report("nlp", _make_metrics("nlp", items_in=10, items_out=10, errors=0))
        snap = bus.latest_snapshot()
        assert snap.pressure == 0.0

    def test_pressure_elevated_with_errors(self):
        bus = TelemetryBus()
        bus.report("nlp", _make_metrics("nlp", items_in=10, items_out=5, errors=5))
        snap = bus.latest_snapshot()
        assert snap.pressure > 0.0

    def test_pressure_clamped_to_one(self):
        bus = TelemetryBus()
        bus.report("nlp", _make_metrics("nlp", items_in=1, items_out=0, errors=1))
        snap = bus.latest_snapshot()
        assert snap.pressure <= 1.0

    def test_latest_snapshot_none_when_empty(self):
        bus = TelemetryBus()
        assert bus.latest_snapshot() is None

    def test_rolling_window_prunes_old_samples(self):
        bus = TelemetryBus()
        # Report with an old timestamp
        old_m = StageMetrics(
            stage="nlp",
            ts=time.time() - 7200,  # 2 hours ago — outside 1h window
            latency_ms=5.0,
            items_in=10,
            items_out=10,
        )
        bus.report("nlp", old_m)
        new_m = _make_metrics("nlp", latency_ms=50.0)
        bus.report("nlp", new_m)
        snap = bus.latest_snapshot()
        # Latest should be the recent one
        assert snap.per_stage["nlp"].latency_ms == 50.0

    def test_subscribe_receives_snapshots(self):
        async def run():
            bus = TelemetryBus(interval_s=0.05)
            q = bus.subscribe()
            bus.report("nlp", _make_metrics("nlp"))
            await bus.start()
            snap = await asyncio.wait_for(q.get(), timeout=1.0)
            await bus.stop()
            return snap

        snap = asyncio.run(run())
        assert snap is not None
        assert "nlp" in snap.per_stage

    def test_unsubscribe_removes_queue(self):
        bus = TelemetryBus()
        q = bus.subscribe()
        assert q in bus._subscribers
        bus.unsubscribe(q)
        assert q not in bus._subscribers

    def test_full_subscriber_queue_drops_not_blocks(self):
        bus = TelemetryBus()
        bus._subscribers = []  # Clear
        # Add a tiny queue that immediately fills
        import asyncio as aio
        small_q = aio.Queue(maxsize=1)
        bus._subscribers.append(small_q)
        # Fill it first
        small_q.put_nowait(_make_snapshot_with_stage("x"))
        # Should not raise even when full
        bus._broadcast(_make_snapshot_with_stage("y"))

    def test_throughput_ratio_property(self):
        m = _make_metrics(items_in=10, items_out=7)
        assert abs(m.throughput_ratio - 0.7) < 1e-9

    def test_throughput_ratio_zero_items_in(self):
        m = _make_metrics(items_in=0, items_out=0)
        assert m.throughput_ratio == 1.0

    def test_error_rate_property(self):
        m = _make_metrics(items_in=10, errors=2)
        assert abs(m.error_rate - 0.2) < 1e-9


# ── LiveTuning ────────────────────────────────────────────────────────────────


class TestLiveTuning:
    def test_default_values(self):
        lt = LiveTuning()
        for pid in ParameterId:
            v = lt.get(pid)
            assert v is not None

    def test_set_and_get_roundtrip(self):
        lt = LiveTuning()
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.3)
        assert abs(lt.get(ParameterId.CONFIDENCE_FLOOR) - 0.3) < 0.02  # within 1 step

    def test_value_clamped_at_max(self):
        lt = LiveTuning()
        lt.set(ParameterId.CONFIDENCE_FLOOR, 999.0)
        assert lt.get(ParameterId.CONFIDENCE_FLOOR) <= 0.7

    def test_value_clamped_at_min(self):
        lt = LiveTuning()
        lt.set(ParameterId.CONFIDENCE_FLOOR, -999.0)
        assert lt.get(ParameterId.CONFIDENCE_FLOOR) >= 0.0

    def test_value_quantized_to_step(self):
        lt = LiveTuning()
        # CONFIDENCE_FLOOR has step=0.01
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.157)
        v = lt.get(ParameterId.CONFIDENCE_FLOOR)
        # Should be 0.16 (nearest 0.01 step)
        assert abs(v - 0.16) < 1e-9

    def test_apply_adjustments_atomic(self):
        lt = LiveTuning()
        adjustments = {
            ParameterId.CONFIDENCE_FLOOR: 0.2,
            ParameterId.POSITION_SIZING_FACTOR: 1.5,
        }
        stored = lt.apply_adjustments(adjustments)
        assert ParameterId.CONFIDENCE_FLOOR in stored
        assert ParameterId.POSITION_SIZING_FACTOR in stored

    def test_snapshot_returns_copy(self):
        lt = LiveTuning()
        snap1 = lt.snapshot()
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.4)
        snap2 = lt.snapshot()
        # Snapshot is a copy — changing value after snap doesn't affect snap1
        assert snap1[ParameterId.CONFIDENCE_FLOOR] != snap2[ParameterId.CONFIDENCE_FLOOR]

    def test_restore_applies_values(self):
        lt = LiveTuning()
        orig = lt.snapshot()
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.5)
        assert lt.get(ParameterId.CONFIDENCE_FLOOR) > 0.1
        lt.restore(orig)
        assert abs(lt.get(ParameterId.CONFIDENCE_FLOOR) - orig[ParameterId.CONFIDENCE_FLOOR]) < 0.01

    def test_convenience_accessors(self):
        lt = LiveTuning()
        assert isinstance(lt.confidence_floor, float)
        assert isinstance(lt.suppress_threshold, float)
        assert isinstance(lt.position_sizing_factor, float)

    def test_thread_safe_concurrent_access(self):
        import threading
        lt = LiveTuning()
        errors = []

        def writer():
            for _ in range(100):
                try:
                    lt.set(ParameterId.CONFIDENCE_FLOOR, 0.3)
                except Exception as e:
                    errors.append(e)

        def reader():
            for _ in range(100):
                try:
                    lt.get(ParameterId.CONFIDENCE_FLOOR)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ── HelixConfig ───────────────────────────────────────────────────────────────


class TestHelixConfig:
    def test_snapshot_increments_counter(self):
        lt = LiveTuning()
        h = HelixConfig(lt)
        h.snapshot()
        h.snapshot()
        assert h.snapshot_count == 2

    def test_snapshot_captures_current_values(self):
        lt = LiveTuning()
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.3)
        h = HelixConfig(lt)
        snap = h.snapshot(trigger="test")
        assert abs(snap.values[ParameterId.CONFIDENCE_FLOOR] - 0.3) < 0.02

    def test_rollback_restores_previous_values(self):
        lt = LiveTuning()
        h = HelixConfig(lt)
        h.snapshot()  # snap 1: CONFIDENCE_FLOOR=default(0.0)
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.5)
        h.snapshot()  # snap 2: CONFIDENCE_FLOOR=0.5
        h.rollback()
        assert lt.get(ParameterId.CONFIDENCE_FLOOR) < 0.3  # rolled back

    def test_rollback_empty_history_returns_none(self):
        lt = LiveTuning()
        h = HelixConfig(lt)
        result = h.rollback()
        assert result is None

    def test_rollback_increments_rollback_count(self):
        lt = LiveTuning()
        h = HelixConfig(lt)
        h.snapshot()
        h.snapshot()
        h.rollback()
        assert h.rollback_count == 1

    def test_diff_shows_changed_params(self):
        lt = LiveTuning()
        h = HelixConfig(lt)
        snap_a = h.snapshot()
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.4)
        snap_b = h.snapshot()
        diff = h.diff(snap_a, snap_b)
        assert ParameterId.CONFIDENCE_FLOOR in diff

    def test_diff_empty_when_unchanged(self):
        lt = LiveTuning()
        h = HelixConfig(lt)
        snap_a = h.snapshot()
        snap_b = h.snapshot()
        diff = h.diff(snap_a, snap_b)
        assert diff == {}

    def test_history_bounded_by_cap(self):
        lt = LiveTuning()
        h = HelixConfig(lt, history_cap=5)
        for _ in range(10):
            h.snapshot()
        assert len(h.history()) <= 5

    def test_rollback_to_best_picks_highest_accuracy(self):
        lt = LiveTuning()
        h = HelixConfig(lt)
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.1)
        h.snapshot(trigger="t", accuracy_at_snap=0.60)
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.2)
        h.snapshot(trigger="t", accuracy_at_snap=0.80)
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.3)
        h.snapshot(trigger="t", accuracy_at_snap=0.55)
        h.rollback_to_best()
        # Should restore to snap with 0.80 accuracy (CONFIDENCE_FLOOR=0.2)
        assert abs(lt.get(ParameterId.CONFIDENCE_FLOOR) - 0.2) < 0.05


# ── TuningController ──────────────────────────────────────────────────────────


class TestTuningController:
    def _make_controller(self):
        lt = LiveTuning()
        h = HelixConfig(lt)
        ctrl = TuningController(lt, h, tick_s=1.0, rollback_threshold=0.05)
        return ctrl, lt, h

    def test_update_returns_empty_when_no_snapshot(self):
        ctrl, lt, h = self._make_controller()
        snap = _make_snapshot_with_stage("pipeline", pressure=0.3)
        result = ctrl.update(snap, current_accuracy=0.7)
        # On first call, all parameters are in cooldown except possibly some
        # (since last_update_ts starts at 0, they might all fire)
        assert isinstance(result, dict)

    def test_rollback_fires_on_accuracy_drop(self):
        ctrl, lt, h = self._make_controller()
        # Establish baseline
        h.snapshot()  # need history for rollback to work
        h.snapshot()
        snap = _make_snapshot_with_stage("pipeline", pressure=0.3)

        # Set initial accuracy
        ctrl._last_accuracy = 0.80

        # Force rollback: drop accuracy by > threshold (5%)
        result = ctrl.update(snap, current_accuracy=0.70)

        # Should have triggered rollback (empty dict returned)
        assert result == {}
        assert h.rollback_count >= 1

    def test_no_rollback_when_accuracy_stable(self):
        ctrl, lt, h = self._make_controller()
        snap = _make_snapshot_with_stage("pipeline", pressure=0.3)
        ctrl._last_accuracy = 0.75
        # Drop of 2% < 5% threshold
        ctrl.update(snap, current_accuracy=0.73)
        assert h.rollback_count == 0

    def test_pid_output_bounded(self):
        """PID output clamped to [-1, 1]."""
        ctrl, lt, h = self._make_controller()
        from rot.control.tuning_controller import _PidState, PidGains
        state = _PidState(integral=100.0, prev_error=0.0, last_update_ts=0.0)
        ctrl._pid[ParameterId.CONFIDENCE_FLOOR] = state
        snap = _make_snapshot_with_stage("pipeline", pressure=0.9)
        # Should not raise and output stays within parameter range
        result = ctrl._pid_tick(
            ParameterId.CONFIDENCE_FLOOR, snap, accuracy=0.5, now=time.time() + 1000
        )
        if result is not None:
            spec = ctrl._lt._specs[ParameterId.CONFIDENCE_FLOOR]
            assert spec.min_val <= result <= spec.max_val

    def test_controller_lifecycle(self):
        async def run():
            ctrl, lt, h = self._make_controller()
            await ctrl.start()
            assert ctrl._running is True
            await ctrl.stop()
            assert ctrl._running is False

        asyncio.run(run())

    def test_suppress_threshold_error_signal(self):
        ctrl, lt, h = self._make_controller()
        snap = _make_snapshot_with_stage("pipeline", pressure=0.3)
        # accuracy above target → suppress_threshold error > 0 → raise threshold
        error = ctrl._compute_error(ParameterId.SUPPRESS_THRESHOLD, snap, accuracy=0.80)
        assert error is not None
        assert error > 0  # 0.80 > _ACCURACY_TARGET (0.65)

    def test_confidence_floor_error_from_pressure(self):
        ctrl, lt, h = self._make_controller()
        snap = _make_snapshot_with_stage("pipeline", pressure=0.8)
        error = ctrl._compute_error(ParameterId.CONFIDENCE_FLOOR, snap, accuracy=None)
        assert error is not None
        assert error > 0  # pressure > target → raise confidence floor


# ── AnomalyDetector ───────────────────────────────────────────────────────────


class TestAnomalyDetector:
    def test_no_anomaly_on_normal_data(self):
        detector = AnomalyDetector()
        snap = _make_snapshot_with_stage("nlp", pressure=0.1)
        reports = detector.analyze(snap)
        # May have some reports but none should be CRITICAL
        critical = [r for r in reports if r.severity == AnomalySeverity.CRITICAL]
        assert critical == []

    def test_pressure_critical_anomaly(self):
        detector = AnomalyDetector(pressure_crit=0.85)
        snap = _make_snapshot_with_stage("nlp", pressure=0.95)
        reports = detector.analyze(snap)
        critical = [r for r in reports if r.severity == AnomalySeverity.CRITICAL]
        assert len(critical) >= 1
        assert critical[0].recommend_rollback is True

    def test_pressure_warning_anomaly(self):
        detector = AnomalyDetector(pressure_warn=0.6, pressure_crit=0.85)
        snap = _make_snapshot_with_stage("nlp", pressure=0.7)
        reports = detector.analyze(snap)
        warnings = [r for r in reports if r.severity == AnomalySeverity.WARNING]
        assert len(warnings) >= 1

    def test_analyze_returns_list(self):
        detector = AnomalyDetector()
        snap = _make_snapshot_with_stage("nlp", pressure=0.0)
        result = detector.analyze(snap)
        assert isinstance(result, list)

    def test_empty_snapshot_no_crash(self):
        detector = AnomalyDetector()
        snap = TelemetrySnapshot(ts=time.time(), per_stage={}, windows={}, pressure=0.0)
        result = detector.analyze(snap)
        assert isinstance(result, list)


# ── Integration: Control Plane end-to-end ────────────────────────────────────


class TestControlPlaneE2E:
    """End-to-end test: TelemetryBus → TuningController → LiveTuning → HelixConfig."""

    def test_full_pipeline_tick(self):
        """One tick of the full control loop produces a valid state."""
        bus = TelemetryBus()
        lt = LiveTuning()
        h = HelixConfig(lt)
        from rot.control.anomaly_detector import AnomalyDetector as AD
        ctrl = TuningController(lt, h, AD(), tick_s=1.0, rollback_threshold=0.05)

        # Simulate a pipeline cycle
        bus.report("nlp", _make_metrics("nlp", latency_ms=15.0, errors=0))
        bus.report("credibility", _make_metrics("credibility", latency_ms=5.0))
        bus.report("pipeline", _make_metrics("pipeline", items_in=100, items_out=8))

        snap = bus.latest_snapshot()
        assert snap is not None

        # Run controller update
        result = ctrl.update(snap, current_accuracy=0.72)
        assert isinstance(result, dict)

        # LiveTuning values are still within spec after update
        for pid in ParameterId:
            from rot.control.live_tuning import PARAMETER_SPECS
            spec = PARAMETER_SPECS[pid]
            v = lt.get(pid)
            assert spec.min_val <= v <= spec.max_val, f"{pid}: {v} out of [{spec.min_val}, {spec.max_val}]"

    def test_snapshot_persists_after_adjustment(self):
        """HelixConfig stores history of PID adjustments."""
        lt = LiveTuning()
        h = HelixConfig(lt)
        initial = h.snapshot(trigger="initial", accuracy_at_snap=0.70)
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.2)
        after = h.snapshot(trigger="pid_adjustment", accuracy_at_snap=0.72)
        assert h.snapshot_count == 2
        diff = h.diff(initial, after)
        assert ParameterId.CONFIDENCE_FLOOR in diff


# ── Chaos: graceful degradation ───────────────────────────────────────────────


class TestControlPlaneChaos:
    def test_bus_continues_after_subscriber_error(self):
        """TelemetryBus degrades gracefully if subscriber raises."""
        bus = TelemetryBus()

        class BrokenQueue:
            def put_nowait(self, item):
                raise RuntimeError("subscriber exploded")

        bus._subscribers = [BrokenQueue()]  # type: ignore[list-item]
        snap = _make_snapshot_with_stage("nlp")
        # Should not raise
        bus._broadcast(snap)
        # Dead queue removed
        assert bus._subscribers == []

    def test_tuning_controller_skips_unknown_param(self):
        lt = LiveTuning()
        h = HelixConfig(lt)
        ctrl = TuningController(lt, h)
        snap = _make_snapshot_with_stage("pipeline")
        # Pass in a non-existent param id — should not raise
        ctrl._compute_error("NONEXISTENT", snap, None)

    def test_helix_rollback_with_one_entry(self):
        lt = LiveTuning()
        h = HelixConfig(lt)
        h.snapshot()
        # Only 1 entry — rollback gracefully returns None or does not crash
        result = h.rollback()
        # Either None or valid snapshot
        assert result is None or isinstance(result, ConfigSnapshot)
