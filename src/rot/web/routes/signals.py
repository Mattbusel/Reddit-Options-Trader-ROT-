from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from rot.web.auth import get_current_user_optional, require_tier
from rot.web.rate_limit import check_rate_limit
from rot.web.tier_gate import (
    gate_signal,
    gate_signal_list,
    gate_performance_access,
    gate_leaderboard_access,
    gate_correlation_access,
    gate_heatmap_access,
)

router = APIRouter()


@router.get("/signals")
async def list_signals(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ticker: Optional[str] = None,
    stance: Optional[str] = None,
    min_confidence: Optional[float] = None,
    event_type: Optional[str] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
):
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    settings = request.app.state.settings

    # Free tier: cap page size
    if tier == "free":
        limit = min(limit, settings.tier_limits.free_page_limit)

    # Date range filtering only for premium+
    if tier not in ("premium", "ultra"):
        date_from = None
        date_to = None

    db = request.app.state.db
    signals = await db.get_signals(
        limit=limit,
        offset=offset,
        ticker=ticker,
        stance=stance,
        min_confidence=min_confidence,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
    )

    gated = gate_signal_list(
        signals, tier,
        delay_s=settings.tier_limits.free_signal_delay_s,
        page_limit=settings.tier_limits.free_page_limit,
    )

    return {"signals": gated, "count": len(gated), "offset": offset, "tier": tier}


@router.get("/signals/new-count")
async def new_signal_count(request: Request):
    """Get count of new signals since user's last visit."""
    user = await get_current_user_optional(request)
    if not user:
        return {"count": 0}

    db = request.app.state.db
    user_settings = user.get("settings", {})
    last_visit = user_settings.get("last_visit_at", 0) if isinstance(user_settings, dict) else 0
    count = await db.get_signals_since(last_visit) if last_visit else 0
    return {"count": count}


@router.get("/signals/{signal_id}")
async def get_signal(request: Request, signal_id: str):
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    signal = await db.get_signal(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    tier = (user or {}).get("tier", "free")
    settings = request.app.state.settings
    return gate_signal(signal, tier, delay_s=settings.tier_limits.free_signal_delay_s)


@router.get("/tickers/trending")
async def trending_tickers(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(20, ge=1, le=100),
):
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    tickers = await db.get_trending_tickers(hours=hours, limit=limit)
    return {"tickers": tickers, "period_hours": hours}


@router.get("/performance/summary")
async def performance_summary(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    summary = await db.get_performance_summary(days=days)
    return summary


@router.get("/performance/accuracy")
async def accuracy_stats(
    request: Request,
    days: int = Query(7, ge=1, le=365),
    ticker: Optional[str] = None,
):
    """Get signal accuracy statistics."""
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    perf = gate_performance_access(tier)

    # Cap days by tier
    days = min(days, perf["accuracy_days"])

    db = request.app.state.db
    accuracy = await db.get_aggregate_accuracy(days=days, ticker=ticker)
    return accuracy


@router.get("/performance/history")
async def performance_history(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    ticker: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    """Get per-signal performance history (pro+)."""
    user = await require_tier("pro", "premium", "ultra")(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    history = await db.get_performance_history(days=days, ticker=ticker, limit=limit)
    return {"history": history, "count": len(history)}


@router.get("/performance/accuracy-chart")
async def accuracy_chart_data(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    """Get time-series accuracy data for Chart.js (premium+)."""
    user = await require_tier("premium", "ultra")(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    data = await db.get_accuracy_over_time(days=days)
    return {"data": data}


@router.get("/performance/strategy-pnl")
async def strategy_pnl(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    """Get strategy-level P&L breakdown (ultra)."""
    user = await require_tier("ultra")(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    data = await db.get_strategy_pnl(days=days)
    return {"strategies": data}


@router.get("/leaderboard")
async def leaderboard(
    request: Request,
    hours: int = Query(24, ge=1, le=2160),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("signal_count"),
):
    """Get ticker leaderboard."""
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    lb = gate_leaderboard_access(tier)

    # Enforce tier limits
    limit = min(limit, lb["leaderboard_limit"])
    if not lb["has_historical"]:
        hours = 24

    db = request.app.state.db
    if lb["has_performance_column"]:
        data = await db.get_leaderboard_with_performance(hours=hours, limit=limit)
    else:
        data = await db.get_leaderboard(hours=hours, limit=limit, sort_by=sort_by)

    return {"leaderboard": data, "hours": hours, "tier": tier}


@router.get("/correlations")
async def correlations(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
):
    """Get co-occurring ticker pairs (pro+)."""
    user = await require_tier("pro", "premium", "ultra")(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    data = await db.get_co_occurring_tickers(hours=hours, min_co_occurrence=2)
    return {"correlations": data, "hours": hours}


@router.get("/sectors/{sector}")
async def sector_detail(
    request: Request,
    sector: str,
    hours: int = Query(24, ge=1, le=168),
):
    """Get ticker drill-down for a sector (premium+)."""
    user = await require_tier("premium", "ultra")(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    data = await db.get_sector_drill_down(sector, hours=hours)
    return {"sector": sector, "tickers": data, "hours": hours}
