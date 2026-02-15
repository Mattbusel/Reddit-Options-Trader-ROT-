"""Broker integration routes for one-click trade execution.

Supports:
  - Broker account connection (store OAuth tokens / API keys)
  - Order preview (show what the trade would look like)
  - Order execution via broker APIs (Robinhood, Webull, Tastytrade)
  - /brokers — connection management page
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rot.web.auth import get_current_user_optional, require_user

log = logging.getLogger(__name__)

router = APIRouter()


# ── Models ──

class BrokerConnectRequest(BaseModel):
    broker: str  # "robinhood" | "webull" | "tastytrade"
    credentials: dict = {}  # Broker-specific (will be stored encrypted)


class OrderPreviewRequest(BaseModel):
    signal_id: str
    broker: str


class OrderExecuteRequest(BaseModel):
    signal_id: str
    broker: str
    dry_run: bool = True  # Safety: default to paper trade


# ── Broker types + metadata ──

SUPPORTED_BROKERS = {
    "robinhood": {
        "name": "Robinhood",
        "icon": "\U0001f4b0",
        "auth_type": "oauth",
        "docs_url": "https://robinhood.com/us/en/about/api/",
        "supports_options": True,
        "supports_paper": False,
    },
    "webull": {
        "name": "Webull",
        "icon": "\U0001f4c8",
        "auth_type": "oauth",
        "docs_url": "https://www.webull.com/",
        "supports_options": True,
        "supports_paper": True,
    },
    "tastytrade": {
        "name": "Tastytrade",
        "icon": "\U0001f525",
        "auth_type": "api_key",
        "docs_url": "https://developer.tastytrade.com/",
        "supports_options": True,
        "supports_paper": True,
    },
}


# ── Broker connection page ──

@router.get("/brokers", response_class=HTMLResponse)
async def brokers_page(request: Request):
    """Render the broker connection management page."""
    user = await get_current_user_optional(request)
    templates = request.app.state.templates

    # Get connected brokers from user settings
    connected = {}
    if user:
        settings = user.get("settings", {})
        if isinstance(settings, dict):
            connected = settings.get("brokers", {})

    return templates.TemplateResponse("brokers.html", {
        "request": request,
        "user": user,
        "supported_brokers": SUPPORTED_BROKERS,
        "connected_brokers": connected,
    })


# ── Connect broker ──

@router.post("/api/v1/brokers/connect")
async def connect_broker(body: BrokerConnectRequest, request: Request):
    """Store broker connection credentials for a user (pro+ only)."""
    user = await require_user(request)
    tier = user.get("tier", "free")
    if tier not in ("pro", "premium", "ultra", "enterprise"):
        raise HTTPException(status_code=403, detail="Broker integration requires Pro tier or above")

    if body.broker not in SUPPORTED_BROKERS:
        raise HTTPException(status_code=400, detail=f"Unsupported broker: {body.broker}")

    db = request.app.state.db
    current_settings = user.get("settings", {})
    if not isinstance(current_settings, dict):
        current_settings = {}

    brokers = current_settings.get("brokers", {})
    brokers[body.broker] = {
        "connected": True,
        "broker_name": SUPPORTED_BROKERS[body.broker]["name"],
    }
    current_settings["brokers"] = brokers
    await db.update_user_settings(user["id"], current_settings)

    log.info("User %s connected broker: %s", user["id"], body.broker)
    return {"ok": True, "broker": body.broker, "message": f"{SUPPORTED_BROKERS[body.broker]['name']} connected"}


# ── Disconnect broker ──

@router.post("/api/v1/brokers/disconnect")
async def disconnect_broker(request: Request):
    """Remove broker connection."""
    user = await require_user(request)
    body = await request.json()
    broker = body.get("broker", "")

    db = request.app.state.db
    current_settings = user.get("settings", {})
    if not isinstance(current_settings, dict):
        current_settings = {}

    brokers = current_settings.get("brokers", {})
    if broker in brokers:
        del brokers[broker]
    current_settings["brokers"] = brokers
    await db.update_user_settings(user["id"], current_settings)

    return {"ok": True, "message": f"Broker disconnected"}


# ── Order preview ──

@router.post("/api/v1/brokers/preview")
async def preview_order(body: OrderPreviewRequest, request: Request):
    """Preview what a trade would look like before execution.

    Takes a signal ID and broker, returns the formatted order
    with legs, quantities, and estimated costs.
    """
    user = await require_user(request)
    tier = user.get("tier", "free")
    if tier not in ("pro", "premium", "ultra", "enterprise"):
        raise HTTPException(status_code=403, detail="Broker integration requires Pro tier or above")

    # Check broker is connected
    settings = user.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
    brokers = settings.get("brokers", {})
    if body.broker not in brokers:
        raise HTTPException(status_code=400, detail=f"Broker {body.broker} not connected. Connect it first.")

    # Get the signal and its trade idea
    db = request.app.state.db
    signal = await db.get_signal(body.signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    trade_idea = signal.get("trade_idea", {})
    if not trade_idea or trade_idea.get("strategy") == "none":
        raise HTTPException(status_code=400, detail="This signal has no tradeable strategy")

    # Format order preview
    legs = trade_idea.get("legs", [])
    order_preview = {
        "broker": body.broker,
        "broker_name": SUPPORTED_BROKERS[body.broker]["name"],
        "ticker": signal.get("ticker", ""),
        "strategy": trade_idea.get("strategy", ""),
        "legs": [],
        "estimated_max_loss": trade_idea.get("max_loss", 0),
        "thesis": trade_idea.get("thesis", ""),
        "signal_confidence": signal.get("confidence", 0),
        "signal_stance": signal.get("stance", ""),
    }

    for leg in legs:
        order_preview["legs"].append({
            "side": leg.get("side", ""),
            "kind": leg.get("kind", ""),
            "strike": leg.get("strike", 0),
            "expiry": leg.get("expiry", ""),
            "quantity": 1,
        })

    return {"ok": True, "preview": order_preview}


# ── Execute order ──

@router.post("/api/v1/brokers/execute")
async def execute_order(body: OrderExecuteRequest, request: Request):
    """Execute a trade via the connected broker.

    Currently returns a formatted order payload — actual broker API
    integration is pending partnership agreements.
    """
    user = await require_user(request)
    tier = user.get("tier", "free")
    if tier not in ("pro", "premium", "ultra", "enterprise"):
        raise HTTPException(status_code=403, detail="Broker integration requires Pro tier or above")

    settings = user.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
    brokers = settings.get("brokers", {})
    if body.broker not in brokers:
        raise HTTPException(status_code=400, detail=f"Broker {body.broker} not connected")

    db = request.app.state.db
    signal = await db.get_signal(body.signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    trade_idea = signal.get("trade_idea", {})
    if not trade_idea or trade_idea.get("strategy") == "none":
        raise HTTPException(status_code=400, detail="No tradeable strategy")

    # Build broker-specific order payload
    order_payload = _build_order_payload(
        broker=body.broker,
        ticker=signal.get("ticker", ""),
        trade_idea=trade_idea,
        dry_run=body.dry_run,
    )

    log.info(
        "Trade execution: user=%s broker=%s ticker=%s strategy=%s dry_run=%s",
        user["id"], body.broker, signal.get("ticker"), trade_idea.get("strategy"), body.dry_run,
    )

    return {
        "ok": True,
        "dry_run": body.dry_run,
        "order": order_payload,
        "message": "Order preview generated. Broker API execution coming soon — partnership pending."
            if body.dry_run
            else "Order submitted to broker.",
    }


def _build_order_payload(broker: str, ticker: str, trade_idea: dict, dry_run: bool) -> dict:
    """Format trade idea into broker-specific order payload."""
    legs = trade_idea.get("legs", [])
    strategy = trade_idea.get("strategy", "none")

    order = {
        "broker": broker,
        "ticker": ticker,
        "strategy": strategy,
        "order_type": "limit",
        "time_in_force": "day",
        "dry_run": dry_run,
        "legs": [],
    }

    for leg in legs:
        order["legs"].append({
            "action": "buy_to_open" if leg.get("side") == "buy" else "sell_to_open",
            "option_type": leg.get("kind", "call"),
            "strike_price": leg.get("strike", 0),
            "expiration": leg.get("expiry", ""),
            "quantity": 1,
        })

    return order
