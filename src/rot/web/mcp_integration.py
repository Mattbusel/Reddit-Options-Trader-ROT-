"""MCP Server integration — mounts FastMCP SSE endpoint into the FastAPI app.

This module creates a FastMCP server with 7 tools and 2 resources,
then exposes ``get_mcp_sse_app()`` which returns a Starlette ASGI app
that should be mounted at ``/mcp`` in the main FastAPI application.

The MCP tools proxy to the same ``/api/mcp/*`` REST endpoints on
localhost, keeping the implementation DRY — the backend API routes
contain all the actual logic, and this module just wraps them for
MCP protocol consumption.

Usage in app.py::

    from rot.web.mcp_integration import get_mcp_sse_app
    app.mount("/mcp", get_mcp_sse_app())
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

# When running inside the same process as FastAPI, we call localhost
# to reach our own /api/mcp/* endpoints.  The PORT env var is set
# by Railway; fallback to 8000 for local development.
_PORT = os.environ.get("PORT", "8000")
_INTERNAL_BASE = f"http://127.0.0.1:{_PORT}"
_TIMEOUT = 10.0

# ── MCP Server ───────────────────────────────────────────────────────

mcp = FastMCP(
    "ROT — Reddit Options Trader",
    instructions=(
        "Real-time trading intelligence from Reddit, RSS, and social media. "
        "AI-powered options signals, sentiment analysis, unusual activity "
        "detection, and sports betting intelligence. "
        "Use the available tools to query live data."
    ),
    # Disable DNS rebinding protection — this is a public-facing MCP server
    # deployed on Railway, not a localhost-only dev server.  The default
    # auto-enables protection for localhost hosts, which causes 421 responses
    # when the Host header is the Railway public hostname.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


# ── HTTP Client Helper ───────────────────────────────────────────────


async def _get(path: str, params: dict | None = None) -> dict:
    """Make a GET request to the local ROT backend API."""
    url = f"{_INTERNAL_BASE}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            return {"error": f"Request to {path} timed out after {_TIMEOUT}s"}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code} from {path}"}
        except httpx.RequestError as e:
            return {"error": f"Connection error: {e}"}


# ── Tools (7) ────────────────────────────────────────────────────────


@mcp.tool()
async def get_trending_tickers(hours: int = 24, limit: int = 20) -> dict:
    """Get top trending stock tickers from the last N hours.

    Returns tickers ranked by signal volume with signal counts and
    average confidence scores. Use this to see what the market is
    buzzing about right now.

    Args:
        hours: Lookback window in hours (1-168, default 24)
        limit: Max tickers to return (1-100, default 20)
    """
    return await _get("/api/mcp/trending", {"hours": hours, "limit": limit})


@mcp.tool()
async def get_signals(
    ticker: Optional[str] = None,
    stance: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Get latest trading signals with AI-generated analysis.

    Each signal includes the ticker, bullish/bearish stance, confidence
    percentage, event type, options strategy recommendation, source
    subreddit, and timestamp.

    Args:
        ticker: Filter by stock ticker symbol (e.g. "AAPL", "TSLA")
        stance: Filter by sentiment — "bullish", "bearish", "mixed", or "unknown"
        limit: Max signals to return (1-50, default 10)
    """
    params: dict = {"limit": limit}
    if ticker:
        params["ticker"] = ticker
    if stance:
        params["stance"] = stance
    return await _get("/api/mcp/signals", params)


@mcp.tool()
async def get_sentiment(ticker: str) -> dict:
    """Get sentiment breakdown for a specific stock ticker.

    Returns the bull/bear/mixed signal ratio, net sentiment score
    (-1.0 to +1.0), total signal count, and average confidence.
    Useful for gauging overall market mood on a stock.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL", "NVDA")
    """
    return await _get("/api/mcp/sentiment", {"ticker": ticker})


@mcp.tool()
async def get_market_overview() -> dict:
    """Get a high-level market overview of the last 30 days.

    Returns total signal count, tradeable signal count, average
    confidence, win rate, number of winners/losers, and signal
    distribution (bullish vs bearish). No parameters needed.
    """
    return await _get("/api/mcp/overview")


@mcp.tool()
async def get_unusual_activity(hours: int = 24, limit: int = 20) -> dict:
    """Get tickers with unusual options activity.

    Detects IV spikes, volume surges, open interest anomalies, and
    put/call skew shifts. High scores indicate potentially significant
    institutional positioning or upcoming catalysts.

    Args:
        hours: Lookback window in hours (1-168, default 24)
        limit: Max events to return (1-100, default 20)
    """
    return await _get("/api/mcp/unusual", {"hours": hours, "limit": limit})


@mcp.tool()
async def get_sports_feed(
    league: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Get latest sports betting intelligence with line mover scores.

    Returns news items with team extraction, injury/trade/lineup
    classification, urgency levels, and 0-100 line mover scores
    indicating likelihood of spread or total movement.

    Args:
        league: Filter by league — "NFL", "NBA", "MLB", "NHL", "NCAA", or "Soccer"
        limit: Max items to return (1-100, default 20)
    """
    params: dict = {"limit": limit}
    if league:
        params["league"] = league
    return await _get("/api/mcp/sports", params)


@mcp.tool()
async def search_signals(query: str, limit: int = 10) -> dict:
    """Search across all trading signals by keyword.

    Matches against ticker symbols, post titles, and event types.
    Use this to find signals about specific topics like "FDA approval",
    "earnings beat", or a company name.

    Args:
        query: Search query (e.g. "FDA approval", "NVDA", "earnings")
        limit: Max results to return (1-50, default 10)
    """
    return await _get("/api/mcp/search", {"q": query, "limit": limit})


# ── Resources (2) ────────────────────────────────────────────────────


@mcp.resource("rot://status")
async def server_status() -> str:
    """ROT server health and last update timestamp."""
    data = await _get("/health")
    if "error" in data:
        return f"Server status: UNREACHABLE — {data['error']}"
    return (
        f"Server status: {data.get('status', 'unknown')}\n"
        f"Version: {data.get('version', 'unknown')}\n"
        f"Base URL: https://web-production-71423.up.railway.app"
    )


@mcp.resource("rot://pricing")
async def pricing_info() -> str:
    """ROT subscription tiers and pricing information."""
    return (
        "ROT Pricing Tiers\n"
        "=================\n\n"
        "Free: Delayed signals (15 min), 10 signals/page, no API access.\n"
        "Pro ($19/mo): Real-time signals, basic analytics, 1,000 API calls/day.\n"
        "Premium ($49/mo): Advanced analytics, AI analysis, 5,000 API calls/day.\n"
        "Ultra ($99/mo): Full platform access, agents, 25,000 API calls/day.\n"
        "Enterprise (custom): Data licensing, webhooks, 100,000 API calls/day.\n\n"
        "All MCP tools are currently FREE with no API key required.\n"
        "Sign up at: https://web-production-71423.up.railway.app/pricing"
    )


# ── Public API ───────────────────────────────────────────────────────


def get_mcp_sse_app():
    """Return the Starlette ASGI app for the MCP SSE endpoint.

    Mount this at ``/mcp`` in the main FastAPI application::

        app.mount("/mcp", get_mcp_sse_app())
    """
    return mcp.sse_app()
