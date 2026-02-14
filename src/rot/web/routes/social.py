"""Social intelligence routes.

HTML dashboards + JSON API endpoints for author tracking, manipulation detection,
sentiment propagation, and contrarian signals.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from rot.web.auth import get_current_user_optional
from rot.web.rate_limit import check_rate_limit, rate_limit_headers, require_api_auth
from rot.web.tier_gate import gate_social_access

router = APIRouter()


# ── HTML Pages ──────────────────────────────────────────


@router.get("/social")
async def social_dashboard(request: Request):
    """Social intelligence dashboard page."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_social_access(tier)
    db = request.app.state.db
    templates = request.app.state.templates

    leaderboard = []
    alerts = []
    propagation_leaders = []
    stats = {}

    if access.get("has_access"):
        if access.get("has_leaderboard"):
            leaderboard = await db.get_author_leaderboard(limit=25)
        if access.get("has_alerts"):
            alerts = await db.get_manipulation_alerts(limit=10, resolved=False)
        if access.get("has_propagation"):
            propagation_leaders = await db.get_leading_sources(hours=24.0)

        # Basic stats
        async with db.db.execute(
            "SELECT COUNT(*) as cnt FROM author_profiles WHERE (win_count + loss_count) >= 5"
        ) as cur:
            row = await cur.fetchone()
            stats["tracked_authors"] = row["cnt"] if row else 0

        async with db.db.execute(
            "SELECT COUNT(*) as cnt FROM author_predictions WHERE outcome IS NULL"
        ) as cur:
            row = await cur.fetchone()
            stats["pending_predictions"] = row["cnt"] if row else 0

        async with db.db.execute(
            "SELECT COUNT(*) as cnt FROM manipulation_alerts WHERE resolved = 0"
        ) as cur:
            row = await cur.fetchone()
            stats["active_alerts"] = row["cnt"] if row else 0

    return templates.TemplateResponse("social.html", {
        "request": request,
        "user": user,
        "access": access,
        "leaderboard": leaderboard,
        "alerts": alerts,
        "propagation_leaders": propagation_leaders,
        "stats": stats,
    })


@router.get("/social/author/{username}")
async def social_author_page(request: Request, username: str):
    """Author profile page."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_social_access(tier)
    db = request.app.state.db
    templates = request.app.state.templates

    if not access.get("has_profiles"):
        return templates.TemplateResponse("social_author.html", {
            "request": request,
            "user": user,
            "access": access,
            "author": None,
            "predictions": [],
        })

    # Try to find author
    author = await db.get_author_profile_by_username("reddit", username)
    predictions = []
    if author:
        predictions = await db.get_author_predictions(author["id"], limit=50)

    return templates.TemplateResponse("social_author.html", {
        "request": request,
        "user": user,
        "access": access,
        "author": author,
        "predictions": predictions,
    })


# ── JSON API Endpoints ──────────────────────────────────


@router.get("/api/v1/social/leaderboard")
async def api_leaderboard(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    min_predictions: int = Query(10, ge=1),
):
    """Author leaderboard JSON API."""
    api_user = await require_api_auth(request)
    await check_rate_limit(request, api_user)
    tier = api_user.get("tier", "free")
    access = gate_social_access(tier)

    if not access.get("has_leaderboard"):
        return JSONResponse(
            {"error": "Upgrade to Pro for social intelligence"},
            status_code=403,
            headers=rate_limit_headers(request),
        )

    db = request.app.state.db
    data = await db.get_author_leaderboard(limit=limit, offset=offset, min_predictions=min_predictions)
    return JSONResponse({"leaderboard": data, "count": len(data)}, headers=rate_limit_headers(request))


@router.get("/api/v1/social/author/{username}")
async def api_author(request: Request, username: str):
    """Author profile JSON API."""
    api_user = await require_api_auth(request)
    await check_rate_limit(request, api_user)
    tier = api_user.get("tier", "free")
    access = gate_social_access(tier)

    if not access.get("has_profiles"):
        return JSONResponse(
            {"error": "Upgrade to Premium for author profiles"},
            status_code=403,
            headers=rate_limit_headers(request),
        )

    db = request.app.state.db
    author = await db.get_author_profile_by_username("reddit", username)
    if not author:
        return JSONResponse({"error": "Author not found"}, status_code=404)

    predictions = await db.get_author_predictions(author["id"], limit=50)
    return JSONResponse(
        {"author": author, "predictions": predictions},
        headers=rate_limit_headers(request),
    )


@router.get("/api/v1/social/manipulation")
async def api_manipulation(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    resolved: Optional[bool] = None,
):
    """Manipulation alerts JSON API."""
    api_user = await require_api_auth(request)
    await check_rate_limit(request, api_user)
    tier = api_user.get("tier", "free")
    access = gate_social_access(tier)

    if not access.get("has_alerts"):
        return JSONResponse(
            {"error": "Upgrade to Premium for manipulation alerts"},
            status_code=403,
            headers=rate_limit_headers(request),
        )

    db = request.app.state.db
    alerts = await db.get_manipulation_alerts(limit=limit, resolved=resolved)
    return JSONResponse({"alerts": alerts, "count": len(alerts)}, headers=rate_limit_headers(request))


@router.get("/api/v1/social/propagation/{ticker}")
async def api_propagation(request: Request, ticker: str):
    """Sentiment propagation timeline JSON API."""
    api_user = await require_api_auth(request)
    await check_rate_limit(request, api_user)
    tier = api_user.get("tier", "free")
    access = gate_social_access(tier)

    if not access.get("has_propagation"):
        return JSONResponse(
            {"error": "Upgrade to Ultra for propagation tracking"},
            status_code=403,
            headers=rate_limit_headers(request),
        )

    db = request.app.state.db
    timeline = await db.get_propagation_timeline(ticker.upper())
    leaders = await db.get_leading_sources(hours=24.0)
    return JSONResponse(
        {"ticker": ticker.upper(), "timeline": timeline, "leading_sources": leaders},
        headers=rate_limit_headers(request),
    )


@router.get("/api/v1/social/contrarian")
async def api_contrarian(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    """Contrarian signals JSON API."""
    api_user = await require_api_auth(request)
    await check_rate_limit(request, api_user)
    tier = api_user.get("tier", "free")
    access = gate_social_access(tier)

    if not access.get("has_contrarian"):
        return JSONResponse(
            {"error": "Upgrade to Ultra for contrarian signals"},
            status_code=403,
            headers=rate_limit_headers(request),
        )

    db = request.app.state.db
    clusters = await db.get_author_clusters(min_similarity=0.5)
    return JSONResponse(
        {"contrarian_clusters": clusters, "count": len(clusters)},
        headers=rate_limit_headers(request),
    )
