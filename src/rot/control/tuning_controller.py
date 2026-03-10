"""TuningController — PID controllers for ROT's tunable pipeline parameters.

Ported from tokio-prompt-orchestrator/src/self_tune/controller.rs.

For each ParameterId the controller maintains:
- A PID state (integral accumulator, previous error)
- A cooldown timer (rate-limits how often the parameter can change)
- A post-adjustment monitor (triggers rollback if accuracy degrades)

TuningController.update() is called by a background task every ``tick_s``
seconds with the latest TelemetrySnapshot and the current signal accuracy.
It computes error signals, runs each PID, and applies adjustments via
LiveTuning.  Before every write it calls HelixConfig.snapshot().  If
signal accuracy at the next check is worse by more than ``rollback_threshold``
the controller calls HelixConfig.rollback() automatically.

PID formula (discrete):
    output = kp * e + ki * integral + kd * (e - e_prev)
    integral is clamped to ±INTEGRAL_CAP (anti-windup)
    output is clamped to ±1.0 then scaled to the param's range
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from rot.control.live_tuning import LiveTuning, ParameterId, PARAMETER_SPECS
from rot.control.helix_config import HelixConfig
from rot.control.telemetry_bus import TelemetrySnapshot
from rot.control.anomaly_detector import AnomalyDetector, AnomalySeverity

log = logging.getLogger(__name__)

_INTEGRAL_CAP = 100.0
_MAX_DELTA_RATIO = 0.05   # max single-tick change = 5% of parameter range


@dataclass
class _PidState:
    """Per-parameter PID runtime state."""

    integral: float = 0.0
    prev_error: float = 0.0
    last_update_ts: float = 0.0
    last_accuracy_after_change: Optional[float] = None
    last_change_ts: float = 0.0


@dataclass
class PidGains:
    """PID gain coefficients for a single parameter."""

    kp: float = 0.4
    ki: float = 0.05
    kd: float = 0.1


# Default gains — conservative to avoid over-tuning a live system
DEFAULT_GAINS: Dict[ParameterId, PidGains] = {
    ParameterId.SENTIMENT_THRESHOLD: PidGains(kp=0.3, ki=0.02, kd=0.05),
    ParameterId.SOURCE_WEIGHT_MULTIPLIER: PidGains(kp=0.2, ki=0.01, kd=0.05),
    ParameterId.CONFIDENCE_FLOOR: PidGains(kp=0.3, ki=0.02, kd=0.05),
    ParameterId.FEATURE_WEIGHT_SCALE: PidGains(kp=0.2, ki=0.01, kd=0.05),
    ParameterId.IV_THRESHOLD: PidGains(kp=0.3, ki=0.02, kd=0.08),
    ParameterId.SUPPRESS_THRESHOLD: PidGains(kp=0.1, ki=0.005, kd=0.02),
    ParameterId.POSITION_SIZING_FACTOR: PidGains(kp=0.2, ki=0.01, kd=0.05),
}

# Target performance metrics per parameter
# Each entry: (target_value, get_actual_fn_name_in_snapshot)
# Actual extraction is done in _compute_error()
_PRESSURE_TARGET = 0.3   # target system pressure [0,1]
_ACCURACY_TARGET = 0.65  # target signal accuracy (win rate fraction)


class TuningController:
    """Runs PID control loops for all tunable ROT parameters.

    Usage::

        controller = TuningController(live_tuning, helix_config)
        await controller.start()    # spawns background task
        await controller.stop()
    """

    def __init__(
        self,
        live_tuning: LiveTuning,
        helix_config: HelixConfig,
        anomaly_detector: Optional[AnomalyDetector] = None,
        tick_s: float = 30.0,
        gains: Optional[Dict[ParameterId, PidGains]] = None,
        rollback_threshold: float = 0.05,  # 5% accuracy drop triggers rollback
        telemetry_bus: Optional[Any] = None,
        accuracy_fn: Optional[Any] = None,
    ) -> None:
        self._lt = live_tuning
        self._helix = helix_config
        self._detector = anomaly_detector or AnomalyDetector()
        self._tick_s = tick_s
        self._gains = gains or DEFAULT_GAINS
        self._rollback_threshold = rollback_threshold
        self._pid: Dict[ParameterId, _PidState] = {
            pid: _PidState() for pid in ParameterId
        }
        self._last_accuracy: Optional[float] = None
        self._task = None
        self._running = False
        # Optional wiring: TelemetryBus to read snapshots from, and a callable
        # returning current signal accuracy (float in [0,1] or None).
        self._bus = telemetry_bus
        self._accuracy_fn = accuracy_fn  # () -> Optional[float]

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        import asyncio
        self._running = True
        self._task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                import asyncio
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    # ── Update ───────────────────────────────────────────────────────────────

    def update(
        self,
        snapshot: TelemetrySnapshot,
        current_accuracy: Optional[float] = None,
    ) -> Dict[ParameterId, float]:
        """Run one PID tick and apply adjustments.

        Args:
            snapshot: Latest TelemetrySnapshot from TelemetryBus.
            current_accuracy: Current signal accuracy [0, 1], if available.

        Returns:
            Dict of {param_id → new_value} for every param that was adjusted.
        """
        now = time.time()
        adjusted: Dict[ParameterId, float] = {}

        # 1. Check for anomaly-triggered rollback
        anomalies = self._detector.analyze(snapshot)
        critical_rollbacks = [a for a in anomalies if a.recommend_rollback]
        if critical_rollbacks:
            for a in critical_rollbacks:
                log.warning(
                    "TuningController: anomaly rollback triggered by %s: %s",
                    a.metric, a.message,
                )
            self._helix.rollback()
            return {}

        # 2. Check post-adjustment accuracy degradation
        if current_accuracy is not None and self._last_accuracy is not None:
            drop = self._last_accuracy - current_accuracy
            if drop > self._rollback_threshold:
                log.warning(
                    "TuningController: accuracy dropped %.1f%% → %.1f%% (delta=%.1f%%), rolling back",
                    self._last_accuracy * 100,
                    current_accuracy * 100,
                    drop * 100,
                )
                self._helix.rollback()
                self._last_accuracy = current_accuracy
                return {}

        if current_accuracy is not None:
            self._last_accuracy = current_accuracy

        # 3. Run PID for each parameter
        adjustments: Dict[ParameterId, float] = {}
        for pid in ParameterId:
            new_val = self._pid_tick(pid, snapshot, current_accuracy, now)
            if new_val is not None:
                adjustments[pid] = new_val

        if not adjustments:
            return {}

        # 4. Snapshot before applying
        self._helix.snapshot(
            trigger="pid_adjustment",
            accuracy_at_snap=current_accuracy,
        )

        # 5. Apply
        stored = self._lt.apply_adjustments(adjustments)
        adjusted.update(stored)

        if adjusted:
            log.info(
                "TuningController: adjusted %d params: %s",
                len(adjusted),
                {k.value: round(v, 4) for k, v in adjusted.items()},
            )

        return adjusted

    # ── Internal ─────────────────────────────────────────────────────────────

    def _pid_tick(
        self,
        pid: ParameterId,
        snapshot: TelemetrySnapshot,
        accuracy: Optional[float],
        now: float,
    ) -> Optional[float]:
        """Compute PID output for a single parameter.

        Returns the desired new value, or None if cooldown has not elapsed
        or the computed delta is below the quantization step.
        """
        spec = PARAMETER_SPECS[pid]
        state = self._pid[pid]

        # Enforce cooldown
        if now - state.last_update_ts < spec.cooldown_s:
            return None

        gains = self._gains.get(pid, PidGains())
        error = self._compute_error(pid, snapshot, accuracy)
        if error is None:
            return None

        # PID update
        state.integral = max(-_INTEGRAL_CAP, min(_INTEGRAL_CAP, state.integral + error))
        derivative = error - state.prev_error
        output = gains.kp * error + gains.ki * state.integral + gains.kd * derivative
        output = max(-1.0, min(1.0, output))

        state.prev_error = error
        state.last_update_ts = now

        # Scale output to parameter range and compute delta
        param_range = spec.max_val - spec.min_val
        max_delta = _MAX_DELTA_RATIO * param_range
        delta = max(-max_delta, min(max_delta, output * param_range * 0.1))

        current = self._lt.get(pid)
        new_val = current + delta

        # Skip if delta is smaller than one step (not worth applying)
        if abs(delta) < spec.step * 0.5:
            return None

        return new_val

    def _compute_error(
        self,
        pid: ParameterId,
        snapshot: TelemetrySnapshot,
        accuracy: Optional[float],
    ) -> Optional[float]:
        """Compute the error signal for a given parameter.

        Error = (target - actual) / normalizer.
        Positive error → parameter should increase.
        Negative error → parameter should decrease.
        """
        if pid == ParameterId.SUPPRESS_THRESHOLD:
            # Drive suppress_threshold based on system accuracy vs target
            if accuracy is None:
                return None
            return accuracy - _ACCURACY_TARGET

        if pid == ParameterId.CONFIDENCE_FLOOR:
            # Higher pressure → raise confidence floor to reduce throughput
            return snapshot.pressure - _PRESSURE_TARGET

        if pid == ParameterId.POSITION_SIZING_FACTOR:
            # Conservative: shrink when pressure is high, grow when low
            return _PRESSURE_TARGET - snapshot.pressure

        if pid == ParameterId.SENTIMENT_THRESHOLD:
            if accuracy is None:
                return None
            # If accuracy is low, raise sentiment threshold (be more selective)
            return _ACCURACY_TARGET - accuracy

        if pid == ParameterId.SOURCE_WEIGHT_MULTIPLIER:
            # Use error rate from NLP stage as proxy
            nlp_metrics = snapshot.per_stage.get("nlp")
            if nlp_metrics is None:
                return None
            target_error_rate = 0.05
            return target_error_rate - nlp_metrics.error_rate

        if pid == ParameterId.FEATURE_WEIGHT_SCALE:
            cred_metrics = snapshot.per_stage.get("credibility")
            if cred_metrics is None:
                return None
            target_error_rate = 0.05
            return target_error_rate - cred_metrics.error_rate

        if pid == ParameterId.IV_THRESHOLD:
            market_metrics = snapshot.per_stage.get("market")
            if market_metrics is None:
                return None
            # iv_threshold error is custom domain metric from "extra"
            actual_fill_rate = market_metrics.extra.get("iv_filter_rate", 0.5)
            target_fill_rate = 0.7
            return target_fill_rate - actual_fill_rate

        return None

    async def _tick_loop(self) -> None:
        import asyncio
        while self._running:
            try:
                await asyncio.sleep(self._tick_s)
            except asyncio.CancelledError:
                break
            if not self._running:
                break
            try:
                snapshot = (
                    self._bus.latest_snapshot()
                    if self._bus is not None
                    else None
                )
                if snapshot is None:
                    continue
                accuracy: Optional[float] = None
                if self._accuracy_fn is not None:
                    try:
                        accuracy = self._accuracy_fn()
                    except Exception as acc_err:
                        log.warning("TuningController: accuracy_fn error: %s", acc_err)
                self.update(snapshot, accuracy)
            except Exception as exc:
                log.warning("TuningController: tick error: %s", exc)
