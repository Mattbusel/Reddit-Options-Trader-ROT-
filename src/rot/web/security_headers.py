"""Security headers middleware for FastAPI.

Adds standard security headers to all responses:
- Content-Security-Policy (with unsafe-inline for script-src due to 102 inline scripts)
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: restricts browser features
- X-XSS-Protection: 0 (deprecated, set to 0 per OWASP to avoid legacy browser bugs)

CSP NOTE: This codebase has 102 inline <script> tags across 40+ templates.
Migrating to nonce-based CSP is a future improvement tracked separately.
For now, 'unsafe-inline' is used for script-src, which is acceptable given:
1. Jinja2 autoescape is ON (no XSS vectors for inline injection)
2. All |safe usages are audited safe (tojson or hardcoded content)
3. No Markup() or mark_safe() calls exist in the codebase
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


# CSP directives -- each is a separate policy directive
_CSP_DIRECTIVES = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://js.stripe.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "font-src 'self' data:",
    "connect-src 'self' ws: wss: https://api.stripe.com",
    "frame-src https://js.stripe.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self' https://checkout.stripe.com",
    "object-src 'none'",
]

_CSP_VALUE = "; ".join(_CSP_DIRECTIVES)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all HTTP responses."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(self)"
        )
        response.headers["Content-Security-Policy"] = _CSP_VALUE

        return response
