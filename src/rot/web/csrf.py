"""CSRF protection middleware for form submissions."""
from __future__ import annotations

import hmac
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
CSRF_COOKIE_NAME = "rot_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_TOKEN_LENGTH = 32


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(CSRF_TOKEN_LENGTH)


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Always ensure a CSRF token exists in cookies
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        if not csrf_cookie:
            csrf_cookie = generate_csrf_token()

        # Only set secure flag when behind HTTPS (Railway yes, localhost no)
        is_secure = request.url.scheme == "https"

        # Skip validation for safe methods
        if request.method in SAFE_METHODS:
            response = await call_next(request)
            response.set_cookie(
                CSRF_COOKIE_NAME,
                csrf_cookie,
                httponly=False,  # JS needs to read this for HTMX
                samesite="lax",
                secure=is_secure,
                max_age=86400,
            )
            return response

        # Skip CSRF for API key authenticated requests (they don't use cookies)
        if "x-api-key" in request.headers:
            return await call_next(request)

        # Skip CSRF for Stripe webhooks (they use signature verification)
        if request.url.path.endswith("/webhook") and "stripe-signature" in request.headers:
            return await call_next(request)

        # Skip CSRF for JSON API requests (they use Authorization header, not cookies)
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type and request.url.path.startswith("/api/"):
            return await call_next(request)

        # Validate CSRF token for all other POST/PUT/DELETE requests
        # Check header first (HTMX), then form field (regular forms)
        submitted_token = request.headers.get(CSRF_HEADER_NAME) or (
            await _get_form_token(request)
        )

        if not submitted_token or not hmac.compare_digest(
            submitted_token, csrf_cookie
        ):
            return JSONResponse(
                {"detail": "CSRF validation failed"},
                status_code=403,
            )

        response = await call_next(request)
        response.set_cookie(
            CSRF_COOKIE_NAME,
            csrf_cookie,
            httponly=False,
            samesite="lax",
            secure=is_secure,
            max_age=86400,
        )
        return response


async def _get_form_token(request: Request) -> str | None:
    """Extract CSRF token from form data without consuming the body."""
    content_type = request.headers.get("content-type", "")
    if (
        "application/x-www-form-urlencoded" in content_type
        or "multipart/form-data" in content_type
    ):
        try:
            form = await request.form()
            return form.get(CSRF_FORM_FIELD)
        except Exception:
            return None
    return None
