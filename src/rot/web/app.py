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

from rot.core.config import Settings
from rot.storage.database import Database
from rot.web.routes import signals, health, websocket

log = logging.getLogger(__name__)


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

    yield
    # Shutdown
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

    # Templates
    template_dir = Path(__file__).parent / "templates"
    template_dir.mkdir(exist_ok=True)
    app.state.templates = Jinja2Templates(directory=str(template_dir))

    # Static files
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

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

    # Dashboard routes (HTML)
    from rot.web.routes import dashboard, performance, backtest, raid_tracker, sports_tracker
    app.include_router(dashboard.router, tags=["dashboard"])
    app.include_router(performance.router, tags=["performance"])
    app.include_router(backtest.router, tags=["backtest"])
    app.include_router(raid_tracker.router, tags=["raid-tracker"])
    app.include_router(sports_tracker.router, tags=["sports-tracker"])

    return app
