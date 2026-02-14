from __future__ import annotations

import time
from typing import Any, Dict, List

_PAID_TIERS = ("pro", "premium", "ultra", "enterprise", "admin")
_ADMIN_TIER = "admin"  # Master tier — full access to every feature


def gate_signal(signal: Dict[str, Any], tier: str, delay_s: int = 900) -> Dict[str, Any]:
    """
    Apply tier-based gating to a signal dict.
    Free tier: delay, redact reasoning and trade legs.
    Paid tiers: full access.
    """
    if tier in _PAID_TIERS:
        return signal

    # Free tier gating
    gated = dict(signal)

    # 1. Delay check: if signal is newer than delay_s, redact it heavily
    created_at = signal.get("created_at", 0)
    age = time.time() - created_at
    if age < delay_s:
        gated["_delayed"] = True
        gated["_available_in_s"] = int(delay_s - age)
        gated["reasoning"] = {"_locked": True, "_upgrade_message": "Upgrade to Pro for real-time signals"}
        gated["trade_idea"] = {
            "strategy": signal.get("strategy", "none"),
            "legs": [],
            "_locked": True,
            "_upgrade_message": "Upgrade to Pro for real-time trade ideas",
        }
        return gated

    # 2. Even after delay, free users see limited data
    gated["reasoning"] = _redact_reasoning(signal.get("reasoning", {}))
    gated["trade_idea"] = _redact_trade_idea(signal.get("trade_idea", {}))

    return gated


def gate_signal_list(
    signals: List[Dict[str, Any]],
    tier: str,
    delay_s: int = 900,
    page_limit: int = 10,
) -> List[Dict[str, Any]]:
    """Gate a list of signals. Free tier also gets page limit enforced."""
    if tier in _PAID_TIERS:
        return [gate_signal(s, tier, delay_s) for s in signals]

    # Free tier: limit page size
    limited = signals[:page_limit]
    return [gate_signal(s, "free", delay_s) for s in limited]


def gate_chart_access(tier: str) -> dict:
    """Return chart feature access flags based on tier."""
    return {
        "has_quadrant": tier in _PAID_TIERS,
        "has_timeline": tier in _PAID_TIERS,
        "has_strategy_breakdown": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_realtime_badge": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_custom_time_range": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_chart_export": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "chart_hours": 24 if tier == "pro" else 48 if tier in ("premium", "ultra", "enterprise", _ADMIN_TIER) else 0,
        "chart_limit": 50 if tier == "pro" else 100 if tier in ("premium", "ultra", "enterprise", _ADMIN_TIER) else 0,
    }


def gate_filter_access(tier: str) -> dict:
    """Return filter feature access flags based on tier."""
    return {
        "has_date_range": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_confidence_range": True,  # all tiers have min_confidence
        "has_ticker_filter": tier in _PAID_TIERS,     # Pro+ only
        "has_stance_filter": tier in _PAID_TIERS,     # Pro+ only
        "has_source_filter": tier in _PAID_TIERS,     # Pro+ only
        "has_saved_presets": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "max_presets": 10 if tier in ("ultra", "enterprise", _ADMIN_TIER) else 0,
    }


def gate_performance_access(tier: str) -> dict:
    """Return performance/accuracy feature access flags based on tier."""
    return {
        "has_aggregate_accuracy": tier in _PAID_TIERS,  # Pro+ only (monetization)
        "has_per_signal_pnl": tier in _PAID_TIERS,
        "has_roi_history_chart": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_performance_export": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_performance_dashboard": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_strategy_pnl": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_accuracy_breakdown": tier in _PAID_TIERS,  # Pro+ feature
        "has_confidence_calibration": tier in _PAID_TIERS,  # Pro+ feature
        "has_post_mortem": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),  # Premium+ feature
        "accuracy_days": 7 if tier == "free" else 30 if tier == "pro" else 90 if tier == "premium" else 365,
    }


def gate_email_access(tier: str) -> dict:
    """Return email alert feature access flags based on tier."""
    return {
        "has_daily_digest": True,  # all tiers
        "has_realtime_email": tier in _PAID_TIERS,
        "has_custom_filters": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_webhook": tier in ("ultra", "enterprise", _ADMIN_TIER),
    }


def gate_heatmap_access(tier: str) -> dict:
    """Return sector heatmap feature access flags based on tier."""
    return {
        "has_heatmap": tier in _PAID_TIERS,
        "has_drill_down": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_historical_replay": tier in ("ultra", "enterprise", _ADMIN_TIER),
    }


def gate_leaderboard_access(tier: str) -> dict:
    """Return leaderboard feature access flags based on tier."""
    return {
        "has_leaderboard": tier in _PAID_TIERS,  # Pro+ only (monetization)
        "leaderboard_limit": 0 if tier == "free" else 20,
        "has_sorting": tier in _PAID_TIERS,
        "has_historical": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_performance_column": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_custom_range": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_leaderboard_export": tier in ("ultra", "enterprise", _ADMIN_TIER),
    }


def gate_market_context(tier: str) -> dict:
    """Return market context card feature access flags based on tier."""
    return {
        "has_price_badge": tier in _PAID_TIERS,
        "has_extended_market": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_options_chain": tier in ("ultra", "enterprise", _ADMIN_TIER),
    }


def gate_correlation_access(tier: str) -> dict:
    """Return correlation view feature access flags based on tier."""
    return {
        "has_correlation": tier in _PAID_TIERS,
        "has_strength_scores": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_matrix_export": tier in ("ultra", "enterprise", _ADMIN_TIER),
    }


def gate_sentiment_access(tier: str) -> dict:
    """Return sentiment heatmap feature access flags based on tier."""
    return {
        "max_tickers": 3 if tier == "free" else 50,   # 3 tickers for free (was 10)
        "max_hours": 12 if tier == "free" else 168 if tier == "pro" else 720 if tier == "premium" else 2160,  # 12h for free (was 24h)
        "has_drill_down": tier in _PAID_TIERS,
        "has_sector_group": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_export": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
    }


def gate_ticker_dive_access(tier: str) -> dict:
    """Return ticker deep dive feature access flags based on tier."""
    return {
        "max_signals": 5 if tier == "free" else 50 if tier == "pro" else 100 if tier == "premium" else 9999,
        "has_chart": tier in _PAID_TIERS,
        "has_performance": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_sector_compare": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_correlation": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_export": tier in ("ultra", "enterprise", _ADMIN_TIER),
    }


def gate_weekly_wrap_access(tier: str) -> dict:
    """Return weekly wrap feature access flags based on tier."""
    return {
        "max_weeks_back": 1 if tier == "free" else 4 if tier == "pro" else 12 if tier == "premium" else 52,  # 1 week preview for free (was 0)
        "has_charts": tier in _PAID_TIERS,
        "has_strategy_breakdown": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_export": tier in ("ultra", "enterprise", _ADMIN_TIER),
    }


def gate_replay_access(tier: str) -> dict:
    """Return signal replay feature access flags based on tier."""
    return {
        "has_access": tier in _PAID_TIERS,
        "max_hours": 0 if tier == "free" else 24 if tier == "pro" else 168 if tier == "premium" else 720,
        "has_price_overlay": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_export": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_step_controls": tier in ("ultra", "enterprise", _ADMIN_TIER),
    }


# ── Enterprise-only gates ──

def gate_data_licensing(tier: str) -> dict:
    """Return data licensing feature access flags."""
    return {
        "has_access": tier in ("enterprise", _ADMIN_TIER),
        "has_full_history": tier in ("enterprise", _ADMIN_TIER),
        "has_json_export": tier in ("enterprise", _ADMIN_TIER),
        "has_csv_export": tier in ("enterprise", _ADMIN_TIER),
        "max_rows_per_export": 1000000 if tier in ("enterprise", _ADMIN_TIER) else 0,
    }


def gate_sponsored_access(tier: str) -> dict:
    """Return sponsored signal submission access flags."""
    return {
        "can_submit": tier in ("enterprise", _ADMIN_TIER),
        "can_view_status": tier in ("enterprise", _ADMIN_TIER),
        "max_pending": 10 if tier in ("enterprise", _ADMIN_TIER) else 0,
    }


def gate_sector_rotation_access(tier: str) -> dict:
    """Return sector rotation insights feature access flags based on tier."""
    return {
        "has_access": tier in _PAID_TIERS,  # Pro+ feature
        "has_performance_overlay": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_export": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "max_days": 30 if tier in ("pro", "premium") else 90 if tier in ("ultra", "enterprise", _ADMIN_TIER) else 0,
    }


def gate_unusual_activity(tier: str) -> dict:
    """Return unusual activity feed access flags based on tier."""
    return {
        "has_access": tier in _PAID_TIERS,
        "has_detail": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_history": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "max_hours": 0 if tier == "free" else 24 if tier == "pro" else 48 if tier == "premium" else 168 if tier == "ultra" else 720,
    }


def gate_news_feed_access(tier: str) -> dict:
    """Return news feed feature access flags based on tier."""
    return {
        "has_access": True,  # Free users see delayed/limited feed — great acquisition funnel
        "has_realtime": tier in _PAID_TIERS,  # Pro+ gets real-time
        "has_source_filter": tier in _PAID_TIERS,  # Pro+ can filter by source
        "has_ai_summary": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),  # Premium+ sees AI summaries
        "max_hours": 6 if tier == "free" else 24 if tier == "pro" else 72 if tier == "premium" else 168,
        "max_items": 15 if tier == "free" else 50 if tier == "pro" else 100,
    }


def gate_congress_tracker_access(tier: str) -> dict:
    """Return congressional trading tracker access flags based on tier."""
    return {
        "has_access": tier in _PAID_TIERS,  # Pro+ feature
        "has_amount_detail": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),  # Premium+ sees dollar ranges
        "has_ticker_filter": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_export": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "max_days": 14 if tier == "pro" else 30 if tier == "premium" else 90 if tier in ("ultra", "enterprise", _ADMIN_TIER) else 0,
    }


def gate_paper_leaderboard_access(tier: str) -> dict:
    """Return paper trading leaderboard access flags based on tier."""
    return {
        "has_access": True,  # Public — drives registrations
        "has_full_stats": tier in _PAID_TIERS,  # Pro+ sees win rate, return %
        "has_trade_history": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "max_entries": 10 if tier == "free" else 25,
    }


def gate_sports_betting_access(tier: str) -> dict:
    """Return sports betting intelligence feature access flags based on tier.

    The sleeper monetization feature. Free tier = acquisition funnel (basic news).
    Pro = line mover scores + team filtering. Premium+ = AI analysis + API.
    Enterprise = bulk data + webhooks.
    """
    return {
        # Basic access — free tier gets limited feed (acquisition funnel)
        "has_access": True,
        "max_days": (
            2 if tier == "free"
            else 5 if tier == "pro"
            else 7  # 7-day cap for premium/ultra/enterprise — protects news feed & API value
        ),
        "max_items": (
            20 if tier == "free"
            else 50 if tier == "pro"
            else 100 if tier == "premium"
            else 200 if tier == "ultra"
            else 500  # enterprise
        ),
        # Betting intel features
        "has_line_mover_scores": tier in _PAID_TIERS,
        "has_team_filter": tier in _PAID_TIERS,
        "has_league_filter": True,  # all tiers can filter by league
        "has_category_filter": tier in _PAID_TIERS,
        "has_betting_categories": tier in _PAID_TIERS,
        # AI features
        "has_ai_summaries": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_injury_analysis": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        # Alerts
        "has_email_alerts": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_custom_alerts": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_websocket_push": tier in ("ultra", "enterprise", _ADMIN_TIER),
        # API
        "has_api": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "api_daily_limit": (
            0 if tier in ("free", "pro")
            else 100 if tier == "premium"
            else 500 if tier == "ultra"
            else 10000  # enterprise
        ),
        # Export & Data
        "has_csv_export": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_bulk_data": tier in ("enterprise", _ADMIN_TIER),
        "has_webhook_feed": tier in ("enterprise", _ADMIN_TIER),
        # Sort options
        "has_score_sort": tier in _PAID_TIERS,  # sort by line mover score
    }


def gate_signal_quality_access(tier: str) -> dict:
    """Return signal quality dashboard feature access flags based on tier.

    Pro+ gets basic category heatmap and quality trends.
    Premium+ gets source reliability, feature importance, and detailed calibration.
    Ultra+ gets suppression view (operational insight into adaptive suppression).
    """
    return {
        "has_access": tier in _PAID_TIERS,
        "has_category_heatmap": tier in _PAID_TIERS,
        "has_source_reliability": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_feature_importance": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_quality_trend": tier in _PAID_TIERS,
        "has_suppression_view": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_calibration_detail": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "quality_days": (
            30 if tier in ("free", "pro")
            else 90 if tier == "premium"
            else 365
        ),
    }


def _redact_reasoning(reasoning: dict) -> dict:
    """Free users see thesis only, rest is locked."""
    if not reasoning:
        return {}
    return {
        "thesis": reasoning.get("thesis", ""),
        "_locked": True,
        "_locked_fields": [
            "catalyst_window", "market_expectation",
            "recommended_structures", "invalidations", "risk_notes",
        ],
        "_upgrade_message": "Upgrade to Pro for full analysis",
    }


def gate_backtest_access(tier: str) -> dict:
    """Return backtest feature access flags based on tier.

    Tier breakdown:
      - Free: No access
      - Pro: Basic backtest (30d, 200 signals, fixed_pct sizing)
      - Premium: + Monte Carlo, walk-forward, risk, benchmark (90d, 1000 signals)
      - Ultra/Enterprise: + optimizer, comparison, saved strategies, export (365d, 5000 signals)
    """
    if tier == "free":
        return {
            "has_access": False,
            "has_basic": False,
            "has_monte_carlo": False,
            "has_walk_forward": False,
            "has_risk_metrics": False,
            "has_benchmark": False,
            "has_optimizer": False,
            "has_comparison": False,
            "has_saved_strategies": False,
            "has_export": False,
            "max_days": 0,
            "max_signals": 0,
            "position_size_modes": [],
        }
    elif tier == "pro":
        return {
            "has_access": True,
            "has_basic": True,
            "has_monte_carlo": False,
            "has_walk_forward": False,
            "has_risk_metrics": False,
            "has_benchmark": False,
            "has_optimizer": False,
            "has_comparison": False,
            "has_saved_strategies": False,
            "has_export": False,
            "max_days": 30,
            "max_signals": 200,
            "position_size_modes": ["fixed_pct"],
        }
    elif tier == "premium":
        return {
            "has_access": True,
            "has_basic": True,
            "has_monte_carlo": True,
            "has_walk_forward": True,
            "has_risk_metrics": True,
            "has_benchmark": True,
            "has_optimizer": False,
            "has_comparison": False,
            "has_saved_strategies": False,
            "has_export": False,
            "max_days": 90,
            "max_signals": 1000,
            "position_size_modes": ["fixed_pct", "confidence_weighted"],
        }
    else:
        # ultra / enterprise
        return {
            "has_access": True,
            "has_basic": True,
            "has_monte_carlo": True,
            "has_walk_forward": True,
            "has_risk_metrics": True,
            "has_benchmark": True,
            "has_optimizer": True,
            "has_comparison": True,
            "has_saved_strategies": True,
            "has_export": True,
            "max_days": 365,
            "max_signals": 5000,
            "position_size_modes": ["fixed_pct", "kelly", "confidence_weighted"],
        }


def gate_macro_access(tier: str) -> dict:
    """Return macro events & economic calendar access flags based on tier.

    Free: next 3 upcoming events, no history, no impact/earnings/insider/fomc
    Pro: full calendar 7d, basic earnings, basic insider, FOMC dates
    Premium: +impact analysis, +IV crush, +seasonal, +earnings strategy
    Ultra/Enterprise: +full history, +insider cross-ref, +statement diffs, +export
    """
    if tier == "free":
        return {
            "has_access": True,  # Free users see limited calendar
            "has_calendar": True,
            "has_earnings": False,
            "has_insider": False,
            "has_fomc": False,
            "has_seasonal": False,
            "has_impact": False,
            "has_iv_crush": False,
            "has_statement_diff": False,
            "has_cross_reference": False,
            "has_strategy_recommend": False,
            "has_export": False,
            "calendar_max_days": 3,
            "calendar_max_events": 5,
            "history_max_days": 0,
        }
    elif tier == "pro":
        return {
            "has_access": True,
            "has_calendar": True,
            "has_earnings": True,
            "has_insider": True,
            "has_fomc": True,
            "has_seasonal": False,
            "has_impact": False,
            "has_iv_crush": False,
            "has_statement_diff": False,
            "has_cross_reference": False,
            "has_strategy_recommend": False,
            "has_export": False,
            "calendar_max_days": 7,
            "calendar_max_events": 50,
            "history_max_days": 30,
        }
    elif tier == "premium":
        return {
            "has_access": True,
            "has_calendar": True,
            "has_earnings": True,
            "has_insider": True,
            "has_fomc": True,
            "has_seasonal": True,
            "has_impact": True,
            "has_iv_crush": True,
            "has_statement_diff": True,
            "has_cross_reference": False,
            "has_strategy_recommend": True,
            "has_export": False,
            "calendar_max_days": 30,
            "calendar_max_events": 200,
            "history_max_days": 90,
        }
    else:
        # ultra / enterprise
        return {
            "has_access": True,
            "has_calendar": True,
            "has_earnings": True,
            "has_insider": True,
            "has_fomc": True,
            "has_seasonal": True,
            "has_impact": True,
            "has_iv_crush": True,
            "has_statement_diff": True,
            "has_cross_reference": True,
            "has_strategy_recommend": True,
            "has_export": True,
            "calendar_max_days": 90,
            "calendar_max_events": 500,
            "history_max_days": 365,
        }


def gate_terminal_access(tier: str) -> dict:
    """Return Bloomberg-lite terminal feature access flags based on tier.

    Premium+ gets the full multi-panel terminal experience.
    Ultra+ gets options flow panel and watchlist alerts.
    """
    return {
        "has_access": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_options_flow": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_news_wire": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "has_watchlist_alerts": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_heatmap": tier in ("premium", "ultra", "enterprise", _ADMIN_TIER),
        "refresh_interval_s": (
            0 if tier not in ("premium", "ultra", "enterprise", _ADMIN_TIER)
            else 60 if tier == "premium"
            else 30
        ),
        "max_signals_feed": (
            0 if tier not in ("premium", "ultra", "enterprise", _ADMIN_TIER)
            else 25 if tier == "premium"
            else 50
        ),
    }


def gate_agent_access(tier: str) -> dict:
    """Return autonomous trading agent feature access flags based on tier.

    Ultra+ gets AI trading agents that auto-execute paper trades.
    Enterprise gets custom rule agents, more agents, and API access.
    """
    return {
        "has_access": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "max_agents": (
            0 if tier not in ("ultra", "enterprise", _ADMIN_TIER)
            else 3 if tier == "ultra"
            else 10
        ),
        "has_signal_follower": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_contrarian": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_momentum_rider": tier in ("ultra", "enterprise", _ADMIN_TIER),
        "has_custom_rules": tier in ("enterprise", _ADMIN_TIER),
        "has_performance_export": tier in ("enterprise", _ADMIN_TIER),
        "has_api": tier in ("enterprise", _ADMIN_TIER),
    }


def gate_flow_access(tier: str) -> dict:
    """Return options flow intelligence feature access flags based on tier.

    Tier breakdown:
      - Free: No access
      - Pro: Flow events (24h), basic convergence
      - Premium: + patterns, convergence details, Greeks (7d)
      - Ultra/Enterprise: + full history (30d), export, portfolio Greeks
    """
    if tier == "free":
        return {
            "has_access": False,
            "has_events": False,
            "has_patterns": False,
            "has_convergences": False,
            "has_greeks": False,
            "has_portfolio_greeks": False,
            "has_export": False,
            "max_hours": 0,
        }
    elif tier == "pro":
        return {
            "has_access": True,
            "has_events": True,
            "has_patterns": False,
            "has_convergences": True,
            "has_greeks": False,
            "has_portfolio_greeks": False,
            "has_export": False,
            "max_hours": 24,
        }
    elif tier == "premium":
        return {
            "has_access": True,
            "has_events": True,
            "has_patterns": True,
            "has_convergences": True,
            "has_greeks": True,
            "has_portfolio_greeks": False,
            "has_export": False,
            "max_hours": 168,  # 7 days
        }
    else:
        # ultra / enterprise
        return {
            "has_access": True,
            "has_events": True,
            "has_patterns": True,
            "has_convergences": True,
            "has_greeks": True,
            "has_portfolio_greeks": True,
            "has_export": True,
            "max_hours": 720,  # 30 days
        }


def gate_social_access(tier: str) -> dict:
    """Return social intelligence feature access flags based on tier.

    Tier breakdown:
      - Free: No access
      - Pro: Leaderboard only
      - Premium: + author profiles, manipulation alerts
      - Ultra/Enterprise: + propagation, contrarian, export
    """
    if tier == "free":
        return {
            "has_access": False,
            "has_leaderboard": False,
            "has_profiles": False,
            "has_alerts": False,
            "has_propagation": False,
            "has_contrarian": False,
            "has_export": False,
        }
    elif tier == "pro":
        return {
            "has_access": True,
            "has_leaderboard": True,
            "has_profiles": False,
            "has_alerts": False,
            "has_propagation": False,
            "has_contrarian": False,
            "has_export": False,
        }
    elif tier == "premium":
        return {
            "has_access": True,
            "has_leaderboard": True,
            "has_profiles": True,
            "has_alerts": True,
            "has_propagation": False,
            "has_contrarian": False,
            "has_export": False,
        }
    else:
        # ultra / enterprise
        return {
            "has_access": True,
            "has_leaderboard": True,
            "has_profiles": True,
            "has_alerts": True,
            "has_propagation": True,
            "has_contrarian": True,
            "has_export": True,
        }


def gate_strategy_access(tier: str) -> dict:
    """Return strategy builder feature access flags based on tier.

    Tier breakdown:
      - Free: No access
      - Pro: 3 manual strategies only
      - Premium: + discovery, ML optimize
      - Ultra: + genetic, marketplace, unlimited strategies
      - Enterprise: Full API + bulk
    """
    if tier == "free":
        return {
            "has_access": False,
            "max_strategies": 0,
            "has_discovery": False,
            "has_ml_optimize": False,
            "has_genetic": False,
            "has_marketplace": False,
            "has_auto_trade": False,
            "has_regimes": False,
            "has_export": False,
        }
    elif tier == "pro":
        return {
            "has_access": True,
            "max_strategies": 3,
            "has_discovery": False,
            "has_ml_optimize": False,
            "has_genetic": False,
            "has_marketplace": False,
            "has_auto_trade": True,
            "has_regimes": False,
            "has_export": False,
        }
    elif tier == "premium":
        return {
            "has_access": True,
            "max_strategies": 10,
            "has_discovery": True,
            "has_ml_optimize": True,
            "has_genetic": False,
            "has_marketplace": False,
            "has_auto_trade": True,
            "has_regimes": True,
            "has_export": False,
        }
    else:
        # ultra / enterprise
        return {
            "has_access": True,
            "max_strategies": 999,
            "has_discovery": True,
            "has_ml_optimize": True,
            "has_genetic": True,
            "has_marketplace": True,
            "has_auto_trade": True,
            "has_regimes": True,
            "has_export": True,
        }


def gate_tradingview_access(tier: str) -> dict:
    """Return TradingView integration feature access flags based on tier.

    Free: Public page, basic info
    Pro+: Pine Script generator, full integration
    Ultra+: Enhanced features (future)
    """
    return {
        "has_access": True,  # All tiers can view the TradingView page
        "has_pine_script_generator": tier in _PAID_TIERS,  # Pro+ only
        "has_signal_feed": tier in _PAID_TIERS,  # JSON feed requires Pro+
        "has_webhook": tier in _PAID_TIERS,  # Incoming webhooks require Pro+
        "max_script_signals": (
            0 if tier == "free"
            else 50 if tier == "pro"
            else 100
        ),
        "max_days_history": (
            0 if tier == "free"
            else 30 if tier == "pro"
            else 90 if tier == "premium"
            else 365
        ),
    }


def _redact_trade_idea(idea: dict) -> dict:
    """Free users see strategy name only, legs are hidden."""
    if not idea:
        return {}
    return {
        "strategy": idea.get("strategy", "none"),
        "thesis": idea.get("thesis", ""),
        "legs": [],
        "_locked": True,
        "_upgrade_message": "Upgrade to Pro to see trade legs and details",
    }
