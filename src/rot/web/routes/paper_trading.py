"""Paper Trading routes.

Provides:
  - /paper-trading — HTML dashboard with portfolio, positions, history
  - /api/v1/paper-trading/trade — execute a paper trade on a signal
  - /api/v1/paper-trading/close/{trade_id} — close an open position
  - /api/v1/paper-trading/portfolio — JSON portfolio stats
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rot.web.auth import get_current_user_optional, require_user

log = logging.getLogger(__name__)

router = APIRouter()

_STARTING_BALANCE = 10000.0


class PaperTradeRequest(BaseModel):
    signal_id: str
    dollars: float = 1000.0  # how much $ to allocate


# ── HTML page ──

@router.get("/paper-trading", response_class=HTMLResponse)
async def paper_trading_page(request: Request):
    """Paper trading dashboard."""
    user = await get_current_user_optional(request)
    templates = request.app.state.templates
    db = request.app.state.db

    portfolio = None
    open_trades = []
    closed_trades = []

    if user:
        portfolio = await db.get_paper_portfolio(user["id"])
        if not portfolio:
            await db.init_paper_portfolio(user["id"])
            portfolio = await db.get_paper_portfolio(user["id"])
        open_trades = await db.get_paper_trades(user["id"], status="open", limit=50)
        closed_trades = await db.get_paper_trades(user["id"], status="closed", limit=50)

    return templates.TemplateResponse("paper_trading.html", {
        "request": request,
        "user": user,
        "tier": (user or {}).get("tier", "free"),
        "portfolio": portfolio,
        "open_trades": open_trades,
        "closed_trades": closed_trades,
    })


# ── Execute paper trade ──

@router.post("/api/v1/paper-trading/trade")
async def execute_paper_trade(body: PaperTradeRequest, request: Request):
    """Paper-buy a signal position."""
    user = await require_user(request)
    db = request.app.state.db

    # Get or init portfolio
    portfolio = await db.get_paper_portfolio(user["id"])
    if not portfolio:
        await db.init_paper_portfolio(user["id"])
        portfolio = await db.get_paper_portfolio(user["id"])

    # Validate allocation
    dollars = min(max(body.dollars, 10.0), portfolio["balance"])
    if portfolio["balance"] < 10.0:
        raise HTTPException(status_code=400, detail="Insufficient paper balance")

    # Get signal + price
    signal = await db.get_signal(body.signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    # Get entry price from performance data or market_data
    perf = await db.get_performance_for_signal(body.signal_id)
    entry_price = None
    if perf:
        entry_price = perf.get("price_at_signal")
    if not entry_price:
        md = signal.get("market_data", {})
        ticker = signal.get("ticker", "")
        if isinstance(md, dict) and ticker in md:
            entry_price = md[ticker].get("price") or md[ticker].get("currentPrice")
    if not entry_price or entry_price <= 0:
        raise HTTPException(status_code=400, detail="No price data for this signal")

    # Calculate quantity (fractional shares ok)
    quantity = round(dollars / entry_price, 4)

    trade = await db.create_paper_trade(
        user_id=user["id"],
        signal_id=body.signal_id,
        ticker=signal["ticker"],
        stance=signal.get("stance", "unknown"),
        entry_price=entry_price,
        quantity=quantity,
        dollars=dollars,
    )

    return {"ok": True, "trade": trade}


# ── Close position ──

@router.post("/api/v1/paper-trading/close/{trade_id}")
async def close_paper_trade(trade_id: str, request: Request):
    """Close an open paper trade at current price."""
    user = await require_user(request)
    db = request.app.state.db

    trade = await db.get_paper_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not your trade")
    if trade["status"] != "open":
        raise HTTPException(status_code=400, detail="Trade already closed")

    # Get current price from performance table
    perf = await db.get_performance_for_signal(trade["signal_id"])
    exit_price = None
    if perf:
        # Use the latest available price snapshot
        for field in ("price_1w", "price_1d", "price_4h", "price_1h", "price_at_signal"):
            p = perf.get(field)
            if p and p > 0:
                exit_price = p
                break
    if not exit_price:
        raise HTTPException(status_code=400, detail="No current price available yet — try again later")

    result = await db.close_paper_trade(trade_id, exit_price)
    return {"ok": True, "trade": result}


# ── Portfolio JSON ──

@router.get("/api/v1/paper-trading/portfolio")
async def paper_portfolio(request: Request):
    """Return portfolio stats as JSON."""
    user = await require_user(request)
    db = request.app.state.db

    portfolio = await db.get_paper_portfolio(user["id"])
    if not portfolio:
        await db.init_paper_portfolio(user["id"])
        portfolio = await db.get_paper_portfolio(user["id"])

    open_trades = await db.get_paper_trades(user["id"], status="open", limit=50)

    return {
        "portfolio": portfolio,
        "open_positions": len(open_trades),
    }
