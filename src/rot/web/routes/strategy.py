"""Strategy Builder routes — dashboard, CRUD, discovery, ML, genetic, marketplace, regimes."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_strategy_access
from rot.web.validation import (
    CreateStrategyRequest,
    DiscoverStrategiesRequest,
    GeneticEvolveRequest,
    MLOptimizeRequest,
    PublishToMarketplaceRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_db(request: Request):
    return request.app.state.db


def _get_templates(request: Request):
    return request.app.state.templates


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------


@router.get("/strategies", response_class=HTMLResponse)
async def strategies_page(request: Request):
    """Strategy builder dashboard."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_strategy_access(tier)
    templates = _get_templates(request)
    db = _get_db(request)

    strategies = []
    if user and access["has_access"]:
        strategies = await db.get_user_strategies(user["id"])

    return templates.TemplateResponse(
        "strategies.html",
        {
            "request": request,
            "user": user,
            "access": access,
            "strategies": strategies,
        },
    )


@router.get("/strategies/{strategy_id}", response_class=HTMLResponse)
async def strategy_detail_page(request: Request, strategy_id: str):
    """Strategy detail page with trades and performance."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_strategy_access(tier)
    templates = _get_templates(request)
    db = _get_db(request)

    if not access["has_access"]:
        raise HTTPException(status_code=403, detail="Upgrade to Pro+ for strategies")

    strategy = await db.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    trades = await db.get_strategy_trades(strategy_id, limit=50)

    return templates.TemplateResponse(
        "strategy_detail.html",
        {
            "request": request,
            "user": user,
            "access": access,
            "strategy": strategy,
            "trades": trades,
        },
    )


@router.get("/marketplace", response_class=HTMLResponse)
async def marketplace_page(request: Request):
    """Strategy marketplace page."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_strategy_access(tier)
    templates = _get_templates(request)
    db = _get_db(request)

    entries = []
    if access.get("has_marketplace"):
        entries = await db.get_marketplace_entries(sort_by="rating", limit=20)

    return templates.TemplateResponse(
        "marketplace.html",
        {
            "request": request,
            "user": user,
            "access": access,
            "entries": entries,
        },
    )


@router.get("/strategies/regimes", response_class=HTMLResponse)
async def regimes_page(request: Request):
    """Market regimes dashboard."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_strategy_access(tier)
    templates = _get_templates(request)
    db = _get_db(request)

    regimes = []
    if access.get("has_regimes"):
        regimes = await db.get_market_regimes(days=90)

    return templates.TemplateResponse(
        "regimes.html",
        {
            "request": request,
            "user": user,
            "access": access,
            "regimes": regimes,
        },
    )


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------


@router.post("/api/v1/strategies/create")
async def create_strategy(body: CreateStrategyRequest, request: Request):
    """Create a new manual strategy."""
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    tier = user["tier"]
    access = gate_strategy_access(tier)
    if not access["has_access"]:
        raise HTTPException(status_code=403, detail="Upgrade to Pro+ for strategies")

    db = _get_db(request)

    # Check strategy limit
    existing = await db.get_user_strategies(user["id"])
    if len(existing) >= access["max_strategies"]:
        raise HTTPException(
            status_code=403,
            detail=f"Strategy limit reached ({access['max_strategies']}). Upgrade for more.",
        )

    strategy = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "name": body.name.strip(),
        "description": body.description,
        "rules": body.rules,
        "config": body.config,
        "performance": {},
        "health_score": 1.0,
        "is_active": False,
        "source": "manual",
        "created_at": time.time(),
        "updated_at": time.time(),
    }

    await db.save_strategy(strategy)
    return JSONResponse({"ok": True, "strategy_id": strategy["id"]})


@router.post("/api/v1/strategies/{strategy_id}/activate")
async def activate_strategy(request: Request, strategy_id: str):
    """Toggle a strategy's active status."""
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    db = _get_db(request)
    strategy = await db.get_strategy(strategy_id)
    if not strategy or strategy["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Strategy not found")

    new_active = not strategy["is_active"]
    await db.update_strategy_health(strategy_id, strategy["health_score"], new_active)
    return JSONResponse({"ok": True, "is_active": new_active})


@router.delete("/api/v1/strategies/{strategy_id}")
async def delete_strategy(request: Request, strategy_id: str):
    """Delete a strategy."""
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    db = _get_db(request)
    deleted = await db.delete_strategy(strategy_id, user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return JSONResponse({"ok": True})


@router.post("/api/v1/strategies/discover")
async def discover_strategies(body: DiscoverStrategiesRequest, request: Request):
    """Run strategy discovery."""
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    access = gate_strategy_access(user["tier"])
    if not access.get("has_discovery"):
        raise HTTPException(status_code=403, detail="Upgrade to Premium+ for discovery")

    db = _get_db(request)

    try:
        from rot.backtest import BacktestConfig, BacktestEngine
        from rot.strategy.discovery import StrategyDiscoverer

        signals = await db.get_signals_for_backtest(
            days=body.days, limit=body.max_signals
        )

        discoverer = StrategyDiscoverer(signals)
        search_config = {
            "max_rules": body.max_rules,
            "max_candidates": body.max_candidates,
            "min_trades": body.min_trades,
            "min_win_rate": body.min_win_rate,
            "min_sharpe": body.min_sharpe,
            "search_mode": body.search_mode,
            "walk_forward": body.walk_forward,
        }

        result = discoverer.discover(search_config)
        await db.save_discovery_result(result.to_dict())

        return JSONResponse({
            "ok": True,
            "strategies_found": result.strategies_found,
            "best_strategies": result.best_strategies[:10],
            "elapsed_s": result.elapsed_s,
        })
    except Exception:
        logger.exception("Strategy discovery failed")
        return JSONResponse({"ok": False, "error": "Strategy discovery failed"}, status_code=500)


@router.post("/api/v1/strategies/ml-optimize")
async def ml_optimize(body: MLOptimizeRequest, request: Request):
    """Run ML optimization."""
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    access = gate_strategy_access(user["tier"])
    if not access.get("has_ml_optimize"):
        raise HTTPException(status_code=403, detail="Upgrade to Premium+ for ML optimization")

    db = _get_db(request)

    try:
        from rot.strategy.ml_optimizer import MLStrategyOptimizer

        signals = await db.get_signals_for_backtest(
            days=body.days, limit=body.max_signals
        )

        optimizer = MLStrategyOptimizer(min_signals=body.min_signals)
        result = optimizer.optimize(signals)

        return JSONResponse({"ok": True, **result})
    except Exception:
        logger.exception("ML optimization failed")
        return JSONResponse({"ok": False, "error": "Strategy optimization failed"}, status_code=500)


@router.post("/api/v1/strategies/evolve")
async def evolve_strategies(body: GeneticEvolveRequest, request: Request):
    """Run genetic evolution."""
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    access = gate_strategy_access(user["tier"])
    if not access.get("has_genetic"):
        raise HTTPException(status_code=403, detail="Upgrade to Ultra+ for genetic optimization")

    db = _get_db(request)

    try:
        from rot.strategy.genetic import GeneticOptimizer

        signals = await db.get_signals_for_backtest(
            days=body.days, limit=body.max_signals
        )

        optimizer = GeneticOptimizer(
            signals=signals,
            population_size=body.population_size,
            generations=body.generations,
            max_rules=body.max_rules,
        )

        result = optimizer.evolve()
        return JSONResponse({"ok": True, **result})
    except Exception:
        logger.exception("Genetic evolution failed")
        return JSONResponse({"ok": False, "error": "Strategy evolution failed"}, status_code=500)


@router.get("/api/v1/strategies/regimes")
async def get_regimes(
    request: Request,
    days: int = Query(90, ge=1, le=365),
):
    """Get market regime data."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_strategy_access(tier)

    if not access.get("has_regimes"):
        raise HTTPException(status_code=403, detail="Upgrade to Premium+ for regime analysis")

    db = _get_db(request)
    regimes = await db.get_market_regimes(days=days)
    return JSONResponse({"regimes": regimes})


@router.get("/api/v1/marketplace")
async def get_marketplace(
    request: Request,
    sort_by: str = Query("rating"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Get marketplace entries."""
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_strategy_access(tier)

    if not access.get("has_marketplace"):
        raise HTTPException(status_code=403, detail="Upgrade to Ultra+ for marketplace")

    db = _get_db(request)
    entries = await db.get_marketplace_entries(sort_by=sort_by, limit=limit, offset=offset)
    return JSONResponse({"entries": entries})


@router.post("/api/v1/marketplace/publish")
async def publish_to_marketplace(body: PublishToMarketplaceRequest, request: Request):
    """Publish a strategy to the marketplace."""
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    access = gate_strategy_access(user["tier"])
    if not access.get("has_marketplace"):
        raise HTTPException(status_code=403, detail="Upgrade to Ultra+ for marketplace")

    db = _get_db(request)

    strategy = await db.get_strategy(body.strategy_id)
    if not strategy or strategy["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Strategy not found")

    entry = {
        "id": str(uuid.uuid4()),
        "strategy_id": body.strategy_id,
        "author_id": user["id"],
        "name": body.name or strategy["name"],
        "description": body.description or strategy.get("description", ""),
        "performance": strategy.get("performance", {}),
        "subscriber_count": 0,
        "rating": 0.0,
        "created_at": time.time(),
    }

    await db.save_marketplace_entry(entry)
    return JSONResponse({"ok": True, "entry_id": entry["id"]})
