"""Confidence Calibration Report (Premium+)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_performance_access

router = APIRouter()


@router.get("/confidence-calibration", response_class=HTMLResponse)
async def confidence_calibration(request: Request):
    """Confidence calibration — shows expected vs actual win rate by decile."""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    tier = user.get("tier", "free")
    perf = gate_performance_access(tier)

    if not perf.get("has_confidence_calibration"):
        return RedirectResponse(url="/pricing", status_code=302)

    db = request.app.state.db
    days = perf["accuracy_days"]

    calibration = await db.get_confidence_calibration(days=days)

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "calibration": calibration,
        "days": days,
        "perf_access": perf,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("confidence_calibration.html", ctx)
