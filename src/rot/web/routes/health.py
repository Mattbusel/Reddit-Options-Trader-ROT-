from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health_check(request: Request):
    db = request.app.state.db
    count = await db.get_signal_count()
    return {
        "status": "healthy",
        "version": "0.1.0",
        "signals_stored": count,
    }
