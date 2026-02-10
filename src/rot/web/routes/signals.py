from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from rot.web.auth import get_current_user_optional
from rot.web.rate_limit import check_rate_limit
from rot.web.tier_gate import gate_signal, gate_signal_list

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
):
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    settings = request.app.state.settings

    # Free tier: cap page size
    if tier == "free":
        limit = min(limit, settings.tier_limits.free_page_limit)

    db = request.app.state.db
    signals = await db.get_signals(
        limit=limit,
        offset=offset,
        ticker=ticker,
        stance=stance,
        min_confidence=min_confidence,
        event_type=event_type,
    )

    gated = gate_signal_list(
        signals, tier,
        delay_s=settings.tier_limits.free_signal_delay_s,
        page_limit=settings.tier_limits.free_page_limit,
    )

    return {"signals": gated, "count": len(gated), "offset": offset, "tier": tier}


@router.get("/signals/{signal_id}")
async def get_signal(request: Request, signal_id: str):
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    signal = await db.get_signal(signal_id)
    if not signal:
        from fastapi import HTTPException
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
