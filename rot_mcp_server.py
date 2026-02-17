"""ROT MCP Server — Model Context Protocol interface for Reddit Options Trader.

Exposes ROT's trading intelligence (signals, sentiment, unusual activity,
sports betting) as MCP tools that any LLM client can call. Zero install —
just point your MCP client at the remote URL.

Usage:
    # Run locally (development)
    pip install "mcp[cli]" httpx
    python rot_mcp_server.py

    # Or connect any MCP client to the hosted URL:
    # https://web-production-71423.up.railway.app/mcp
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

BASE_URL = os.environ.get(
    "ROT_BASE_URL",
    "https://web-production-71423.up.railway.app",
)
API_KEY = os.environ.get("ROT_API_KEY", "")  # Optional — no auth required at launch
TIMEOUT = 15.0

# ── MCP Server ───────────────────────────────────────────────────────

mcp = FastMCP(
    "ROT — Reddit Options Trader",
    instructions=(
        "Real-time trading intelligence from Reddit, RSS, and social media. "
        "AI-powered options signals, sentiment analysis, unusual activity "
        "detection, and sports betting intelligence."
    ),
)


# ── HTTP Client Helper ───────────────────────────────────────────────


async def _get(path: str, params: dict | None = None) -> dict:
    """Make a GET request to the ROT backend API."""
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    url = f"{BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            return {"error": f"Request to {path} timed out after {TIMEOUT}s"}
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
        f"Base URL: {BASE_URL}"
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


# ── Entrypoint ───────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="sse")
