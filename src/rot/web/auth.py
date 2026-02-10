from __future__ import annotations

import hashlib
import secrets
import time
import logging
from typing import Optional

from fastapi import HTTPException, Request
from jose import JWTError, jwt
from passlib.context import CryptContext

log = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


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


async def get_current_user_optional(request: Request) -> Optional[dict]:
    """
    Try to extract user from: 1) JWT Bearer token, 2) X-API-Key header, 3) session cookie.
    Returns None if no auth provided (anonymous = free tier).
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
                return user
        except JWTError:
            pass

    # 2. Try API key
    api_key = request.headers.get("x-api-key", "")
    if api_key:
        key_hash = hash_api_key(api_key)
        user = await db.get_user_by_api_key_hash(key_hash)
        if user:
            return user

    # 3. Try session cookie (for dashboard)
    session_token = request.cookies.get("rot_session")
    if session_token:
        try:
            payload = jwt.decode(session_token, secret, algorithms=[algorithm])
            user = await db.get_user_by_id(payload["sub"])
            if user:
                return user
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
    """Factory for a dependency that checks user tier."""
    async def check_tier(request: Request) -> dict:
        user = await require_user(request)
        if user["tier"] not in allowed_tiers:
            raise HTTPException(
                status_code=403,
                detail=f"This feature requires {' or '.join(allowed_tiers)} tier",
            )
        return user
    return check_tier
