"""Weekly Wrap — auto-generated weekly market summary from signal data."""
from __future__ import annotations

import datetime
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web import tier_gate

router = APIRouter()


def _base_context(request: Request, user: dict | None) -> dict:
    tier = (user or {}).get("tier", "free")
    badge_map = {
        "free": "bg-gray-700 text-gray-300",
        "pro": "bg-blue-700/60 text-blue-200",
        "premium": "bg-purple-700/60 text-purple-200",
        "ultra": "bg-orange-700/60 text-orange-200",
    }
    return {
        "request": request,
        "user": user,
        "tier": tier,
        "tier_badge_class": badge_map.get(tier, badge_map["free"]),
        "stripe_enabled": bool(request.app.state.settings.stripe.secret_key),
    }


def _week_bounds(weeks_ago: int = 0) -> tuple[float, float, str]:
    """Return (start_ts, end_ts, label) for a given week offset (0 = current)."""
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    # Monday of current week
    monday = now - datetime.timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)

    start = monday - datetime.timedelta(weeks=weeks_ago)
    end = start + datetime.timedelta(days=7)

    label = f"{start.strftime('%b %d')} – {(end - datetime.timedelta(days=1)).strftime('%b %d, %Y')}"
    return start.timestamp(), end.timestamp(), label


@router.get("/weekly-wrap", response_class=HTMLResponse)
async def weekly_wrap(request: Request, week: str = "0"):
    """Weekly Wrap — auto-generated weekly market summary."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)
    tier = ctx["tier"]

    access = tier_gate.gate_weekly_wrap_access(tier)
    weeks_ago = min(int(week) if week.isdigit() else 0, access["max_weeks_back"])

    start_ts, end_ts, week_label = _week_bounds(weeks_ago)

    db = request.app.state.db
    summary = await db.get_weekly_summary(start_ts, end_ts)

    # Parse summary data — DB returns: total_signals, bullish, bearish, mixed, avg_confidence
    total_signals = summary.get("total_signals", 0) or 0
    bullish_count = summary.get("bullish", 0) or 0
    bearish_count = summary.get("bearish", 0) or 0
    mixed_count = summary.get("mixed", 0) or 0
    avg_confidence = round((summary.get("avg_confidence") or 0) * 100, 1)

    # DB returns top_tickers as list of {ticker, count, avg_conf, bull, bear}
    # Normalize field names for template
    raw_tickers = summary.get("top_tickers", [])
    top_tickers = []
    for t in raw_tickers:
        top_tickers.append({
            "ticker": t.get("ticker", "???"),
            "total": t.get("count", 0) or 0,
            "avg_confidence": t.get("avg_conf", 0) or 0,
            "bullish": t.get("bull", 0) or 0,
            "bearish": t.get("bear", 0) or 0,
        })

    # DB returns best_calls / worst_calls as lists
    best_calls = summary.get("best_calls", [])
    worst_calls = summary.get("worst_calls", [])
    best_call = None
    worst_call = None
    if best_calls:
        bc = best_calls[0]
        best_call = {
            "ticker": bc.get("ticker", "???"),
            "stance": bc.get("stance", "unknown"),
            "confidence": bc.get("confidence", 0) or 0,
            "gain_pct": bc.get("max_gain_pct"),
        }
    if worst_calls:
        wc = worst_calls[0]
        worst_call = {
            "ticker": wc.get("ticker", "???"),
            "stance": wc.get("stance", "unknown"),
            "confidence": wc.get("confidence", 0) or 0,
            "gain_pct": wc.get("max_loss_pct"),
        }

    # Bullish consensus: tickers with 3+ bullish signals
    bullish_tickers = [t for t in top_tickers if t.get("bullish", 0) >= 3]
    # Bearish consensus
    bearish_tickers = [t for t in top_tickers if t.get("bearish", 0) >= 3]
    # Controversy corner: tickers with both bullish and bearish signals
    controversial = [
        t for t in top_tickers
        if t.get("bullish", 0) >= 1 and t.get("bearish", 0) >= 1
    ]

    # Week navigation options
    week_options = []
    for i in range(min(access["max_weeks_back"] + 1, 53)):
        _, _, lbl = _week_bounds(i)
        week_options.append({"value": str(i), "label": lbl})

    ctx.update({
        "week_label": week_label,
        "selected_week": str(weeks_ago),
        "total_signals": total_signals,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "mixed_count": mixed_count,
        "avg_confidence": avg_confidence,
        "top_tickers": top_tickers[:15],
        "bullish_tickers": bullish_tickers[:5],
        "bearish_tickers": bearish_tickers[:5],
        "controversial": controversial[:5],
        "best_call": best_call,
        "worst_call": worst_call,
        "week_options": week_options,
        "access": access,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("weekly_wrap.html", ctx)
