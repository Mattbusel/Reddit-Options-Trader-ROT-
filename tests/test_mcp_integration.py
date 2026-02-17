"""Tests for the MCP Streamable HTTP integration module.

Verifies that the FastMCP server is properly configured, tools are
registered, resources are available, both Streamable HTTP and legacy SSE
apps can be created, the HTTP helper handles errors correctly, and
the event store lifecycle functions work properly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-mcp-int!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.web.mcp_integration import (
    _get,
    get_mcp_sse_app,
    get_mcp_streamable_http_app,
    connect_mcp_event_store,
    close_mcp_event_store,
    cleanup_mcp_events,
    mcp,
    _event_store,
    get_trending_tickers,
    get_signals,
    get_sentiment,
    get_market_overview,
    get_unusual_activity,
    get_sports_feed,
    search_signals,
    server_status,
    pricing_info,
)
from rot.web.mcp_event_store import InMemoryEventStore


# ═══════════════════════════════════════════════════════════════════════════
# MCP Server Configuration
# ═══════════════════════════════════════════════════════════════════════════


class TestMcpServerConfig:
    """MCP server configuration and identity."""

    def test_server_has_name(self):
        """MCP server has the correct name."""
        assert "ROT" in mcp.name

    def test_server_has_instructions(self):
        """MCP server has instructions for LLMs."""
        assert mcp.instructions is not None
        assert "trading" in mcp.instructions.lower()

    def test_dns_rebinding_protection_disabled(self):
        """DNS rebinding protection is disabled for public deployment."""
        settings = mcp.settings.transport_security
        assert settings is not None
        assert settings.enable_dns_rebinding_protection is False

    def test_sse_app_is_starlette(self):
        """get_mcp_sse_app returns a Starlette ASGI app."""
        app = get_mcp_sse_app()
        assert app is not None
        assert type(app).__name__ == "Starlette"

    def test_sse_app_has_routes(self):
        """SSE app has /sse and /messages routes."""
        app = get_mcp_sse_app()
        paths = [getattr(r, "path", None) for r in app.routes]
        assert "/sse" in paths

    def test_sse_app_callable(self):
        """SSE app is callable (ASGI interface)."""
        app = get_mcp_sse_app()
        assert callable(app)


# ═══════════════════════════════════════════════════════════════════════════
# HTTP Helper: _get
# ═══════════════════════════════════════════════════════════════════════════


def _mock_get(return_value: dict):
    """Create a mock for _get that returns the given dict."""
    return AsyncMock(return_value=return_value)


class TestHttpHelper:
    """HTTP client helper for internal API calls."""

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        import httpx
        with patch("rot.web.mcp_integration.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _get("/api/mcp/trending")
            assert "error" in result
            assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_http_error_returns_error(self):
        import httpx
        with patch("rot.web.mcp_integration.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server Error", request=MagicMock(), response=mock_resp,
            )
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _get("/api/mcp/overview")
            assert "error" in result
            assert "500" in result["error"]

    @pytest.mark.asyncio
    async def test_connection_error_returns_error(self):
        import httpx
        with patch("rot.web.mcp_integration.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.RequestError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _get("/api/mcp/signals")
            assert "error" in result
            assert "Connection error" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_json_response(self):
        import httpx
        with patch("rot.web.mcp_integration.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"tickers": [], "count": 0}
            mock_resp.raise_for_status.return_value = None
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _get("/api/mcp/trending", {"hours": 24})
            assert result == {"tickers": [], "count": 0}


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_trending_tickers
# ═══════════════════════════════════════════════════════════════════════════


class TestGetTrendingTickers:
    @pytest.mark.asyncio
    async def test_default_params(self):
        mock_response = {"tickers": [{"ticker": "NVDA", "count": 5}], "count": 1}
        with patch("rot.web.mcp_integration._get", _mock_get(mock_response)):
            result = await get_trending_tickers()
            assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_custom_params(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_trending_tickers(hours=48, limit=5)
            mock.assert_called_once_with("/api/mcp/trending", {"hours": 48, "limit": 5})


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_signals
# ═══════════════════════════════════════════════════════════════════════════


class TestGetSignals:
    @pytest.mark.asyncio
    async def test_no_filters(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_signals()
            mock.assert_called_once_with("/api/mcp/signals", {"limit": 10})

    @pytest.mark.asyncio
    async def test_ticker_filter(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_signals(ticker="AAPL")
            mock.assert_called_once_with("/api/mcp/signals", {"limit": 10, "ticker": "AAPL"})

    @pytest.mark.asyncio
    async def test_stance_filter(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_signals(stance="bearish")
            mock.assert_called_once_with("/api/mcp/signals", {"limit": 10, "stance": "bearish"})

    @pytest.mark.asyncio
    async def test_all_filters(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_signals(ticker="TSLA", stance="bullish", limit=5)
            mock.assert_called_once_with(
                "/api/mcp/signals",
                {"limit": 5, "ticker": "TSLA", "stance": "bullish"},
            )


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_sentiment
# ═══════════════════════════════════════════════════════════════════════════


class TestGetSentiment:
    @pytest.mark.asyncio
    async def test_passes_ticker(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_sentiment("AAPL")
            mock.assert_called_once_with("/api/mcp/sentiment", {"ticker": "AAPL"})

    @pytest.mark.asyncio
    async def test_returns_data(self):
        mock_response = {"ticker": "NVDA", "net_sentiment": 0.5}
        with patch("rot.web.mcp_integration._get", _mock_get(mock_response)):
            result = await get_sentiment("NVDA")
            assert result["net_sentiment"] == 0.5


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_market_overview
# ═══════════════════════════════════════════════════════════════════════════


class TestGetMarketOverview:
    @pytest.mark.asyncio
    async def test_no_params(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_market_overview()
            mock.assert_called_once_with("/api/mcp/overview")

    @pytest.mark.asyncio
    async def test_returns_overview(self):
        mock_response = {"total_signals": 150, "win_rate": 0.55}
        with patch("rot.web.mcp_integration._get", _mock_get(mock_response)):
            result = await get_market_overview()
            assert result["total_signals"] == 150


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_unusual_activity
# ═══════════════════════════════════════════════════════════════════════════


class TestGetUnusualActivity:
    @pytest.mark.asyncio
    async def test_default_params(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_unusual_activity()
            mock.assert_called_once_with("/api/mcp/unusual", {"hours": 24, "limit": 20})

    @pytest.mark.asyncio
    async def test_custom_params(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_unusual_activity(hours=72, limit=5)
            mock.assert_called_once_with("/api/mcp/unusual", {"hours": 72, "limit": 5})


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_sports_feed
# ═══════════════════════════════════════════════════════════════════════════


class TestGetSportsFeed:
    @pytest.mark.asyncio
    async def test_no_league(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_sports_feed()
            mock.assert_called_once_with("/api/mcp/sports", {"limit": 20})

    @pytest.mark.asyncio
    async def test_with_league(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await get_sports_feed(league="NFL", limit=10)
            mock.assert_called_once_with("/api/mcp/sports", {"limit": 10, "league": "NFL"})


# ═══════════════════════════════════════════════════════════════════════════
# Tool: search_signals
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchSignals:
    @pytest.mark.asyncio
    async def test_passes_query(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await search_signals("FDA")
            mock.assert_called_once_with("/api/mcp/search", {"q": "FDA", "limit": 10})

    @pytest.mark.asyncio
    async def test_with_limit(self):
        with patch("rot.web.mcp_integration._get", _mock_get({})) as mock:
            await search_signals("earnings", limit=5)
            mock.assert_called_once_with("/api/mcp/search", {"q": "earnings", "limit": 5})

    @pytest.mark.asyncio
    async def test_returns_results(self):
        mock_response = {"query": "NVDA", "count": 1, "results": [{"ticker": "NVDA"}]}
        with patch("rot.web.mcp_integration._get", _mock_get(mock_response)):
            result = await search_signals("NVDA")
            assert result["count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# Resource: rot://status
# ═══════════════════════════════════════════════════════════════════════════


class TestStatusResource:
    @pytest.mark.asyncio
    async def test_healthy_status(self):
        mock_response = {"status": "healthy", "version": "0.1.0"}
        with patch("rot.web.mcp_integration._get", _mock_get(mock_response)):
            result = await server_status()
            assert "healthy" in result
            assert "0.1.0" in result

    @pytest.mark.asyncio
    async def test_unreachable_status(self):
        mock_response = {"error": "Connection refused"}
        with patch("rot.web.mcp_integration._get", _mock_get(mock_response)):
            result = await server_status()
            assert "UNREACHABLE" in result


# ═══════════════════════════════════════════════════════════════════════════
# Resource: rot://pricing
# ═══════════════════════════════════════════════════════════════════════════


class TestPricingResource:
    @pytest.mark.asyncio
    async def test_pricing_content(self):
        result = await pricing_info()
        assert "Free" in result
        assert "Pro" in result
        assert "Premium" in result
        assert "Ultra" in result
        assert "Enterprise" in result

    @pytest.mark.asyncio
    async def test_pricing_includes_url(self):
        result = await pricing_info()
        assert "web-production-71423.up.railway.app" in result


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI App Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestFastAPIIntegration:
    """Verify MCP endpoint is mounted in the main app."""

    @pytest.mark.asyncio
    async def test_mcp_mount_in_app(self):
        """MCP Streamable HTTP app is mounted at /mcp in the main FastAPI app."""
        from rot.core.config import Settings
        from rot.web.app import create_app, connect_db, register_routes

        settings = Settings(
            storage={"root": os.path.join(os.path.dirname(__file__), "_tmp_mcp_int")},
            web={"secret_key": "test-secret-key-for-mcp-int!", "host": "127.0.0.1", "port": 8000},
            reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
            auth={"jwt_secret": "test-jwt-secret-mcp-int!!"},
        )
        app = create_app(settings)
        await connect_db(app)
        register_routes(app)

        # Check that /mcp is mounted
        mount_paths = []
        for route in app.routes:
            path = getattr(route, "path", None)
            if path:
                mount_paths.append(path)

        # The mount shows up as a route with path "/mcp"
        assert any("/mcp" in str(getattr(r, "path", "")) for r in app.routes), \
            f"Expected /mcp mount in routes, got: {mount_paths}"

        if hasattr(app.state, "db"):
            await app.state.db.close()
        cleanup = getattr(app.state, "_db_cleanup_task", None)
        if cleanup:
            cleanup.cancel()

    def test_mcp_sse_app_created_independently(self):
        """Legacy SSE app can still be created without the full FastAPI app."""
        app = get_mcp_sse_app()
        assert app is not None

    def test_multiple_sse_app_calls_succeed(self):
        """Calling get_mcp_sse_app() multiple times doesn't error."""
        app1 = get_mcp_sse_app()
        app2 = get_mcp_sse_app()
        assert app1 is not None
        assert app2 is not None


# ═══════════════════════════════════════════════════════════════════════════
# Streamable HTTP Transport
# ═══════════════════════════════════════════════════════════════════════════


class TestStreamableHttpApp:
    """Verify the Streamable HTTP transport app."""

    def test_streamable_http_app_is_starlette(self):
        """get_mcp_streamable_http_app returns a Starlette ASGI app."""
        app = get_mcp_streamable_http_app()
        assert app is not None
        assert type(app).__name__ == "Starlette"

    def test_streamable_http_app_callable(self):
        """Streamable HTTP app is callable (ASGI interface)."""
        app = get_mcp_streamable_http_app()
        assert callable(app)

    def test_streamable_http_app_has_routes(self):
        """Streamable HTTP app has the root path route."""
        app = get_mcp_streamable_http_app()
        paths = [getattr(r, "path", None) for r in app.routes]
        # streamable_http_path="/" means root route
        assert "/" in paths

    def test_multiple_streamable_http_app_calls_succeed(self):
        """Calling get_mcp_streamable_http_app() multiple times doesn't error."""
        app1 = get_mcp_streamable_http_app()
        app2 = get_mcp_streamable_http_app()
        assert app1 is not None
        assert app2 is not None

    def test_event_store_is_configured(self):
        """FastMCP instance has an event store configured."""
        assert mcp._event_store is not None

    def test_streamable_http_path_is_root(self):
        """streamable_http_path is '/' so mounting at /mcp gives /mcp/."""
        assert mcp.settings.streamable_http_path == "/"


# ═══════════════════════════════════════════════════════════════════════════
# Event Store Lifecycle
# ═══════════════════════════════════════════════════════════════════════════


class TestEventStoreLifecycle:
    """Verify connect/close/cleanup lifecycle functions."""

    @pytest.mark.asyncio
    async def test_connect_mcp_event_store_creates_sqlite(self, tmp_path):
        """connect_mcp_event_store upgrades to SQLite in a valid directory."""
        import rot.web.mcp_integration as mod

        # Save original state
        original_store = mod._event_store

        try:
            # Reset to InMemory for this test
            mod._event_store = InMemoryEventStore()
            mod.mcp._event_store = mod._event_store

            await connect_mcp_event_store(str(tmp_path))

            from rot.web.mcp_event_store import SqliteEventStore
            assert isinstance(mod._event_store, SqliteEventStore)

            # Clean up
            await mod._event_store.close()
        finally:
            # Restore original state
            mod._event_store = original_store
            mod.mcp._event_store = original_store

    @pytest.mark.asyncio
    async def test_close_mcp_event_store_noop_for_inmemory(self):
        """close_mcp_event_store is a no-op when using InMemoryEventStore."""
        import rot.web.mcp_integration as mod

        original_store = mod._event_store
        try:
            mod._event_store = InMemoryEventStore()
            # Should not raise
            await close_mcp_event_store()
        finally:
            mod._event_store = original_store

    @pytest.mark.asyncio
    async def test_cleanup_mcp_events_returns_zero_for_inmemory(self):
        """cleanup_mcp_events returns 0 when using InMemoryEventStore."""
        import rot.web.mcp_integration as mod

        original_store = mod._event_store
        try:
            mod._event_store = InMemoryEventStore()
            result = await cleanup_mcp_events()
            assert result == 0
        finally:
            mod._event_store = original_store

    @pytest.mark.asyncio
    async def test_connect_handles_bad_directory(self, tmp_path):
        """connect_mcp_event_store gracefully handles bad paths."""
        import rot.web.mcp_integration as mod

        original_store = mod._event_store
        try:
            mod._event_store = InMemoryEventStore()
            # A file path that can't be a directory
            bad_path = str(tmp_path / "nonexistent" / "deeply" / "nested")
            # Should not raise — falls back to keeping in-memory
            await connect_mcp_event_store(bad_path)
        finally:
            mod._event_store = original_store

    @pytest.mark.asyncio
    async def test_connect_skips_if_already_sqlite(self, tmp_path):
        """connect_mcp_event_store is idempotent — skips if already SQLite."""
        import rot.web.mcp_integration as mod
        from rot.web.mcp_event_store import SqliteEventStore

        original_store = mod._event_store
        try:
            # Set up a SqliteEventStore
            mod._event_store = InMemoryEventStore()
            await connect_mcp_event_store(str(tmp_path))
            first_store = mod._event_store
            assert isinstance(first_store, SqliteEventStore)

            # Call again — should be a no-op
            await connect_mcp_event_store(str(tmp_path))
            assert mod._event_store is first_store  # same object

            await mod._event_store.close()
        finally:
            mod._event_store = original_store
