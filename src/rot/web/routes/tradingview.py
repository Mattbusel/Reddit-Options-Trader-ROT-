"""TradingView integration routes.

Provides:
  - /tradingview — public page with Pine Script code + setup instructions
  - /api/v1/tradingview/signals — JSON feed for TradingView external data
  - /api/v1/tradingview/webhook — incoming webhook from TradingView alerts
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional, require_user
from rot.web.rate_limit import check_rate_limit, require_api_auth, rate_limit_headers

log = logging.getLogger(__name__)

router = APIRouter()


# ── Public Pine Script page ──

@router.get("/tradingview", response_class=HTMLResponse)
async def tradingview_page(request: Request):
    """Render the TradingView integration page with Pine Script code."""
    user = await get_current_user_optional(request)
    templates = request.app.state.templates
    settings = request.app.state.settings

    # Build the API base URL for Pine Script
    base_url = f"{request.base_url}api/v1/tradingview"

    return templates.TemplateResponse("tradingview.html", {
        "request": request,
        "user": user,
        "base_url": str(base_url).rstrip("/"),
        "dashboard_url": str(request.base_url).rstrip("/"),
    })


# ── JSON signal feed for TradingView ──

@router.get("/api/v1/tradingview/signals")
async def tradingview_signals(
    request: Request,
    ticker: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    """Return signals formatted for TradingView external data consumption.

    Requires paid subscription. Can be polled by Pine Script or external integrations.
    Returns lightweight JSON optimized for charting overlays.
    """
    from fastapi.responses import JSONResponse

    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")

    db = request.app.state.db
    settings = request.app.state.settings

    signals = await db.get_signals(limit=limit, ticker=ticker)

    # Format for TradingView consumption
    tv_signals = []
    for s in signals:
        tv_signals.append({
            "t": int(s.get("created_at", 0)),  # Unix timestamp
            "s": s.get("ticker", ""),
            "stance": s.get("stance", "unknown"),
            "c": round(s.get("confidence", 0), 2),
            "type": s.get("event_type", "other"),
            "strategy": s.get("strategy", "none"),
            "horizon": s.get("time_horizon", "unknown"),
            "trend": round(s.get("trend_score", 0), 4),
            "id": s.get("id", ""),
        })

    return JSONResponse(
        content={
            "signals": tv_signals,
            "count": len(tv_signals),
            "tier": tier,
            "ts": int(time.time()),
        },
        headers=rate_limit_headers(user),
    )


# ── TradingView alert webhook receiver ──

@router.post("/api/v1/tradingview/webhook")
async def tradingview_webhook(request: Request):
    """Receive TradingView alert webhooks.

    Users configure TradingView alerts to POST here when ROT signals
    trigger their custom conditions (e.g., confidence > 0.7 + bullish).

    This stores the alert for the user's alert history and can trigger
    notifications (email, Discord).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Extract fields from TradingView alert payload
    ticker = body.get("ticker", body.get("symbol", ""))
    action = body.get("action", body.get("stance", ""))
    confidence = body.get("confidence", 0)
    message = body.get("message", "")
    api_key = body.get("api_key", "")

    if not ticker:
        raise HTTPException(status_code=400, detail="Missing ticker/symbol")

    # Validate API key if provided (ties webhook to a user)
    user = None
    if api_key:
        from rot.web.auth import hash_api_key
        db = request.app.state.db
        key_hash = hash_api_key(api_key)
        user = await db.get_user_by_api_key_hash(key_hash)

    log.info(
        "TradingView webhook: ticker=%s action=%s confidence=%s user=%s",
        ticker, action, confidence,
        user["id"] if user else "anonymous",
    )

    return {
        "ok": True,
        "received": {
            "ticker": ticker,
            "action": action,
            "confidence": confidence,
        },
    }
