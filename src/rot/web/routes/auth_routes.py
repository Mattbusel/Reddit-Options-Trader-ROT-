from __future__ import annotations

import re
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from rot.web.auth import (
    create_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    require_user,
    verify_password,
)
from rot.web.rate_limit import check_auth_rate_limit
from rot.core.security_logger import log_auth_attempt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth")

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LLMSettingsRequest(BaseModel):
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"


@router.post("/register")
async def register(body: RegisterRequest, request: Request):
    # Brute-force protection: 3 attempts per IP per hour
    await check_auth_rate_limit(request, "register")

    if not _EMAIL_RE.match(body.email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    db = request.app.state.db
    existing = await db.get_user_by_email(body.email.lower())
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    pw_hash = hash_password(body.password)
    user = await db.create_user(body.email.lower(), pw_hash)

    settings = request.app.state.settings
    token = create_access_token(user["id"], user["email"], user["tier"], settings)

    # Log successful registration
    ip = request.client.host if request.client else "unknown"
    log_auth_attempt(
        event="register",
        email=user["email"],
        ip=ip,
        success=True,
        metadata={"tier": user["tier"], "user_id": user["id"]}
    )

    response = JSONResponse(content={
        "user": {"id": user["id"], "email": user["email"], "tier": user["tier"]},
        "token": token,
    })
    response.set_cookie(
        key="rot_session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=settings.auth.jwt_expire_minutes * 60,
    )
    return response


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    from rot.core.logging import sanitize_for_log
    safe_email = sanitize_for_log(body.email)
    safe_ip = sanitize_for_log(request.client.host if request.client else 'unknown')
    log.warning(f"[LOGIN_DEBUG] Login attempt for email={safe_email}, ip={safe_ip}")

    # Brute-force protection: 5 attempts per IP per 15 minutes
    log.warning("[LOGIN_DEBUG] About to call check_auth_rate_limit")
    await check_auth_rate_limit(request, "login")
    log.warning("[LOGIN_DEBUG] check_auth_rate_limit completed successfully")

    db = request.app.state.db
    user = await db.get_user_by_email(body.email.lower())
    ip = request.client.host if request.client else "unknown"

    if not user or not user.get("password_hash"):
        # Log failed login - user not found
        log_auth_attempt(
            event="login",
            email=body.email.lower(),
            ip=ip,
            success=False,
            reason="user_not_found"
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(body.password, user["password_hash"]):
        # Log failed login - invalid password
        log_auth_attempt(
            event="login",
            email=body.email.lower(),
            ip=ip,
            success=False,
            reason="invalid_password",
            metadata={"user_id": user["id"]}
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    settings = request.app.state.settings
    token = create_access_token(user["id"], user["email"], user["tier"], settings)

    # Log successful login
    log_auth_attempt(
        event="login",
        email=user["email"],
        ip=ip,
        success=True,
        metadata={"tier": user["tier"], "user_id": user["id"]}
    )

    # Track login for gamification (async, fire-and-forget)
    try:
        from rot.gamification import BadgeTracker

        tracker = BadgeTracker(db)
        await tracker.record_login(user["id"])
    except Exception as e:
        log.warning("Badge tracking failed for login: %s", e)

    response = JSONResponse(content={
        "user": {"id": user["id"], "email": user["email"], "tier": user["tier"]},
        "token": token,
    })
    response.set_cookie(
        key="rot_session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=settings.auth.jwt_expire_minutes * 60,
    )
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse(content={"ok": True})
    response.delete_cookie("rot_session")
    return response


@router.get("/me")
async def me(request: Request):
    user = await require_user(request)
    db = request.app.state.db
    sub = await db.get_subscription(user["id"])

    return {
        "id": user["id"],
        "email": user["email"],
        "tier": user["tier"],
        "has_api_key": bool(user.get("api_key_hash")),
        "settings": {
            "llm_provider": user.get("settings", {}).get("llm_provider", ""),
            "llm_model": user.get("settings", {}).get("llm_model", ""),
            "has_llm_key": bool(user.get("settings", {}).get("llm_api_key")),
        },
        "subscription": {
            "status": sub.get("status") if sub else None,
            "current_period_end": sub.get("current_period_end") if sub else None,
        } if sub else None,
    }


@router.post("/api-key")
async def create_api_key(request: Request):
    # Brute-force protection: 3 attempts per IP per hour
    await check_auth_rate_limit(request, "api-key")

    user = await require_user(request)
    db = request.app.state.db

    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    await db.set_user_api_key(user["id"], key_hash)

    return {
        "api_key": raw_key,
        "message": "Save this key -- it will not be shown again.",
    }


@router.put("/llm-settings")
async def update_llm_settings(body: LLMSettingsRequest, request: Request):
    """Update BYOK LLM settings (paid tiers only)."""
    user = await require_user(request)
    if user["tier"] not in ("pro", "premium", "ultra", "enterprise"):
        raise HTTPException(status_code=403, detail="BYOK LLM requires a paid tier")

    db = request.app.state.db
    current_settings = user.get("settings", {})
    if not isinstance(current_settings, dict):
        current_settings = {}

    current_settings["llm_provider"] = body.llm_provider
    current_settings["llm_api_key"] = body.llm_api_key
    current_settings["llm_model"] = body.llm_model
    await db.update_user_settings(user["id"], current_settings)

    return {"ok": True, "message": "LLM settings updated"}


class WatchlistRequest(BaseModel):
    ticker: str


_WATCHLIST_LIMITS = {"free": 3, "pro": 20, "premium": 50, "ultra": 999}


@router.post("/watchlist")
async def add_to_watchlist(body: WatchlistRequest, request: Request):
    """Add a ticker to the user's watchlist."""
    user = await require_user(request)
    db = request.app.state.db

    ticker = body.ticker.strip().upper()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")

    current_settings = user.get("settings", {})
    if not isinstance(current_settings, dict):
        current_settings = {}

    watchlist = current_settings.get("watchlist", [])
    limit = _WATCHLIST_LIMITS.get(user["tier"], 3)

    if ticker in watchlist:
        return {"ok": True, "watchlist": watchlist, "message": "Already watching"}

    if len(watchlist) >= limit:
        raise HTTPException(
            status_code=403,
            detail=f"Watchlist limit reached ({limit} tickers on {user['tier']} tier). Upgrade for more.",
        )

    watchlist.append(ticker)
    current_settings["watchlist"] = watchlist
    await db.update_user_settings(user["id"], current_settings)
    return {"ok": True, "watchlist": watchlist}


@router.delete("/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str, request: Request):
    """Remove a ticker from the user's watchlist."""
    user = await require_user(request)
    db = request.app.state.db

    ticker = ticker.strip().upper()
    current_settings = user.get("settings", {})
    if not isinstance(current_settings, dict):
        current_settings = {}

    watchlist = current_settings.get("watchlist", [])
    watchlist = [t for t in watchlist if t != ticker]
    current_settings["watchlist"] = watchlist
    await db.update_user_settings(user["id"], current_settings)
    return {"ok": True, "watchlist": watchlist}


@router.get("/watchlist")
async def get_watchlist(request: Request):
    """Get the user's watchlist."""
    user = await require_user(request)
    current_settings = user.get("settings", {})
    if not isinstance(current_settings, dict):
        current_settings = {}
    watchlist = current_settings.get("watchlist", [])
    limit = _WATCHLIST_LIMITS.get(user["tier"], 3)
    return {"watchlist": watchlist, "limit": limit, "tier": user["tier"]}


# ── Saved Filter Presets (ultra only) ──

class FilterPresetRequest(BaseModel):
    name: str
    ticker: str = ""
    stance: str = ""
    event_type: str = ""
    min_confidence: str = ""
    date_range: str = ""


@router.post("/filter-presets")
async def save_filter_preset(body: FilterPresetRequest, request: Request):
    """Save a filter preset (ultra only)."""
    user = await require_user(request)
    if user["tier"] != "ultra":
        raise HTTPException(status_code=403, detail="Saved presets require Ultra tier")

    db = request.app.state.db
    current_settings = user.get("settings", {})
    if not isinstance(current_settings, dict):
        current_settings = {}

    presets = current_settings.get("filter_presets", [])
    if len(presets) >= 10:
        raise HTTPException(status_code=400, detail="Maximum 10 presets allowed")

    presets.append({
        "name": body.name[:50],
        "ticker": body.ticker.upper().strip(),
        "stance": body.stance.strip(),
        "event_type": body.event_type.strip(),
        "min_confidence": body.min_confidence.strip(),
        "date_range": body.date_range.strip(),
    })
    current_settings["filter_presets"] = presets
    await db.update_user_settings(user["id"], current_settings)
    return {"ok": True, "presets": presets}


@router.delete("/filter-presets/{index}")
async def delete_filter_preset(index: int, request: Request):
    """Delete a saved filter preset by index (ultra only)."""
    user = await require_user(request)
    if user["tier"] != "ultra":
        raise HTTPException(status_code=403, detail="Saved presets require Ultra tier")

    db = request.app.state.db
    current_settings = user.get("settings", {})
    if not isinstance(current_settings, dict):
        current_settings = {}

    presets = current_settings.get("filter_presets", [])
    if 0 <= index < len(presets):
        presets.pop(index)
        current_settings["filter_presets"] = presets
        await db.update_user_settings(user["id"], current_settings)

    return {"ok": True, "presets": presets}


@router.get("/filter-presets")
async def get_filter_presets(request: Request):
    """Get saved filter presets (ultra only)."""
    user = await require_user(request)
    if user["tier"] != "ultra":
        return {"presets": [], "tier": user["tier"]}

    current_settings = user.get("settings", {})
    if not isinstance(current_settings, dict):
        current_settings = {}
    return {"presets": current_settings.get("filter_presets", []), "tier": user["tier"]}


# ── Email Alert Settings ──

class EmailAlertSettingsRequest(BaseModel):
    enabled: int = 0
    digest_enabled: int = 1
    realtime_enabled: int = 0
    min_confidence: float = 0.6
    tickers: list = []
    stances: list = []
    event_types: list = []
    webhook_url: str = ""


@router.get("/email-alerts")
async def get_email_alerts(request: Request):
    """Get email alert settings."""
    user = await require_user(request)
    db = request.app.state.db
    settings = await db.get_email_alert_settings(user["id"])
    return {"settings": settings or {}, "tier": user["tier"]}


@router.put("/email-alerts")
async def update_email_alerts(body: EmailAlertSettingsRequest, request: Request):
    """Update email alert settings."""
    user = await require_user(request)
    tier = user["tier"]

    # Enforce tier limitations
    settings_dict = body.model_dump()
    if tier == "free":
        settings_dict["realtime_enabled"] = 0
        settings_dict["tickers"] = []
        settings_dict["stances"] = []
        settings_dict["event_types"] = []
        settings_dict["webhook_url"] = ""
    elif tier == "pro":
        settings_dict["tickers"] = []
        settings_dict["stances"] = []
        settings_dict["event_types"] = []
        settings_dict["webhook_url"] = ""
    elif tier == "premium":
        settings_dict["webhook_url"] = ""

    db = request.app.state.db
    await db.upsert_email_alert_settings(user["id"], settings_dict)
    return {"ok": True, "message": "Email alert settings updated"}
