from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from rot.core.config import Settings
from rot.web.request_id_middleware import RequestIDMiddleware
from rot.web.error_middleware import ErrorTrackingMiddleware

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

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store settings on app state (no heavy imports needed)
    app.state.settings = settings

    # Templates (lightweight — just reads directory listing)
    template_dir = Path(__file__).parent / "templates"
    template_dir.mkdir(exist_ok=True)
    app.state.templates = Jinja2Templates(directory=str(template_dir))

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

    # Start periodic cleanup task
    app.state._db_cleanup_task = asyncio.create_task(_periodic_db_cleanup(db))


def register_routes(app: FastAPI):
    """Register all route modules. Called after port bind to avoid slow imports blocking startup."""
    from rot.web.routes import signals, health, websocket

    # Routes — export MUST be registered before signals so /signals/export
    # matches before /signals/{signal_id} catch-all
    from rot.web.routes import auth_routes, export, stripe_routes
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(export.router, prefix="/api/v1", tags=["export"])
    app.include_router(signals.router, prefix="/api/v1", tags=["signals"])
    app.include_router(websocket.router, prefix="/api/v1", tags=["websocket"])

    # Auth & billing routes
    app.include_router(auth_routes.router, prefix="/api/v1", tags=["auth"])
    app.include_router(stripe_routes.router, prefix="/api/v1", tags=["billing"])

    # Error monitoring (admin only)
    from rot.web.routes import error_dashboard
    app.include_router(error_dashboard.router, tags=["monitoring"])

    # TradingView, broker, affiliate, and enterprise routes (mixed HTML + API)
    from rot.web.routes import tradingview, brokers, affiliates, enterprise
    app.include_router(tradingview.router, tags=["tradingview"])
    app.include_router(brokers.router, tags=["brokers"])
    app.include_router(affiliates.router, tags=["affiliates"])
    app.include_router(enterprise.router, tags=["enterprise"])

    # Widget, paper trading, badges, correlation, unusual activity, flow, social routes
    from rot.web.routes import widgets, paper_trading, badges, correlations, unusual_activity, flow, social, strategy
    app.include_router(widgets.router, tags=["widgets"])
    app.include_router(paper_trading.router, tags=["paper-trading"])
    app.include_router(badges.router, tags=["badges"])
    app.include_router(correlations.router, tags=["correlations"])
    app.include_router(unusual_activity.router, tags=["unusual-activity"])
    app.include_router(flow.router, tags=["flow"])
    app.include_router(social.router, tags=["social"])
    app.include_router(strategy.router, tags=["strategy"])

    # Competitor-killer routes: news feed, congress tracker, paper leaderboard
    from rot.web.routes import news_feed, congress_tracker, paper_leaderboard, api_status
    app.include_router(news_feed.router, tags=["news"])
    app.include_router(congress_tracker.router, tags=["congress"])
    app.include_router(paper_leaderboard.router, tags=["leaderboard"])
    app.include_router(api_status.router, tags=["api-status"])

    # Terminal and Agents routes
    from rot.web.routes import terminal, agents
    app.include_router(terminal.router, tags=["terminal"])
    app.include_router(agents.router, tags=["agents"])

    # Dashboard routes (HTML)
    from rot.web.routes import (
        dashboard, performance, backtest, raid_tracker, sports_tracker,
        hall_of_legends, glossary, ceo_rap_sheet,
        sentiment, ticker_dive, weekly_wrap, replay, seo, faq,
        accuracy_breakdown, confidence_calibration, sector_rotation,
        signal_quality,
    )
    app.include_router(dashboard.router, tags=["dashboard"])
    app.include_router(performance.router, tags=["performance"])
    app.include_router(accuracy_breakdown.router, tags=["accuracy-breakdown"])
    app.include_router(confidence_calibration.router, tags=["confidence-calibration"])
    app.include_router(sector_rotation.router, tags=["sector-rotation"])
    app.include_router(signal_quality.router, tags=["signal-quality"])
    app.include_router(backtest.router, tags=["backtest"])
    app.include_router(raid_tracker.router, tags=["raid-tracker"])
    app.include_router(sports_tracker.router, tags=["sports-tracker"])
    app.include_router(hall_of_legends.router, tags=["hall-of-legends"])
    app.include_router(glossary.router, tags=["glossary"])
    app.include_router(ceo_rap_sheet.router, tags=["ceo-rap-sheet"])
    app.include_router(sentiment.router, tags=["sentiment"])
    app.include_router(ticker_dive.router, tags=["ticker-dive"])
    app.include_router(weekly_wrap.router, tags=["weekly-wrap"])
    app.include_router(replay.router, tags=["replay"])
    app.include_router(seo.router, tags=["seo"])
    app.include_router(faq.router, tags=["faq"])

    # Macro events & economic calendar
    from rot.web.routes import macro
    app.include_router(macro.router, tags=["macro"])

    log.info("All routes registered (%d routes)", len(app.routes))
