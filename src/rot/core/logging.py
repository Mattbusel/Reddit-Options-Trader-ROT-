from __future__ import annotations

import glob
import json
import logging
import os
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Dict

from rot.core.request_context import RequestContextFilter, configure_request_logging

log = logging.getLogger(__name__)


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
                    pass
            if i > 1:
                prev = f"{path}.{i - 1}"
                dst = f"{path}.{i}"
                try:
                    os.replace(prev, dst)
                except OSError:
                    pass
        try:
            os.replace(path, f"{path}.1")
        except OSError:
            pass

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
                pass

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


def setup_logging_with_request_context(level: int = logging.INFO) -> None:
    """Configure logging with request context tracking.

    Sets up:
    - Basic logging configuration
    - Request context filter on all handlers
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

    # Add request context filter to all handlers
    configure_request_logging()
