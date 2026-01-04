from __future__ import annotations

from typing import Dict, List

from rot.core.types import ThreadSnapshot, TrendCandidate
from rot.trend.trend_store import TrendStore


class TrendEngine:
    def __init__(self, store: TrendStore, window_s: int = 1800, threshold: float = 0.01) -> None:
        self.store = store
        self.window_s = window_s
        self.threshold = threshold

    def detect(self, snapshots: List[ThreadSnapshot]) -> List[TrendCandidate]:
        out: List[TrendCandidate] = []

        for snap in snapshots:
            key = f"{snap.post.subreddit}:{snap.post.id}"
            prev = self.store.update(key, snap)
            if prev is None:
                continue

            dt = max(1, snap.snapshot_ts - prev.snapshot_ts)
            dscore = snap.post.score - prev.post.score
            dcom = snap.post.num_comments - prev.post.num_comments

            features: Dict[str, float] = {
                "score_rate": dscore / dt,
                "comment_rate": dcom / dt,
            }
            trend_score = features["score_rate"] + 2.0 * features["comment_rate"]

            if trend_score >= self.threshold:
                out.append(
                    TrendCandidate(
                        key=key,
                        window_s=self.window_s,
                        features=features,
                        trend_score=trend_score,
                        reason="rate_threshold",
                        snapshot=snap,
                    )
                )

        return out
