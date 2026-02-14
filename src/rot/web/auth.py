from __future__ import annotations

import hashlib
import secrets
import time
import logging
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request
from jose import JWTError, jwt

log = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, tier: str, settings) -> str:
    """Create JWT with user claims. `settings` is the app Settings object."""
    secret = settings.auth.jwt_secret or settings.web.secret_key
    expire = time.time() + (settings.auth.jwt_expire_minutes * 60)
    payload = {
        "sub": user_id,
        "email": email,
        "tier": tier,
        "exp": expire,
    }
    return jwt.encode(payload, secret, algorithm=settings.auth.jwt_algorithm)


def generate_api_key() -> str:
    """Generate a rot_... prefixed API key."""
    return "rot_" + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    """SHA-256 hash of the API key for storage."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def _maybe_elevate_admin(user: dict, settings) -> dict:
    """If user email is in admin_emails list, elevate tier to 'admin'."""
    admin_emails = settings.auth.admin_emails
    if admin_emails and user.get("email", "").lower() in [e.lower() for e in admin_emails]:
        user = dict(user)  # copy to avoid mutating cached row
        user["tier"] = "admin"
    return user


async def get_current_user_optional(request: Request) -> Optional[dict]:
    """
    Try to extract user from: 1) JWT Bearer token, 2) X-API-Key header, 3) session cookie.
    Returns None if no auth provided (anonymous = free tier).
    Admin emails (ROT_AUTH_ADMIN_EMAILS) are auto-elevated to 'admin' tier.
    """
    settings = request.app.state.settings
    db = request.app.state.db
    secret = settings.auth.jwt_secret or settings.web.secret_key
    algorithm = settings.auth.jwt_algorithm

    # 1. Try Bearer token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            payload = jwt.decode(token, secret, algorithms=[algorithm])
            user = await db.get_user_by_id(payload["sub"])
            if user:
                return _maybe_elevate_admin(user, settings)
        except JWTError:
            pass

    # 2. Try API key
    api_key = request.headers.get("x-api-key", "")
    if api_key:
        key_hash = hash_api_key(api_key)
        user = await db.get_user_by_api_key_hash(key_hash)
        if user:
            return _maybe_elevate_admin(user, settings)

    # 3. Try session cookie (for dashboard)
    session_token = request.cookies.get("rot_session")
    if session_token:
        try:
            payload = jwt.decode(session_token, secret, algorithms=[algorithm])
            user = await db.get_user_by_id(payload["sub"])
            if user:
                return _maybe_elevate_admin(user, settings)
        except JWTError:
            pass

    return None


async def require_user(request: Request) -> dict:
    """Dependency that REQUIRES authentication. Raises 401 if not authenticated."""
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_tier(*allowed_tiers: str):
    """Factory for a dependency that checks user tier. Admin always passes."""
    async def check_tier(request: Request) -> dict:
        user = await require_user(request)
        if user["tier"] == "admin":
            return user  # admin bypasses all tier checks
        if user["tier"] not in allowed_tiers:
            raise HTTPException(
                status_code=403,
                detail=f"This feature requires {' or '.join(allowed_tiers)} tier",
            )
        return user
    return check_tier
