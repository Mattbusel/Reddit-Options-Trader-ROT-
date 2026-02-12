"""Unusual Activity Feed routes.

Provides:
  - /unusual-activity — HTML page showing signals with unusual options activity
  - /api/v1/unusual-activity — JSON feed with unusual flags
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_unusual_activity

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/unusual-activity", response_class=HTMLResponse)
async def unusual_activity_page(request: Request):
    """Unusual activity feed page."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    templates = request.app.state.templates
    db = request.app.state.db
    access = gate_unusual_activity(tier)

    signals = []
    if access["has_access"]:
        hours = access["max_hours"]
        signals = await db.get_unusual_activity_signals(hours=hours, limit=50)

        # Strip detail fields for non-premium
        if not access["has_detail"]:
            for s in signals:
                s.pop("unusual_detail", None)

    return templates.TemplateResponse("unusual_activity.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
        "signals": signals,
    })


@router.get("/api/v1/unusual-activity")
async def unusual_activity_json(
    request: Request,
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(50, ge=1, le=200),
):
    """JSON feed of signals with unusual options activity."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_unusual_activity(tier)

    if not access["has_access"]:
        return {"signals": [], "detail": "Upgrade to Pro for unusual activity data"}

    hours = min(hours, access["max_hours"])
    db = request.app.state.db
    signals = await db.get_unusual_activity_signals(hours=hours, limit=limit)

    # Strip detail for non-premium
    if not access["has_detail"]:
        for s in signals:
            s.pop("unusual_detail", None)

    return {
        "signals": signals,
        "count": len(signals),
        "hours": hours,
        "tier": tier,
    }
