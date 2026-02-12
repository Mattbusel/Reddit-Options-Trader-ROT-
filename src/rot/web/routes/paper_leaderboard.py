"""Paper Trading Leaderboard routes.

Kills: BlackBoxStocks community ($149/mo).
Public leaderboard drives registrations. Competitive paper trading
creates community engagement without Discord mod costs.

Public page (drives signups). Pro+ sees detailed stats.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_paper_leaderboard_access

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/leaderboard", response_class=HTMLResponse)
async def paper_leaderboard_page(request: Request):
    """Public paper trading leaderboard."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    gate = gate_paper_leaderboard_access(tier)

    db = request.app.state.db
    leaders = await db.get_paper_trading_leaderboard(limit=gate["max_entries"])

    # Mask detailed stats for free users
    if not gate["has_full_stats"]:
        for leader in leaders:
            leader["win_rate"] = None
            leader["return_pct"] = None
            leader["winning_trades"] = None

    # Anonymize usernames (show first 3 chars + ***)
    for i, leader in enumerate(leaders):
        name = leader.get("username", "anon")
        if len(name) > 3:
            leader["username"] = name[:3] + "***"
        leader["rank"] = i + 1

    templates = request.app.state.templates
    return templates.TemplateResponse("paper_leaderboard.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "gate": gate,
        "leaders": leaders,
    })


@router.get("/api/v1/paper-leaderboard", tags=["paper-trading"])
async def paper_leaderboard_api(request: Request, limit: int = 25):
    """JSON paper trading leaderboard."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    gate = gate_paper_leaderboard_access(tier)

    db = request.app.state.db
    leaders = await db.get_paper_trading_leaderboard(limit=min(limit, gate["max_entries"]))

    if not gate["has_full_stats"]:
        for leader in leaders:
            leader.pop("win_rate", None)
            leader.pop("return_pct", None)

    # Anonymize
    for i, leader in enumerate(leaders):
        name = leader.get("username", "anon")
        if len(name) > 3:
            leader["username"] = name[:3] + "***"
        leader["rank"] = i + 1
        leader.pop("user_id", None)

    return {"leaders": leaders, "count": len(leaders)}
