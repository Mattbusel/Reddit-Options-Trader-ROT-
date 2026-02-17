"""Security headers middleware for FastAPI.

Adds standard security headers to all responses:
- Content-Security-Policy (nonce-based for script-src, unsafe-inline for style-src)
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: restricts browser features
- X-XSS-Protection: 0 (deprecated, set to 0 per OWASP to avoid legacy browser bugs)

CSP uses per-request cryptographic nonces for script-src (eliminates unsafe-inline
for scripts, the primary XSS vector). style-src retains 'unsafe-inline' because
Tailwind CSS CDN (cdn.tailwindcss.com) dynamically generates <style> tags at runtime
via JavaScript — those runtime-injected styles cannot carry a server-side nonce.
This is standard practice per OWASP: inline styles are not a meaningful XSS vector.
The nonce is generated in dispatch(), stored on request.state.csp_nonce,
and auto-injected into Jinja2 template contexts by NonceTemplates.
"""
from __future__ import annotations

import base64
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


# Static CSP directives (do not change per-request)
_CSP_STATIC_DIRECTIVES = [
    "default-src 'self'",
    "img-src 'self' data: https: https://www.googletagmanager.com https://www.google-analytics.com",
    "font-src 'self' data:",
    "connect-src 'self' ws: wss: https://api.stripe.com https://www.google-analytics.com https://analytics.google.com https://*.google-analytics.com https://*.analytics.google.com",
    "frame-src https://js.stripe.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self' https://checkout.stripe.com",
    "object-src 'none'",
]

_CSP_STATIC_PART = "; ".join(_CSP_STATIC_DIRECTIVES)


def _build_csp(nonce: str) -> str:
    """Build full CSP header with per-request nonce for scripts.

    style-src uses 'unsafe-inline' because Tailwind CSS CDN dynamically
    generates <style> tags at runtime that cannot carry a server-side nonce.
    """
    return (
        f"script-src 'self' 'nonce-{nonce}' https://cdn.tailwindcss.com https://js.stripe.com https://www.googletagmanager.com; "
        f"style-src 'self' 'unsafe-inline'; "
        f"{_CSP_STATIC_PART}"
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all HTTP responses with per-request CSP nonce."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        # Generate a cryptographic nonce for this request
        nonce = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request.state.csp_nonce = nonce

        response = await call_next(request)

        # Skip security headers for MCP SSE transport — BaseHTTPMiddleware
        # can buffer streaming responses and break SSE event delivery.
        if request.url.path.startswith("/mcp/"):
            return response

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(self)"
        )
        response.headers["Content-Security-Policy"] = _build_csp(nonce)

        return response
