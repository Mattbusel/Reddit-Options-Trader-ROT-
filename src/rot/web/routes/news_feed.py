"""News Feed routes — real-time market news aggregator.

Kills: Benzinga Pro ($177/mo). ROT aggregates the same sources for $0.
Surfaces existing RSS signal data as a dedicated news feed experience.

Pro feature (source filter, real-time). Premium feature (AI summaries).
"""
# Force redeploy
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web.rate_limit import check_rate_limit, require_api_auth, rate_limit_headers
from rot.web.tier_gate import gate_news_feed_access

log = logging.getLogger(__name__)

router = APIRouter()

# Map subreddit labels to human-readable source names and icons
_SOURCE_MAP = {
    "marketwatch": ("MarketWatch", "MW"),
    "investing-com": ("Investing.com", "INV"),
    "yahoo-finance": ("Yahoo Finance", "YF"),
    "cnbc": ("CNBC", "CNBC"),
    "seekingalpha": ("SeekingAlpha", "SA"),
    "reuters": ("Reuters", "R"),
    "dod-contracts": ("DoD Contracts", "DoD"),
    "dod-releases": ("DoD Releases", "DoD"),
    "dod-news": ("DoD News", "DoD"),
    "fda-press-releases": ("FDA Press", "FDA"),
    "fda-drugs": ("FDA Drugs", "FDA"),
    "fda-safety-alerts": ("FDA Safety", "FDA"),
    "fda-recalls": ("FDA Recalls", "FDA"),
    "fda-oncology": ("FDA Oncology", "FDA"),
    "biopharma-dive": ("BioPharma", "BIO"),
    "drugs-com-approvals": ("Drug Approvals", "RX"),
    "drugs-com-trials": ("Clinical Trials", "RX"),
    "fed-press-releases": ("Federal Reserve", "FED"),
    "stocktwits": ("StockTwits", "ST"),
    "twitter": ("X / Twitter", "X"),
}

_SOURCE_CATEGORIES = {
    "all": "All Sources",
    "financial": "Financial News",
    "regulatory": "Government & Regulatory",
    "social": "Social Feeds",
}


@router.get("/news", response_class=HTMLResponse)
async def news_feed_page(request: Request, source: str = "all", hours: int = 0):
    """Real-time news feed aggregator page."""
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    gate = gate_news_feed_access(tier)

    # Enforce tier limits
    max_hours = gate["max_hours"]
    max_items = gate["max_items"]
    if hours <= 0 or hours > max_hours:
        hours = max_hours

    # Only Pro+ can filter by source
    source_filter = None
    if source != "all" and gate["has_source_filter"]:
        source_filter = source

    db = request.app.state.db
    items = await db.get_news_feed(hours=hours, limit=max_items, source=source_filter)

    # Enrich items with readable source names
    for item in items:
        sub = item.get("subreddit", "")
        src_info = _SOURCE_MAP.get(sub, (sub, "?"))
        item["source_name"] = src_info[0]
        item["source_badge"] = src_info[1]
        # Strip AI summary if not premium
        if not gate["has_ai_summary"]:
            item["ai_summary"] = ""

    templates = request.app.state.templates
    # Count total available sources (not just sources with items in current time window)
    total_sources = len(_SOURCE_MAP)

    return templates.TemplateResponse("news_feed.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "gate": gate,
        "items": items,
        "source": source,
        "hours": hours,
        "source_map": _SOURCE_MAP,
        "source_categories": _SOURCE_CATEGORIES,
        "total_sources": total_sources,
    })


@router.get("/api/v1/news", tags=["news"])
async def news_feed_api(request: Request, source: str = "all", hours: int = 24, limit: int = 50):
    """JSON news feed endpoint for API consumers. Requires paid subscription."""
    from fastapi.responses import JSONResponse

    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    gate = gate_news_feed_access(tier)

    hours = min(hours, gate["max_hours"])
    limit = min(limit, gate["max_items"])

    source_filter = None if source == "all" else source
    db = request.app.state.db
    items = await db.get_news_feed(hours=hours, limit=limit, source=source_filter)

    if not gate["has_ai_summary"]:
        for item in items:
            item.pop("ai_summary", None)

    headers = rate_limit_headers(user)
    return JSONResponse(
        content={"items": items, "count": len(items), "hours": hours},
        headers=headers,
    )
