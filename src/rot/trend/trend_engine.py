from __future__ import annotations

import time
from typing import Dict, List

from rot.core.types import ThreadSnapshot, TrendCandidate
from rot.trend.trend_store import TrendStore


class TrendEngine:
    def __init__(
        self,
        store: TrendStore,
        window_s: int = 1800,
        threshold: float = 0.01,
        comment_weight: float = 2.0,
        rss_bypass: bool = False,
        rss_max_age_s: int = 3600,
        rss_synthetic_score: float = 0.5,
    ) -> None:
        self.store = store
        self.window_s = window_s
        self.threshold = threshold
        self.comment_weight = comment_weight
        self.rss_bypass = rss_bypass
        self.rss_max_age_s = rss_max_age_s
        self.rss_synthetic_score = rss_synthetic_score

    def detect(self, snapshots: List[ThreadSnapshot]) -> List[TrendCandidate]:
        out: List[TrendCandidate] = []
        now = int(time.time())

        for snap in snapshots:
            key = f"{snap.post.subreddit}:{snap.post.id}"

            # RSS bypass: promote fresh RSS items directly to candidate.
            # RSS items have static score=0/num_comments=0, so they'd never
            # pass rate-of-change detection. Instead, treat new items within
            # the freshness window as candidates with a synthetic trend score.
            if self.rss_bypass and snap.post.flair == "rss":
                age = now - snap.post.created_utc
                if age <= self.rss_max_age_s:
                    freshness = max(0.0, 1.0 - age / self.rss_max_age_s)
                    out.append(
                        TrendCandidate(
                            key=key,
                            window_s=self.window_s,
                            features={"source": 1.0, "freshness": freshness},
                            trend_score=self.rss_synthetic_score,
                            reason="rss_bypass",
                            snapshot=snap,
                        )
                    )
                # Record in store for logging, but skip rate-of-change logic
                self.store.update(key, snap)
                continue

            # Standard rate-of-change detection (Reddit and other sources)
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
            trend_score = features["score_rate"] + self.comment_weight * features["comment_rate"]

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
