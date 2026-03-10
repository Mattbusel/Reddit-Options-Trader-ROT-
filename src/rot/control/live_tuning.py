"""LiveTuning — thread-safe parameter store for runtime pipeline adjustments.

Ported from tokio-prompt-orchestrator/src/self_tune/actuator.rs.

Pipeline stages read their tunable parameters from this store at the start
of each cycle.  The TuningController writes new values here after each PID
update.  All reads and writes are O(1) and safe for concurrent access.

Parameters are clamped to their defined [min, max] range at write time.
Values never go outside spec, regardless of what the PID controller outputs.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class ParameterId(str, Enum):
    """Enumeration of all tunable ROT pipeline parameters.

    Mirrors the tuning targets listed in the capability spec:
    Stage 2 NLP: sentiment_threshold
    Stage 3 credibility: source_weight_multiplier
    Stage 4 aggregator: confidence_floor
    Stage 5 ML ensemble: feature_weight_scale
    Stage 6 strategy: iv_threshold
    Stage 6.5 suppression: suppress_threshold
    Stage 7 risk: position_sizing_factor
    """

    SENTIMENT_THRESHOLD = "sentiment_threshold"
    SOURCE_WEIGHT_MULTIPLIER = "source_weight_multiplier"
    CONFIDENCE_FLOOR = "confidence_floor"
    FEATURE_WEIGHT_SCALE = "feature_weight_scale"
    IV_THRESHOLD = "iv_threshold"
    SUPPRESS_THRESHOLD = "suppress_threshold"
    POSITION_SIZING_FACTOR = "position_sizing_factor"


@dataclass(frozen=True)
class ParameterSpec:
    """Spec for a single tunable parameter.

    Attributes:
        param_id: The ParameterId this spec governs.
        default: Starting value used before any PID updates.
        min_val: Hard lower bound; values are clamped here.
        max_val: Hard upper bound; values are clamped here.
        step: Discrete quantization step.  PID outputs are rounded to the
              nearest multiple of step before being stored.
        cooldown_s: Minimum seconds between successive writes for this param.
        rollback_window_s: Seconds to monitor after an adjustment before
                           triggering rollback if accuracy degrades.
    """

    param_id: ParameterId
    default: float
    min_val: float
    max_val: float
    step: float
    cooldown_s: float = 30.0
    rollback_window_s: float = 500.0  # resolved outcomes (proxy via seconds)


# ── Default parameter specifications ─────────────────────────────────────────
PARAMETER_SPECS: Dict[ParameterId, ParameterSpec] = {
    ParameterId.SENTIMENT_THRESHOLD: ParameterSpec(
        param_id=ParameterId.SENTIMENT_THRESHOLD,
        default=0.0,
        min_val=-1.0,
        max_val=1.0,
        step=0.05,
        cooldown_s=60.0,
    ),
    ParameterId.SOURCE_WEIGHT_MULTIPLIER: ParameterSpec(
        param_id=ParameterId.SOURCE_WEIGHT_MULTIPLIER,
        default=1.0,
        min_val=0.1,
        max_val=5.0,
        step=0.1,
        cooldown_s=120.0,
    ),
    ParameterId.CONFIDENCE_FLOOR: ParameterSpec(
        param_id=ParameterId.CONFIDENCE_FLOOR,
        default=0.0,
        min_val=0.0,
        max_val=0.7,
        step=0.01,
        cooldown_s=60.0,
    ),
    ParameterId.FEATURE_WEIGHT_SCALE: ParameterSpec(
        param_id=ParameterId.FEATURE_WEIGHT_SCALE,
        default=1.0,
        min_val=0.1,
        max_val=3.0,
        step=0.1,
        cooldown_s=300.0,
    ),
    ParameterId.IV_THRESHOLD: ParameterSpec(
        param_id=ParameterId.IV_THRESHOLD,
        default=0.3,
        min_val=0.05,
        max_val=2.0,
        step=0.05,
        cooldown_s=120.0,
    ),
    ParameterId.SUPPRESS_THRESHOLD: ParameterSpec(
        param_id=ParameterId.SUPPRESS_THRESHOLD,
        default=0.20,
        min_val=0.05,
        max_val=0.50,
        step=0.01,
        cooldown_s=3600.0,  # very cautious — touches learned gate state
    ),
    ParameterId.POSITION_SIZING_FACTOR: ParameterSpec(
        param_id=ParameterId.POSITION_SIZING_FACTOR,
        default=1.0,
        min_val=0.1,
        max_val=3.0,
        step=0.1,
        cooldown_s=300.0,
    ),
}


class LiveTuning:
    """Thread-safe parameter store.

    Usage::

        lt = LiveTuning()
        # In pipeline stage:
        threshold = lt.get(ParameterId.SENTIMENT_THRESHOLD)
        # In TuningController:
        lt.set(ParameterId.SENTIMENT_THRESHOLD, 0.15)
    """

    def __init__(self, specs: Optional[Dict[ParameterId, ParameterSpec]] = None) -> None:
        self._specs = specs or PARAMETER_SPECS
        self._lock = threading.RLock()
        self._values: Dict[ParameterId, float] = {
            pid: spec.default for pid, spec in self._specs.items()
        }

    # ── Read ─────────────────────────────────────────────────────────────────

    def get(self, param_id: ParameterId) -> float:
        """Return the current value for param_id (always within spec)."""
        with self._lock:
            return self._values.get(param_id, self._specs[param_id].default)

    def snapshot(self) -> Dict[ParameterId, float]:
        """Return a point-in-time copy of all parameter values."""
        with self._lock:
            return dict(self._values)

    # ── Write ────────────────────────────────────────────────────────────────

    def set(self, param_id: ParameterId, value: float) -> float:
        """Set param_id to value (clamped + quantized).  Returns stored value."""
        spec = self._specs[param_id]
        stored = _clamp_quantize(value, spec)
        with self._lock:
            self._values[param_id] = stored
        return stored

    def apply_adjustments(self, adjustments: Dict[ParameterId, float]) -> Dict[ParameterId, float]:
        """Apply multiple parameter updates atomically.

        Returns a dict of {param_id → stored_value} for each applied param.
        """
        stored: Dict[ParameterId, float] = {}
        with self._lock:
            for pid, val in adjustments.items():
                if pid not in self._specs:
                    continue
                clamped = _clamp_quantize(val, self._specs[pid])
                self._values[pid] = clamped
                stored[pid] = clamped
        return stored

    def restore(self, values: Dict[ParameterId, float]) -> None:
        """Restore a previously snapshotted parameter set (used by rollback)."""
        with self._lock:
            for pid, val in values.items():
                if pid in self._specs:
                    self._values[pid] = _clamp_quantize(val, self._specs[pid])

    # ── Convenience accessors ────────────────────────────────────────────────

    @property
    def sentiment_threshold(self) -> float:
        return self.get(ParameterId.SENTIMENT_THRESHOLD)

    @property
    def confidence_floor(self) -> float:
        return self.get(ParameterId.CONFIDENCE_FLOOR)

    @property
    def suppress_threshold(self) -> float:
        return self.get(ParameterId.SUPPRESS_THRESHOLD)

    @property
    def position_sizing_factor(self) -> float:
        return self.get(ParameterId.POSITION_SIZING_FACTOR)

    @property
    def iv_threshold(self) -> float:
        return self.get(ParameterId.IV_THRESHOLD)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _clamp_quantize(value: float, spec: ParameterSpec) -> float:
    """Clamp value to [min_val, max_val] and round to nearest step."""
    clamped = max(spec.min_val, min(spec.max_val, value))
    if spec.step > 0:
        quantized = round(clamped / spec.step) * spec.step
        # Re-clamp after quantization to handle edge cases
        quantized = max(spec.min_val, min(spec.max_val, quantized))
        return quantized
    return clamped
