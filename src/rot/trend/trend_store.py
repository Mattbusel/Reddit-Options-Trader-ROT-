from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from rot.core.types import ThreadSnapshot, Post


class TrendStore:
    def __init__(self, path: str = "storage/trend_state.json", max_age_s: int = 3600) -> None:
        self.path = Path(path)
        self.max_age_s = max_age_s
        self._last: Dict[str, ThreadSnapshot] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            cutoff = int(time.time()) - self.max_age_s
            for key, entry in raw.items():
                if entry.get("snapshot_ts", 0) < cutoff:
                    continue
                post_data = entry.get("post", {})
                post = Post(
                    id=post_data.get("id", ""),
                    created_utc=post_data.get("created_utc", 0),
                    subreddit=post_data.get("subreddit", ""),
                    title=post_data.get("title", ""),
                    selftext=post_data.get("selftext", ""),
                    url=post_data.get("url", ""),
                    score=post_data.get("score", 0),
                    num_comments=post_data.get("num_comments", 0),
                    upvote_ratio=post_data.get("upvote_ratio"),
                    author=post_data.get("author", ""),
                    permalink=post_data.get("permalink", ""),
                    flair=post_data.get("flair"),
                    is_crosspost=post_data.get("is_crosspost", False),
                )
                self._last[key] = ThreadSnapshot(
                    snapshot_ts=entry.get("snapshot_ts", 0),
                    post=post,
                )
        except Exception:
            self._last = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cutoff = int(time.time()) - self.max_age_s
        raw: Dict[str, Any] = {}
        for key, snap in self._last.items():
            if snap.snapshot_ts < cutoff:
                continue
            raw[key] = {
                "snapshot_ts": snap.snapshot_ts,
                "post": {
                    "id": snap.post.id,
                    "created_utc": snap.post.created_utc,
                    "subreddit": snap.post.subreddit,
                    "title": snap.post.title,
                    "selftext": snap.post.selftext,
                    "url": snap.post.url,
                    "score": snap.post.score,
                    "num_comments": snap.post.num_comments,
                    "upvote_ratio": snap.post.upvote_ratio,
                    "author": snap.post.author,
                    "permalink": snap.post.permalink,
                    "flair": snap.post.flair,
                    "is_crosspost": snap.post.is_crosspost,
                },
            }
        try:
            self.path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _evict_old(self) -> None:
        cutoff = int(time.time()) - self.max_age_s
        to_remove = [k for k, s in self._last.items() if s.snapshot_ts < cutoff]
        for k in to_remove:
            del self._last[k]

    def update(self, key: str, snap: ThreadSnapshot) -> Optional[ThreadSnapshot]:
        prev = self._last.get(key)
        self._last[key] = snap
        # Periodically prune in-memory entries (piggyback on updates)
        if len(self._last) % 100 == 0:
            self._evict_old()
        return prev
