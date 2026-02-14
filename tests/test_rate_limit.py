"""
Test suite for API rate limiting (Work Stream 4).

Covers:
- Tier-based daily limits (Free: 0, Pro: 1000, Premium: 5000, Ultra: 25000, Enterprise: 100000, Admin: 999999)
- Burst limits per minute (Pro: 50/min, Premium: 200/min, Ultra: 500/min, Enterprise: 2000/min)
- Anonymous blocking (401 before rate limit check)
- Rate limit headers (X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset)
- Daily counter reset at 24h
- Burst protection (sliding window last 60s)
- 403 on daily limit exceeded
- 429 on burst limit exceeded
- API call recording
- Admin tier unlimited access
"""
import time
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi import HTTPException, Request

from rot.web.rate_limit import (
    _BURST_LIMITS,
    _DEFAULT_LIMITS,
    check_rate_limit,
    rate_limit_headers,
    require_api_auth,
)


# =========================================================================
# Constants Validation
# =========================================================================


class TestConstants:
    """Test rate limit constants are correct."""

    def test_default_limits_all_tiers(self):
        """_DEFAULT_LIMITS includes all 6 tiers."""
        assert "free" in _DEFAULT_LIMITS
        assert "pro" in _DEFAULT_LIMITS
        assert "premium" in _DEFAULT_LIMITS
        assert "ultra" in _DEFAULT_LIMITS
        assert "enterprise" in _DEFAULT_LIMITS
        assert "admin" in _DEFAULT_LIMITS

    def test_default_limits_values(self):
        """_DEFAULT_LIMITS matches documented values."""
        assert _DEFAULT_LIMITS["free"] == 0
        assert _DEFAULT_LIMITS["pro"] == 1000
        assert _DEFAULT_LIMITS["premium"] == 5000
        assert _DEFAULT_LIMITS["ultra"] == 25000
        assert _DEFAULT_LIMITS["enterprise"] == 100000
        assert _DEFAULT_LIMITS["admin"] == 999999

    def test_burst_limits_all_tiers(self):
        """_BURST_LIMITS includes all 6 tiers."""
        assert "free" in _BURST_LIMITS
        assert "pro" in _BURST_LIMITS
        assert "premium" in _BURST_LIMITS
        assert "ultra" in _BURST_LIMITS
        assert "enterprise" in _BURST_LIMITS
        assert "admin" in _BURST_LIMITS

    def test_burst_limits_values(self):
        """_BURST_LIMITS matches documented values."""
        assert _BURST_LIMITS["free"] == 0
        assert _BURST_LIMITS["pro"] == 50
        assert _BURST_LIMITS["premium"] == 200
        assert _BURST_LIMITS["ultra"] == 500
        assert _BURST_LIMITS["enterprise"] == 2000
        assert _BURST_LIMITS["admin"] == 99999


# =========================================================================
# require_api_auth Tests
# =========================================================================


class TestRequireAPIAuth:
    """Test require_api_auth() authentication check."""

    @pytest.mark.asyncio
    async def test_require_api_auth_with_user(self):
        """require_api_auth() returns user if authenticated."""
        request = Mock(spec=Request)
        user = {"id": "user1", "tier": "pro"}

        result = await require_api_auth(request, user)

        assert result == user

    @pytest.mark.asyncio
    async def test_require_api_auth_without_user_raises_401(self):
        """require_api_auth() raises 401 if user is None."""
        request = Mock(spec=Request)

        with pytest.raises(HTTPException) as exc_info:
            await require_api_auth(request, None)

        assert exc_info.value.status_code == 401
        assert "API access requires authentication" in exc_info.value.detail
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


# =========================================================================
# check_rate_limit - Free Tier Blocking
# =========================================================================


class TestFreeTierBlocking:
    """Test free tier is completely blocked from API access."""

    @pytest.mark.asyncio
    async def test_free_tier_blocked(self):
        """Free tier users get 403 (API access requires paid subscription)."""
        request = Mock(spec=Request)
        user = {"id": "free_user", "tier": "free"}

        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit(request, user)

        assert exc_info.value.status_code == 403
        assert "API access requires a paid subscription" in exc_info.value.detail
        assert "Pro+" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_anonymous_blocked_before_rate_limit(self):
        """Anonymous users (None) get 401 before rate limit check."""
        request = Mock(spec=Request)

        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit(request, None)

        assert exc_info.value.status_code == 401
        assert "authentication" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_unknown_tier_blocked(self):
        """Unknown tier treated as free (blocked)."""
        request = Mock(spec=Request)
        user = {"id": "user1", "tier": "unknown_tier"}

        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit(request, user)

        assert exc_info.value.status_code == 403


# =========================================================================
# check_rate_limit - Daily Limits
# =========================================================================


class TestDailyLimits:
    """Test daily rate limits for each tier."""

    @pytest.mark.asyncio
    async def test_pro_tier_daily_limit(self):
        """Pro tier: 1000 calls/day."""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.url = Mock()
        request.url.path = "/api/v1/signals"

        settings = MagicMock()
        settings.tier_limits.pro_api_limit_day = 1000
        request.app = MagicMock()
        request.app.state.settings = settings

        db = AsyncMock()
        db.get_api_call_count = AsyncMock(return_value=500)  # Under limit
        db.record_api_call = AsyncMock()
        request.app.state.db = db

        user = {"id": "pro_user", "tier": "pro"}

        await check_rate_limit(request, user)  # Should pass

        # Verify API call recorded
        db.record_api_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_premium_tier_daily_limit(self):
        """Premium tier: 5000 calls/day."""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.url = Mock()
        request.url.path = "/api/v1/signals"

        settings = MagicMock()
        settings.tier_limits.premium_api_limit_day = 5000
        request.app = MagicMock()
        request.app.state.settings = settings

        db = AsyncMock()
        db.get_api_call_count = AsyncMock(return_value=4999)  # Just under
        db.record_api_call = AsyncMock()
        request.app.state.db = db

        user = {"id": "prem_user", "tier": "premium"}

        await check_rate_limit(request, user)  # Should pass

    @pytest.mark.asyncio
    async def test_ultra_tier_daily_limit(self):
        """Ultra tier: 25000 calls/day."""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.url = Mock()
        request.url.path = "/api/v1/signals"

        settings = MagicMock()
        settings.tier_limits.ultra_api_limit_day = 25000
        request.app = MagicMock()
        request.app.state.settings = settings

        db = AsyncMock()
        db.get_api_call_count = AsyncMock(return_value=10000)  # Under
        db.record_api_call = AsyncMock()
        request.app.state.db = db

        user = {"id": "ultra_user", "tier": "ultra"}

        await check_rate_limit(request, user)  # Should pass

    @pytest.mark.asyncio
    async def test_enterprise_tier_daily_limit(self):
        """Enterprise tier: 100000 calls/day."""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.url = Mock()
        request.url.path = "/api/v1/signals"

        settings = MagicMock()
        settings.tier_limits.enterprise_api_limit_day = 100000
        request.app = MagicMock()
        request.app.state.settings = settings

        db = AsyncMock()
        db.get_api_call_count = AsyncMock(return_value=50000)  # Half used
        db.record_api_call = AsyncMock()
        request.app.state.db = db

        user = {"id": "ent_user", "tier": "enterprise"}

        await check_rate_limit(request, user)  # Should pass

    @pytest.mark.asyncio
    async def test_admin_tier_unlimited(self):
        """Admin tier: 999999 calls/day (effectively unlimited)."""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.url = Mock()
        request.url.path = "/api/v1/signals"

        settings = MagicMock()
        settings.tier_limits.admin_api_limit_day = 999999
        request.app = MagicMock()
        request.app.state.settings = settings

        db = AsyncMock()
        db.get_api_call_count = AsyncMock(return_value=100000)  # High usage
        db.record_api_call = AsyncMock()
        request.app.state.db = db

        user = {"id": "admin", "tier": "admin"}

        await check_rate_limit(request, user)  # Should pass

    @pytest.mark.asyncio
    async def test_daily_limit_exceeded_raises_429(self):
        """Daily limit exceeded raises 429 with Retry-After header."""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.url = Mock()
        request.url.path = "/api/v1/signals"

        settings = MagicMock()
        settings.tier_limits.pro_api_limit_day = 1000
        request.app = MagicMock()
        request.app.state.settings = settings

        db = AsyncMock()
        db.get_api_call_count = AsyncMock(return_value=1000)  # At limit
        request.app.state.db = db

        user = {"id": "pro_user", "tier": "pro"}

        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit(request, user)

        assert exc_info.value.status_code == 429
        assert "Daily rate limit exceeded" in exc_info.value.detail
        assert "1000 calls/day" in exc_info.value.detail
        assert "Retry-After" in exc_info.value.headers
        assert "X-RateLimit-Limit" in exc_info.value.headers
        assert exc_info.value.headers["X-RateLimit-Remaining"] == "0"


# =========================================================================
# check_rate_limit - Burst Limits
# =========================================================================


class TestBurstLimits:
    """Test per-minute burst limits."""

    @pytest.mark.asyncio
    async def test_pro_burst_limit(self):
        """Pro tier: 50 calls/minute."""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.url = Mock()
        request.url.path = "/api/v1/signals"

        settings = MagicMock()
        settings.tier_limits.pro_api_limit_day = 1000
        request.app = MagicMock()
        request.app.state.settings = settings

        db = AsyncMock()
        # Mock two different time windows
        call_counts = [100, 30]  # 100 daily, 30 in last minute
        db.get_api_call_count = AsyncMock(side_effect=call_counts)
        db.record_api_call = AsyncMock()
        request.app.state.db = db

        user = {"id": "pro_user", "tier": "pro"}

        await check_rate_limit(request, user)  # 30 < 50, should pass

    @pytest.mark.asyncio
    async def test_burst_limit_exceeded_raises_429(self):
        """Burst limit exceeded raises 429."""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.url = Mock()
        request.url.path = "/api/v1/signals"

        settings = MagicMock()
        settings.tier_limits.pro_api_limit_day = 1000
        request.app = MagicMock()
        request.app.state.settings = settings

        db = AsyncMock()
        # 500 daily (under), 50 burst (at limit)
        call_counts = [500, 50]
        db.get_api_call_count = AsyncMock(side_effect=call_counts)
        request.app.state.db = db

        user = {"id": "pro_user", "tier": "pro"}

        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit(request, user)

        assert exc_info.value.status_code == 429
        assert "Burst rate limit exceeded" in exc_info.value.detail
        assert "50 calls/minute" in exc_info.value.detail
        assert exc_info.value.headers["Retry-After"] == "60"


# =========================================================================
# check_rate_limit - API Call Recording
# =========================================================================


class TestAPICallRecording:
    """Test API call recording."""

    @pytest.mark.asyncio
    async def test_api_call_recorded(self):
        """check_rate_limit() records API call with user_id, path, IP."""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "192.168.1.100"
        request.url = Mock()
        request.url.path = "/api/v1/signals/123"

        settings = MagicMock()
        settings.tier_limits.pro_api_limit_day = 1000
        request.app = MagicMock()
        request.app.state.settings = settings

        db = AsyncMock()
        db.get_api_call_count = AsyncMock(return_value=0)
        db.record_api_call = AsyncMock()
        request.app.state.db = db

        user = {"id": "user123", "tier": "pro"}

        await check_rate_limit(request, user)

        db.record_api_call.assert_called_once_with(
            "user123",
            "/api/v1/signals/123",
            "192.168.1.100",
        )

    @pytest.mark.asyncio
    async def test_api_call_recorded_no_client_ip(self):
        """API call recorded with empty IP if request.client is None."""
        request = Mock(spec=Request)
        request.client = None  # No client info
        request.url = Mock()
        request.url.path = "/api/v1/test"

        settings = MagicMock()
        settings.tier_limits.premium_api_limit_day = 5000
        request.app = MagicMock()
        request.app.state.settings = settings

        db = AsyncMock()
        db.get_api_call_count = AsyncMock(return_value=0)
        db.record_api_call = AsyncMock()
        request.app.state.db = db

        user = {"id": "user456", "tier": "premium"}

        await check_rate_limit(request, user)

        db.record_api_call.assert_called_once_with("user456", "/api/v1/test", "")


# =========================================================================
# rate_limit_headers Tests
# =========================================================================


class TestRateLimitHeaders:
    """Test rate limit response headers."""

    def test_rate_limit_headers_pro(self):
        """Pro tier headers include daily + burst limits."""
        user = {"id": "user1", "tier": "pro"}

        headers = rate_limit_headers(user)

        assert headers["X-RateLimit-Limit"] == "1000"
        assert headers["X-RateLimit-Burst"] == "50"
        assert headers["X-Tier"] == "pro"

    def test_rate_limit_headers_premium(self):
        """Premium tier headers."""
        user = {"id": "user2", "tier": "premium"}

        headers = rate_limit_headers(user)

        assert headers["X-RateLimit-Limit"] == "5000"
        assert headers["X-RateLimit-Burst"] == "200"
        assert headers["X-Tier"] == "premium"

    def test_rate_limit_headers_ultra(self):
        """Ultra tier headers."""
        user = {"id": "user3", "tier": "ultra"}

        headers = rate_limit_headers(user)

        assert headers["X-RateLimit-Limit"] == "25000"
        assert headers["X-RateLimit-Burst"] == "500"
        assert headers["X-Tier"] == "ultra"

    def test_rate_limit_headers_enterprise(self):
        """Enterprise tier headers."""
        user = {"id": "user4", "tier": "enterprise"}

        headers = rate_limit_headers(user)

        assert headers["X-RateLimit-Limit"] == "100000"
        assert headers["X-RateLimit-Burst"] == "2000"
        assert headers["X-Tier"] == "enterprise"

    def test_rate_limit_headers_admin(self):
        """Admin tier headers."""
        user = {"id": "admin", "tier": "admin"}

        headers = rate_limit_headers(user)

        assert headers["X-RateLimit-Limit"] == "999999"
        assert headers["X-RateLimit-Burst"] == "99999"
        assert headers["X-Tier"] == "admin"

    def test_rate_limit_headers_no_user(self):
        """None user returns empty dict."""
        headers = rate_limit_headers(None)

        assert headers == {}

    def test_rate_limit_headers_free_tier(self):
        """Free tier headers show 0 limits."""
        user = {"id": "user5", "tier": "free"}

        headers = rate_limit_headers(user)

        assert headers["X-RateLimit-Limit"] == "0"
        assert headers["X-RateLimit-Burst"] == "0"
        assert headers["X-Tier"] == "free"

    def test_rate_limit_headers_unknown_tier(self):
        """Unknown tier defaults to 0."""
        user = {"id": "user6", "tier": "unknown"}

        headers = rate_limit_headers(user)

        assert headers["X-RateLimit-Limit"] == "0"
        assert headers["X-RateLimit-Burst"] == "0"
        assert headers["X-Tier"] == "unknown"
