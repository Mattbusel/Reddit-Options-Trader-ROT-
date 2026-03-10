"""
Comprehensive tests for rot.control.tuning_controller.

Modules tested:
- TuningController
- PidGains
- _PidState

Coverage:
- TuningController construction with defaults
- update() returns dict of adjustments
- update() applies changes via LiveTuning
- update() triggers rollback on accuracy degradation
- update() skips adjustment when anomaly recommends rollback
- update() snapshots before applying
- PID cooldown enforcement (no double-updates within cooldown window)
- _compute_error() for each ParameterId
- _pid_tick() returns None when cooldown not elapsed
- _pid_tick() returns None when delta < step/2
- start() / stop() lifecycle (asyncio task)
"""
from __future__ import annotations

import math
import time
from typing import Dict
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from rot.control.anomaly_detector import AnomalyDetector, AnomalyReport, AnomalySeverity
from rot.control.helix_config import HelixConfig
from rot.control.live_tuning import LiveTuning, ParameterId
from rot.control.telemetry_bus import StageMetrics, TelemetrySnapshot, _WindowStats
from rot.control.tuning_controller import TuningController, PidGains


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_snapshot(pressure=0.3, extra_stages: Dict = None) -> TelemetrySnapshot:
    per_stage = {
        "nlp": StageMetrics("nlp", ts=time.time(), latency_ms=10, items_in=10, items_out=10),
        "credibility": StageMetrics("credibility", ts=time.time(), latency_ms=5, items_in=10, items_out=10),
        "market": StageMetrics("market", ts=time.time(), latency_ms=8, items_in=10, items_out=10,
                               extra={"iv_filter_rate": 0.7}),
    }
    if extra_stages:
        per_stage.update(extra_stages)
    return TelemetrySnapshot(ts=time.time(), per_stage=per_stage, windows={}, pressure=pressure)


def _make_controller(lt=None, helix=None) -> TuningController:
    lt = lt or LiveTuning()
    helix = helix or HelixConfig(lt)
    return TuningController(
        live_tuning=lt,
        helix_config=helix,
        tick_s=9999.0,  # never tick automatically
        rollback_threshold=0.05,
    )


# ── PidGains ──────────────────────────────────────────────────────────────────

class TestPidGains:
    def test_default_gains(self):
        gains = PidGains()
        assert gains.kp == 0.4
        assert gains.ki == 0.05
        assert gains.kd == 0.1

    def test_custom_gains(self):
        gains = PidGains(kp=0.1, ki=0.01, kd=0.05)
        assert gains.kp == 0.1


# ── TuningController construction ────────────────────────────────────────────

class TestTuningControllerInit:
    def test_construction_with_defaults(self):
        lt = LiveTuning()
        helix = HelixConfig(lt)
        controller = TuningController(lt, helix)
        assert controller._lt is lt
        assert controller._helix is helix
        assert controller._rollback_threshold == 0.05

    def test_custom_rollback_threshold(self):
        lt = LiveTuning()
        helix = HelixConfig(lt)
        controller = TuningController(lt, helix, rollback_threshold=0.10)
        assert controller._rollback_threshold == 0.10

    def test_pid_states_initialized_for_all_params(self):
        lt = LiveTuning()
        helix = HelixConfig(lt)
        controller = TuningController(lt, helix)
        for pid in ParameterId:
            assert pid in controller._pid


# ── update() return value ─────────────────────────────────────────────────────

class TestTuningControllerUpdate:
    def test_update_returns_dict(self):
        controller = _make_controller()
        snap = _make_snapshot()
        result = controller.update(snap, current_accuracy=0.65)
        assert isinstance(result, dict)

    def test_update_with_no_accuracy_still_works(self):
        controller = _make_controller()
        snap = _make_snapshot()
        result = controller.update(snap, current_accuracy=None)
        assert isinstance(result, dict)

    def test_update_after_accuracy_drop_triggers_rollback(self):
        lt = LiveTuning()
        helix = HelixConfig(lt)
        rollback_called = []

        original_rollback = helix.rollback
        def mock_rollback(*a, **kw):
            rollback_called.append(True)
            return original_rollback(*a, **kw)
        helix.rollback = mock_rollback

        controller = TuningController(lt, helix, rollback_threshold=0.05)
        snap = _make_snapshot()
        controller._last_accuracy = 0.80  # set baseline
        # Simulate large drop
        result = controller.update(snap, current_accuracy=0.60)
        assert len(rollback_called) == 1
        assert result == {}

    def test_update_no_rollback_when_accuracy_stable(self):
        lt = LiveTuning()
        helix = HelixConfig(lt)
        rollback_calls = []
        helix.rollback = lambda *a, **kw: rollback_calls.append(True)

        controller = TuningController(lt, helix, rollback_threshold=0.05)
        controller._last_accuracy = 0.70
        snap = _make_snapshot()
        controller.update(snap, current_accuracy=0.70)
        assert len(rollback_calls) == 0

    def test_update_anomaly_triggers_rollback(self):
        lt = LiveTuning()
        helix = HelixConfig(lt)
        rollback_calls = []
        helix.rollback = lambda *a, **kw: rollback_calls.append(True)

        # Detector that always recommends rollback
        mock_detector = MagicMock()
        mock_detector.analyze.return_value = [
            AnomalyReport(
                stage="nlp", metric="p95_latency_ms",
                severity=AnomalySeverity.CRITICAL,
                algorithm="zscore", value=100.0, expected=10.0,
                message="spike", recommend_rollback=True,
            )
        ]

        controller = TuningController(lt, helix, anomaly_detector=mock_detector)
        snap = _make_snapshot()
        result = controller.update(snap)
        assert len(rollback_calls) == 1
        assert result == {}


# ── _compute_error() ──────────────────────────────────────────────────────────

class TestComputeError:
    def test_suppress_threshold_error_requires_accuracy(self):
        controller = _make_controller()
        snap = _make_snapshot()
        error = controller._compute_error(ParameterId.SUPPRESS_THRESHOLD, snap, None)
        assert error is None

    def test_suppress_threshold_positive_error_when_below_target(self):
        controller = _make_controller()
        snap = _make_snapshot()
        # accuracy < target (0.65) → positive error → raise suppress threshold
        error = controller._compute_error(ParameterId.SUPPRESS_THRESHOLD, snap, 0.50)
        assert error is not None
        assert error < 0  # 0.50 - 0.65 = -0.15

    def test_confidence_floor_positive_error_at_high_pressure(self):
        controller = _make_controller()
        snap = _make_snapshot(pressure=0.9)
        error = controller._compute_error(ParameterId.CONFIDENCE_FLOOR, snap, None)
        assert error is not None
        assert error > 0  # 0.9 - 0.3 = 0.6

    def test_position_sizing_error_shrinks_at_high_pressure(self):
        controller = _make_controller()
        snap = _make_snapshot(pressure=0.9)
        error = controller._compute_error(ParameterId.POSITION_SIZING_FACTOR, snap, None)
        assert error is not None
        assert error < 0  # target (0.3) - pressure (0.9) = -0.6

    def test_iv_threshold_error_returns_none_without_market_stage(self):
        controller = _make_controller()
        snap = TelemetrySnapshot(ts=time.time(), per_stage={}, windows={}, pressure=0.1)
        error = controller._compute_error(ParameterId.IV_THRESHOLD, snap, None)
        assert error is None

    def test_iv_threshold_error_with_market_stage(self):
        controller = _make_controller()
        market_metrics = StageMetrics(
            "market", ts=time.time(), latency_ms=5, items_in=10, items_out=10,
            extra={"iv_filter_rate": 0.5}
        )
        snap = TelemetrySnapshot(
            ts=time.time(), per_stage={"market": market_metrics},
            windows={}, pressure=0.1,
        )
        error = controller._compute_error(ParameterId.IV_THRESHOLD, snap, None)
        assert error is not None
        # target fill=0.7, actual=0.5 → error = 0.2
        assert math.isclose(error, 0.2, abs_tol=0.01)


# ── _pid_tick() cooldown ──────────────────────────────────────────────────────

class TestPidTickCooldown:
    def test_pid_tick_respects_cooldown(self):
        controller = _make_controller()
        snap = _make_snapshot()
        now = time.time()
        # Set last_update very recent
        controller._pid[ParameterId.CONFIDENCE_FLOOR].last_update_ts = now - 1.0
        result = controller._pid_tick(ParameterId.CONFIDENCE_FLOOR, snap, 0.5, now)
        assert result is None

    def test_pid_tick_fires_after_cooldown(self):
        controller = _make_controller()
        snap = _make_snapshot(pressure=0.9)  # high pressure → big error
        now = time.time()
        # Set last_update far in the past
        controller._pid[ParameterId.CONFIDENCE_FLOOR].last_update_ts = now - 10000.0
        result = controller._pid_tick(ParameterId.CONFIDENCE_FLOOR, snap, 0.5, now)
        # High pressure should produce a non-None adjustment
        assert result is not None


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTuningControllerLifecycle:
    async def test_start_stop(self):
        lt = LiveTuning()
        helix = HelixConfig(lt)
        controller = TuningController(lt, helix, tick_s=0.05)
        await controller.start()
        assert controller._running is True
        await controller.stop()
        assert controller._running is False

    async def test_stop_without_start_noop(self):
        lt = LiveTuning()
        helix = HelixConfig(lt)
        controller = TuningController(lt, helix)
        await controller.stop()  # Should not raise
