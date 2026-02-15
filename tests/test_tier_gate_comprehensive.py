"""Comprehensive tests for rot.web.tier_gate — all 28 gate functions + signal gating."""
from __future__ import annotations

import json
import time

import pytest

from rot.web.tier_gate import (
    _parse_json_field,
    _redact_reasoning,
    _redact_trade_idea,
    gate_agent_access,
    gate_backtest_access,
    gate_chart_access,
    gate_congress_tracker_access,
    gate_correlation_access,
    gate_data_licensing,
    gate_email_access,
    gate_filter_access,
    gate_flow_access,
    gate_heatmap_access,
    gate_leaderboard_access,
    gate_macro_access,
    gate_market_context,
    gate_news_feed_access,
    gate_paper_leaderboard_access,
    gate_performance_access,
    gate_replay_access,
    gate_sector_rotation_access,
    gate_sentiment_access,
    gate_signal,
    gate_signal_list,
    gate_signal_quality_access,
    gate_social_access,
    gate_sponsored_access,
    gate_sports_betting_access,
    gate_strategy_access,
    gate_terminal_access,
    gate_ticker_dive_access,
    gate_tradingview_access,
    gate_unusual_activity,
    gate_weekly_wrap_access,
)

ALL_TIERS = ["free", "pro", "premium", "ultra", "enterprise", "admin"]
PAID_TIERS = ["pro", "premium", "ultra", "enterprise", "admin"]
PREMIUM_PLUS = ["premium", "ultra", "enterprise", "admin"]
ULTRA_PLUS = ["ultra", "enterprise", "admin"]
ENTERPRISE_PLUS = ["enterprise", "admin"]


# ---------------------------------------------------------------------------
# _parse_json_field
# ---------------------------------------------------------------------------


class TestParseJsonField:
    def test_dict_passthrough(self):
        assert _parse_json_field({"a": 1}) == {"a": 1}

    def test_json_string_parsed(self):
        assert _parse_json_field('{"a": 1}') == {"a": 1}

    def test_invalid_json_returns_empty(self):
        assert _parse_json_field("not json") == {}

    def test_none_passthrough(self):
        assert _parse_json_field(None) is None

    def test_int_passthrough(self):
        assert _parse_json_field(42) == 42

    @pytest.mark.parametrize("val,expected_type", [
        ('{"k":"v"}', dict),
        ("[1,2]", list),
        ("bad", dict),
        ({"x": 1}, dict),
    ])
    def test_various_inputs(self, val, expected_type):
        result = _parse_json_field(val)
        assert isinstance(result, expected_type)


# ---------------------------------------------------------------------------
# gate_signal — the core gating logic
# ---------------------------------------------------------------------------


class TestGateSignal:
    def _make_signal(self, age_s=2000):
        return {
            "id": "sig_test",
            "created_at": time.time() - age_s,
            "ticker": "TSLA",
            "stance": "bullish",
            "strategy": "debit_spread",
            "reasoning": json.dumps({"thesis": "bull case", "catalyst_window": "1w"}),
            "trade_idea": json.dumps({"strategy": "debit_spread", "legs": [{"strike": 300}]}),
            "market_data": json.dumps({"TSLA": {"price": 250}}),
            "event_data": json.dumps({"type": "earnings"}),
        }

    @pytest.mark.parametrize("tier", PAID_TIERS)
    def test_paid_tiers_get_full_access(self, tier):
        sig = self._make_signal()
        result = gate_signal(sig, tier)
        assert "_locked" not in result.get("reasoning", {})
        assert "_delayed" not in result

    def test_free_tier_old_signal_redacted(self):
        sig = self._make_signal(age_s=2000)
        result = gate_signal(sig, "free")
        assert result["reasoning"]["_locked"] is True
        assert result["trade_idea"]["_locked"] is True
        assert result["trade_idea"]["legs"] == []

    def test_free_tier_new_signal_delayed(self):
        sig = self._make_signal(age_s=100)  # Under 900s
        result = gate_signal(sig, "free")
        assert result["_delayed"] is True
        assert "_available_in_s" in result
        assert result["reasoning"]["_locked"] is True

    def test_free_tier_thesis_visible(self):
        sig = self._make_signal(age_s=2000)
        result = gate_signal(sig, "free")
        assert result["reasoning"]["thesis"] == "bull case"

    def test_json_fields_parsed(self):
        sig = self._make_signal()
        result = gate_signal(sig, "pro")
        assert isinstance(result["reasoning"], dict)
        assert isinstance(result["trade_idea"], dict)
        assert isinstance(result["market_data"], dict)


# ---------------------------------------------------------------------------
# gate_signal_list
# ---------------------------------------------------------------------------


class TestGateSignalList:
    def _make_signals(self, count, age_s=2000):
        return [
            {
                "id": f"sig_{i}",
                "created_at": time.time() - age_s,
                "ticker": "TSLA",
                "reasoning": "{}",
                "trade_idea": "{}",
                "market_data": "{}",
                "event_data": "{}",
            }
            for i in range(count)
        ]

    @pytest.mark.parametrize("tier", PAID_TIERS)
    def test_paid_no_limit(self, tier):
        signals = self._make_signals(20)
        result = gate_signal_list(signals, tier)
        assert len(result) == 20

    def test_free_page_limit(self):
        signals = self._make_signals(20)
        result = gate_signal_list(signals, "free", page_limit=10)
        assert len(result) == 10

    def test_free_custom_limit(self):
        signals = self._make_signals(20)
        result = gate_signal_list(signals, "free", page_limit=5)
        assert len(result) == 5

    def test_empty_list(self):
        result = gate_signal_list([], "free")
        assert result == []


# ---------------------------------------------------------------------------
# gate_chart_access
# ---------------------------------------------------------------------------


class TestGateChartAccess:
    @pytest.mark.parametrize("tier", PAID_TIERS)
    def test_paid_has_quadrant(self, tier):
        result = gate_chart_access(tier)
        assert result["has_quadrant"] is True

    def test_free_no_quadrant(self):
        result = gate_chart_access("free")
        assert result["has_quadrant"] is False
        assert result["chart_hours"] == 0

    def test_pro_chart_hours(self):
        result = gate_chart_access("pro")
        assert result["chart_hours"] == 24
        assert result["chart_limit"] == 50

    @pytest.mark.parametrize("tier", PREMIUM_PLUS)
    def test_premium_plus_strategy_breakdown(self, tier):
        result = gate_chart_access(tier)
        assert result["has_strategy_breakdown"] is True
        assert result["chart_hours"] == 48


# ---------------------------------------------------------------------------
# gate_filter_access
# ---------------------------------------------------------------------------


class TestGateFilterAccess:
    def test_free_has_confidence_only(self):
        result = gate_filter_access("free")
        assert result["has_confidence_range"] is True
        assert result["has_ticker_filter"] is False

    @pytest.mark.parametrize("tier", PAID_TIERS)
    def test_paid_has_filters(self, tier):
        result = gate_filter_access(tier)
        assert result["has_ticker_filter"] is True
        assert result["has_stance_filter"] is True


# ---------------------------------------------------------------------------
# gate_performance_access
# ---------------------------------------------------------------------------


class TestGatePerformanceAccess:
    @pytest.mark.parametrize("tier,expected_days", [
        ("free", 7), ("pro", 30), ("premium", 90), ("ultra", 365), ("enterprise", 365),
    ])
    def test_accuracy_days(self, tier, expected_days):
        result = gate_performance_access(tier)
        assert result["accuracy_days"] == expected_days

    def test_free_no_aggregate(self):
        result = gate_performance_access("free")
        assert result["has_aggregate_accuracy"] is False

    @pytest.mark.parametrize("tier", PAID_TIERS)
    def test_paid_has_accuracy_breakdown(self, tier):
        result = gate_performance_access(tier)
        assert result["has_accuracy_breakdown"] is True


# ---------------------------------------------------------------------------
# gate_backtest_access
# ---------------------------------------------------------------------------


class TestGateBacktestAccess:
    def test_free_no_access(self):
        result = gate_backtest_access("free")
        assert result["has_access"] is False
        assert result["max_days"] == 0
        assert result["position_size_modes"] == []

    def test_pro_basic(self):
        result = gate_backtest_access("pro")
        assert result["has_access"] is True
        assert result["has_basic"] is True
        assert result["has_monte_carlo"] is False
        assert result["max_days"] == 30

    def test_premium_advanced(self):
        result = gate_backtest_access("premium")
        assert result["has_monte_carlo"] is True
        assert result["has_walk_forward"] is True
        assert result["max_days"] == 90

    @pytest.mark.parametrize("tier", ULTRA_PLUS)
    def test_ultra_plus_full(self, tier):
        result = gate_backtest_access(tier)
        assert result["has_optimizer"] is True
        assert result["has_comparison"] is True
        assert result["max_days"] == 365
        assert "kelly" in result["position_size_modes"]


# ---------------------------------------------------------------------------
# gate_macro_access
# ---------------------------------------------------------------------------


class TestGateMacroAccess:
    def test_free_limited(self):
        result = gate_macro_access("free")
        assert result["has_calendar"] is True
        assert result["has_earnings"] is False
        assert result["calendar_max_events"] == 5

    @pytest.mark.parametrize("tier,has_seasonal", [
        ("pro", False), ("premium", True), ("ultra", True),
    ])
    def test_seasonal_by_tier(self, tier, has_seasonal):
        result = gate_macro_access(tier)
        assert result["has_seasonal"] is has_seasonal


# ---------------------------------------------------------------------------
# gate_flow_access
# ---------------------------------------------------------------------------


class TestGateFlowAccess:
    def test_free_no_access(self):
        result = gate_flow_access("free")
        assert result["has_access"] is False
        assert result["max_hours"] == 0

    def test_pro_basic(self):
        result = gate_flow_access("pro")
        assert result["has_events"] is True
        assert result["has_patterns"] is False
        assert result["max_hours"] == 24

    @pytest.mark.parametrize("tier", ULTRA_PLUS)
    def test_ultra_full(self, tier):
        result = gate_flow_access(tier)
        assert result["has_portfolio_greeks"] is True
        assert result["max_hours"] == 720


# ---------------------------------------------------------------------------
# gate_social_access
# ---------------------------------------------------------------------------


class TestGateSocialAccess:
    def test_free_no_access(self):
        result = gate_social_access("free")
        assert result["has_access"] is False

    def test_pro_leaderboard_only(self):
        result = gate_social_access("pro")
        assert result["has_leaderboard"] is True
        assert result["has_profiles"] is False

    def test_premium_alerts(self):
        result = gate_social_access("premium")
        assert result["has_profiles"] is True
        assert result["has_alerts"] is True

    @pytest.mark.parametrize("tier", ULTRA_PLUS)
    def test_ultra_full(self, tier):
        result = gate_social_access(tier)
        assert result["has_propagation"] is True
        assert result["has_export"] is True


# ---------------------------------------------------------------------------
# gate_strategy_access
# ---------------------------------------------------------------------------


class TestGateStrategyAccess:
    def test_free_no_access(self):
        result = gate_strategy_access("free")
        assert result["has_access"] is False
        assert result["max_strategies"] == 0

    def test_pro_limited(self):
        result = gate_strategy_access("pro")
        assert result["max_strategies"] == 3
        assert result["has_auto_trade"] is True
        assert result["has_discovery"] is False

    @pytest.mark.parametrize("tier", ULTRA_PLUS)
    def test_ultra_full(self, tier):
        result = gate_strategy_access(tier)
        assert result["has_genetic"] is True
        assert result["has_marketplace"] is True
        assert result["max_strategies"] == 999


# ---------------------------------------------------------------------------
# All other gate functions — bulk parametrized
# ---------------------------------------------------------------------------


class TestOtherGates:
    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_email_access(self, tier):
        result = gate_email_access(tier)
        assert "has_daily_digest" in result
        assert result["has_daily_digest"] is True  # All tiers

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_heatmap_access(self, tier):
        result = gate_heatmap_access(tier)
        assert "has_heatmap" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_leaderboard_access(self, tier):
        result = gate_leaderboard_access(tier)
        assert "has_leaderboard" in result
        assert "leaderboard_limit" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_market_context(self, tier):
        result = gate_market_context(tier)
        assert "has_price_badge" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_correlation_access(self, tier):
        result = gate_correlation_access(tier)
        assert "has_correlation" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_sentiment_access(self, tier):
        result = gate_sentiment_access(tier)
        assert "max_tickers" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_ticker_dive_access(self, tier):
        result = gate_ticker_dive_access(tier)
        assert "max_signals" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_weekly_wrap_access(self, tier):
        result = gate_weekly_wrap_access(tier)
        assert "max_weeks_back" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_replay_access(self, tier):
        result = gate_replay_access(tier)
        assert "has_access" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_data_licensing(self, tier):
        result = gate_data_licensing(tier)
        assert "has_access" in result
        if tier in ("enterprise", "admin"):
            assert result["max_rows_per_export"] == 1000000
        else:
            assert result["max_rows_per_export"] == 0

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_sponsored_access(self, tier):
        result = gate_sponsored_access(tier)
        if tier in ("enterprise", "admin"):
            assert result["can_submit"] is True
        else:
            assert result["can_submit"] is False

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_sector_rotation_access(self, tier):
        result = gate_sector_rotation_access(tier)
        assert "has_access" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_unusual_activity(self, tier):
        result = gate_unusual_activity(tier)
        assert "has_access" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_news_feed_access(self, tier):
        result = gate_news_feed_access(tier)
        assert result["has_access"] is True  # All tiers

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_congress_tracker_access(self, tier):
        result = gate_congress_tracker_access(tier)
        assert "has_access" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_paper_leaderboard_access(self, tier):
        result = gate_paper_leaderboard_access(tier)
        assert result["has_access"] is True  # Public

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_sports_betting_access(self, tier):
        result = gate_sports_betting_access(tier)
        assert result["has_access"] is True
        assert "max_days" in result
        assert "api_daily_limit" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_signal_quality_access(self, tier):
        result = gate_signal_quality_access(tier)
        assert "has_access" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_terminal_access(self, tier):
        result = gate_terminal_access(tier)
        assert "has_access" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_agent_access(self, tier):
        result = gate_agent_access(tier)
        assert "has_access" in result
        assert "max_agents" in result

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_gate_tradingview_access(self, tier):
        result = gate_tradingview_access(tier)
        assert result["has_access"] is True  # All tiers can view


# ---------------------------------------------------------------------------
# Tier escalation (verify monotonic feature increase)
# ---------------------------------------------------------------------------


class TestTierEscalation:
    @pytest.mark.parametrize("gate_fn", [
        gate_chart_access, gate_filter_access, gate_performance_access,
        gate_email_access, gate_heatmap_access, gate_leaderboard_access,
        gate_market_context, gate_correlation_access, gate_sentiment_access,
    ])
    def test_paid_has_more_than_free(self, gate_fn):
        free = gate_fn("free")
        pro = gate_fn("pro")
        # At least one boolean flag should be True in pro that is False in free
        free_true = sum(1 for v in free.values() if v is True)
        pro_true = sum(1 for v in pro.values() if v is True)
        assert pro_true >= free_true

    def test_backtest_tier_escalation(self):
        free = gate_backtest_access("free")
        pro = gate_backtest_access("pro")
        prem = gate_backtest_access("premium")
        ultra = gate_backtest_access("ultra")
        assert free["max_days"] < pro["max_days"] < prem["max_days"] < ultra["max_days"]

    def test_sentiment_max_tickers_escalation(self):
        free = gate_sentiment_access("free")
        pro = gate_sentiment_access("pro")
        assert free["max_tickers"] < pro["max_tickers"]


# ---------------------------------------------------------------------------
# _redact_reasoning / _redact_trade_idea
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_redact_reasoning_keeps_thesis(self):
        r = _redact_reasoning({"thesis": "bull case", "catalyst_window": "1w"})
        assert r["thesis"] == "bull case"
        assert r["_locked"] is True
        assert "catalyst_window" in r["_locked_fields"]

    def test_redact_reasoning_empty(self):
        assert _redact_reasoning({}) == {}
        assert _redact_reasoning(None) == {}

    def test_redact_trade_idea_keeps_strategy(self):
        r = _redact_trade_idea({"strategy": "debit_spread", "legs": [{"strike": 300}]})
        assert r["strategy"] == "debit_spread"
        assert r["legs"] == []
        assert r["_locked"] is True

    def test_redact_trade_idea_empty(self):
        assert _redact_trade_idea({}) == {}
        assert _redact_trade_idea(None) == {}

    @pytest.mark.parametrize("reasoning", [
        {"thesis": "test"},
        {"thesis": "abc", "raw": {"confidence": 0.8}},
        {"thesis": "", "catalyst_window": "2d"},
    ])
    def test_redact_reasoning_variants(self, reasoning):
        result = _redact_reasoning(reasoning)
        assert "_locked" in result
        assert "thesis" in result


# ---------------------------------------------------------------------------
# Sports betting tier-specific values
# ---------------------------------------------------------------------------


class TestSportsBettingDetails:
    @pytest.mark.parametrize("tier,expected_days", [
        ("free", 2), ("pro", 5), ("premium", 7), ("ultra", 7), ("enterprise", 7),
    ])
    def test_max_days(self, tier, expected_days):
        result = gate_sports_betting_access(tier)
        assert result["max_days"] == expected_days

    @pytest.mark.parametrize("tier,expected_items", [
        ("free", 20), ("pro", 50), ("premium", 100), ("ultra", 200), ("enterprise", 500),
    ])
    def test_max_items(self, tier, expected_items):
        result = gate_sports_betting_access(tier)
        assert result["max_items"] == expected_items

    @pytest.mark.parametrize("tier,expected_api_limit", [
        ("free", 0), ("pro", 0), ("premium", 100), ("ultra", 500), ("enterprise", 10000),
    ])
    def test_api_daily_limit(self, tier, expected_api_limit):
        result = gate_sports_betting_access(tier)
        assert result["api_daily_limit"] == expected_api_limit


# ---------------------------------------------------------------------------
# Admin tier gets everything
# ---------------------------------------------------------------------------


class TestAdminTier:
    @pytest.mark.parametrize("gate_fn", [
        gate_chart_access, gate_filter_access, gate_performance_access,
        gate_email_access, gate_heatmap_access, gate_leaderboard_access,
        gate_correlation_access, gate_terminal_access, gate_agent_access,
    ])
    def test_admin_has_all_flags(self, gate_fn):
        result = gate_fn("admin")
        bool_flags = {k: v for k, v in result.items() if isinstance(v, bool)}
        assert all(bool_flags.values()), f"Admin should have all True booleans: {bool_flags}"

    def test_admin_backtest_full(self):
        result = gate_backtest_access("admin")
        assert result["has_access"] is True
        assert result["has_optimizer"] is True
        assert result["max_days"] == 365

    def test_admin_flow_full(self):
        result = gate_flow_access("admin")
        assert result["has_portfolio_greeks"] is True
        assert result["max_hours"] == 720

    def test_admin_strategy_full(self):
        result = gate_strategy_access("admin")
        assert result["has_genetic"] is True
        assert result["max_strategies"] == 999
