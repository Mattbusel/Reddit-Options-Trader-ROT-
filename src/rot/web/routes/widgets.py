"""Embed-Anywhere Widget routes.

Provides:
  - /widgets — generator page for embed codes
  - /widget/{ticker} — public self-contained widget (no base.html)
  - /api/v1/widgets/{ticker}/json — public JSON feed for JS embeds
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/widgets", response_class=HTMLResponse)
async def widgets_page(request: Request):
    """Generator page where users grab embed codes."""
    user = await get_current_user_optional(request)
    templates = request.app.state.templates
    base_url = str(request.base_url).rstrip("/")
    return templates.TemplateResponse("widgets.html", {
        "request": request,
        "user": user,
        "tier": (user or {}).get("tier", "free"),
        "base_url": base_url,
    })


@router.get("/widget/{ticker}", response_class=HTMLResponse)
async def widget_embed(request: Request, ticker: str):
    """Public self-contained widget showing latest signals for a ticker.

    Designed to be embedded via iframe. No auth required.
    Minimal HTML with inline styles — no base.html dependency.
    """
    ticker = ticker.upper().strip()
    db = request.app.state.db
    signals = await db.get_signals(limit=5, ticker=ticker)
    base_url = str(request.base_url).rstrip("/")
    templates = request.app.state.templates
    return templates.TemplateResponse("widget_embed.html", {
        "request": request,
        "ticker": ticker,
        "signals": signals,
        "base_url": base_url,
        "now": time.time(),
    })


@router.get("/api/v1/widgets/{ticker}/json")
async def widget_json(
    request: Request,
    ticker: str,
    limit: int = Query(5, ge=1, le=10),
):
    """Public JSON feed for JS-based widget embeds."""
    ticker = ticker.upper().strip()
    db = request.app.state.db
    signals = await db.get_signals(limit=limit, ticker=ticker)

    items = []
    for s in signals:
        items.append({
            "id": s.get("id", ""),
            "ticker": s.get("ticker", ""),
            "stance": s.get("stance", "unknown"),
            "confidence": round(s.get("confidence", 0), 2),
            "strategy": s.get("strategy", "none"),
            "created_at": int(s.get("created_at", 0)),
        })

    return {
        "ticker": ticker,
        "signals": items,
        "count": len(items),
        "ts": int(time.time()),
        "powered_by": "ROT - Reddit Options Trader",
        "url": f"{str(request.base_url).rstrip('/')}/signals?ticker={ticker}",
    }
