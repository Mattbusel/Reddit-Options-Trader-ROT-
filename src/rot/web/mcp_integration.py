"""MCP Server integration — mounts FastMCP Streamable HTTP endpoint into FastAPI.

This module creates a FastMCP server with 7 tools and 2 resources,
then exposes ``get_mcp_streamable_http_app()`` which returns a Starlette
ASGI app that should be mounted at ``/mcp`` in the main FastAPI application.

The Streamable HTTP transport (replacing legacy SSE) provides built-in
session resumability via ``EventStore`` and ``Last-Event-ID`` headers.
Clients auto-reconnect on disconnection without user intervention.

The MCP tools proxy to the same ``/api/mcp/*`` REST endpoints on
localhost, keeping the implementation DRY — the backend API routes
contain all the actual logic, and this module just wraps them for
MCP protocol consumption.

Usage in app.py::

    from rot.web.mcp_integration import get_mcp_streamable_http_app
    app.mount("/mcp", get_mcp_streamable_http_app())
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from starlette.responses import JSONResponse

from rot.web.mcp_event_store import InMemoryEventStore, SqliteEventStore

log = logging.getLogger(__name__)


# ── Error Middleware ─────────────────────────────────────────────────


class _MCPErrorMiddleware:
    """ASGI middleware wrapping the combined MCP app.

    Catches unhandled exceptions from the MCP transports and returns
    a clean JSON 500 instead of leaking stack traces to clients.
    Non-HTTP scopes (lifespan, websocket) pass through unchanged.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except Exception:
            method = scope.get("method", "?")
            path = scope.get("path", "?")
            log.exception("MCP transport error: %s %s", method, path)
            response = JSONResponse(
                {"error": "Internal MCP transport error"},
                status_code=500,
            )
            await response(scope, receive, send)


class MCPDispatcher:
    """Top-level ASGI app that routes /mcp/* directly to the MCP app.

    Requests whose path starts with ``/mcp`` are forwarded to the MCP
    ASGI app (with the ``/mcp`` prefix stripped so the sub-app sees
    ``/``, ``/sse``, etc.).  Everything else goes to the FastAPI app.

    This bypasses FastAPI's middleware stack (GZip, CSRF, SecurityHeaders)
    which uses ``BaseHTTPMiddleware`` — incompatible with the streaming
    ASGI responses produced by the MCP Streamable HTTP transport.
    """

    def __init__(self, fastapi_app, mcp_app):
        self.fastapi_app = fastapi_app
        self.mcp_app = mcp_app

    async def __call__(self, scope, receive, send):
        # Non-HTTP scopes (lifespan, websocket) always go to FastAPI
        if scope["type"] != "http":
            await self.fastapi_app(scope, receive, send)
            return
        path = scope.get("path", "")
        # Match /mcp/ and /mcp/sse etc, but NOT /mcp-server or /api/mcp/*
        if path == "/mcp" or path.startswith("/mcp/"):
            # Strip the /mcp prefix so the sub-app sees / , /sse, /messages/
            scope = dict(scope)
            stripped = path[4:]  # Remove "/mcp"
            scope["path"] = stripped or "/"
            scope["root_path"] = scope.get("root_path", "") + "/mcp"
            await self.mcp_app(scope, receive, send)
        else:
            await self.fastapi_app(scope, receive, send)


# ── Configuration ────────────────────────────────────────────────────

# When running inside the same process as FastAPI, we call localhost
# to reach our own /api/mcp/* endpoints.  The PORT env var is set
# by Railway; fallback to 8000 for local development.
_PORT = os.environ.get("PORT", "8000")
_INTERNAL_BASE = f"http://127.0.0.1:{_PORT}"
_TIMEOUT = 10.0

# ── MCP Server ───────────────────────────────────────────────────────

# Start with an in-memory event store; upgraded to SQLite via
# connect_mcp_event_store() during app startup if persistent storage
# is available.
_event_store: InMemoryEventStore | SqliteEventStore = InMemoryEventStore()

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
    # Streamable HTTP transport with session resumability
    event_store=_event_store,
    # Path "/" so mounted at /mcp in FastAPI the endpoint is /mcp/ (not /mcp/mcp)
    streamable_http_path="/",
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


def get_mcp_streamable_http_app():
    """Return a combined ASGI app serving both MCP transports.

    Routes (relative to the ``/mcp`` mount point):

    - ``POST/GET/DELETE /``  — Streamable HTTP (new protocol)
    - ``GET /sse``           — Legacy SSE endpoint
    - ``POST /messages/``    — Legacy SSE message posting

    Mount this at ``/mcp`` in the main FastAPI application::

        app.mount("/mcp", get_mcp_streamable_http_app())

    Uses the original Starlette app from ``streamable_http_app()``
    (which has the correct lifespan and middleware stack) and injects
    the SSE routes into it.  The session manager lifespan is started
    separately via ``start_mcp_session_manager()`` because FastAPI
    does not trigger sub-app lifespans.
    """
    # Get the original Starlette app — preserves lifespan, middleware,
    # and internal references that break if routes are transplanted.
    streamable_app = mcp.streamable_http_app()

    # Inject legacy SSE routes into the same app.
    # SSE routes (/sse, /messages/) don't overlap with streamable (/).
    sse_app = mcp.sse_app()
    for route in sse_app.routes:
        streamable_app.routes.append(route)

    # Force Starlette to rebuild middleware stack on next request
    # so the new routes are included.
    streamable_app.middleware_stack = None

    return _MCPErrorMiddleware(streamable_app)


def get_mcp_sse_app():
    """Deprecated — use ``get_mcp_streamable_http_app()`` instead.

    Kept for backward compatibility.  Returns the legacy SSE transport app.
    """
    return mcp.sse_app()


async def start_mcp_session_manager(stop_event) -> None:
    """Run the Streamable HTTP session manager until *stop_event* is set.

    FastAPI does NOT trigger sub-app lifespans, so the session manager
    must be started as an independent background task from ``server.py``.

    Args:
        stop_event: ``asyncio.Event`` — set to signal shutdown.
    """
    # Ensure streamable_http_app() has been called first so the
    # session manager exists.
    if mcp._session_manager is None:
        log.warning("MCP session manager not initialised — skipping")
        return

    async with mcp.session_manager.run():
        log.info("MCP Streamable HTTP session manager started")
        while not stop_event.is_set():
            await asyncio.sleep(1)
    log.info("MCP Streamable HTTP session manager stopped")


async def connect_mcp_event_store(db_dir: str) -> None:
    """Upgrade the event store to SQLite for cross-restart persistence.

    Called during app startup after the storage directory is known.
    If SQLite connection succeeds, the FastMCP server's event store
    is hot-swapped from InMemoryEventStore to SqliteEventStore.

    Args:
        db_dir: Directory for the ``mcp_events.db`` file
            (typically the ROT_STORAGE_ROOT).
    """
    global _event_store
    if isinstance(_event_store, SqliteEventStore):
        return  # already upgraded

    db_path = os.path.join(db_dir, "mcp_events.db")
    sqlite_store = SqliteEventStore(db_path)
    try:
        await sqlite_store.connect()
    except Exception as exc:
        log.warning("MCP SqliteEventStore failed, keeping in-memory: %s", exc)
        return

    # Hot-swap the event store on the FastMCP instance
    mcp._event_store = sqlite_store
    _event_store = sqlite_store
    log.info("MCP event store upgraded to SQLite: %s", db_path)


async def close_mcp_event_store() -> None:
    """Close the event store on shutdown (no-op for InMemoryEventStore)."""
    if isinstance(_event_store, SqliteEventStore):
        await _event_store.close()


async def cleanup_mcp_events() -> int:
    """Remove stale MCP events.  Returns number of deleted rows."""
    if isinstance(_event_store, SqliteEventStore):
        return await _event_store.cleanup()
    return 0
