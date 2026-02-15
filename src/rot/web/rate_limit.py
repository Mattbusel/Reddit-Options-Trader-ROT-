"""API Rate Limiting — aggressive, paid-only access.

Free users get ZERO API calls. The API is a paid product.
The dashboard (HTML pages) is the free funnel. The API is the business.

Rate limits:
  - Free:       0 calls/day (blocked entirely)
  - Pro:        1,000 calls/day (50/min burst)
  - Premium:    5,000 calls/day (200/min burst)
  - Ultra:     25,000 calls/day (500/min burst)
  - Enterprise: 100,000 calls/day (2,000/min burst)

Auth Rate Limiting (brute-force protection):
  - /auth/login:     5 attempts per IP per 15 minutes
  - /auth/register:  3 attempts per IP per hour
  - /auth/api-key:   3 attempts per user per hour
"""
from __future__ import annotations

import time
import logging
from typing import Optional, Dict, List

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

# Auth brute-force protection: IP -> list of attempt timestamps
_auth_attempts: Dict[str, List[float]] = {}

_DEFAULT_LIMITS = {
    "free": 0,         # Zero. The API is not free.
    "pro": 1000,
    "premium": 5000,
    "ultra": 25000,
    "enterprise": 100000,
    "admin": 999999,   # Effectively unlimited
}

_BURST_LIMITS = {
    "free": 0,
    "pro": 50,         # 50 calls/minute
    "premium": 200,    # 200 calls/minute
    "ultra": 500,      # 500 calls/minute
    "enterprise": 2000,  # 2,000 calls/minute
    "admin": 99999,    # Effectively unlimited
}


async def require_api_auth(request: Request, user: Optional[dict]) -> dict:
    """Require authentication for all API endpoints. No anonymous access."""
    if not user:
        raise HTTPException(
            status_code=401,
            detail="API access requires authentication. Get an API key at /account. "
                   "Subscribe at /pricing for API access (Pro+).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def check_rate_limit(request: Request, user: Optional[dict]) -> None:
    """Check API rate limit for the given user.

    - Free users are blocked entirely (0 calls/day)
    - Paid users have daily + burst (per-minute) limits
    - Returns rate limit headers on every response
    """
    # Require auth for API access
    if not user:
        raise HTTPException(
            status_code=401,
            detail="API access requires authentication. Subscribe at /pricing for API access.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tier = user.get("tier", "free")
    user_id = user.get("id", "anon")

    # Free tier: no API access at all
    if tier == "free" or tier not in _DEFAULT_LIMITS:
        raise HTTPException(
            status_code=403,
            detail="API access requires a paid subscription (Pro+). "
                   "Upgrade at /pricing to unlock API access.",
        )

    settings = request.app.state.settings
    daily_limit = getattr(
        settings.tier_limits, f"{tier}_api_limit_day",
        _DEFAULT_LIMITS.get(tier, 0),
    )
    burst_limit = _BURST_LIMITS.get(tier, 0)

    if daily_limit == 0:
        raise HTTPException(
            status_code=403,
            detail="API access not available for your tier. Upgrade at /pricing.",
        )

    db = request.app.state.db
    now = time.time()

    # Check daily limit (24h window)
    since_24h = now - 86400
    daily_count = await db.get_api_call_count(user_id, since_24h)
    daily_remaining = max(0, daily_limit - daily_count)

    if daily_count >= daily_limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily rate limit exceeded ({daily_limit} calls/day for {tier} tier). "
                   f"Resets in ~{int((since_24h + 86400 - now) / 3600)}h. "
                   f"Upgrade at /pricing for higher limits.",
            headers={
                "Retry-After": str(int(since_24h + 86400 - now)),
                "X-RateLimit-Limit": str(daily_limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(since_24h + 86400)),
            },
        )

    # Check burst limit (1-minute window)
    if burst_limit > 0:
        since_1m = now - 60
        burst_count = await db.get_api_call_count(user_id, since_1m)
        if burst_count >= burst_limit:
            raise HTTPException(
                status_code=429,
                detail=f"Burst rate limit exceeded ({burst_limit} calls/minute for {tier} tier). "
                       f"Slow down your request rate.",
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(daily_limit),
                    "X-RateLimit-Remaining": str(daily_remaining),
                },
            )

    # Record this call
    ip = request.client.host if request.client else ""
    await db.record_api_call(user_id, request.url.path, ip)


def rate_limit_headers(user: Optional[dict]) -> dict:
    """Generate rate limit response headers for API responses."""
    if not user:
        return {}
    tier = user.get("tier", "free")
    daily_limit = _DEFAULT_LIMITS.get(tier, 0)
    burst_limit = _BURST_LIMITS.get(tier, 0)
    return {
        "X-RateLimit-Limit": str(daily_limit),
        "X-RateLimit-Burst": str(burst_limit),
        "X-Tier": tier,
    }


def check_auth_rate_limit(request: Request, endpoint: str) -> None:
    """Check brute-force protection for auth endpoints.

    Args:
        request: FastAPI request object
        endpoint: One of "login", "register", "api-key"

    Raises:
        HTTPException: 429 if rate limit exceeded

    Rate limits:
        - login:     5 attempts per IP per 15 minutes
        - register:  3 attempts per IP per hour
        - api-key:   3 attempts per hour (per IP, since user might not be authed yet)
    """
    ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Define limits
    limits = {
        "login": (5, 900),      # 5 attempts, 15 minutes
        "register": (3, 3600),  # 3 attempts, 1 hour
        "api-key": (3, 3600),   # 3 attempts, 1 hour
    }

    if endpoint not in limits:
        log.warning(f"Unknown auth endpoint for rate limiting: {endpoint}")
        return

    max_attempts, window_seconds = limits[endpoint]

    # Clean up old attempts (older than window)
    key = f"{ip}:{endpoint}"
    if key in _auth_attempts:
        _auth_attempts[key] = [ts for ts in _auth_attempts[key] if now - ts < window_seconds]

    # Check if limit exceeded
    attempts = _auth_attempts.get(key, [])

    log.info(f"Auth rate limit check: endpoint={endpoint}, ip={ip}, attempts={len(attempts)}/{max_attempts}")

    if len(attempts) >= max_attempts:
        # Calculate retry-after
        oldest_attempt = min(attempts)
        retry_after_seconds = int(window_seconds - (now - oldest_attempt))

        log.warning(f"Auth rate limit EXCEEDED: endpoint={endpoint}, ip={ip}, attempts={len(attempts)}")

        raise HTTPException(
            status_code=429,
            detail=f"Too many {endpoint} attempts. Please try again later.",
            headers={
                "Retry-After": str(max(1, retry_after_seconds))
            }
        )

    # Record this attempt
    if key not in _auth_attempts:
        _auth_attempts[key] = []
    _auth_attempts[key].append(now)

    log.info(f"Auth attempt recorded: endpoint={endpoint}, ip={ip}, total={len(_auth_attempts[key])}")

    # Cleanup: Remove entries older than 1 hour to prevent memory buildup
    cutoff = now - 3600
    keys_to_delete = []
    for k, timestamps in _auth_attempts.items():
        if not timestamps or max(timestamps) < cutoff:
            keys_to_delete.append(k)
    for k in keys_to_delete:
        del _auth_attempts[k]
