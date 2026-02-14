"""Tests for macro-related Database methods — real temp SQLite, no mocks."""

from __future__ import annotations

import time

import pytest

from rot.storage.database import Database
from rot.macro.types import (
    MacroEvent,
    EarningsEvent,
    InsiderTrade,
    FOMCMeeting,
)


# ── DB fixture ──────────────────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test_macro.db"))
    await database.connect()
    yield database
    await database.close()


# ── MacroEvent CRUD ─────────────────────────────────────────────────


class TestUpsertMacroEvent:
    @pytest.mark.asyncio
    async def test_insert_macro_event(self, db):
        event = MacroEvent(
            id="macro-cpi-2026-03",
            event_type="cpi",
            name="Consumer Price Index",
            scheduled_at=1772000000.0,
            category="inflation",
            importance="critical",
            source="recurring",
        )
        result = await db.upsert_macro_event(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_query_back_inserted_event(self, db):
        event = MacroEvent(
            id="macro-nfp-2026-03",
            event_type="nonfarm_payrolls",
            name="Nonfarm Payrolls",
            scheduled_at=1772000000.0,
            category="employment",
            importance="critical",
        )
        await db.upsert_macro_event(event)
        row = await db.get_macro_event("macro-nfp-2026-03")
        assert row is not None
        assert row["event_type"] == "nonfarm_payrolls"
        assert row["category"] == "employment"
        assert row["importance"] == "critical"

    @pytest.mark.asyncio
    async def test_upsert_updates_on_conflict(self, db):
        event1 = MacroEvent(
            id="macro-upsert-test",
            event_type="cpi",
            name="CPI",
            scheduled_at=1772000000.0,
            category="inflation",
            actual_value=None,
        )
        await db.upsert_macro_event(event1)

        # Update with actual value
        event2 = MacroEvent(
            id="macro-upsert-test",
            event_type="cpi",
            name="CPI",
            scheduled_at=1772000000.0,
            category="inflation",
            actual_value=3.2,
            surprise_pct=0.1,
        )
        await db.upsert_macro_event(event2)

        row = await db.get_macro_event("macro-upsert-test")
        assert row is not None
        assert row["actual_value"] == 3.2
        assert row["surprise_pct"] == 0.1


class TestQueryMacroEvents:
    @pytest.mark.asyncio
    async def test_start_end_filter(self, db):
        now = time.time()
        for i in range(5):
            ev = MacroEvent(
                id=f"macro-range-{i}",
                event_type="cpi",
                name=f"CPI {i}",
                scheduled_at=now + i * 86400,
                category="inflation",
            )
            await db.upsert_macro_event(ev)

        # Query first 3 days
        rows = await db.query_macro_events(
            start_ts=now - 1, end_ts=now + 2.5 * 86400
        )
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_category_filter(self, db):
        now = time.time()
        await db.upsert_macro_event(MacroEvent(
            id="cat-emp-1", event_type="nfp", name="NFP",
            scheduled_at=now, category="employment",
        ))
        await db.upsert_macro_event(MacroEvent(
            id="cat-inf-1", event_type="cpi", name="CPI",
            scheduled_at=now, category="inflation",
        ))
        rows = await db.query_macro_events(category="employment")
        assert len(rows) == 1
        assert rows[0]["event_type"] == "nfp"

    @pytest.mark.asyncio
    async def test_importance_in_filter(self, db):
        now = time.time()
        await db.upsert_macro_event(MacroEvent(
            id="imp-crit", event_type="cpi", name="CPI",
            scheduled_at=now, category="inflation", importance="critical",
        ))
        await db.upsert_macro_event(MacroEvent(
            id="imp-low", event_type="case_shiller", name="Case-Shiller",
            scheduled_at=now, category="housing", importance="low",
        ))
        await db.upsert_macro_event(MacroEvent(
            id="imp-high", event_type="opex", name="OPEX",
            scheduled_at=now, category="markets", importance="high",
        ))

        rows = await db.query_macro_events(importance_in=["critical", "high"])
        assert len(rows) == 2
        types = {r["event_type"] for r in rows}
        assert "cpi" in types
        assert "opex" in types

    @pytest.mark.asyncio
    async def test_event_type_filter(self, db):
        now = time.time()
        await db.upsert_macro_event(MacroEvent(
            id="type-cpi", event_type="cpi", name="CPI",
            scheduled_at=now, category="inflation",
        ))
        await db.upsert_macro_event(MacroEvent(
            id="type-nfp", event_type="nonfarm_payrolls", name="NFP",
            scheduled_at=now, category="employment",
        ))
        rows = await db.query_macro_events(event_type="cpi")
        assert len(rows) == 1
        assert rows[0]["id"] == "type-cpi"

    @pytest.mark.asyncio
    async def test_order_asc(self, db):
        now = time.time()
        for i in [3, 1, 2]:
            await db.upsert_macro_event(MacroEvent(
                id=f"ord-{i}", event_type="cpi", name=f"CPI {i}",
                scheduled_at=now + i * 86400, category="inflation",
            ))
        rows = await db.query_macro_events(order="asc")
        timestamps = [r["scheduled_at"] for r in rows]
        assert timestamps == sorted(timestamps)

    @pytest.mark.asyncio
    async def test_order_desc(self, db):
        now = time.time()
        for i in [3, 1, 2]:
            await db.upsert_macro_event(MacroEvent(
                id=f"ord-desc-{i}", event_type="ppi", name=f"PPI {i}",
                scheduled_at=now + i * 86400, category="inflation",
            ))
        rows = await db.query_macro_events(event_type="ppi", order="desc")
        timestamps = [r["scheduled_at"] for r in rows]
        assert timestamps == sorted(timestamps, reverse=True)

    @pytest.mark.asyncio
    async def test_limit(self, db):
        now = time.time()
        for i in range(10):
            await db.upsert_macro_event(MacroEvent(
                id=f"lim-{i}", event_type="cpi", name=f"CPI {i}",
                scheduled_at=now + i * 86400, category="inflation",
            ))
        rows = await db.query_macro_events(limit=3)
        assert len(rows) == 3


# ── EarningsEvent CRUD ──────────────────────────────────────────────


class TestUpsertEarningsEvent:
    @pytest.mark.asyncio
    async def test_insert_earnings_event(self, db):
        ev = EarningsEvent(
            id="earn-tsla-20260120",
            ticker="TSLA",
            report_date=1772000000.0,
            fiscal_quarter="2026-Q1",
            eps_estimate=2.0,
        )
        result = await db.upsert_earnings_event(ev)
        assert result is True

        row = await db.get_earnings_event("earn-tsla-20260120")
        assert row is not None
        assert row["ticker"] == "TSLA"
        assert row["eps_estimate"] == 2.0


class TestQueryEarningsEvents:
    @pytest.mark.asyncio
    async def test_ticker_filter(self, db):
        now = time.time()
        await db.upsert_earnings_event(EarningsEvent(
            id="earn-tsla", ticker="TSLA", report_date=now,
        ))
        await db.upsert_earnings_event(EarningsEvent(
            id="earn-aapl", ticker="AAPL", report_date=now,
        ))
        rows = await db.query_earnings_events(ticker="TSLA")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "TSLA"

    @pytest.mark.asyncio
    async def test_date_range_filter(self, db):
        now = time.time()
        for i in range(5):
            await db.upsert_earnings_event(EarningsEvent(
                id=f"earn-range-{i}", ticker="MSFT",
                report_date=now + i * 86400 * 30,
            ))
        rows = await db.query_earnings_events(
            start_ts=now - 1, end_ts=now + 61 * 86400,
        )
        assert len(rows) == 3  # days 0, 30, 60


# ── InsiderTrade CRUD ───────────────────────────────────────────────


class TestUpsertInsiderTrade:
    @pytest.mark.asyncio
    async def test_insert_insider_trade(self, db):
        trade = InsiderTrade(
            id="ins-cook-001",
            ticker="AAPL",
            insider_name="Tim Cook",
            trade_type="sell",
            filing_date=1772000000.0,
            source="form4",
            title="CEO",
            shares=50000,
            price=185.0,
            value=9250000.0,
        )
        result = await db.upsert_insider_trade(trade)
        assert result is True


class TestQueryInsiderTrades:
    @pytest.mark.asyncio
    async def test_ticker_filter(self, db):
        now = time.time()
        await db.upsert_insider_trade(InsiderTrade(
            id="ins-t1", ticker="AAPL", insider_name="Cook",
            trade_type="sell", filing_date=now, source="form4",
        ))
        await db.upsert_insider_trade(InsiderTrade(
            id="ins-t2", ticker="MSFT", insider_name="Nadella",
            trade_type="buy", filing_date=now, source="form4",
        ))
        rows = await db.query_insider_trades(ticker="AAPL")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_trade_type_filter(self, db):
        now = time.time()
        await db.upsert_insider_trade(InsiderTrade(
            id="ins-buy", ticker="TSLA", insider_name="Musk",
            trade_type="buy", filing_date=now, source="form4",
        ))
        await db.upsert_insider_trade(InsiderTrade(
            id="ins-sell", ticker="TSLA", insider_name="CFO",
            trade_type="sell", filing_date=now, source="form4",
        ))
        rows = await db.query_insider_trades(trade_type="buy")
        assert len(rows) == 1
        assert rows[0]["trade_type"] == "buy"

    @pytest.mark.asyncio
    async def test_min_value_filter(self, db):
        now = time.time()
        await db.upsert_insider_trade(InsiderTrade(
            id="ins-small", ticker="AAPL", insider_name="Jr Manager",
            trade_type="buy", filing_date=now, source="form4",
            value=5000.0,
        ))
        await db.upsert_insider_trade(InsiderTrade(
            id="ins-big", ticker="AAPL", insider_name="CEO",
            trade_type="buy", filing_date=now, source="form4",
            value=500000.0,
        ))
        rows = await db.query_insider_trades(min_value=100000)
        assert len(rows) == 1
        assert rows[0]["value"] == 500000.0


# ── FOMC Meeting CRUD ──────────────────────────────────────────────


class TestUpsertFomcMeeting:
    @pytest.mark.asyncio
    async def test_insert_fomc_meeting(self, db):
        meeting = FOMCMeeting(
            id="fomc-2026-01-29",
            meeting_date=1772000000.0,
            rate_decision="hold",
            rate_before=5.25,
            rate_after=5.25,
            statement_text="The Committee decided to maintain...",
            hawkish_score=0.4,
            dovish_score=0.5,
        )
        result = await db.upsert_fomc_meeting(meeting)
        assert result is True


class TestQueryFomcMeetings:
    @pytest.mark.asyncio
    async def test_query_returns_ordered_results(self, db):
        now = time.time()
        for i in range(3):
            await db.upsert_fomc_meeting(FOMCMeeting(
                id=f"fomc-q-{i}",
                meeting_date=now + i * 86400 * 45,
            ))
        rows = await db.query_fomc_meetings(order="desc")
        dates = [r["meeting_date"] for r in rows]
        assert dates == sorted(dates, reverse=True)

    @pytest.mark.asyncio
    async def test_query_asc_order(self, db):
        now = time.time()
        for i in range(3):
            await db.upsert_fomc_meeting(FOMCMeeting(
                id=f"fomc-asc-{i}",
                meeting_date=now + i * 86400 * 45,
            ))
        rows = await db.query_fomc_meetings(order="asc")
        dates = [r["meeting_date"] for r in rows]
        assert dates == sorted(dates)


class TestGetNextFomcMeeting:
    @pytest.mark.asyncio
    async def test_returns_future_meeting(self, db):
        now = time.time()
        await db.upsert_fomc_meeting(FOMCMeeting(
            id="fomc-past", meeting_date=now - 86400 * 30,
        ))
        await db.upsert_fomc_meeting(FOMCMeeting(
            id="fomc-future", meeting_date=now + 86400 * 30,
        ))
        row = await db.get_next_fomc_meeting(now)
        assert row is not None
        assert row["id"] == "fomc-future"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_future(self, db):
        now = time.time()
        await db.upsert_fomc_meeting(FOMCMeeting(
            id="fomc-old", meeting_date=now - 86400 * 60,
        ))
        row = await db.get_next_fomc_meeting(now)
        assert row is None


class TestGetFomcMeeting:
    @pytest.mark.asyncio
    async def test_get_by_id(self, db):
        await db.upsert_fomc_meeting(FOMCMeeting(
            id="fomc-lookup",
            meeting_date=1772000000.0,
            rate_decision="raise_25",
            rate_before=5.25,
            rate_after=5.50,
        ))
        row = await db.get_fomc_meeting("fomc-lookup")
        assert row is not None
        assert row["rate_decision"] == "raise_25"
        assert row["rate_after"] == 5.50

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, db):
        row = await db.get_fomc_meeting("nonexistent-id")
        assert row is None


# ── Event Impact Cache ──────────────────────────────────────────────


class TestEventImpactCache:
    @pytest.mark.asyncio
    async def test_save_and_get_round_trip(self, db):
        await db.save_event_impact_cache(
            event_type="cpi",
            avg_spy_move=0.35,
            avg_vix_change=-1.2,
            sample_size=50,
            reactions_json=[{"date": 1700000000, "spy_move_pct": 0.5}],
            sector_sensitivity=["Financials", "Energy"],
        )
        cached = await db.get_event_impact_cache("cpi")
        assert cached is not None
        assert cached["event_type"] == "cpi"
        assert cached["avg_spy_move"] == 0.35
        assert cached["avg_vix_change"] == -1.2
        assert cached["sample_size"] == 50

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, db):
        cached = await db.get_event_impact_cache("nonexistent")
        assert cached is None

    @pytest.mark.asyncio
    async def test_upsert_updates_on_conflict(self, db):
        await db.save_event_impact_cache(
            event_type="nfp",
            avg_spy_move=0.1,
            avg_vix_change=0.5,
            sample_size=10,
            reactions_json=[],
            sector_sensitivity=[],
        )
        await db.save_event_impact_cache(
            event_type="nfp",
            avg_spy_move=0.2,
            avg_vix_change=0.8,
            sample_size=20,
            reactions_json=[],
            sector_sensitivity=[],
        )
        cached = await db.get_event_impact_cache("nfp")
        assert cached["avg_spy_move"] == 0.2
        assert cached["sample_size"] == 20


# ── Purge methods ───────────────────────────────────────────────────


class TestPurgeMacroEvents:
    @pytest.mark.asyncio
    async def test_purge_deletes_old_keeps_recent(self, db):
        now = time.time()
        # Old event (400 days ago)
        await db.upsert_macro_event(MacroEvent(
            id="old-event", event_type="cpi", name="Old CPI",
            scheduled_at=now - 400 * 86400, category="inflation",
        ))
        # Recent event (10 days ago)
        await db.upsert_macro_event(MacroEvent(
            id="recent-event", event_type="cpi", name="Recent CPI",
            scheduled_at=now - 10 * 86400, category="inflation",
        ))
        deleted = await db.purge_old_macro_events(keep_days=365)
        assert deleted == 1

        # Verify recent is still there
        row = await db.get_macro_event("recent-event")
        assert row is not None
        # Old one should be gone
        row = await db.get_macro_event("old-event")
        assert row is None


class TestPurgeEarningsEvents:
    @pytest.mark.asyncio
    async def test_purge_deletes_old_keeps_recent(self, db):
        now = time.time()
        await db.upsert_earnings_event(EarningsEvent(
            id="old-earn", ticker="TSLA",
            report_date=now - 400 * 86400,
        ))
        await db.upsert_earnings_event(EarningsEvent(
            id="recent-earn", ticker="TSLA",
            report_date=now - 10 * 86400,
        ))
        deleted = await db.purge_old_earnings_events(keep_days=365)
        assert deleted == 1

        row = await db.get_earnings_event("recent-earn")
        assert row is not None
        row = await db.get_earnings_event("old-earn")
        assert row is None


class TestPurgeInsiderTrades:
    @pytest.mark.asyncio
    async def test_purge_deletes_old_keeps_recent(self, db):
        now = time.time()
        await db.upsert_insider_trade(InsiderTrade(
            id="old-ins", ticker="AAPL", insider_name="Old Guy",
            trade_type="buy", filing_date=now - 400 * 86400, source="form4",
        ))
        await db.upsert_insider_trade(InsiderTrade(
            id="recent-ins", ticker="AAPL", insider_name="New Guy",
            trade_type="buy", filing_date=now - 10 * 86400, source="form4",
        ))
        deleted = await db.purge_old_insider_trades(keep_days=365)
        assert deleted == 1

        rows = await db.query_insider_trades(ticker="AAPL")
        assert len(rows) == 1
        assert rows[0]["id"] == "recent-ins"


# ── get_signals_for_ticker ──────────────────────────────────────────


class TestGetSignalsForTicker:
    @pytest.mark.asyncio
    async def test_returns_recent_signals(self, db):
        # Insert a signal first
        await db.insert_signal({
            "run_id": "run-1",
            "event": {
                "entities": ["AAPL"],
                "stance": "bullish",
                "confidence": 0.7,
                "evidence": [{"subreddit": "stocks", "excerpt": "AAPL buy"}],
                "meta": {},
            },
            "reasoning": {"thesis": "Test"},
            "trade_idea": {"underlying": "AAPL", "strategy": "debit_spread", "legs": []},
        })
        rows = await db.get_signals_for_ticker("AAPL", limit=10, days=7)
        assert len(rows) >= 1
        assert rows[0]["stance"] == "bullish"

    @pytest.mark.asyncio
    async def test_no_signals_returns_empty(self, db):
        rows = await db.get_signals_for_ticker("ZZZZ", limit=10, days=7)
        assert rows == []
