"""
ROT request logging middleware.

Every authenticated API request is logged to `api_request_log` for security
monitoring and anomaly detection.  Unauthenticated requests to protected
endpoints are blocked upstream by `require_api_auth`; this middleware only
records requests that made it through auth.

The table is write-only from the middleware's perspective — the access monitor
reads it independently.

Schema (created at startup via AccessLogMixin.ensure_access_log_schema()):

    CREATE TABLE IF NOT EXISTS api_request_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          REAL    NOT NULL,             -- unix epoch float
        api_key_hash TEXT,                        -- SHA-256 of key (never raw)
        user_id     TEXT,
        tier        TEXT,
        method      TEXT    NOT NULL,
        endpoint    TEXT    NOT NULL,             -- path only, no query string
        status_code INTEGER,
        response_ms REAL,
        ip          TEXT,
        user_agent  TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_arl_ts      ON api_request_log(ts DESC);
    CREATE INDEX IF NOT EXISTS idx_arl_ip      ON api_request_log(ip, ts DESC);
    CREATE INDEX IF NOT EXISTS idx_arl_key     ON api_request_log(api_key_hash, ts DESC);

Usage:
    Add to FastAPI app:
        from rot.auth.middleware import RequestLogMiddleware
        app.add_middleware(RequestLogMiddleware)
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)

# Endpoints we skip logging entirely (high-volume, no security value)
_SKIP_PATHS = frozenset({"/health", "/favicon.ico", "/static"})


def _path_prefix_skip(path: str) -> bool:
    for prefix in ("/static/", "/assets/"):
        if path.startswith(prefix):
            return True
    return path in _SKIP_PATHS


def _get_ip(request: Request) -> str:
    """Extract real client IP, respecting Railway/Cloudflare forwarding headers."""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        # Leftmost address is the original client
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _hash_key(raw_key: str) -> str:
    """SHA-256 of the raw API key — never store the key itself."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that logs every request to `api_request_log`.

    Attaches to `request.state`:
        - `rot_user`: resolved user dict (if auth succeeded) — set by auth layer
        - `rot_start_ts`: float timestamp before processing
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if _path_prefix_skip(request.url.path):
            return await call_next(request)

        start = time.time()
        request.state.rot_start_ts = start

        response = await call_next(request)

        elapsed_ms = (time.time() - start) * 1000.0

        # Best-effort log — never let logging crash the response
        try:
            await self._log_request(request, response.status_code, elapsed_ms)
        except Exception as exc:
            log.debug("RequestLogMiddleware: log error: %s", exc)

        return response

    async def _log_request(
        self,
        request: Request,
        status_code: int,
        response_ms: float,
    ) -> None:
        db = getattr(getattr(request, "app", None), "state", None)
        if db is None:
            return
        db = getattr(db, "db", None)
        if db is None:
            return

        # Resolve user from state (set by auth layer if auth succeeded)
        user: Optional[dict] = getattr(request.state, "rot_user", None)
        user_id: Optional[str] = user.get("id") if user else None
        tier: Optional[str] = user.get("tier") if user else None

        # Determine api_key_hash without storing raw key
        api_key_hash: Optional[str] = None
        raw_key = request.headers.get("x-api-key", "")
        if raw_key:
            api_key_hash = _hash_key(raw_key)
        else:
            # Check Authorization: Bearer rot_...
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer rot_"):
                api_key_hash = _hash_key(auth_header[7:])

        ip = _get_ip(request)
        endpoint = request.url.path  # no query string
        method = request.method
        user_agent = request.headers.get("user-agent", "")[:200]

        await db.execute(
            """
            INSERT INTO api_request_log
                (ts, api_key_hash, user_id, tier, method, endpoint,
                 status_code, response_ms, ip, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                api_key_hash,
                user_id,
                tier,
                method,
                endpoint,
                status_code,
                round(response_ms, 2),
                ip,
                user_agent,
            ),
        )
        await db.commit()
