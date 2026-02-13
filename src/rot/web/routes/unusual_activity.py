"""Unusual Activity Feed routes.

Provides:
  - /unusual-activity — HTML page showing signals with unusual options activity
  - /api/v1/unusual-activity — JSON feed with unusual flags
  - /api/v1/unusual-activity/summary — aggregate stats
  - /api/v1/unusual-activity/timeline/{ticker} — per-ticker timeline
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web.rate_limit import check_rate_limit, require_api_auth, rate_limit_headers
from rot.web.tier_gate import gate_unusual_activity

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/unusual-activity", response_class=HTMLResponse)
async def unusual_activity_page(request: Request):
    """Unusual activity feed page with event cards and timeline chart."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    templates = request.app.state.templates
    db = request.app.state.db
    access = gate_unusual_activity(tier)

    events = []
    summary = {}
    legacy_signals = []

    if access["has_access"]:
        hours = access["max_hours"]

        # Pull from new unusual_events table
        events = await db.get_unusual_events(hours=hours, limit=100)
        summary = await db.get_unusual_summary(hours=hours)

        # Also pull legacy inline-scanned signals as fallback
        legacy_signals = await db.get_unusual_activity_signals(hours=hours, limit=50)

        # Strip detail fields for non-premium
        if not access["has_detail"]:
            for s in legacy_signals:
                s.pop("unusual_detail", None)
            for e in events:
                e.pop("details", None)

    return templates.TemplateResponse("unusual_activity.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
        "events": events,
        "summary": summary,
        "signals": legacy_signals,
        "now": time.time(),
    })


@router.get("/api/v1/unusual-activity")
async def unusual_activity_json(
    request: Request,
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(50, ge=1, le=200),
    ticker: str = Query(None),
    min_score: float = Query(0.0, ge=0, le=100),
    event_type: str = Query(None),
):
    """JSON feed of unusual activity events. Requires paid subscription."""
    from fastapi.responses import JSONResponse

    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_unusual_activity(tier)

    if not access["has_access"]:
        return JSONResponse(
            content={"events": [], "detail": "Upgrade to Pro for unusual activity data"},
            status_code=403,
            headers=rate_limit_headers(user),
        )

    hours = min(hours, access["max_hours"])
    db = request.app.state.db
    events = await db.get_unusual_events(
        hours=hours, limit=limit, ticker=ticker,
        min_score=min_score, event_type=event_type,
    )

    # Strip detail for non-premium
    if not access["has_detail"]:
        for e in events:
            e.pop("details", None)

    return JSONResponse(
        content={
            "events": events,
            "count": len(events),
            "hours": hours,
            "tier": tier,
        },
        headers=rate_limit_headers(user),
    )


@router.get("/api/v1/unusual-activity/summary")
async def unusual_activity_summary(
    request: Request,
    hours: int = Query(24, ge=1, le=720),
):
    """Aggregate unusual activity statistics."""
    from fastapi.responses import JSONResponse

    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_unusual_activity(tier)

    if not access["has_access"]:
        return JSONResponse(
            content={"detail": "Upgrade to Pro for unusual activity data"},
            status_code=403,
            headers=rate_limit_headers(user),
        )

    hours = min(hours, access["max_hours"])
    db = request.app.state.db
    summary = await db.get_unusual_summary(hours=hours)

    return JSONResponse(
        content=summary,
        headers=rate_limit_headers(user),
    )


@router.get("/api/v1/unusual-activity/timeline/{ticker}")
async def unusual_activity_timeline(
    request: Request,
    ticker: str,
    days: int = Query(7, ge=1, le=90),
):
    """Per-ticker unusual activity timeline."""
    from fastapi.responses import JSONResponse

    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_unusual_activity(tier)

    if not access["has_access"]:
        return JSONResponse(
            content={"detail": "Upgrade to Pro for unusual activity data"},
            status_code=403,
            headers=rate_limit_headers(user),
        )

    db = request.app.state.db
    events = await db.get_unusual_timeline(ticker.upper(), days=days)

    # Strip detail for non-premium
    if not access["has_detail"]:
        for e in events:
            e.pop("details", None)

    return JSONResponse(
        content={
            "ticker": ticker.upper(),
            "events": events,
            "count": len(events),
            "days": days,
        },
        headers=rate_limit_headers(user),
    )
