"""
Achievement Badges & Streaks routes.

Provides:
  - /badges — HTML page showing all badges and progress
  - /api/v1/badges/progress — Get badge progress for current user
  - /api/v1/badges/leaderboard — Get badge leaderboard
  - /api/v1/badges/check — Recalculate badge state for current user (legacy compat)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from rot.web.auth import get_current_user_optional, require_user
from rot.gamification import BadgeTracker, BADGE_REGISTRY, GamificationLeaderboard

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/badges", response_class=HTMLResponse)
async def badges_page(request: Request):
    """Badge showcase page with real gamification data."""
    user = await get_current_user_optional(request)
    templates = request.app.state.templates
    db = request.app.state.db

    badges = []
    stats = {}
    leaderboard = []

    if user:
        tracker = BadgeTracker(db)

        # Get user stats
        user_stats = await db.get_user_stats(user["id"])
        if user_stats:
            stats = user_stats.to_dict()
            # Map to template-expected field names
            stats["streak_count"] = stats["current_streak_days"]
            stats["streak_best"] = stats["longest_streak_days"]
        else:
            stats = {
                "total_logins": 0,
                "current_streak_days": 0,
                "longest_streak_days": 0,
                "streak_count": 0,  # Template compatibility
                "streak_best": 0,  # Template compatibility
                "signals_viewed": 0,
                "trades_executed": 0,
                "predictions_made": 0,
                "predictions_correct": 0,
                "total_badge_points": 0,
                "badges_unlocked": 0,
            }

        # Get badge progress
        progress_list = await tracker.get_badge_progress(user["id"])

        # Convert to display format
        for progress in progress_list:
            from rot.gamification import get_badge

            badge = get_badge(progress.badge_id)
            if badge:
                badges.append(
                    {
                        "id": badge.id,
                        "name": badge.name,
                        "description": badge.description,
                        "icon": badge.icon_emoji,
                        "category": badge.category.capitalize(),
                        "rarity": badge.rarity.capitalize(),
                        "points": badge.points,
                        "earned": progress.unlocked,
                        "progress": progress.current_value,
                        "target": progress.threshold,
                        "pct": int(progress.progress_pct),
                        "unlocked_at": progress.unlocked_at,
                    }
                )

        # Get leaderboard
        lb = GamificationLeaderboard(db)
        leaderboard = await lb.get_top_by_points(limit=10)

    else:
        # Logged out - show all badges as locked
        for badge in BADGE_REGISTRY:
            badges.append(
                {
                    "id": badge.id,
                    "name": badge.name,
                    "description": badge.description,
                    "icon": badge.icon_emoji,
                    "category": badge.category.capitalize(),
                    "rarity": badge.rarity.capitalize(),
                    "points": badge.points,
                    "earned": False,
                    "progress": 0,
                    "target": badge.unlock_criteria.get("threshold", 1),
                    "pct": 0,
                    "unlocked_at": None,
                }
            )

    return templates.TemplateResponse(
        "badges.html",
        {
            "request": request,
            "user": user,
            "tier": (user or {}).get("tier", "free"),
            "badges": badges,
            "stats": stats,
            "leaderboard": leaderboard,
            "total_earned": sum(1 for b in badges if b.get("earned")),
            "total_badges": len(badges),
        },
    )


@router.get("/api/v1/badges/progress")
async def badge_progress(request: Request) -> JSONResponse:
    """Get badge progress for current user."""
    user = await require_user(request)
    db = request.app.state.db

    tracker = BadgeTracker(db)
    progress_list = await tracker.get_badge_progress(user["id"])

    return JSONResponse([p.to_dict() for p in progress_list])


@router.get("/api/v1/badges/leaderboard")
async def badge_leaderboard(
    request: Request,
    sort_by: str = "points",
    limit: int = 10,
) -> JSONResponse:
    """Get badge leaderboard."""
    db = request.app.state.db

    leaderboard = GamificationLeaderboard(db)
    top_users = await leaderboard.get_top_by(sort_by, limit)

    return JSONResponse(top_users)


@router.get("/api/v1/badges/check")
async def check_badges(request: Request):
    """
    Recalculate and return badge state for current user.

    This endpoint maintains backward compatibility with the old badge system
    while using the new gamification engine under the hood.
    """
    user = await require_user(request)
    db = request.app.state.db

    tracker = BadgeTracker(db)

    # Get current stats
    user_stats = await db.get_user_stats(user["id"])
    if not user_stats:
        # Create initial stats
        import time

        await db.create_user_stats(user["id"], time.time())
        user_stats = await db.get_user_stats(user["id"])

    # Evaluate badges
    new_badges = await tracker.evaluate_badge_eligibility(user["id"])

    # Get all unlocked badges
    unlocked_badge_ids = await db.get_user_badges(user["id"])

    # Build earned dict for compatibility
    earned = {}
    for badge in BADGE_REGISTRY:
        earned[badge.id] = badge.id in unlocked_badge_ids

    return {
        "ok": True,
        "earned": earned,
        "total_earned": len(unlocked_badge_ids),
        "new_badges": new_badges,
        "streak_count": user_stats.current_streak_days,
        "streak_best": user_stats.longest_streak_days,
        "total_points": user_stats.total_badge_points,
    }
