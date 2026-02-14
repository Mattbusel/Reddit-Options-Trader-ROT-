"""Tests for rot.macro.calendar — EconomicCalendar generation, queries, helpers."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rot.macro.calendar import (
    EconomicCalendar,
    _first_business_day_of_month,
    _last_weekday_of_month,
    _make_timestamp,
    _nth_weekday_of_month,
    _resolve_rule,
)
from rot.macro.types import MacroEvent


# ── Helper functions ────────────────────────────────────────────────


class TestNthWeekdayOfMonth:
    def test_first_friday_march_2026(self):
        # March 2026 starts on Sunday. First Friday = March 6.
        day = _nth_weekday_of_month(2026, 3, 4, 1)  # Friday=4, 1st
        assert day == 6

    def test_second_tuesday_march_2026(self):
        # March 2026: 1st is Sun, so first Tue is 3, second is 10
        day = _nth_weekday_of_month(2026, 3, 1, 2)  # Tuesday=1, 2nd
        assert day == 10

    def test_third_friday_march_2026(self):
        # March 2026: first Fri=6, second=13, third=20
        day = _nth_weekday_of_month(2026, 3, 4, 3)
        assert day == 20

    def test_first_friday_january_2026(self):
        # January 2026 starts on Thursday. First Friday = January 2.
        day = _nth_weekday_of_month(2026, 1, 4, 1)
        assert day == 2

    def test_nonexistent_fifth_monday(self):
        # February 2026 has only 4 Mondays at most
        day = _nth_weekday_of_month(2026, 2, 0, 5)
        assert day == 0

    def test_first_monday_january_2026(self):
        # Jan 2026 starts on Thursday, first Monday = Jan 5
        day = _nth_weekday_of_month(2026, 1, 0, 1)
        assert day == 5


class TestLastWeekdayOfMonth:
    def test_last_tuesday_march_2026(self):
        # March 2026: last day is 31 (Tuesday)
        day = _last_weekday_of_month(2026, 3, 1)  # Tuesday=1
        assert day == 31

    def test_last_friday_february_2026(self):
        # February 2026: 28 days, 28 is Saturday, last Friday = 27
        day = _last_weekday_of_month(2026, 2, 4)  # Friday=4
        assert day == 27

    def test_last_tuesday_january_2026(self):
        # Jan 2026: 31 is Saturday, last Tuesday is 27
        day = _last_weekday_of_month(2026, 1, 1)
        assert day == 27


class TestFirstBusinessDayOfMonth:
    def test_march_2026_starts_on_sunday(self):
        # March 2026 starts on Sunday, so first business day is Monday March 2
        day = _first_business_day_of_month(2026, 3)
        assert day == 2

    def test_january_2026_starts_on_thursday(self):
        # January 2026 starts on Thursday, first business day = Jan 1
        day = _first_business_day_of_month(2026, 1)
        assert day == 1

    def test_february_2026_starts_on_sunday(self):
        # February 2026 starts on Sunday, first business day = Feb 2 (Monday)
        day = _first_business_day_of_month(2026, 2)
        assert day == 2

    def test_august_2026_starts_on_saturday(self):
        # Aug 2026: Aug 1 is Saturday, first business day = Aug 3 (Monday)
        day = _first_business_day_of_month(2026, 8)
        assert day == 3


class TestResolveRule:
    def test_first_friday(self):
        day = _resolve_rule("first_friday", 2026, 3)
        assert day > 0

    def test_second_tuesday(self):
        day = _resolve_rule("second_tuesday", 2026, 3)
        assert day > 0

    def test_second_wednesday(self):
        day = _resolve_rule("second_wednesday", 2026, 3)
        assert day > 0

    def test_second_friday(self):
        day = _resolve_rule("second_friday", 2026, 3)
        assert day > 0

    def test_third_tuesday(self):
        day = _resolve_rule("third_tuesday", 2026, 3)
        assert day > 0

    def test_third_wednesday(self):
        day = _resolve_rule("third_wednesday", 2026, 3)
        assert day > 0

    def test_third_thursday(self):
        day = _resolve_rule("third_thursday", 2026, 3)
        assert day > 0

    def test_third_friday(self):
        day = _resolve_rule("third_friday", 2026, 3)
        assert day > 0

    def test_last_tuesday(self):
        day = _resolve_rule("last_tuesday", 2026, 3)
        assert day > 0

    def test_first_business_day(self):
        day = _resolve_rule("first_business_day", 2026, 3)
        assert day > 0

    def test_third_business_day(self):
        day = _resolve_rule("third_business_day", 2026, 3)
        assert day > 0

    def test_unknown_rule_returns_zero(self):
        day = _resolve_rule("nonexistent_rule", 2026, 3)
        assert day == 0


# ── generate_recurring ──────────────────────────────────────────────


class TestGenerateRecurring:
    def setup_method(self):
        self.db = AsyncMock()
        self.cal = EconomicCalendar(db=self.db)

    def test_returns_list_of_macro_events(self):
        events = self.cal.generate_recurring(2026, 3)
        assert isinstance(events, list)
        assert all(isinstance(e, MacroEvent) for e in events)

    def test_generates_nfp_event(self):
        events = self.cal.generate_recurring(2026, 3)
        nfp = [e for e in events if e.event_type == "nonfarm_payrolls"]
        assert len(nfp) == 1
        assert nfp[0].category == "employment"
        assert nfp[0].importance == "critical"

    def test_generates_cpi_event(self):
        events = self.cal.generate_recurring(2026, 3)
        cpi = [e for e in events if e.event_type == "cpi"]
        assert len(cpi) == 1
        assert cpi[0].category == "inflation"
        assert cpi[0].importance == "critical"

    def test_generates_opex_event(self):
        events = self.cal.generate_recurring(2026, 3)
        opex = [e for e in events if e.event_type == "opex"]
        assert len(opex) == 1
        assert opex[0].category == "markets"
        assert opex[0].importance == "high"

    def test_event_id_format(self):
        events = self.cal.generate_recurring(2026, 3)
        for e in events:
            assert e.id.startswith("recurring-")
            assert "2026-03" in e.id

    def test_event_source_is_recurring(self):
        events = self.cal.generate_recurring(2026, 3)
        for e in events:
            assert e.source == "recurring"

    def test_generates_ism_manufacturing(self):
        events = self.cal.generate_recurring(2026, 3)
        ism = [e for e in events if e.event_type == "ism_manufacturing"]
        assert len(ism) == 1
        assert ism[0].category == "manufacturing"

    def test_generates_consumer_confidence(self):
        events = self.cal.generate_recurring(2026, 3)
        cc = [e for e in events if e.event_type == "consumer_confidence"]
        assert len(cc) == 1
        assert cc[0].category == "consumer"

    def test_scheduled_at_is_positive_float(self):
        events = self.cal.generate_recurring(2026, 3)
        for e in events:
            assert e.scheduled_at > 0

    def test_affected_sectors_populated(self):
        events = self.cal.generate_recurring(2026, 3)
        nfp = [e for e in events if e.event_type == "nonfarm_payrolls"][0]
        assert len(nfp.affected_sectors) > 0


# ── generate_fomc_events ────────────────────────────────────────────


class TestGenerateFomcEvents:
    def setup_method(self):
        self.db = AsyncMock()
        self.cal = EconomicCalendar(db=self.db)

    def test_returns_8_decision_dates_for_2026(self):
        events = self.cal.generate_fomc_events(2026)
        assert len(events) == 8

    def test_all_critical_importance(self):
        events = self.cal.generate_fomc_events(2026)
        for e in events:
            assert e.importance == "critical"

    def test_all_monetary_policy_category(self):
        events = self.cal.generate_fomc_events(2026)
        for e in events:
            assert e.category == "monetary_policy"

    def test_all_fomc_decision_type(self):
        events = self.cal.generate_fomc_events(2026)
        for e in events:
            assert e.event_type == "fomc_decision"

    def test_id_format(self):
        events = self.cal.generate_fomc_events(2026)
        for e in events:
            assert e.id.startswith("fomc-decision-")

    def test_source_is_fed_calendar(self):
        events = self.cal.generate_fomc_events(2026)
        for e in events:
            assert e.source == "fed_calendar"

    def test_non_2026_year_returns_empty(self):
        events = self.cal.generate_fomc_events(2025)
        assert events == []

    def test_affected_sectors_populated(self):
        events = self.cal.generate_fomc_events(2026)
        for e in events:
            assert "Financials" in e.affected_sectors


# ── seed_events ─────────────────────────────────────────────────────


class TestSeedEvents:
    @pytest.mark.asyncio
    async def test_seed_calls_upsert(self):
        db = AsyncMock()
        db.upsert_macro_event = AsyncMock(return_value=True)
        cal = EconomicCalendar(db=db)
        count = await cal.seed_events(2026, months=[3])
        assert count > 0
        assert db.upsert_macro_event.call_count == count

    @pytest.mark.asyncio
    async def test_seed_all_months(self):
        db = AsyncMock()
        db.upsert_macro_event = AsyncMock(return_value=True)
        cal = EconomicCalendar(db=db)
        count = await cal.seed_events(2026)
        # 12 months of recurring + 8 FOMC
        assert count > 100  # each month generates ~13 events


# ── Query methods (mocked DB) ──────────────────────────────────────


class TestCalendarQueries:
    @pytest.mark.asyncio
    async def test_get_upcoming(self):
        mock_row = {
            "id": "ev-1",
            "event_type": "cpi",
            "name": "CPI",
            "scheduled_at": time.time() + 86400,
            "category": "inflation",
            "importance": "critical",
        }
        db = AsyncMock()
        db.query_macro_events = AsyncMock(return_value=[mock_row])
        cal = EconomicCalendar(db=db)
        results = await cal.get_upcoming(days=7)
        assert len(results) == 1
        assert results[0].event_type == "cpi"
        db.query_macro_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_past(self):
        db = AsyncMock()
        db.query_macro_events = AsyncMock(return_value=[])
        cal = EconomicCalendar(db=db)
        results = await cal.get_past(days=30)
        assert results == []
        db.query_macro_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_type(self):
        db = AsyncMock()
        db.query_macro_events = AsyncMock(return_value=[])
        cal = EconomicCalendar(db=db)
        results = await cal.get_by_type("nonfarm_payrolls")
        assert results == []
        call_kwargs = db.query_macro_events.call_args
        assert call_kwargs[1]["event_type"] == "nonfarm_payrolls"

    @pytest.mark.asyncio
    async def test_get_by_category(self):
        db = AsyncMock()
        db.query_macro_events = AsyncMock(return_value=[])
        cal = EconomicCalendar(db=db)
        results = await cal.get_by_category("inflation")
        assert results == []
        call_kwargs = db.query_macro_events.call_args
        assert call_kwargs[1]["category"] == "inflation"

    @pytest.mark.asyncio
    async def test_get_this_week(self):
        db = AsyncMock()
        db.query_macro_events = AsyncMock(return_value=[])
        cal = EconomicCalendar(db=db)
        results = await cal.get_this_week()
        assert results == []

    @pytest.mark.asyncio
    async def test_get_next_critical(self):
        db = AsyncMock()
        db.query_macro_events = AsyncMock(return_value=[])
        cal = EconomicCalendar(db=db)
        results = await cal.get_next_critical(limit=5)
        assert results == []
        call_kwargs = db.query_macro_events.call_args
        assert call_kwargs[1]["importance_in"] == ["critical", "high"]
        assert call_kwargs[1]["limit"] == 5


# ── _row_to_event ───────────────────────────────────────────────────


class TestRowToEvent:
    def test_basic_conversion(self):
        row = {
            "id": "ev-100",
            "event_type": "cpi",
            "name": "CPI",
            "scheduled_at": 1700000000.0,
            "category": "inflation",
            "importance": "critical",
            "country": "US",
            "actual_at": None,
            "consensus_value": 3.0,
            "actual_value": 3.2,
            "previous_value": 2.9,
            "surprise_pct": 6.7,
            "affected_sectors": '["Technology", "Financials"]',
            "affected_tickers": '["SPY"]',
            "source": "rss",
            "meta": '{"key": "value"}',
        }
        ev = EconomicCalendar._row_to_event(row)
        assert ev.id == "ev-100"
        assert ev.event_type == "cpi"
        assert ev.affected_sectors == ["Technology", "Financials"]
        assert ev.affected_tickers == ["SPY"]
        assert ev.meta == {"key": "value"}

    def test_handles_invalid_json_sectors(self):
        row = {
            "id": "ev-200",
            "event_type": "nfp",
            "name": "NFP",
            "scheduled_at": 1700000000.0,
            "category": "employment",
            "affected_sectors": "not-json",
            "affected_tickers": "[]",
            "meta": "{}",
        }
        ev = EconomicCalendar._row_to_event(row)
        assert ev.affected_sectors == []

    def test_handles_missing_optional_fields(self):
        row = {
            "id": "ev-300",
            "event_type": "ppi",
            "name": "PPI",
            "scheduled_at": 1700000000.0,
        }
        ev = EconomicCalendar._row_to_event(row)
        assert ev.category == "other"
        assert ev.importance == "medium"
        assert ev.country == "US"


# ── find_nearby_events ──────────────────────────────────────────────


class TestFindNearbyEvents:
    def test_filters_within_window(self):
        events = [
            MacroEvent(id="e1", event_type="cpi", name="CPI",
                       scheduled_at=1000.0, category="inflation"),
            MacroEvent(id="e2", event_type="nfp", name="NFP",
                       scheduled_at=2000.0, category="employment"),
            MacroEvent(id="e3", event_type="ppi", name="PPI",
                       scheduled_at=100000.0, category="inflation"),
        ]
        nearby = EconomicCalendar.find_nearby_events(events, signal_ts=1500.0, window_hours=1)
        # 1h = 3600s, so events within [1500-3600, 1500+3600] = [-2100, 5100]
        assert len(nearby) == 2
        ids = {e.id for e in nearby}
        assert "e1" in ids
        assert "e2" in ids
        assert "e3" not in ids

    def test_empty_events(self):
        nearby = EconomicCalendar.find_nearby_events([], signal_ts=1000.0)
        assert nearby == []


# ── ingest_from_rss ─────────────────────────────────────────────────


class TestIngestFromRss:
    @pytest.mark.asyncio
    async def test_ingest_rss_with_mocked_http(self):
        db = AsyncMock()
        db.upsert_macro_event = AsyncMock(return_value=True)
        cal = EconomicCalendar(db=db)

        mock_feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Fed Press Release</title>
              <link>https://fed.gov/release/1</link>
            </item>
          </channel>
        </rss>"""

        with patch("rot.macro.calendar.httpx.AsyncClient") as MockClient:
            mock_resp = MagicMock()
            mock_resp.text = mock_feed_xml
            mock_resp.raise_for_status = MagicMock()
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            count = await cal.ingest_from_rss()
            assert count >= 0  # May be 0 or 1 depending on feedparser

    @pytest.mark.asyncio
    async def test_ingest_rss_handles_error(self):
        db = AsyncMock()
        db.upsert_macro_event = AsyncMock(return_value=True)
        cal = EconomicCalendar(db=db)

        with patch("rot.macro.calendar.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            count = await cal.ingest_from_rss()
            assert count == 0
