"""Tests for TradingView route endpoints.

Tests:
- GET /api/v1/tradingview/script endpoint
- Tier gating (Free blocked, Pro+ allowed)
- Query parameter handling
- Script generation integration
- Error handling
"""

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


# Mock database that will be injected via app.state
class MockDatabase:
    """Mock database for testing."""

    async def get_signals(self, limit=100, ticker=None):
        """Return mock signals."""
        import time
        # Use recent timestamps (within last hour)
        now = int(time.time())
        base_signals = [
            {
                "id": "sig_1",
                "created_at": now - 3600,  # 1 hour ago
                "ticker": "AAPL",
                "stance": "bullish",
                "confidence": 0.85,
                "event_type": "fda_approval",
                "strategy": "call_debit_spread",
                "time_horizon": "1_week",
                "trend_score": 0.92,
            },
            {
                "id": "sig_2",
                "created_at": now - 1800,  # 30 min ago
                "ticker": "TSLA",
                "stance": "bearish",
                "confidence": 0.72,
                "event_type": "earnings_miss",
                "strategy": "put_debit_spread",
                "time_horizon": "1_day",
                "trend_score": 0.68,
            },
            {
                "id": "sig_3",
                "created_at": now - 900,  # 15 min ago
                "ticker": "NVDA",
                "stance": "bullish",
                "confidence": 0.91,
                "event_type": "partnership",
                "strategy": "long_call",
                "time_horizon": "1_month",
                "trend_score": 0.95,
            },
        ]

        # Filter by ticker if provided
        if ticker:
            return [s for s in base_signals if s["ticker"] == ticker]

        return base_signals[:limit]


@pytest.fixture
def mock_app():
    """Create a mock FastAPI app with routes."""
    from fastapi import FastAPI
    from rot.web.routes.tradingview import router

    app = FastAPI()
    app.include_router(router)

    # Mock app state
    app.state.db = MockDatabase()
    app.state.settings = type('obj', (object,), {})()

    return app


@pytest.fixture
def client(mock_app):
    """Create test client."""
    return TestClient(mock_app)


class TestTradingViewScriptRouteAccess:
    """Test route access and tier gating."""

    def test_free_tier_blocked(self, client):
        """Free tier should be blocked from Pine Script generator."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate:

            mock_user.return_value = {"id": "user_1", "tier": "free"}
            mock_auth.return_value = None
            mock_rate.return_value = None

            response = client.get("/api/v1/tradingview/script")

            assert response.status_code == 403
            assert "Pro tier" in response.json()["detail"]

    def test_pro_tier_allowed(self, client):
        """Pro tier should have access to Pine Script generator."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script")

            assert response.status_code == 200
            assert "//@version=5" in response.text

    def test_premium_tier_allowed(self, client):
        """Premium tier should have access."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "premium"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script")

            assert response.status_code == 200

    def test_ultra_tier_allowed(self, client):
        """Ultra tier should have access."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "ultra"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script")

            assert response.status_code == 200

    def test_enterprise_tier_allowed(self, client):
        """Enterprise tier should have access."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "enterprise"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script")

            assert response.status_code == 200

    def test_admin_tier_allowed(self, client):
        """Admin tier should have access."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "admin"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script")

            assert response.status_code == 200


class TestTradingViewScriptRouteParams:
    """Test query parameter handling."""

    def test_default_params(self, client):
        """Should use default parameters."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script")

            assert response.status_code == 200
            assert "ROT Signals" in response.text

    def test_ticker_filter(self, client):
        """Should filter by ticker."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script?ticker=AAPL")

            assert response.status_code == 200
            assert "AAPL" in response.text

    def test_min_confidence_filter(self, client):
        """Should filter by min_confidence."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script?min_confidence=0.8")

            assert response.status_code == 200
            # Should only include signals >= 0.8 (AAPL 0.85, NVDA 0.91)
            assert "0.85" in response.text or "0.91" in response.text

    def test_days_param(self, client):
        """Should accept days parameter."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script?days=60")

            assert response.status_code == 200

    def test_script_type_signal_overlay(self, client):
        """Should generate signal overlay."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script?script_type=signal_overlay")

            assert response.status_code == 200
            assert "plotshape" in response.text

    def test_script_type_confidence_heatmap(self, client):
        """Should generate confidence heatmap."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script?script_type=confidence_heatmap")

            assert response.status_code == 200
            assert "bgcolor" in response.text

    def test_script_type_watchlist(self, client):
        """Should generate watchlist indicator."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script?script_type=watchlist_indicator")

            assert response.status_code == 200
            assert "table.new" in response.text

    def test_script_type_strategy(self, client):
        """Should generate strategy backtest."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script?script_type=strategy_backtest")

            assert response.status_code == 200
            assert "strategy.entry" in response.text

    def test_script_type_alerts(self, client):
        """Should generate alert conditions."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script?script_type=alert_conditions")

            assert response.status_code == 200
            assert "alertcondition" in response.text

    def test_invalid_script_type(self, client):
        """Should reject invalid script_type."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None

            response = client.get("/api/v1/tradingview/script?script_type=invalid")

            assert response.status_code == 422  # Validation error

    def test_show_labels_param(self, client):
        """Should respect show_labels parameter."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script?show_labels=false")

            assert response.status_code == 200
            assert "label.new" not in response.text

    def test_show_lines_param(self, client):
        """Should respect show_lines parameter."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script?show_lines=true")

            assert response.status_code == 200
            assert "line.new" in response.text


class TestTradingViewScriptRouteResponse:
    """Test response format and content."""

    def test_returns_plain_text(self, client):
        """Should return PlainTextResponse."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script")

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/plain; charset=utf-8"

    def test_valid_pine_script_syntax(self, client):
        """Generated script should have valid Pine Script syntax."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script")

            assert response.status_code == 200
            script = response.text

            # Basic syntax checks
            assert script.startswith("//@version=5")
            assert script.count("(") == script.count(")")  # Balanced parens
            assert script.count("[") == script.count("]")  # Balanced brackets

    def test_includes_signal_data(self, client):
        """Generated script should include signal data."""
        with patch("rot.web.routes.tradingview.get_current_user_optional") as mock_user, \
             patch("rot.web.routes.tradingview.require_api_auth") as mock_auth, \
             patch("rot.web.routes.tradingview.check_rate_limit") as mock_rate, \
             patch("rot.web.routes.tradingview.rate_limit_headers") as mock_headers:

            mock_user.return_value = {"id": "user_1", "tier": "pro"}
            mock_auth.return_value = None
            mock_rate.return_value = None
            mock_headers.return_value = {}

            response = client.get("/api/v1/tradingview/script")

            assert response.status_code == 200
            script = response.text

            # Should contain signal data (check for array declarations)
            assert "signal_times" in script or "array.from" in script
