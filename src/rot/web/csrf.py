"""CSRF protection middleware for form submissions.

Uses a pure-ASGI middleware (not BaseHTTPMiddleware) to avoid the
body-consumption bug where reading form data in middleware prevents
downstream route handlers from reading it again.
"""
from __future__ import annotations

import hmac
import secrets
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
CSRF_COOKIE_NAME = "rot_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_TOKEN_LENGTH = 32


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(CSRF_TOKEN_LENGTH)


def _parse_cookies(cookie_header: str) -> dict[str, str]:
    """Parse a Cookie header into a dict."""
    cookies: dict[str, str] = {}
    for item in cookie_header.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


class CSRFMiddleware:
    """Pure-ASGI CSRF middleware that peeks at the body without consuming it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        method = request.method

        # Parse CSRF cookie
        cookie_header = dict(scope.get("headers", [])).get(b"cookie", b"").decode()
        cookies = _parse_cookies(cookie_header) if cookie_header else {}
        csrf_cookie = cookies.get(CSRF_COOKIE_NAME)
        if not csrf_cookie:
            csrf_cookie = generate_csrf_token()

        is_secure = scope.get("scheme", "http") == "https"

        # Skip validation for safe methods — just ensure cookie is set
        if method in SAFE_METHODS:
            await self._call_with_csrf_cookie(scope, receive, send, csrf_cookie, is_secure)
            return

        # Skip CSRF for API key authenticated requests
        headers = dict(scope.get("headers", []))
        if b"x-api-key" in headers:
            await self.app(scope, receive, send)
            return

        # Skip CSRF for Stripe webhooks
        path = scope.get("path", "")
        if path.endswith("/webhook") and b"stripe-signature" in headers:
            await self.app(scope, receive, send)
            return

        # Skip CSRF for MCP protocol endpoints (SSE transport)
        if path.startswith("/mcp/"):
            await self.app(scope, receive, send)
            return

        # Skip CSRF for JSON API requests
        content_type = headers.get(b"content-type", b"").decode()
        if "application/json" in content_type and path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        # Check header first (HTMX sends x-csrf-token header)
        submitted_token = headers.get(b"x-csrf-token", b"").decode() or None

        # If no header token and it's a form POST, peek at the body
        if not submitted_token and (
            "application/x-www-form-urlencoded" in content_type
            or "multipart/form-data" in content_type
        ):
            submitted_token, receive = await self._peek_form_token(receive)

        if not submitted_token or not hmac.compare_digest(submitted_token, csrf_cookie):
            response = JSONResponse({"detail": "CSRF validation failed"}, status_code=403)
            await response(scope, receive, send)
            return

        await self._call_with_csrf_cookie(scope, receive, send, csrf_cookie, is_secure)

    async def _peek_form_token(self, receive: Receive) -> tuple[str | None, Receive]:
        """Read the request body to extract csrf_token, then replay it for downstream."""
        body_chunks: list[bytes] = []
        while True:
            message = await receive()
            body_chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break

        full_body = b"".join(body_chunks)
        token = None
        try:
            parsed = parse_qs(full_body.decode())
            values = parsed.get(CSRF_FORM_FIELD, [])
            if values:
                token = values[0]
        except (UnicodeDecodeError, ValueError):
            pass  # Malformed body — leave token as None

        # Create a replay receive that yields the cached body
        body_sent = False

        async def replay_receive() -> dict:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": full_body, "more_body": False}
            return {"type": "http.disconnect"}

        return token, replay_receive

    async def _call_with_csrf_cookie(
        self, scope: Scope, receive: Receive, send: Send,
        csrf_cookie: str, is_secure: bool,
    ) -> None:
        """Call the downstream app and inject the CSRF Set-Cookie header."""
        cookie_value = (
            f"{CSRF_COOKIE_NAME}={csrf_cookie}; Path=/; SameSite=Lax; Max-Age=86400"
        )
        if is_secure:
            cookie_value += "; Secure"

        async def send_with_cookie(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"set-cookie", cookie_value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)
