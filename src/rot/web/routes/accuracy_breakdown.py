"""Historical Accuracy Breakdown by Event Type & Strategy (Premium+)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_performance_access

router = APIRouter()


@router.get("/accuracy-breakdown", response_class=HTMLResponse)
async def accuracy_breakdown(request: Request):
    """Accuracy breakdown by event type and strategy — Premium+ feature."""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    tier = user.get("tier", "free")
    perf = gate_performance_access(tier)

    if not perf.get("has_accuracy_breakdown"):
        return RedirectResponse(url="/pricing", status_code=302)

    db = request.app.state.db
    days = perf["accuracy_days"]

    # Get accuracy by event type and strategy
    by_event = await db.get_accuracy_by_event_type(days=days)
    by_strategy = await db.get_accuracy_by_strategy(days=days)

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "by_event": by_event,
        "by_strategy": by_strategy,
        "days": days,
        "perf_access": perf,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("accuracy_breakdown.html", ctx)
