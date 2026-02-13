"""Signal Quality Dashboard — Pro+ tier-gated analytics.

Shows category performance heatmap, source reliability, ML feature importance,
quality trends, suppression candidates, and confidence calibration.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_signal_quality_access

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/signal-quality", response_class=HTMLResponse)
async def signal_quality_dashboard(request: Request):
    """Signal quality analysis dashboard."""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    tier = user.get("tier", "free")
    access = gate_signal_quality_access(tier)

    if not access["has_access"]:
        return RedirectResponse(url="/pricing", status_code=302)

    # Get cached feedback analysis results
    analyzer = getattr(request.app.state, "feedback_analyzer", None)
    cache = getattr(request.app.state, "query_cache", None)

    results: dict = {}
    if analyzer:
        if cache:
            results = await cache.get_or_fetch(
                "feedback_analysis",
                lambda: _get_results(analyzer),
                ttl=300,
            )
        else:
            results = analyzer.get_cached_results() or {}

    # Build template context
    from rot.web.routes.dashboard import _base_context

    ctx = _base_context(request, user)
    ctx.update({
        "access": access,
        "has_data": bool(results.get("computed_at")),
        "category_performance": results.get("category_performance", []),
        "source_reliability": results.get("source_reliability", []),
        "feature_importance": results.get("feature_importance", [])[:10],
        "quality_trend": results.get("quality_trend", {}),
        "suppression_candidates": results.get("suppression_candidates", []),
        "calibration": results.get("calibration_detailed", []),
        "analysis_timestamp": results.get("computed_at"),
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("signal_quality.html", ctx)


async def _get_results(analyzer: object) -> dict:
    """Thin async wrapper for query_cache compatibility."""
    return getattr(analyzer, "_last_analysis", {}) or {}
