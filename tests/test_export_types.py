"""Tests for enterprise export data types."""

from __future__ import annotations

import time

import pytest

from rot.export.types import (
    ExportJob,
    ExportResult,
    LineageStep,
    ScheduleConfig,
    SignalLineage,
)


# ── ScheduleConfig ──


class TestScheduleConfig:
    """ScheduleConfig tests."""

    def test_defaults(self):
        cfg = ScheduleConfig()
        assert cfg.frequency == "daily"
        assert cfg.format == "csv"
        assert cfg.export_type == "signals"
        assert cfg.filters == {}
        assert cfg.include_lineage is False
        assert cfg.max_rows == 10000

    def test_custom(self):
        cfg = ScheduleConfig(
            frequency="weekly", format="json", export_type="all",
            filters={"ticker": "AAPL"}, include_lineage=True, max_rows=500,
        )
        assert cfg.frequency == "weekly"
        assert cfg.format == "json"
        assert cfg.filters["ticker"] == "AAPL"
        assert cfg.include_lineage is True
        assert cfg.max_rows == 500

    def test_frozen(self):
        cfg = ScheduleConfig()
        with pytest.raises(AttributeError):
            cfg.frequency = "weekly"  # type: ignore[misc]

    def test_to_dict(self):
        cfg = ScheduleConfig(frequency="daily", format="csv")
        d = cfg.to_dict()
        assert d["frequency"] == "daily"
        assert d["format"] == "csv"
        assert d["include_lineage"] is False
        assert d["max_rows"] == 10000


# ── ExportJob ──


class TestExportJob:
    """ExportJob tests."""

    def test_creation(self):
        cfg = ScheduleConfig()
        job = ExportJob(id="j1", user_id="u1", schedule_config=cfg)
        assert job.id == "j1"
        assert job.user_id == "u1"
        assert job.status == "pending"
        assert job.run_count == 0
        assert job.last_run_at is None

    def test_frozen(self):
        cfg = ScheduleConfig()
        job = ExportJob(id="j1", user_id="u1", schedule_config=cfg)
        with pytest.raises(AttributeError):
            job.status = "running"  # type: ignore[misc]

    def test_to_dict(self):
        cfg = ScheduleConfig(frequency="weekly", format="json")
        now = time.time()
        job = ExportJob(
            id="j1", user_id="u1", schedule_config=cfg,
            status="completed", created_at=now, last_run_at=now,
            run_count=3,
        )
        d = job.to_dict()
        assert d["id"] == "j1"
        assert d["user_id"] == "u1"
        assert d["status"] == "completed"
        assert d["run_count"] == 3
        assert d["schedule_config"]["frequency"] == "weekly"


# ── ExportResult ──


class TestExportResult:
    """ExportResult tests."""

    def test_creation(self):
        r = ExportResult(
            job_id="j1", row_count=100, format="csv",
            data="a,b,c\n1,2,3\n", generated_at=time.time(),
            duration_s=0.5,
        )
        assert r.row_count == 100
        assert r.format == "csv"
        assert r.duration_s == 0.5

    def test_to_dict(self):
        r = ExportResult(
            job_id="j1", row_count=50, format="json",
            data="{}", generated_at=time.time(), duration_s=1.234,
        )
        d = r.to_dict()
        assert d["row_count"] == 50
        assert d["duration_s"] == 1.23  # rounded to 2dp

    def test_frozen(self):
        r = ExportResult(
            job_id="j1", row_count=0, format="csv",
            data="", generated_at=0.0,
        )
        with pytest.raises(AttributeError):
            r.row_count = 10  # type: ignore[misc]


# ── LineageStep ──


class TestLineageStep:
    """LineageStep tests."""

    def test_creation(self):
        step = LineageStep(stage="ingestion", timestamp=1000.0)
        assert step.stage == "ingestion"
        assert step.details == {}

    def test_with_details(self):
        step = LineageStep(
            stage="nlp_analysis", timestamp=1000.0,
            details={"polarity": 0.85, "conviction": 0.7},
        )
        assert step.details["polarity"] == 0.85

    def test_to_dict(self):
        step = LineageStep(
            stage="market_enrichment", timestamp=1000.5,
            details={"last_close": 175.50},
        )
        d = step.to_dict()
        assert d["stage"] == "market_enrichment"
        assert d["timestamp"] == 1000.5
        assert d["details"]["last_close"] == 175.50


# ── SignalLineage ──


class TestSignalLineage:
    """SignalLineage tests."""

    def test_empty_steps(self):
        lin = SignalLineage(signal_id="s1", ticker="AAPL")
        assert lin.total_processing_time_s == 0.0
        assert lin.steps == []

    def test_single_step(self):
        lin = SignalLineage(
            signal_id="s1", ticker="AAPL",
            steps=[LineageStep("ingestion", 1000.0)],
        )
        assert lin.total_processing_time_s == 0.0  # need 2+ steps

    def test_processing_time(self):
        steps = [
            LineageStep("ingestion", 1000.0),
            LineageStep("nlp", 1000.3),
            LineageStep("storage", 1001.0),
        ]
        lin = SignalLineage(signal_id="s1", ticker="AAPL", steps=steps)
        assert lin.total_processing_time_s == pytest.approx(1.0, abs=0.01)

    def test_to_dict(self):
        steps = [
            LineageStep("ingestion", 1000.0, {"source": "reddit"}),
            LineageStep("storage", 1000.8, {"signal_id": "s1"}),
        ]
        lin = SignalLineage(
            signal_id="s1", ticker="AAPL", steps=steps,
            source="reddit", created_at=1000.0,
        )
        d = lin.to_dict()
        assert d["signal_id"] == "s1"
        assert d["ticker"] == "AAPL"
        assert d["source"] == "reddit"
        assert len(d["steps"]) == 2
        assert d["total_processing_time_s"] == 0.8

    def test_frozen(self):
        lin = SignalLineage(signal_id="s1", ticker="AAPL")
        with pytest.raises(AttributeError):
            lin.ticker = "MSFT"  # type: ignore[misc]
