"""AnomalyDetector — detects metric anomalies in telemetry streams.

Ported from tokio-prompt-orchestrator/src/self_tune/anomaly.rs.

Implements three detection algorithms:
- Z-score spike detection (sudden deviations from the rolling mean)
- CUSUM drift detection (sustained one-directional shift)
- Pressure threshold alert (simple threshold on the composite pressure score)

The detector is stateless between calls — all state lives in the rolling
window passed in from TelemetryBus.  This makes it trivially testable and
safe to call from any context.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence

from rot.control.telemetry_bus import TelemetrySnapshot, _WindowStats

log = logging.getLogger(__name__)

# Default thresholds — can be overridden at construction time
_DEFAULT_Z_THRESHOLD = 3.0       # standard deviations
_DEFAULT_CUSUM_SLACK = 1.0       # slack factor (k) for CUSUM
_DEFAULT_CUSUM_THRESHOLD = 5.0   # cumulative sum threshold (h)
_DEFAULT_PRESSURE_WARN = 0.6     # pressure score → WARNING
_DEFAULT_PRESSURE_CRIT = 0.85    # pressure score → CRITICAL


class AnomalySeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AnomalyReport:
    """A single detected anomaly.

    Attributes:
        stage: Which pipeline stage triggered the anomaly.
        metric: Which metric was anomalous (e.g. ``"latency_ms"``).
        severity: INFO / WARNING / CRITICAL.
        algorithm: ``"zscore"`` | ``"cusum"`` | ``"pressure"``.
        value: The observed metric value.
        expected: The baseline/expected value (mean or threshold).
        message: Human-readable summary.
        recommend_rollback: Whether the controller should consider a rollback.
    """

    stage: str
    metric: str
    severity: AnomalySeverity
    algorithm: str
    value: float
    expected: float
    message: str
    recommend_rollback: bool = False


class AnomalyDetector:
    """Detects metric anomalies from TelemetrySnapshot data.

    Usage::

        detector = AnomalyDetector()
        reports = detector.analyze(snapshot)
        for r in reports:
            if r.recommend_rollback:
                helix_config.rollback()
    """

    def __init__(
        self,
        z_threshold: float = _DEFAULT_Z_THRESHOLD,
        cusum_slack: float = _DEFAULT_CUSUM_SLACK,
        cusum_threshold: float = _DEFAULT_CUSUM_THRESHOLD,
        pressure_warn: float = _DEFAULT_PRESSURE_WARN,
        pressure_crit: float = _DEFAULT_PRESSURE_CRIT,
    ) -> None:
        self._z_threshold = z_threshold
        self._cusum_slack = cusum_slack
        self._cusum_threshold = cusum_threshold
        self._pressure_warn = pressure_warn
        self._pressure_crit = pressure_crit
        # CUSUM accumulators: {stage → {metric → (s_pos, s_neg)}}
        self._cusum_state: Dict[str, Dict[str, tuple[float, float]]] = {}

    # ── Public API ───────────────────────────────────────────────────────────

    def analyze(self, snapshot: TelemetrySnapshot) -> List[AnomalyReport]:
        """Analyze a TelemetrySnapshot and return any anomaly reports."""
        reports: List[AnomalyReport] = []

        # Pressure-level anomaly (system-wide)
        reports.extend(self._check_pressure(snapshot.pressure))

        # Per-stage anomalies using 5m window stats
        for stage, stage_windows in snapshot.windows.items():
            w5 = stage_windows.get("5m")
            w1 = stage_windows.get("1m")
            if w5 is None or w1 is None:
                continue
            reports.extend(self._check_latency_zscore(stage, w1, w5))
            reports.extend(self._check_latency_cusum(stage, w1.avg_latency_ms, w5))
            reports.extend(self._check_error_rate(stage, w1, w5))
            reports.extend(self._check_throughput(stage, w1, w5))

        return reports

    def reset_cusum(self, stage: Optional[str] = None) -> None:
        """Reset CUSUM accumulators, optionally for a single stage."""
        if stage is None:
            self._cusum_state.clear()
        elif stage in self._cusum_state:
            del self._cusum_state[stage]

    # ── Detection Algorithms ─────────────────────────────────────────────────

    def _check_pressure(self, pressure: float) -> List[AnomalyReport]:
        if pressure >= self._pressure_crit:
            return [AnomalyReport(
                stage="system",
                metric="pressure",
                severity=AnomalySeverity.CRITICAL,
                algorithm="pressure",
                value=pressure,
                expected=self._pressure_warn,
                message=f"System pressure CRITICAL: {pressure:.2f} ≥ {self._pressure_crit:.2f}",
                recommend_rollback=True,
            )]
        if pressure >= self._pressure_warn:
            return [AnomalyReport(
                stage="system",
                metric="pressure",
                severity=AnomalySeverity.WARNING,
                algorithm="pressure",
                value=pressure,
                expected=self._pressure_warn,
                message=f"System pressure WARNING: {pressure:.2f} ≥ {self._pressure_warn:.2f}",
            )]
        return []

    def _check_latency_zscore(
        self, stage: str, w1: _WindowStats, w5: _WindowStats
    ) -> List[AnomalyReport]:
        """Z-score spike: 1m p95 latency vs 5m baseline."""
        mean = w5.avg_latency_ms
        if mean <= 0:
            return []
        # Estimate std from p95 assuming normal-ish distribution
        std_est = max(1.0, (w5.p95_latency_ms - mean) / 1.645)
        z = (w1.p95_latency_ms - mean) / std_est
        if abs(z) < self._z_threshold:
            return []
        severity = AnomalySeverity.CRITICAL if abs(z) > self._z_threshold * 1.5 else AnomalySeverity.WARNING
        return [AnomalyReport(
            stage=stage,
            metric="p95_latency_ms",
            severity=severity,
            algorithm="zscore",
            value=w1.p95_latency_ms,
            expected=mean,
            message=(
                f"{stage}: p95 latency spike z={z:.1f}σ "
                f"({w1.p95_latency_ms:.1f}ms vs baseline {mean:.1f}ms)"
            ),
            recommend_rollback=severity == AnomalySeverity.CRITICAL,
        )]

    def _check_latency_cusum(
        self, stage: str, current: float, w5: _WindowStats
    ) -> List[AnomalyReport]:
        """CUSUM drift detection on latency."""
        mean = w5.avg_latency_ms
        if mean <= 0:
            return []
        std_est = max(1.0, (w5.p95_latency_ms - mean) / 1.645)
        k = self._cusum_slack * std_est
        h = self._cusum_threshold * std_est

        state = self._cusum_state.setdefault(stage, {})
        s_pos, s_neg = state.get("latency", (0.0, 0.0))

        s_pos = max(0.0, s_pos + (current - mean - k))
        s_neg = max(0.0, s_neg + (mean - current - k))
        state["latency"] = (s_pos, s_neg)

        reports: List[AnomalyReport] = []
        if s_pos > h:
            reports.append(AnomalyReport(
                stage=stage,
                metric="latency_drift_up",
                severity=AnomalySeverity.WARNING,
                algorithm="cusum",
                value=s_pos,
                expected=h,
                message=f"{stage}: latency drifting upward (CUSUM s+={s_pos:.1f} > h={h:.1f})",
            ))
        if s_neg > h:
            reports.append(AnomalyReport(
                stage=stage,
                metric="latency_drift_down",
                severity=AnomalySeverity.INFO,
                algorithm="cusum",
                value=s_neg,
                expected=h,
                message=f"{stage}: latency drifting downward (CUSUM s-={s_neg:.1f} > h={h:.1f})",
            ))
        return reports

    def _check_error_rate(
        self, stage: str, w1: _WindowStats, w5: _WindowStats
    ) -> List[AnomalyReport]:
        """Flag when 1m error rate significantly exceeds 5m baseline."""
        baseline = w5.avg_error_rate
        current = w1.avg_error_rate
        if baseline <= 0:
            baseline = 0.01  # avoid div-by-zero; assume 1% floor
        ratio = current / baseline
        if ratio < 3.0:
            return []
        severity = AnomalySeverity.CRITICAL if ratio > 5.0 else AnomalySeverity.WARNING
        return [AnomalyReport(
            stage=stage,
            metric="error_rate",
            severity=severity,
            algorithm="zscore",
            value=current,
            expected=baseline,
            message=(
                f"{stage}: error rate spike {current:.1%} vs baseline {baseline:.1%} "
                f"(ratio={ratio:.1f}x)"
            ),
            recommend_rollback=severity == AnomalySeverity.CRITICAL,
        )]

    def _check_throughput(
        self, stage: str, w1: _WindowStats, w5: _WindowStats
    ) -> List[AnomalyReport]:
        """Flag when 1m throughput ratio drops well below 5m baseline."""
        baseline = w5.avg_throughput_ratio
        current = w1.avg_throughput_ratio
        drop = baseline - current
        if drop < 0.2:  # less than 20% drop — not significant
            return []
        severity = AnomalySeverity.CRITICAL if drop > 0.5 else AnomalySeverity.WARNING
        return [AnomalyReport(
            stage=stage,
            metric="throughput_ratio",
            severity=severity,
            algorithm="zscore",
            value=current,
            expected=baseline,
            message=(
                f"{stage}: throughput drop {current:.2f} vs baseline {baseline:.2f} "
                f"(drop={drop:.2f})"
            ),
        )]


# ── Utility ───────────────────────────────────────────────────────────────────


def _welford_stats(values: Sequence[float]) -> tuple[float, float]:
    """Return (mean, std) via Welford single-pass algorithm."""
    n = 0
    mean = 0.0
    m2 = 0.0
    for x in values:
        n += 1
        delta = x - mean
        mean += delta / n
        m2 += delta * (x - mean)
    std = math.sqrt(m2 / (n - 1)) if n > 1 else 0.0
    return mean, std
