"""Performance dashboard routes (premium+ tiers)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_performance_access

router = APIRouter()


@router.get("/performance", response_class=HTMLResponse)
async def performance_dashboard(request: Request):
    """Dedicated performance analytics page (premium+)."""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    tier = user.get("tier", "free")
    perf = gate_performance_access(tier)

    if not perf["has_performance_dashboard"]:
        return RedirectResponse(url="/pricing", status_code=302)

    db = request.app.state.db

    # Aggregate accuracy
    accuracy = await db.get_aggregate_accuracy(days=perf["accuracy_days"])

    # Accuracy over time chart data
    accuracy_chart = await db.get_accuracy_over_time(days=perf["accuracy_days"])

    # Strategy P&L (ultra only)
    strategy_pnl = None
    if perf["has_strategy_pnl"]:
        strategy_pnl = await db.get_strategy_pnl(days=perf["accuracy_days"])

    # Top/bottom performers
    performers = await db.get_performance_by_ticker(days=perf["accuracy_days"], limit=20)

    # Build context
    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "accuracy": accuracy,
        "accuracy_chart": accuracy_chart,
        "strategy_pnl": strategy_pnl,
        "performers": performers,
        "perf_access": perf,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("performance.html", ctx)
