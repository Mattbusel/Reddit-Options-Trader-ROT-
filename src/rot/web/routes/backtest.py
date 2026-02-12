"""Backtesting view routes (ultra tier).

Replays historical signals against known price outcomes to evaluate strategy performance.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from rot.web.auth import get_current_user_optional

router = APIRouter()


@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    """Backtesting dashboard page (ultra only)."""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    tier = user.get("tier", "free")
    if tier != "ultra":
        return RedirectResponse(url="/pricing", status_code=302)

    db = request.app.state.db

    # Get strategy list for the dropdown
    strategy_pnl = await db.get_strategy_pnl(days=365)
    strategies = [s["strategy"] for s in strategy_pnl] if strategy_pnl else []

    # Get default backtest results (30 days, all strategies)
    q_days = request.query_params.get("days", "30")
    q_strategy = request.query_params.get("strategy", "")
    q_min_conf = request.query_params.get("min_confidence", "")

    try:
        days = int(q_days)
    except ValueError:
        days = 30

    min_conf = None
    if q_min_conf:
        try:
            min_conf = float(q_min_conf) / 100.0
        except ValueError:
            pass

    # Get performance history with optional filtering
    history = await db.get_performance_history(
        days=days,
        ticker=None,
        limit=200,
    )

    # Filter by strategy and min confidence on the Python side
    if q_strategy:
        history = [h for h in history if h.get("strategy") == q_strategy]
    if min_conf is not None:
        history = [h for h in history if h.get("confidence", 0) >= min_conf]

    # Compute backtest summary
    total = len(history)
    winners = sum(1 for h in history if (h.get("gain_loss_pct") or 0) > 0)
    losers = total - winners
    win_rate = (winners / total * 100) if total > 0 else 0

    gains = [h["gain_loss_pct"] for h in history if (h.get("gain_loss_pct") or 0) > 0]
    losses = [h["gain_loss_pct"] for h in history if (h.get("gain_loss_pct") or 0) <= 0]
    avg_gain = sum(gains) / len(gains) if gains else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    cumulative_pnl = sum(h.get("gain_loss_pct", 0) or 0 for h in history)

    # Build equity curve data (cumulative P&L over time)
    equity_curve = []
    running_pnl = 0
    for h in sorted(history, key=lambda x: x.get("created_at", 0)):
        running_pnl += h.get("gain_loss_pct", 0) or 0
        equity_curve.append({
            "ts": h.get("created_at", 0),
            "pnl": round(running_pnl, 2),
            "ticker": h.get("ticker", "?"),
        })

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "strategies": strategies,
        "history": history[:100],  # Top 100 for table
        "backtest_summary": {
            "total": total,
            "winners": winners,
            "losers": losers,
            "win_rate": round(win_rate, 1),
            "avg_gain": round(avg_gain, 2),
            "avg_loss": round(avg_loss, 2),
            "cumulative_pnl": round(cumulative_pnl, 2),
        },
        "equity_curve": equity_curve,
        "filter_days": days,
        "filter_strategy": q_strategy,
        "filter_min_confidence": q_min_conf,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("backtest.html", ctx)
