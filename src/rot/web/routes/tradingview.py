"""TradingView integration routes.

Provides:
  - /tradingview — public page with Pine Script code + setup instructions
  - /api/v1/tradingview/signals — JSON feed for TradingView external data
  - /api/v1/tradingview/webhook — incoming webhook from TradingView alerts
  - /api/v1/tradingview/script — Pine Script generator (Pro+ tier)
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from rot.integrations import PineScriptConfig, PineScriptGenerator, TVSignalOverlay
from rot.web.auth import get_current_user_optional
from rot.web.rate_limit import check_rate_limit, require_api_auth, rate_limit_headers
from rot.web.tier_gate import gate_tradingview_access

log = logging.getLogger(__name__)

router = APIRouter()


# ── Public Pine Script page ──

@router.get("/tradingview", response_class=HTMLResponse)
async def tradingview_page(request: Request):
    """Render the TradingView integration page with Pine Script code."""
    user = await get_current_user_optional(request)
    templates = request.app.state.templates

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
        log.exception("Failed to parse incoming TradingView webhook JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Extract fields from TradingView alert payload
    ticker = body.get("ticker", body.get("symbol", ""))
    action = body.get("action", body.get("stance", ""))
    confidence = body.get("confidence", 0)
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


# ── Pine Script generator ──

@router.get("/api/v1/tradingview/script")
async def tradingview_script(
    request: Request,
    ticker: Optional[str] = None,
    days: int = Query(30, ge=1, le=365),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    script_type: str = Query("signal_overlay", regex="^(signal_overlay|confidence_heatmap|watchlist_indicator|strategy_backtest|alert_conditions)$"),
    show_labels: bool = Query(True),
    show_lines: bool = Query(False),
):
    """Generate Pine Script v5 code from ROT signals.

    Tier gate: Free blocked, Pro+ full access.

    Query params:
        ticker: Filter to single ticker (optional)
        days: Number of days of history (1-365, default 30)
        min_confidence: Minimum confidence threshold (0.0-1.0, default 0.0)
        script_type: Type of script (default signal_overlay)
        show_labels: Show text labels on chart (default true)
        show_lines: Draw vertical lines at signals (default false)

    Returns:
        PlainTextResponse with Pine Script v5 code
    """
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")

    # Tier gating: Free blocked, Pro+ allowed
    access = gate_tradingview_access(tier)
    if not access["has_pine_script_generator"]:
        raise HTTPException(
            status_code=403,
            detail="Pine Script generator requires Pro tier or higher. Upgrade at /pricing",
        )

    db = request.app.state.db

    # Calculate cutoff timestamp
    cutoff_ts = int(time.time()) - (days * 86400)

    # Fetch signals
    signals = await db.get_signals(
        limit=1000,  # Fetch more, will filter client-side
        ticker=ticker,
    )

    # Filter by time and confidence
    filtered_signals = [
        s for s in signals
        if s.get("created_at", 0) >= cutoff_ts
        and s.get("confidence", 0) >= min_confidence
    ]

    # Convert to TVSignalOverlay objects
    tv_signals = []
    for sig in filtered_signals[:100]:  # Limit to 100 for Pine Script performance
        tv_signals.append(
            TVSignalOverlay(
                timestamp=int(sig.get("created_at", 0)),
                ticker=sig.get("ticker", "UNKNOWN"),
                stance=sig.get("stance", "unknown"),
                confidence=sig.get("confidence", 0.0),
                event_type=sig.get("event_type", "other"),
                strategy=sig.get("strategy", "none"),
                time_horizon=sig.get("time_horizon", "unknown"),
                trend_score=sig.get("trend_score", 0.0),
                signal_id=sig.get("id", ""),
            )
        )

    # Build configuration
    config = PineScriptConfig(
        ticker=ticker,
        min_confidence=min_confidence,
        days=days,
        max_signals=100,
        show_labels=show_labels,
        show_lines=show_lines,
        script_name=f"ROT Signals - {ticker}" if ticker else "ROT Signals",
        script_description=f"Reddit Options Trader signals ({'filtered to ' + ticker if ticker else 'all tickers'})",
    )

    # Generate script
    generator = PineScriptGenerator(config)
    try:
        script_code = generator.generate(tv_signals, script_type=script_type)  # type: ignore
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Validate syntax
    is_valid, error_msg = PineScriptGenerator.validate_pine_script(script_code)
    if not is_valid:
        log.error("Generated invalid Pine Script: %s", error_msg)
        raise HTTPException(
            status_code=500,
            detail=f"Script generation failed validation: {error_msg}",
        )

    log.info(
        "Generated Pine Script: type=%s ticker=%s signals=%d user=%s",
        script_type, ticker or "all", len(tv_signals),
        user["id"] if user else "anonymous",
    )

    return PlainTextResponse(
        content=script_code,
        headers=rate_limit_headers(user),
        media_type="text/plain",
    )
