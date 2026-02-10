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

    response = JSONResponse(content={
        "user": {"id": user["id"], "email": user["email"], "tier": user["tier"]},
        "token": token,
    })
    response.set_cookie(
        key="rot_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.auth.jwt_expire_minutes * 60,
    )
    return response


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    db = request.app.state.db
    user = await db.get_user_by_email(body.email.lower())
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    settings = request.app.state.settings
    token = create_access_token(user["id"], user["email"], user["tier"], settings)

    response = JSONResponse(content={
        "user": {"id": user["id"], "email": user["email"], "tier": user["tier"]},
        "token": token,
    })
    response.set_cookie(
        key="rot_session",
        value=token,
        httponly=True,
        samesite="lax",
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
    if user["tier"] not in ("pro", "premium", "ultra"):
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
