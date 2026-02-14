from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from rot.core.config import Settings
from rot.storage.database import Database
from rot.web.routes import signals, health, websocket

log = logging.getLogger(__name__)


async def _periodic_db_cleanup(db: Database, interval_s: int = 3600):
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db: Database = app.state.db

    # Volume diagnostics
    db_path = str(db.db_path)
    db_dir = str(db.db_path.parent)
    log.info("Database path: %s", db_path)
    log.info("Database dir exists: %s", os.path.isdir(db_dir))
    log.info("Database file exists: %s", os.path.isfile(db_path))
    log.info("RAILWAY_VOLUME_MOUNT_PATH: %s", os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "NOT SET"))
    log.info("ROT_STORAGE_ROOT: %s", os.environ.get("ROT_STORAGE_ROOT", "NOT SET"))

    # List files in the data directory to check volume state
    if os.path.isdir(db_dir):
        files = os.listdir(db_dir)
        log.info("Files in %s: %s", db_dir, files)
    else:
        log.warning("Database directory %s does NOT exist!", db_dir)

    await db.connect()

    # Confirm DB is on persistent volume
    if os.path.isfile(db_path):
        size = os.path.getsize(db_path)
        log.info("Database connected: %s (size=%d bytes)", db_path, size)

    # Start periodic cleanup task
    cleanup_task = asyncio.create_task(_periodic_db_cleanup(db))

    yield
    # Shutdown
    cleanup_task.cancel()
    await db.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    app = FastAPI(
        title="ROT - Reddit Options Trader",
        description="Real-time Reddit trend detection and options trade signal API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # GZip compression — reduces HTML/JSON response sizes by ~70%
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # State
    db = Database(db_path=settings.db_path)
    app.state.db = db
    app.state.settings = settings
    app.state.signal_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    # Dashboard query cache — reduces DB hits on repeated page loads
    from rot.web.query_cache import QueryCache
    app.state.query_cache = QueryCache(default_ttl=60)

    # Templates
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

    # TradingView, broker, affiliate, and enterprise routes (mixed HTML + API)
    from rot.web.routes import tradingview, brokers, affiliates, enterprise
    app.include_router(tradingview.router, tags=["tradingview"])
    app.include_router(brokers.router, tags=["brokers"])
    app.include_router(affiliates.router, tags=["affiliates"])
    app.include_router(enterprise.router, tags=["enterprise"])

    # Widget, paper trading, badges, correlation, unusual activity routes
    from rot.web.routes import widgets, paper_trading, badges, correlations, unusual_activity
    app.include_router(widgets.router, tags=["widgets"])
    app.include_router(paper_trading.router, tags=["paper-trading"])
    app.include_router(badges.router, tags=["badges"])
    app.include_router(correlations.router, tags=["correlations"])
    app.include_router(unusual_activity.router, tags=["unusual-activity"])

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

    return app
