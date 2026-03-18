from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

log = logging.getLogger(__name__)

router = APIRouter()

# Connected WebSocket clients
_clients: Set[WebSocket] = set()
MAX_WS_CLIENTS = 200

_PAID_TIERS = ("pro", "premium", "ultra", "enterprise")

# Timeout for the first auth message after connection
_AUTH_TIMEOUT_S = 10


def _jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    return obj


async def broadcast_signal(signal_data: dict) -> None:
    """Broadcast a signal to all connected WebSocket clients."""
    if not _clients:
        return

    msg = json.dumps(_jsonable(signal_data), default=str)
    dead: list[WebSocket] = []

    for ws in _clients:
        try:
            await ws.send_text(msg)
        except Exception:
            log.exception("Failed to send WebSocket broadcast message; marking client as dead")
            dead.append(ws)

    for ws in dead:
        _clients.discard(ws)


def _validate_token(websocket: WebSocket, token: str) -> bool:
    """Validate a JWT token. Returns True if user has paid tier."""
    if not token:
        return False

    settings = websocket.app.state.settings
    secret = settings.auth.jwt_secret or settings.web.secret_key
    algorithm = settings.auth.jwt_algorithm

    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        tier = payload.get("tier", "free")
        return tier in _PAID_TIERS
    except JWTError:
        return False


@router.websocket("/signals/live")
async def signal_websocket(websocket: WebSocket):
    """Accept a WebSocket connection, authenticate via first message, then stream live signals."""
    if len(_clients) >= MAX_WS_CLIENTS:
        await websocket.close(code=4008, reason="Too many connections")
        return

    # Accept first, then authenticate via first message.
    # This avoids leaking JWTs in URL query strings (browser history, server logs).
    await websocket.accept()

    try:
        # Wait for auth message: {"type": "auth", "token": "<jwt>"}
        raw = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=_AUTH_TIMEOUT_S,
        )
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await websocket.close(code=4003, reason="Invalid auth message")
            return

        if msg.get("type") != "auth" or not isinstance(msg.get("token"), str):
            await websocket.close(code=4003, reason="Expected auth message with token")
            return

        if not _validate_token(websocket, msg["token"]):
            await websocket.close(code=4003, reason="WebSocket requires Pro or higher tier")
            return

        # Auth succeeded — send confirmation and add to broadcast set
        await websocket.send_text(json.dumps({"type": "auth_ok"}))

    except asyncio.TimeoutError:
        await websocket.close(code=4003, reason="Auth timeout")
        return
    except WebSocketDisconnect:
        return

    _clients.add(websocket)
    log.info("WebSocket client connected (%d total)", len(_clients))

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass  # Intentionally suppressed
    finally:
        _clients.discard(websocket)
        log.info("WebSocket client disconnected (%d remaining)", len(_clients))
