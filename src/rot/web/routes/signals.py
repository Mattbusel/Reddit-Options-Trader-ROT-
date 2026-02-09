from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

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
):
    db = request.app.state.db
    signals = await db.get_signals(
        limit=limit,
        offset=offset,
        ticker=ticker,
        stance=stance,
        min_confidence=min_confidence,
        event_type=event_type,
    )
    return {"signals": signals, "count": len(signals), "offset": offset}


@router.get("/signals/{signal_id}")
async def get_signal(request: Request, signal_id: str):
    db = request.app.state.db
    signal = await db.get_signal(signal_id)
    if not signal:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@router.get("/tickers/trending")
async def trending_tickers(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(20, ge=1, le=100),
):
    db = request.app.state.db
    tickers = await db.get_trending_tickers(hours=hours, limit=limit)
    return {"tickers": tickers, "period_hours": hours}


@router.get("/performance/summary")
async def performance_summary(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    db = request.app.state.db
    summary = await db.get_performance_summary(days=days)
    return summary
