"""
Test suite for tier gating module - comprehensive coverage of all 35+ gate functions (Work Stream 4).

Covers:
- gate_signal() - Signal delay, redaction
- gate_signal_list() - Signal list with page limits
- gate_chart_access() - Chart features by tier
- gate_filter_access() - Date range, confidence, filters
- gate_performance_access() - Analytics depth
- gate_email_access() - Alert types
- gate_heatmap_access() - Sentiment heatmap
- gate_leaderboard_access() - Leaderboard features
- gate_market_context() - Market data depth
- gate_correlation_access() - Correlation features
- gate_sentiment_access() - Sentiment analysis depth
- gate_ticker_dive_access() - Ticker deep dive
- gate_weekly_wrap_access() - Weekly summaries
- gate_replay_access() - Signal replay
- gate_data_licensing() - Enterprise data export
- gate_sponsored_access() - Enterprise sponsored signals
- gate_sector_rotation_access() - Sector analysis
- gate_unusual_activity() - Unusual options activity
- gate_news_feed_access() - News feed depth
- gate_congress_tracker_access() - Congressional trading
- gate_paper_leaderboard_access() - Paper trading leaderboard
- gate_sports_betting_access() - Sports betting intel
- gate_signal_quality_access() - Signal quality analytics dashboard
- gate_backtest_access() - Backtest engine features
- gate_macro_access() - Macro events calendar
- gate_terminal_access() - Bloomberg-lite terminal
- gate_agent_access() - Autonomous trading agents
- gate_flow_access() - Options flow intelligence
- gate_social_access() - Social intelligence network
- gate_strategy_access() - Strategy builder

All functions tested across all 6 tiers: free, pro, premium, ultra, enterprise, admin
Admin tier should bypass all restrictions and get enterprise-level or better access.
"""

import time

import pytest

from rot.web.tier_gate import (
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
    gate_unusual_activity,
    gate_weekly_wrap_access,
)


class TestGateSignal:
    """Test gate_signal() function across all tiers."""

    def test_free_tier_delayed_signal(self):
        """Free tier: signals newer than 900s are delayed and heavily redacted."""
        signal = {
            "id": "sig1",
            "created_at": time.time() - 300,  # 5 minutes ago (< 15 min delay)
            "strategy": "debit_spread",
            "reasoning": {"thesis": "Test thesis", "catalyst_window": "1w"},
            "trade_idea": {"strategy": "debit_spread", "legs": [{"side": "buy"}]},
        }

        result = gate_signal(signal, "free", delay_s=900)

        assert result["_delayed"] is True
        assert result["_available_in_s"] > 0
        assert result["reasoning"]["_locked"] is True
        assert "Upgrade to Pro" in result["reasoning"]["_upgrade_message"]
        assert result["trade_idea"]["_locked"] is True
        assert result["trade_idea"]["legs"] == []

    def test_free_tier_old_signal_redacted(self):
        """Free tier: signals older than delay_s are available but redacted."""
        signal = {
            "id": "sig1",
            "created_at": time.time() - 1000,  # > 900s ago
            "strategy": "debit_spread",
            "reasoning": {
                "thesis": "Test thesis",
                "catalyst_window": "1w",
                "invalidations": ["price < 100"],
            },
            "trade_idea": {
                "strategy": "debit_spread",
                "legs": [{"side": "buy", "strike": 100}],
            },
        }

        result = gate_signal(signal, "free", delay_s=900)

        assert "_delayed" not in result
        # Reasoning redacted but thesis visible
        assert result["reasoning"]["thesis"] == "Test thesis"
        assert result["reasoning"]["_locked"] is True
        # Trade legs removed
        assert result["trade_idea"]["legs"] == []
        assert result["trade_idea"]["_locked"] is True

    def test_pro_tier_full_access(self):
        """Pro tier gets full signal with no delay or redaction."""
        signal = {
            "id": "sig1",
            "created_at": time.time(),
            "reasoning": {"thesis": "Test", "invalidations": ["x"]},
            "trade_idea": {"legs": [{"side": "buy"}]},
        }

        result = gate_signal(signal, "pro")

        assert result == signal  # No modifications

    def test_premium_tier_full_access(self):
        """Premium tier gets full signal."""
        signal = {"id": "sig1", "created_at": time.time()}
        result = gate_signal(signal, "premium")
        assert result == signal

    def test_ultra_tier_full_access(self):
        """Ultra tier gets full signal."""
        signal = {"id": "sig1", "created_at": time.time()}
        result = gate_signal(signal, "ultra")
        assert result == signal

    def test_enterprise_tier_full_access(self):
        """Enterprise tier gets full signal."""
        signal = {"id": "sig1", "created_at": time.time()}
        result = gate_signal(signal, "enterprise")
        assert result == signal

    def test_admin_tier_full_access(self):
        """Admin tier gets full signal (bypasses all restrictions)."""
        signal = {"id": "sig1", "created_at": time.time()}
        result = gate_signal(signal, "admin")
        assert result == signal


class TestGateSignalList:
    """Test gate_signal_list() function across all tiers."""

    def test_free_tier_page_limit(self):
        """Free tier enforces page limit (default 10)."""
        signals = [{"id": f"sig{i}", "created_at": time.time()} for i in range(50)]

        result = gate_signal_list(signals, "free", page_limit=10)

        assert len(result) == 10
        assert result[0]["id"] == "sig0"
        assert result[-1]["id"] == "sig9"

    def test_pro_tier_no_page_limit(self):
        """Pro tier gets all signals without page limit."""
        signals = [{"id": f"sig{i}", "created_at": time.time()} for i in range(50)]

        result = gate_signal_list(signals, "pro")

        assert len(result) == 50

    def test_admin_tier_no_page_limit(self):
        """Admin tier gets all signals."""
        signals = [{"id": f"sig{i}", "created_at": time.time()} for i in range(50)]

        result = gate_signal_list(signals, "admin")

        assert len(result) == 50


class TestGateChartAccess:
    """Test gate_chart_access() function across all tiers."""

    def test_free_tier(self):
        """Free tier: no chart features."""
        result = gate_chart_access("free")

        assert result["has_quadrant"] is False
        assert result["has_timeline"] is False
        assert result["has_strategy_breakdown"] is False
        assert result["has_realtime_badge"] is False
        assert result["has_custom_time_range"] is False
        assert result["has_chart_export"] is False
        assert result["chart_hours"] == 0
        assert result["chart_limit"] == 0

    def test_pro_tier(self):
        """Pro tier: basic charts (24h, 50 signals)."""
        result = gate_chart_access("pro")

        assert result["has_quadrant"] is True
        assert result["has_timeline"] is True
        assert result["has_strategy_breakdown"] is False
        assert result["has_realtime_badge"] is False
        assert result["has_custom_time_range"] is False
        assert result["has_chart_export"] is False
        assert result["chart_hours"] == 24
        assert result["chart_limit"] == 50

    def test_premium_tier(self):
        """Premium tier: + strategy breakdown (48h, 100 signals)."""
        result = gate_chart_access("premium")

        assert result["has_quadrant"] is True
        assert result["has_timeline"] is True
        assert result["has_strategy_breakdown"] is True
        assert result["has_realtime_badge"] is False
        assert result["has_custom_time_range"] is False
        assert result["has_chart_export"] is False
        assert result["chart_hours"] == 48
        assert result["chart_limit"] == 100

    def test_ultra_tier(self):
        """Ultra tier: + realtime badge, custom time range, export."""
        result = gate_chart_access("ultra")

        assert result["has_quadrant"] is True
        assert result["has_timeline"] is True
        assert result["has_strategy_breakdown"] is True
        assert result["has_realtime_badge"] is True
        assert result["has_custom_time_range"] is True
        assert result["has_chart_export"] is True
        assert result["chart_hours"] == 48
        assert result["chart_limit"] == 100

    def test_enterprise_tier(self):
        """Enterprise tier: full access."""
        result = gate_chart_access("enterprise")

        assert result["has_quadrant"] is True
        assert result["has_realtime_badge"] is True
        assert result["has_custom_time_range"] is True
        assert result["has_chart_export"] is True

    def test_admin_tier(self):
        """Admin tier: full access (bypasses restrictions)."""
        result = gate_chart_access("admin")

        assert result["has_quadrant"] is True
        assert result["has_realtime_badge"] is True
        assert result["has_custom_time_range"] is True
        assert result["has_chart_export"] is True
        assert result["chart_hours"] == 48
        assert result["chart_limit"] == 100


class TestGateFilterAccess:
    """Test gate_filter_access() function across all tiers."""

    def test_free_tier(self):
        """Free tier: confidence filter only."""
        result = gate_filter_access("free")

        assert result["has_date_range"] is False
        assert result["has_confidence_range"] is True
        assert result["has_ticker_filter"] is False
        assert result["has_stance_filter"] is False
        assert result["has_source_filter"] is False
        assert result["has_saved_presets"] is False
        assert result["max_presets"] == 0

    def test_pro_tier(self):
        """Pro tier: + ticker/stance/source filters."""
        result = gate_filter_access("pro")

        assert result["has_date_range"] is False
        assert result["has_confidence_range"] is True
        assert result["has_ticker_filter"] is True
        assert result["has_stance_filter"] is True
        assert result["has_source_filter"] is True
        assert result["has_saved_presets"] is False

    def test_premium_tier(self):
        """Premium tier: + date range."""
        result = gate_filter_access("premium")

        assert result["has_date_range"] is True
        assert result["has_ticker_filter"] is True
        assert result["has_saved_presets"] is False

    def test_ultra_tier(self):
        """Ultra tier: + saved presets."""
        result = gate_filter_access("ultra")

        assert result["has_date_range"] is True
        assert result["has_saved_presets"] is True
        assert result["max_presets"] == 10

    def test_admin_tier(self):
        """Admin tier: full filter access."""
        result = gate_filter_access("admin")

        assert result["has_date_range"] is True
        assert result["has_saved_presets"] is True
        assert result["max_presets"] == 10


class TestGatePerformanceAccess:
    """Test gate_performance_access() function across all tiers."""

    def test_free_tier(self):
        """Free tier: limited to 7 days, no advanced analytics."""
        result = gate_performance_access("free")

        assert result["has_aggregate_accuracy"] is False
        assert result["has_per_signal_pnl"] is False
        assert result["has_roi_history_chart"] is False
        assert result["has_performance_export"] is False
        assert result["has_performance_dashboard"] is False
        assert result["has_strategy_pnl"] is False
        assert result["has_accuracy_breakdown"] is False
        assert result["has_confidence_calibration"] is False
        assert result["has_post_mortem"] is False
        assert result["accuracy_days"] == 7

    def test_pro_tier(self):
        """Pro tier: aggregate accuracy, breakdowns (30 days)."""
        result = gate_performance_access("pro")

        assert result["has_aggregate_accuracy"] is True
        assert result["has_per_signal_pnl"] is True
        assert result["has_roi_history_chart"] is False
        assert result["has_performance_dashboard"] is False
        assert result["has_strategy_pnl"] is False
        assert result["has_accuracy_breakdown"] is True
        assert result["has_confidence_calibration"] is True
        assert result["has_post_mortem"] is False
        assert result["accuracy_days"] == 30

    def test_premium_tier(self):
        """Premium tier: + ROI history, dashboard, post mortem (90 days)."""
        result = gate_performance_access("premium")

        assert result["has_aggregate_accuracy"] is True
        assert result["has_roi_history_chart"] is True
        assert result["has_performance_dashboard"] is True
        assert result["has_post_mortem"] is True
        assert result["has_strategy_pnl"] is False
        assert result["has_performance_export"] is False
        assert result["accuracy_days"] == 90

    def test_ultra_tier(self):
        """Ultra tier: + strategy P&L, export (365 days)."""
        result = gate_performance_access("ultra")

        assert result["has_performance_export"] is True
        assert result["has_strategy_pnl"] is True
        assert result["accuracy_days"] == 365

    def test_admin_tier(self):
        """Admin tier: full performance analytics."""
        result = gate_performance_access("admin")

        assert result["has_strategy_pnl"] is True
        assert result["has_performance_export"] is True
        assert result["accuracy_days"] == 365


class TestGateBacktestAccess:
    """Test gate_backtest_access() function across all tiers."""

    def test_free_tier_no_access(self):
        """Free tier: no backtest access."""
        result = gate_backtest_access("free")

        assert result["has_access"] is False
        assert result["has_basic"] is False
        assert result["has_monte_carlo"] is False
        assert result["has_walk_forward"] is False
        assert result["has_risk_metrics"] is False
        assert result["has_benchmark"] is False
        assert result["has_optimizer"] is False
        assert result["has_comparison"] is False
        assert result["has_saved_strategies"] is False
        assert result["has_export"] is False
        assert result["max_days"] == 0
        assert result["max_signals"] == 0
        assert result["position_size_modes"] == []

    def test_pro_tier_basic(self):
        """Pro tier: basic backtest (30d, 200 signals, fixed_pct only)."""
        result = gate_backtest_access("pro")

        assert result["has_access"] is True
        assert result["has_basic"] is True
        assert result["has_monte_carlo"] is False
        assert result["has_walk_forward"] is False
        assert result["has_risk_metrics"] is False
        assert result["has_benchmark"] is False
        assert result["has_optimizer"] is False
        assert result["has_comparison"] is False
        assert result["has_saved_strategies"] is False
        assert result["has_export"] is False
        assert result["max_days"] == 30
        assert result["max_signals"] == 200
        assert result["position_size_modes"] == ["fixed_pct"]

    def test_premium_tier_advanced(self):
        """Premium tier: + MC, walk-forward, risk, benchmark (90d, 1000 signals)."""
        result = gate_backtest_access("premium")

        assert result["has_access"] is True
        assert result["has_basic"] is True
        assert result["has_monte_carlo"] is True
        assert result["has_walk_forward"] is True
        assert result["has_risk_metrics"] is True
        assert result["has_benchmark"] is True
        assert result["has_optimizer"] is False
        assert result["has_comparison"] is False
        assert result["has_saved_strategies"] is False
        assert result["has_export"] is False
        assert result["max_days"] == 90
        assert result["max_signals"] == 1000
        assert "fixed_pct" in result["position_size_modes"]
        assert "confidence_weighted" in result["position_size_modes"]

    def test_ultra_tier_full(self):
        """Ultra tier: + optimizer, comparison, saved strategies, export (365d, 5000 signals)."""
        result = gate_backtest_access("ultra")

        assert result["has_access"] is True
        assert result["has_basic"] is True
        assert result["has_monte_carlo"] is True
        assert result["has_walk_forward"] is True
        assert result["has_risk_metrics"] is True
        assert result["has_benchmark"] is True
        assert result["has_optimizer"] is True
        assert result["has_comparison"] is True
        assert result["has_saved_strategies"] is True
        assert result["has_export"] is True
        assert result["max_days"] == 365
        assert result["max_signals"] == 5000
        assert "kelly" in result["position_size_modes"]

    def test_admin_tier_full(self):
        """Admin tier: full backtest features."""
        result = gate_backtest_access("admin")

        assert result["has_optimizer"] is True
        assert result["has_export"] is True
        assert result["max_signals"] == 5000


class TestGateMacroAccess:
    """Test gate_macro_access() function across all tiers."""

    def test_free_tier_limited_calendar(self):
        """Free tier: next 3 events only, no earnings/insider/FOMC."""
        result = gate_macro_access("free")

        assert result["has_access"] is True
        assert result["has_calendar"] is True
        assert result["has_earnings"] is False
        assert result["has_insider"] is False
        assert result["has_fomc"] is False
        assert result["has_seasonal"] is False
        assert result["has_impact"] is False
        assert result["has_iv_crush"] is False
        assert result["has_statement_diff"] is False
        assert result["has_cross_reference"] is False
        assert result["has_strategy_recommend"] is False
        assert result["has_export"] is False
        assert result["calendar_max_days"] == 3
        assert result["calendar_max_events"] == 5
        assert result["history_max_days"] == 0

    def test_pro_tier_basic(self):
        """Pro tier: 7d calendar, basic earnings/insider/FOMC."""
        result = gate_macro_access("pro")

        assert result["has_access"] is True
        assert result["has_calendar"] is True
        assert result["has_earnings"] is True
        assert result["has_insider"] is True
        assert result["has_fomc"] is True
        assert result["has_seasonal"] is False
        assert result["has_impact"] is False
        assert result["has_iv_crush"] is False
        assert result["has_statement_diff"] is False
        assert result["has_cross_reference"] is False
        assert result["has_strategy_recommend"] is False
        assert result["has_export"] is False
        assert result["calendar_max_days"] == 7
        assert result["calendar_max_events"] == 50
        assert result["history_max_days"] == 30

    def test_premium_tier_analytics(self):
        """Premium tier: + impact, IV crush, seasonal, strategy (30d, 200 events)."""
        result = gate_macro_access("premium")

        assert result["has_access"] is True
        assert result["has_earnings"] is True
        assert result["has_fomc"] is True
        assert result["has_seasonal"] is True
        assert result["has_impact"] is True
        assert result["has_iv_crush"] is True
        assert result["has_statement_diff"] is True
        assert result["has_cross_reference"] is False
        assert result["has_strategy_recommend"] is True
        assert result["has_export"] is False
        assert result["calendar_max_days"] == 30
        assert result["calendar_max_events"] == 200
        assert result["history_max_days"] == 90

    def test_ultra_tier_full(self):
        """Ultra tier: + cross-reference, export (90d, 500 events, 365d history)."""
        result = gate_macro_access("ultra")

        assert result["has_access"] is True
        assert result["has_cross_reference"] is True
        assert result["has_export"] is True
        assert result["calendar_max_days"] == 90
        assert result["calendar_max_events"] == 500
        assert result["history_max_days"] == 365

    def test_admin_tier_full(self):
        """Admin tier: full macro features."""
        result = gate_macro_access("admin")

        assert result["has_export"] is True
        assert result["has_cross_reference"] is True
        assert result["calendar_max_days"] == 90


class TestGateTerminalAccess:
    """Test gate_terminal_access() function across all tiers."""

    def test_free_tier_no_access(self):
        """Free tier: no terminal access."""
        result = gate_terminal_access("free")

        assert result["has_access"] is False
        assert result["has_options_flow"] is False
        assert result["has_news_wire"] is False
        assert result["has_watchlist_alerts"] is False
        assert result["has_heatmap"] is False
        assert result["refresh_interval_s"] == 0
        assert result["max_signals_feed"] == 0

    def test_pro_tier_no_access(self):
        """Pro tier: no terminal access."""
        result = gate_terminal_access("pro")

        assert result["has_access"] is False
        assert result["refresh_interval_s"] == 0

    def test_premium_tier_basic(self):
        """Premium tier: terminal access (60s refresh, 25 signals, no flow/alerts)."""
        result = gate_terminal_access("premium")

        assert result["has_access"] is True
        assert result["has_options_flow"] is False
        assert result["has_news_wire"] is True
        assert result["has_watchlist_alerts"] is False
        assert result["has_heatmap"] is True
        assert result["refresh_interval_s"] == 60
        assert result["max_signals_feed"] == 25

    def test_ultra_tier_full(self):
        """Ultra tier: + flow, alerts (30s refresh, 50 signals)."""
        result = gate_terminal_access("ultra")

        assert result["has_access"] is True
        assert result["has_options_flow"] is True
        assert result["has_news_wire"] is True
        assert result["has_watchlist_alerts"] is True
        assert result["has_heatmap"] is True
        assert result["refresh_interval_s"] == 30
        assert result["max_signals_feed"] == 50

    def test_admin_tier_full(self):
        """Admin tier: full terminal access."""
        result = gate_terminal_access("admin")

        assert result["has_access"] is True
        assert result["has_options_flow"] is True
        assert result["has_watchlist_alerts"] is True
        assert result["refresh_interval_s"] == 30


class TestGateAgentAccess:
    """Test gate_agent_access() function across all tiers."""

    def test_free_tier_no_access(self):
        """Free tier: no agent access."""
        result = gate_agent_access("free")

        assert result["has_access"] is False
        assert result["max_agents"] == 0
        assert result["has_signal_follower"] is False
        assert result["has_contrarian"] is False
        assert result["has_momentum_rider"] is False
        assert result["has_custom_rules"] is False
        assert result["has_performance_export"] is False
        assert result["has_api"] is False

    def test_pro_tier_no_access(self):
        """Pro tier: no agent access."""
        result = gate_agent_access("pro")

        assert result["has_access"] is False
        assert result["max_agents"] == 0

    def test_premium_tier_no_access(self):
        """Premium tier: no agent access."""
        result = gate_agent_access("premium")

        assert result["has_access"] is False
        assert result["max_agents"] == 0

    def test_ultra_tier_basic(self):
        """Ultra tier: 3 agents (follower, contrarian, momentum)."""
        result = gate_agent_access("ultra")

        assert result["has_access"] is True
        assert result["max_agents"] == 3
        assert result["has_signal_follower"] is True
        assert result["has_contrarian"] is True
        assert result["has_momentum_rider"] is True
        assert result["has_custom_rules"] is False
        assert result["has_performance_export"] is False
        assert result["has_api"] is False

    def test_enterprise_tier_full(self):
        """Enterprise tier: 10 agents + custom rules + export + API."""
        result = gate_agent_access("enterprise")

        assert result["has_access"] is True
        assert result["max_agents"] == 10
        assert result["has_signal_follower"] is True
        assert result["has_contrarian"] is True
        assert result["has_momentum_rider"] is True
        assert result["has_custom_rules"] is True
        assert result["has_performance_export"] is True
        assert result["has_api"] is True

    def test_admin_tier_full(self):
        """Admin tier: full agent access."""
        result = gate_agent_access("admin")

        assert result["has_access"] is True
        assert result["max_agents"] == 10
        assert result["has_custom_rules"] is True
        assert result["has_api"] is True


class TestGateFlowAccess:
    """Test gate_flow_access() function across all tiers."""

    def test_free_tier_no_access(self):
        """Free tier: no flow access."""
        result = gate_flow_access("free")

        assert result["has_access"] is False
        assert result["has_events"] is False
        assert result["has_patterns"] is False
        assert result["has_convergences"] is False
        assert result["has_greeks"] is False
        assert result["has_portfolio_greeks"] is False
        assert result["has_export"] is False
        assert result["max_hours"] == 0

    def test_pro_tier_basic(self):
        """Pro tier: events + convergence (24h)."""
        result = gate_flow_access("pro")

        assert result["has_access"] is True
        assert result["has_events"] is True
        assert result["has_patterns"] is False
        assert result["has_convergences"] is True
        assert result["has_greeks"] is False
        assert result["has_portfolio_greeks"] is False
        assert result["has_export"] is False
        assert result["max_hours"] == 24

    def test_premium_tier_patterns(self):
        """Premium tier: + patterns, Greeks (7d)."""
        result = gate_flow_access("premium")

        assert result["has_access"] is True
        assert result["has_events"] is True
        assert result["has_patterns"] is True
        assert result["has_convergences"] is True
        assert result["has_greeks"] is True
        assert result["has_portfolio_greeks"] is False
        assert result["has_export"] is False
        assert result["max_hours"] == 168

    def test_ultra_tier_full(self):
        """Ultra tier: + portfolio Greeks, export (30d)."""
        result = gate_flow_access("ultra")

        assert result["has_access"] is True
        assert result["has_events"] is True
        assert result["has_patterns"] is True
        assert result["has_convergences"] is True
        assert result["has_greeks"] is True
        assert result["has_portfolio_greeks"] is True
        assert result["has_export"] is True
        assert result["max_hours"] == 720

    def test_admin_tier_full(self):
        """Admin tier: full flow access."""
        result = gate_flow_access("admin")

        assert result["has_access"] is True
        assert result["has_portfolio_greeks"] is True
        assert result["has_export"] is True
        assert result["max_hours"] == 720


class TestGateSocialAccess:
    """Test gate_social_access() function across all tiers."""

    def test_free_tier_no_access(self):
        """Free tier: no social intelligence access."""
        result = gate_social_access("free")

        assert result["has_access"] is False
        assert result["has_leaderboard"] is False
        assert result["has_profiles"] is False
        assert result["has_alerts"] is False
        assert result["has_propagation"] is False
        assert result["has_contrarian"] is False
        assert result["has_export"] is False

    def test_pro_tier_leaderboard_only(self):
        """Pro tier: leaderboard only."""
        result = gate_social_access("pro")

        assert result["has_access"] is True
        assert result["has_leaderboard"] is True
        assert result["has_profiles"] is False
        assert result["has_alerts"] is False
        assert result["has_propagation"] is False
        assert result["has_contrarian"] is False
        assert result["has_export"] is False

    def test_premium_tier_profiles_alerts(self):
        """Premium tier: + profiles, manipulation alerts."""
        result = gate_social_access("premium")

        assert result["has_access"] is True
        assert result["has_leaderboard"] is True
        assert result["has_profiles"] is True
        assert result["has_alerts"] is True
        assert result["has_propagation"] is False
        assert result["has_contrarian"] is False
        assert result["has_export"] is False

    def test_ultra_tier_full(self):
        """Ultra tier: + propagation, contrarian, export."""
        result = gate_social_access("ultra")

        assert result["has_access"] is True
        assert result["has_leaderboard"] is True
        assert result["has_profiles"] is True
        assert result["has_alerts"] is True
        assert result["has_propagation"] is True
        assert result["has_contrarian"] is True
        assert result["has_export"] is True

    def test_admin_tier_full(self):
        """Admin tier: full social intelligence."""
        result = gate_social_access("admin")

        assert result["has_access"] is True
        assert result["has_propagation"] is True
        assert result["has_contrarian"] is True
        assert result["has_export"] is True


class TestGateStrategyAccess:
    """Test gate_strategy_access() function across all tiers."""

    def test_free_tier_no_access(self):
        """Free tier: no strategy builder access."""
        result = gate_strategy_access("free")

        assert result["has_access"] is False
        assert result["max_strategies"] == 0
        assert result["has_discovery"] is False
        assert result["has_ml_optimize"] is False
        assert result["has_genetic"] is False
        assert result["has_marketplace"] is False
        assert result["has_auto_trade"] is False
        assert result["has_regimes"] is False
        assert result["has_export"] is False

    def test_pro_tier_manual_only(self):
        """Pro tier: 3 manual strategies, auto-trade."""
        result = gate_strategy_access("pro")

        assert result["has_access"] is True
        assert result["max_strategies"] == 3
        assert result["has_discovery"] is False
        assert result["has_ml_optimize"] is False
        assert result["has_genetic"] is False
        assert result["has_marketplace"] is False
        assert result["has_auto_trade"] is True
        assert result["has_regimes"] is False
        assert result["has_export"] is False

    def test_premium_tier_discovery_ml(self):
        """Premium tier: 10 strategies + discovery + ML + regimes."""
        result = gate_strategy_access("premium")

        assert result["has_access"] is True
        assert result["max_strategies"] == 10
        assert result["has_discovery"] is True
        assert result["has_ml_optimize"] is True
        assert result["has_genetic"] is False
        assert result["has_marketplace"] is False
        assert result["has_auto_trade"] is True
        assert result["has_regimes"] is True
        assert result["has_export"] is False

    def test_ultra_tier_full(self):
        """Ultra tier: unlimited strategies + genetic + marketplace + export."""
        result = gate_strategy_access("ultra")

        assert result["has_access"] is True
        assert result["max_strategies"] == 999
        assert result["has_discovery"] is True
        assert result["has_ml_optimize"] is True
        assert result["has_genetic"] is True
        assert result["has_marketplace"] is True
        assert result["has_auto_trade"] is True
        assert result["has_regimes"] is True
        assert result["has_export"] is True

    def test_admin_tier_full(self):
        """Admin tier: full strategy builder access."""
        result = gate_strategy_access("admin")

        assert result["has_access"] is True
        assert result["max_strategies"] == 999
        assert result["has_genetic"] is True
        assert result["has_marketplace"] is True
        assert result["has_export"] is True


class TestRemainingGateFunctions:
    """Test remaining gate functions across all tiers."""

    # Email access
    def test_gate_email_access_all_tiers(self):
        """Test email access across all tiers."""
        # Free: digest only
        free_result = gate_email_access("free")
        assert free_result["has_daily_digest"] is True
        assert free_result["has_realtime_email"] is False
        assert free_result["has_custom_filters"] is False
        assert free_result["has_webhook"] is False

        # Pro: + realtime
        pro_result = gate_email_access("pro")
        assert pro_result["has_realtime_email"] is True
        assert pro_result["has_custom_filters"] is False

        # Premium: + custom filters
        premium_result = gate_email_access("premium")
        assert premium_result["has_custom_filters"] is True
        assert premium_result["has_webhook"] is False

        # Ultra: + webhook
        ultra_result = gate_email_access("ultra")
        assert ultra_result["has_webhook"] is True

        # Admin: full access
        admin_result = gate_email_access("admin")
        assert admin_result["has_webhook"] is True

    # Heatmap access
    def test_gate_heatmap_access_all_tiers(self):
        """Test heatmap access across all tiers."""
        # Free: no access
        free_result = gate_heatmap_access("free")
        assert free_result["has_heatmap"] is False
        assert free_result["has_drill_down"] is False
        assert free_result["has_historical_replay"] is False

        # Pro: basic heatmap
        pro_result = gate_heatmap_access("pro")
        assert pro_result["has_heatmap"] is True
        assert pro_result["has_drill_down"] is False

        # Premium: + drill down
        premium_result = gate_heatmap_access("premium")
        assert premium_result["has_drill_down"] is True
        assert premium_result["has_historical_replay"] is False

        # Ultra: + historical replay
        ultra_result = gate_heatmap_access("ultra")
        assert ultra_result["has_historical_replay"] is True

        # Admin: full access
        admin_result = gate_heatmap_access("admin")
        assert admin_result["has_historical_replay"] is True

    # Leaderboard access
    def test_gate_leaderboard_access_all_tiers(self):
        """Test leaderboard access across all tiers."""
        # Free: no access
        free_result = gate_leaderboard_access("free")
        assert free_result["has_leaderboard"] is False
        assert free_result["leaderboard_limit"] == 0

        # Pro: basic leaderboard (20 entries)
        pro_result = gate_leaderboard_access("pro")
        assert pro_result["has_leaderboard"] is True
        assert pro_result["leaderboard_limit"] == 20
        assert pro_result["has_sorting"] is True
        assert pro_result["has_historical"] is False
        assert pro_result["has_performance_column"] is False

        # Premium: + historical, performance column
        premium_result = gate_leaderboard_access("premium")
        assert premium_result["has_historical"] is True
        assert premium_result["has_performance_column"] is True
        assert premium_result["has_custom_range"] is False

        # Ultra: + custom range, export
        ultra_result = gate_leaderboard_access("ultra")
        assert ultra_result["has_custom_range"] is True
        assert ultra_result["has_leaderboard_export"] is True

        # Admin: full access
        admin_result = gate_leaderboard_access("admin")
        assert admin_result["has_leaderboard_export"] is True

    # Market context
    def test_gate_market_context_all_tiers(self):
        """Test market context across all tiers."""
        # Free: no badge
        free_result = gate_market_context("free")
        assert free_result["has_price_badge"] is False
        assert free_result["has_extended_market"] is False
        assert free_result["has_options_chain"] is False

        # Pro: + price badge
        pro_result = gate_market_context("pro")
        assert pro_result["has_price_badge"] is True
        assert pro_result["has_extended_market"] is False

        # Premium: + extended market
        premium_result = gate_market_context("premium")
        assert premium_result["has_extended_market"] is True
        assert premium_result["has_options_chain"] is False

        # Ultra: + options chain
        ultra_result = gate_market_context("ultra")
        assert ultra_result["has_options_chain"] is True

        # Admin: full access
        admin_result = gate_market_context("admin")
        assert admin_result["has_options_chain"] is True

    # Correlation, sentiment, ticker dive, weekly wrap, replay
    def test_gate_correlation_access_all_tiers(self):
        """Test correlation access across all tiers."""
        assert gate_correlation_access("free")["has_correlation"] is False
        assert gate_correlation_access("pro")["has_correlation"] is True
        assert gate_correlation_access("pro")["has_strength_scores"] is False
        assert gate_correlation_access("premium")["has_strength_scores"] is True
        assert gate_correlation_access("ultra")["has_matrix_export"] is True
        assert gate_correlation_access("admin")["has_matrix_export"] is True

    def test_gate_sentiment_access_all_tiers(self):
        """Test sentiment access across all tiers."""
        free_result = gate_sentiment_access("free")
        assert free_result["max_tickers"] == 3
        assert free_result["max_hours"] == 12
        assert free_result["has_drill_down"] is False

        pro_result = gate_sentiment_access("pro")
        assert pro_result["max_tickers"] == 50
        assert pro_result["max_hours"] == 168
        assert pro_result["has_drill_down"] is True

        premium_result = gate_sentiment_access("premium")
        assert premium_result["has_sector_group"] is True
        assert premium_result["has_export"] is True

        admin_result = gate_sentiment_access("admin")
        assert admin_result["max_hours"] == 2160

    def test_gate_ticker_dive_access_all_tiers(self):
        """Test ticker dive across all tiers."""
        free_result = gate_ticker_dive_access("free")
        assert free_result["max_signals"] == 5
        assert free_result["has_chart"] is False

        pro_result = gate_ticker_dive_access("pro")
        assert pro_result["max_signals"] == 50
        assert pro_result["has_chart"] is True

        premium_result = gate_ticker_dive_access("premium")
        assert premium_result["max_signals"] == 100
        assert premium_result["has_performance"] is True

        ultra_result = gate_ticker_dive_access("ultra")
        assert ultra_result["max_signals"] == 9999
        assert ultra_result["has_export"] is True

        admin_result = gate_ticker_dive_access("admin")
        assert admin_result["has_export"] is True

    def test_gate_weekly_wrap_access_all_tiers(self):
        """Test weekly wrap across all tiers."""
        assert gate_weekly_wrap_access("free")["max_weeks_back"] == 1
        assert gate_weekly_wrap_access("pro")["max_weeks_back"] == 4
        assert gate_weekly_wrap_access("premium")["max_weeks_back"] == 12
        assert gate_weekly_wrap_access("ultra")["max_weeks_back"] == 52
        assert gate_weekly_wrap_access("admin")["max_weeks_back"] == 52

    def test_gate_replay_access_all_tiers(self):
        """Test replay access across all tiers."""
        free_result = gate_replay_access("free")
        assert free_result["has_access"] is False
        assert free_result["max_hours"] == 0

        pro_result = gate_replay_access("pro")
        assert pro_result["has_access"] is True
        assert pro_result["max_hours"] == 24
        assert pro_result["has_price_overlay"] is False

        premium_result = gate_replay_access("premium")
        assert premium_result["max_hours"] == 168
        assert premium_result["has_price_overlay"] is True

        ultra_result = gate_replay_access("ultra")
        assert ultra_result["max_hours"] == 720
        assert ultra_result["has_export"] is True

        admin_result = gate_replay_access("admin")
        assert admin_result["has_export"] is True

    # Enterprise gates
    def test_gate_data_licensing_all_tiers(self):
        """Test data licensing across all tiers."""
        free_result = gate_data_licensing("free")
        assert free_result["has_access"] is False
        assert free_result["max_rows_per_export"] == 0

        pro_result = gate_data_licensing("pro")
        assert pro_result["has_access"] is False

        enterprise_result = gate_data_licensing("enterprise")
        assert enterprise_result["has_access"] is True
        assert enterprise_result["has_full_history"] is True
        assert enterprise_result["max_rows_per_export"] == 1000000

        admin_result = gate_data_licensing("admin")
        assert admin_result["has_access"] is True

    def test_gate_sponsored_access_all_tiers(self):
        """Test sponsored signal access across all tiers."""
        free_result = gate_sponsored_access("free")
        assert free_result["can_submit"] is False
        assert free_result["max_pending"] == 0

        pro_result = gate_sponsored_access("pro")
        assert pro_result["can_submit"] is False

        enterprise_result = gate_sponsored_access("enterprise")
        assert enterprise_result["can_submit"] is True
        assert enterprise_result["max_pending"] == 10

        admin_result = gate_sponsored_access("admin")
        assert admin_result["can_submit"] is True

    # Other feature gates
    def test_gate_sector_rotation_access_all_tiers(self):
        """Test sector rotation across all tiers."""
        free_result = gate_sector_rotation_access("free")
        assert free_result["has_access"] is False
        assert free_result["max_days"] == 0

        pro_result = gate_sector_rotation_access("pro")
        assert pro_result["has_access"] is True
        assert pro_result["max_days"] == 30
        assert pro_result["has_performance_overlay"] is False

        premium_result = gate_sector_rotation_access("premium")
        assert premium_result["has_performance_overlay"] is True
        assert premium_result["max_days"] == 30

        ultra_result = gate_sector_rotation_access("ultra")
        assert ultra_result["max_days"] == 90
        assert ultra_result["has_export"] is True

        admin_result = gate_sector_rotation_access("admin")
        assert admin_result["has_export"] is True

    def test_gate_unusual_activity_all_tiers(self):
        """Test unusual activity across all tiers."""
        free_result = gate_unusual_activity("free")
        assert free_result["has_access"] is False
        assert free_result["max_hours"] == 0

        pro_result = gate_unusual_activity("pro")
        assert pro_result["has_access"] is True
        assert pro_result["max_hours"] == 24
        assert pro_result["has_detail"] is False

        premium_result = gate_unusual_activity("premium")
        assert premium_result["max_hours"] == 48
        assert premium_result["has_detail"] is True
        assert premium_result["has_history"] is False

        ultra_result = gate_unusual_activity("ultra")
        assert ultra_result["max_hours"] == 168
        assert ultra_result["has_history"] is True

        enterprise_result = gate_unusual_activity("enterprise")
        assert enterprise_result["max_hours"] == 720

        admin_result = gate_unusual_activity("admin")
        assert admin_result["max_hours"] == 720

    def test_gate_news_feed_access_all_tiers(self):
        """Test news feed access across all tiers."""
        free_result = gate_news_feed_access("free")
        assert free_result["has_access"] is True
        assert free_result["has_realtime"] is False
        assert free_result["max_hours"] == 6
        assert free_result["max_items"] == 15

        pro_result = gate_news_feed_access("pro")
        assert pro_result["has_realtime"] is True
        assert pro_result["max_hours"] == 24
        assert pro_result["max_items"] == 50
        assert pro_result["has_ai_summary"] is False

        premium_result = gate_news_feed_access("premium")
        assert premium_result["has_ai_summary"] is True
        assert premium_result["max_hours"] == 72

        ultra_result = gate_news_feed_access("ultra")
        assert ultra_result["max_hours"] == 168
        assert ultra_result["max_items"] == 100

        admin_result = gate_news_feed_access("admin")
        assert admin_result["has_ai_summary"] is True

    def test_gate_congress_tracker_access_all_tiers(self):
        """Test congress tracker across all tiers."""
        free_result = gate_congress_tracker_access("free")
        assert free_result["has_access"] is False
        assert free_result["max_days"] == 0

        pro_result = gate_congress_tracker_access("pro")
        assert pro_result["has_access"] is True
        assert pro_result["max_days"] == 14
        assert pro_result["has_amount_detail"] is False

        premium_result = gate_congress_tracker_access("premium")
        assert premium_result["max_days"] == 30
        assert premium_result["has_amount_detail"] is True

        ultra_result = gate_congress_tracker_access("ultra")
        assert ultra_result["max_days"] == 90
        assert ultra_result["has_export"] is True

        admin_result = gate_congress_tracker_access("admin")
        assert admin_result["has_export"] is True

    def test_gate_paper_leaderboard_access_all_tiers(self):
        """Test paper trading leaderboard across all tiers."""
        free_result = gate_paper_leaderboard_access("free")
        assert free_result["has_access"] is True  # Public for acquisition
        assert free_result["has_full_stats"] is False
        assert free_result["max_entries"] == 10

        pro_result = gate_paper_leaderboard_access("pro")
        assert pro_result["has_full_stats"] is True
        assert pro_result["max_entries"] == 25
        assert pro_result["has_trade_history"] is False

        premium_result = gate_paper_leaderboard_access("premium")
        assert premium_result["has_trade_history"] is True

        admin_result = gate_paper_leaderboard_access("admin")
        assert admin_result["has_trade_history"] is True

    def test_gate_sports_betting_access_all_tiers(self):
        """Test sports betting access across all tiers."""
        free_result = gate_sports_betting_access("free")
        assert free_result["has_access"] is True  # Acquisition funnel
        assert free_result["max_days"] == 2
        assert free_result["max_items"] == 20
        assert free_result["has_line_mover_scores"] is False
        assert free_result["api_daily_limit"] == 0

        pro_result = gate_sports_betting_access("pro")
        assert pro_result["max_days"] == 5
        assert pro_result["max_items"] == 50
        assert pro_result["has_line_mover_scores"] is True
        assert pro_result["api_daily_limit"] == 0

        premium_result = gate_sports_betting_access("premium")
        assert premium_result["max_days"] == 7
        assert premium_result["max_items"] == 100
        assert premium_result["has_ai_summaries"] is True
        assert premium_result["api_daily_limit"] == 100

        ultra_result = gate_sports_betting_access("ultra")
        assert ultra_result["max_items"] == 200
        assert ultra_result["api_daily_limit"] == 500
        assert ultra_result["has_csv_export"] is True

        enterprise_result = gate_sports_betting_access("enterprise")
        assert enterprise_result["max_items"] == 500
        assert enterprise_result["api_daily_limit"] == 10000
        assert enterprise_result["has_bulk_data"] is True

        admin_result = gate_sports_betting_access("admin")
        assert admin_result["has_bulk_data"] is True

    def test_gate_signal_quality_access_all_tiers(self):
        """Test signal quality dashboard across all tiers."""
        free_result = gate_signal_quality_access("free")
        assert free_result["has_access"] is False

        pro_result = gate_signal_quality_access("pro")
        assert pro_result["has_access"] is True
        assert pro_result["has_category_heatmap"] is True
        assert pro_result["has_source_reliability"] is False
        assert pro_result["quality_days"] == 30

        premium_result = gate_signal_quality_access("premium")
        assert premium_result["has_source_reliability"] is True
        assert premium_result["has_feature_importance"] is True
        assert premium_result["quality_days"] == 90
        assert premium_result["has_suppression_view"] is False

        ultra_result = gate_signal_quality_access("ultra")
        assert ultra_result["has_suppression_view"] is True
        assert ultra_result["quality_days"] == 365

        admin_result = gate_signal_quality_access("admin")
        assert admin_result["has_suppression_view"] is True
