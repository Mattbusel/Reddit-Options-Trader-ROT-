from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

router = APIRouter()

# Connected WebSocket clients
_clients: Set[WebSocket] = set()


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


@router.websocket("/signals/live")
async def signal_websocket(websocket: WebSocket):
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
        pass
    finally:
        _clients.discard(websocket)
        log.info("WebSocket client disconnected (%d remaining)", len(_clients))
