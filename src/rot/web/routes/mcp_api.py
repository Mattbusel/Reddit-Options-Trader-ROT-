"""MCP API routes — lightweight JSON endpoints for the MCP server.

These endpoints power the ROT MCP server, providing structured data
that LLMs can consume via the Model Context Protocol.

All endpoints are unauthenticated at launch to maximize distribution.
An optional ``Authorization: Bearer {key}`` header is accepted for
future tier gating but has no effect yet.

Routes:
    GET /api/mcp/trending     — Top trending tickers (24h)
    GET /api/mcp/signals      — Latest signals with filters
    GET /api/mcp/sentiment    — Sentiment breakdown for a ticker
    GET /api/mcp/overview     — Market overview stats (30d)
    GET /api/mcp/unusual      — Tickers with unusual activity
    GET /api/mcp/sports       — Sports betting intelligence feed
    GET /api/mcp/search       — Full-text search across signals
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


# ── Helpers ──────────────────────────────────────────────────────────


def _json(data: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status)


# ── GET /api/mcp/trending ────────────────────────────────────────────


@router.get("/trending")
async def mcp_trending(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(20, ge=1, le=100),
):
    """Top trending tickers with signal counts and average confidence."""
    db = request.app.state.db
    tickers = await db.get_trending_tickers(hours=hours, limit=limit)
    return _json({
        "tickers": tickers,
        "period_hours": hours,
        "count": len(tickers),
    })


# ── GET /api/mcp/signals ────────────────────────────────────────────


@router.get("/signals")
async def mcp_signals(
    request: Request,
    ticker: Optional[str] = None,
    stance: Optional[str] = Query(None, pattern="^(bullish|bearish|unknown|mixed)$"),
    limit: int = Query(10, ge=1, le=50),
):
    """Latest trading signals with source, confidence, event type, and timestamp."""
    db = request.app.state.db
    signals = await db.get_signals(
        limit=limit,
        ticker=ticker.upper() if ticker else None,
        stance=stance,
    )

    # Shape output for LLM consumption — keep it lean
    results = []
    for s in signals:
        results.append({
            "id": s.get("id"),
            "ticker": s.get("ticker"),
            "stance": s.get("stance"),
            "confidence": s.get("confidence"),
            "event_type": s.get("event_type"),
            "strategy": s.get("strategy"),
            "subreddit": s.get("subreddit"),
            "post_title": s.get("post_title"),
            "ai_summary": s.get("ai_summary"),
            "created_at": s.get("created_at"),
        })

    return _json({
        "signals": results,
        "count": len(results),
        "filters": {
            "ticker": ticker,
            "stance": stance,
            "limit": limit,
        },
    })


# ── GET /api/mcp/sentiment ──────────────────────────────────────────


@router.get("/sentiment")
async def mcp_sentiment(
    request: Request,
    ticker: str = Query(..., min_length=1, max_length=10),
):
    """Sentiment breakdown for a specific ticker — bull/bear/mixed ratio and signal count."""
    db = request.app.state.db
    upper_ticker = ticker.upper()

    # Fetch recent signals for this ticker
    signals = await db.get_signals(limit=200, ticker=upper_ticker)

    if not signals:
        return _json({
            "ticker": upper_ticker,
            "signal_count": 0,
            "bullish": 0,
            "bearish": 0,
            "mixed": 0,
            "unknown": 0,
            "net_sentiment": 0.0,
            "avg_confidence": 0.0,
        })

    bullish = sum(1 for s in signals if s.get("stance") == "bullish")
    bearish = sum(1 for s in signals if s.get("stance") == "bearish")
    mixed = sum(1 for s in signals if s.get("stance") == "mixed")
    unknown = sum(1 for s in signals if s.get("stance") == "unknown")
    total = len(signals)

    # Net sentiment: +1.0 = all bullish, -1.0 = all bearish
    net = (bullish - bearish) / total if total else 0.0

    confidences = [s.get("confidence", 0) or 0 for s in signals]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    return _json({
        "ticker": upper_ticker,
        "signal_count": total,
        "bullish": bullish,
        "bearish": bearish,
        "mixed": mixed,
        "unknown": unknown,
        "net_sentiment": round(net, 3),
        "avg_confidence": round(avg_conf, 3),
    })


# ── GET /api/mcp/overview ───────────────────────────────────────────


@router.get("/overview")
async def mcp_overview(request: Request):
    """Market overview — total signals (30d), tradeable count, avg confidence, win rate, top strategies."""
    db = request.app.state.db

    summary = await db.get_performance_summary(days=30)
    accuracy = await db.get_aggregate_accuracy(days=30)

    return _json({
        "period_days": 30,
        "total_signals": summary.get("total_signals", 0),
        "tradeable_signals": summary.get("tradeable_signals", 0),
        "avg_confidence": round(summary.get("avg_confidence", 0) or 0, 3),
        "signals_today": summary.get("signals_today", 0),
        "signals_7d": summary.get("signals_7d", 0),
        "unique_tickers": summary.get("unique_tickers", 0),
        "bullish_count": summary.get("bullish_count", 0),
        "bearish_count": summary.get("bearish_count", 0),
        "win_rate": round(accuracy.get("win_rate", 0) or 0, 3),
        "total_tracked": accuracy.get("total_tracked", 0),
        "winners": accuracy.get("winners", 0),
        "losers": accuracy.get("losers", 0),
    })


# ── GET /api/mcp/unusual ────────────────────────────────────────────


@router.get("/unusual")
async def mcp_unusual(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(20, ge=1, le=100),
):
    """Tickers with unusual signal volume or confidence spikes."""
    db = request.app.state.db
    events = await db.get_unusual_events(hours=hours, limit=limit)

    results = []
    for e in events:
        results.append({
            "ticker": e.get("ticker"),
            "event_type": e.get("event_type"),
            "score": e.get("score"),
            "detected_at": e.get("detected_at"),
            "details": e.get("details"),
        })

    return _json({
        "events": results,
        "count": len(results),
        "period_hours": hours,
    })


# ── GET /api/mcp/sports ─────────────────────────────────────────────


@router.get("/sports")
async def mcp_sports(
    request: Request,
    league: Optional[str] = Query(None, pattern="^(NFL|NBA|MLB|NHL|NCAA|Soccer)$"),
    limit: int = Query(20, ge=1, le=100),
):
    """Sports betting intelligence with line mover scores."""
    # Use the in-memory sports cache (same as the sports tracker page)
    from rot.web.routes.sports_tracker import _news_cache

    items = await _news_cache.get_items(
        league=league if league else "all",
    )
    items = items[:limit]

    results = []
    for item in items:
        results.append({
            "title": item.title,
            "league": item.league,
            "source": item.source,
            "teams": item.teams,
            "categories": item.categories,
            "urgency": item.urgency,
            "line_mover_score": item.line_mover_score,
            "published": item.published,
            "link": item.link,
            "summary": item.summary[:200] if item.summary else "",
        })

    return _json({
        "items": results,
        "count": len(results),
        "league_filter": league,
    })


# ── GET /api/mcp/search ─────────────────────────────────────────────


@router.get("/search")
async def mcp_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(10, ge=1, le=50),
):
    """Full-text search across all signals — matches ticker, post title, event type."""
    db = request.app.state.db
    query_upper = q.upper().strip()
    query_lower = q.lower().strip()

    # Strategy 1: exact ticker match
    ticker_signals = await db.get_signals(limit=limit, ticker=query_upper)

    # Strategy 2: LIKE search on post_title
    title_signals = []
    try:
        sql = """
            SELECT id, ticker, stance, confidence, event_type, strategy,
                   subreddit, post_title, ai_summary, created_at
            FROM signals
            WHERE post_title LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        async with db.db.execute(sql, (f"%{query_lower}%", limit)) as cursor:
            rows = await cursor.fetchall()
            title_signals = [dict(r) for r in rows]
    except Exception as e:
        log.warning("MCP search title query failed: %s", e)

    # Merge and deduplicate
    seen_ids = set()
    results = []
    for s in ticker_signals + title_signals:
        sid = s.get("id")
        if sid and sid not in seen_ids:
            seen_ids.add(sid)
            results.append({
                "id": s.get("id"),
                "ticker": s.get("ticker"),
                "stance": s.get("stance"),
                "confidence": s.get("confidence"),
                "event_type": s.get("event_type"),
                "strategy": s.get("strategy"),
                "subreddit": s.get("subreddit"),
                "post_title": s.get("post_title"),
                "ai_summary": s.get("ai_summary"),
                "created_at": s.get("created_at"),
            })
        if len(results) >= limit:
            break

    return _json({
        "query": q,
        "results": results,
        "count": len(results),
    })
