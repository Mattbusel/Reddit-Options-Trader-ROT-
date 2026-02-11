from __future__ import annotations

import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from rot.web.auth import get_current_user_optional, require_user, require_tier
from rot.web.rate_limit import check_rate_limit
from rot.web.tier_gate import (
    gate_signal,
    gate_signal_list,
    gate_performance_access,
    gate_leaderboard_access,
    gate_correlation_access,
    gate_heatmap_access,
)

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/signals")
async def list_signals(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ticker: Optional[str] = None,
    stance: Optional[str] = None,
    min_confidence: Optional[float] = None,
    event_type: Optional[str] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
):
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    settings = request.app.state.settings

    # Free tier: cap page size
    if tier == "free":
        limit = min(limit, settings.tier_limits.free_page_limit)

    # Date range filtering only for premium+
    if tier not in ("premium", "ultra"):
        date_from = None
        date_to = None

    db = request.app.state.db
    signals = await db.get_signals(
        limit=limit,
        offset=offset,
        ticker=ticker,
        stance=stance,
        min_confidence=min_confidence,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
    )

    gated = gate_signal_list(
        signals, tier,
        delay_s=settings.tier_limits.free_signal_delay_s,
        page_limit=settings.tier_limits.free_page_limit,
    )

    return {"signals": gated, "count": len(gated), "offset": offset, "tier": tier}


@router.get("/signals/new-count")
async def new_signal_count(request: Request):
    """Get count of new signals since user's last visit."""
    user = await get_current_user_optional(request)
    if not user:
        return {"count": 0}

    db = request.app.state.db
    user_settings = user.get("settings", {})
    last_visit = user_settings.get("last_visit_at", 0) if isinstance(user_settings, dict) else 0
    count = await db.get_signals_since(last_visit) if last_visit else 0
    return {"count": count}


@router.get("/signals/{signal_id}")
async def get_signal(request: Request, signal_id: str):
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    signal = await db.get_signal(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    tier = (user or {}).get("tier", "free")
    settings = request.app.state.settings
    return gate_signal(signal, tier, delay_s=settings.tier_limits.free_signal_delay_s)


@router.get("/tickers/trending")
async def trending_tickers(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(20, ge=1, le=100),
):
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    tickers = await db.get_trending_tickers(hours=hours, limit=limit)
    return {"tickers": tickers, "period_hours": hours}


@router.get("/performance/summary")
async def performance_summary(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    summary = await db.get_performance_summary(days=days)
    return summary


@router.get("/performance/accuracy")
async def accuracy_stats(
    request: Request,
    days: int = Query(7, ge=1, le=365),
    ticker: Optional[str] = None,
):
    """Get signal accuracy statistics."""
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    perf = gate_performance_access(tier)

    # Cap days by tier
    days = min(days, perf["accuracy_days"])

    db = request.app.state.db
    accuracy = await db.get_aggregate_accuracy(days=days, ticker=ticker)
    return accuracy


@router.get("/performance/history")
async def performance_history(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    ticker: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    """Get per-signal performance history (pro+)."""
    user = await require_tier("pro", "premium", "ultra")(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    history = await db.get_performance_history(days=days, ticker=ticker, limit=limit)
    return {"history": history, "count": len(history)}


@router.get("/performance/accuracy-chart")
async def accuracy_chart_data(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    """Get time-series accuracy data for Chart.js (premium+)."""
    user = await require_tier("premium", "ultra")(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    data = await db.get_accuracy_over_time(days=days)
    return {"data": data}


@router.get("/performance/strategy-pnl")
async def strategy_pnl(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    """Get strategy-level P&L breakdown (ultra)."""
    user = await require_tier("ultra")(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    data = await db.get_strategy_pnl(days=days)
    return {"strategies": data}


@router.get("/leaderboard")
async def leaderboard(
    request: Request,
    hours: int = Query(24, ge=1, le=2160),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("signal_count"),
):
    """Get ticker leaderboard."""
    user = await get_current_user_optional(request)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    lb = gate_leaderboard_access(tier)

    # Enforce tier limits
    limit = min(limit, lb["leaderboard_limit"])
    if not lb["has_historical"]:
        hours = 24

    db = request.app.state.db
    if lb["has_performance_column"]:
        data = await db.get_leaderboard_with_performance(hours=hours, limit=limit)
    else:
        data = await db.get_leaderboard(hours=hours, limit=limit, sort_by=sort_by)

    return {"leaderboard": data, "hours": hours, "tier": tier}


@router.get("/correlations")
async def correlations(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
):
    """Get co-occurring ticker pairs (pro+)."""
    user = await require_tier("pro", "premium", "ultra")(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    data = await db.get_co_occurring_tickers(hours=hours, min_co_occurrence=2)
    return {"correlations": data, "hours": hours}


@router.get("/sectors/{sector}")
async def sector_detail(
    request: Request,
    sector: str,
    hours: int = Query(24, ge=1, le=168),
):
    """Get ticker drill-down for a sector (premium+)."""
    user = await require_tier("premium", "ultra")(request)
    await check_rate_limit(request, user)

    db = request.app.state.db
    data = await db.get_sector_drill_down(sector, hours=hours)
    return {"sector": sector, "tickers": data, "hours": hours}


@router.post("/signals/{signal_id}/reason")
async def byok_reason_signal(request: Request, signal_id: str):
    """Re-analyze a signal using the user's BYOK LLM key (pro+ only)."""
    user = await require_user(request)
    tier = user.get("tier", "free")
    if tier not in ("pro", "premium", "ultra"):
        raise HTTPException(status_code=403, detail="BYOK reasoning requires a paid tier")

    # Get user's LLM settings
    settings = user.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
    api_key = settings.get("llm_api_key", "")
    provider = settings.get("llm_provider", "openai")
    model = settings.get("llm_model", "gpt-4o-mini")

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="No LLM API key configured. Go to Account → LLM Settings to add your key.",
        )

    # Get the signal
    db = request.app.state.db
    signal = await db.get_signal(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    # Build a Reasoner with the user's key
    from rot.reasoner.reasoner import Reasoner
    from rot.reasoner.prompts import SYSTEM_PROMPT, format_event_prompt
    from rot.reasoner.parser import parse_reasoning_response
    from rot.reasoner.llm_client import LLMClient

    try:
        client = LLMClient(
            provider=provider,
            api_key=api_key,
            model=model,
            max_tokens=1024,
            temperature=0.3,
        )
        if not client.available:
            raise HTTPException(
                status_code=400,
                detail=f"Could not initialize {provider} client. Check your API key and that the required package is installed.",
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"LLM client init failed: {e}")

    # Reconstruct the prompt from stored signal data
    event_data = signal.get("event_data", {})
    market_data = signal.get("market_data", {})
    reasoning_old = signal.get("reasoning", {})

    ticker = signal.get("ticker", "UNKNOWN")
    subreddit = signal.get("subreddit", "unknown")
    post_title = signal.get("post_title", "")

    # Extract metadata from event_data
    meta = event_data.get("meta", {}) if isinstance(event_data, dict) else {}
    features = meta.get("features", {}) if isinstance(meta, dict) else {}

    user_prompt = format_event_prompt(
        entities=[ticker],
        subreddit=subreddit,
        title=post_title,
        body_excerpt="",
        score=int(meta.get("score", 0)),
        num_comments=int(meta.get("num_comments", 0)),
        upvote_ratio=meta.get("upvote_ratio"),
        author=meta.get("author", "unknown"),
        flair=meta.get("flair"),
        is_crosspost=bool(meta.get("is_crosspost", False)),
        trend_score=float(signal.get("trend_score", 0)),
        score_rate=float(features.get("score_rate", 0)),
        comment_rate=float(features.get("comment_rate", 0)),
        market_data=market_data if market_data else None,
    )

    # Call the LLM
    try:
        raw_response = client.complete(SYSTEM_PROMPT, user_prompt)
        reasoning_packet = parse_reasoning_response(raw_response, [ticker])
    except Exception as e:
        log.warning("BYOK reasoning failed for signal %s: %s", signal_id, e)
        raise HTTPException(status_code=500, detail=f"LLM reasoning failed: {e}")

    # Convert to dict for storage
    new_reasoning = {
        "thesis": reasoning_packet.thesis,
        "catalyst_window": reasoning_packet.catalyst_window,
        "market_expectation": reasoning_packet.market_expectation,
        "invalidations": list(reasoning_packet.invalidations),
        "recommended_structures": list(reasoning_packet.recommended_structures),
        "risk_notes": list(reasoning_packet.risk_notes),
        "byok": True,
        "byok_provider": provider,
        "byok_model": model,
    }

    # Update the signal's reasoning in the database
    await db.update_signal_reasoning(signal_id, new_reasoning)

    # Also update confidence/stance/event_type if the LLM provided them
    raw = reasoning_packet.raw or {}
    updates = {}
    if raw.get("confidence") is not None:
        try:
            updates["confidence"] = max(0.0, min(1.0, float(raw["confidence"])))
        except (ValueError, TypeError):
            pass
    if raw.get("stance") in ("bullish", "bearish", "mixed", "unknown"):
        updates["stance"] = raw["stance"]
    if raw.get("event_type"):
        updates["event_type"] = raw["event_type"]

    if updates:
        await db.update_signal_fields(signal_id, updates)

    return {
        "ok": True,
        "reasoning": new_reasoning,
        "message": f"Signal re-analyzed with {provider}/{model}",
    }
