from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class SeenRecord:
    score: int
    num_comments: int
    last_seen_ts: int


class SeenStore:
    def __init__(self, path: str = "storage/seen_posts.json") -> None:
        self.path = Path(path)
        self._data: Dict[str, SeenRecord] = {}
        self._loaded = False

    def load(self) -> None:
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
            # If state is corrupted, start fresh
            self._data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            k: {"score": r.score, "num_comments": r.num_comments, "last_seen_ts": r.last_seen_ts}
            for k, r in self._data.items()
        }
        self.path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, post_id: str) -> Optional[SeenRecord]:
        self.load()
        return self._data.get(post_id)

    def update(self, post_id: str, score: int, num_comments: int, ts: int) -> None:
        self.load()
        self._data[post_id] = SeenRecord(score=int(score), num_comments=int(num_comments), last_seen_ts=int(ts))

    def is_changed(self, post_id: str, score: int, num_comments: int) -> bool:
        rec = self.get(post_id)
        if rec is None:
            return True
        return int(score) != rec.score or int(num_comments) != rec.num_comments
