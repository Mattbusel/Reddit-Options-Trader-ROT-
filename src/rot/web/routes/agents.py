"""Autonomous Trading Agents — CRUD routes + dashboard."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from rot.web.auth import get_current_user_optional, require_user
from rot.web.tier_gate import gate_agent_access

router = APIRouter()
log = logging.getLogger(__name__)


class CreateAgentRequest(BaseModel):
    name: str
    agent_type: str = "signal_follower"
    rules: List[Dict[str, Any]] = []
    config: Dict[str, Any] = {}
    max_daily_trades: int = 5
    max_position_dollars: float = 2000.0
    max_portfolio_exposure_pct: float = 50.0
    min_confidence: float = 0.4
    stop_loss_pct: float = 10.0


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    rules: Optional[List[Dict[str, Any]]] = None
    config: Optional[Dict[str, Any]] = None
    max_daily_trades: Optional[int] = None
    max_position_dollars: Optional[float] = None
    max_portfolio_exposure_pct: Optional[float] = None
    min_confidence: Optional[float] = None
    stop_loss_pct: Optional[float] = None


@router.get("/agents", response_class=HTMLResponse)
async def agents_page(request: Request):
    """Agent dashboard — list agents, create new, view KPIs."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_agent_access(tier)
    templates = request.app.state.templates

    agents = []
    if access["has_access"] and user:
        db = request.app.state.db
        try:
            agents = await db.get_agents_for_user(user["id"])
        except Exception as e:
            log.error("Failed to fetch agents: %s", e)

    return templates.TemplateResponse("agents.html", {
        "request": request,
        "user": user or {"tier": "free"},
        "tier": tier,
        "access": access,
        "agents": agents,
    })


@router.get("/agents/{agent_id}", response_class=HTMLResponse)
async def agent_detail_page(request: Request, agent_id: str):
    """Agent detail — trades, performance, config."""
    user = await require_user(request)
    tier = user["tier"]
    access = gate_agent_access(tier)
    templates = request.app.state.templates
    db = request.app.state.db

    if not access["has_access"]:
        return HTMLResponse("Upgrade to Ultra for trading agents", status_code=403)

    agent = await db.get_agent(agent_id)
    if not agent or agent["user_id"] != user["id"]:
        return HTMLResponse("Agent not found", status_code=404)

    trades = await db.get_agent_trades(agent_id, limit=50)
    perf = await db.get_agent_performance_stats(agent_id)

    return templates.TemplateResponse("agents_detail.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
        "agent": agent,
        "trades": trades,
        "perf": perf,
    })


@router.post("/api/v1/agents/create")
async def create_agent(request: Request, body: CreateAgentRequest):
    """Create a new trading agent."""
    user = await require_user(request)
    tier = user["tier"]
    access = gate_agent_access(tier)

    if not access["has_access"]:
        return JSONResponse({"error": "Upgrade to Ultra for trading agents"}, status_code=403)

    db = request.app.state.db

    # Check agent count limit
    existing = await db.get_agents_for_user(user["id"])
    if len(existing) >= access["max_agents"]:
        return JSONResponse(
            {"error": f"Agent limit reached ({len(existing)}/{access['max_agents']})"},
            status_code=400,
        )

    # Validate agent type
    from rot.agents.types import AGENT_TYPES
    if body.agent_type not in AGENT_TYPES:
        return JSONResponse({"error": f"Invalid agent type: {body.agent_type}"}, status_code=400)

    if body.agent_type == "custom_rule" and not access["has_custom_rules"]:
        return JSONResponse({"error": "Custom rule agents require Enterprise tier"}, status_code=403)

    agent_id = await db.create_agent(
        user_id=user["id"],
        name=body.name,
        agent_type=body.agent_type,
        rules_json=json.dumps(body.rules),
        config_json=json.dumps(body.config),
        max_daily_trades=body.max_daily_trades,
        max_position_dollars=body.max_position_dollars,
        max_portfolio_exposure_pct=body.max_portfolio_exposure_pct,
        min_confidence=body.min_confidence,
        stop_loss_pct=body.stop_loss_pct,
    )

    return JSONResponse({"id": agent_id, "status": "active"}, status_code=201)


@router.put("/api/v1/agents/{agent_id}")
async def update_agent(request: Request, agent_id: str, body: UpdateAgentRequest):
    """Update an existing agent's configuration."""
    user = await require_user(request)
    access = gate_agent_access(user["tier"])
    if not access["has_access"]:
        return JSONResponse({"error": "Upgrade to Ultra"}, status_code=403)

    db = request.app.state.db
    agent = await db.get_agent(agent_id)
    if not agent or agent["user_id"] != user["id"]:
        return JSONResponse({"error": "Agent not found"}, status_code=404)

    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.rules is not None:
        updates["rules_json"] = json.dumps(body.rules)
    if body.config is not None:
        updates["config_json"] = json.dumps(body.config)
    if body.max_daily_trades is not None:
        updates["max_daily_trades"] = body.max_daily_trades
    if body.max_position_dollars is not None:
        updates["max_position_dollars"] = body.max_position_dollars
    if body.max_portfolio_exposure_pct is not None:
        updates["max_portfolio_exposure_pct"] = body.max_portfolio_exposure_pct
    if body.min_confidence is not None:
        updates["min_confidence"] = body.min_confidence
    if body.stop_loss_pct is not None:
        updates["stop_loss_pct"] = body.stop_loss_pct

    if updates:
        updates["updated_at"] = time.time()
        await db.update_agent(agent_id, **updates)

    return JSONResponse({"status": "updated"})


@router.post("/api/v1/agents/{agent_id}/pause")
async def pause_agent(request: Request, agent_id: str):
    """Pause an active agent."""
    user = await require_user(request)
    db = request.app.state.db
    agent = await db.get_agent(agent_id)
    if not agent or agent["user_id"] != user["id"]:
        return JSONResponse({"error": "Agent not found"}, status_code=404)
    await db.update_agent_status(agent_id, "paused")
    return JSONResponse({"status": "paused"})


@router.post("/api/v1/agents/{agent_id}/resume")
async def resume_agent(request: Request, agent_id: str):
    """Resume a paused agent."""
    user = await require_user(request)
    db = request.app.state.db
    agent = await db.get_agent(agent_id)
    if not agent or agent["user_id"] != user["id"]:
        return JSONResponse({"error": "Agent not found"}, status_code=404)
    await db.update_agent_status(agent_id, "active")
    return JSONResponse({"status": "active"})


@router.delete("/api/v1/agents/{agent_id}")
async def delete_agent(request: Request, agent_id: str):
    """Delete an agent and its trade history."""
    user = await require_user(request)
    db = request.app.state.db
    agent = await db.get_agent(agent_id)
    if not agent or agent["user_id"] != user["id"]:
        return JSONResponse({"error": "Agent not found"}, status_code=404)
    await db.delete_agent(agent_id)
    return JSONResponse({"status": "deleted"})


@router.get("/api/v1/agents/{agent_id}/trades")
async def agent_trades(request: Request, agent_id: str):
    """Get agent trade history."""
    user = await require_user(request)
    db = request.app.state.db
    agent = await db.get_agent(agent_id)
    if not agent or agent["user_id"] != user["id"]:
        return JSONResponse({"error": "Agent not found"}, status_code=404)

    status = request.query_params.get("status")
    limit = min(int(request.query_params.get("limit", "50")), 200)
    trades = await db.get_agent_trades(agent_id, status=status, limit=limit)
    return JSONResponse({"trades": trades})


@router.get("/api/v1/agents/{agent_id}/performance")
async def agent_performance(request: Request, agent_id: str):
    """Get agent performance metrics."""
    user = await require_user(request)
    db = request.app.state.db
    agent = await db.get_agent(agent_id)
    if not agent or agent["user_id"] != user["id"]:
        return JSONResponse({"error": "Agent not found"}, status_code=404)

    engine = getattr(request.app.state, "agent_engine", None)
    if engine:
        perf = await engine.get_agent_performance(agent_id)
        return JSONResponse(perf.to_dict())

    stats = await db.get_agent_performance_stats(agent_id)
    return JSONResponse(stats)
