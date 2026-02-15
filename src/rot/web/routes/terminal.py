"""Bloomberg-lite Terminal — unified multi-panel market intelligence dashboard."""

from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_terminal_access

router = APIRouter()


@router.get("/terminal", response_class=HTMLResponse)
async def terminal_page(request: Request):
    """Main terminal page — multi-panel real-time market intelligence."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_terminal_access(tier)
    templates = request.app.state.templates
    db = request.app.state.db

    # Even without access, render the page (with paywall overlay)
    signals = []
    trending = []
    unusual_events = []
    perf_summary = {}
    quick_stats = {}
    watchlist = []

    if access["has_access"]:
        cache = getattr(request.app.state, "query_cache", None)
        limit = access["max_signals_feed"]

        # Fetch signals for feed panel
        try:
            signals_raw = await db.get_recent_signals(limit=limit)
            signals = signals_raw if signals_raw else []
        except Exception:
            signals = []

        # Fetch trending tickers for ticker bar
        try:
            if cache:
                trending = await cache.get_or_fetch(
                    "trending_terminal", lambda: db.get_trending_tickers(limit=20), ttl=30
                )
            else:
                trending = await db.get_trending_tickers(limit=20)
        except Exception:
            trending = []

        # Fetch unusual activity for options flow panel
        if access["has_options_flow"]:
            try:
                unusual_events = await db.query_unusual_events(limit=10)
            except Exception:
                unusual_events = []

        # Fetch performance summary for quick stats
        try:
            if cache:
                perf_summary = await cache.get_or_fetch(
                    "perf_summary_terminal", lambda: db.get_performance_summary(), ttl=120
                )
            else:
                perf_summary = await db.get_performance_summary()
        except Exception:
            perf_summary = {}

        # Build quick stats
        quick_stats = _build_quick_stats(perf_summary, signals, trending)

        # User watchlist
        if user and access.get("has_watchlist_alerts"):
            try:
                settings = user.get("settings", {})
                if isinstance(settings, str):
                    import json
                    settings = json.loads(settings)
                watchlist_tickers = settings.get("watchlist", [])
                if watchlist_tickers:
                    watchlist = await _build_watchlist(db, watchlist_tickers)
            except Exception:
                watchlist = []

    return templates.TemplateResponse("terminal.html", {
        "request": request,
        "user": user or {"tier": "free"},
        "tier": tier,
        "access": access,
        "signals": signals,
        "trending": trending,
        "unusual_events": unusual_events,
        "perf_summary": perf_summary,
        "quick_stats": quick_stats,
        "watchlist": watchlist,
    })


@router.get("/api/v1/terminal/ticker-bar", response_class=HTMLResponse)
async def terminal_ticker_bar(request: Request):
    """HTMX partial: scrolling ticker bar data."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_terminal_access(tier)
    templates = request.app.state.templates

    if not access["has_access"]:
        return HTMLResponse("")

    db = request.app.state.db
    try:
        trending = await db.get_trending_tickers(limit=20)
    except Exception:
        trending = []

    return templates.TemplateResponse("terminal_ticker_bar_partial.html", {
        "request": request,
        "trending": trending,
    })


@router.get("/api/v1/terminal/quick-stats", response_class=HTMLResponse)
async def terminal_quick_stats(request: Request):
    """HTMX partial: quick stats panel."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_terminal_access(tier)
    templates = request.app.state.templates

    if not access["has_access"]:
        return HTMLResponse("")

    db = request.app.state.db
    try:
        perf = await db.get_performance_summary()
        signals = await db.get_recent_signals(limit=50)
        trending = await db.get_trending_tickers(limit=10)
        quick_stats = _build_quick_stats(perf, signals, trending)
    except Exception:
        quick_stats = {}

    return templates.TemplateResponse("terminal_quick_stats_partial.html", {
        "request": request,
        "quick_stats": quick_stats,
    })


@router.get("/api/v1/terminal/watchlist", response_class=HTMLResponse)
async def terminal_watchlist(request: Request):
    """HTMX partial: user watchlist panel."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_terminal_access(tier)
    templates = request.app.state.templates

    if not access["has_access"] or not access.get("has_watchlist_alerts") or not user:
        return HTMLResponse("")

    db = request.app.state.db
    try:
        import json
        settings = user.get("settings", {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        watchlist_tickers = settings.get("watchlist", [])
        watchlist = await _build_watchlist(db, watchlist_tickers) if watchlist_tickers else []
    except Exception:
        watchlist = []

    return templates.TemplateResponse("terminal_watchlist_partial.html", {
        "request": request,
        "watchlist": watchlist,
    })


def _build_quick_stats(
    perf: Dict[str, Any],
    signals: list,
    trending: list,
) -> Dict[str, Any]:
    """Build quick stats dict from performance summary and recent signals."""
    now = time.time()
    today_cutoff = now - 86400

    today_signals = [s for s in signals if s.get("created_at", 0) > today_cutoff]
    bullish = sum(1 for s in today_signals if s.get("stance") == "bullish")
    bearish = sum(1 for s in today_signals if s.get("stance") == "bearish")

    # Top bullish/bearish tickers
    bull_tickers: Dict[str, int] = {}
    bear_tickers: Dict[str, int] = {}
    for s in today_signals:
        t = s.get("ticker", "")
        if s.get("stance") == "bullish":
            bull_tickers[t] = bull_tickers.get(t, 0) + 1
        elif s.get("stance") == "bearish":
            bear_tickers[t] = bear_tickers.get(t, 0) + 1

    top_bull = sorted(bull_tickers.items(), key=lambda x: -x[1])[:3]
    top_bear = sorted(bear_tickers.items(), key=lambda x: -x[1])[:3]

    # Market sentiment gauge (-1 to +1)
    total_dir = bullish + bearish
    sentiment_gauge = (bullish - bearish) / total_dir if total_dir > 0 else 0.0

    return {
        "signals_today": len(today_signals),
        "bullish_count": bullish,
        "bearish_count": bearish,
        "win_rate": perf.get("win_rate", 0),
        "total_signals_7d": perf.get("total_signals", 0),
        "top_bullish": top_bull,
        "top_bearish": top_bear,
        "sentiment_gauge": round(sentiment_gauge, 2),
        "avg_confidence": perf.get("avg_confidence", 0),
    }


async def _build_watchlist(db, tickers: list) -> list:
    """Build watchlist panel data for given tickers."""
    watchlist = []
    for ticker in tickers[:20]:  # Cap at 20
        try:
            # Get recent signals for this ticker
            signals = await db.get_signals_for_ticker(ticker, limit=5)
            signal_count = len(signals)
            latest = signals[0] if signals else {}
            latest_stance = latest.get("stance", "unknown")
            latest_conf = latest.get("confidence", 0)

            watchlist.append({
                "ticker": ticker,
                "signal_count": signal_count,
                "latest_stance": latest_stance,
                "latest_confidence": latest_conf,
                "latest_time": latest.get("created_at", 0),
            })
        except Exception:
            watchlist.append({
                "ticker": ticker,
                "signal_count": 0,
                "latest_stance": "unknown",
                "latest_confidence": 0,
                "latest_time": 0,
            })
    return watchlist
