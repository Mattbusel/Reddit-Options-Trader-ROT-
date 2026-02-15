"""Correlation Engine routes.

Provides:
  - /correlations — HTML explorer page with heatmap, clusters, lead-lag
  - /api/v1/correlations/matrix — top correlated pairs globally
  - /api/v1/correlations/{ticker} — per-ticker correlation data
  - /api/v1/correlations/clusters — ticker cluster detection
  - /api/v1/correlations/lead-lag — lead-lag pair detection
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from rot.web.auth import get_current_user_optional
from rot.web.rate_limit import check_rate_limit, require_api_auth, rate_limit_headers
from rot.web.tier_gate import gate_correlation_access

log = logging.getLogger(__name__)

router = APIRouter()


async def _get_correlation_analyzer_data(db, days: int) -> dict:
    """Fetch signals and run correlation analysis. Returns dict of results."""
    from rot.analysis.correlations import CorrelationAnalyzer

    signals = await db.get_signal_pairs_for_correlation(days=days)
    if not signals:
        return {"matrix": None, "clusters": [], "lead_lag": [], "network": None}

    analyzer = CorrelationAnalyzer(min_co_fires=3)
    matrix = analyzer.compute_signal_correlations(signals, min_signals=3)
    clusters = analyzer.detect_clusters(matrix, threshold=0.4)
    lead_lag = analyzer.compute_lead_lag(signals, days=days, min_occurrences=3)

    counts = await db.get_ticker_signal_counts(days=days)
    network = analyzer.build_network_data(matrix, min_correlation=0.3, signal_counts=counts)

    return {
        "matrix": matrix,
        "clusters": clusters,
        "lead_lag": lead_lag,
        "network": network,
    }


@router.get("/correlations", response_class=HTMLResponse)
async def correlations_page(request: Request):
    """Correlation explorer page with matrix, clusters, and lead-lag."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    templates = request.app.state.templates
    db = request.app.state.db
    access = gate_correlation_access(tier)

    # Get correlation data
    pairs = []
    clusters = []
    lead_lag = []
    network_data = {"nodes": [], "edges": []}

    if access["has_correlation"]:
        try:
            data = await _get_correlation_analyzer_data(db, days=30)
            if data["matrix"]:
                pairs = [p.to_dict() for p in data["matrix"].pairs[:20]]
            clusters = [c.to_dict() for c in data["clusters"]]
            lead_lag = [ll.to_dict() for ll in data["lead_lag"][:15]]
            if data["network"]:
                network_data = data["network"].to_dict()
        except Exception:
            log.exception("Correlation analysis failed")
            # Fall back to legacy DB query
            pairs_raw = await db.get_correlation_matrix(days=30, min_co=3, limit=20)
            for p in pairs_raw:
                total = p.get("co_fires", 0)
                same = p.get("same_stance", 0)
                pairs.append({
                    "ticker_a": p["ticker_a"],
                    "ticker_b": p["ticker_b"],
                    "co_fires": total,
                    "same_stance_pct": round(same / total * 100, 1) if total > 0 else 0,
                    "correlation": round(same / total, 2) if total > 0 else 0,
                    "sample_size": total,
                })

    # Mark badge
    if user:
        settings = user.get("settings", {})
        if isinstance(settings, str):
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
        "pairs": pairs,
        "clusters": clusters,
        "lead_lag": lead_lag,
        "network_data": network_data,
        "json_dumps": json.dumps,
    })


@router.get("/api/v1/correlations/matrix")
async def correlation_matrix(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=50),
):
    """Top correlated ticker pairs across all signals. Requires paid subscription."""
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_correlation_access(tier)

    if not access["has_correlation"]:
        return JSONResponse(
            content={"pairs": [], "detail": "Upgrade to Pro for correlation data"},
            status_code=403,
            headers=rate_limit_headers(user),
        )

    if tier == "pro":
        days = min(days, 30)
    elif tier == "premium":
        days = min(days, 90)

    db = request.app.state.db

    try:
        from rot.analysis.correlations import CorrelationAnalyzer
        signals = await db.get_signal_pairs_for_correlation(days=days)
        analyzer = CorrelationAnalyzer(min_co_fires=3)
        matrix = analyzer.compute_signal_correlations(signals, min_signals=3)
        pairs = [p.to_dict() for p in matrix.pairs[:limit]]
    except Exception:
        # Fall back to legacy
        pairs_raw = await db.get_correlation_matrix(days=days, min_co=3, limit=limit)
        pairs = pairs_raw

    return JSONResponse(
        content={"pairs": pairs, "count": len(pairs), "days": days, "tier": tier},
        headers=rate_limit_headers(user),
    )


@router.get("/api/v1/correlations/{ticker}")
async def ticker_correlations(
    request: Request,
    ticker: str,
    days: int = Query(90, ge=1, le=365),
    window_hours: int = Query(4, ge=1, le=24),
):
    """Tickers that fire signals within N hours of the given ticker."""
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_correlation_access(tier)

    if not access["has_correlation"]:
        return JSONResponse(
            content={"correlations": [], "detail": "Upgrade to Pro for correlation data"},
            status_code=403,
            headers=rate_limit_headers(user),
        )

    if tier == "pro":
        days = min(days, 30)
    elif tier == "premium":
        days = min(days, 90)

    ticker = ticker.upper().strip()
    db = request.app.state.db
    correlations = await db.get_ticker_correlations(
        ticker=ticker, days=days, window_hours=window_hours,
    )

    for c in correlations:
        total = c.get("co_fires", 0)
        same = c.get("same_stance", 0)
        c["stance_agreement_pct"] = round((same / total * 100), 1) if total > 0 else 0
        if not access["has_strength_scores"]:
            c.pop("same_stance", None)
            c.pop("avg_confidence", None)

    return JSONResponse(
        content={
            "ticker": ticker,
            "correlations": correlations,
            "count": len(correlations),
            "days": days,
            "window_hours": window_hours,
        },
        headers=rate_limit_headers(user),
    )


@router.get("/api/v1/correlations/clusters")
async def correlation_clusters(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    threshold: float = Query(0.4, ge=0.1, le=1.0),
):
    """Ticker clusters based on signal correlation."""
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_correlation_access(tier)

    if not access["has_correlation"]:
        return JSONResponse(
            content={"clusters": [], "detail": "Upgrade to Pro"},
            status_code=403,
            headers=rate_limit_headers(user),
        )

    db = request.app.state.db
    try:
        from rot.analysis.correlations import CorrelationAnalyzer
        signals = await db.get_signal_pairs_for_correlation(days=days)
        analyzer = CorrelationAnalyzer(min_co_fires=3)
        matrix = analyzer.compute_signal_correlations(signals, min_signals=3)
        clusters = analyzer.detect_clusters(matrix, threshold=threshold)
        result = [c.to_dict() for c in clusters]
    except Exception:
        result = []

    return JSONResponse(
        content={"clusters": result, "count": len(result), "days": days},
        headers=rate_limit_headers(user),
    )


@router.get("/api/v1/correlations/lead-lag")
async def correlation_lead_lag(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    """Lead-lag pair detection between tickers."""
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    access = gate_correlation_access(tier)

    if not access["has_correlation"]:
        return JSONResponse(
            content={"lead_lag": [], "detail": "Upgrade to Pro"},
            status_code=403,
            headers=rate_limit_headers(user),
        )

    db = request.app.state.db
    try:
        from rot.analysis.correlations import CorrelationAnalyzer
        signals = await db.get_signal_pairs_for_correlation(days=days)
        analyzer = CorrelationAnalyzer()
        lead_lag = analyzer.compute_lead_lag(signals, days=days, min_occurrences=3)
        result = [ll.to_dict() for ll in lead_lag[:20]]
    except Exception:
        result = []

    return JSONResponse(
        content={"lead_lag": result, "count": len(result), "days": days},
        headers=rate_limit_headers(user),
    )
