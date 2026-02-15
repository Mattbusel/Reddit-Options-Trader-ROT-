"""FastAPI middleware for request ID tracking.

Automatically:
- Generates unique request IDs for each HTTP request
- Propagates request IDs through the application
- Adds X-Request-ID header to responses
- Supports correlation IDs from upstream services
- Integrates with logging for distributed tracing
"""
from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from rot.core.request_context import (
    generate_request_id,
    set_request_id,
    set_user_id,
    set_correlation_id,
    get_request_id,
    clear_context,
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to track request IDs across the application.

    Features:
    - Auto-generates request IDs for incoming requests
    - Accepts X-Request-ID header from clients
    - Accepts X-Correlation-ID for distributed tracing
    - Adds request ID to response headers
    - Sets request context for logging
    - Tracks request timing
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with request ID tracking.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/route handler

        Returns:
            HTTP response with X-Request-ID header
        """
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = generate_request_id()

        # Get correlation ID if present (for distributed tracing)
        correlation_id = request.headers.get("X-Correlation-ID")

        # Set context variables
        set_request_id(request_id)
        if correlation_id:
            set_correlation_id(correlation_id)

        # Extract user ID from request if authenticated
        # (Will be set by auth middleware later, but we can check state)
        if hasattr(request.state, "user") and request.state.user:
            user_id = request.state.user.get("id")
            if user_id:
                set_user_id(user_id)

        # Track request timing
        start_time = time.time()

        try:
            # Process request
            response = await call_next(request)

            # Calculate request duration
            duration_ms = int((time.time() - start_time) * 1000)

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            # Add correlation ID if present
            if correlation_id:
                response.headers["X-Correlation-ID"] = correlation_id

            # Add timing header
            response.headers["X-Response-Time"] = f"{duration_ms}ms"

            return response

        finally:
            # Clear context after request completes
            # This prevents context leakage between requests
            clear_context()


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
