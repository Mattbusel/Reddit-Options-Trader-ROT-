"""
Comprehensive tests for rot.control.live_tuning.

Modules tested:
- LiveTuning
- ParameterId
- ParameterSpec
- PARAMETER_SPECS defaults
- _clamp_quantize helper

Coverage:
- Default values on construction
- get() returns default
- set() clamps to [min, max]
- set() quantizes to step
- set() returns stored value
- apply_adjustments() batch update
- apply_adjustments() with unknown param_id (skipped)
- restore() from snapshot
- snapshot() returns copy
- All convenience accessors
- Thread-safety not tested (no-lock path tested for correctness)
- Edge cases: value at exact min, exact max, below min, above max
"""
from __future__ import annotations

import math

import pytest

from rot.control.live_tuning import (
    LiveTuning,
    ParameterId,
    ParameterSpec,
    PARAMETER_SPECS,
    _clamp_quantize,
)


# ── ParameterSpec ─────────────────────────────────────────────────────────────

class TestParameterSpec:
    def test_all_parameters_have_specs(self):
        for pid in ParameterId:
            assert pid in PARAMETER_SPECS, f"Missing spec for {pid}"

    def test_all_specs_have_valid_range(self):
        for pid, spec in PARAMETER_SPECS.items():
            assert spec.min_val < spec.max_val, f"{pid}: min >= max"

    def test_all_defaults_within_range(self):
        for pid, spec in PARAMETER_SPECS.items():
            assert spec.min_val <= spec.default <= spec.max_val, f"{pid}: default out of range"

    def test_all_steps_positive(self):
        for pid, spec in PARAMETER_SPECS.items():
            assert spec.step > 0, f"{pid}: step must be positive"

    def test_cooldowns_positive(self):
        for pid, spec in PARAMETER_SPECS.items():
            assert spec.cooldown_s > 0, f"{pid}: cooldown must be positive"

    def test_suppress_threshold_has_high_cooldown(self):
        """Suppress threshold has the longest cooldown — protecting learned state."""
        spec = PARAMETER_SPECS[ParameterId.SUPPRESS_THRESHOLD]
        assert spec.cooldown_s >= 3600.0, "suppress_threshold cooldown should be >= 1h"


# ── _clamp_quantize ───────────────────────────────────────────────────────────

class TestClampQuantize:
    def _spec(self, min_val=0.0, max_val=1.0, default=0.5, step=0.1):
        return ParameterSpec(
            param_id=ParameterId.CONFIDENCE_FLOOR,
            default=default, min_val=min_val, max_val=max_val, step=step,
        )

    def test_value_within_range_quantized(self):
        result = _clamp_quantize(0.35, self._spec(step=0.1))
        assert math.isclose(result, 0.3, abs_tol=0.001) or math.isclose(result, 0.4, abs_tol=0.001)

    def test_value_below_min_clamped(self):
        result = _clamp_quantize(-1.0, self._spec(min_val=0.0, max_val=1.0))
        assert result == 0.0

    def test_value_above_max_clamped(self):
        result = _clamp_quantize(5.0, self._spec(min_val=0.0, max_val=1.0))
        assert result == 1.0

    def test_value_at_exact_min(self):
        result = _clamp_quantize(0.0, self._spec(min_val=0.0, max_val=1.0, step=0.1))
        assert result == 0.0

    def test_value_at_exact_max(self):
        result = _clamp_quantize(1.0, self._spec(min_val=0.0, max_val=1.0, step=0.1))
        assert result == 1.0

    def test_quantization_rounding(self):
        # Quantization snaps to the nearest multiple of step.
        # Use values that avoid floating-point ties (banker's rounding).
        result = _clamp_quantize(0.37, self._spec(step=0.1))
        # 0.37 / 0.1 ≈ 3.7 → rounds to 4 → 0.4
        assert math.isclose(result, 0.4, abs_tol=0.001)

    def test_no_quantization_when_step_zero(self):
        """Step=0 should skip quantization and just clamp."""
        spec = ParameterSpec(
            param_id=ParameterId.CONFIDENCE_FLOOR,
            default=0.5, min_val=0.0, max_val=1.0, step=0.0,
        )
        result = _clamp_quantize(0.333, spec)
        assert math.isclose(result, 0.333)


# ── LiveTuning defaults ───────────────────────────────────────────────────────

class TestLiveTuningDefaults:
    def test_all_params_have_default_values(self):
        lt = LiveTuning()
        for pid in ParameterId:
            val = lt.get(pid)
            spec = PARAMETER_SPECS[pid]
            assert math.isclose(val, spec.default, rel_tol=0.001), \
                f"{pid}: expected {spec.default}, got {val}"

    def test_sentiment_threshold_default(self):
        lt = LiveTuning()
        assert lt.sentiment_threshold == PARAMETER_SPECS[ParameterId.SENTIMENT_THRESHOLD].default

    def test_confidence_floor_default(self):
        lt = LiveTuning()
        assert lt.confidence_floor == PARAMETER_SPECS[ParameterId.CONFIDENCE_FLOOR].default

    def test_suppress_threshold_default(self):
        lt = LiveTuning()
        assert math.isclose(lt.suppress_threshold, 0.20, abs_tol=0.001)

    def test_position_sizing_factor_default(self):
        lt = LiveTuning()
        assert math.isclose(lt.position_sizing_factor, 1.0, abs_tol=0.001)

    def test_iv_threshold_default(self):
        lt = LiveTuning()
        assert lt.iv_threshold > 0


# ── LiveTuning.set() ──────────────────────────────────────────────────────────

class TestLiveTuningSet:
    def test_set_within_range(self):
        lt = LiveTuning()
        returned = lt.set(ParameterId.CONFIDENCE_FLOOR, 0.1)
        assert lt.get(ParameterId.CONFIDENCE_FLOOR) == returned

    def test_set_clamps_below_min(self):
        lt = LiveTuning()
        spec = PARAMETER_SPECS[ParameterId.CONFIDENCE_FLOOR]
        lt.set(ParameterId.CONFIDENCE_FLOOR, spec.min_val - 1.0)
        assert lt.get(ParameterId.CONFIDENCE_FLOOR) == spec.min_val

    def test_set_clamps_above_max(self):
        lt = LiveTuning()
        spec = PARAMETER_SPECS[ParameterId.CONFIDENCE_FLOOR]
        lt.set(ParameterId.CONFIDENCE_FLOOR, spec.max_val + 10.0)
        assert lt.get(ParameterId.CONFIDENCE_FLOOR) == spec.max_val

    def test_set_returns_stored_value(self):
        lt = LiveTuning()
        returned = lt.set(ParameterId.SUPPRESS_THRESHOLD, 0.25)
        assert math.isclose(returned, lt.get(ParameterId.SUPPRESS_THRESHOLD))

    def test_set_quantizes_value(self):
        lt = LiveTuning()
        # SUPPRESS_THRESHOLD has step=0.01
        lt.set(ParameterId.SUPPRESS_THRESHOLD, 0.2333)
        val = lt.get(ParameterId.SUPPRESS_THRESHOLD)
        # Should be quantized to 0.23
        assert math.isclose(val, 0.23, abs_tol=0.001)


# ── LiveTuning.snapshot() and restore() ──────────────────────────────────────

class TestLiveTuningSnapshotRestore:
    def test_snapshot_returns_copy(self):
        lt = LiveTuning()
        snap = lt.snapshot()
        assert isinstance(snap, dict)
        # Modifying the snapshot should not affect LiveTuning
        snap[ParameterId.CONFIDENCE_FLOOR] = 999.0
        assert lt.get(ParameterId.CONFIDENCE_FLOOR) != 999.0

    def test_snapshot_contains_all_params(self):
        lt = LiveTuning()
        snap = lt.snapshot()
        for pid in ParameterId:
            assert pid in snap

    def test_restore_sets_values(self):
        lt = LiveTuning()
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.3)
        lt.set(ParameterId.SUPPRESS_THRESHOLD, 0.35)
        snap = lt.snapshot()
        # Change values
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.1)
        lt.set(ParameterId.SUPPRESS_THRESHOLD, 0.10)
        # Restore
        lt.restore(snap)
        assert math.isclose(lt.get(ParameterId.CONFIDENCE_FLOOR), 0.3, abs_tol=0.001)
        assert math.isclose(lt.get(ParameterId.SUPPRESS_THRESHOLD), 0.35, abs_tol=0.001)

    def test_restore_ignores_unknown_param(self):
        lt = LiveTuning()
        # Should not raise even if the snapshot has junk keys
        lt.restore({"not_a_real_param": 1.0})  # type: ignore[arg-type]


# ── LiveTuning.apply_adjustments() ───────────────────────────────────────────

class TestLiveTuningApplyAdjustments:
    def test_apply_multiple_params(self):
        lt = LiveTuning()
        adjustments = {
            ParameterId.CONFIDENCE_FLOOR: 0.2,
            ParameterId.SENTIMENT_THRESHOLD: 0.1,
        }
        stored = lt.apply_adjustments(adjustments)
        assert ParameterId.CONFIDENCE_FLOOR in stored
        assert ParameterId.SENTIMENT_THRESHOLD in stored

    def test_apply_returns_stored_values(self):
        lt = LiveTuning()
        stored = lt.apply_adjustments({ParameterId.CONFIDENCE_FLOOR: 0.5})
        assert ParameterId.CONFIDENCE_FLOOR in stored
        assert math.isclose(stored[ParameterId.CONFIDENCE_FLOOR], 0.5, abs_tol=0.01)

    def test_apply_clamps_values(self):
        lt = LiveTuning()
        spec = PARAMETER_SPECS[ParameterId.CONFIDENCE_FLOOR]
        stored = lt.apply_adjustments({ParameterId.CONFIDENCE_FLOOR: spec.max_val + 100.0})
        assert stored[ParameterId.CONFIDENCE_FLOOR] == spec.max_val

    def test_apply_empty_dict(self):
        lt = LiveTuning()
        stored = lt.apply_adjustments({})
        assert stored == {}

    def test_apply_atomicity(self):
        """All params are updated — no partial update."""
        lt = LiveTuning()
        adjustments = {
            ParameterId.CONFIDENCE_FLOOR: 0.15,
            ParameterId.IV_THRESHOLD: 0.5,
            ParameterId.POSITION_SIZING_FACTOR: 1.5,
        }
        lt.apply_adjustments(adjustments)
        assert math.isclose(lt.get(ParameterId.CONFIDENCE_FLOOR), 0.15, abs_tol=0.01)
        assert math.isclose(lt.get(ParameterId.IV_THRESHOLD), 0.5, abs_tol=0.05)
        assert math.isclose(lt.get(ParameterId.POSITION_SIZING_FACTOR), 1.5, abs_tol=0.1)
