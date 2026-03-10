"""
Comprehensive tests for rot.control.telemetry_bus.

Modules tested:
- TelemetryBus
- StageMetrics
- TelemetrySnapshot
- _aggregate helper
- _WindowStats

Coverage targets:
- StageMetrics construction and derived properties
- TelemetryBus.report() accumulation and ring pruning
- TelemetryBus.subscribe() / unsubscribe()
- TelemetryBus.latest_snapshot() without running loop
- TelemetryBus background broadcast via start/stop
- Pressure computation
- Window aggregation (avg latency, p95, throughput, error rate)
- Subscriber queue full handling (drop not block)
- Dead subscriber cleanup
- Multi-stage metrics
"""
from __future__ import annotations

import asyncio
import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rot.control.telemetry_bus import (
    StageMetrics,
    TelemetryBus,
    TelemetrySnapshot,
    _WindowStats,
    _aggregate,
)


# ── StageMetrics ──────────────────────────────────────────────────────────────

class TestStageMetrics:
    def test_basic_construction(self):
        m = StageMetrics(
            stage="nlp", ts=1000.0, latency_ms=42.0, items_in=10, items_out=8
        )
        assert m.stage == "nlp"
        assert m.latency_ms == 42.0
        assert m.items_in == 10
        assert m.items_out == 8
        assert m.errors == 0
        assert m.extra == {}

    def test_throughput_ratio_normal(self):
        m = StageMetrics(stage="a", ts=0, latency_ms=1, items_in=10, items_out=7)
        assert math.isclose(m.throughput_ratio, 0.7)

    def test_throughput_ratio_zero_items_in(self):
        m = StageMetrics(stage="a", ts=0, latency_ms=1, items_in=0, items_out=0)
        assert m.throughput_ratio == 1.0

    def test_throughput_ratio_full_pass(self):
        m = StageMetrics(stage="a", ts=0, latency_ms=1, items_in=5, items_out=5)
        assert m.throughput_ratio == 1.0

    def test_error_rate_normal(self):
        m = StageMetrics(stage="a", ts=0, latency_ms=1, items_in=100, items_out=95, errors=5)
        assert math.isclose(m.error_rate, 0.05)

    def test_error_rate_zero_items_in(self):
        m = StageMetrics(stage="a", ts=0, latency_ms=1, items_in=0, items_out=0, errors=0)
        assert m.error_rate == 0.0

    def test_extra_populated(self):
        m = StageMetrics(
            stage="market", ts=0, latency_ms=1, items_in=5, items_out=5,
            extra={"iv_filter_rate": 0.6}
        )
        assert m.extra["iv_filter_rate"] == 0.6

    def test_stage_name_preserved(self):
        for name in ["nlp", "credibility", "suppression", "market"]:
            m = StageMetrics(stage=name, ts=0, latency_ms=1, items_in=1, items_out=1)
            assert m.stage == name


# ── _aggregate helper ─────────────────────────────────────────────────────────

class TestAggregate:
    def _make_metrics(self, latency: float, items_in: int = 10, items_out: int = 8,
                       errors: int = 0) -> StageMetrics:
        return StageMetrics(
            stage="test", ts=time.time(), latency_ms=latency,
            items_in=items_in, items_out=items_out, errors=errors
        )

    def test_single_sample(self):
        samples = [self._make_metrics(50.0)]
        stats = _aggregate("1m", samples)
        assert stats.sample_count == 1
        assert math.isclose(stats.avg_latency_ms, 50.0)
        assert math.isclose(stats.p95_latency_ms, 50.0)

    def test_p95_with_multiple_samples(self):
        # 20 samples: latencies 1..20
        samples = [self._make_metrics(float(i)) for i in range(1, 21)]
        stats = _aggregate("5m", samples)
        # p95 index = ceil(20 * 0.95) - 1 = 19 - 1 = 18 → value 19
        assert stats.p95_latency_ms == 19.0

    def test_avg_latency(self):
        samples = [self._make_metrics(10.0), self._make_metrics(20.0), self._make_metrics(30.0)]
        stats = _aggregate("5m", samples)
        assert math.isclose(stats.avg_latency_ms, 20.0)

    def test_throughput_and_error_aggregation(self):
        samples = [
            self._make_metrics(10.0, items_in=10, items_out=8, errors=1),
            self._make_metrics(20.0, items_in=10, items_out=10, errors=0),
        ]
        stats = _aggregate("5m", samples)
        assert math.isclose(stats.avg_throughput_ratio, 0.9)  # (0.8+1.0)/2
        assert math.isclose(stats.avg_error_rate, 0.05)  # (0.1+0.0)/2

    def test_total_items(self):
        samples = [
            self._make_metrics(10.0, items_in=5, items_out=4),
            self._make_metrics(20.0, items_in=3, items_out=3),
        ]
        stats = _aggregate("5m", samples)
        assert stats.total_items_in == 8
        assert stats.total_items_out == 7

    def test_window_name_preserved(self):
        stats = _aggregate("15m", [self._make_metrics(1.0)])
        assert stats.window_name == "15m"


# ── TelemetryBus.report() ────────────────────────────────────────────────────

class TestTelemetryBusReport:
    def _make_bus(self) -> TelemetryBus:
        return TelemetryBus(interval_s=1.0)

    def _make_metrics(self, stage: str, ts: float = None) -> StageMetrics:
        return StageMetrics(
            stage=stage, ts=ts or time.time(),
            latency_ms=10.0, items_in=5, items_out=5
        )

    def test_report_creates_ring_entry(self):
        bus = self._make_bus()
        m = self._make_metrics("nlp")
        bus.report("nlp", m)
        assert "nlp" in bus._ring
        assert len(bus._ring["nlp"]) == 1

    def test_report_multiple_samples_same_stage(self):
        bus = self._make_bus()
        for _ in range(5):
            bus.report("nlp", self._make_metrics("nlp"))
        assert len(bus._ring["nlp"]) == 5

    def test_report_multiple_stages(self):
        bus = self._make_bus()
        bus.report("nlp", self._make_metrics("nlp"))
        bus.report("credibility", self._make_metrics("credibility"))
        bus.report("market", self._make_metrics("market"))
        assert len(bus._ring) == 3

    def test_ring_prunes_old_samples(self):
        bus = self._make_bus()
        old_ts = time.time() - 4000  # older than 1h
        bus.report("nlp", self._make_metrics("nlp", ts=old_ts))
        new_ts = time.time()
        bus.report("nlp", self._make_metrics("nlp", ts=new_ts))
        # Old entry should be pruned on next report
        assert len(bus._ring["nlp"]) == 1

    def test_ring_retains_samples_within_window(self):
        bus = self._make_bus()
        now = time.time()
        for i in range(10):
            ts = now - i * 60  # 1 minute apart, all within 1h
            bus.report("nlp", self._make_metrics("nlp", ts=ts))
        assert len(bus._ring["nlp"]) == 10


# ── TelemetryBus.latest_snapshot() ───────────────────────────────────────────

class TestTelemetryBusSnapshot:
    def test_empty_bus_returns_none(self):
        bus = TelemetryBus()
        assert bus.latest_snapshot() is None

    def test_snapshot_contains_stage(self):
        bus = TelemetryBus()
        m = StageMetrics(stage="nlp", ts=time.time(), latency_ms=20.0, items_in=10, items_out=10)
        bus.report("nlp", m)
        snap = bus.latest_snapshot()
        assert snap is not None
        assert "nlp" in snap.per_stage

    def test_snapshot_pressure_zero_when_perfect(self):
        bus = TelemetryBus()
        m = StageMetrics(stage="s", ts=time.time(), latency_ms=1.0, items_in=10, items_out=10, errors=0)
        bus.report("s", m)
        snap = bus.latest_snapshot()
        assert snap is not None
        assert snap.pressure == 0.0

    def test_snapshot_pressure_elevated_with_errors(self):
        bus = TelemetryBus()
        m = StageMetrics(stage="s", ts=time.time(), latency_ms=1.0, items_in=10, items_out=10, errors=5)
        bus.report("s", m)
        snap = bus.latest_snapshot()
        assert snap is not None
        assert snap.pressure > 0.0

    def test_snapshot_pressure_capped_at_one(self):
        bus = TelemetryBus()
        # All items fail, all dropped
        m = StageMetrics(stage="s", ts=time.time(), latency_ms=1.0, items_in=100, items_out=0, errors=100)
        bus.report("s", m)
        snap = bus.latest_snapshot()
        assert snap is not None
        assert snap.pressure <= 1.0

    def test_snapshot_has_ts(self):
        bus = TelemetryBus()
        bus.report("s", StageMetrics(stage="s", ts=time.time(), latency_ms=1, items_in=1, items_out=1))
        snap = bus.latest_snapshot()
        assert snap is not None
        assert snap.ts > 0


# ── TelemetryBus subscribe / unsubscribe ─────────────────────────────────────

class TestTelemetryBusSubscription:
    def test_subscribe_returns_queue(self):
        bus = TelemetryBus()
        q = bus.subscribe()
        assert q is not None
        assert len(bus._subscribers) == 1

    def test_unsubscribe_removes_queue(self):
        bus = TelemetryBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        assert len(bus._subscribers) == 0

    def test_unsubscribe_unknown_queue_no_error(self):
        bus = TelemetryBus()
        other_q: asyncio.Queue = asyncio.Queue()
        bus.unsubscribe(other_q)  # Should not raise

    def test_multiple_subscribers(self):
        bus = TelemetryBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        q3 = bus.subscribe()
        assert len(bus._subscribers) == 3
        bus.unsubscribe(q2)
        assert len(bus._subscribers) == 2
        assert q1 in bus._subscribers
        assert q3 in bus._subscribers


# ── TelemetryBus broadcast ───────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTelemetryBusBroadcast:
    async def test_broadcast_delivers_snapshot(self):
        bus = TelemetryBus(interval_s=0.05)
        q = bus.subscribe()
        bus.report("nlp", StageMetrics(stage="nlp", ts=time.time(), latency_ms=5, items_in=3, items_out=3))
        await bus.start()
        try:
            snap = await asyncio.wait_for(q.get(), timeout=1.0)
            assert isinstance(snap, TelemetrySnapshot)
        finally:
            await bus.stop()

    async def test_broadcast_drops_when_queue_full(self):
        """A full subscriber queue should not block the broadcast loop."""
        bus = TelemetryBus(interval_s=0.05)
        # Subscribe with a tiny queue that fills instantly
        q: asyncio.Queue[TelemetrySnapshot] = asyncio.Queue(maxsize=1)
        bus._subscribers.append(q)
        bus.report("nlp", StageMetrics(stage="nlp", ts=time.time(), latency_ms=5, items_in=1, items_out=1))
        await bus.start()
        # Wait for two broadcast intervals — second should drop not block
        await asyncio.sleep(0.15)
        await bus.stop()
        # Bus should still be functional

    async def test_start_stop_lifecycle(self):
        bus = TelemetryBus(interval_s=0.1)
        await bus.start()
        assert bus._running is True
        await bus.stop()
        assert bus._running is False

    async def test_stop_without_start_noop(self):
        bus = TelemetryBus()
        await bus.stop()  # Should not raise


# ── Pressure computation ──────────────────────────────────────────────────────

class TestPressureComputation:
    def test_pressure_zero_no_errors_full_throughput(self):
        bus = TelemetryBus()
        per_stage = {
            "nlp": StageMetrics("nlp", ts=0, latency_ms=1, items_in=10, items_out=10, errors=0),
            "cred": StageMetrics("cred", ts=0, latency_ms=2, items_in=10, items_out=10, errors=0),
        }
        pressure = bus._compute_pressure(per_stage)
        assert pressure == 0.0

    def test_pressure_increases_with_errors(self):
        bus = TelemetryBus()
        per_stage = {
            "nlp": StageMetrics("nlp", ts=0, latency_ms=1, items_in=10, items_out=10, errors=5),
        }
        pressure = bus._compute_pressure(per_stage)
        assert pressure > 0.0

    def test_pressure_increases_with_low_throughput(self):
        bus = TelemetryBus()
        per_stage = {
            "nlp": StageMetrics("nlp", ts=0, latency_ms=1, items_in=10, items_out=1, errors=0),
        }
        pressure = bus._compute_pressure(per_stage)
        assert pressure > 0.0

    def test_pressure_capped_at_one(self):
        bus = TelemetryBus()
        per_stage = {
            "nlp": StageMetrics("nlp", ts=0, latency_ms=1, items_in=10, items_out=0, errors=10),
        }
        pressure = bus._compute_pressure(per_stage)
        assert pressure <= 1.0

    def test_pressure_empty_stages(self):
        bus = TelemetryBus()
        pressure = bus._compute_pressure({})
        assert pressure == 0.0
