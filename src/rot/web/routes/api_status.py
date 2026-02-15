"""API Status & Self-Service Documentation.

Provides:
  - /api/v1/status — Your current API usage, limits, and available endpoints
  - /api/v1/docs — Endpoint reference with parameters and examples

Paid users can see exactly what they have access to, how much quota remains,
and how to use each endpoint with the right query parameters.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from rot.web.auth import get_current_user_optional
from rot.web.rate_limit import require_api_auth, rate_limit_headers

log = logging.getLogger(__name__)

router = APIRouter()

# ── Endpoint catalog — tells paid users exactly what they can hit ──

_ENDPOINTS = [
    {
        "path": "/api/v1/signals",
        "method": "GET",
        "description": "List trading signals with filtering, sorting, and field selection",
        "min_tier": "pro",
        "params": {
            "limit": "int (1-200, default 50) — max results per page",
            "offset": "int (default 0) — pagination offset",
            "ticker": "str — filter by ticker symbol (e.g. AAPL)",
            "stance": "str — bullish, bearish, mixed, unknown",
            "min_confidence": "float (0-1) — minimum confidence threshold",
            "event_type": "str — earnings, fda, merger, etc.",
            "date_from": "float — Unix timestamp (premium+ only)",
            "date_to": "float — Unix timestamp (premium+ only)",
            "source": "str — filter by subreddit/feed source",
            "fields": "str — comma-separated field names to return (reduces bandwidth)",
            "sort": "str — created_at, confidence, or trend_score",
            "order": "str — asc or desc",
        },
        "example": "/api/v1/signals?ticker=AAPL&stance=bullish&min_confidence=0.7&fields=ticker,stance,confidence,created_at&limit=10",
    },
    {
        "path": "/api/v1/signals/{signal_id}",
        "method": "GET",
        "description": "Get a single signal by ID with optional field selection",
        "min_tier": "pro",
        "params": {
            "fields": "str — comma-separated field names to return",
        },
    },
    {
        "path": "/api/v1/tickers/trending",
        "method": "GET",
        "description": "Get trending tickers by signal volume",
        "min_tier": "pro",
        "params": {
            "hours": "int (1-168, default 24) — lookback window",
            "limit": "int (1-100, default 20) — max tickers",
        },
    },
    {
        "path": "/api/v1/performance/summary",
        "method": "GET",
        "description": "Aggregate performance summary (win rate, avg P&L)",
        "min_tier": "pro",
        "params": {"days": "int (1-365, default 30)"},
    },
    {
        "path": "/api/v1/performance/accuracy",
        "method": "GET",
        "description": "Signal accuracy stats by ticker and event type",
        "min_tier": "pro",
        "params": {
            "days": "int (capped by tier)",
            "ticker": "str — filter by ticker",
        },
    },
    {
        "path": "/api/v1/performance/history",
        "method": "GET",
        "description": "Per-signal performance history",
        "min_tier": "pro",
        "params": {
            "days": "int (1-365)",
            "ticker": "str",
            "limit": "int (1-200)",
        },
    },
    {
        "path": "/api/v1/performance/accuracy-chart",
        "method": "GET",
        "description": "Time-series accuracy data for charting",
        "min_tier": "premium",
        "params": {"days": "int (1-365)"},
    },
    {
        "path": "/api/v1/performance/strategy-pnl",
        "method": "GET",
        "description": "Strategy-level P&L breakdown",
        "min_tier": "ultra",
        "params": {"days": "int (1-365)"},
    },
    {
        "path": "/api/v1/leaderboard",
        "method": "GET",
        "description": "Ticker leaderboard by signal volume/performance",
        "min_tier": "pro",
        "params": {
            "hours": "int (1-2160)",
            "limit": "int (1-100)",
            "sort_by": "str — signal_count (default)",
        },
    },
    {
        "path": "/api/v1/correlations",
        "method": "GET",
        "description": "Co-occurring ticker pairs",
        "min_tier": "pro",
        "params": {"hours": "int (1-168)"},
    },
    {
        "path": "/api/v1/correlations/matrix",
        "method": "GET",
        "description": "Top correlated ticker pairs globally",
        "min_tier": "pro",
        "params": {
            "days": "int (1-365, capped by tier)",
            "limit": "int (1-50)",
        },
    },
    {
        "path": "/api/v1/correlations/{ticker}",
        "method": "GET",
        "description": "Tickers that co-fire with a specific ticker",
        "min_tier": "pro",
        "params": {
            "days": "int (capped by tier)",
            "window_hours": "int (1-24) — co-occurrence window",
        },
    },
    {
        "path": "/api/v1/news",
        "method": "GET",
        "description": "Real-time news feed from 15+ financial sources",
        "min_tier": "pro",
        "params": {
            "source": "str — filter by source (all, marketwatch, cnbc, etc.)",
            "hours": "int (capped by tier)",
            "limit": "int (capped by tier)",
        },
    },
    {
        "path": "/api/v1/unusual-activity",
        "method": "GET",
        "description": "Signals with unusual options activity flags",
        "min_tier": "pro",
        "params": {
            "hours": "int (1-720, capped by tier)",
            "limit": "int (1-200)",
        },
    },
    {
        "path": "/api/v1/congress-trades",
        "method": "GET",
        "description": "Congressional stock trading tracker",
        "min_tier": "pro",
        "params": {
            "days": "int (capped by tier)",
            "limit": "int (max 100)",
            "ticker": "str — filter by ticker (premium+ only)",
        },
    },
    {
        "path": "/api/v1/paper-leaderboard",
        "method": "GET",
        "description": "Paper trading leaderboard rankings",
        "min_tier": "pro",
        "params": {"limit": "int (capped by tier)"},
    },
    {
        "path": "/api/v1/tradingview/signals",
        "method": "GET",
        "description": "Signals formatted for TradingView Pine Script consumption",
        "min_tier": "pro",
        "params": {
            "ticker": "str — filter by ticker",
            "limit": "int (1-200)",
        },
    },
    {
        "path": "/api/v1/sectors/{sector}",
        "method": "GET",
        "description": "Ticker drill-down within a sector",
        "min_tier": "premium",
        "params": {"hours": "int (1-168)"},
    },
    {
        "path": "/api/v1/signals/{signal_id}/reason",
        "method": "POST",
        "description": "Re-analyze a signal with your own LLM key (BYOK)",
        "min_tier": "pro",
        "params": {},
    },
    {
        "path": "/api/v1/sports-betting",
        "method": "GET",
        "description": "Sports betting intelligence — news, Line Mover Scores, team tracking, AI analysis",
        "min_tier": "premium",
        "params": {
            "league": "str — NFL, NBA, MLB, NHL, Soccer, NCAA, Multi, or all",
            "category": "str — injury, trade, suspension, lineup, game, news, or all",
            "team": "str — team name filter (e.g. 'chiefs', 'lakers')",
            "urgency": "str — high, medium, low, or all",
            "min_score": "int (0-100) — minimum Line Mover Score",
            "sort": "str — time (default) or score (by Line Mover Score)",
            "limit": "int (1-200, default 50)",
            "offset": "int (default 0) — pagination offset",
            "fields": "str — comma-separated field names to return",
        },
        "example": "/api/v1/sports-betting?league=NFL&urgency=high&min_score=60&sort=score&limit=20",
    },
]

_TIER_ORDER = {"free": 0, "pro": 1, "premium": 2, "ultra": 3, "enterprise": 4}


@router.get("/api/v1/status")
async def api_status(request: Request):
    """Get your API status: usage, limits, and available features.

    Returns your current rate limit state, which endpoints you have access to,
    and customization options. Use this to build dashboards or monitor usage.
    """
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)

    tier = user.get("tier", "free")
    user_id = user.get("id", "")
    settings = request.app.state.settings

    # Get current usage
    db = request.app.state.db
    now = time.time()
    daily_count = await db.get_api_call_count(user_id, now - 86400)
    minute_count = await db.get_api_call_count(user_id, now - 60)

    # Build limits from config
    daily_limit = getattr(
        settings.tier_limits, f"{tier}_api_limit_day", 0,
    )
    from rot.web.rate_limit import _BURST_LIMITS
    burst_limit = _BURST_LIMITS.get(tier, 0)

    # Determine which endpoints this tier can access
    tier_rank = _TIER_ORDER.get(tier, 0)
    accessible = []
    locked = []
    for ep in _ENDPOINTS:
        ep_rank = _TIER_ORDER.get(ep["min_tier"], 0)
        info = {
            "path": ep["path"],
            "method": ep["method"],
            "description": ep["description"],
            "min_tier": ep["min_tier"],
        }
        if tier_rank >= ep_rank:
            info["params"] = ep.get("params", {})
            if "example" in ep:
                info["example"] = ep["example"]
            accessible.append(info)
        else:
            locked.append(info)

    data = {
        "tier": tier,
        "usage": {
            "daily": {"used": daily_count, "limit": daily_limit, "remaining": max(0, daily_limit - daily_count)},
            "burst": {"used": minute_count, "limit": burst_limit, "remaining": max(0, burst_limit - minute_count)},
        },
        "endpoints": {
            "accessible": len(accessible),
            "locked": len(locked),
            "list": accessible,
        },
        "locked_endpoints": locked,
        "customization": {
            "field_selection": "Pass ?fields=ticker,stance,confidence to any signal endpoint to reduce response size",
            "sorting": "Pass ?sort=confidence&order=desc to /api/v1/signals",
            "filtering": "Use ?ticker=, ?stance=, ?min_confidence=, ?event_type=, ?source= on signal endpoints",
            "date_range": "Premium+ can use ?date_from= and ?date_to= (Unix timestamps)",
            "pagination": "Use ?limit= and ?offset= for pagination (max 200 per page)",
        },
        "headers": {
            "X-RateLimit-Limit": "Your daily call limit",
            "X-RateLimit-Burst": "Your per-minute burst limit",
            "X-RateLimit-Remaining": "Remaining daily calls (on 429 responses)",
            "X-RateLimit-Reset": "Unix timestamp when daily limit resets (on 429 responses)",
            "X-Tier": "Your current subscription tier",
        },
        "ts": int(now),
    }

    headers = rate_limit_headers(user)
    return JSONResponse(content=data, headers=headers)


@router.get("/api/v1/docs")
async def api_docs(request: Request):
    """Public endpoint reference — no auth required.

    Shows all available API endpoints so prospective users know
    what they'll get when they subscribe. Drives upgrades.
    """
    from fastapi.responses import HTMLResponse
    from rot.web.auth import get_current_user_optional

    endpoints = []
    for ep in _ENDPOINTS:
        info = {
            "path": ep["path"],
            "method": ep["method"],
            "description": ep["description"],
            "min_tier": ep["min_tier"],
            "params": ep.get("params", {}),
        }
        if "example" in ep:
            info["example"] = ep["example"]
        endpoints.append(info)

    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")

    templates = request.app.state.templates
    return templates.TemplateResponse("api_docs.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "endpoints": endpoints,
    })
