from __future__ import annotations

import asyncio
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db: Database = app.state.db
    await db.connect()
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

    # Routes
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(signals.router, prefix="/api/v1", tags=["signals"])
    app.include_router(websocket.router, prefix="/api/v1", tags=["websocket"])

    # Dashboard routes (HTML)
    from rot.web.routes import dashboard
    app.include_router(dashboard.router, tags=["dashboard"])

    return app
