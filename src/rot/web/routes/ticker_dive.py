"""Ticker Deep Dive — comprehensive single-ticker intelligence page."""
from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web import tier_gate

log = logging.getLogger(__name__)

router = APIRouter()


def _base_context(request: Request, user: dict | None) -> dict:
    tier = (user or {}).get("tier", "free")
    badge_map = {
        "free": "bg-gray-700 text-gray-300",
        "pro": "bg-blue-700/60 text-blue-200",
        "premium": "bg-purple-700/60 text-purple-200",
        "ultra": "bg-orange-700/60 text-orange-200",
        "admin": "bg-red-700/60 text-red-200",
    }
    return {
        "request": request,
        "user": user,
        "tier": tier,
        "tier_badge_class": badge_map.get(tier, badge_map["free"]),
        "stripe_enabled": bool(request.app.state.settings.stripe.secret_key),
    }


def _time_ago(ts: float) -> str:
    diff = time.time() - ts
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff / 60)}m ago"
    if diff < 86400:
        return f"{int(diff / 3600)}h ago"
    return f"{int(diff / 86400)}d ago"


@router.get("/ticker/{symbol}", response_class=HTMLResponse)
async def ticker_deep_dive(request: Request, symbol: str):
    """Ticker Deep Dive — everything ROT knows about one ticker."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)
    tier = ctx["tier"]

    access = tier_gate.gate_ticker_dive_access(tier)
    symbol = symbol.upper()

    db = request.app.state.db

    # Get ticker summary
    summary = await db.get_ticker_summary(symbol)

    # Get signals (limited by tier)
    signals = await db.get_ticker_signals(symbol, limit=access["max_signals"])

    # Extract market data from latest signal (if available)
    market_data = {}
    if signals:
        md = signals[0].get("market_data", {})
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except Exception:
                log.exception("Failed to parse market_data JSON for ticker dive")
                md = {}
        if isinstance(md, dict):
            # Market data is nested: {ticker: {price, ...}} or flat
            market_data = md.get(symbol, md)

    # Stance determination
    bull = summary.get("bullish_count", 0) or 0
    bear = summary.get("bearish_count", 0) or 0
    mixed = summary.get("mixed_count", 0) or 0
    total = summary.get("total_signals", 0) or 0

    if total > 0:
        if bull > bear and bull > mixed:
            consensus = "bullish"
        elif bear > bull and bear > mixed:
            consensus = "bearish"
        elif bull > 0 and bear > 0:
            consensus = "mixed"
        else:
            consensus = "neutral"
    else:
        consensus = "unknown"

    # Signal counts by time window
    now = time.time()
    count_24h = sum(1 for s in signals if s.get("created_at", 0) > now - 86400)
    count_7d = sum(1 for s in signals if s.get("created_at", 0) > now - 604800)
    count_30d = sum(1 for s in signals if s.get("created_at", 0) > now - 2592000)

    # Chart data: confidence over time (Pro+)
    chart_data = []
    if access["has_chart"] and signals:
        for s in reversed(signals):  # oldest first for chart
            chart_data.append({
                "x": int(s.get("created_at", 0) * 1000),  # JS timestamp
                "y": round(s.get("confidence", 0) * 100, 1),
                "stance": s.get("stance", "unknown"),
            })

    # Stance color mapping
    stance_colors = {
        "bullish": "text-green-400",
        "bearish": "text-red-400",
        "mixed": "text-yellow-400",
        "neutral": "text-gray-400",
        "unknown": "text-gray-500",
    }
    stance_bg = {
        "bullish": "bg-green-900/30 border-green-700",
        "bearish": "bg-red-900/30 border-red-700",
        "mixed": "bg-yellow-900/30 border-yellow-700",
        "neutral": "bg-gray-900/30 border-gray-700",
        "unknown": "bg-gray-900/30 border-gray-700",
    }

    ctx.update({
        "symbol": symbol,
        "summary": summary,
        "signals": signals,
        "market_data": market_data,
        "consensus": consensus,
        "bull_count": bull,
        "bear_count": bear,
        "mixed_count": mixed,
        "total_signals": total,
        "count_24h": count_24h,
        "count_7d": count_7d,
        "count_30d": count_30d,
        "avg_confidence": round((summary.get("avg_confidence") or 0) * 100, 1),
        "chart_data": chart_data,
        "stance_colors": stance_colors,
        "stance_bg": stance_bg,
        "access": access,
        "time_ago": _time_ago,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("ticker_dive.html", ctx)
