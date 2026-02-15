"""Paper Trading routes.

Provides:
  - /paper-trading — HTML dashboard with portfolio, positions, history
  - /api/v1/paper-trading/trade — execute a paper trade on a signal
  - /api/v1/paper-trading/close/{trade_id} — close an open position
  - /api/v1/paper-trading/portfolio — JSON portfolio stats

Business logic is delegated to PaperTradingService; route handlers are
thin wrappers that map service exceptions to HTTP status codes.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rot.services.paper_trading_service import (
    InsufficientBalanceError,
    NoPriceDataError,
    NotOwnerError,
    SignalNotFoundError,
    TradeAlreadyClosedError,
    TradeNotFoundError,
)
from rot.web.auth import get_current_user_optional, require_user

log = logging.getLogger(__name__)

router = APIRouter()


class PaperTradeRequest(BaseModel):
    signal_id: str
    dollars: float = 1000.0  # how much $ to allocate


# ── HTML page ──

@router.get("/paper-trading", response_class=HTMLResponse)
async def paper_trading_page(request: Request):
    """Paper trading dashboard."""
    user = await get_current_user_optional(request)
    templates = request.app.state.templates
    svc = request.app.state.paper_trading_service

    portfolio = None
    open_trades = []
    closed_trades = []

    if user:
        portfolio = await svc.get_or_create_portfolio(user["id"])
        open_trades = await svc.get_trades(user["id"], status="open", limit=50)
        closed_trades = await svc.get_trades(user["id"], status="closed", limit=50)

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
    svc = request.app.state.paper_trading_service

    try:
        trade = await svc.execute_trade(user["id"], body.signal_id, body.dollars)
    except InsufficientBalanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SignalNotFoundError:
        raise HTTPException(status_code=404, detail="Signal not found")
    except NoPriceDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ok": True, "trade": trade}


# ── Close position ──

@router.post("/api/v1/paper-trading/close/{trade_id}")
async def close_paper_trade(trade_id: str, request: Request):
    """Close an open paper trade at current price."""
    user = await require_user(request)
    svc = request.app.state.paper_trading_service

    try:
        result = await svc.close_trade(user["id"], trade_id)
    except TradeNotFoundError:
        raise HTTPException(status_code=404, detail="Trade not found")
    except NotOwnerError:
        raise HTTPException(status_code=403, detail="Not your trade")
    except TradeAlreadyClosedError:
        raise HTTPException(status_code=400, detail="Trade already closed")
    except NoPriceDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ok": True, "trade": result}


# ── Portfolio JSON ──

@router.get("/api/v1/paper-trading/portfolio")
async def paper_portfolio(request: Request):
    """Return portfolio stats as JSON."""
    user = await require_user(request)
    svc = request.app.state.paper_trading_service
    return await svc.get_portfolio_summary(user["id"])
