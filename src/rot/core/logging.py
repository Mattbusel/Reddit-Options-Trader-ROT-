from __future__ import annotations

import glob
import json
import logging
import os
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Dict

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
    def __init__(self, root: str = "storage") -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)

    def write(self, stream: str, record: Dict[str, Any]) -> None:
        path = os.path.join(self.root, f"{stream}.jsonl")
        record = dict(record)
        record.setdefault("ts", int(time.time()))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(_to_jsonable(record), ensure_ascii=False) + "\n")

    def rotate(self, max_age_days: int = 7) -> Dict[str, int]:
        """Rotate all .jsonl files, keeping only entries from the last N days.

        Returns dict of {filename: lines_removed}.
        """
        cutoff_ts = int(time.time()) - (max_age_days * 86400)
        results = {}

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
