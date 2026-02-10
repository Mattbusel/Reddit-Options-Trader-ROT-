from __future__ import annotations

import time
import logging
from typing import Optional

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

_DEFAULT_LIMITS = {
    "free": 100,
    "pro": 5000,
    "premium": 25000,
    "ultra": 50000,
}


async def check_rate_limit(request: Request, user: Optional[dict]) -> None:
    """Check API rate limit for the given user. Raises 429 if exceeded."""
    tier = (user or {}).get("tier", "free")
    user_id = (user or {}).get("id", "anon")

    settings = request.app.state.settings
    limit = getattr(settings.tier_limits, f"{tier}_api_limit_day", _DEFAULT_LIMITS.get(tier, 100))

    if limit == 0:  # unlimited
        return

    db = request.app.state.db
    since = time.time() - 86400  # 24h window
    count = await db.get_api_call_count(user_id, since)

    if count >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({limit} calls/day for {tier} tier). "
                   f"Upgrade at /pricing for higher limits.",
            headers={
                "Retry-After": "3600",
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    # Record this call
    ip = request.client.host if request.client else ""
    await db.record_api_call(user_id, request.url.path, ip)
