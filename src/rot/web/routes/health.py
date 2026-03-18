from __future__ import annotations

import logging
import os
import platform
import time
from pathlib import Path

import psutil
from fastapi import APIRouter, Request

log = logging.getLogger(__name__)

from rot.web.auth import get_current_user_optional

router = APIRouter()

# Track server start time for uptime calculation
_SERVER_START_TIME = time.time()


@router.get("/health")
async def health_check(request: Request):
    """Health check endpoint.

    Unauthenticated: returns {"status": "ok"} only.
    Admin-authenticated: returns full diagnostic data.
    """
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "")

    # Unauthenticated and non-admin users get minimal response only
    if tier != "admin":
        return {"status": "ok"}

    from rot.storage.backup import BackupManager

    health_data = {
        "status": "healthy",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - _SERVER_START_TIME),
    }

    # Database health
    try:
        db = request.app.state.db
        signal_count = await db.get_signal_count()
        settings = request.app.state.settings

        db_path = Path(settings.storage.root) / "rot.db"
        db_size_mb = db_path.stat().st_size / (1024 * 1024) if db_path.exists() else 0

        health_data["database"] = {
            "status": "connected",
            "signals_stored": signal_count,
            "size_mb": round(db_size_mb, 2),
        }
    except Exception as e:
        # DB may not be ready yet — mark as initializing
        log.warning("Database health check failed (may still be initializing): %s", e)
        health_data["database"] = {
            "status": "initializing",
            "error": str(e),
            "signals_stored": -1,
        }

    # System metrics
    try:
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()

        health_data["system"] = {
            "memory_rss_mb": round(memory_info.rss / (1024 * 1024), 2),
            "memory_percent": round(process.memory_percent(), 2),
            "cpu_percent": round(process.cpu_percent(interval=0.1), 2),
            "num_threads": process.num_threads(),
            "python_version": platform.python_version(),
            "platform": platform.system(),
        }

        # Disk usage for storage directory
        try:
            settings = request.app.state.settings
            storage_path = Path(settings.storage.root)
            disk_usage = psutil.disk_usage(str(storage_path))
            health_data["system"]["disk_usage_percent"] = round(disk_usage.percent, 2)
            health_data["system"]["disk_free_gb"] = round(disk_usage.free / (1024**3), 2)
        except Exception as _e:
            log.debug("health: disk usage unavailable: %s", _e)

    except Exception as e:
        log.exception("System metrics collection failed")
        health_data["system"] = {"error": str(e)}

    # Backup status
    try:
        settings = request.app.state.settings
        backup_mgr = BackupManager(
            db_path=f"{settings.storage.root}/rot.db",
            backup_dir=f"{settings.storage.root}/backups",
        )
        backups = await backup_mgr.list_backups()

        if backups:
            latest_backup = backups[0]
            total_backup_size = sum(b["size_mb"] for b in backups)

            health_data["backups"] = {
                "count": len(backups),
                "total_size_mb": round(total_backup_size, 2),
                "latest_backup": {
                    "filename": latest_backup["filename"],
                    "age_hours": round(latest_backup["age_hours"], 1),
                    "size_mb": round(latest_backup["size_mb"], 2),
                },
            }
        else:
            health_data["backups"] = {"count": 0, "status": "no_backups_yet"}

    except Exception as e:
        log.exception("Backup status check failed")
        health_data["backups"] = {"error": str(e)}

    # Environment info
    try:
        health_data["environment"] = {
            "deployment": "railway" if os.getenv("RAILWAY_ENVIRONMENT") else "local",
            "railway_env": os.getenv("RAILWAY_ENVIRONMENT", "n/a"),
        }
    except Exception as _e:
        log.debug("health: environment info unavailable: %s", _e)

    return health_data
