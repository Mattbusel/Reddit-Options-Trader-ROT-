"""API Rate Limiting — aggressive, paid-only access.

Free users get ZERO API calls. The API is a paid product.
The dashboard (HTML pages) is the free funnel. The API is the business.

Rate limits:
  - Free:       0 calls/day (blocked entirely)
  - Pro:        1,000 calls/day (50/min burst)
  - Premium:    5,000 calls/day (200/min burst)
  - Ultra:     25,000 calls/day (500/min burst)
  - Enterprise: 100,000 calls/day (2,000/min burst)
"""
from __future__ import annotations

import time
import logging
from typing import Optional

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

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
