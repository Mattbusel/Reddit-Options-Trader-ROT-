"""
Tests for rot.storage.radar_db.RadarMixin and rot.storage.probability_db.ProbabilityMixin.

Coverage:
- RadarMixin: schema creation
- RadarMixin: save_radar_event persists event
- RadarMixin: get_unresolved_radar_events returns pending events
- RadarMixin: get_unresolved_radar_events filtered by age
- RadarMixin: resolve_radar_event marks event resolved
- RadarMixin: get_radar_lead_time_distribution returns stats
- RadarMixin: get_directional_signals_after queries signals table
- ProbabilityMixin: schema creation
- ProbabilityMixin: save_pre_signal persists record
- ProbabilityMixin: resolve_pre_signal updates record
- ProbabilityMixin: get_presignal_accuracy_stats
- ProbabilityMixin: get_presignals_by_source
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def radar_db():
    from rot.storage.radar_db import RadarMixin
    import aiosqlite

    class Mixed(RadarMixin):
        pass

    conn = await aiosqlite.connect(":memory:")

    class FakeDb:
        def __init__(self, c):
            self._conn = c

        def execute(self, sql, params=()):
            # Return the aiosqlite async context manager directly (not awaited)
            # so callers can use both `await self.db.execute(...)` and
            # `async with self.db.execute(...) as cursor:`
            return self._conn.execute(sql, params)

        async def commit(self):
            await self._conn.commit()

    m = Mixed()
    m.db = FakeDb(conn)
    # Also need signals table for get_directional_signals_after
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY, created_at REAL, ticker TEXT,
            event_type TEXT, stance TEXT, confidence REAL
        )
    """)
    await conn.commit()
    await m.ensure_radar_schema()
    yield m
    await conn.close()


@pytest_asyncio.fixture
async def prob_db():
    from rot.storage.probability_db import ProbabilityMixin
    import aiosqlite

    class Mixed(ProbabilityMixin):
        pass

    conn = await aiosqlite.connect(":memory:")

    class FakeDb:
        def __init__(self, c):
            self._conn = c

        def execute(self, sql, params=()):
            return self._conn.execute(sql, params)

        async def commit(self):
            await self._conn.commit()

    m = Mixed()
    m.db = FakeDb(conn)
    await m.ensure_probability_schema()
    yield m
    await conn.close()


# ── RadarMixin tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestRadarMixin:
    async def test_schema_created(self, radar_db):
        async with radar_db.db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cur:
            tables = [r[0] for r in await cur.fetchall()]
        assert "attention_radar_events" in tables

    async def test_save_and_get_unresolved(self, radar_db):
        row_id = await radar_db.save_radar_event(
            ticker="TSLA", timestamp=time.time() - 86400,
            confidence=0.92, signal_volume_zscore=3.5,
        )
        assert row_id > 0
        events = await radar_db.get_unresolved_radar_events()
        assert len(events) == 1
        assert events[0]["ticker"] == "TSLA"

    async def test_get_unresolved_filtered_by_age(self, radar_db):
        now = time.time()
        await radar_db.save_radar_event("TSLA", now - 10 * 86400, 0.91, 3.0)
        await radar_db.save_radar_event("AAPL", now - 1 * 86400, 0.89, 2.5)
        # Only events older than 5 days
        events = await radar_db.get_unresolved_radar_events(older_than_ts=now - 5 * 86400)
        assert len(events) == 1
        assert events[0]["ticker"] == "TSLA"

    async def test_resolve_radar_event(self, radar_db):
        row_id = await radar_db.save_radar_event("TSLA", time.time() - 86400, 0.90, 3.0)
        await radar_db.resolve_radar_event(row_id, "earnings_surprise", lead_time_days=5.0)
        events = await radar_db.get_unresolved_radar_events()
        assert len(events) == 0

    async def test_lead_time_distribution_empty(self, radar_db):
        result = await radar_db.get_radar_lead_time_distribution()
        assert result.get("total_resolved", 0) == 0

    async def test_lead_time_distribution_with_data(self, radar_db):
        row_id = await radar_db.save_radar_event("TSLA", time.time() - 86400, 0.90, 3.0)
        await radar_db.resolve_radar_event(row_id, "buyout", lead_time_days=7.0)
        result = await radar_db.get_radar_lead_time_distribution()
        assert result["total_resolved"] == 1
        assert abs(result["avg_lead_days"] - 7.0) < 0.01

    async def test_get_directional_signals_after(self, radar_db):
        now = time.time()
        await radar_db.db._conn.execute(
            "INSERT INTO signals (id, created_at, ticker, event_type, stance, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("s1", now - 86400, "TSLA", "earnings_rumor", "bullish", 0.85),
        )
        await radar_db.db._conn.commit()
        signals = await radar_db.get_directional_signals_after("TSLA", now - 2 * 86400)
        assert len(signals) == 1
        assert signals[0]["stance"] == "bullish"

    async def test_get_directional_excludes_mixed(self, radar_db):
        now = time.time()
        # Insert mixed stance signal — should be excluded
        await radar_db.db._conn.execute(
            "INSERT INTO signals (id, created_at, ticker, event_type, stance, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("s2", now, "TSLA", "other", "mixed", 0.85),
        )
        await radar_db.db._conn.commit()
        signals = await radar_db.get_directional_signals_after("TSLA", now - 3600)
        assert len(signals) == 0

    async def test_save_multiple_events(self, radar_db):
        for i in range(5):
            await radar_db.save_radar_event(f"TICK{i}", time.time(), 0.90, 3.0)
        events = await radar_db.get_unresolved_radar_events()
        assert len(events) == 5


# ── ProbabilityMixin tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestProbabilityMixin:
    async def test_schema_created(self, prob_db):
        async with prob_db.db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cur:
            tables = [r[0] for r in await cur.fetchall()]
        assert "pre_signal_events" in tables

    async def test_save_pre_signal(self, prob_db):
        row_id = await prob_db.save_pre_signal(
            ticker="TSLA",
            timestamp=time.time(),
            source="reddit",
            doc_id="t3_abc",
            pre_signal_confidence=0.75,
            pre_signal_direction="bullish",
            iir_value=0.4,
            variance=0.02,
            chunks_at_fire=7,
        )
        assert row_id > 0

    async def test_resolve_pre_signal(self, prob_db):
        row_id = await prob_db.save_pre_signal(
            "TSLA", time.time(), "reddit", "d1", 0.75, "bullish",
        )
        await prob_db.resolve_pre_signal(
            event_id=row_id,
            final_confidence=0.80,
            final_direction="bullish",
            agreement=True,
            lead_time_ms=2500.0,
        )
        stats = await prob_db.get_presignal_accuracy_stats()
        assert stats["total"] == 1
        assert stats["agreements"] == 1
        assert stats["agreement_rate"] == 1.0

    async def test_accuracy_stats_empty(self, prob_db):
        stats = await prob_db.get_presignal_accuracy_stats()
        assert stats.get("total", 0) == 0

    async def test_accuracy_stats_with_disagreement(self, prob_db):
        rid1 = await prob_db.save_pre_signal("TSLA", time.time(), "reddit", "d1", 0.75, "bullish")
        rid2 = await prob_db.save_pre_signal("TSLA", time.time(), "reddit", "d2", 0.80, "bearish")
        await prob_db.resolve_pre_signal(rid1, 0.80, "bullish", True, 1000.0)
        await prob_db.resolve_pre_signal(rid2, 0.70, "bullish", False, 2000.0)  # disagreement
        stats = await prob_db.get_presignal_accuracy_stats()
        assert stats["total"] == 2
        assert stats["agreements"] == 1
        assert abs(stats["agreement_rate"] - 0.5) < 0.01

    async def test_presignals_by_source(self, prob_db):
        rid1 = await prob_db.save_pre_signal("TSLA", time.time(), "reddit", "d1", 0.75, "bullish")
        rid2 = await prob_db.save_pre_signal("NVDA", time.time(), "sec_filing", "d2", 0.80, "bearish")
        await prob_db.resolve_pre_signal(rid1, 0.80, "bullish", True, 500.0)
        await prob_db.resolve_pre_signal(rid2, 0.85, "bullish", False, 1000.0)
        rows = await prob_db.get_presignals_by_source()
        sources = [r["source"] for r in rows]
        assert "reddit" in sources
        assert "sec_filing" in sources

    async def test_confidence_delta_in_stats(self, prob_db):
        row_id = await prob_db.save_pre_signal("TSLA", time.time(), "reddit", "d1", 0.70, "bullish")
        await prob_db.resolve_pre_signal(row_id, 0.80, "bullish", True, 1000.0)
        stats = await prob_db.get_presignal_accuracy_stats()
        assert "confidence_delta" in stats
        assert abs(stats["confidence_delta"] - 0.10) < 0.01
