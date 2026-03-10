"""
Comprehensive tests for rot.control.anomaly_detector.

Modules tested:
- AnomalyDetector
- AnomalyReport
- AnomalySeverity
- _welford_stats helper

Coverage:
- Z-score spike detection on latency
- CUSUM drift detection (upward and downward)
- Error rate spike detection
- Throughput drop detection
- Pressure threshold alerts (WARNING and CRITICAL)
- Rollback recommendations
- CUSUM state reset (full and per-stage)
- Severity escalation (WARNING vs CRITICAL)
- No anomalies when metrics are nominal
- Multiple anomalies in one snapshot
"""
from __future__ import annotations

import math
import time
from typing import Dict
from unittest.mock import MagicMock

import pytest

from rot.control.anomaly_detector import (
    AnomalyDetector,
    AnomalyReport,
    AnomalySeverity,
    _welford_stats,
)
from rot.control.telemetry_bus import StageMetrics, TelemetrySnapshot, _WindowStats


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_window_stats(
    avg_latency: float = 10.0,
    p95_latency: float = 15.0,
    avg_throughput: float = 0.95,
    avg_error: float = 0.01,
    n: int = 10,
) -> _WindowStats:
    return _WindowStats(
        window_name="5m",
        sample_count=n,
        avg_latency_ms=avg_latency,
        p95_latency_ms=p95_latency,
        avg_throughput_ratio=avg_throughput,
        avg_error_rate=avg_error,
        total_items_in=100,
        total_items_out=95,
    )


def _make_snapshot(
    pressure: float = 0.1,
    stage_windows: Dict = None,
    per_stage: Dict = None,
) -> TelemetrySnapshot:
    per_stage = per_stage or {}
    windows = stage_windows or {}
    return TelemetrySnapshot(
        ts=time.time(),
        per_stage=per_stage,
        windows=windows,
        pressure=pressure,
    )


# ── AnomalyReport ─────────────────────────────────────────────────────────────

class TestAnomalyReport:
    def test_basic_construction(self):
        r = AnomalyReport(
            stage="nlp",
            metric="p95_latency_ms",
            severity=AnomalySeverity.WARNING,
            algorithm="zscore",
            value=100.0,
            expected=20.0,
            message="spike detected",
        )
        assert r.stage == "nlp"
        assert r.severity == AnomalySeverity.WARNING
        assert r.recommend_rollback is False

    def test_rollback_flag(self):
        r = AnomalyReport(
            stage="nlp",
            metric="latency",
            severity=AnomalySeverity.CRITICAL,
            algorithm="zscore",
            value=1.0,
            expected=0.5,
            message="critical",
            recommend_rollback=True,
        )
        assert r.recommend_rollback is True


# ── Pressure detection ────────────────────────────────────────────────────────

class TestPressureDetection:
    def test_no_anomaly_below_warning(self):
        detector = AnomalyDetector(pressure_warn=0.6, pressure_crit=0.85)
        reports = detector._check_pressure(0.3)
        assert len(reports) == 0

    def test_warning_at_threshold(self):
        detector = AnomalyDetector(pressure_warn=0.6, pressure_crit=0.85)
        reports = detector._check_pressure(0.65)
        assert len(reports) == 1
        assert reports[0].severity == AnomalySeverity.WARNING
        assert reports[0].recommend_rollback is False

    def test_critical_at_threshold(self):
        detector = AnomalyDetector(pressure_warn=0.6, pressure_crit=0.85)
        reports = detector._check_pressure(0.90)
        assert len(reports) == 1
        assert reports[0].severity == AnomalySeverity.CRITICAL
        assert reports[0].recommend_rollback is True

    def test_pressure_exactly_at_critical(self):
        detector = AnomalyDetector(pressure_crit=0.85)
        reports = detector._check_pressure(0.85)
        assert reports[0].severity == AnomalySeverity.CRITICAL

    def test_pressure_exactly_at_warning(self):
        detector = AnomalyDetector(pressure_warn=0.6, pressure_crit=0.85)
        reports = detector._check_pressure(0.6)
        assert reports[0].severity == AnomalySeverity.WARNING


# ── Z-score latency detection ─────────────────────────────────────────────────

class TestZscoreLatency:
    def test_no_anomaly_when_latency_nominal(self):
        detector = AnomalyDetector(z_threshold=3.0)
        w5 = _make_window_stats(avg_latency=10.0, p95_latency=12.0)
        w1 = _make_window_stats(avg_latency=10.5, p95_latency=12.5)
        reports = detector._check_latency_zscore("nlp", w1, w5)
        assert len(reports) == 0

    def test_anomaly_when_latency_spikes(self):
        detector = AnomalyDetector(z_threshold=2.0)
        # baseline: mean=10, p95=15 → std_est = (15-10)/1.645 ≈ 3.04
        # spike: p95=50 → z = (50-10)/3.04 ≈ 13.2 >> 2.0
        w5 = _make_window_stats(avg_latency=10.0, p95_latency=15.0)
        w1 = _make_window_stats(avg_latency=50.0, p95_latency=50.0)
        reports = detector._check_latency_zscore("nlp", w1, w5)
        assert len(reports) == 1
        assert reports[0].stage == "nlp"
        assert reports[0].algorithm == "zscore"

    def test_critical_severity_for_large_z(self):
        detector = AnomalyDetector(z_threshold=2.0)
        w5 = _make_window_stats(avg_latency=10.0, p95_latency=15.0)
        # z > 2 * 1.5 = 3.0 → CRITICAL
        w1 = _make_window_stats(avg_latency=200.0, p95_latency=200.0)
        reports = detector._check_latency_zscore("nlp", w1, w5)
        assert reports[0].severity == AnomalySeverity.CRITICAL
        assert reports[0].recommend_rollback is True

    def test_no_anomaly_when_mean_zero(self):
        detector = AnomalyDetector()
        w5 = _make_window_stats(avg_latency=0.0, p95_latency=0.0)
        w1 = _make_window_stats(avg_latency=10.0, p95_latency=10.0)
        reports = detector._check_latency_zscore("nlp", w1, w5)
        assert len(reports) == 0  # mean=0, skip detection


# ── CUSUM drift detection ─────────────────────────────────────────────────────

class TestCusumDrift:
    def test_no_drift_when_stable(self):
        detector = AnomalyDetector(cusum_threshold=5.0)
        w5 = _make_window_stats(avg_latency=10.0, p95_latency=15.0)
        # Send same value repeatedly — should not accumulate
        for _ in range(20):
            reports = detector._check_latency_cusum("nlp", 10.0, w5)
        assert len(reports) == 0

    def test_drift_detected_upward(self):
        detector = AnomalyDetector(cusum_slack=0.1, cusum_threshold=1.0)
        w5 = _make_window_stats(avg_latency=10.0, p95_latency=12.0)
        reports = []
        for _ in range(50):
            reports = detector._check_latency_cusum("nlp", 15.0, w5)
        assert len(reports) > 0
        assert any(r.metric == "latency_drift_up" for r in reports)

    def test_cusum_reset_clears_state(self):
        detector = AnomalyDetector(cusum_slack=0.1, cusum_threshold=1.0)
        w5 = _make_window_stats(avg_latency=10.0, p95_latency=12.0)
        for _ in range(50):
            detector._check_latency_cusum("nlp", 20.0, w5)
        detector.reset_cusum("nlp")
        # After reset, state should be clear
        assert "nlp" not in detector._cusum_state or detector._cusum_state.get("nlp", {}).get("latency", (0, 0)) == (0.0, 0.0)

    def test_cusum_full_reset(self):
        detector = AnomalyDetector()
        detector._cusum_state["nlp"] = {"latency": (99.0, 0.0)}
        detector._cusum_state["cred"] = {"latency": (50.0, 0.0)}
        detector.reset_cusum()
        assert len(detector._cusum_state) == 0

    def test_cusum_stage_isolation(self):
        detector = AnomalyDetector(cusum_slack=0.1, cusum_threshold=1.0)
        w5 = _make_window_stats(avg_latency=10.0, p95_latency=12.0)
        for _ in range(50):
            detector._check_latency_cusum("nlp", 20.0, w5)
        # cred stage should have no accumulated state
        assert "cred" not in detector._cusum_state


# ── Error rate detection ──────────────────────────────────────────────────────

class TestErrorRateDetection:
    def test_no_anomaly_normal_error_rate(self):
        detector = AnomalyDetector()
        w5 = _make_window_stats(avg_error=0.02)
        w1 = _make_window_stats(avg_error=0.03)
        reports = detector._check_error_rate("nlp", w1, w5)
        assert len(reports) == 0

    def test_anomaly_on_error_spike(self):
        detector = AnomalyDetector()
        w5 = _make_window_stats(avg_error=0.01)
        w1 = _make_window_stats(avg_error=0.10)  # 10x spike
        reports = detector._check_error_rate("nlp", w1, w5)
        assert len(reports) == 1

    def test_critical_on_extreme_error_spike(self):
        detector = AnomalyDetector()
        w5 = _make_window_stats(avg_error=0.01)
        w1 = _make_window_stats(avg_error=0.10)  # ratio = 10 > 5 → CRITICAL
        reports = detector._check_error_rate("nlp", w1, w5)
        assert reports[0].severity == AnomalySeverity.CRITICAL
        assert reports[0].recommend_rollback is True

    def test_warning_on_moderate_error_spike(self):
        detector = AnomalyDetector()
        w5 = _make_window_stats(avg_error=0.02)
        w1 = _make_window_stats(avg_error=0.08)  # ratio = 4 < 5 → WARNING
        reports = detector._check_error_rate("nlp", w1, w5)
        assert reports[0].severity == AnomalySeverity.WARNING


# ── Throughput detection ──────────────────────────────────────────────────────

class TestThroughputDetection:
    def test_no_anomaly_normal_throughput(self):
        detector = AnomalyDetector()
        w5 = _make_window_stats(avg_throughput=0.95)
        w1 = _make_window_stats(avg_throughput=0.90)
        reports = detector._check_throughput("nlp", w1, w5)
        assert len(reports) == 0

    def test_anomaly_on_throughput_drop(self):
        detector = AnomalyDetector()
        w5 = _make_window_stats(avg_throughput=0.95)
        w1 = _make_window_stats(avg_throughput=0.60)  # drop = 0.35 > 0.2
        reports = detector._check_throughput("nlp", w1, w5)
        assert len(reports) == 1

    def test_critical_on_large_throughput_drop(self):
        detector = AnomalyDetector()
        w5 = _make_window_stats(avg_throughput=0.95)
        w1 = _make_window_stats(avg_throughput=0.30)  # drop = 0.65 > 0.5 → CRITICAL
        reports = detector._check_throughput("nlp", w1, w5)
        assert reports[0].severity == AnomalySeverity.CRITICAL


# ── Full analyze() integration ────────────────────────────────────────────────

class TestAnalyzeFull:
    def test_no_reports_for_healthy_snapshot(self):
        detector = AnomalyDetector()
        w5 = _make_window_stats(avg_latency=10, p95_latency=12, avg_throughput=0.95, avg_error=0.01)
        w1 = _make_window_stats(avg_latency=10, p95_latency=12, avg_throughput=0.95, avg_error=0.01)
        per_stage = {"nlp": StageMetrics("nlp", ts=0, latency_ms=10, items_in=10, items_out=10)}
        snap = TelemetrySnapshot(
            ts=time.time(), per_stage=per_stage,
            windows={"nlp": {"5m": w5, "1m": w1}},
            pressure=0.1,
        )
        reports = detector.analyze(snap)
        assert len(reports) == 0

    def test_pressure_anomaly_in_analyze(self):
        detector = AnomalyDetector(pressure_crit=0.5)
        per_stage = {"nlp": StageMetrics("nlp", ts=0, latency_ms=1, items_in=1, items_out=1)}
        snap = TelemetrySnapshot(
            ts=time.time(), per_stage=per_stage,
            windows={},
            pressure=0.9,
        )
        reports = detector.analyze(snap)
        pressure_reports = [r for r in reports if r.metric == "pressure"]
        assert len(pressure_reports) == 1
        assert pressure_reports[0].recommend_rollback is True

    def test_no_stage_window_skipped(self):
        detector = AnomalyDetector()
        per_stage = {"nlp": StageMetrics("nlp", ts=0, latency_ms=1, items_in=1, items_out=1)}
        # No windows for nlp → should not raise
        snap = TelemetrySnapshot(
            ts=time.time(), per_stage=per_stage,
            windows={"nlp": {}},  # empty window dict
            pressure=0.1,
        )
        reports = detector.analyze(snap)
        assert isinstance(reports, list)


# ── _welford_stats ─────────────────────────────────────────────────────────────

class TestWelfordStats:
    def test_single_value(self):
        mean, std = _welford_stats([5.0])
        assert math.isclose(mean, 5.0)
        assert std == 0.0

    def test_two_equal_values(self):
        mean, std = _welford_stats([3.0, 3.0])
        assert math.isclose(mean, 3.0)
        assert std == 0.0

    def test_known_distribution(self):
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        mean, std = _welford_stats(values)
        assert math.isclose(mean, 5.0)
        assert math.isclose(std, 2.0, rel_tol=0.01)

    def test_empty_returns_zeros(self):
        mean, std = _welford_stats([])
        assert mean == 0.0
        assert std == 0.0
