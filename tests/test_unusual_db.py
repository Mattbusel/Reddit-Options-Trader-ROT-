"""Tests for unusual events database operations."""

from __future__ import annotations

import time
import pytest
from rot.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    """Create a temporary database with schema."""
    db_path = str(tmp_path / "test_unusual.db")
    d = Database(db_path=db_path)
    await d.connect()
    yield d
    await d.close()


def _make_event_row(
    ticker: str = "SPY",
    event_type: str = "iv_spike",
    score: float = 75.0,
    details: dict | None = None,
    signal_id: str | None = None,
    detected_at: float | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "event_type": event_type,
        "score": score,
        "details": details or {"atm_iv": 0.72},
        "signal_id": signal_id,
        "detected_at": detected_at or time.time(),
    }


# ── save_unusual_events ──


class TestSaveUnusualEvents:
    """Tests for batch event insertion."""

    @pytest.mark.asyncio
    async def test_save_empty(self, db):
        count = await db.save_unusual_events([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_save_single(self, db):
        events = [_make_event_row()]
        count = await db.save_unusual_events(events)
        assert count == 1

    @pytest.mark.asyncio
    async def test_save_batch(self, db):
        events = [
            _make_event_row("SPY", "iv_spike", 80.0),
            _make_event_row("AAPL", "volume_surge", 65.0),
            _make_event_row("TSLA", "sweep", 55.0),
        ]
        count = await db.save_unusual_events(events)
        assert count == 3

    @pytest.mark.asyncio
    async def test_save_with_signal_id(self, db):
        events = [_make_event_row(signal_id="sig-001")]
        await db.save_unusual_events(events)
        results = await db.get_unusual_events(hours=1)
        assert results[0]["signal_id"] == "sig-001"


# ── get_unusual_events ──


class TestGetUnusualEvents:
    """Tests for filtered event queries."""

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        results = await db.get_unusual_events()
        assert results == []

    @pytest.mark.asyncio
    async def test_basic_query(self, db):
        await db.save_unusual_events([
            _make_event_row("SPY", "iv_spike", 80.0),
            _make_event_row("AAPL", "volume_surge", 65.0),
        ])
        results = await db.get_unusual_events(hours=1)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_filter_by_ticker(self, db):
        await db.save_unusual_events([
            _make_event_row("SPY", "iv_spike", 80.0),
            _make_event_row("AAPL", "volume_surge", 65.0),
        ])
        results = await db.get_unusual_events(hours=1, ticker="SPY")
        assert len(results) == 1
        assert results[0]["ticker"] == "SPY"

    @pytest.mark.asyncio
    async def test_filter_by_min_score(self, db):
        await db.save_unusual_events([
            _make_event_row("SPY", "iv_spike", 80.0),
            _make_event_row("AAPL", "volume_surge", 30.0),
        ])
        results = await db.get_unusual_events(hours=1, min_score=50.0)
        assert len(results) == 1
        assert results[0]["score"] == 80.0

    @pytest.mark.asyncio
    async def test_filter_by_event_type(self, db):
        await db.save_unusual_events([
            _make_event_row("SPY", "iv_spike", 80.0),
            _make_event_row("SPY", "sweep", 60.0),
        ])
        results = await db.get_unusual_events(hours=1, event_type="sweep")
        assert len(results) == 1
        assert results[0]["event_type"] == "sweep"

    @pytest.mark.asyncio
    async def test_time_filter(self, db):
        old = _make_event_row(detected_at=time.time() - 7200)  # 2h ago
        new = _make_event_row(detected_at=time.time())
        await db.save_unusual_events([old, new])
        results = await db.get_unusual_events(hours=1)
        assert len(results) == 1  # only new

    @pytest.mark.asyncio
    async def test_limit(self, db):
        events = [_make_event_row(f"T{i}", "iv_spike", float(50 + i)) for i in range(10)]
        await db.save_unusual_events(events)
        results = await db.get_unusual_events(hours=1, limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_details_parsed(self, db):
        await db.save_unusual_events([
            _make_event_row(details={"atm_iv": 0.72, "iv_rank": 92.0}),
        ])
        results = await db.get_unusual_events(hours=1)
        assert isinstance(results[0]["details"], dict)
        assert results[0]["details"]["atm_iv"] == 0.72

    @pytest.mark.asyncio
    async def test_ordered_desc(self, db):
        t1 = time.time() - 60
        t2 = time.time()
        await db.save_unusual_events([
            _make_event_row("SPY", detected_at=t1),
            _make_event_row("AAPL", detected_at=t2),
        ])
        results = await db.get_unusual_events(hours=1)
        assert results[0]["ticker"] == "AAPL"  # newest first


# ── get_unusual_summary ──


class TestGetUnusualSummary:
    """Tests for aggregate summary."""

    @pytest.mark.asyncio
    async def test_empty_summary(self, db):
        summary = await db.get_unusual_summary()
        assert summary["total_events"] == 0

    @pytest.mark.asyncio
    async def test_summary_counts(self, db):
        await db.save_unusual_events([
            _make_event_row("SPY", "iv_spike", 80.0),
            _make_event_row("AAPL", "volume_surge", 60.0),
            _make_event_row("SPY", "sweep", 50.0),
        ])
        summary = await db.get_unusual_summary(hours=1)
        assert summary["total_events"] == 3
        assert summary["unique_tickers"] == 2

    @pytest.mark.asyncio
    async def test_summary_type_breakdown(self, db):
        await db.save_unusual_events([
            _make_event_row("SPY", "iv_spike", 80.0),
            _make_event_row("AAPL", "iv_spike", 70.0),
            _make_event_row("SPY", "sweep", 50.0),
        ])
        summary = await db.get_unusual_summary(hours=1)
        assert summary["type_breakdown"]["iv_spike"] == 2
        assert summary["type_breakdown"]["sweep"] == 1

    @pytest.mark.asyncio
    async def test_summary_top_tickers(self, db):
        await db.save_unusual_events([
            _make_event_row("SPY", "iv_spike", 80.0),
            _make_event_row("SPY", "sweep", 60.0),
            _make_event_row("AAPL", "volume_surge", 70.0),
        ])
        summary = await db.get_unusual_summary(hours=1)
        assert summary["top_tickers"][0]["ticker"] == "SPY"
        assert summary["top_tickers"][0]["count"] == 2


# ── get_unusual_timeline ──


class TestGetUnusualTimeline:
    """Tests for per-ticker timeline."""

    @pytest.mark.asyncio
    async def test_empty_timeline(self, db):
        results = await db.get_unusual_timeline("SPY")
        assert results == []

    @pytest.mark.asyncio
    async def test_timeline_for_ticker(self, db):
        await db.save_unusual_events([
            _make_event_row("SPY", "iv_spike", 80.0),
            _make_event_row("AAPL", "volume_surge", 60.0),
            _make_event_row("SPY", "sweep", 50.0),
        ])
        results = await db.get_unusual_timeline("SPY", days=1)
        assert len(results) == 2
        assert all(r["ticker"] == "SPY" for r in results)

    @pytest.mark.asyncio
    async def test_timeline_ordered_asc(self, db):
        t1 = time.time() - 3600
        t2 = time.time()
        await db.save_unusual_events([
            _make_event_row("SPY", "iv_spike", 80.0, detected_at=t2),
            _make_event_row("SPY", "sweep", 50.0, detected_at=t1),
        ])
        results = await db.get_unusual_timeline("SPY", days=1)
        assert results[0]["detected_at"] < results[1]["detected_at"]


# ── purge_old_unusual_events ──


class TestPurgeUnusualEvents:
    """Tests for event cleanup."""

    @pytest.mark.asyncio
    async def test_purge_nothing(self, db):
        count = await db.purge_old_unusual_events(keep_days=30)
        assert count == 0

    @pytest.mark.asyncio
    async def test_purge_old(self, db):
        old_time = time.time() - (31 * 86400)  # 31 days ago
        await db.save_unusual_events([
            _make_event_row("SPY", detected_at=old_time),
            _make_event_row("AAPL", detected_at=time.time()),
        ])
        count = await db.purge_old_unusual_events(keep_days=30)
        assert count == 1
        remaining = await db.get_unusual_events(hours=24 * 365)
        assert len(remaining) == 1
        assert remaining[0]["ticker"] == "AAPL"
