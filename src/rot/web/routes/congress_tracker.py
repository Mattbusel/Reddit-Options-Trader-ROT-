"""Congressional Trading Tracker routes.

Kills: Unusual Whales congressional add-on ($10/mo on top of $48/mo).
Tracks politician stock trades from EFDS/SEC filings for free.

Pro feature. Premium+ sees dollar amounts and ticker filter.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_congress_tracker_access

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/congress-tracker", response_class=HTMLResponse)
async def congress_tracker_page(request: Request, ticker: str = "", days: int = 0):
    """Congressional trading tracker page."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    gate = gate_congress_tracker_access(tier)

    if not gate["has_access"]:
        templates = request.app.state.templates
        return templates.TemplateResponse("congress_tracker.html", {
            "request": request,
            "user": user,
            "tier": tier,
            "gate": gate,
            "trades": [],
            "summary": {},
            "ticker_filter": "",
            "days": 0,
            "locked": True,
        })

    max_days = gate["max_days"]
    if days <= 0 or days > max_days:
        days = max_days

    ticker_filter = ""
    if ticker and gate["has_ticker_filter"]:
        ticker_filter = ticker.upper()

    db = request.app.state.db
    trades = await db.get_congress_trades(days=days, limit=100, ticker=ticker_filter or None)
    summary = await db.get_congress_summary(days=days)

    # Strip dollar amounts for non-premium
    if not gate["has_amount_detail"]:
        for t in trades:
            t["amount_range"] = "Pro+"

    templates = request.app.state.templates
    return templates.TemplateResponse("congress_tracker.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "gate": gate,
        "trades": trades,
        "summary": summary,
        "ticker_filter": ticker_filter,
        "days": days,
        "locked": False,
    })


@router.get("/api/v1/congress-trades", tags=["congress"])
async def congress_trades_api(request: Request, days: int = 30, limit: int = 50, ticker: str = ""):
    """JSON endpoint for congressional trades."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    gate = gate_congress_tracker_access(tier)

    if not gate["has_access"]:
        return {"error": "Pro subscription required", "trades": []}

    days = min(days, gate["max_days"])
    ticker_filter = ticker.upper() if ticker and gate["has_ticker_filter"] else None

    db = request.app.state.db
    trades = await db.get_congress_trades(days=days, limit=min(limit, 100), ticker=ticker_filter)

    if not gate["has_amount_detail"]:
        for t in trades:
            t["amount_range"] = "hidden"

    return {"trades": trades, "count": len(trades), "days": days}
