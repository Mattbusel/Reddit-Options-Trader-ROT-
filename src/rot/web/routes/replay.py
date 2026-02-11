"""Signal Replay — animated signal timeline visualization."""
from __future__ import annotations

import json

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


@router.get("/replay", response_class=HTMLResponse)
async def signal_replay(request: Request, hours: str = "24"):
    """Signal Replay — animated signal timeline."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)
    tier = ctx["tier"]

    access = tier_gate.gate_replay_access(tier)

    # Free tier gets no access
    if not access["has_access"]:
        ctx.update({
            "access": access,
            "signals_json": "[]",
            "total_signals": 0,
            "selected_hours": "24",
        })
        templates = request.app.state.templates
        return templates.TemplateResponse("replay.html", ctx)

    hours_int = min(int(hours) if hours.isdigit() else 24, access["max_hours"])

    db = request.app.state.db
    signals = await db.get_replay_data(
        hours=hours_int,
        include_performance=access["has_price_overlay"],
    )

    # Transform for frontend: each signal becomes a timeline dot
    replay_data = []
    for s in signals:
        entities = s.get("entities", [])
        if isinstance(entities, str):
            try:
                entities = json.loads(entities)
            except Exception:
                entities = []

        replay_data.append({
            "ts": int(s.get("created_at", 0) * 1000),  # JS timestamp
            "ticker": entities[0] if entities else "???",
            "stance": s.get("stance", "unknown"),
            "confidence": round(s.get("confidence", 0) * 100, 1),
            "event_type": s.get("event_type", ""),
            "thesis": (s.get("thesis") or "")[:120],
            "gain_pct": s.get("gain_pct"),
        })

    # Time range options
    time_options = [
        {"value": "24", "label": "24h", "min_tier": "pro"},
        {"value": "168", "label": "7d", "min_tier": "premium"},
        {"value": "720", "label": "30d", "min_tier": "ultra"},
    ]

    ctx.update({
        "access": access,
        "signals_json": json.dumps(replay_data),
        "total_signals": len(replay_data),
        "selected_hours": str(hours_int),
        "time_options": time_options,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("replay.html", ctx)
