"""Request context tracking for distributed tracing.

Provides request ID tracking across the entire pipeline:
- Auto-generates unique request IDs for each HTTP request
- Propagates request IDs through async context
- Includes request IDs in all log messages
- Supports distributed tracing across services
- Thread-safe and async-safe implementation

Usage:
    # In middleware (automatic)
    request_id = generate_request_id()
    set_request_id(request_id)

    # In application code
    current_id = get_request_id()
    log.info("Processing", extra=get_log_context())
"""
from __future__ import annotations

import contextvars
import logging
import uuid
from typing import Any, Dict, Optional

# Context variable for request ID (async-safe, thread-local)
_request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)

# Context variable for user ID
_user_id_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "user_id", default=None
)

# Context variable for correlation ID (for tracing across services)
_correlation_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)


def generate_request_id() -> str:
    """Generate a unique request ID.

    Uses UUID4 for globally unique identifiers.
    Format: req_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

    Returns:
        Unique request ID string
    """
    return f"req_{uuid.uuid4()}"


def set_request_id(request_id: str) -> None:
    """Set the current request ID in context.

    Args:
        request_id: Request ID to set
    """
    _request_id_var.set(request_id)


def get_request_id() -> Optional[str]:
    """Get the current request ID from context.

    Returns:
        Current request ID or None if not set
    """
    return _request_id_var.get()


def set_user_id(user_id: int) -> None:
    """Set the current user ID in context.

    Args:
        user_id: User ID to set
    """
    _user_id_var.set(user_id)


def get_user_id() -> Optional[int]:
    """Get the current user ID from context.

    Returns:
        Current user ID or None if not set
    """
    return _user_id_var.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID for distributed tracing.

    Args:
        correlation_id: Correlation ID to set (from upstream service)
    """
    _correlation_id_var.set(correlation_id)


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID.

    Returns:
        Current correlation ID or None if not set
    """
    return _correlation_id_var.get()


def clear_context() -> None:
    """Clear all context variables.

    Should be called after request processing completes.
    """
    _request_id_var.set(None)
    _user_id_var.set(None)
    _correlation_id_var.set(None)


def get_log_context() -> Dict[str, Any]:
    """Get context dict for logging.

    Returns dict with all context variables for structured logging.
    Use with logging.info("message", extra=get_log_context())

    Returns:
        Dict with request_id, user_id, correlation_id
    """
    context: Dict[str, Any] = {}

    request_id = get_request_id()
    if request_id:
        context["request_id"] = request_id

    user_id = get_user_id()
    if user_id:
        context["user_id"] = user_id

    correlation_id = get_correlation_id()
    if correlation_id:
        context["correlation_id"] = correlation_id

    return context


class RequestContextFilter(logging.Filter):
    """Logging filter to add request context to all log records.

    Automatically adds request_id, user_id, correlation_id to log records.

    Usage:
        import logging
        handler = logging.StreamHandler()
        handler.addFilter(RequestContextFilter())
        logger.addHandler(handler)
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add context variables to log record.

        Args:
            record: Log record to enhance

        Returns:
            Always True (don't filter out any records)
        """
        # Add request ID
        request_id = get_request_id()
        record.request_id = request_id if request_id else "-"

        # Add user ID
        user_id = get_user_id()
        record.user_id = user_id if user_id is not None else "-"

        # Add correlation ID
        correlation_id = get_correlation_id()
        record.correlation_id = correlation_id if correlation_id else "-"

        return True


def configure_request_logging() -> None:
    """Configure all loggers to include request context.

    Adds RequestContextFilter to all existing handlers.
    Should be called during application startup.
    """
    # Get root logger
    root_logger = logging.getLogger()

    # Add filter to all handlers
    for handler in root_logger.handlers:
        if not any(isinstance(f, RequestContextFilter) for f in handler.filters):
            handler.addFilter(RequestContextFilter())

    # Also update the logging format to include request context
    # This should be done in the logging configuration
    # Example format: "%(asctime)s [%(request_id)s] [%(user_id)s] %(name)s - %(levelname)s - %(message)s"


# Context manager for scoped request context
class RequestContext:
    """Context manager for request context.

    Usage:
        with RequestContext(request_id="req_123", user_id=42):
            # All logs here will include request_id and user_id
            log.info("Processing request")
    """

    def __init__(
        self,
        request_id: Optional[str] = None,
        user_id: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ):
        """Initialize request context.

        Args:
            request_id: Request ID (auto-generated if None)
            user_id: User ID
            correlation_id: Correlation ID for distributed tracing
        """
        self.request_id = request_id or generate_request_id()
        self.user_id = user_id
        self.correlation_id = correlation_id

        # Store previous values for restoration
        self._prev_request_id: Optional[str] = None
        self._prev_user_id: Optional[int] = None
        self._prev_correlation_id: Optional[str] = None

    def __enter__(self) -> "RequestContext":
        """Enter context - set context variables."""
        # Save previous values
        self._prev_request_id = get_request_id()
        self._prev_user_id = get_user_id()
        self._prev_correlation_id = get_correlation_id()

        # Set new values
        set_request_id(self.request_id)
        if self.user_id is not None:
            set_user_id(self.user_id)
        if self.correlation_id:
            set_correlation_id(self.correlation_id)

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context - restore previous values."""
        # Restore previous values
        if self._prev_request_id:
            set_request_id(self._prev_request_id)
        else:
            _request_id_var.set(None)

        if self._prev_user_id is not None:
            set_user_id(self._prev_user_id)
        else:
            _user_id_var.set(None)

        if self._prev_correlation_id:
            set_correlation_id(self._prev_correlation_id)
        else:
            _correlation_id_var.set(None)
