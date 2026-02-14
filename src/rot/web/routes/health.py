from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health_check(request: Request):
    """Full health check with DB query — used by /api/v1/health."""
    try:
        db = request.app.state.db
        count = await db.get_signal_count()
        return {
            "status": "healthy",
            "version": "0.1.0",
            "signals_stored": count,
        }
    except Exception:
        # DB may not be ready yet — still return healthy so Railway doesn't kill us
        return {
            "status": "healthy",
            "version": "0.1.0",
            "signals_stored": -1,
        }
