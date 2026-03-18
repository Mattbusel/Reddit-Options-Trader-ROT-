from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class SeenRecord:
    """Snapshot of a Reddit post's engagement metrics at a point in time."""

    score: int
    num_comments: int
    last_seen_ts: int


class SeenStore:
    """Persistent store tracking which Reddit posts have already been processed.

    Persists engagement snapshots to disk so the deduplication state survives
    process restarts. Entries older than ``max_age_s`` are evicted periodically
    and the in-memory store is capped at ``MAX_SIZE`` entries.
    """

    EVICT_INTERVAL = 300  # evict at most every 5 minutes during runtime
    MAX_SIZE = 5000  # cap entries to prevent unbounded memory growth

    def __init__(self, path: str = "storage/seen_posts.json", max_age_s: int = 2 * 24 * 3600) -> None:
        self.path = Path(path)
        self.max_age_s = max_age_s
        self._data: Dict[str, SeenRecord] = {}
        self._loaded = False
        self._last_evict_ts = 0

    def load(self) -> None:
        """Load persisted records from disk. Idempotent; subsequent calls are no-ops."""
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for k, v in raw.items():
                self._data[k] = SeenRecord(
                    score=int(v.get("score", 0)),
                    num_comments=int(v.get("num_comments", 0)),
                    last_seen_ts=int(v.get("last_seen_ts", 0)),
                )
        except Exception:
            self._data = {}

    def _evict_old(self) -> None:
        cutoff = int(time.time()) - self.max_age_s
        to_remove = [k for k, r in self._data.items() if r.last_seen_ts < cutoff]
        for k in to_remove:
            del self._data[k]
        # Cap size: keep most recent entries
        if len(self._data) > self.MAX_SIZE:
            sorted_keys = sorted(self._data, key=lambda k: self._data[k].last_seen_ts)
            for k in sorted_keys[: len(self._data) - self.MAX_SIZE]:
                del self._data[k]

    def save(self) -> None:
        """Evict stale entries and flush the current state to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._evict_old()
        raw = {
            k: {"score": r.score, "num_comments": r.num_comments, "last_seen_ts": r.last_seen_ts}
            for k, r in self._data.items()
        }
        self.path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    def get(self, post_id: str) -> Optional[SeenRecord]:
        """Return the stored record for *post_id*, or ``None`` if unseen."""
        self.load()
        return self._data.get(post_id)

    def update(self, post_id: str, score: int, num_comments: int, ts: int) -> None:
        """Upsert a post record and periodically evict stale entries."""
        self.load()
        self._data[post_id] = SeenRecord(score=int(score), num_comments=int(num_comments), last_seen_ts=int(ts))
        now = int(time.time())
        if now - self._last_evict_ts >= self.EVICT_INTERVAL:
            self._evict_old()
            self._last_evict_ts = now

    def is_changed(self, post_id: str, score: int, num_comments: int) -> bool:
        """Return ``True`` if *post_id* is unseen or its engagement metrics have changed."""
        rec = self.get(post_id)
        if rec is None:
            return True
        return int(score) != rec.score or int(num_comments) != rec.num_comments
