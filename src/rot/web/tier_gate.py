from __future__ import annotations

import time
from typing import Any, Dict, List

_PAID_TIERS = ("pro", "premium", "ultra")


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
        "has_strategy_breakdown": tier in ("premium", "ultra"),
        "has_realtime_badge": tier == "ultra",
        "has_custom_time_range": tier == "ultra",
        "has_chart_export": tier == "ultra",
        "chart_hours": 24 if tier == "pro" else 48 if tier in ("premium", "ultra") else 0,
        "chart_limit": 50 if tier == "pro" else 100 if tier in ("premium", "ultra") else 0,
    }


def gate_filter_access(tier: str) -> dict:
    """Return filter feature access flags based on tier."""
    return {
        "has_date_range": tier in ("premium", "ultra"),
        "has_confidence_range": True,  # all tiers have min_confidence
        "has_saved_presets": tier == "ultra",
        "max_presets": 10 if tier == "ultra" else 0,
    }


def gate_performance_access(tier: str) -> dict:
    """Return performance/accuracy feature access flags based on tier."""
    return {
        "has_aggregate_accuracy": True,  # all tiers
        "has_per_signal_pnl": tier in ("pro", "premium", "ultra"),
        "has_roi_history_chart": tier in ("premium", "ultra"),
        "has_performance_export": tier == "ultra",
        "has_performance_dashboard": tier in ("premium", "ultra"),
        "has_strategy_pnl": tier == "ultra",
        "accuracy_days": 7 if tier == "free" else 30 if tier == "pro" else 90 if tier == "premium" else 365,
    }


def gate_email_access(tier: str) -> dict:
    """Return email alert feature access flags based on tier."""
    return {
        "has_daily_digest": True,  # all tiers
        "has_realtime_email": tier in ("pro", "premium", "ultra"),
        "has_custom_filters": tier in ("premium", "ultra"),
        "has_webhook": tier == "ultra",
    }


def gate_heatmap_access(tier: str) -> dict:
    """Return sector heatmap feature access flags based on tier."""
    return {
        "has_heatmap": tier in ("pro", "premium", "ultra"),
        "has_drill_down": tier in ("premium", "ultra"),
        "has_historical_replay": tier == "ultra",
    }


def gate_leaderboard_access(tier: str) -> dict:
    """Return leaderboard feature access flags based on tier."""
    return {
        "has_leaderboard": True,  # all tiers
        "leaderboard_limit": 5 if tier == "free" else 20,
        "has_sorting": tier in ("pro", "premium", "ultra"),
        "has_historical": tier in ("premium", "ultra"),
        "has_performance_column": tier in ("premium", "ultra"),
        "has_custom_range": tier == "ultra",
        "has_leaderboard_export": tier == "ultra",
    }


def gate_market_context(tier: str) -> dict:
    """Return market context card feature access flags based on tier."""
    return {
        "has_price_badge": tier in ("pro", "premium", "ultra"),
        "has_extended_market": tier in ("premium", "ultra"),
        "has_options_chain": tier == "ultra",
    }


def gate_correlation_access(tier: str) -> dict:
    """Return correlation view feature access flags based on tier."""
    return {
        "has_correlation": tier in ("pro", "premium", "ultra"),
        "has_strength_scores": tier in ("premium", "ultra"),
        "has_matrix_export": tier == "ultra",
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
