"""Sector Rotation Intelligence (Pro+).

Provides:
  - /sector-rotation — main dashboard with rankings, flow chart, drill-down
  - /sector-rotation/drill-down/{sector} — HTMX partial: ticker breakdown
  - /sector-rotation/timeline — HTMX partial: rotation timeline data
  - /api/v1/sectors/rankings — JSON API: sector rankings with momentum
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_sector_rotation_access

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/sector-rotation", response_class=HTMLResponse)
async def sector_rotation(request: Request):
    """Sector rotation insights with momentum, rankings, and drill-down."""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    tier = user.get("tier", "free")
    access = gate_sector_rotation_access(tier)

    if not access["has_access"]:
        return RedirectResponse(url="/pricing", status_code=302)

    db = request.app.state.db
    days = access["max_days"]

    # Get ranked sectors with performance
    sectors = await db.get_sector_performance_ranked(days=days)

    # Compute momentum & capital flow if we have enough data
    momentum_data = []
    flow_data = []
    if sectors:
        try:
            from rot.analysis.sector import SectorAnalyzer
            analyzer = SectorAnalyzer(min_signals=2)

            # Build sector_data from DB signals for analysis
            sector_signals = {}
            for s in sectors:
                sector_signals[s["sector"]] = {
                    "total_signals": s["total_signals"],
                    "bullish": s["bullish"],
                    "bearish": s["bearish"],
                    "avg_confidence": s.get("avg_confidence", 0),
                }

            # Fetch time-series data for momentum
            ts_data = await db.get_sector_time_series(days=days)
            if ts_data:
                # Group by sector for momentum analysis
                sector_ts: dict = {}
                for row in ts_data:
                    sec = row.get("sector", "")
                    if sec:
                        sector_ts.setdefault(sec, []).append({
                            "created_at": row["timestamp"],
                            "stance": "bullish" if row.get("bullish", 0) > row.get("bearish", 0) else "bearish",
                            "confidence": row.get("avg_confidence", 0.5),
                        })

                momentum_data = [
                    m.to_dict() for m in analyzer.compute_sector_momentum(sector_ts, days)
                ]

                flow_data = [
                    f.to_dict() for f in analyzer.compute_capital_flow(sector_ts, days)
                ]
        except Exception:
            log.exception("Sector rotation analysis failed (best-effort; continuing without data)")
            pass  # Analysis is best-effort

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "sectors": sectors,
        "days": days,
        "access": access,
        "momentum": momentum_data,
        "flow_data": flow_data,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("sector_rotation.html", ctx)


@router.get("/sector-rotation/drill-down/{sector}", response_class=HTMLResponse)
async def sector_drill_down(request: Request, sector: str):
    """HTMX partial: ticker breakdown within a sector."""
    user = await get_current_user_optional(request)
    if not user:
        return HTMLResponse("<p class='text-gray-500'>Login required</p>")

    tier = user.get("tier", "free")
    access = gate_sector_rotation_access(tier)
    if not access["has_access"]:
        return HTMLResponse("<p class='text-gray-500'>Upgrade required</p>")

    db = request.app.state.db
    days = access["max_days"]
    tickers = await db.get_sector_ticker_breakdown(sector, days=days)

    templates = request.app.state.templates
    return templates.TemplateResponse("sector_drill_down_partial.html", {
        "request": request,
        "sector": sector,
        "tickers": tickers,
        "access": access,
    })


@router.get("/api/v1/sectors/rankings")
async def sector_rankings_api(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    """JSON API: sector rankings with momentum."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_sector_rotation_access(tier)

    if not access["has_access"]:
        return JSONResponse(
            content={"sectors": [], "detail": "Upgrade to Pro for sector data"},
            status_code=403,
        )

    days = min(days, access["max_days"])
    db = request.app.state.db
    sectors = await db.get_sector_performance_ranked(days=days)

    return JSONResponse(content={
        "sectors": sectors,
        "count": len(sectors),
        "days": days,
        "tier": tier,
    })
