"""Error tracking and monitoring.

Provides structured error logging and metrics for production monitoring.
Can be upgraded to Sentry/Datadog integration in the future.

Features:
- Structured error logging with context
- Error rate tracking
- Automatic error aggregation
- Stack trace capture
- Request context integration
"""
from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import defaultdict

log = logging.getLogger(__name__)

# Error storage directory — defer mkdir to ErrorTracker.__init__ so module
# import never fails in environments where the path does not yet exist.
ERROR_LOG_DIR = Path(os.environ.get("ROT_ERROR_LOG_DIR", "/app/data/errors"))


class ErrorTracker:
    """Track and aggregate errors for monitoring.

    Writes errors to rotating JSON logs for analysis.
    Can be extended to integrate with Sentry/Datadog.
    """

    def __init__(self, log_dir: Path = ERROR_LOG_DIR):
        """Initialize error tracker.

        Args:
            log_dir: Directory to store error logs
        """
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # In-memory error rate tracking
        self._error_counts: Dict[str, int] = defaultdict(int)
        self._last_reset = datetime.utcnow()

    def capture_exception(
        self,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None,
        level: str = "error",
        tags: Optional[Dict[str, str]] = None,
    ) -> str:
        """Capture an exception with context.

        Args:
            exception: The exception to capture
            context: Additional context (user_id, request_id, etc.)
            level: Error level (error, warning, critical)
            tags: Tags for categorization (endpoint, module, etc.)

        Returns:
            Error ID for reference
        """
        from rot.core.request_context import get_request_id, get_user_id

        # Generate error ID
        error_id = f"err_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"

        # Build error data
        error_data = {
            "error_id": error_id,
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "type": type(exception).__name__,
            "message": str(exception),
            "stack_trace": traceback.format_exc(),
            "context": context or {},
            "tags": tags or {},
            "request_id": get_request_id(),
            "user_id": get_user_id(),
        }

        # Write to daily log file
        log_file = self._get_log_file()
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(error_data) + "\n")
        except Exception as write_err:
            log.error(f"Failed to write error log: {write_err}")

        # Update error rate tracking
        error_type = type(exception).__name__
        self._error_counts[error_type] += 1

        # Log to standard logger
        log_message = f"[{error_id}] {type(exception).__name__}: {exception}"
        if level == "critical":
            log.critical(log_message, exc_info=True)
        elif level == "warning":
            log.warning(log_message, exc_info=True)
        else:
            log.error(log_message, exc_info=True)

        return error_id

    def capture_message(
        self,
        message: str,
        level: str = "info",
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> str:
        """Capture a message event (non-exception).

        Args:
            message: The message to capture
            level: Log level (info, warning, error)
            context: Additional context
            tags: Tags for categorization

        Returns:
            Event ID for reference
        """
        from rot.core.request_context import get_request_id, get_user_id

        event_id = f"msg_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"

        event_data = {
            "event_id": event_id,
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            "context": context or {},
            "tags": tags or {},
            "request_id": get_request_id(),
            "user_id": get_user_id(),
        }

        log_file = self._get_log_file()
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event_data) + "\n")
        except Exception as write_err:
            log.error(f"Failed to write event log: {write_err}")

        return event_id

    def get_error_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get error statistics for the last N hours.

        Args:
            hours: Number of hours to analyze

        Returns:
            Dict with error counts by type, level, endpoint
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        stats: Dict[str, Any] = {
            "total_errors": 0,
            "by_type": defaultdict(int),
            "by_level": defaultdict(int),
            "by_endpoint": defaultdict(int),
            "recent_errors": [],
        }

        # Read errors from log files
        for log_file in self._get_recent_log_files(hours):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            error_data = json.loads(line.strip())
                            error_time = datetime.fromisoformat(error_data["timestamp"])

                            if error_time < cutoff:
                                continue

                            stats["total_errors"] += 1

                            # Aggregate by type
                            error_type = error_data.get("type", error_data.get("message", "Unknown"))
                            stats["by_type"][error_type] += 1

                            # Aggregate by level
                            level = error_data.get("level", "error")
                            stats["by_level"][level] += 1

                            # Aggregate by endpoint (from tags)
                            endpoint = error_data.get("tags", {}).get("endpoint", "unknown")
                            stats["by_endpoint"][endpoint] += 1

                            # Keep last 50 recent errors
                            if len(stats["recent_errors"]) < 50:
                                stats["recent_errors"].append({
                                    "id": error_data.get("error_id", error_data.get("event_id")),
                                    "type": error_type,
                                    "message": error_data.get("message", ""),
                                    "timestamp": error_data["timestamp"],
                                    "request_id": error_data.get("request_id"),
                                })

                        except json.JSONDecodeError:
                            continue

            except FileNotFoundError:
                continue

        # Convert defaultdicts to regular dicts for JSON serialization
        stats["by_type"] = dict(stats["by_type"])
        stats["by_level"] = dict(stats["by_level"])
        stats["by_endpoint"] = dict(stats["by_endpoint"])

        # Sort recent errors by timestamp (newest first)
        stats["recent_errors"].sort(key=lambda x: x["timestamp"], reverse=True)

        return stats

    def get_error_rate(self) -> Dict[str, int]:
        """Get current error rate (since last reset).

        Returns:
            Dict of error counts by type
        """
        # Reset hourly
        if (datetime.utcnow() - self._last_reset).total_seconds() > 3600:
            self._error_counts.clear()
            self._last_reset = datetime.utcnow()

        return dict(self._error_counts)

    def cleanup_old_logs(self, days: int = 30) -> int:
        """Remove error logs older than N days.

        Args:
            days: Keep logs from last N days

        Returns:
            Number of files deleted
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = 0

        for log_file in self.log_dir.glob("errors_*.jsonl"):
            try:
                # Parse date from filename: errors_20260214.jsonl
                date_str = log_file.stem.split("_")[1]
                file_date = datetime.strptime(date_str, "%Y%m%d")

                if file_date < cutoff:
                    log_file.unlink()
                    deleted += 1
                    log.info(f"Deleted old error log: {log_file.name}")

            except (ValueError, IndexError):
                # Skip files with unexpected names
                continue

        return deleted

    def _get_log_file(self) -> Path:
        """Get the current day's log file path.

        Returns:
            Path to today's error log file
        """
        date_str = datetime.utcnow().strftime("%Y%m%d")
        return self.log_dir / f"errors_{date_str}.jsonl"

    def _get_recent_log_files(self, hours: int) -> List[Path]:
        """Get log files that might contain recent errors.

        Args:
            hours: Number of hours to look back

        Returns:
            List of log file paths
        """
        files = []
        current_date = datetime.utcnow()

        # Include today and yesterday (to cover last 24h across date boundary)
        for days_back in range(0, (hours // 24) + 2):
            date = current_date - timedelta(days=days_back)
            date_str = date.strftime("%Y%m%d")
            log_file = self.log_dir / f"errors_{date_str}.jsonl"
            if log_file.exists():
                files.append(log_file)

        return files


# Global error tracker instance
_error_tracker: Optional[ErrorTracker] = None


def get_error_tracker() -> ErrorTracker:
    """Get the global error tracker instance.

    Returns:
        ErrorTracker instance
    """
    global _error_tracker
    if _error_tracker is None:
        _error_tracker = ErrorTracker()
    return _error_tracker


def capture_exception(
    exception: Exception,
    context: Optional[Dict[str, Any]] = None,
    level: str = "error",
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Convenience function to capture an exception.

    Args:
        exception: The exception to capture
        context: Additional context
        level: Error level
        tags: Tags for categorization

    Returns:
        Error ID
    """
    return get_error_tracker().capture_exception(exception, context, level, tags)


def capture_message(
    message: str,
    level: str = "info",
    context: Optional[Dict[str, Any]] = None,
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Convenience function to capture a message.

    Args:
        message: The message to capture
        level: Log level
        context: Additional context
        tags: Tags for categorization

    Returns:
        Event ID
    """
    return get_error_tracker().capture_message(message, level, context, tags)
