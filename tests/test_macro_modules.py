"""Tests for rot.macro — EconomicCalendar, EventImpactAnalyzer, and macro types.

Covers EconomicCalendar: generate_recurring, generate_fomc_events,
get_upcoming, get_past, get_by_type, get_by_category, get_this_week,
get_next_critical, seed_events, find_nearby_events, _row_to_event.
Covers EventImpactAnalyzer: analyze_impact, predict_impact,
get_sector_sensitivity, get_surprise_correlation, _pearson, _cache_to_impact.
Covers macro types: MacroEvent, HistoricalReaction, EventImpact,
EarningsEvent, InsiderTrade, FOMCMeeting, SeasonalPattern, constants.
"""
from __future__ import annotations

import json
import statistics
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from rot.macro.calendar import (
    EconomicCalendar,
    _FOMC_DECISION_DATES_2026,
    _RECURRING_RULES,
    _first_business_day_of_month,
    _last_weekday_of_month,
    _make_timestamp,
    _nth_weekday_of_month,
    _resolve_rule,
)
from rot.macro.impact import EventImpactAnalyzer
from rot.macro.types import (
    ALL_EVENT_TYPES,
    CATEGORY_SECTOR_SENSITIVITY,
    EVENT_TYPE_CATEGORY,
    EVENT_TYPE_IMPORTANCE,
    EarningsEvent,
    EventImpact,
    FOMCMeeting,
    HistoricalReaction,
    InsiderTrade,
    MacroEvent,
    SeasonalPattern,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.query_macro_events = AsyncMock(return_value=[])
    db.upsert_macro_event = AsyncMock(return_value=True)
    db.get_event_impact_cache = AsyncMock(return_value=None)
    db.save_event_impact_cache = AsyncMock()
    return db


@pytest.fixture
def calendar(mock_db):
    return EconomicCalendar(mock_db)


@pytest.fixture
def analyzer(mock_db):
    return EventImpactAnalyzer(mock_db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_row(**overrides) -> Dict[str, Any]:
    defaults = dict(
        id="ev-1",
        event_type="cpi",
        name="Consumer Price Index",
        scheduled_at=1700000000.0,
        category="inflation",
        importance="critical",
        country="US",
        source="recurring",
        affected_sectors=json.dumps(["Consumer Staples", "Energy"]),
        affected_tickers="[]",
        meta="{}",
    )
    defaults.update(overrides)
    return defaults


def _make_reaction(spy_move: float = 0.5, vix: float = 1.0,
                   surprise: float = 0.1, sector_moves: Dict[str, float] = None) -> Dict[str, Any]:
    return {
        "scheduled_at": 1700000000.0,
        "surprise_pct": surprise,
        "meta": json.dumps({
            "spy_move_pct": spy_move,
            "vix_change": vix,
            "sector_moves": sector_moves or {},
        }),
    }


# =========================================================================
# Part 1: Macro Types
# =========================================================================


class TestMacroEvent:
    def test_creation(self):
        e = MacroEvent(id="e1", event_type="cpi", name="CPI",
                       scheduled_at=1.0, category="inflation")
        assert e.id == "e1"
        assert e.importance == "medium"
        assert e.country == "US"

    def test_frozen(self):
        e = MacroEvent(id="e1", event_type="cpi", name="CPI",
                       scheduled_at=1.0, category="inflation")
        with pytest.raises(AttributeError):
            e.importance = "high"

    def test_default_lists(self):
        e = MacroEvent(id="e1", event_type="cpi", name="CPI",
                       scheduled_at=1.0, category="inflation")
        assert e.affected_sectors == []
        assert e.affected_tickers == []
        assert e.meta == {}


class TestHistoricalReaction:
    def test_creation(self):
        r = HistoricalReaction(date=1.0, spy_move_pct=0.5, vix_change=1.2)
        assert r.spy_move_pct == 0.5
        assert r.surprise_pct == 0.0
        assert r.sector_moves == {}


class TestEventImpact:
    def test_creation(self):
        ei = EventImpact(event_type="cpi", avg_spy_move_pct=0.3, avg_vix_change=0.8)
        assert ei.sample_size == 0
        assert ei.historical_reactions == []
        assert ei.most_affected_sectors == []


class TestEarningsEvent:
    def test_creation(self):
        e = EarningsEvent(id="e1", ticker="AAPL", report_date=1.0)
        assert e.fiscal_quarter == ""
        assert e.eps_estimate is None
        assert e.meta == {}


class TestInsiderTrade:
    def test_creation(self):
        t = InsiderTrade(id="t1", ticker="AAPL", insider_name="Tim Cook",
                         trade_type="sell", filing_date=1.0, source="form4")
        assert t.shares == 0
        assert t.price == 0.0


class TestFOMCMeeting:
    def test_creation(self):
        m = FOMCMeeting(id="m1", meeting_date=1.0)
        assert m.rate_decision == ""
        assert m.hawkish_score == 0.0


class TestSeasonalPattern:
    def test_creation(self):
        p = SeasonalPattern(ticker_or_sector="AAPL", month=1,
                            avg_return_pct=2.5, win_rate_pct=60.0, sample_years=20)
        assert p.best_year_return == 0.0
        assert p.median_return_pct == 0.0


# ---------------------------------------------------------------------------
# Type constants
# ---------------------------------------------------------------------------


class TestTypeConstants:
    def test_all_event_types_populated(self):
        assert len(ALL_EVENT_TYPES) >= 30

    def test_event_type_category_covers_all(self):
        for et in ALL_EVENT_TYPES:
            assert et in EVENT_TYPE_CATEGORY, f"{et} missing from EVENT_TYPE_CATEGORY"

    def test_event_type_importance_covers_all(self):
        for et in ALL_EVENT_TYPES:
            assert et in EVENT_TYPE_IMPORTANCE, f"{et} missing from EVENT_TYPE_IMPORTANCE"

    @pytest.mark.parametrize("category", [
        "monetary_policy", "employment", "inflation", "gdp",
        "housing", "manufacturing", "consumer", "markets", "government",
    ])
    def test_sector_sensitivity_categories(self, category):
        assert category in CATEGORY_SECTOR_SENSITIVITY
        assert len(CATEGORY_SECTOR_SENSITIVITY[category]) > 0

    @pytest.mark.parametrize("importance", ["low", "medium", "high", "critical"])
    def test_importance_levels_used(self, importance):
        used = [v for v in EVENT_TYPE_IMPORTANCE.values() if v == importance]
        assert len(used) > 0


# =========================================================================
# Part 2: Calendar date helpers
# =========================================================================


class TestNthWeekday:
    def test_first_friday_feb_2026(self):
        # Feb 2026: Feb 1 is Sunday, first Friday is Feb 6
        day = _nth_weekday_of_month(2026, 2, 4, 1)
        assert day == 6

    def test_second_tuesday_feb_2026(self):
        # Feb 2026: first Tuesday is Feb 3, second is Feb 10
        day = _nth_weekday_of_month(2026, 2, 1, 2)
        assert day == 10

    def test_third_friday_march_2026(self):
        # March 2026: first Friday is Mar 6, third is Mar 20
        day = _nth_weekday_of_month(2026, 3, 4, 3)
        assert day == 20

    def test_returns_zero_for_impossible(self):
        # 5th Monday in February (usually doesn't exist)
        day = _nth_weekday_of_month(2026, 2, 0, 5)
        assert day == 0

    @pytest.mark.parametrize("month", range(1, 13))
    def test_first_friday_exists_every_month(self, month):
        day = _nth_weekday_of_month(2026, month, 4, 1)
        assert day > 0
        assert day <= 7  # First Friday is always in first 7 days


class TestLastWeekday:
    def test_last_tuesday_feb_2026(self):
        day = _last_weekday_of_month(2026, 2, 1)
        assert day >= 22  # Last Tuesday in Feb
        assert day <= 28

    @pytest.mark.parametrize("month", range(1, 13))
    def test_last_friday_exists_every_month(self, month):
        day = _last_weekday_of_month(2026, month, 4)
        assert day >= 22


class TestFirstBusinessDay:
    def test_feb_2026_first_business_day(self):
        # Feb 1 2026 is Sunday, so first business day is Feb 2 (Monday)
        day = _first_business_day_of_month(2026, 2)
        assert day == 2

    def test_jan_2026_first_business_day(self):
        # Jan 1 2026 is Thursday
        day = _first_business_day_of_month(2026, 1)
        assert day == 1

    @pytest.mark.parametrize("month", range(1, 13))
    def test_always_within_first_3_days(self, month):
        day = _first_business_day_of_month(2026, month)
        assert 1 <= day <= 3


class TestResolveRule:
    @pytest.mark.parametrize("rule", [
        "first_friday", "every_thursday", "second_tuesday", "second_wednesday",
        "second_friday", "third_tuesday", "third_wednesday", "third_thursday",
        "third_friday", "last_tuesday", "first_business_day", "third_business_day",
    ])
    def test_all_rules_resolve(self, rule):
        day = _resolve_rule(rule, 2026, 3)
        assert day > 0

    def test_unknown_rule_returns_zero(self):
        assert _resolve_rule("nonexistent_rule", 2026, 3) == 0


class TestMakeTimestamp:
    def test_returns_float(self):
        ts = _make_timestamp(2026, 2, 15, "08:30")
        assert isinstance(ts, float)
        assert ts > 0

    def test_different_times(self):
        ts_early = _make_timestamp(2026, 2, 15, "08:30")
        ts_late = _make_timestamp(2026, 2, 15, "16:00")
        assert ts_late > ts_early


# =========================================================================
# Part 3: EconomicCalendar
# =========================================================================


class TestGenerateRecurring:
    def test_generates_events_for_month(self, calendar):
        events = calendar.generate_recurring(2026, 3)
        assert len(events) > 0
        assert len(events) == len(_RECURRING_RULES)

    def test_all_events_have_ids(self, calendar):
        events = calendar.generate_recurring(2026, 3)
        for e in events:
            assert e.id.startswith("recurring-")

    def test_all_events_have_category(self, calendar):
        events = calendar.generate_recurring(2026, 3)
        for e in events:
            assert e.category != ""

    def test_all_events_have_importance(self, calendar):
        events = calendar.generate_recurring(2026, 3)
        for e in events:
            assert e.importance in ("low", "medium", "high", "critical")

    def test_events_have_timestamps(self, calendar):
        events = calendar.generate_recurring(2026, 3)
        for e in events:
            assert e.scheduled_at > 0

    @pytest.mark.parametrize("month", range(1, 13))
    def test_generates_for_all_months(self, calendar, month):
        events = calendar.generate_recurring(2026, month)
        assert len(events) >= len(_RECURRING_RULES) - 1  # Some rules might fail

    def test_event_types_match_rules(self, calendar):
        events = calendar.generate_recurring(2026, 3)
        types = {e.event_type for e in events}
        for et in _RECURRING_RULES:
            assert et in types

    def test_source_is_recurring(self, calendar):
        events = calendar.generate_recurring(2026, 3)
        for e in events:
            assert e.source == "recurring"


class TestGenerateFomcEvents:
    def test_generates_2026_fomc_dates(self, calendar):
        events = calendar.generate_fomc_events(2026)
        assert len(events) == len(_FOMC_DECISION_DATES_2026)
        assert len(events) == 8

    def test_all_fomc_events_critical(self, calendar):
        events = calendar.generate_fomc_events(2026)
        for e in events:
            assert e.importance == "critical"
            assert e.event_type == "fomc_decision"
            assert e.category == "monetary_policy"

    def test_fomc_source_is_fed_calendar(self, calendar):
        events = calendar.generate_fomc_events(2026)
        for e in events:
            assert e.source == "fed_calendar"

    def test_non_2026_returns_empty(self, calendar):
        events = calendar.generate_fomc_events(2025)
        assert len(events) == 0

    def test_fomc_ids_contain_dates(self, calendar):
        events = calendar.generate_fomc_events(2026)
        for e in events:
            assert e.id.startswith("fomc-decision-2026-")


class TestGetUpcoming:
    @pytest.mark.asyncio
    async def test_queries_with_time_window(self, calendar, mock_db):
        mock_db.query_macro_events.return_value = []
        await calendar.get_upcoming(days=7)
        call_kwargs = mock_db.query_macro_events.call_args[1]
        assert call_kwargs["order"] == "asc"
        assert call_kwargs["end_ts"] > call_kwargs["start_ts"]

    @pytest.mark.asyncio
    async def test_returns_macro_events(self, calendar, mock_db):
        mock_db.query_macro_events.return_value = [_make_event_row()]
        events = await calendar.get_upcoming()
        assert len(events) == 1
        assert isinstance(events[0], MacroEvent)


class TestGetPast:
    @pytest.mark.asyncio
    async def test_queries_past_events(self, calendar, mock_db):
        mock_db.query_macro_events.return_value = []
        await calendar.get_past(days=30)
        call_kwargs = mock_db.query_macro_events.call_args[1]
        assert call_kwargs["order"] == "desc"


class TestGetByType:
    @pytest.mark.asyncio
    async def test_filters_by_event_type(self, calendar, mock_db):
        mock_db.query_macro_events.return_value = []
        await calendar.get_by_type("cpi", limit=50)
        call_kwargs = mock_db.query_macro_events.call_args[1]
        assert call_kwargs["event_type"] == "cpi"
        assert call_kwargs["limit"] == 50


class TestGetByCategory:
    @pytest.mark.asyncio
    async def test_filters_by_category(self, calendar, mock_db):
        mock_db.query_macro_events.return_value = []
        await calendar.get_by_category("inflation", days=30)
        call_kwargs = mock_db.query_macro_events.call_args[1]
        assert call_kwargs["category"] == "inflation"


class TestGetThisWeek:
    @pytest.mark.asyncio
    async def test_delegates_to_get_upcoming(self, calendar, mock_db):
        mock_db.query_macro_events.return_value = []
        await calendar.get_this_week()
        mock_db.query_macro_events.assert_awaited_once()


class TestGetNextCritical:
    @pytest.mark.asyncio
    async def test_filters_critical_high(self, calendar, mock_db):
        mock_db.query_macro_events.return_value = []
        await calendar.get_next_critical(limit=5)
        call_kwargs = mock_db.query_macro_events.call_args[1]
        assert call_kwargs["importance_in"] == ["critical", "high"]
        assert call_kwargs["limit"] == 5


class TestSeedEvents:
    @pytest.mark.asyncio
    async def test_seeds_all_months(self, calendar, mock_db):
        count = await calendar.seed_events(2026)
        # Should seed 12 months of recurring events + FOMC
        assert count > 0
        assert mock_db.upsert_macro_event.await_count == count

    @pytest.mark.asyncio
    async def test_seeds_specific_months(self, calendar, mock_db):
        count = await calendar.seed_events(2026, months=[1, 2])
        assert count > 0
        # 2 months of recurring + FOMC events
        expected_recurring = 2 * len(_RECURRING_RULES)
        expected_fomc = len(_FOMC_DECISION_DATES_2026)
        assert count == expected_recurring + expected_fomc


class TestRowToEvent:
    def test_basic_conversion(self):
        row = _make_event_row()
        event = EconomicCalendar._row_to_event(row)
        assert isinstance(event, MacroEvent)
        assert event.id == "ev-1"
        assert event.event_type == "cpi"

    def test_parses_json_sectors(self):
        row = _make_event_row(affected_sectors=json.dumps(["Tech", "Finance"]))
        event = EconomicCalendar._row_to_event(row)
        assert event.affected_sectors == ["Tech", "Finance"]

    def test_handles_invalid_json_sectors(self):
        row = _make_event_row(affected_sectors="bad json")
        event = EconomicCalendar._row_to_event(row)
        assert event.affected_sectors == []

    def test_handles_list_sectors(self):
        row = _make_event_row(affected_sectors=["Tech"])
        event = EconomicCalendar._row_to_event(row)
        assert event.affected_sectors == ["Tech"]

    def test_parses_json_meta(self):
        row = _make_event_row(meta=json.dumps({"key": "val"}))
        event = EconomicCalendar._row_to_event(row)
        assert event.meta["key"] == "val"

    def test_handles_invalid_json_meta(self):
        row = _make_event_row(meta="bad json")
        event = EconomicCalendar._row_to_event(row)
        assert event.meta == {}


class TestFindNearbyEvents:
    def test_finds_events_within_window(self):
        events = [
            MacroEvent(id="e1", event_type="cpi", name="CPI",
                       scheduled_at=1000.0, category="inflation"),
            MacroEvent(id="e2", event_type="ppi", name="PPI",
                       scheduled_at=100000.0, category="inflation"),
        ]
        result = EconomicCalendar.find_nearby_events(events, 1500.0, window_hours=1)
        assert len(result) == 1
        assert result[0].id == "e1"

    def test_empty_when_no_match(self):
        events = [
            MacroEvent(id="e1", event_type="cpi", name="CPI",
                       scheduled_at=1000.0, category="inflation"),
        ]
        result = EconomicCalendar.find_nearby_events(events, 100000.0, window_hours=1)
        assert len(result) == 0

    def test_multiple_matches(self):
        events = [
            MacroEvent(id="e1", event_type="cpi", name="CPI",
                       scheduled_at=1000.0, category="inflation"),
            MacroEvent(id="e2", event_type="ppi", name="PPI",
                       scheduled_at=1500.0, category="inflation"),
            MacroEvent(id="e3", event_type="nfp", name="NFP",
                       scheduled_at=500000.0, category="employment"),
        ]
        result = EconomicCalendar.find_nearby_events(events, 1200.0, window_hours=1)
        assert len(result) == 2

    def test_default_window_24h(self):
        events = [
            MacroEvent(id="e1", event_type="cpi", name="CPI",
                       scheduled_at=1000.0, category="inflation"),
        ]
        # 24 hours = 86400 seconds
        result = EconomicCalendar.find_nearby_events(events, 87400.0)
        assert len(result) == 1  # Within 24h

    @pytest.mark.parametrize("window_hours", [1, 6, 12, 24, 48, 72])
    def test_parametrized_windows(self, window_hours):
        events = [
            MacroEvent(id="e1", event_type="cpi", name="CPI",
                       scheduled_at=0.0, category="inflation"),
        ]
        window_s = window_hours * 3600
        # Just inside the window
        result = EconomicCalendar.find_nearby_events(
            events, float(window_s - 1), window_hours=window_hours
        )
        assert len(result) == 1
        # Just outside the window
        result = EconomicCalendar.find_nearby_events(
            events, float(window_s + 1), window_hours=window_hours
        )
        assert len(result) == 0


# =========================================================================
# Part 4: EventImpactAnalyzer
# =========================================================================


class TestAnalyzeImpact:
    @pytest.mark.asyncio
    async def test_returns_empty_impact_for_no_data(self, analyzer, mock_db):
        mock_db.query_macro_events.return_value = []
        impact = await analyzer.analyze_impact("cpi")
        assert impact.sample_size == 0
        assert impact.avg_spy_move_pct == 0.0

    @pytest.mark.asyncio
    async def test_computes_average_moves(self, analyzer, mock_db):
        rows = [
            _make_reaction(spy_move=0.5, vix=1.0),
            _make_reaction(spy_move=-0.3, vix=-0.5),
            _make_reaction(spy_move=0.8, vix=2.0),
        ]
        mock_db.query_macro_events.return_value = rows
        impact = await analyzer.analyze_impact("cpi")
        assert impact.sample_size == 3
        expected_spy = statistics.mean([0.5, -0.3, 0.8])
        assert impact.avg_spy_move_pct == pytest.approx(round(expected_spy, 4))

    @pytest.mark.asyncio
    async def test_computes_max_min_moves(self, analyzer, mock_db):
        rows = [
            _make_reaction(spy_move=1.5),
            _make_reaction(spy_move=-0.8),
            _make_reaction(spy_move=0.3),
        ]
        mock_db.query_macro_events.return_value = rows
        impact = await analyzer.analyze_impact("cpi")
        assert impact.max_spy_move_pct == pytest.approx(1.5)
        assert impact.min_spy_move_pct == pytest.approx(-0.8)

    @pytest.mark.asyncio
    async def test_uses_cache_when_fresh(self, analyzer, mock_db):
        mock_db.get_event_impact_cache.return_value = {
            "event_type": "cpi",
            "avg_spy_move": 0.5,
            "avg_vix_change": 1.0,
            "sample_size": 20,
            "computed_at": time.time(),
            "reactions_json": "[]",
            "sector_sensitivity_json": "[]",
        }
        impact = await analyzer.analyze_impact("cpi")
        assert impact.avg_spy_move_pct == 0.5
        mock_db.query_macro_events.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ignores_stale_cache(self, analyzer, mock_db):
        mock_db.get_event_impact_cache.return_value = {
            "event_type": "cpi",
            "avg_spy_move": 0.5,
            "computed_at": time.time() - 100000,  # Old cache
        }
        mock_db.query_macro_events.return_value = [_make_reaction(spy_move=0.3)]
        impact = await analyzer.analyze_impact("cpi")
        assert impact.sample_size == 1  # Used fresh data, not cache

    @pytest.mark.asyncio
    async def test_limits_reactions_to_50(self, analyzer, mock_db):
        rows = [_make_reaction(spy_move=float(i) / 100) for i in range(100)]
        mock_db.query_macro_events.return_value = rows
        impact = await analyzer.analyze_impact("cpi")
        assert len(impact.historical_reactions) <= 50

    @pytest.mark.asyncio
    async def test_saves_to_cache(self, analyzer, mock_db):
        rows = [_make_reaction(spy_move=0.5)]
        mock_db.query_macro_events.return_value = rows
        await analyzer.analyze_impact("cpi")
        mock_db.save_event_impact_cache.assert_awaited_once()


class TestPredictImpact:
    @pytest.mark.asyncio
    async def test_low_sample_returns_low_confidence(self, analyzer, mock_db):
        rows = [_make_reaction(spy_move=0.5) for _ in range(3)]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.predict_impact("cpi")
        assert result["confidence"] == "low"
        assert "Insufficient" in result["recommendation"]

    @pytest.mark.asyncio
    async def test_high_sample_consistent_returns_high_confidence(self, analyzer, mock_db):
        # 20+ samples, consistent moves (low CV)
        rows = [_make_reaction(spy_move=0.5 + (i % 3) * 0.1) for i in range(25)]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.predict_impact("cpi")
        assert result["confidence"] in ("high", "medium")

    @pytest.mark.asyncio
    async def test_high_impact_recommendation(self, analyzer, mock_db):
        # High abs moves > 1.0
        rows = [_make_reaction(spy_move=1.5) for _ in range(20)]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.predict_impact("cpi")
        assert "straddle" in result["recommendation"].lower() or "volatility" in result["recommendation"].lower()

    @pytest.mark.asyncio
    async def test_low_impact_recommendation(self, analyzer, mock_db):
        rows = [_make_reaction(spy_move=0.1) for _ in range(20)]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.predict_impact("cpi")
        assert "low" in result["recommendation"].lower()

    @pytest.mark.asyncio
    async def test_includes_affected_sectors(self, analyzer, mock_db):
        rows = [_make_reaction(spy_move=0.5) for _ in range(10)]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.predict_impact("cpi")
        assert "affected_sectors" in result

    @pytest.mark.asyncio
    async def test_includes_sample_size(self, analyzer, mock_db):
        rows = [_make_reaction(spy_move=0.5) for _ in range(10)]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.predict_impact("cpi")
        assert result["sample_size"] == 10


class TestGetSectorSensitivity:
    @pytest.mark.asyncio
    async def test_empty_when_no_sector_moves(self, analyzer, mock_db):
        rows = [_make_reaction(sector_moves={})]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.get_sector_sensitivity("cpi")
        assert result == {}

    @pytest.mark.asyncio
    async def test_computes_average_sector_moves(self, analyzer, mock_db):
        rows = [
            _make_reaction(sector_moves={"Tech": 0.5, "Finance": -0.3}),
            _make_reaction(sector_moves={"Tech": 0.7, "Finance": 0.1}),
        ]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.get_sector_sensitivity("cpi")
        assert "Tech" in result
        assert "Finance" in result
        # Uses absolute values
        assert result["Tech"] == pytest.approx(statistics.mean([0.5, 0.7]), abs=0.001)


class TestGetSurpriseCorrelation:
    @pytest.mark.asyncio
    async def test_returns_zero_with_few_samples(self, analyzer, mock_db):
        rows = [_make_reaction(surprise=0.1) for _ in range(3)]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.get_surprise_correlation("cpi")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_computes_correlation(self, analyzer, mock_db):
        # Create correlated data: higher surprise → higher move
        rows = [
            _make_reaction(spy_move=float(i) * 0.1, surprise=float(i) * 0.05)
            for i in range(1, 10)
        ]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.get_surprise_correlation("cpi")
        assert -1.0 <= result <= 1.0
        assert result > 0.5  # Should be positively correlated

    @pytest.mark.asyncio
    async def test_excludes_zero_surprises(self, analyzer, mock_db):
        rows = [_make_reaction(surprise=0.0) for _ in range(10)]
        mock_db.query_macro_events.return_value = rows
        result = await analyzer.get_surprise_correlation("cpi")
        assert result == 0.0  # All filtered out


class TestPearson:
    def test_perfect_positive(self):
        r = EventImpactAnalyzer._pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
        assert r == pytest.approx(1.0, abs=0.001)

    def test_perfect_negative(self):
        r = EventImpactAnalyzer._pearson([1, 2, 3, 4, 5], [10, 8, 6, 4, 2])
        assert r == pytest.approx(-1.0, abs=0.001)

    def test_weak_or_no_correlation(self):
        r = EventImpactAnalyzer._pearson([1, 2, 3, 4, 5], [3, 1, 4, 2, 5])
        assert -1.0 <= r <= 1.0  # Valid range

    def test_single_element_returns_zero(self):
        assert EventImpactAnalyzer._pearson([1], [1]) == 0.0

    def test_empty_returns_zero(self):
        assert EventImpactAnalyzer._pearson([], []) == 0.0

    def test_constant_y_returns_zero(self):
        r = EventImpactAnalyzer._pearson([1, 2, 3], [5, 5, 5])
        assert r == 0.0


class TestCacheToImpact:
    def test_basic_conversion(self):
        cached = {
            "event_type": "cpi",
            "avg_spy_move": 0.5,
            "avg_vix_change": 1.0,
            "sample_size": 20,
            "reactions_json": json.dumps([
                {"date": 1.0, "spy_move_pct": 0.5, "vix_change": 1.0},
            ]),
            "sector_sensitivity_json": json.dumps(["Tech", "Finance"]),
        }
        impact = EventImpactAnalyzer._cache_to_impact(cached)
        assert impact.event_type == "cpi"
        assert impact.avg_spy_move_pct == 0.5
        assert len(impact.historical_reactions) == 1
        assert impact.most_affected_sectors == ["Tech", "Finance"]

    def test_handles_invalid_reactions_json(self):
        cached = {
            "event_type": "cpi",
            "avg_spy_move": 0.0,
            "avg_vix_change": 0.0,
            "reactions_json": "bad json",
            "sector_sensitivity_json": "[]",
        }
        impact = EventImpactAnalyzer._cache_to_impact(cached)
        assert impact.historical_reactions == []

    def test_handles_missing_keys(self):
        cached = {"event_type": "cpi"}
        impact = EventImpactAnalyzer._cache_to_impact(cached)
        assert impact.avg_spy_move_pct == 0.0
        assert impact.sample_size == 0


# ---------------------------------------------------------------------------
# FOMC dates
# ---------------------------------------------------------------------------


class TestFomcDates:
    def test_eight_meetings_in_2026(self):
        assert len(_FOMC_DECISION_DATES_2026) == 8

    def test_all_dates_in_2026(self):
        for ds in _FOMC_DECISION_DATES_2026:
            assert ds.startswith("2026-")

    def test_dates_are_sorted(self):
        assert _FOMC_DECISION_DATES_2026 == sorted(_FOMC_DECISION_DATES_2026)


# ---------------------------------------------------------------------------
# Recurring rules
# ---------------------------------------------------------------------------


class TestRecurringRules:
    def test_has_expected_event_types(self):
        expected = {
            "nonfarm_payrolls", "initial_claims", "cpi", "core_cpi", "ppi",
            "retail_sales", "michigan_sentiment", "consumer_confidence",
            "ism_manufacturing", "ism_services", "existing_home_sales",
            "housing_starts", "opex",
        }
        assert set(_RECURRING_RULES.keys()) == expected

    def test_all_rules_have_name(self):
        for et, rule in _RECURRING_RULES.items():
            assert "name" in rule, f"{et} missing name"

    def test_all_rules_have_rule(self):
        for et, rule in _RECURRING_RULES.items():
            assert "rule" in rule, f"{et} missing rule"

    def test_all_rules_have_time_et(self):
        for et, rule in _RECURRING_RULES.items():
            assert "time_et" in rule, f"{et} missing time_et"
            h, m = rule["time_et"].split(":")
            assert 0 <= int(h) <= 23
            assert 0 <= int(m) <= 59
