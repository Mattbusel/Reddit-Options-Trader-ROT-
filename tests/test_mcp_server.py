"""Tests for the standalone ROT MCP server (rot_mcp_server.py).

Tests the MCP tool functions and resources in isolation by mocking
the HTTP calls to the backend API. Verifies tool signatures,
error handling, parameter passing, and resource output formatting.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path so rot_mcp_server can be imported
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import rot_mcp_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_get(return_value: dict):
    """Create a mock for rot_mcp_server._get that returns the given dict."""
    return AsyncMock(return_value=return_value)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_trending_tickers
# ═══════════════════════════════════════════════════════════════════════════


class TestGetTrendingTickers:
    @pytest.mark.asyncio
    async def test_default_params(self):
        mock_response = {"tickers": [{"ticker": "NVDA", "count": 5}], "period_hours": 24, "count": 1}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)):
            result = await rot_mcp_server.get_trending_tickers()
            assert result["count"] == 1
            assert result["tickers"][0]["ticker"] == "NVDA"

    @pytest.mark.asyncio
    async def test_custom_params(self):
        mock_response = {"tickers": [], "period_hours": 48, "count": 0}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)) as mock:
            await rot_mcp_server.get_trending_tickers(hours=48, limit=5)
            mock.assert_called_once_with("/api/mcp/trending", {"hours": 48, "limit": 5})

    @pytest.mark.asyncio
    async def test_error_response(self):
        mock_response = {"error": "Request to /api/mcp/trending timed out after 15.0s"}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)):
            result = await rot_mcp_server.get_trending_tickers()
            assert "error" in result


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_signals
# ═══════════════════════════════════════════════════════════════════════════


class TestGetSignals:
    @pytest.mark.asyncio
    async def test_no_filters(self):
        mock_response = {"signals": [], "count": 0, "filters": {"limit": 10}}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)) as mock:
            await rot_mcp_server.get_signals()
            mock.assert_called_once_with("/api/mcp/signals", {"limit": 10})

    @pytest.mark.asyncio
    async def test_ticker_filter(self):
        mock_response = {"signals": [{"ticker": "AAPL"}], "count": 1}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)) as mock:
            await rot_mcp_server.get_signals(ticker="AAPL")
            mock.assert_called_once_with("/api/mcp/signals", {"limit": 10, "ticker": "AAPL"})

    @pytest.mark.asyncio
    async def test_stance_filter(self):
        mock_response = {"signals": [], "count": 0}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)) as mock:
            await rot_mcp_server.get_signals(stance="bearish")
            mock.assert_called_once_with("/api/mcp/signals", {"limit": 10, "stance": "bearish"})

    @pytest.mark.asyncio
    async def test_all_filters(self):
        mock_response = {"signals": [], "count": 0}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)) as mock:
            await rot_mcp_server.get_signals(ticker="TSLA", stance="bullish", limit=5)
            mock.assert_called_once_with(
                "/api/mcp/signals",
                {"limit": 5, "ticker": "TSLA", "stance": "bullish"},
            )


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_sentiment
# ═══════════════════════════════════════════════════════════════════════════


class TestGetSentiment:
    @pytest.mark.asyncio
    async def test_returns_sentiment(self):
        mock_response = {
            "ticker": "NVDA", "signal_count": 10,
            "bullish": 7, "bearish": 2, "mixed": 1, "unknown": 0,
            "net_sentiment": 0.5, "avg_confidence": 0.72,
        }
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)):
            result = await rot_mcp_server.get_sentiment("NVDA")
            assert result["ticker"] == "NVDA"
            assert result["net_sentiment"] == 0.5

    @pytest.mark.asyncio
    async def test_passes_ticker(self):
        with patch.object(rot_mcp_server, "_get", _mock_get({})) as mock:
            await rot_mcp_server.get_sentiment("AAPL")
            mock.assert_called_once_with("/api/mcp/sentiment", {"ticker": "AAPL"})


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_market_overview
# ═══════════════════════════════════════════════════════════════════════════


class TestGetMarketOverview:
    @pytest.mark.asyncio
    async def test_returns_overview(self):
        mock_response = {
            "period_days": 30, "total_signals": 150,
            "tradeable_signals": 100, "avg_confidence": 0.6,
            "win_rate": 0.55,
        }
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)):
            result = await rot_mcp_server.get_market_overview()
            assert result["total_signals"] == 150
            assert result["win_rate"] == 0.55

    @pytest.mark.asyncio
    async def test_no_params(self):
        with patch.object(rot_mcp_server, "_get", _mock_get({})) as mock:
            await rot_mcp_server.get_market_overview()
            mock.assert_called_once_with("/api/mcp/overview")


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_unusual_activity
# ═══════════════════════════════════════════════════════════════════════════


class TestGetUnusualActivity:
    @pytest.mark.asyncio
    async def test_default_params(self):
        mock_response = {"events": [{"ticker": "TSLA"}], "count": 1, "period_hours": 24}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)) as mock:
            result = await rot_mcp_server.get_unusual_activity()
            mock.assert_called_once_with("/api/mcp/unusual", {"hours": 24, "limit": 20})
            assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_custom_params(self):
        with patch.object(rot_mcp_server, "_get", _mock_get({})) as mock:
            await rot_mcp_server.get_unusual_activity(hours=72, limit=5)
            mock.assert_called_once_with("/api/mcp/unusual", {"hours": 72, "limit": 5})


# ═══════════════════════════════════════════════════════════════════════════
# Tool: get_sports_feed
# ═══════════════════════════════════════════════════════════════════════════


class TestGetSportsFeed:
    @pytest.mark.asyncio
    async def test_no_league_filter(self):
        mock_response = {"items": [], "count": 0, "league_filter": None}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)) as mock:
            await rot_mcp_server.get_sports_feed()
            mock.assert_called_once_with("/api/mcp/sports", {"limit": 20})

    @pytest.mark.asyncio
    async def test_with_league(self):
        with patch.object(rot_mcp_server, "_get", _mock_get({})) as mock:
            await rot_mcp_server.get_sports_feed(league="NFL", limit=10)
            mock.assert_called_once_with("/api/mcp/sports", {"limit": 10, "league": "NFL"})

    @pytest.mark.asyncio
    async def test_returns_items(self):
        mock_response = {
            "items": [{"title": "Chiefs injury", "line_mover_score": 85}],
            "count": 1,
        }
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)):
            result = await rot_mcp_server.get_sports_feed(league="NFL")
            assert result["count"] == 1
            assert result["items"][0]["line_mover_score"] == 85


# ═══════════════════════════════════════════════════════════════════════════
# Tool: search_signals
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchSignals:
    @pytest.mark.asyncio
    async def test_search_passes_query(self):
        mock_response = {"query": "FDA", "results": [], "count": 0}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)) as mock:
            await rot_mcp_server.search_signals("FDA")
            mock.assert_called_once_with("/api/mcp/search", {"q": "FDA", "limit": 10})

    @pytest.mark.asyncio
    async def test_search_with_limit(self):
        with patch.object(rot_mcp_server, "_get", _mock_get({})) as mock:
            await rot_mcp_server.search_signals("earnings", limit=5)
            mock.assert_called_once_with("/api/mcp/search", {"q": "earnings", "limit": 5})

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        mock_response = {
            "query": "NVDA", "count": 1,
            "results": [{"ticker": "NVDA", "stance": "bullish"}],
        }
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)):
            result = await rot_mcp_server.search_signals("NVDA")
            assert result["count"] == 1
            assert result["results"][0]["ticker"] == "NVDA"


# ═══════════════════════════════════════════════════════════════════════════
# Resource: rot://status
# ═══════════════════════════════════════════════════════════════════════════


class TestStatusResource:
    @pytest.mark.asyncio
    async def test_healthy_status(self):
        mock_response = {"status": "healthy", "version": "0.1.0"}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)):
            result = await rot_mcp_server.server_status()
            assert "healthy" in result
            assert "0.1.0" in result

    @pytest.mark.asyncio
    async def test_unreachable_status(self):
        mock_response = {"error": "Connection error: timed out"}
        with patch.object(rot_mcp_server, "_get", _mock_get(mock_response)):
            result = await rot_mcp_server.server_status()
            assert "UNREACHABLE" in result


# ═══════════════════════════════════════════════════════════════════════════
# Resource: rot://pricing
# ═══════════════════════════════════════════════════════════════════════════


class TestPricingResource:
    @pytest.mark.asyncio
    async def test_pricing_content(self):
        result = await rot_mcp_server.pricing_info()
        assert "Free" in result
        assert "Pro" in result
        assert "Premium" in result
        assert "Ultra" in result
        assert "Enterprise" in result

    @pytest.mark.asyncio
    async def test_pricing_includes_url(self):
        result = await rot_mcp_server.pricing_info()
        assert "web-production-71423.up.railway.app" in result


# ═══════════════════════════════════════════════════════════════════════════
# HTTP Helper: _get
# ═══════════════════════════════════════════════════════════════════════════


class TestHttpHelper:
    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        import httpx
        with patch("rot_mcp_server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await rot_mcp_server._get("/api/mcp/trending")
            assert "error" in result
            assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_http_error_returns_error(self):
        import httpx
        with patch("rot_mcp_server.httpx.AsyncClient") as mock_client_cls:
            # Use MagicMock for response because raise_for_status() is sync
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server Error", request=MagicMock(), response=mock_resp,
            )
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await rot_mcp_server._get("/api/mcp/overview")
            assert "error" in result
            assert "500" in result["error"]

    @pytest.mark.asyncio
    async def test_connection_error_returns_error(self):
        import httpx
        with patch("rot_mcp_server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.RequestError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await rot_mcp_server._get("/api/mcp/signals")
            assert "error" in result
            assert "Connection error" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════
# MCP Server Configuration
# ═══════════════════════════════════════════════════════════════════════════


class TestMcpConfig:
    def test_mcp_server_has_name(self):
        assert rot_mcp_server.mcp.name == "ROT — Reddit Options Trader"

    def test_base_url_default(self):
        assert "web-production-71423" in rot_mcp_server.BASE_URL

    def test_timeout_reasonable(self):
        assert 5.0 <= rot_mcp_server.TIMEOUT <= 30.0
