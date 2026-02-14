"""Backtesting engine routes.

Full portfolio simulation backtesting with Monte Carlo, walk-forward,
optimization, risk analytics, benchmark comparison, and strategy management.
Pro+ access (tiered features).
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from rot.backtest.benchmark import compare_to_benchmark
from rot.backtest.comparator import compare_strategies
from rot.backtest.config import BacktestConfig
from rot.backtest.engine import BacktestEngine
from rot.backtest.monte_carlo import run_monte_carlo
from rot.backtest.optimizer import optimize
from rot.backtest.risk import compute_risk_metrics
from rot.backtest.walk_forward import run_walk_forward
from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_backtest_access

router = APIRouter()


def _get_access(user: dict | None) -> dict:
    tier = (user or {}).get("tier", "free")
    return gate_backtest_access(tier)


# ── Main Page ──


@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    """Backtesting dashboard with config form and saved runs."""
    user = await get_current_user_optional(request)
    access = _get_access(user)

    if not access["has_access"]:
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return RedirectResponse(url="/pricing", status_code=302)

    db = request.app.state.db
    tier = (user or {}).get("tier", "free")

    # Get strategy list for dropdown
    strategy_pnl = await db.get_strategy_pnl(days=365)
    strategies = [s["strategy"] for s in strategy_pnl] if strategy_pnl else []

    # Get saved runs and strategies
    user_id = (user or {}).get("id", "")
    saved_runs = await db.get_user_backtests(user_id) if user_id else []
    saved_strategies = await db.get_user_backtest_strategies(user_id) if user_id and access["has_saved_strategies"] else []

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "strategies": strategies,
        "saved_runs": saved_runs,
        "saved_strategies": saved_strategies,
        "access": access,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("backtest.html", ctx)


# ── Run Backtest ──


@router.post("/backtest/run", response_class=HTMLResponse)
async def backtest_run(
    request: Request,
    starting_capital: float = Form(10000.0),
    position_size_mode: str = Form("fixed_pct"),
    position_size_pct: float = Form(5.0),
    max_concurrent_positions: int = Form(5),
    stop_loss_pct: float = Form(0.0),
    take_profit_pct: float = Form(0.0),
    min_confidence: float = Form(0.0),
    strategy_filter: str = Form(""),
    event_type_filter: str = Form(""),
    stance_filter: str = Form(""),
    ticker_filter: str = Form(""),
    days: int = Form(90),
    use_1d_price: bool = Form(True),
):
    """Run a backtest and return results partial (HTMX)."""
    user = await get_current_user_optional(request)
    access = _get_access(user)
    if not access["has_access"]:
        return HTMLResponse("<p class='text-red-400'>Upgrade required</p>", status_code=403)

    # Apply tier limits
    days = min(days, access["max_days"])
    if position_size_mode not in access["position_size_modes"]:
        position_size_mode = "fixed_pct"

    config = BacktestConfig(
        starting_capital=starting_capital,
        position_size_mode=position_size_mode,
        position_size_pct=position_size_pct,
        max_concurrent_positions=max_concurrent_positions,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        min_confidence=min_confidence / 100.0 if min_confidence > 1 else min_confidence,
        strategy_filter=strategy_filter or None,
        event_type_filter=event_type_filter or None,
        stance_filter=stance_filter or None,
        ticker_filter=ticker_filter.upper() or None,
        days=days,
        use_1d_price=use_1d_price,
    )

    errors = config.validate()
    if errors:
        return HTMLResponse(f"<p class='text-red-400'>Config errors: {', '.join(errors)}</p>")

    db = request.app.state.db
    signals = await db.get_backtest_signals(
        days=days,
        ticker=config.ticker_filter,
        stance=config.stance_filter,
        strategy=config.strategy_filter,
        event_type=config.event_type_filter,
        min_confidence=config.min_confidence,
        limit=access["max_signals"],
    )

    engine = BacktestEngine()
    result = engine.run(signals, config)

    # Compute risk metrics if allowed
    risk = None
    if access["has_risk_metrics"]:
        risk = compute_risk_metrics(result)

    # Save run
    user_id = (user or {}).get("id", "")
    run_id = ""
    if user_id:
        run_id = await db.save_backtest_run(
            user_id=user_id,
            name=f"Backtest {days}d",
            config_json=json.dumps(config.to_dict()),
            result_json=json.dumps(result.to_dict()),
            risk_json=json.dumps({}) if not risk else json.dumps({
                k: getattr(risk, k) for k in risk.__dataclass_fields__
            }),
        )

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "result": result,
        "result_dict": result.to_dict(),
        "risk": risk,
        "config": config,
        "run_id": run_id,
        "access": access,
        "json_dumps": json.dumps,
        "signal_count": len(signals),
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("backtest_result.html", ctx)


# ── Monte Carlo ──


@router.post("/backtest/monte-carlo/{run_id}", response_class=HTMLResponse)
async def backtest_monte_carlo(request: Request, run_id: str):
    """Run Monte Carlo simulation on a saved backtest run (HTMX)."""
    user = await get_current_user_optional(request)
    access = _get_access(user)
    if not access["has_monte_carlo"]:
        return HTMLResponse("<p class='text-red-400'>Upgrade to Premium for Monte Carlo</p>", status_code=403)

    db = request.app.state.db
    run = await db.get_backtest_run(run_id)
    if not run:
        return HTMLResponse("<p class='text-red-400'>Run not found</p>", status_code=404)

    result_data = json.loads(run.get("result_json", "{}"))
    trades_data = result_data.get("trades", [])

    # Reconstruct TradeRecord objects
    from rot.backtest.result import TradeRecord
    trades = []
    for t in trades_data:
        try:
            trades.append(TradeRecord(
                signal_id=t.get("signal_id", ""),
                ticker=t.get("ticker", ""),
                stance=t.get("stance", ""),
                strategy=t.get("strategy", ""),
                event_type=t.get("event_type", ""),
                confidence=t.get("confidence", 0),
                entry_time=t.get("entry_time", 0),
                entry_price=t.get("entry_price", 0),
                exit_price=t.get("exit_price", 0),
                pnl_pct=t.get("pnl_pct", 0),
                pnl_dollars=t.get("pnl_dollars", 0),
                is_win=t.get("is_win", False),
            ))
        except Exception:
            continue

    config_data = json.loads(run.get("config_json", "{}"))
    starting_capital = config_data.get("starting_capital", 10000.0)

    settings = request.app.state.settings
    n_sims = settings.backtest_server.monte_carlo_sims

    mc_result = run_monte_carlo(trades, starting_capital, n_simulations=n_sims, seed=42)

    # Save MC results back to run
    mc_dict = {
        k: getattr(mc_result, k)
        for k in mc_result.__dataclass_fields__
    }
    await db.db.execute(
        "UPDATE backtest_runs SET monte_carlo_json = ? WHERE id = ?",
        (json.dumps(mc_dict), run_id),
    )
    await db.db.commit()

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "mc": mc_result,
        "mc_dict": mc_dict,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("backtest_monte_carlo_partial.html", ctx)


# ── Optimization ──


@router.post("/backtest/optimize", response_class=HTMLResponse)
async def backtest_optimize(request: Request):
    """Run parameter optimization (HTMX)."""
    user = await get_current_user_optional(request)
    access = _get_access(user)
    if not access["has_optimizer"]:
        return HTMLResponse("<p class='text-red-400'>Upgrade to Ultra for Optimizer</p>", status_code=403)

    form = await request.form()
    days = min(int(form.get("days", 90)), access["max_days"])

    base_config = BacktestConfig(
        days=days,
        strategy_filter=form.get("strategy_filter") or None,
        stance_filter=form.get("stance_filter") or None,
    )

    db = request.app.state.db
    signals = await db.get_backtest_signals(
        days=days,
        strategy=base_config.strategy_filter,
        stance=base_config.stance_filter,
        limit=access["max_signals"],
    )

    settings = request.app.state.settings
    max_combos = settings.backtest_server.optimizer_max_combos

    opt_result = optimize(signals, base_config, max_combos=max_combos)

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "opt": opt_result,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("backtest_optimize_partial.html", ctx)


# ── Walk-Forward ──


@router.post("/backtest/walk-forward/{run_id}", response_class=HTMLResponse)
async def backtest_walk_forward(request: Request, run_id: str):
    """Run walk-forward analysis on a backtest run (HTMX)."""
    user = await get_current_user_optional(request)
    access = _get_access(user)
    if not access["has_walk_forward"]:
        return HTMLResponse("<p class='text-red-400'>Upgrade to Premium for Walk-Forward</p>", status_code=403)

    db = request.app.state.db
    run = await db.get_backtest_run(run_id)
    if not run:
        return HTMLResponse("<p class='text-red-400'>Run not found</p>", status_code=404)

    config_data = json.loads(run.get("config_json", "{}"))
    config = BacktestConfig.from_dict(config_data)

    signals = await db.get_backtest_signals(
        days=config.days,
        ticker=config.ticker_filter,
        stance=config.stance_filter,
        strategy=config.strategy_filter,
        event_type=config.event_type_filter,
        min_confidence=config.min_confidence,
        limit=access["max_signals"],
    )

    settings = request.app.state.settings
    n_folds = settings.backtest_server.walk_forward_folds

    wf_result = run_walk_forward(signals, config, n_folds=n_folds)

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "wf": wf_result,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("backtest_walk_forward_partial.html", ctx)


# ── Strategy CRUD ──


@router.post("/backtest/strategies/save", response_class=HTMLResponse)
async def save_strategy(
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    config_json: str = Form("{}"),
):
    """Save a named backtest strategy."""
    user = await get_current_user_optional(request)
    access = _get_access(user)
    if not access["has_saved_strategies"]:
        return HTMLResponse("<p class='text-red-400'>Upgrade to Ultra</p>", status_code=403)

    user_id = (user or {}).get("id", "")
    if not user_id or not name:
        return HTMLResponse("<p class='text-red-400'>Name required</p>")

    db = request.app.state.db
    await db.save_backtest_strategy(user_id, name, description, config_json)
    return HTMLResponse("<p class='text-green-400'>Strategy saved!</p>")


@router.delete("/backtest/strategies/{strategy_id}", response_class=HTMLResponse)
async def delete_strategy(request: Request, strategy_id: str):
    """Delete a saved strategy."""
    user = await get_current_user_optional(request)
    user_id = (user or {}).get("id", "")
    if not user_id:
        return HTMLResponse("", status_code=401)

    db = request.app.state.db
    await db.delete_backtest_strategy(strategy_id, user_id)
    return HTMLResponse("")


# ── Saved Result ──


@router.get("/backtest/result/{run_id}", response_class=HTMLResponse)
async def backtest_result_page(request: Request, run_id: str):
    """View a saved backtest result."""
    user = await get_current_user_optional(request)
    access = _get_access(user)
    if not access["has_access"]:
        return RedirectResponse(url="/pricing", status_code=302)

    db = request.app.state.db
    run = await db.get_backtest_run(run_id)
    if not run:
        return RedirectResponse(url="/backtest", status_code=302)

    result_data = json.loads(run.get("result_json", "{}"))
    config_data = json.loads(run.get("config_json", "{}"))
    mc_data = json.loads(run.get("monte_carlo_json", "{}"))
    risk_data = json.loads(run.get("risk_json", "{}"))

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "run": run,
        "result_dict": result_data,
        "config_dict": config_data,
        "mc_dict": mc_data,
        "risk_dict": risk_data,
        "run_id": run_id,
        "access": access,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("backtest_result.html", ctx)


# ── Export ──


@router.get("/api/v1/backtest/export/{run_id}")
async def backtest_export(request: Request, run_id: str, fmt: str = Query("json")):
    """Export backtest results as JSON or CSV."""
    user = await get_current_user_optional(request)
    access = _get_access(user)
    if not access["has_export"]:
        return JSONResponse({"error": "Upgrade to Ultra for exports"}, status_code=403)

    db = request.app.state.db
    run = await db.get_backtest_run(run_id)
    if not run:
        return JSONResponse({"error": "Not found"}, status_code=404)

    result_data = json.loads(run.get("result_json", "{}"))

    if fmt == "csv":
        from rot.backtest.report import generate_csv_trades
        csv_content = generate_csv_trades(result_data.get("trades", []))
        return JSONResponse(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=backtest_{run_id[:8]}.csv"},
        )

    return JSONResponse(result_data)


# ── Compare ──


@router.get("/backtest/compare", response_class=HTMLResponse)
async def backtest_compare(request: Request):
    """Strategy comparison page."""
    user = await get_current_user_optional(request)
    access = _get_access(user)
    if not access["has_comparison"]:
        return RedirectResponse(url="/pricing", status_code=302)

    # Get user's saved runs to compare
    db = request.app.state.db
    user_id = (user or {}).get("id", "")
    saved_runs = await db.get_user_backtests(user_id, limit=50) if user_id else []

    from rot.web.routes.dashboard import _base_context
    ctx = _base_context(request, user)
    ctx.update({
        "saved_runs": saved_runs,
        "access": access,
        "json_dumps": json.dumps,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("backtest_compare.html", ctx)
