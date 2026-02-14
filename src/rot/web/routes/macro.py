"""Macro Events & Economic Calendar routes.

Provides:
  - /macro/calendar — Economic calendar page
  - /macro/earnings — Earnings calendar page
  - /macro/insider — Insider & congressional trades page
  - /macro/fomc — FOMC tracker page
  - /api/v1/macro/events — JSON API for macro events
  - /api/v1/macro/earnings — JSON API for earnings
  - /api/v1/macro/insider — JSON API for insider trades
  - /api/v1/macro/impact — JSON API for event impact analysis
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_macro_access

log = logging.getLogger(__name__)

router = APIRouter()


# ── HTML Pages ──────────────────────────────────────────────────────


@router.get("/macro/calendar", response_class=HTMLResponse)
async def macro_calendar_page(request: Request):
    """Economic calendar page showing upcoming and past macro events."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    templates = request.app.state.templates
    db = request.app.state.db
    access = gate_macro_access(tier)

    upcoming = []
    past = []
    seasonal_bias = {}

    if access["has_calendar"]:
        max_days = access["calendar_max_days"]
        max_events = access["calendar_max_events"]

        upcoming = await db.query_macro_events(
            start_ts=time.time(),
            end_ts=time.time() + max_days * 86400,
            order="asc",
            limit=max_events,
        )
        if access["history_max_days"] > 0:
            past = await db.query_macro_events(
                start_ts=time.time() - access["history_max_days"] * 86400,
                end_ts=time.time(),
                order="desc",
                limit=50,
            )

        if access["has_seasonal"]:
            from rot.macro.seasonal import SeasonalAnalyzer
            from datetime import datetime, timezone

            analyzer = SeasonalAnalyzer()
            current_month = datetime.now(timezone.utc).month
            seasonal_bias = analyzer.get_current_bias(current_month)

    return templates.TemplateResponse("macro_calendar.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
        "upcoming": upcoming,
        "past": past,
        "seasonal_bias": seasonal_bias,
        "now": time.time(),
    })


@router.get("/macro/earnings", response_class=HTMLResponse)
async def macro_earnings_page(request: Request):
    """Earnings calendar page with IV crush history and strategy recommendations."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    templates = request.app.state.templates
    db = request.app.state.db
    access = gate_macro_access(tier)

    upcoming = []
    past = []

    if access["has_earnings"]:
        upcoming = await db.query_earnings_events(
            start_ts=time.time(),
            end_ts=time.time() + 14 * 86400,
            order="asc",
            limit=50,
        )
        if access["history_max_days"] > 0:
            past = await db.query_earnings_events(
                start_ts=time.time() - access["history_max_days"] * 86400,
                end_ts=time.time(),
                order="desc",
                limit=50,
            )

    return templates.TemplateResponse("macro_earnings.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
        "upcoming": upcoming,
        "past": past,
        "now": time.time(),
    })


@router.get("/macro/insider", response_class=HTMLResponse)
async def macro_insider_page(request: Request):
    """Insider & congressional trades page."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    templates = request.app.state.templates
    db = request.app.state.db
    access = gate_macro_access(tier)

    trades = []
    notable = []

    if access["has_insider"]:
        max_days = access["history_max_days"] or 14
        trades = await db.query_insider_trades(
            start_ts=time.time() - max_days * 86400,
            end_ts=time.time(),
            order="desc",
            limit=100,
        )
        notable = await db.query_insider_trades(
            start_ts=time.time() - max_days * 86400,
            end_ts=time.time(),
            min_value=100000,
            order="desc",
            limit=20,
        )

    return templates.TemplateResponse("macro_insider.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
        "trades": trades,
        "notable": notable,
        "now": time.time(),
    })


@router.get("/macro/fomc", response_class=HTMLResponse)
async def macro_fomc_page(request: Request):
    """FOMC tracker page with rate decisions, statement analysis, and scoring."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    templates = request.app.state.templates
    db = request.app.state.db
    access = gate_macro_access(tier)

    meetings = []
    next_meeting = None

    if access["has_fomc"]:
        meetings = await db.query_fomc_meetings(limit=20, order="desc")
        next_row = await db.get_next_fomc_meeting(time.time())
        if next_row:
            next_meeting = next_row

    return templates.TemplateResponse("macro_fomc.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
        "meetings": meetings,
        "next_meeting": next_meeting,
        "now": time.time(),
    })


# ── JSON API Endpoints ──────────────────────────────────────────────


@router.get("/api/v1/macro/events")
async def macro_events_json(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    direction: str = Query("upcoming"),
    category: str = Query(None),
    importance: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """JSON feed of macro economic events."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_macro_access(tier)

    if not access["has_calendar"]:
        return JSONResponse(
            {"error": "Macro calendar requires a paid subscription"},
            status_code=403,
        )

    days = min(days, access["calendar_max_days"])
    limit = min(limit, access["calendar_max_events"])

    db = request.app.state.db
    now = time.time()

    importance_filter = [importance] if importance else None

    if direction == "upcoming":
        events = await db.query_macro_events(
            start_ts=now, end_ts=now + days * 86400,
            category=category, importance_in=importance_filter,
            order="asc", limit=limit,
        )
    else:
        events = await db.query_macro_events(
            start_ts=now - days * 86400, end_ts=now,
            category=category, importance_in=importance_filter,
            order="desc", limit=limit,
        )

    return {"events": events, "count": len(events)}


@router.get("/api/v1/macro/earnings")
async def macro_earnings_json(
    request: Request,
    days: int = Query(14, ge=1, le=90),
    ticker: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """JSON feed of earnings events."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_macro_access(tier)

    if not access["has_earnings"]:
        return JSONResponse(
            {"error": "Earnings calendar requires Pro+ subscription"},
            status_code=403,
        )

    db = request.app.state.db
    now = time.time()

    events = await db.query_earnings_events(
        ticker=ticker,
        start_ts=now,
        end_ts=now + days * 86400,
        order="asc",
        limit=limit,
    )

    return {"events": events, "count": len(events)}


@router.get("/api/v1/macro/insider")
async def macro_insider_json(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    ticker: str = Query(None),
    trade_type: str = Query(None),
    min_value: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """JSON feed of insider trades."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_macro_access(tier)

    if not access["has_insider"]:
        return JSONResponse(
            {"error": "Insider feed requires Pro+ subscription"},
            status_code=403,
        )

    db = request.app.state.db
    now = time.time()

    trades = await db.query_insider_trades(
        ticker=ticker,
        start_ts=now - days * 86400,
        end_ts=now,
        trade_type=trade_type,
        min_value=min_value if min_value > 0 else None,
        order="desc",
        limit=limit,
    )

    return {"trades": trades, "count": len(trades)}


@router.get("/api/v1/macro/impact")
async def macro_impact_json(
    request: Request,
    event_type: str = Query(...),
):
    """JSON API for historical event impact analysis."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_macro_access(tier)

    if not access["has_impact"]:
        return JSONResponse(
            {"error": "Impact analysis requires Premium+ subscription"},
            status_code=403,
        )

    db = request.app.state.db

    from rot.macro.impact import EventImpactAnalyzer

    analyzer = EventImpactAnalyzer(db)
    prediction = await analyzer.predict_impact(event_type)

    return prediction
