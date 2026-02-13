"""Tests for export scheduler."""

from __future__ import annotations

import csv
import io
import json
import time

import pytest

from rot.export.scheduler import ExportScheduler
from rot.export.types import ExportJob, ExportResult, ScheduleConfig


# ── Helpers ──


def _make_job(
    frequency: str = "daily",
    fmt: str = "csv",
    status: str = "pending",
    next_run_at: float | None = None,
    run_count: int = 0,
    **kwargs,
) -> ExportJob:
    cfg = ScheduleConfig(frequency=frequency, format=fmt, **kwargs)
    return ExportJob(
        id="j1",
        user_id="u1",
        schedule_config=cfg,
        status=status,
        created_at=time.time(),
        next_run_at=next_run_at,
        run_count=run_count,
    )


def _make_signals(count: int = 5) -> list:
    signals = []
    now = time.time()
    for i in range(count):
        signals.append({
            "id": f"sig-{i}",
            "ticker": "AAPL" if i % 2 == 0 else "MSFT",
            "event_type": "earnings_rumor",
            "stance": "bullish",
            "time_horizon": "1w",
            "confidence": 0.5 + i * 0.05,
            "trend_score": 0.3,
            "quality_score": 0.6,
            "strategy": "debit_spread",
            "subreddit": "wallstreetbets",
            "post_title": f"Signal {i}",
            "created_at": now - i * 3600,
            "sector": "Technology",
        })
    return signals


# ── Schedule Management ──


class TestScheduleManagement:
    """Export scheduling tests."""

    def test_create_job_daily(self):
        scheduler = ExportScheduler()
        cfg = ScheduleConfig(frequency="daily", format="csv")
        job = scheduler.create_job("u1", cfg)
        assert job.user_id == "u1"
        assert job.status == "pending"
        assert job.run_count == 0
        assert job.next_run_at is not None
        # Next run should be ~24h from now
        assert job.next_run_at > time.time()
        assert job.next_run_at <= time.time() + 86401

    def test_create_job_weekly(self):
        scheduler = ExportScheduler()
        cfg = ScheduleConfig(frequency="weekly")
        job = scheduler.create_job("u1", cfg)
        assert job.next_run_at is not None
        assert job.next_run_at > time.time() + 86400 * 6

    def test_create_job_on_demand(self):
        scheduler = ExportScheduler()
        cfg = ScheduleConfig(frequency="on_demand")
        job = scheduler.create_job("u1", cfg)
        # On-demand runs immediately
        assert job.next_run_at is not None
        assert job.next_run_at <= time.time() + 1

    def test_pending_jobs_due(self):
        scheduler = ExportScheduler()
        job = _make_job(next_run_at=time.time() - 100)
        pending = scheduler.get_pending_jobs([job])
        assert len(pending) == 1

    def test_pending_jobs_not_due(self):
        scheduler = ExportScheduler()
        job = _make_job(next_run_at=time.time() + 86400)
        pending = scheduler.get_pending_jobs([job])
        assert len(pending) == 0

    def test_pending_jobs_on_demand_first_run(self):
        scheduler = ExportScheduler()
        job = _make_job(
            frequency="on_demand", next_run_at=None, run_count=0,
        )
        pending = scheduler.get_pending_jobs([job])
        assert len(pending) == 1

    def test_pending_jobs_on_demand_already_ran(self):
        scheduler = ExportScheduler()
        job = _make_job(
            frequency="on_demand", next_run_at=None, run_count=1,
            status="completed",
        )
        pending = scheduler.get_pending_jobs([job])
        assert len(pending) == 0

    def test_pending_skips_running(self):
        scheduler = ExportScheduler()
        job = _make_job(status="running", next_run_at=time.time() - 100)
        pending = scheduler.get_pending_jobs([job])
        assert len(pending) == 0

    def test_pending_skips_failed(self):
        scheduler = ExportScheduler()
        job = _make_job(status="failed", next_run_at=time.time() - 100)
        pending = scheduler.get_pending_jobs([job])
        assert len(pending) == 0

    def test_compute_next_run_daily(self):
        scheduler = ExportScheduler()
        job = _make_job(frequency="daily")
        updated = scheduler.compute_next_run(job)
        assert updated.status == "completed"
        assert updated.run_count == 1
        assert updated.last_run_at is not None
        assert updated.next_run_at is not None
        assert updated.next_run_at > time.time() + 86399

    def test_compute_next_run_on_demand(self):
        scheduler = ExportScheduler()
        job = _make_job(frequency="on_demand")
        updated = scheduler.compute_next_run(job)
        assert updated.status == "completed"
        assert updated.next_run_at is None  # no future runs
        assert updated.run_count == 1


# ── CSV Generation ──


class TestCSVGeneration:
    """CSV export tests."""

    @pytest.mark.asyncio
    async def test_csv_basic(self):
        scheduler = ExportScheduler()
        job = _make_job(fmt="csv")
        signals = _make_signals(3)
        result = await scheduler.generate_export(job, signals)
        assert result.row_count == 3
        assert result.format == "csv"
        assert result.job_id == "j1"
        # Parse CSV
        reader = csv.DictReader(io.StringIO(result.data))
        rows = list(reader)
        assert len(rows) == 3
        assert rows[0]["ticker"] in ("AAPL", "MSFT")

    @pytest.mark.asyncio
    async def test_csv_empty(self):
        scheduler = ExportScheduler()
        job = _make_job(fmt="csv")
        result = await scheduler.generate_export(job, [])
        assert result.row_count == 0
        assert result.data == ""

    @pytest.mark.asyncio
    async def test_csv_max_rows(self):
        scheduler = ExportScheduler()
        job = _make_job(fmt="csv", max_rows=2)
        signals = _make_signals(5)
        result = await scheduler.generate_export(job, signals)
        assert result.row_count == 2

    @pytest.mark.asyncio
    async def test_csv_columns(self):
        scheduler = ExportScheduler()
        job = _make_job(fmt="csv")
        signals = _make_signals(1)
        result = await scheduler.generate_export(job, signals)
        reader = csv.DictReader(io.StringIO(result.data))
        rows = list(reader)
        assert "ticker" in rows[0]
        assert "confidence" in rows[0]
        assert "strategy" in rows[0]


# ── JSON Generation ──


class TestJSONGeneration:
    """JSON export tests."""

    @pytest.mark.asyncio
    async def test_json_basic(self):
        scheduler = ExportScheduler()
        job = _make_job(fmt="json")
        signals = _make_signals(3)
        result = await scheduler.generate_export(job, signals)
        assert result.row_count == 3
        assert result.format == "json"
        data = json.loads(result.data)
        assert data["count"] == 3
        assert len(data["signals"]) == 3

    @pytest.mark.asyncio
    async def test_json_with_lineage(self):
        scheduler = ExportScheduler()
        job = _make_job(fmt="json")
        signals = _make_signals(2)
        lineage = [{"signal_id": "sig-0", "steps": []}]
        result = await scheduler.generate_export(job, signals, lineage_data=lineage)
        data = json.loads(result.data)
        assert "lineage" in data
        assert len(data["lineage"]) == 1

    @pytest.mark.asyncio
    async def test_json_empty(self):
        scheduler = ExportScheduler()
        job = _make_job(fmt="json")
        result = await scheduler.generate_export(job, [])
        data = json.loads(result.data)
        assert data["count"] == 0
        assert data["signals"] == []


# ── Export Result Metadata ──


class TestExportResultMetadata:
    """Export result metadata tests."""

    @pytest.mark.asyncio
    async def test_duration_tracked(self):
        scheduler = ExportScheduler()
        job = _make_job(fmt="csv")
        signals = _make_signals(10)
        result = await scheduler.generate_export(job, signals)
        assert result.duration_s >= 0.0
        assert result.generated_at > 0

    @pytest.mark.asyncio
    async def test_result_to_dict(self):
        scheduler = ExportScheduler()
        job = _make_job(fmt="csv")
        signals = _make_signals(5)
        result = await scheduler.generate_export(job, signals)
        d = result.to_dict()
        assert d["row_count"] == 5
        assert d["format"] == "csv"
        assert "duration_s" in d
