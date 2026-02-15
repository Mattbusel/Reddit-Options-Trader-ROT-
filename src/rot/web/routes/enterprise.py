"""Enterprise tier routes.

Provides:
  - /enterprise — Enterprise info page or dashboard (with analytics)
  - /api/v1/enterprise/data-export — Bulk historical data export (CSV/JSON)
  - /api/v1/enterprise/sponsored/submit — Submit press release for priority analysis
  - /api/v1/enterprise/sponsored/status — Check sponsored signal statuses
  - /api/v1/enterprise/usage — Enterprise usage dashboard data
  - /api/v1/enterprise/analytics/signals — Signal stats API
  - /api/v1/enterprise/analytics/performance — Performance stats API
  - /api/v1/enterprise/analytics/trends — Trend analysis API
  - /api/v1/enterprise/analytics/sources — Source analysis API
  - /api/v1/enterprise/lineage/{signal_id} — Signal lineage API
"""
from __future__ import annotations

import csv
import io
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from rot.web.auth import get_current_user_optional, require_tier

log = logging.getLogger(__name__)

router = APIRouter()


# ── Models ──

class SponsoredSubmitRequest(BaseModel):
    company_name: str
    ticker: str
    press_url: str
    press_content: str = ""
    notes: str = ""
    priority: int = 0  # 0=normal, 1=high


class DataExportRequest(BaseModel):
    export_type: str = "signals"  # "signals" | "performance" | "full"
    format: str = "csv"  # "csv" | "json"
    ticker: Optional[str] = None
    date_from: Optional[float] = None
    date_to: Optional[float] = None
    limit: int = 100000
    include_lineage: bool = False


# ── Enterprise page (HTML) ──

@router.get("/enterprise", response_class=HTMLResponse)
async def enterprise_page(request: Request):
    """Render the enterprise dashboard (enterprise users) or info page (others)."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    templates = request.app.state.templates

    ctx = {
        "request": request,
        "user": user,
        "tier": tier,
        "stripe_enabled": bool(request.app.state.settings.stripe.secret_key),
        "is_enterprise": tier == "enterprise",
        "json_dumps": json.dumps,
    }

    if tier == "enterprise" and user:
        db = request.app.state.db
        sponsored = await db.get_sponsored_signals(user_id=user["id"], limit=20)
        exports = await db.get_data_exports(user_id=user["id"], limit=10)
        since_24h = time.time() - 86400
        api_count = await db.get_api_call_count(user["id"], since_24h)

        # Analytics overview
        analytics_data = {}
        try:
            from rot.export.analytics import AnalyticsAPI
            analytics = AnalyticsAPI()
            signals = await db.get_enterprise_analytics_signals(
                date_from=time.time() - 86400 * 7,
            )
            analytics_data = {
                "signal_stats": analytics.compute_signal_stats(signals),
                "performance_stats": analytics.compute_performance_stats(signals),
                "source_stats": analytics.compute_source_analysis(signals),
            }
        except Exception:
            log.exception("Enterprise analytics failed")

        ctx.update({
            "sponsored_signals": sponsored,
            "data_exports": exports,
            "api_usage_24h": api_count,
            "api_limit_day": request.app.state.settings.tier_limits.enterprise_api_limit_day,
            "analytics": analytics_data,
        })

    return templates.TemplateResponse("enterprise.html", ctx)


# ── Data Export ──

@router.post("/api/v1/enterprise/data-export")
async def enterprise_data_export(body: DataExportRequest, request: Request):
    """Bulk data export for enterprise data licensing. Enterprise only."""
    user = await require_tier("enterprise")(request)
    db = request.app.state.db

    rows = await db.get_full_signal_export(
        ticker=body.ticker,
        date_from=body.date_from,
        date_to=body.date_to,
        limit=body.limit,
    )

    # Optionally include lineage
    lineage_data = None
    if body.include_lineage and rows:
        try:
            from rot.export.lineage import LineageBuilder
            builder = LineageBuilder()
            lineage_data = [l.to_dict() for l in builder.build_batch_lineage(rows[:500])]
        except Exception:
            log.exception("Lineage build failed")

    # Track the export
    await db.record_data_export(
        user_id=user["id"],
        export_type=body.export_type,
        fmt=body.format,
        row_count=len(rows),
        filters={"ticker": body.ticker, "date_from": body.date_from, "date_to": body.date_to},
    )

    if body.format == "json":
        result = {"ok": True, "count": len(rows), "data": rows}
        if lineage_data:
            result["lineage"] = lineage_data
        return result

    # CSV streaming response
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "id", "ticker", "stance", "event_type", "confidence", "trend_score",
        "quality_score", "strategy", "subreddit", "post_title", "created_at",
        "price_at_signal", "price_1h", "price_4h", "price_1d", "price_1w",
        "max_gain_pct", "max_loss_pct", "sponsored", "sponsored_by",
    ]
    writer.writerow(headers)
    for r in rows:
        created_dt = ""
        if r.get("created_at"):
            created_dt = datetime.fromtimestamp(
                r["created_at"], tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")
        writer.writerow([
            r.get("id", ""), r.get("ticker", ""), r.get("stance", ""),
            r.get("event_type", ""), r.get("confidence", ""), r.get("trend_score", ""),
            r.get("quality_score", ""), r.get("strategy", ""), r.get("subreddit", ""),
            r.get("post_title", ""), created_dt,
            r.get("price_at_signal", ""), r.get("price_1h", ""), r.get("price_4h", ""),
            r.get("price_1d", ""), r.get("price_1w", ""),
            r.get("max_gain_pct", ""), r.get("max_loss_pct", ""),
            r.get("sponsored", 0), r.get("sponsored_by", ""),
        ])
    output.seek(0)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"rot_enterprise_export_{date_str}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Sponsored Signals ──

@router.post("/api/v1/enterprise/sponsored/submit")
async def submit_sponsored_signal(body: SponsoredSubmitRequest, request: Request):
    """Submit a press release / IR document for priority ROT analysis."""
    user = await require_tier("enterprise")(request)
    db = request.app.state.db
    settings = request.app.state.settings

    pending = await db.get_pending_sponsored_count(user["id"])
    max_pending = settings.sponsored.max_pending_per_user
    if pending >= max_pending:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum {max_pending} pending sponsored signals. Wait for current ones to be analyzed.",
        )

    if not body.ticker or not body.company_name:
        raise HTTPException(status_code=400, detail="company_name and ticker are required")

    sponsored_id = await db.create_sponsored_signal(
        user_id=user["id"],
        data={
            "company_name": body.company_name,
            "ticker": body.ticker,
            "press_url": body.press_url,
            "press_content": body.press_content,
            "notes": body.notes,
            "priority": body.priority,
        },
    )

    log.info("Sponsored signal submitted: id=%s ticker=%s company=%s user=%s",
             sponsored_id, body.ticker, body.company_name, user["id"])

    return {"ok": True, "sponsored_id": sponsored_id, "status": "pending"}


@router.get("/api/v1/enterprise/sponsored/status")
async def sponsored_signal_status(request: Request):
    """Get status of all sponsored signal submissions for the current user."""
    user = await require_tier("enterprise")(request)
    db = request.app.state.db
    signals = await db.get_sponsored_signals(user_id=user["id"], limit=50)
    return {"ok": True, "sponsored_signals": signals}


# ── Usage Dashboard ──

@router.get("/api/v1/enterprise/usage")
async def enterprise_usage(request: Request):
    """Get enterprise usage statistics."""
    user = await require_tier("enterprise")(request)
    db = request.app.state.db
    settings = request.app.state.settings

    since_24h = time.time() - 86400
    api_count_24h = await db.get_api_call_count(user["id"], since_24h)
    exports = await db.get_data_exports(user_id=user["id"], limit=50)
    sponsored = await db.get_sponsored_signals(user_id=user["id"], limit=50)

    limit = settings.tier_limits.enterprise_api_limit_day
    return {
        "ok": True,
        "api_usage": {
            "calls_24h": api_count_24h,
            "limit_day": limit,
            "remaining": max(0, limit - api_count_24h),
        },
        "data_exports": {
            "total": len(exports),
            "recent": exports[:10],
        },
        "sponsored_signals": {
            "total": len(sponsored),
            "pending": len([s for s in sponsored if s.get("status") == "pending"]),
            "completed": len([s for s in sponsored if s.get("status") == "completed"]),
        },
    }


# ── Analytics API ──

@router.get("/api/v1/enterprise/analytics/signals")
async def analytics_signals(
    request: Request,
    days: int = Query(7, ge=1, le=365),
):
    """Signal statistics. Enterprise only."""
    await require_tier("enterprise")(request)
    db = request.app.state.db

    from rot.export.analytics import AnalyticsAPI
    signals = await db.get_enterprise_analytics_signals(
        date_from=time.time() - days * 86400,
    )
    api = AnalyticsAPI()
    return {"ok": True, "stats": api.compute_signal_stats(signals)}


@router.get("/api/v1/enterprise/analytics/performance")
async def analytics_performance(
    request: Request,
    days: int = Query(7, ge=1, le=365),
):
    """Performance statistics. Enterprise only."""
    await require_tier("enterprise")(request)
    db = request.app.state.db

    from rot.export.analytics import AnalyticsAPI
    signals = await db.get_enterprise_analytics_signals(
        date_from=time.time() - days * 86400,
    )
    api = AnalyticsAPI()
    return {"ok": True, "stats": api.compute_performance_stats(signals)}


@router.get("/api/v1/enterprise/analytics/trends")
async def analytics_trends(
    request: Request,
    days: int = Query(7, ge=1, le=365),
    bucket_hours: int = Query(24, ge=1, le=168),
):
    """Signal volume trends. Enterprise only."""
    await require_tier("enterprise")(request)
    db = request.app.state.db

    from rot.export.analytics import AnalyticsAPI
    signals = await db.get_enterprise_analytics_signals(
        date_from=time.time() - days * 86400,
    )
    api = AnalyticsAPI()
    return {"ok": True, "trends": api.compute_trend_analysis(signals, bucket_hours=bucket_hours)}


@router.get("/api/v1/enterprise/analytics/sources")
async def analytics_sources(
    request: Request,
    days: int = Query(7, ge=1, le=365),
):
    """Source breakdown. Enterprise only."""
    await require_tier("enterprise")(request)
    db = request.app.state.db

    from rot.export.analytics import AnalyticsAPI
    signals = await db.get_enterprise_analytics_signals(
        date_from=time.time() - days * 86400,
    )
    api = AnalyticsAPI()
    return {"ok": True, "sources": api.compute_source_analysis(signals)}


@router.get("/api/v1/enterprise/lineage/{signal_id}")
async def signal_lineage(
    request: Request,
    signal_id: str = Path(...),
):
    """Get full provenance chain for a signal. Enterprise only."""
    await require_tier("enterprise")(request)
    db = request.app.state.db

    from rot.export.lineage import LineageBuilder

    # Fetch signal
    query = "SELECT * FROM signals WHERE id = ?"
    async with db.db.execute(query, (signal_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Signal not found")
        signal = dict(row)

    builder = LineageBuilder()
    lineage = builder.build_lineage(signal)
    return {"ok": True, "lineage": lineage.to_dict()}
