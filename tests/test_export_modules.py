"""Tests for rot.export — ExportScheduler, LineageBuilder, and export types.

Covers ExportScheduler: create_job, get_pending_jobs, compute_next_run,
generate_export (CSV/JSON), run_pending_exports, _to_csv, _to_json.
Covers LineageBuilder: build_lineage (all 9 steps), build_batch_lineage,
JSON string parsing, source type detection.
Covers export types: ScheduleConfig, ExportJob, ExportResult, LineageStep,
SignalLineage — to_dict, frozen, default values.
"""
from __future__ import annotations

import csv
import io
import json
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from rot.export.lineage import LineageBuilder
from rot.export.scheduler import ExportScheduler, _FREQ_S
from rot.export.types import (
    ExportJob,
    ExportResult,
    LineageStep,
    ScheduleConfig,
    SignalLineage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> ScheduleConfig:
    defaults = dict(
        frequency="daily",
        format="csv",
        export_type="signals",
        filters={},
        include_lineage=False,
        max_rows=10000,
    )
    defaults.update(overrides)
    return ScheduleConfig(**defaults)


def _make_job(
    job_id: str = "job-1",
    user_id: str = "user-1",
    config: ScheduleConfig = None,
    status: str = "pending",
    next_run_at: float = None,
    run_count: int = 0,
    **overrides,
) -> ExportJob:
    if config is None:
        config = _make_config()
    if next_run_at is None:
        next_run_at = time.time() - 10  # Due to run
    return ExportJob(
        id=job_id,
        user_id=user_id,
        schedule_config=config,
        status=status,
        next_run_at=next_run_at,
        run_count=run_count,
        **overrides,
    )


def _make_signal(**overrides) -> Dict[str, Any]:
    defaults = dict(
        id="sig-1",
        ticker="AAPL",
        event_type="earnings",
        stance="bullish",
        time_horizon="1w",
        confidence=0.75,
        trend_score=0.8,
        quality_score=72,
        strategy="debit_spread",
        subreddit="options",
        post_title="AAPL earnings play",
        created_at=1700000000,
        sector="Technology",
    )
    defaults.update(overrides)
    return defaults


# =========================================================================
# Part 1: Export Types
# =========================================================================


class TestScheduleConfig:
    def test_default_values(self):
        c = ScheduleConfig()
        assert c.frequency == "daily"
        assert c.format == "csv"
        assert c.export_type == "signals"
        assert c.filters == {}
        assert c.include_lineage is False
        assert c.max_rows == 10000

    def test_custom_values(self):
        c = ScheduleConfig(frequency="weekly", format="json", max_rows=500)
        assert c.frequency == "weekly"
        assert c.format == "json"
        assert c.max_rows == 500

    def test_frozen(self):
        c = ScheduleConfig()
        with pytest.raises(AttributeError):
            c.frequency = "weekly"

    def test_to_dict(self):
        c = ScheduleConfig(frequency="weekly", format="json")
        d = c.to_dict()
        assert d["frequency"] == "weekly"
        assert d["format"] == "json"
        assert d["max_rows"] == 10000

    def test_to_dict_includes_all_fields(self):
        c = ScheduleConfig()
        d = c.to_dict()
        expected_keys = {"frequency", "format", "export_type", "filters", "include_lineage", "max_rows"}
        assert set(d.keys()) == expected_keys


class TestExportJob:
    def test_default_values(self):
        j = ExportJob(id="j1", user_id="u1", schedule_config=ScheduleConfig())
        assert j.status == "pending"
        assert j.run_count == 0
        assert j.last_run_at is None
        assert j.next_run_at is None

    def test_frozen(self):
        j = ExportJob(id="j1", user_id="u1", schedule_config=ScheduleConfig())
        with pytest.raises(AttributeError):
            j.status = "completed"

    def test_to_dict(self):
        j = ExportJob(id="j1", user_id="u1", schedule_config=ScheduleConfig())
        d = j.to_dict()
        assert d["id"] == "j1"
        assert d["user_id"] == "u1"
        assert isinstance(d["schedule_config"], dict)
        assert d["status"] == "pending"

    def test_to_dict_includes_all_fields(self):
        j = ExportJob(id="j1", user_id="u1", schedule_config=ScheduleConfig())
        d = j.to_dict()
        expected = {"id", "user_id", "schedule_config", "status", "created_at",
                    "last_run_at", "next_run_at", "run_count"}
        assert set(d.keys()) == expected


class TestExportResult:
    def test_creation(self):
        r = ExportResult(job_id="j1", row_count=100, format="csv", data="a,b\n1,2", generated_at=1.0)
        assert r.row_count == 100
        assert r.format == "csv"
        assert r.duration_s == 0.0

    def test_frozen(self):
        r = ExportResult(job_id="j1", row_count=100, format="csv", data="", generated_at=1.0)
        with pytest.raises(AttributeError):
            r.row_count = 200

    def test_to_dict(self):
        r = ExportResult(job_id="j1", row_count=100, format="csv", data="data",
                         generated_at=1.0, duration_s=0.123456)
        d = r.to_dict()
        assert d["job_id"] == "j1"
        assert d["duration_s"] == 0.12  # Rounded to 2 decimal places
        # data is NOT in to_dict (it's raw export data)
        assert "data" not in d


class TestLineageStep:
    def test_creation(self):
        s = LineageStep(stage="ingestion", timestamp=1.0, details={"source": "reddit"})
        assert s.stage == "ingestion"
        assert s.details["source"] == "reddit"

    def test_default_details(self):
        s = LineageStep(stage="test", timestamp=1.0)
        assert s.details == {}

    def test_to_dict(self):
        s = LineageStep(stage="ingestion", timestamp=1.0, details={"key": "val"})
        d = s.to_dict()
        assert d["stage"] == "ingestion"
        assert d["timestamp"] == 1.0
        assert d["details"]["key"] == "val"


class TestSignalLineage:
    def test_creation(self):
        sl = SignalLineage(signal_id="s1", ticker="AAPL", source="reddit")
        assert sl.signal_id == "s1"
        assert sl.steps == []

    def test_total_processing_time_empty(self):
        sl = SignalLineage(signal_id="s1", ticker="AAPL")
        assert sl.total_processing_time_s == 0.0

    def test_total_processing_time_single_step(self):
        sl = SignalLineage(
            signal_id="s1", ticker="AAPL",
            steps=[LineageStep(stage="ingestion", timestamp=1.0)],
        )
        assert sl.total_processing_time_s == 0.0

    def test_total_processing_time_multiple_steps(self):
        sl = SignalLineage(
            signal_id="s1", ticker="AAPL",
            steps=[
                LineageStep(stage="ingestion", timestamp=1.0),
                LineageStep(stage="storage", timestamp=1.8),
            ],
        )
        assert sl.total_processing_time_s == pytest.approx(0.8)

    def test_to_dict(self):
        sl = SignalLineage(
            signal_id="s1", ticker="AAPL", source="reddit", created_at=100.0,
            steps=[LineageStep(stage="ingestion", timestamp=100.0)],
        )
        d = sl.to_dict()
        assert d["signal_id"] == "s1"
        assert d["ticker"] == "AAPL"
        assert d["source"] == "reddit"
        assert len(d["steps"]) == 1
        assert "total_processing_time_s" in d


# =========================================================================
# Part 2: ExportScheduler
# =========================================================================


class TestFrequencyConstants:
    def test_daily_frequency(self):
        assert _FREQ_S["daily"] == 86400

    def test_weekly_frequency(self):
        assert _FREQ_S["weekly"] == 86400 * 7

    def test_on_demand_frequency(self):
        assert _FREQ_S["on_demand"] == 0


class TestCreateJob:
    def test_creates_job_with_uuid(self):
        scheduler = ExportScheduler()
        config = _make_config()
        job = scheduler.create_job("user-1", config)
        assert job.id  # Non-empty UUID
        assert len(job.id) == 36  # UUID format
        assert job.user_id == "user-1"
        assert job.status == "pending"

    def test_daily_job_next_run_in_future(self):
        scheduler = ExportScheduler()
        config = _make_config(frequency="daily")
        job = scheduler.create_job("user-1", config)
        assert job.next_run_at > time.time() - 1

    def test_weekly_job_next_run_in_future(self):
        scheduler = ExportScheduler()
        config = _make_config(frequency="weekly")
        job = scheduler.create_job("user-1", config)
        assert job.next_run_at > time.time() + 86400  # More than 1 day away

    def test_on_demand_job_runs_immediately(self):
        scheduler = ExportScheduler()
        config = _make_config(frequency="on_demand")
        job = scheduler.create_job("user-1", config)
        assert job.next_run_at <= time.time() + 1

    def test_preserves_config(self):
        scheduler = ExportScheduler()
        config = _make_config(format="json", max_rows=500)
        job = scheduler.create_job("user-1", config)
        assert job.schedule_config.format == "json"
        assert job.schedule_config.max_rows == 500

    @pytest.mark.parametrize("frequency", ["daily", "weekly", "on_demand"])
    def test_all_frequencies_accepted(self, frequency):
        scheduler = ExportScheduler()
        config = _make_config(frequency=frequency)
        job = scheduler.create_job("user-1", config)
        assert job.schedule_config.frequency == frequency


class TestGetPendingJobs:
    def test_returns_due_pending_jobs(self):
        scheduler = ExportScheduler()
        job = _make_job(next_run_at=time.time() - 10, status="pending")
        result = scheduler.get_pending_jobs([job])
        assert len(result) == 1

    def test_returns_due_completed_jobs(self):
        scheduler = ExportScheduler()
        job = _make_job(next_run_at=time.time() - 10, status="completed")
        result = scheduler.get_pending_jobs([job])
        assert len(result) == 1

    def test_excludes_running_jobs(self):
        scheduler = ExportScheduler()
        job = _make_job(next_run_at=time.time() - 10, status="running")
        result = scheduler.get_pending_jobs([job])
        assert len(result) == 0

    def test_excludes_failed_jobs(self):
        scheduler = ExportScheduler()
        job = _make_job(next_run_at=time.time() - 10, status="failed")
        result = scheduler.get_pending_jobs([job])
        assert len(result) == 0

    def test_excludes_not_yet_due(self):
        scheduler = ExportScheduler()
        job = _make_job(next_run_at=time.time() + 3600, status="pending")
        result = scheduler.get_pending_jobs([job])
        assert len(result) == 0

    def test_on_demand_first_run_always_pending(self):
        scheduler = ExportScheduler()
        config = _make_config(frequency="on_demand")
        job = _make_job(config=config, next_run_at=time.time() + 9999, run_count=0)
        result = scheduler.get_pending_jobs([job])
        assert len(result) == 1

    def test_on_demand_second_run_not_pending(self):
        scheduler = ExportScheduler()
        config = _make_config(frequency="on_demand")
        job = _make_job(config=config, next_run_at=time.time() + 9999, run_count=1)
        result = scheduler.get_pending_jobs([job])
        assert len(result) == 0

    def test_empty_list(self):
        scheduler = ExportScheduler()
        result = scheduler.get_pending_jobs([])
        assert result == []

    def test_multiple_jobs_filtered(self):
        scheduler = ExportScheduler()
        jobs = [
            _make_job(job_id="j1", next_run_at=time.time() - 10, status="pending"),
            _make_job(job_id="j2", next_run_at=time.time() + 3600, status="pending"),
            _make_job(job_id="j3", next_run_at=time.time() - 10, status="failed"),
            _make_job(job_id="j4", next_run_at=time.time() - 10, status="completed"),
        ]
        result = scheduler.get_pending_jobs(jobs)
        assert len(result) == 2
        ids = {j.id for j in result}
        assert ids == {"j1", "j4"}


class TestComputeNextRun:
    def test_daily_next_run(self):
        scheduler = ExportScheduler()
        config = _make_config(frequency="daily")
        job = _make_job(config=config, run_count=0)
        updated = scheduler.compute_next_run(job)
        assert updated.status == "completed"
        assert updated.run_count == 1
        assert updated.next_run_at > time.time()
        assert updated.next_run_at <= time.time() + 86401

    def test_weekly_next_run(self):
        scheduler = ExportScheduler()
        config = _make_config(frequency="weekly")
        job = _make_job(config=config, run_count=0)
        updated = scheduler.compute_next_run(job)
        assert updated.next_run_at > time.time() + 86400

    def test_on_demand_no_next_run(self):
        scheduler = ExportScheduler()
        config = _make_config(frequency="on_demand")
        job = _make_job(config=config, run_count=0)
        updated = scheduler.compute_next_run(job)
        assert updated.next_run_at is None
        assert updated.status == "completed"
        assert updated.run_count == 1

    def test_increments_run_count(self):
        scheduler = ExportScheduler()
        job = _make_job(run_count=5)
        updated = scheduler.compute_next_run(job)
        assert updated.run_count == 6

    def test_sets_last_run_at(self):
        scheduler = ExportScheduler()
        job = _make_job()
        updated = scheduler.compute_next_run(job)
        assert updated.last_run_at is not None
        assert abs(updated.last_run_at - time.time()) < 2


# ---------------------------------------------------------------------------
# CSV Generation
# ---------------------------------------------------------------------------


class TestToCsv:
    def test_empty_signals_returns_empty_string(self):
        scheduler = ExportScheduler()
        assert scheduler._to_csv([]) == ""

    def test_single_signal_csv(self):
        scheduler = ExportScheduler()
        signals = [_make_signal()]
        result = scheduler._to_csv(signals)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"

    def test_csv_header_columns(self):
        scheduler = ExportScheduler()
        signals = [_make_signal()]
        result = scheduler._to_csv(signals)
        lines = result.strip().split("\n")
        header = lines[0]
        assert "id" in header
        assert "ticker" in header
        assert "event_type" in header
        assert "strategy" in header

    def test_multiple_signals(self):
        scheduler = ExportScheduler()
        signals = [
            _make_signal(id="s1", ticker="AAPL"),
            _make_signal(id="s2", ticker="TSLA"),
            _make_signal(id="s3", ticker="MSFT"),
        ]
        result = scheduler._to_csv(signals)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 3

    def test_dict_values_serialized_as_json(self):
        scheduler = ExportScheduler()
        signals = [_make_signal(sector={"name": "Tech"})]
        result = scheduler._to_csv(signals)
        assert '"name"' in result

    def test_missing_fields_use_empty_string(self):
        scheduler = ExportScheduler()
        signals = [{"id": "s1"}]  # Most fields missing
        result = scheduler._to_csv(signals)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows[0]["ticker"] == ""


# ---------------------------------------------------------------------------
# JSON Generation
# ---------------------------------------------------------------------------


class TestToJson:
    def test_empty_signals(self):
        scheduler = ExportScheduler()
        result = scheduler._to_json([])
        data = json.loads(result)
        assert data["signals"] == []
        assert data["count"] == 0

    def test_single_signal(self):
        scheduler = ExportScheduler()
        result = scheduler._to_json([_make_signal()])
        data = json.loads(result)
        assert data["count"] == 1
        assert data["signals"][0]["ticker"] == "AAPL"

    def test_includes_exported_at(self):
        scheduler = ExportScheduler()
        result = scheduler._to_json([])
        data = json.loads(result)
        assert "exported_at" in data

    def test_includes_lineage_when_provided(self):
        scheduler = ExportScheduler()
        lineage = [{"signal_id": "s1", "steps": []}]
        result = scheduler._to_json([_make_signal()], lineage=lineage)
        data = json.loads(result)
        assert "lineage" in data
        assert data["lineage"][0]["signal_id"] == "s1"

    def test_no_lineage_key_when_none(self):
        scheduler = ExportScheduler()
        result = scheduler._to_json([_make_signal()])
        data = json.loads(result)
        assert "lineage" not in data

    def test_no_lineage_key_when_empty(self):
        scheduler = ExportScheduler()
        result = scheduler._to_json([_make_signal()], lineage=[])
        data = json.loads(result)
        assert "lineage" not in data


# ---------------------------------------------------------------------------
# generate_export
# ---------------------------------------------------------------------------


class TestGenerateExport:
    @pytest.mark.asyncio
    async def test_csv_export(self):
        scheduler = ExportScheduler()
        config = _make_config(format="csv")
        job = _make_job(config=config)
        signals = [_make_signal()]
        result = await scheduler.generate_export(job, signals)
        assert result.format == "csv"
        assert result.row_count == 1
        assert "AAPL" in result.data

    @pytest.mark.asyncio
    async def test_json_export(self):
        scheduler = ExportScheduler()
        config = _make_config(format="json")
        job = _make_job(config=config)
        signals = [_make_signal()]
        result = await scheduler.generate_export(job, signals)
        assert result.format == "json"
        data = json.loads(result.data)
        assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_max_rows_limit(self):
        scheduler = ExportScheduler()
        config = _make_config(max_rows=2)
        job = _make_job(config=config)
        signals = [_make_signal(id=f"s{i}") for i in range(10)]
        result = await scheduler.generate_export(job, signals)
        assert result.row_count == 2

    @pytest.mark.asyncio
    async def test_includes_lineage_data(self):
        scheduler = ExportScheduler()
        config = _make_config(format="json")
        job = _make_job(config=config)
        lineage = [{"signal_id": "s1", "steps": []}]
        result = await scheduler.generate_export(job, [_make_signal()], lineage_data=lineage)
        data = json.loads(result.data)
        assert "lineage" in data

    @pytest.mark.asyncio
    async def test_duration_is_positive(self):
        scheduler = ExportScheduler()
        job = _make_job()
        result = await scheduler.generate_export(job, [_make_signal()])
        assert result.duration_s >= 0

    @pytest.mark.asyncio
    async def test_job_id_in_result(self):
        scheduler = ExportScheduler()
        job = _make_job(job_id="test-job-123")
        result = await scheduler.generate_export(job, [])
        assert result.job_id == "test-job-123"


# ---------------------------------------------------------------------------
# run_pending_exports
# ---------------------------------------------------------------------------


class TestRunPendingExports:
    @pytest.mark.asyncio
    async def test_runs_pending_jobs(self):
        scheduler = ExportScheduler()
        job = _make_job(next_run_at=time.time() - 10)
        results = await scheduler.run_pending_exports([job])
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_skips_non_pending(self):
        scheduler = ExportScheduler()
        job = _make_job(status="failed", next_run_at=time.time() - 10)
        results = await scheduler.run_pending_exports([job])
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_with_db_fetches_signals(self):
        db = AsyncMock()
        db.get_signals = AsyncMock(return_value=[_make_signal()])
        scheduler = ExportScheduler(db=db)
        config = _make_config(format="json")
        job = _make_job(config=config, next_run_at=time.time() - 10)
        results = await scheduler.run_pending_exports([job])
        assert len(results) == 1
        data = json.loads(results[0].data)
        assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self):
        db = AsyncMock()
        db.get_signals = AsyncMock(side_effect=Exception("db error"))
        scheduler = ExportScheduler(db=db)
        job = _make_job(next_run_at=time.time() - 10)
        # Should not raise
        results = await scheduler.run_pending_exports([job])
        assert len(results) == 0


# ---------------------------------------------------------------------------
# DB property
# ---------------------------------------------------------------------------


class TestDbProperty:
    def test_get_db(self):
        db = MagicMock()
        scheduler = ExportScheduler(db=db)
        assert scheduler.db is db

    def test_set_db(self):
        scheduler = ExportScheduler()
        db = MagicMock()
        scheduler.db = db
        assert scheduler.db is db

    def test_none_db_by_default(self):
        scheduler = ExportScheduler()
        assert scheduler.db is None


# =========================================================================
# Part 3: LineageBuilder
# =========================================================================


class TestLineageIngestion:
    def test_always_has_ingestion_step(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "created_at": 1000}
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "ingestion" in stages

    def test_reddit_source_default(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "subreddit": "options"}
        lineage = builder.build_lineage(signal)
        assert lineage.source == "reddit"

    def test_rss_source_detected(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL", "subreddit": "rss_feed",
            "event_data": json.dumps({"meta": {"rss_feed": "benzinga"}}),
        }
        lineage = builder.build_lineage(signal)
        assert lineage.source == "rss"

    def test_stocktwits_source_detected(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL", "subreddit": "stocktwits",
            "event_data": json.dumps({"meta": {"stocktwits": True}}),
        }
        lineage = builder.build_lineage(signal)
        assert lineage.source == "stocktwits"

    def test_explicit_source_type(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "event_data": json.dumps({"meta": {"source_type": "twitter"}}),
        }
        lineage = builder.build_lineage(signal)
        assert lineage.source == "twitter"


class TestLineageTrendDetection:
    def test_trend_step_when_score_present(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "trend_score": 0.8}
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "trend_detection" in stages

    def test_no_trend_step_when_no_score(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "trend_score": 0}
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "trend_detection" not in stages

    def test_trend_from_meta(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "event_data": json.dumps({"meta": {"trend_score": 0.9}}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "trend_detection" in stages


class TestLineageNlpAnalysis:
    def test_nlp_step_when_data_present(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "event_data": json.dumps({"meta": {"nlp": {"polarity": 0.7}}}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "nlp_analysis" in stages

    def test_nlp_step_from_polarity(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "event_data": json.dumps({"meta": {"nlp_polarity": 0.5}}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "nlp_analysis" in stages

    def test_no_nlp_step_when_no_data(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL"}
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "nlp_analysis" not in stages


class TestLineageEntityExtraction:
    def test_entity_step_when_entities_present(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "event_data": json.dumps({"entities": ["AAPL", "TSLA"]}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "entity_extraction" in stages

    def test_no_entity_step_when_empty(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "event_data": json.dumps({"entities": []}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "entity_extraction" not in stages


class TestLineageMarketEnrichment:
    def test_market_step_when_data_present(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "market_data": json.dumps({"AAPL": {"last_close": 150.0}}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "market_enrichment" in stages

    def test_no_market_step_when_empty(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "market_data": "{}"}
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "market_enrichment" not in stages


class TestLineageCredibilityScoring:
    def test_always_has_credibility_step(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL"}
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "credibility_scoring" in stages


class TestLineageLlmReasoning:
    def test_reasoning_step_when_thesis_present(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "reasoning": json.dumps({"thesis": "Strong earnings expected"}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "llm_reasoning" in stages

    def test_thesis_truncated_to_200_chars(self):
        builder = LineageBuilder()
        long_thesis = "A" * 500
        signal = {
            "id": "s1", "ticker": "AAPL",
            "reasoning": json.dumps({"thesis": long_thesis}),
        }
        lineage = builder.build_lineage(signal)
        reasoning_step = next(s for s in lineage.steps if s.stage == "llm_reasoning")
        assert len(reasoning_step.details["thesis"]) == 200

    def test_no_reasoning_step_when_no_thesis(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "reasoning": json.dumps({"catalyst_window": "1w"}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "llm_reasoning" not in stages


class TestLineageTradeBuilding:
    def test_trade_step_when_strategy_present(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "trade_idea": json.dumps({"strategy": "debit_spread", "legs": []}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "trade_building" in stages

    def test_no_trade_step_for_none_strategy(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "trade_idea": json.dumps({"strategy": "none"}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "trade_building" not in stages

    def test_trade_step_from_signal_strategy(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "trade_idea": json.dumps({"legs": [{"type": "call"}]}),
            "strategy": "long_call",
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "trade_building" in stages


class TestLineageStorage:
    def test_always_has_storage_step(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "created_at": 1000}
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "storage" in stages

    def test_storage_is_last_step(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "created_at": 1000}
        lineage = builder.build_lineage(signal)
        assert lineage.steps[-1].stage == "storage"


class TestLineageJsonParsing:
    def test_parses_event_data_json_string(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "event_data": json.dumps({"entities": ["AAPL"]}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "entity_extraction" in stages

    def test_handles_invalid_event_data_json(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "event_data": "not json{{{"}
        lineage = builder.build_lineage(signal)
        # Should not crash, just have minimal steps
        assert len(lineage.steps) >= 2  # At least ingestion + storage

    def test_handles_invalid_market_data_json(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "market_data": "bad json"}
        lineage = builder.build_lineage(signal)
        assert len(lineage.steps) >= 2

    def test_handles_invalid_reasoning_json(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "reasoning": "bad json"}
        lineage = builder.build_lineage(signal)
        assert len(lineage.steps) >= 2

    def test_handles_dict_event_data(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL", "event_data": {"entities": ["TSLA"]}}
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "entity_extraction" in stages

    def test_handles_dict_trade_idea(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL",
            "trade_idea": {"strategy": "debit_spread", "legs": [{"type": "call"}]},
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "trade_building" in stages


class TestLineageTimestamps:
    def test_steps_ordered_chronologically(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL", "created_at": 1000, "trend_score": 0.8,
            "confidence": 0.75,
            "event_data": json.dumps({
                "entities": ["AAPL"],
                "meta": {"nlp": {"polarity": 0.5}},
            }),
            "market_data": json.dumps({"AAPL": {"last_close": 150.0}}),
            "reasoning": json.dumps({"thesis": "test"}),
            "trade_idea": json.dumps({"strategy": "debit_spread", "legs": []}),
        }
        lineage = builder.build_lineage(signal)
        timestamps = [s.timestamp for s in lineage.steps]
        assert timestamps == sorted(timestamps)

    def test_all_steps_present_for_full_signal(self):
        builder = LineageBuilder()
        signal = {
            "id": "s1", "ticker": "AAPL", "created_at": 1000, "trend_score": 0.8,
            "confidence": 0.75, "subreddit": "options",
            "event_data": json.dumps({
                "entities": ["AAPL"],
                "meta": {"nlp": {"polarity": 0.5}},
            }),
            "market_data": json.dumps({"AAPL": {"last_close": 150.0}}),
            "reasoning": json.dumps({"thesis": "Strong buy"}),
            "trade_idea": json.dumps({"strategy": "debit_spread", "legs": [{"type": "call"}]}),
        }
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "ingestion" in stages
        assert "trend_detection" in stages
        assert "nlp_analysis" in stages
        assert "entity_extraction" in stages
        assert "market_enrichment" in stages
        assert "credibility_scoring" in stages
        assert "llm_reasoning" in stages
        assert "trade_building" in stages
        assert "storage" in stages
        assert len(stages) == 9


class TestBuildBatchLineage:
    def test_empty_batch(self):
        builder = LineageBuilder()
        result = builder.build_batch_lineage([])
        assert result == []

    def test_single_signal_batch(self):
        builder = LineageBuilder()
        signals = [{"id": "s1", "ticker": "AAPL"}]
        result = builder.build_batch_lineage(signals)
        assert len(result) == 1
        assert result[0].signal_id == "s1"

    def test_multiple_signals_batch(self):
        builder = LineageBuilder()
        signals = [
            {"id": "s1", "ticker": "AAPL"},
            {"id": "s2", "ticker": "TSLA"},
            {"id": "s3", "ticker": "MSFT"},
        ]
        result = builder.build_batch_lineage(signals)
        assert len(result) == 3
        ids = [l.signal_id for l in result]
        assert ids == ["s1", "s2", "s3"]

    @pytest.mark.parametrize("n", [1, 5, 10, 50, 100])
    def test_batch_sizes(self, n):
        builder = LineageBuilder()
        signals = [{"id": f"s{i}", "ticker": "AAPL"} for i in range(n)]
        result = builder.build_batch_lineage(signals)
        assert len(result) == n


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestLineageEdgeCases:
    def test_empty_signal(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage({})
        assert lineage.signal_id == ""
        assert lineage.ticker == ""
        assert len(lineage.steps) >= 2  # ingestion + storage

    def test_missing_all_optional_fields(self):
        builder = LineageBuilder()
        signal = {"id": "s1", "ticker": "AAPL"}
        lineage = builder.build_lineage(signal)
        # Should have at least ingestion, credibility, storage
        stages = [s.stage for s in lineage.steps]
        assert "ingestion" in stages
        assert "credibility_scoring" in stages
        assert "storage" in stages

    def test_none_string_values_in_signal(self):
        builder = LineageBuilder()
        signal = {
            "id": None, "ticker": None,
            "event_data": "{}", "market_data": "{}", "reasoning": "{}",
        }
        lineage = builder.build_lineage(signal)
        # Should not crash
        assert len(lineage.steps) >= 2
