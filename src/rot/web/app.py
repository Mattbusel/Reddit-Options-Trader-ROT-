from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from rot.web.nonce_templates import NonceTemplates
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from rot.core.config import Settings
from rot.web.csrf import CSRFMiddleware
from rot.web.request_id_middleware import RequestIDMiddleware
from rot.web.error_middleware import ErrorTrackingMiddleware
from rot.web.security_headers import SecurityHeadersMiddleware

log = logging.getLogger(__name__)


async def _periodic_db_cleanup(db, interval_s: int = 3600):
    """Background task: lightweight cleanup of api_usage, old signals, blob compaction, and AI summary backfill."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            api_count = await db.cleanup_old_api_usage()
            sig_count = await db.cleanup_old_signals()
            blob_count = await db.compact_old_signal_blobs(older_than_days=3)
            if api_count or sig_count or blob_count:
                log.info("DB cleanup: removed %d api_usage, %d old signals, compacted %d blobs",
                         api_count, sig_count, blob_count)
        except Exception as e:
            log.error("DB cleanup error: %s", e)

        # Cleanup stale MCP session events
        try:
            from rot.web.mcp_integration import cleanup_mcp_events
            mcp_deleted = await cleanup_mcp_events()
            if mcp_deleted:
                log.info("MCP event cleanup: removed %d stale events", mcp_deleted)
        except Exception as e:
            log.debug("MCP event cleanup: %s", e)

        # Backfill AI summaries for signals that don't have one
        try:
            from rot.reasoner.ai_summary import backfill_ai_summaries
            await backfill_ai_summaries(db, limit=20)
        except Exception as e:
            log.debug("AI summary backfill: %s", e)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a MINIMAL FastAPI app with just /health for fast startup.

    Route registration and DB connection happen later via register_routes()
    and connect_db(), called from server.py's _heavy_init() AFTER uvicorn
    has already bound the port.  This ensures Railway health checks pass
    within seconds of cold start.
    """
    if settings is None:
        settings = Settings()

    app = FastAPI(
        title="ROT - Reddit Options Trader API",
        description="""
# ROT (Reddit Options Trader) API

Real-time social intelligence platform for options trading signals.

## Features

- **Real-time Signals**: AI-powered analysis of Reddit trends for actionable options trade ideas
- **Multi-source Intelligence**: Analyzes 13+ RSS feeds, Reddit, StockTwits, Twitter
- **ML Credibility Scoring**: GradientBoosting model with 32 features for signal quality
- **Advanced Analytics**: Win rate tracking, backtesting, sector rotation, correlation analysis
- **Tier-based Access**: Free → Pro → Premium → Ultra → Enterprise tiers

## Authentication

All API endpoints require authentication via API key:

```bash
curl -H "X-API-Key: your_api_key_here" https://api.rot.example.com/api/v1/signals
```

Get your API key at [/account](/account) after registration.

## Rate Limits

| Tier | Daily Limit | Burst Limit | Real-time |
|------|-------------|-------------|-----------|
| Pro | 1,000 | 50/min | ✓ |
| Premium | 5,000 | 200/min | ✓ |
| Ultra | 25,000 | 500/min | ✓ |
| Enterprise | 100,000 | 2,000/min | ✓ |

## Support

- Documentation: [/docs](/docs)
- Issues: [GitHub](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-)
- Email: support@rot.example.com
        """,
        version="0.1.0",
        contact={
            "name": "ROT Support",
            "url": "https://github.com/Mattbusel/Reddit-Options-Trader-ROT-",
            "email": "support@rot.example.com"
        },
        license_info={
            "name": "Proprietary",
            "url": "https://rot.example.com/terms"
        },
        servers=[
            {
                "url": "https://api.rot.example.com",
                "description": "Production server"
            },
            {
                "url": "http://localhost:8000",
                "description": "Local development server"
            }
        ],
        openapi_tags=[
            {
                "name": "signals",
                "description": "Trading signal endpoints - AI-generated options trade ideas"
            },
            {
                "name": "analytics",
                "description": "Performance analytics and metrics"
            },
            {
                "name": "backtest",
                "description": "Historical backtesting endpoints"
            },
            {
                "name": "auth",
                "description": "Authentication and user management"
            },
            {
                "name": "health",
                "description": "System health and status checks"
            }
        ],
        responses={
            401: {
                "description": "Unauthorized - Invalid or missing API key",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "error": "Authentication required",
                            "error_code": "UNAUTHORIZED"
                        }
                    }
                }
            },
            429: {
                "description": "Rate limit exceeded",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "error": "Rate limit exceeded",
                            "error_code": "RATE_LIMIT_EXCEEDED"
                        }
                    }
                }
            }
        }
    )

    # Error tracking — captures unhandled exceptions and HTTP errors
    app.add_middleware(ErrorTrackingMiddleware)

    # Request ID tracking — must be first middleware for proper context
    app.add_middleware(RequestIDMiddleware)

    # GZip compression — reduces HTML/JSON response sizes by ~70%
    # minimum_size=500: Only compress responses >= 500 bytes (small responses not worth overhead)
    # compresslevel=6: Balanced compression (1=fastest/largest, 9=slowest/smallest)
    app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)

    # CSRF protection — validates tokens on state-changing requests
    app.add_middleware(CSRFMiddleware)

    # CORS — restrict to explicit allowlist (ROT_WEB_CORS_ORIGINS env var)
    allowed_origins = [o.strip() for o in settings.web.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security headers — CSP, X-Frame-Options, X-Content-Type-Options, etc.
    app.add_middleware(SecurityHeadersMiddleware)

    # Store settings on app state (no heavy imports needed)
    app.state.settings = settings

    # Templates (lightweight — just reads directory listing)
    template_dir = Path(__file__).parent / "templates"
    template_dir.mkdir(exist_ok=True)
    app.state.templates = NonceTemplates(directory=str(template_dir))

    # Static files
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Root-level /health for Railway health checks — no DB dependency, instant response
    @app.get("/health")
    async def root_health():
        return {"status": "healthy", "version": "0.1.0"}

    return app


async def connect_db(app: FastAPI):
    """Connect to the database and store on app state. Called after port bind."""
    from rot.storage.database import Database
    from rot.web.query_cache import QueryCache

    settings = app.state.settings

    db = Database(db_path=settings.db_path)
    app.state.db = db
    app.state.signal_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    app.state.query_cache = QueryCache(default_ttl=60)

    # Volume diagnostics
    db_path = str(db.db_path)
    db_dir = str(db.db_path.parent)
    log.info("Database path: %s", db_path)
    log.info("Database dir exists: %s", os.path.isdir(db_dir))
    log.info("Database file exists: %s", os.path.isfile(db_path))
    log.info("RAILWAY_VOLUME_MOUNT_PATH: %s", os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "NOT SET"))
    log.info("ROT_STORAGE_ROOT: %s", os.environ.get("ROT_STORAGE_ROOT", "NOT SET"))

    if os.path.isdir(db_dir):
        files = os.listdir(db_dir)
        log.info("Files in %s: %s", db_dir, files)
    else:
        log.warning("Database directory %s does NOT exist!", db_dir)

    await db.connect()

    if os.path.isfile(db_path):
        size = os.path.getsize(db_path)
        log.info("Database connected: %s (size=%d bytes)", db_path, size)

    # Initialize service layer
    from rot.services.paper_trading_service import PaperTradingService
    from rot.services.signal_service import SignalService
    from rot.services.user_service import UserService

    app.state.paper_trading_service = PaperTradingService(db=db)
    app.state.signal_service = SignalService(db=db, cache=app.state.query_cache)
    app.state.user_service = UserService(db=db)

    # Upgrade MCP event store to SQLite for cross-restart session persistence
    try:
        from rot.web.mcp_integration import connect_mcp_event_store
        await connect_mcp_event_store(str(db.db_path.parent))
    except Exception as exc:
        log.warning("MCP event store upgrade skipped: %s", exc)

    # Start periodic cleanup task
    app.state._db_cleanup_task = asyncio.create_task(_periodic_db_cleanup(db))


def register_routes(app: FastAPI):
    """Register all route modules, organized by domain.

    Called after port bind to avoid slow imports blocking startup.

    Domain groups:
    - core-api: health, signals, export, websocket
    - auth: authentication, billing (stripe)
    - admin: error dashboard (admin-only)
    - trading: paper trading, agents, strategy, terminal, backtest, replay
    - analytics: performance, accuracy, confidence, quality, correlations,
                 unusual activity, flow, social, sector rotation, sentiment
    - market-data: macro, ticker dive, tradingview, news, congress
    - dashboard: landing pages, informational (glossary, faq, badges, etc.)
    - integrations: brokers, affiliates, enterprise, widgets, leaderboard, API status
    """
    # ── Core API ──────────────────────────────────────────────────────
    # Export MUST be registered before signals so /signals/export
    # matches before /signals/{signal_id} catch-all
    from rot.web.routes import signals, health, websocket, export
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(export.router, prefix="/api/v1", tags=["export"])
    app.include_router(signals.router, prefix="/api/v1", tags=["signals"])
    app.include_router(websocket.router, prefix="/api/v1", tags=["websocket"])

    # ── Auth & Billing ────────────────────────────────────────────────
    from rot.web.routes import auth_routes, stripe_routes
    app.include_router(auth_routes.router, prefix="/api/v1", tags=["auth"])
    app.include_router(stripe_routes.router, prefix="/api/v1", tags=["billing"])

    # ── Admin ─────────────────────────────────────────────────────────
    from rot.web.routes import error_dashboard
    app.include_router(error_dashboard.router, tags=["admin"])

    # ── Trading ───────────────────────────────────────────────────────
    from rot.web.routes import paper_trading, agents, strategy, terminal, backtest, replay
    app.include_router(paper_trading.router, tags=["trading"])
    app.include_router(agents.router, tags=["trading"])
    app.include_router(strategy.router, tags=["trading"])
    app.include_router(terminal.router, tags=["trading"])
    app.include_router(backtest.router, tags=["trading"])
    app.include_router(replay.router, tags=["trading"])

    # ── Analytics ─────────────────────────────────────────────────────
    from rot.web.routes import (
        performance, accuracy_breakdown, confidence_calibration,
        signal_quality, correlations, unusual_activity, flow, social,
        sector_rotation, sentiment,
    )
    app.include_router(performance.router, tags=["analytics"])
    app.include_router(accuracy_breakdown.router, tags=["analytics"])
    app.include_router(confidence_calibration.router, tags=["analytics"])
    app.include_router(signal_quality.router, tags=["analytics"])
    app.include_router(correlations.router, tags=["analytics"])
    app.include_router(unusual_activity.router, tags=["analytics"])
    app.include_router(flow.router, tags=["analytics"])
    app.include_router(social.router, tags=["analytics"])
    app.include_router(sector_rotation.router, tags=["analytics"])
    app.include_router(sentiment.router, tags=["analytics"])

    # ── Market Data ───────────────────────────────────────────────────
    from rot.web.routes import macro, ticker_dive, tradingview, news_feed, congress_tracker
    app.include_router(macro.router, tags=["market-data"])
    app.include_router(ticker_dive.router, tags=["market-data"])
    app.include_router(tradingview.router, tags=["market-data"])
    app.include_router(news_feed.router, tags=["market-data"])
    app.include_router(congress_tracker.router, tags=["market-data"])

    # ── Dashboard & Informational ─────────────────────────────────────
    from rot.web.routes import (
        dashboard, raid_tracker, sports_tracker, hall_of_legends,
        glossary, ceo_rap_sheet, weekly_wrap, seo, faq, badges,
    )
    app.include_router(dashboard.router, tags=["dashboard"])
    app.include_router(raid_tracker.router, tags=["dashboard"])
    app.include_router(sports_tracker.router, tags=["dashboard"])
    app.include_router(hall_of_legends.router, tags=["dashboard"])
    app.include_router(glossary.router, tags=["dashboard"])
    app.include_router(ceo_rap_sheet.router, tags=["dashboard"])
    app.include_router(weekly_wrap.router, tags=["dashboard"])
    app.include_router(seo.router, tags=["dashboard"])
    app.include_router(faq.router, tags=["dashboard"])
    app.include_router(badges.router, tags=["dashboard"])

    # ── Integrations ──────────────────────────────────────────────────
    from rot.web.routes import brokers, affiliates, enterprise, widgets, paper_leaderboard, api_status
    app.include_router(brokers.router, tags=["integrations"])
    app.include_router(affiliates.router, tags=["integrations"])
    app.include_router(enterprise.router, tags=["integrations"])
    app.include_router(widgets.router, tags=["integrations"])
    app.include_router(paper_leaderboard.router, tags=["integrations"])
    app.include_router(api_status.router, tags=["integrations"])

    # ── MCP (API + landing page + Streamable HTTP protocol endpoint) ─
    from rot.web.routes import mcp_api, mcp_landing
    app.include_router(mcp_api.router, tags=["mcp"])
    app.include_router(mcp_landing.router, tags=["mcp"])

    # NOTE: The MCP protocol endpoints (/mcp/, /mcp/sse, /mcp/messages/)
    # are mounted at the ASGI level in server.py via MCPDispatcher, NOT
    # inside FastAPI.  This is required because FastAPI's BaseHTTPMiddleware
    # (GZip, SecurityHeaders) is incompatible with streaming ASGI responses
    # used by the MCP Streamable HTTP transport.  The /api/mcp/* REST routes
    # and /mcp-server landing page above ARE in FastAPI (they return normal
    # JSON/HTML responses).

    log.info("All routes registered (%d routes)", len(app.routes))
