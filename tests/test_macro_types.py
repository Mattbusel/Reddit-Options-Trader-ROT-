"""Tests for rot.macro.types — frozen dataclasses and constant mappings."""

from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError

from rot.macro.types import (
    MacroEvent,
    EarningsEvent,
    InsiderTrade,
    FOMCMeeting,
    HistoricalReaction,
    EventImpact,
    SeasonalPattern,
    ALL_EVENT_TYPES,
    EVENT_TYPE_CATEGORY,
    EVENT_TYPE_IMPORTANCE,
    CATEGORY_SECTOR_SENSITIVITY,
    # Event type constants
    FOMC_DECISION,
    FOMC_MINUTES,
    FED_SPEECH,
    ECB_DECISION,
    NFP,
    INITIAL_CLAIMS,
    JOLTS,
    ADP_EMPLOYMENT,
    UNEMPLOYMENT_RATE,
    CPI,
    CORE_CPI,
    PPI,
    PCE,
    CORE_PCE,
    GDP_ADVANCE,
    GDP_PRELIMINARY,
    GDP_FINAL,
    HOUSING_STARTS,
    EXISTING_HOME_SALES,
    NEW_HOME_SALES,
    CASE_SHILLER,
    BUILDING_PERMITS,
    ISM_MANUFACTURING,
    ISM_SERVICES,
    DURABLE_GOODS,
    INDUSTRIAL_PRODUCTION,
    CAPACITY_UTILIZATION,
    RETAIL_SALES,
    CONSUMER_CONFIDENCE,
    MICHIGAN_SENTIMENT,
    PERSONAL_INCOME,
    PERSONAL_SPENDING,
    VIX_EXPIRY,
    OPEX,
    QUAD_WITCHING,
    EARNINGS_SEASON_START,
    EARNINGS_SEASON_END,
    EARNINGS_REPORT,
    TREASURY_AUCTION,
    DEBT_CEILING,
    GOVERNMENT_SHUTDOWN,
    TRADE_DATA,
    BUDGET_STATEMENT,
)


# ── MacroEvent ──────────────────────────────────────────────────────


class TestMacroEvent:
    def test_creation_with_required_fields(self):
        ev = MacroEvent(
            id="ev-1",
            event_type="cpi",
            name="Consumer Price Index",
            scheduled_at=1700000000.0,
            category="inflation",
        )
        assert ev.id == "ev-1"
        assert ev.event_type == "cpi"
        assert ev.name == "Consumer Price Index"
        assert ev.scheduled_at == 1700000000.0
        assert ev.category == "inflation"

    def test_creation_defaults(self):
        ev = MacroEvent(
            id="ev-2",
            event_type="nfp",
            name="Nonfarm Payrolls",
            scheduled_at=1700000000.0,
            category="employment",
        )
        assert ev.importance == "medium"
        assert ev.country == "US"
        assert ev.actual_at is None
        assert ev.consensus_value is None
        assert ev.actual_value is None
        assert ev.previous_value is None
        assert ev.surprise_pct is None
        assert ev.affected_sectors == []
        assert ev.affected_tickers == []
        assert ev.source == ""
        assert ev.meta == {}

    def test_creation_all_fields(self):
        ev = MacroEvent(
            id="ev-3",
            event_type="fomc_decision",
            name="FOMC Rate Decision",
            scheduled_at=1700000000.0,
            category="monetary_policy",
            importance="critical",
            country="US",
            actual_at=1700000100.0,
            consensus_value=5.25,
            actual_value=5.50,
            previous_value=5.25,
            surprise_pct=4.76,
            affected_sectors=["Financials", "Real Estate"],
            affected_tickers=["SPY", "XLF"],
            source="fed_calendar",
            meta={"notes": "Hawkish surprise"},
        )
        assert ev.importance == "critical"
        assert ev.actual_at == 1700000100.0
        assert ev.consensus_value == 5.25
        assert ev.actual_value == 5.50
        assert ev.previous_value == 5.25
        assert ev.surprise_pct == 4.76
        assert ev.affected_sectors == ["Financials", "Real Estate"]
        assert ev.affected_tickers == ["SPY", "XLF"]
        assert ev.source == "fed_calendar"
        assert ev.meta == {"notes": "Hawkish surprise"}

    def test_frozen_immutability(self):
        ev = MacroEvent(
            id="ev-4",
            event_type="cpi",
            name="CPI",
            scheduled_at=1700000000.0,
            category="inflation",
        )
        with pytest.raises(FrozenInstanceError):
            ev.importance = "high"  # type: ignore[misc]

    def test_frozen_cannot_set_id(self):
        ev = MacroEvent(
            id="ev-5",
            event_type="cpi",
            name="CPI",
            scheduled_at=1700000000.0,
            category="inflation",
        )
        with pytest.raises(FrozenInstanceError):
            ev.id = "new-id"  # type: ignore[misc]


# ── EarningsEvent ───────────────────────────────────────────────────


class TestEarningsEvent:
    def test_creation_with_required_fields(self):
        ev = EarningsEvent(
            id="earn-1",
            ticker="TSLA",
            report_date=1700000000.0,
        )
        assert ev.id == "earn-1"
        assert ev.ticker == "TSLA"
        assert ev.report_date == 1700000000.0

    def test_creation_defaults(self):
        ev = EarningsEvent(
            id="earn-2",
            ticker="AAPL",
            report_date=1700000000.0,
        )
        assert ev.fiscal_quarter == ""
        assert ev.eps_estimate is None
        assert ev.eps_actual is None
        assert ev.revenue_estimate is None
        assert ev.revenue_actual is None
        assert ev.surprise_pct is None
        assert ev.expected_move_pct is None
        assert ev.actual_move_pct is None
        assert ev.iv_before is None
        assert ev.iv_after is None
        assert ev.iv_crush_pct is None
        assert ev.meta == {}

    def test_creation_all_fields(self):
        ev = EarningsEvent(
            id="earn-3",
            ticker="MSFT",
            report_date=1700000000.0,
            fiscal_quarter="2024-Q3",
            eps_estimate=2.35,
            eps_actual=2.50,
            revenue_estimate=55000000000.0,
            revenue_actual=56200000000.0,
            surprise_pct=6.38,
            expected_move_pct=4.5,
            actual_move_pct=3.2,
            iv_before=45.0,
            iv_after=30.0,
            iv_crush_pct=33.3,
            meta={"beat": True},
        )
        assert ev.eps_estimate == 2.35
        assert ev.eps_actual == 2.50
        assert ev.revenue_actual == 56200000000.0
        assert ev.surprise_pct == 6.38
        assert ev.iv_crush_pct == 33.3
        assert ev.meta == {"beat": True}

    def test_frozen_immutability(self):
        ev = EarningsEvent(id="earn-4", ticker="GOOG", report_date=1700000000.0)
        with pytest.raises(FrozenInstanceError):
            ev.ticker = "GOOGL"  # type: ignore[misc]


# ── InsiderTrade ────────────────────────────────────────────────────


class TestInsiderTrade:
    def test_creation_with_required_fields(self):
        trade = InsiderTrade(
            id="ins-1",
            ticker="AAPL",
            insider_name="Tim Cook",
            trade_type="sell",
            filing_date=1700000000.0,
            source="form4",
        )
        assert trade.id == "ins-1"
        assert trade.ticker == "AAPL"
        assert trade.insider_name == "Tim Cook"
        assert trade.trade_type == "sell"
        assert trade.source == "form4"

    def test_creation_defaults(self):
        trade = InsiderTrade(
            id="ins-2",
            ticker="MSFT",
            insider_name="Satya Nadella",
            trade_type="buy",
            filing_date=1700000000.0,
            source="congress",
        )
        assert trade.title == ""
        assert trade.shares == 0
        assert trade.price == 0.0
        assert trade.value == 0.0
        assert trade.transaction_date is None
        assert trade.meta == {}

    def test_creation_all_fields(self):
        trade = InsiderTrade(
            id="ins-3",
            ticker="NVDA",
            insider_name="Jensen Huang",
            trade_type="sell",
            filing_date=1700000000.0,
            source="form4",
            title="CEO",
            shares=10000,
            price=450.50,
            value=4505000.0,
            transaction_date=1699900000.0,
            meta={"plan": "10b5-1"},
        )
        assert trade.title == "CEO"
        assert trade.shares == 10000
        assert trade.price == 450.50
        assert trade.value == 4505000.0
        assert trade.transaction_date == 1699900000.0
        assert trade.meta == {"plan": "10b5-1"}

    def test_frozen_immutability(self):
        trade = InsiderTrade(
            id="ins-4",
            ticker="AAPL",
            insider_name="Test",
            trade_type="buy",
            filing_date=1700000000.0,
            source="form4",
        )
        with pytest.raises(FrozenInstanceError):
            trade.shares = 100  # type: ignore[misc]


# ── FOMCMeeting ─────────────────────────────────────────────────────


class TestFOMCMeeting:
    def test_creation_with_required_fields(self):
        meeting = FOMCMeeting(id="fomc-1", meeting_date=1700000000.0)
        assert meeting.id == "fomc-1"
        assert meeting.meeting_date == 1700000000.0

    def test_creation_defaults(self):
        meeting = FOMCMeeting(id="fomc-2", meeting_date=1700000000.0)
        assert meeting.rate_decision == ""
        assert meeting.rate_before == 0.0
        assert meeting.rate_after == 0.0
        assert meeting.statement_text == ""
        assert meeting.statement_diff == ""
        assert meeting.hawkish_score == 0.0
        assert meeting.dovish_score == 0.0
        assert meeting.dot_plot_median is None
        assert meeting.meta == {}

    def test_creation_all_fields(self):
        meeting = FOMCMeeting(
            id="fomc-3",
            meeting_date=1700000000.0,
            rate_decision="raise_25",
            rate_before=5.25,
            rate_after=5.50,
            statement_text="The Committee decided...",
            statement_diff="<html>diff</html>",
            hawkish_score=0.8,
            dovish_score=0.2,
            dot_plot_median=5.75,
            meta={"votes": "11-1"},
        )
        assert meeting.rate_decision == "raise_25"
        assert meeting.rate_before == 5.25
        assert meeting.rate_after == 5.50
        assert meeting.hawkish_score == 0.8
        assert meeting.dovish_score == 0.2
        assert meeting.dot_plot_median == 5.75

    def test_frozen_immutability(self):
        meeting = FOMCMeeting(id="fomc-4", meeting_date=1700000000.0)
        with pytest.raises(FrozenInstanceError):
            meeting.rate_decision = "cut_50"  # type: ignore[misc]


# ── HistoricalReaction ──────────────────────────────────────────────


class TestHistoricalReaction:
    def test_creation_required(self):
        r = HistoricalReaction(
            date=1700000000.0,
            spy_move_pct=-1.2,
            vix_change=3.5,
        )
        assert r.date == 1700000000.0
        assert r.spy_move_pct == -1.2
        assert r.vix_change == 3.5

    def test_creation_defaults(self):
        r = HistoricalReaction(
            date=1700000000.0, spy_move_pct=0.5, vix_change=-1.0
        )
        assert r.surprise_pct == 0.0
        assert r.sector_moves == {}

    def test_creation_all_fields(self):
        r = HistoricalReaction(
            date=1700000000.0,
            spy_move_pct=2.1,
            vix_change=-5.0,
            surprise_pct=0.3,
            sector_moves={"Technology": 3.5, "Financials": -1.2},
        )
        assert r.surprise_pct == 0.3
        assert r.sector_moves["Technology"] == 3.5

    def test_frozen_immutability(self):
        r = HistoricalReaction(date=1.0, spy_move_pct=0.0, vix_change=0.0)
        with pytest.raises(FrozenInstanceError):
            r.spy_move_pct = 1.0  # type: ignore[misc]


# ── EventImpact ─────────────────────────────────────────────────────


class TestEventImpact:
    def test_creation_required(self):
        impact = EventImpact(
            event_type="cpi",
            avg_spy_move_pct=-0.5,
            avg_vix_change=2.0,
        )
        assert impact.event_type == "cpi"
        assert impact.avg_spy_move_pct == -0.5
        assert impact.avg_vix_change == 2.0

    def test_creation_defaults(self):
        impact = EventImpact(
            event_type="nfp", avg_spy_move_pct=0.0, avg_vix_change=0.0
        )
        assert impact.max_spy_move_pct == 0.0
        assert impact.min_spy_move_pct == 0.0
        assert impact.historical_reactions == []
        assert impact.most_affected_sectors == []
        assert impact.sample_size == 0

    def test_creation_all_fields(self):
        reaction = HistoricalReaction(date=1.0, spy_move_pct=0.5, vix_change=-0.3)
        impact = EventImpact(
            event_type="fomc_decision",
            avg_spy_move_pct=0.3,
            avg_vix_change=-1.5,
            max_spy_move_pct=2.0,
            min_spy_move_pct=-1.8,
            historical_reactions=[reaction],
            most_affected_sectors=["Financials"],
            sample_size=50,
        )
        assert impact.max_spy_move_pct == 2.0
        assert impact.min_spy_move_pct == -1.8
        assert len(impact.historical_reactions) == 1
        assert impact.most_affected_sectors == ["Financials"]
        assert impact.sample_size == 50

    def test_frozen_immutability(self):
        impact = EventImpact(
            event_type="cpi", avg_spy_move_pct=0.0, avg_vix_change=0.0
        )
        with pytest.raises(FrozenInstanceError):
            impact.sample_size = 10  # type: ignore[misc]


# ── SeasonalPattern ─────────────────────────────────────────────────


class TestSeasonalPattern:
    def test_creation_required(self):
        p = SeasonalPattern(
            ticker_or_sector="AAPL",
            month=1,
            avg_return_pct=1.5,
            win_rate_pct=62.0,
            sample_years=10,
        )
        assert p.ticker_or_sector == "AAPL"
        assert p.month == 1
        assert p.avg_return_pct == 1.5
        assert p.win_rate_pct == 62.0
        assert p.sample_years == 10

    def test_creation_defaults(self):
        p = SeasonalPattern(
            ticker_or_sector="SPY",
            month=9,
            avg_return_pct=-0.7,
            win_rate_pct=42.0,
            sample_years=20,
        )
        assert p.best_year_return == 0.0
        assert p.worst_year_return == 0.0
        assert p.median_return_pct == 0.0

    def test_creation_all_fields(self):
        p = SeasonalPattern(
            ticker_or_sector="Technology",
            month=11,
            avg_return_pct=1.8,
            win_rate_pct=70.0,
            sample_years=20,
            best_year_return=8.5,
            worst_year_return=-3.2,
            median_return_pct=1.5,
        )
        assert p.best_year_return == 8.5
        assert p.worst_year_return == -3.2
        assert p.median_return_pct == 1.5

    def test_frozen_immutability(self):
        p = SeasonalPattern(
            ticker_or_sector="SPY", month=1, avg_return_pct=1.0,
            win_rate_pct=55.0, sample_years=10,
        )
        with pytest.raises(FrozenInstanceError):
            p.month = 2  # type: ignore[misc]


# ── ALL_EVENT_TYPES constant ────────────────────────────────────────


class TestAllEventTypes:
    def test_is_set(self):
        assert isinstance(ALL_EVENT_TYPES, set)

    def test_contains_fomc_decision(self):
        assert FOMC_DECISION in ALL_EVENT_TYPES

    def test_contains_nfp(self):
        assert NFP in ALL_EVENT_TYPES

    def test_contains_cpi(self):
        assert CPI in ALL_EVENT_TYPES

    def test_contains_core_cpi(self):
        assert CORE_CPI in ALL_EVENT_TYPES

    def test_contains_ppi(self):
        assert PPI in ALL_EVENT_TYPES

    def test_contains_pce(self):
        assert PCE in ALL_EVENT_TYPES

    def test_contains_gdp_advance(self):
        assert GDP_ADVANCE in ALL_EVENT_TYPES

    def test_contains_opex(self):
        assert OPEX in ALL_EVENT_TYPES

    def test_contains_ism_manufacturing(self):
        assert ISM_MANUFACTURING in ALL_EVENT_TYPES

    def test_contains_retail_sales(self):
        assert RETAIL_SALES in ALL_EVENT_TYPES

    def test_contains_debt_ceiling(self):
        assert DEBT_CEILING in ALL_EVENT_TYPES

    def test_contains_earnings_report(self):
        assert EARNINGS_REPORT in ALL_EVENT_TYPES

    def test_has_at_least_40_types(self):
        assert len(ALL_EVENT_TYPES) >= 40

    def test_all_types_are_strings(self):
        for t in ALL_EVENT_TYPES:
            assert isinstance(t, str)


# ── EVENT_TYPE_CATEGORY mapping ─────────────────────────────────────


class TestEventTypeCategory:
    def test_is_dict(self):
        assert isinstance(EVENT_TYPE_CATEGORY, dict)

    def test_covers_all_event_types(self):
        """Every event type in ALL_EVENT_TYPES should have a category."""
        for et in ALL_EVENT_TYPES:
            assert et in EVENT_TYPE_CATEGORY, f"{et} missing from EVENT_TYPE_CATEGORY"

    def test_fomc_is_monetary_policy(self):
        assert EVENT_TYPE_CATEGORY[FOMC_DECISION] == "monetary_policy"

    def test_nfp_is_employment(self):
        assert EVENT_TYPE_CATEGORY[NFP] == "employment"

    def test_cpi_is_inflation(self):
        assert EVENT_TYPE_CATEGORY[CPI] == "inflation"

    def test_gdp_advance_is_gdp(self):
        assert EVENT_TYPE_CATEGORY[GDP_ADVANCE] == "gdp"

    def test_housing_starts_is_housing(self):
        assert EVENT_TYPE_CATEGORY[HOUSING_STARTS] == "housing"

    def test_ism_is_manufacturing(self):
        assert EVENT_TYPE_CATEGORY[ISM_MANUFACTURING] == "manufacturing"

    def test_retail_sales_is_consumer(self):
        assert EVENT_TYPE_CATEGORY[RETAIL_SALES] == "consumer"

    def test_opex_is_markets(self):
        assert EVENT_TYPE_CATEGORY[OPEX] == "markets"

    def test_earnings_report_is_earnings(self):
        assert EVENT_TYPE_CATEGORY[EARNINGS_REPORT] == "earnings"

    def test_treasury_auction_is_government(self):
        assert EVENT_TYPE_CATEGORY[TREASURY_AUCTION] == "government"

    def test_all_values_are_valid_categories(self):
        valid_cats = {
            "monetary_policy", "employment", "inflation", "gdp", "housing",
            "manufacturing", "consumer", "markets", "earnings", "insider",
            "congressional", "government", "other",
        }
        for et, cat in EVENT_TYPE_CATEGORY.items():
            assert cat in valid_cats, f"{et} has invalid category {cat}"


# ── EVENT_TYPE_IMPORTANCE mapping ───────────────────────────────────


class TestEventTypeImportance:
    def test_is_dict(self):
        assert isinstance(EVENT_TYPE_IMPORTANCE, dict)

    def test_covers_all_event_types(self):
        for et in ALL_EVENT_TYPES:
            assert et in EVENT_TYPE_IMPORTANCE, f"{et} missing from EVENT_TYPE_IMPORTANCE"

    def test_fomc_decision_is_critical(self):
        assert EVENT_TYPE_IMPORTANCE[FOMC_DECISION] == "critical"

    def test_nfp_is_critical(self):
        assert EVENT_TYPE_IMPORTANCE[NFP] == "critical"

    def test_cpi_is_critical(self):
        assert EVENT_TYPE_IMPORTANCE[CPI] == "critical"

    def test_case_shiller_is_low(self):
        assert EVENT_TYPE_IMPORTANCE[CASE_SHILLER] == "low"

    def test_opex_is_high(self):
        assert EVENT_TYPE_IMPORTANCE[OPEX] == "high"

    def test_debt_ceiling_is_critical(self):
        assert EVENT_TYPE_IMPORTANCE[DEBT_CEILING] == "critical"

    def test_all_values_are_valid_importance(self):
        valid = {"low", "medium", "high", "critical"}
        for et, imp in EVENT_TYPE_IMPORTANCE.items():
            assert imp in valid, f"{et} has invalid importance {imp}"


# ── CATEGORY_SECTOR_SENSITIVITY mapping ─────────────────────────────


class TestCategorySectorSensitivity:
    def test_is_dict(self):
        assert isinstance(CATEGORY_SECTOR_SENSITIVITY, dict)

    def test_has_monetary_policy(self):
        assert "monetary_policy" in CATEGORY_SECTOR_SENSITIVITY

    def test_has_employment(self):
        assert "employment" in CATEGORY_SECTOR_SENSITIVITY

    def test_has_inflation(self):
        assert "inflation" in CATEGORY_SECTOR_SENSITIVITY

    def test_has_gdp(self):
        assert "gdp" in CATEGORY_SECTOR_SENSITIVITY

    def test_has_housing(self):
        assert "housing" in CATEGORY_SECTOR_SENSITIVITY

    def test_has_manufacturing(self):
        assert "manufacturing" in CATEGORY_SECTOR_SENSITIVITY

    def test_monetary_policy_includes_financials(self):
        assert "Financials" in CATEGORY_SECTOR_SENSITIVITY["monetary_policy"]

    def test_inflation_includes_energy(self):
        assert "Energy" in CATEGORY_SECTOR_SENSITIVITY["inflation"]

    def test_values_are_lists_of_strings(self):
        for cat, sectors in CATEGORY_SECTOR_SENSITIVITY.items():
            assert isinstance(sectors, list)
            for s in sectors:
                assert isinstance(s, str)
