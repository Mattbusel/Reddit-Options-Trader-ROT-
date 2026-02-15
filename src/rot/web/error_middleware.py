"""FastAPI middleware for automatic error tracking.

Automatically captures unhandled exceptions and HTTP errors.
Integrates with error tracking system for monitoring.
"""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from rot.core.error_tracker import capture_exception, capture_message

log = logging.getLogger(__name__)


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically track errors.

    Features:
    - Captures unhandled exceptions
    - Tracks 4xx and 5xx responses
    - Adds error context (endpoint, user, etc.)
    - Returns user-friendly error responses
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with error tracking.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/route handler

        Returns:
            HTTP response
        """
        try:
            response = await call_next(request)

            # Track 4xx and 5xx responses
            if response.status_code >= 400:
                await self._track_http_error(request, response)

            return response

        except Exception as exc:
            # Capture exception with context
            error_id = await self._capture_request_exception(request, exc)

            # Return user-friendly error response
            return await self._create_error_response(exc, error_id)

    async def _track_http_error(self, request: Request, response: Response) -> None:
        """Track HTTP error responses (4xx, 5xx).

        Args:
            request: The HTTP request
            response: The error response
        """
        # Only track server errors (5xx) and some client errors
        if response.status_code < 500 and response.status_code not in (401, 403, 429):
            return

        # Build context
        context = {
            "method": request.method,
            "url": str(request.url),
            "status_code": response.status_code,
        }

        # Get user info if available
        if hasattr(request.state, "user") and request.state.user:
            context["user_id"] = request.state.user.get("id")
            context["user_tier"] = request.state.user.get("tier")

        # Capture message
        level = "error" if response.status_code >= 500 else "warning"
        capture_message(
            f"HTTP {response.status_code}: {request.method} {request.url.path}",
            level=level,
            context=context,
            tags={
                "endpoint": request.url.path,
                "method": request.method,
                "status_code": str(response.status_code),
            },
        )

    async def _capture_request_exception(
        self, request: Request, exc: Exception
    ) -> str:
        """Capture an unhandled exception with request context.

        Args:
            request: The HTTP request
            exc: The exception

        Returns:
            Error ID for reference
        """
        # Build context
        context = {
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
        }

        # Get user info if available
        if hasattr(request.state, "user") and request.state.user:
            context["user_id"] = request.state.user.get("id")
            context["user_email"] = request.state.user.get("email")
            context["user_tier"] = request.state.user.get("tier")

        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        context["client_ip"] = client_ip

        # Capture exception
        error_id = capture_exception(
            exc,
            context=context,
            level="critical",
            tags={
                "endpoint": request.url.path,
                "method": request.method,
            },
        )

        return error_id

    async def _create_error_response(
        self, exc: Exception, error_id: str
    ) -> JSONResponse:
        """Create user-friendly error response.

        Args:
            exc: The exception
            error_id: Error ID for reference

        Returns:
            JSON error response
        """
        # Determine status code
        status_code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Build error response
        error_data = {
            "success": False,
            "error": "Internal server error. Our team has been notified.",
            "error_code": "INTERNAL_ERROR",
            "error_id": error_id,
        }

        # Add specific error message in development
        import os
        if os.getenv("ROT_ENV", "development") == "development":
            error_data["error"] = str(exc)
            error_data["error_type"] = type(exc).__name__

        return JSONResponse(
            status_code=status_code,
            content=error_data,
        )


def get_client_ip(request: Request) -> str:
    """Extract client IP from request.

    Handles X-Forwarded-For header for proxied requests.

    Args:
        request: FastAPI request

    Returns:
        Client IP address
    """
    # Check X-Forwarded-For header (from load balancers/proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs (client, proxy1, proxy2, ...)
        # First IP is the original client
        return forwarded_for.split(",")[0].strip()

    # Check X-Real-IP header (from nginx/other proxies)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fall back to direct connection IP
    if request.client:
        return request.client.host

    return "unknown"
