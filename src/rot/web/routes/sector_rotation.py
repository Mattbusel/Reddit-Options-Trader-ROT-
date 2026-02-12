"""Sector Rotation Insights (Premium+)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_sector_rotation_access

router = APIRouter()


@router.get("/sector-rotation", response_class=HTMLResponse)
async def sector_rotation(request: Request):
    """Sector rotation insights with signal flow and performance overlay."""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    tier = user.get("tier", "free")
    access = gate_sector_rotation_access(tier)

    if not access["has_access"]:
        return RedirectResponse(url="/pricing", status_code=302)

    db = request.app.state.db
    days = access["max_days"]

    # Get sector data with performance overlay
    if access["has_performance_overlay"]:
        sectors = await db.get_sector_rotation_with_performance(days=days)
    else:
        sectors = await db.get_sector_rotation_data(days=days)

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "sectors": sectors,
        "days": days,
        "access": access,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("sector_rotation.html", ctx)
