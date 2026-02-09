from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


def _format_time(ts: float | None) -> str:
    if not ts:
        return "N/A"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _stance_color(stance: str) -> str:
    return {
        "bullish": "text-green-400",
        "bearish": "text-red-400",
        "mixed": "text-yellow-400",
    }.get(stance, "text-gray-400")


def _stance_bg(stance: str) -> str:
    return {
        "bullish": "bg-green-900/30 border-green-700",
        "bearish": "bg-red-900/30 border-red-700",
        "mixed": "bg-yellow-900/30 border-yellow-700",
    }.get(stance, "bg-gray-900/30 border-gray-700")


def _confidence_bar(conf: float) -> str:
    pct = int(conf * 100)
    if conf >= 0.6:
        color = "bg-green-500"
    elif conf >= 0.4:
        color = "bg-yellow-500"
    else:
        color = "bg-red-500"
    return f'<div class="w-full bg-gray-700 rounded h-2"><div class="{color} h-2 rounded" style="width:{pct}%"></div></div>'


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = request.app.state.db
    signals = await db.get_signals(limit=50)
    trending = await db.get_trending_tickers(hours=24, limit=10)
    summary = await db.get_performance_summary(days=30)

    templates = request.app.state.templates
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "signals": signals,
        "trending": trending,
        "summary": summary,
        "format_time": _format_time,
        "stance_color": _stance_color,
        "stance_bg": _stance_bg,
        "confidence_bar": _confidence_bar,
    })


@router.get("/dashboard/signal/{signal_id}", response_class=HTMLResponse)
async def signal_detail(request: Request, signal_id: str):
    db = request.app.state.db
    signal = await db.get_signal(signal_id)
    if not signal:
        return HTMLResponse("<h1>Signal not found</h1>", status_code=404)

    templates = request.app.state.templates
    return templates.TemplateResponse("signal_detail.html", {
        "request": request,
        "signal": signal,
        "format_time": _format_time,
        "stance_color": _stance_color,
        "stance_bg": _stance_bg,
        "confidence_bar": _confidence_bar,
        "json_dumps": json.dumps,
    })
