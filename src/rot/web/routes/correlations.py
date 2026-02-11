"""Correlation Engine routes.

Provides:
  - /correlations — HTML explorer page
  - /api/v1/correlations/{ticker} — per-ticker correlation data
  - /api/v1/correlations/matrix — top correlated pairs globally
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_correlation_access

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/correlations", response_class=HTMLResponse)
async def correlations_page(request: Request):
    """Correlation explorer page."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    templates = request.app.state.templates
    db = request.app.state.db
    access = gate_correlation_access(tier)

    # Get top correlated pairs for the landing view
    matrix = []
    if access["has_correlation"]:
        matrix = await db.get_correlation_matrix(days=30, min_co=3, limit=20)

    # Mark that user explored correlations (for badges)
    if user:
        settings = user.get("settings", {})
        if isinstance(settings, str):
            import json
            try:
                settings = json.loads(settings)
            except Exception:
                settings = {}
        if not settings.get("used_correlations"):
            settings["used_correlations"] = True
            await db.update_user_settings(user["id"], settings)

    return templates.TemplateResponse("correlations.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
        "matrix": matrix,
    })


@router.get("/api/v1/correlations/matrix")
async def correlation_matrix(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=50),
):
    """Top correlated ticker pairs across all signals."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_correlation_access(tier)

    if not access["has_correlation"]:
        return {"pairs": [], "detail": "Upgrade to Pro for correlation data"}

    # Limit history range by tier
    if tier == "pro":
        days = min(days, 30)
    elif tier == "premium":
        days = min(days, 90)

    db = request.app.state.db
    pairs = await db.get_correlation_matrix(days=days, min_co=3, limit=limit)

    return {
        "pairs": pairs,
        "count": len(pairs),
        "days": days,
        "tier": tier,
    }


@router.get("/api/v1/correlations/{ticker}")
async def ticker_correlations(
    request: Request,
    ticker: str,
    days: int = Query(90, ge=1, le=365),
    window_hours: int = Query(4, ge=1, le=24),
):
    """Tickers that fire signals within N hours of the given ticker."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_correlation_access(tier)

    if not access["has_correlation"]:
        return {"correlations": [], "detail": "Upgrade to Pro for correlation data"}

    # Limit history range by tier
    if tier == "pro":
        days = min(days, 30)
    elif tier == "premium":
        days = min(days, 90)

    ticker = ticker.upper().strip()
    db = request.app.state.db
    correlations = await db.get_ticker_correlations(
        ticker=ticker, days=days, window_hours=window_hours,
    )

    # Add strength scores for premium+
    for c in correlations:
        total = c.get("co_fires", 0)
        same = c.get("same_stance", 0)
        c["stance_agreement_pct"] = round((same / total * 100), 1) if total > 0 else 0
        if not access["has_strength_scores"]:
            c.pop("same_stance", None)
            c.pop("avg_confidence", None)

    return {
        "ticker": ticker,
        "correlations": correlations,
        "count": len(correlations),
        "days": days,
        "window_hours": window_hours,
    }
