from __future__ import annotations

import re
from typing import List

from rot.core.types import Evidence, Event, TrendCandidate

_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")

class EventBuilder:
    def from_candidate(self, c: TrendCandidate) -> List[Event]:
        text = f"{c.snapshot.post.title}\n{c.snapshot.post.selftext}"
        tickers = sorted({t for t in _TICKER_RE.findall(text) if t not in {"I","A","DD"}})
        if not tickers:
            return []

        ev = Event(
            event_type="other",
            entities=tickers[:5],
            stance="unknown",
            time_horizon="unknown",
            evidence=[
                Evidence(
                    post_id=c.snapshot.post.id,
                    permalink=c.snapshot.post.permalink,
                    subreddit=c.snapshot.post.subreddit,
                    excerpt=c.snapshot.post.title[:200],
                )
            ],
            confidence=0.3,
            meta={"trend_score": c.trend_score, "features": c.features},
        )
        return [ev]
