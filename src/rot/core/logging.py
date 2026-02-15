from __future__ import annotations

import glob
import json
import logging
import os
import re
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Dict

from rot.core.request_context import configure_request_logging

log = logging.getLogger(__name__)


def sanitize_for_log(value: str) -> str:
    """Sanitize user input for safe logging (prevent log injection attacks).

    Removes or replaces characters that could be used to inject fake log entries:
    - Newlines (\\n, \\r) - could create fake log lines
    - ANSI escape codes - could manipulate terminal output
    - Control characters - could cause parsing issues

    Args:
        value: User-provided string to sanitize

    Returns:
        Sanitized string safe for logging
    """
    if not isinstance(value, str):
        value = str(value)

    # Replace newlines with space to prevent log injection
    value = value.replace('\n', ' ').replace('\r', ' ')

    # Remove ANSI escape codes
    value = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', value)

    # Remove other control characters (except space and printable chars)
    value = ''.join(char if char.isprintable() or char.isspace() else '' for char in value)

    # Truncate if too long (prevent log flooding)
    if len(value) > 500:
        value = value[:497] + '...'

    return value


def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


class JsonlLogger:
    MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB per file
    MAX_BACKUPS = 2  # keep .1 and .2 rotated copies

    def __init__(self, root: str = "storage") -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _rotate_if_needed(self, path: str) -> None:
        try:
            if not os.path.exists(path) or os.path.getsize(path) < self.MAX_FILE_BYTES:
                return
        except OSError:
            return
        # Rotate: .2 is deleted, .1 -> .2, current -> .1
        for i in range(self.MAX_BACKUPS, 0, -1):
            if i == self.MAX_BACKUPS:
                try:
                    os.remove(f"{path}.{i}")
                except OSError:
                    pass  # Intentionally suppressed
            if i > 1:
                prev = f"{path}.{i - 1}"
                dst = f"{path}.{i}"
                try:
                    os.replace(prev, dst)
                except OSError:
                    pass  # Intentionally suppressed
        try:
            os.replace(path, f"{path}.1")
        except OSError:
            pass  # Intentionally suppressed

    def write(self, stream: str, record: Dict[str, Any]) -> None:
        path = os.path.join(self.root, f"{stream}.jsonl")
        self._rotate_if_needed(path)
        record = dict(record)
        record.setdefault("ts", int(time.time()))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(_to_jsonable(record), ensure_ascii=False) + "\n")

    def rotate(self, max_age_days: int = 3) -> Dict[str, int]:
        """Rotate all .jsonl files, keeping only entries from the last N days.

        Also deletes stale .jsonl.N backup files to reclaim volume space.
        Returns dict of {filename: lines_removed}.
        """
        cutoff_ts = int(time.time()) - (max_age_days * 86400)
        results = {}

        # Delete old .jsonl.N backup files — they're rotated copies and waste space
        for backup_path in glob.glob(os.path.join(self.root, "*.jsonl.[0-9]*")):
            try:
                os.remove(backup_path)
                results[os.path.basename(backup_path)] = 1
                log.info("Log rotation: deleted backup %s", os.path.basename(backup_path))
            except OSError:
                pass  # Intentionally suppressed

        for path in glob.glob(os.path.join(self.root, "*.jsonl")):
            fname = os.path.basename(path)
            try:
                kept = []
                removed = 0
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            ts = record.get("ts", 0)
                            if ts >= cutoff_ts:
                                kept.append(line)
                            else:
                                removed += 1
                        except (json.JSONDecodeError, TypeError):
                            removed += 1  # malformed lines get discarded

                if removed > 0:
                    with open(path, "w", encoding="utf-8") as f:
                        for line in kept:
                            f.write(line + "\n")
                    log.info("Log rotation: %s — removed %d old entries, kept %d",
                             fname, removed, len(kept))

                results[fname] = removed
            except Exception as e:
                log.warning("Log rotation failed for %s: %s", fname, e)
                results[fname] = 0

        return results


def cleanup_market_cache(storage_root: str, max_age_days: int = 7) -> int:
    """Evict stale entries from market_cache.json. Returns count evicted."""
    cache_path = os.path.join(storage_root, "market_cache.json")
    if not os.path.isfile(cache_path):
        return 0

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except (json.JSONDecodeError, OSError):
        return 0

    if not isinstance(cache, dict):
        return 0

    cutoff = time.time() - (max_age_days * 86400)
    original_count = len(cache)
    evicted = {k: v for k, v in cache.items()
               if isinstance(v, dict) and v.get("ts", 0) >= cutoff}
    removed = original_count - len(evicted)

    if removed > 0:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(evicted, f)
        log.info("Market cache cleanup: evicted %d stale entries, kept %d",
                 removed, len(evicted))

    return removed


class SanitizingLogFilter(logging.Filter):
    """Log filter that sanitizes log messages to prevent log injection attacks.

    Automatically sanitizes string messages that may contain user input.
    Applied automatically to all loggers in the application.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Sanitize the main log message if it's a string
        if isinstance(record.msg, str):
            record.msg = sanitize_for_log(record.msg)

        # Sanitize any string arguments
        if record.args:
            sanitized_args = []
            for arg in record.args if isinstance(record.args, tuple) else [record.args]:
                if isinstance(arg, str):
                    sanitized_args.append(sanitize_for_log(arg))
                else:
                    sanitized_args.append(arg)
            record.args = tuple(sanitized_args) if isinstance(record.args, tuple) else sanitized_args[0] if sanitized_args else record.args

        return True


# Auto-install sanitizing filter on module import (defense in depth)
def _install_global_log_sanitization():
    """Install log sanitization filter on all existing handlers."""
    root_logger = logging.getLogger()
    sanitizing_filter = SanitizingLogFilter()

    # Add to all existing handlers
    for handler in root_logger.handlers:
        if not any(isinstance(f, SanitizingLogFilter) for f in handler.filters):
            handler.addFilter(sanitizing_filter)

    # Also add to StreamHandler if no handlers exist yet
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(sanitizing_filter)
        root_logger.addHandler(handler)


# Install on module import
_install_global_log_sanitization()


def setup_logging_with_request_context(level: int = logging.INFO) -> None:
    """Configure logging with request context tracking and log injection protection.

    Sets up:
    - Basic logging configuration
    - Request context filter on all handlers
    - Log sanitization filter to prevent log injection
    - Enhanced log format with request_id, user_id

    Args:
        level: Log level (default: INFO)
    """
    # Configure basic logging
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(request_id)s] [user:%(user_id)s] %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Add request context filter and sanitizing filter to all handlers
    configure_request_logging()

    # Add sanitizing filter to all loggers to prevent log injection
    root_logger = logging.getLogger()
    sanitizing_filter = SanitizingLogFilter()
    for handler in root_logger.handlers:
        handler.addFilter(sanitizing_filter)
