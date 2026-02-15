from __future__ import annotations

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
            dead.append(ws)

    for ws in dead:
        _clients.discard(ws)


async def _authenticate_ws(websocket: WebSocket) -> bool:
    """Check JWT from query param. Returns True if user has paid tier."""
    token = websocket.query_params.get("token", "")
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
    # Check auth before accepting
    is_paid = await _authenticate_ws(websocket)
    if not is_paid:
        await websocket.close(code=4003, reason="WebSocket requires Pro or higher tier")
        return

    if len(_clients) >= MAX_WS_CLIENTS:
        await websocket.close(code=4008, reason="Too many connections")
        return

    await websocket.accept()
    _clients.add(websocket)
    log.info("WebSocket client connected (%d total)", len(_clients))

    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass  # Intentionally suppressed
    finally:
        _clients.discard(websocket)
        log.info("WebSocket client disconnected (%d remaining)", len(_clients))
