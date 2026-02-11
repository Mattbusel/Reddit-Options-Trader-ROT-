from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError, jwt

from rot.web.auth import (
    create_access_token,
    get_current_user_optional,
    hash_password,
    require_user,
    verify_password,
)
from rot.web.tier_gate import (
    gate_chart_access,
    gate_correlation_access,
    gate_filter_access,
    gate_heatmap_access,
    gate_leaderboard_access,
    gate_market_context,
    gate_performance_access,
    gate_signal,
    gate_signal_list,
)

router = APIRouter()


def _format_time(ts: float | None) -> str:
    if not ts:
        return "N/A"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _stance_color(stance: str) -> str:
    return {
        "bullish": "text-green-400",
        "bearish": "text-red-400",
        "mixed": "text-yellow-400",
    }.get(stance, "text-gray-400")


def _stance_bg(stance: str) -> str:
    return {
        "bullish": "bg-green-900/30 border-green-700",
        "bearish": "bg-red-900/30 border-red-700",
        "mixed": "bg-yellow-900/30 border-yellow-700",
    }.get(stance, "bg-gray-900/30 border-gray-700")


def _confidence_bar(conf: float) -> str:
    pct = int(conf * 100)
    if conf >= 0.6:
        color = "bg-green-500"
    elif conf >= 0.4:
        color = "bg-yellow-500"
    else:
        color = "bg-red-500"
    return (
        f'<div class="w-full bg-gray-700 rounded h-2">'
        f'<div class="{color} h-2 rounded" style="width:{pct}%"></div></div>'
    )


def _tier_badge_class(tier: str) -> str:
    return {
        "pro": "bg-blue-900/50 text-blue-400 border border-blue-700",
        "premium": "bg-purple-900/50 text-purple-400 border border-purple-700",
        "ultra": "bg-amber-900/50 text-amber-400 border border-amber-700",
    }.get(tier, "bg-gray-700 text-gray-400 border border-gray-600")


def _base_context(request: Request, user: dict | None) -> dict:
    """Common template context for all pages."""
    return {
        "request": request,
        "user": user,
        "tier": (user or {}).get("tier", "free"),
        "tier_badge_class": _tier_badge_class((user or {}).get("tier", "free")),
        "format_time": _format_time,
        "stance_color": _stance_color,
        "stance_bg": _stance_bg,
        "confidence_bar": _confidence_bar,
        "stripe_enabled": bool(request.app.state.settings.stripe.secret_key),
    }


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    try:
        return await _dashboard_inner(request)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log.exception("Dashboard route failed: %s", e)
        return HTMLResponse(
            f"<h1>Something went wrong</h1><p>The dashboard encountered an error. "
            f"Please try <a href='/logout'>logging out</a> and back in, or "
            f"<a href='/dashboard'>refresh</a>.</p>"
            f"<pre>{type(e).__name__}: {e}\n\n{tb}</pre>",
            status_code=500,
        )


async def _dashboard_inner(request: Request):
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    settings = request.app.state.settings

    # Filter params from query string
    q_ticker = request.query_params.get("ticker", "").strip().upper() or None
    q_stance = request.query_params.get("stance", "").strip().lower() or None
    q_event = request.query_params.get("event_type", "").strip().lower() or None
    q_confidence = request.query_params.get("min_confidence", "").strip() or None
    q_date_range = request.query_params.get("date_range", "").strip() or None
    min_conf_float = None
    if q_confidence:
        try:
            min_conf_float = float(q_confidence) / 100.0  # UI sends %, DB stores 0-1
        except ValueError:
            min_conf_float = None

    # Date range filter (premium+ only)
    import time as _time
    filter_access = gate_filter_access(tier)
    date_from = None
    date_to = None
    if filter_access["has_date_range"] and q_date_range:
        now = _time.time()
        range_map = {"24h": 86400, "7d": 604800, "30d": 2592000}
        if q_date_range in range_map:
            date_from = now - range_map[q_date_range]

    db = request.app.state.db
    signals = await db.get_signals(
        limit=50,
        ticker=q_ticker,
        stance=q_stance if q_stance in ("bullish", "bearish", "mixed") else None,
        min_confidence=min_conf_float,
        event_type=q_event,
        date_from=date_from,
        date_to=date_to,
    )
    trending = await db.get_trending_tickers(hours=24, limit=10)
    summary = await db.get_performance_summary(days=30)

    # Chart data — gated by tier
    chart_access = gate_chart_access(tier)
    chart_data = None
    time_series = None
    if chart_access["has_quadrant"]:
        chart_data = await db.get_chart_data(
            hours=chart_access["chart_hours"],
            limit=chart_access["chart_limit"],
        )
        time_series = await db.get_time_series_data(hours=chart_access["chart_hours"])

    gated = gate_signal_list(
        signals, tier,
        delay_s=settings.tier_limits.free_signal_delay_s,
        page_limit=settings.tier_limits.free_page_limit,
    )

    # Accuracy tracker data (graceful degradation)
    perf_access = gate_performance_access(tier)
    accuracy = {"total_tracked": 0, "winners": 0, "losers": 0, "win_rate": 0}
    try:
        accuracy = await db.get_aggregate_accuracy(days=perf_access["accuracy_days"])
    except Exception as e:
        log.warning("Failed to load accuracy data: %s", e)

    # Leaderboard data (graceful degradation)
    lb_access = gate_leaderboard_access(tier)
    leaderboard_hours = 24
    leaderboard = []
    q_lb_hours = request.query_params.get("lb_hours", "")
    if q_lb_hours and lb_access["has_historical"]:
        try:
            leaderboard_hours = int(q_lb_hours)
        except ValueError:
            pass
    try:
        if lb_access["has_performance_column"]:
            leaderboard = await db.get_leaderboard_with_performance(
                hours=leaderboard_hours, limit=lb_access["leaderboard_limit"]
            )
        else:
            leaderboard = await db.get_leaderboard(
                hours=leaderboard_hours, limit=lb_access["leaderboard_limit"]
            )
    except Exception as e:
        log.warning("Failed to load leaderboard: %s", e)

    # Sector heatmap data (pro+, graceful degradation)
    heatmap_access = gate_heatmap_access(tier)
    heatmap_data = None
    try:
        if heatmap_access["has_heatmap"]:
            heatmap_data = await db.get_sector_heatmap_data(
                hours=chart_access["chart_hours"] or 24
            )
    except Exception as e:
        log.warning("Failed to load heatmap data: %s", e)

    # Correlation data (pro+, graceful degradation)
    corr_access = gate_correlation_access(tier)
    correlations = None
    try:
        if corr_access["has_correlation"]:
            correlations = await db.get_co_occurring_tickers(hours=24, min_co_occurrence=2)
    except Exception as e:
        log.warning("Failed to load correlation data: %s", e)

    # Signal count badge (graceful degradation)
    new_signal_count = 0
    if user:
        try:
            user_settings = user.get("settings", {})
            last_visit = user_settings.get("last_visit_at", 0) if isinstance(user_settings, dict) else 0
            if last_visit:
                new_signal_count = await db.get_signals_since(last_visit)
            # Update last visit timestamp
            await db.update_last_visit(user["id"])
        except Exception as e:
            log.warning("Failed to update signal count badge: %s", e)

    # Saved filter presets (ultra only)
    filter_presets = []
    if filter_access["has_saved_presets"] and user:
        user_settings = user.get("settings", {})
        if isinstance(user_settings, dict):
            filter_presets = user_settings.get("filter_presets", [])

    ctx = _base_context(request, user)
    ctx.update({
        "signals": gated,
        "trending": trending,
        "summary": summary,
        "total_signals": len(signals),
        "chart_data": chart_data,
        "time_series": time_series,
        "chart_access": chart_access,
        "filter_ticker": q_ticker or "",
        "filter_stance": q_stance or "",
        "filter_event": q_event or "",
        "filter_confidence": q_confidence or "",
        "filter_date_range": q_date_range or "",
        "has_filters": bool(q_ticker or q_stance or q_event or q_confidence or q_date_range),
        "watchlist": (user.get("settings") if user and isinstance(user.get("settings"), dict) else {}).get("watchlist", []),
        "watchlist_limit": {"free": 3, "pro": 20, "premium": 50, "ultra": 999}.get(tier, 3),
        "filter_access": filter_access,
        "perf_access": perf_access,
        "accuracy": accuracy,
        "leaderboard": leaderboard,
        "lb_access": lb_access,
        "lb_hours": leaderboard_hours,
        "heatmap_access": heatmap_access,
        "heatmap_data": heatmap_data,
        "corr_access": corr_access,
        "correlations": correlations,
        "market_context": gate_market_context(tier),
        "new_signal_count": new_signal_count,
        "filter_presets": filter_presets,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/dashboard/signal/{signal_id}", response_class=HTMLResponse)
async def signal_detail(request: Request, signal_id: str):
    try:
        return await _signal_detail_inner(request, signal_id)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log.exception("Signal detail route failed: %s", e)
        return HTMLResponse(
            f"<h1>Something went wrong</h1><p>Error loading signal. "
            f"<a href='/dashboard'>Back to dashboard</a>.</p>"
            f"<pre>{type(e).__name__}: {e}\n\n{tb}</pre>",
            status_code=500,
        )


async def _signal_detail_inner(request: Request, signal_id: str):
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    settings = request.app.state.settings

    db = request.app.state.db
    signal = await db.get_signal(signal_id)
    if not signal:
        return HTMLResponse("<h1>Signal not found</h1>", status_code=404)

    gated = gate_signal(signal, tier, delay_s=settings.tier_limits.free_signal_delay_s)

    # Get performance data for this signal (graceful degradation)
    perf_access = gate_performance_access(tier)
    performance = None
    try:
        if perf_access["has_per_signal_pnl"]:
            performance = await db.get_performance_for_signal(signal_id)
    except Exception as e:
        log.warning("Failed to load performance for signal %s: %s", signal_id, e)

    # Check if user has BYOK LLM configured
    user_settings = user.get("settings", {}) if user else {}
    if not isinstance(user_settings, dict):
        user_settings = {}
    has_byok = bool(
        tier in ("pro", "premium", "ultra")
        and user_settings.get("llm_api_key")
    )
    reasoning = gated.get("reasoning", {})
    is_stub = isinstance(reasoning, dict) and reasoning.get("raw", {}).get("stub")

    ctx = _base_context(request, user)
    ctx.update({
        "signal": gated,
        "json_dumps": json.dumps,
        "performance": performance,
        "perf_access": perf_access,
        "market_context": gate_market_context(tier),
        "has_byok": has_byok,
        "is_stub_reasoning": is_stub,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("signal_detail.html", ctx)


# ── Auth HTML routes ──

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = await get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    ctx = _base_context(request, None)
    ctx["error"] = request.query_params.get("error", "")
    ctx["success"] = request.query_params.get("success", "")
    templates = request.app.state.templates
    return templates.TemplateResponse("login.html", ctx)


@router.post("/login", response_class=HTMLResponse)
async def login_form(request: Request, email: str = Form(...), password: str = Form(...)):
    db = request.app.state.db
    user = await db.get_user_by_email(email.lower())

    if not user or not user.get("password_hash") or not verify_password(password, user["password_hash"]):
        ctx = _base_context(request, None)
        ctx["error"] = "Invalid email or password"
        templates = request.app.state.templates
        return templates.TemplateResponse("login.html", ctx)

    settings = request.app.state.settings
    token = create_access_token(user["id"], user["email"], user["tier"], settings)

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="rot_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.auth.jwt_expire_minutes * 60,
    )
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    user = await get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    ctx = _base_context(request, None)
    ctx["error"] = ""
    templates = request.app.state.templates
    return templates.TemplateResponse("register.html", ctx)


@router.post("/register", response_class=HTMLResponse)
async def register_form(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    templates = request.app.state.templates

    if password != confirm_password:
        ctx = _base_context(request, None)
        ctx["error"] = "Passwords do not match"
        return templates.TemplateResponse("register.html", ctx)

    if len(password) < 8:
        ctx = _base_context(request, None)
        ctx["error"] = "Password must be at least 8 characters"
        return templates.TemplateResponse("register.html", ctx)

    db = request.app.state.db
    existing = await db.get_user_by_email(email.lower())
    if existing:
        ctx = _base_context(request, None)
        ctx["error"] = "Email already registered"
        return templates.TemplateResponse("register.html", ctx)

    pw_hash = hash_password(password)
    user = await db.create_user(email.lower(), pw_hash)

    settings = request.app.state.settings
    token = create_access_token(user["id"], user["email"], user["tier"], settings)

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="rot_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.auth.jwt_expire_minutes * 60,
    )
    return response


@router.get("/logout")
async def logout_page():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("rot_session")
    return response


# ── Forgot / Reset Password ──

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    user = await get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    ctx = _base_context(request, None)
    ctx["error"] = ""
    ctx["success"] = ""
    templates = request.app.state.templates
    return templates.TemplateResponse("forgot_password.html", ctx)


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_form(request: Request, email: str = Form(...)):
    templates = request.app.state.templates
    db = request.app.state.db
    settings = request.app.state.settings
    email_alerter = getattr(request.app.state, "email_alerter", None)

    ctx = _base_context(request, None)

    # Look up user
    user = await db.get_user_by_email(email.lower().strip())
    if not user:
        ctx["error"] = "No account found with that email address."
        ctx["success"] = ""
        return templates.TemplateResponse("forgot_password.html", ctx)

    # Check email alerter is configured
    if not email_alerter or not email_alerter.is_configured:
        ctx["error"] = "Password reset emails are not configured. Please contact support."
        ctx["success"] = ""
        return templates.TemplateResponse("forgot_password.html", ctx)

    # Generate a signed reset token (JWT with 1-hour expiry)
    secret = settings.auth.jwt_secret or settings.web.secret_key
    reset_payload = {
        "sub": user["id"],
        "email": user["email"],
        "purpose": "password_reset",
        "exp": time.time() + 3600,  # 1 hour
    }
    reset_token = jwt.encode(reset_payload, secret, algorithm=settings.auth.jwt_algorithm)

    # Build reset URL
    host = request.headers.get("host", "localhost:8000")
    scheme = request.headers.get("x-forwarded-proto", "https" if "railway" in host else "http")
    reset_url = f"{scheme}://{host}/reset-password?token={reset_token}"

    # Send the email
    from rot.alerts.email_templates import render_password_reset
    html = render_password_reset(reset_url)
    try:
        email_alerter._send_email(user["email"], "ROT - Password Reset", html)
        log.info("Password reset email sent to %s", user["email"])
    except Exception as e:
        log.error("Failed to send reset email to %s: %s", user["email"], e)
        ctx["error"] = "Failed to send reset email. Please try again later."
        ctx["success"] = ""
        return templates.TemplateResponse("forgot_password.html", ctx)

    ctx["error"] = ""
    ctx["success"] = f"Password reset email sent to {user['email']}. Check your inbox."
    return templates.TemplateResponse("forgot_password.html", ctx)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    token = request.query_params.get("token", "")
    settings = request.app.state.settings
    templates = request.app.state.templates
    ctx = _base_context(request, None)
    ctx["error"] = ""
    ctx["token"] = token

    # Validate the token upfront
    if not token:
        ctx["error"] = "Invalid or missing reset link."
        return templates.TemplateResponse("reset_password.html", ctx)

    secret = settings.auth.jwt_secret or settings.web.secret_key
    try:
        payload = jwt.decode(token, secret, algorithms=[settings.auth.jwt_algorithm])
        if payload.get("purpose") != "password_reset":
            ctx["error"] = "Invalid reset link."
    except JWTError:
        ctx["error"] = "Reset link has expired or is invalid. Please request a new one."

    return templates.TemplateResponse("reset_password.html", ctx)


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password_form(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    templates = request.app.state.templates
    settings = request.app.state.settings
    db = request.app.state.db
    ctx = _base_context(request, None)
    ctx["token"] = token

    # Validate passwords match
    if password != confirm_password:
        ctx["error"] = "Passwords do not match."
        return templates.TemplateResponse("reset_password.html", ctx)

    if len(password) < 8:
        ctx["error"] = "Password must be at least 8 characters."
        return templates.TemplateResponse("reset_password.html", ctx)

    # Validate and decode the reset token
    secret = settings.auth.jwt_secret or settings.web.secret_key
    try:
        payload = jwt.decode(token, secret, algorithms=[settings.auth.jwt_algorithm])
        if payload.get("purpose") != "password_reset":
            ctx["error"] = "Invalid reset link."
            return templates.TemplateResponse("reset_password.html", ctx)
    except JWTError:
        ctx["error"] = "Reset link has expired or is invalid. Please request a new one."
        return templates.TemplateResponse("reset_password.html", ctx)

    # Verify user still exists
    user = await db.get_user_by_id(payload["sub"])
    if not user:
        ctx["error"] = "Account not found."
        return templates.TemplateResponse("reset_password.html", ctx)

    # Update the password
    pw_hash = hash_password(password)
    await db.update_user_password(user["id"], pw_hash)
    log.info("Password reset completed for user %s (%s)", user["id"], user["email"])

    # Redirect to login with success message
    return RedirectResponse(url="/login?success=Password+reset+successful.+Please+sign+in.", status_code=302)


@router.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)
    templates = request.app.state.templates
    return templates.TemplateResponse("pricing.html", ctx)


@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    db = request.app.state.db
    sub = await db.get_subscription(user["id"])

    from rot.web.tier_gate import gate_email_access
    tier = user.get("tier", "free")

    ctx = _base_context(request, user)
    ctx["subscription"] = sub
    ctx["has_api_key"] = bool(user.get("api_key_hash"))
    ctx["llm_settings"] = {
        "provider": user.get("settings", {}).get("llm_provider", ""),
        "model": user.get("settings", {}).get("llm_model", ""),
        "has_key": bool(user.get("settings", {}).get("llm_api_key")),
    }
    ctx["email_access"] = gate_email_access(tier)

    templates = request.app.state.templates
    return templates.TemplateResponse("account.html", ctx)
