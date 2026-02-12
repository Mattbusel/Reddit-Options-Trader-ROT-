"""Achievement Badges & Streaks routes.

Provides:
  - /badges — HTML page showing all badges and progress
  - /api/v1/badges/check — recalculate badge state for current user
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional, require_user

log = logging.getLogger(__name__)

router = APIRouter()

# ── Badge Definitions ──

BADGE_DEFINITIONS = [
    # Activity badges
    {
        "id": "first_signal",
        "name": "First Look",
        "description": "Viewed your first signal",
        "icon": "&#128065;",
        "category": "Activity",
        "check": lambda stats: stats.get("signals_viewed", 0) >= 1,
        "progress": lambda stats: min(stats.get("signals_viewed", 0), 1),
        "target": 1,
    },
    {
        "id": "signal_100",
        "name": "Signal Hawk",
        "description": "Viewed 100 signals",
        "icon": "&#129413;",
        "category": "Activity",
        "check": lambda stats: stats.get("signals_viewed", 0) >= 100,
        "progress": lambda stats: min(stats.get("signals_viewed", 0), 100),
        "target": 100,
    },
    {
        "id": "signal_500",
        "name": "Signal Addict",
        "description": "Viewed 500 signals",
        "icon": "&#127775;",
        "category": "Activity",
        "check": lambda stats: stats.get("signals_viewed", 0) >= 500,
        "progress": lambda stats: min(stats.get("signals_viewed", 0), 500),
        "target": 500,
    },
    # Streak badges
    {
        "id": "streak_3",
        "name": "Getting Hooked",
        "description": "3-day login streak",
        "icon": "&#128293;",
        "category": "Streaks",
        "check": lambda stats: stats.get("streak_best", 0) >= 3,
        "progress": lambda stats: min(stats.get("streak_best", 0), 3),
        "target": 3,
    },
    {
        "id": "streak_7",
        "name": "Weekly Warrior",
        "description": "7-day login streak",
        "icon": "&#9889;",
        "category": "Streaks",
        "check": lambda stats: stats.get("streak_best", 0) >= 7,
        "progress": lambda stats: min(stats.get("streak_best", 0), 7),
        "target": 7,
    },
    {
        "id": "streak_30",
        "name": "Iron Hands",
        "description": "30-day login streak",
        "icon": "&#128170;",
        "category": "Streaks",
        "check": lambda stats: stats.get("streak_best", 0) >= 30,
        "progress": lambda stats: min(stats.get("streak_best", 0), 30),
        "target": 30,
    },
    # Paper trading badges
    {
        "id": "first_paper",
        "name": "Paper Hands",
        "description": "Made your first paper trade",
        "icon": "&#128176;",
        "category": "Paper Trading",
        "check": lambda stats: stats.get("paper_trades", 0) >= 1,
        "progress": lambda stats: min(stats.get("paper_trades", 0), 1),
        "target": 1,
    },
    {
        "id": "paper_10k",
        "name": "Paper Millionaire",
        "description": "Earned $10K in paper profit",
        "icon": "&#128181;",
        "category": "Paper Trading",
        "check": lambda stats: stats.get("paper_total_pnl", 0) >= 10000,
        "progress": lambda stats: max(min(stats.get("paper_total_pnl", 0), 10000), 0),
        "target": 10000,
    },
    # Discovery badges
    {
        "id": "watchlist_5",
        "name": "Watchful Eye",
        "description": "Added 5 tickers to your watchlist",
        "icon": "&#128270;",
        "category": "Discovery",
        "check": lambda stats: stats.get("watchlist_count", 0) >= 5,
        "progress": lambda stats: min(stats.get("watchlist_count", 0), 5),
        "target": 5,
    },
    {
        "id": "correlation_explorer",
        "name": "Pattern Finder",
        "description": "Used the Correlation Explorer",
        "icon": "&#128300;",
        "category": "Discovery",
        "check": lambda stats: stats.get("used_correlations", False),
        "progress": lambda stats: 1 if stats.get("used_correlations", False) else 0,
        "target": 1,
    },
]


def _compute_streak(last_visit: float, current_streak: int) -> tuple[int, bool]:
    """Compute updated streak. Returns (new_streak, was_reset)."""
    if not last_visit:
        return 1, False
    now = time.time()
    hours_since = (now - last_visit) / 3600
    if hours_since < 24:
        # Same day visit — no change
        return current_streak, False
    elif hours_since < 48:
        # Next-day visit — increment
        return current_streak + 1, False
    else:
        # Streak broken
        return 1, True


async def _gather_stats(db, user: dict) -> dict:
    """Gather all stats needed for badge evaluation."""
    settings = user.get("settings", {})
    if isinstance(settings, str):
        import json
        try:
            settings = json.loads(settings)
        except Exception:
            settings = {}

    stats = {
        "signals_viewed": settings.get("signals_viewed", 0),
        "streak_count": settings.get("streak_count", 0),
        "streak_best": settings.get("streak_best", 0),
        "paper_trades": 0,
        "paper_total_pnl": 0,
        "watchlist_count": len(settings.get("watchlist", [])),
        "used_correlations": settings.get("used_correlations", False),
    }

    # Get paper trading stats
    portfolio = await db.get_paper_portfolio(user["id"])
    if portfolio:
        stats["paper_trades"] = portfolio.get("total_trades", 0)
        stats["paper_total_pnl"] = portfolio.get("total_pnl", 0)

    return stats


@router.get("/badges", response_class=HTMLResponse)
async def badges_page(request: Request):
    """Badge showcase page."""
    user = await get_current_user_optional(request)
    templates = request.app.state.templates
    db = request.app.state.db

    badges = []
    stats = {}

    if user:
        stats = await _gather_stats(db, user)

        # Update streak
        settings = user.get("settings", {})
        if isinstance(settings, str):
            import json
            try:
                settings = json.loads(settings)
            except Exception:
                settings = {}

        last_visit = settings.get("last_visit_at", 0)
        current_streak = settings.get("streak_count", 0)
        new_streak, _ = _compute_streak(last_visit, current_streak)
        stats["streak_count"] = new_streak
        stats["streak_best"] = max(settings.get("streak_best", 0), new_streak)

        for badge_def in BADGE_DEFINITIONS:
            earned = badge_def["check"](stats)
            progress = badge_def["progress"](stats)
            badges.append({
                "id": badge_def["id"],
                "name": badge_def["name"],
                "description": badge_def["description"],
                "icon": badge_def["icon"],
                "category": badge_def["category"],
                "earned": earned,
                "progress": progress,
                "target": badge_def["target"],
                "pct": min(round((progress / badge_def["target"]) * 100), 100) if badge_def["target"] > 0 else 0,
            })

    return templates.TemplateResponse("badges.html", {
        "request": request,
        "user": user,
        "tier": (user or {}).get("tier", "free"),
        "badges": badges,
        "stats": stats,
        "total_earned": sum(1 for b in badges if b.get("earned")),
        "total_badges": len(BADGE_DEFINITIONS),
    })


@router.get("/api/v1/badges/check")
async def check_badges(request: Request):
    """Recalculate and return badge state."""
    user = await require_user(request)
    db = request.app.state.db

    stats = await _gather_stats(db, user)

    # Update streak
    settings = user.get("settings", {})
    if isinstance(settings, str):
        import json
        try:
            settings = json.loads(settings)
        except Exception:
            settings = {}

    last_visit = settings.get("last_visit_at", 0)
    current_streak = settings.get("streak_count", 0)
    new_streak, was_reset = _compute_streak(last_visit, current_streak)
    best_streak = max(settings.get("streak_best", 0), new_streak)

    # Save updated streak + signal view count
    settings["streak_count"] = new_streak
    settings["streak_best"] = best_streak
    settings["signals_viewed"] = settings.get("signals_viewed", 0) + 1
    await db.update_user_settings(user["id"], settings)

    stats["streak_count"] = new_streak
    stats["streak_best"] = best_streak

    earned = {}
    for badge_def in BADGE_DEFINITIONS:
        earned[badge_def["id"]] = badge_def["check"](stats)

    return {
        "ok": True,
        "earned": earned,
        "total_earned": sum(1 for v in earned.values() if v),
        "streak_count": new_streak,
        "streak_best": best_streak,
    }
