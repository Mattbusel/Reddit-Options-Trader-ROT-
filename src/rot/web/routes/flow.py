"""Options flow intelligence routes.

HTML dashboard + JSON API endpoints for institutional flow events,
convergence detection, pattern recognition, and Greeks computation.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from rot.web.auth import get_current_user_optional
from rot.web.rate_limit import check_rate_limit, rate_limit_headers, require_api_auth
from rot.web.tier_gate import gate_flow_access

router = APIRouter()


# ── HTML Page ──────────────────────────────────────────


@router.get("/flow")
async def flow_dashboard(request: Request):
    """Flow intelligence dashboard page."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_flow_access(tier)
    db = request.app.state.db
    templates = request.app.state.templates

    events = []
    summary = {}
    convergences = []
    patterns = []

    if access["has_access"]:
        max_hours = access["max_hours"]
        events = await db.get_flow_events(hours=max_hours, limit=50)
        summary = await db.get_flow_summary(hours=max_hours)
        if access["has_convergences"]:
            convergences = await db.get_flow_convergences(hours=max_hours, limit=20)
        if access["has_patterns"]:
            patterns = await db.get_flow_patterns(hours=max_hours, limit=20)

    return templates.TemplateResponse("flow.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
        "events": events,
        "summary": summary,
        "convergences": convergences,
        "patterns": patterns,
        "now": time.time(),
    })


# ── JSON API: Flow Events ──────────────────────────────


@router.get("/api/v1/flow/events")
async def api_flow_events(
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    ticker: Optional[str] = Query(default=None),
    flow_type: Optional[str] = Query(default=None),
    direction: Optional[str] = Query(default=None),
    min_score: float = Query(default=0.0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    """JSON feed of flow events with filters."""
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_flow_access(tier)
    headers = rate_limit_headers(user)

    if not access["has_access"]:
        return JSONResponse(
            {"events": [], "detail": "Upgrade to Pro for flow intelligence"},
            status_code=403,
            headers=headers,
        )

    # Enforce tier max hours
    hours = min(hours, access["max_hours"])
    db = request.app.state.db
    events = await db.get_flow_events(
        hours=hours, ticker=ticker, flow_type=flow_type,
        direction=direction, min_score=min_score, limit=limit,
    )

    return JSONResponse({
        "events": events,
        "count": len(events),
        "hours": hours,
        "tier": tier,
    }, headers=headers)


# ── JSON API: Flow Summary ─────────────────────────────


@router.get("/api/v1/flow/summary")
async def api_flow_summary(
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
):
    """Aggregate flow statistics."""
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_flow_access(tier)
    headers = rate_limit_headers(user)

    if not access["has_access"]:
        return JSONResponse(
            {"summary": {}, "detail": "Upgrade to Pro for flow intelligence"},
            status_code=403,
            headers=headers,
        )

    hours = min(hours, access["max_hours"])
    db = request.app.state.db
    summary = await db.get_flow_summary(hours=hours)

    return JSONResponse({
        "summary": summary,
        "hours": hours,
        "tier": tier,
    }, headers=headers)


# ── JSON API: Flow Timeline ────────────────────────────


@router.get("/api/v1/flow/timeline/{ticker}")
async def api_flow_timeline(
    request: Request,
    ticker: str,
    days: int = Query(default=7, ge=1, le=90),
):
    """Per-ticker flow event timeline."""
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_flow_access(tier)
    headers = rate_limit_headers(user)

    if not access["has_access"]:
        return JSONResponse(
            {"events": [], "detail": "Upgrade to Pro for flow intelligence"},
            status_code=403,
            headers=headers,
        )

    # Enforce tier max hours (convert days to hours for comparison)
    max_days = access["max_hours"] // 24
    days = min(days, max(max_days, 1))

    db = request.app.state.db
    events = await db.get_flow_timeline(ticker=ticker.upper(), days=days)

    return JSONResponse({
        "events": events,
        "ticker": ticker.upper(),
        "days": days,
        "tier": tier,
    }, headers=headers)


# ── JSON API: Convergences ─────────────────────────────


@router.get("/api/v1/flow/convergences")
async def api_flow_convergences(
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    ticker: Optional[str] = Query(default=None),
    convergence_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Signal-flow convergence data."""
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_flow_access(tier)
    headers = rate_limit_headers(user)

    if not access["has_convergences"]:
        return JSONResponse(
            {"convergences": [], "detail": "Upgrade to Pro for convergence data"},
            status_code=403,
            headers=headers,
        )

    hours = min(hours, access["max_hours"])
    db = request.app.state.db
    convergences = await db.get_flow_convergences(
        hours=hours, ticker=ticker,
        convergence_type=convergence_type, limit=limit,
    )

    return JSONResponse({
        "convergences": convergences,
        "count": len(convergences),
        "hours": hours,
        "tier": tier,
    }, headers=headers)


# ── JSON API: Patterns ─────────────────────────────────


@router.get("/api/v1/flow/patterns")
async def api_flow_patterns(
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    pattern_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
):
    """Detected institutional flow patterns."""
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_flow_access(tier)
    headers = rate_limit_headers(user)

    if not access["has_patterns"]:
        return JSONResponse(
            {"patterns": [], "detail": "Upgrade to Premium for flow patterns"},
            status_code=403,
            headers=headers,
        )

    hours = min(hours, access["max_hours"])
    db = request.app.state.db
    patterns = await db.get_flow_patterns(
        hours=hours, pattern_type=pattern_type, limit=limit,
    )

    return JSONResponse({
        "patterns": patterns,
        "count": len(patterns),
        "hours": hours,
        "tier": tier,
    }, headers=headers)
