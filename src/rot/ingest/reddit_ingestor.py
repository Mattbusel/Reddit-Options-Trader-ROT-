from __future__ import annotations

import time
from typing import List

from rot.core.types import Post, ThreadSnapshot


class RedditIngestor:
    """
    V1 demo ingestor: emits two snapshots so trend detection triggers immediately.
    Replace with real Reddit API ingestion later.
    """

    def __init__(self, subreddits: List[str], listing: str = "rising") -> None:
        self.subreddits = subreddits
        self.listing = listing

    def poll(self) -> List[ThreadSnapshot]:
        now = int(time.time())

        p1 = Post(
            id="demo1",
            created_utc=now - 240,
            subreddit="wallstreetbets",
            title="TSLA is moving 👀",
            selftext="Any thoughts on next week options?",
            url="",
            score=90,
            num_comments=20,
            upvote_ratio=0.92,
            author="demo_user",
            permalink="https://reddit.com/r/wallstreetbets/demo1",
        )
        p2 = Post(
            id="demo1",
            created_utc=now - 120,
            subreddit="wallstreetbets",
            title="TSLA is moving 👀",
            selftext="Any thoughts on next week options?",
            url="",
            score=110,
            num_comments=30,
            upvote_ratio=0.93,
            author="demo_user",
            permalink="https://reddit.com/r/wallstreetbets/demo1",
        )

        return [
            ThreadSnapshot(snapshot_ts=now - 60, post=p1),
            ThreadSnapshot(snapshot_ts=now, post=p2),
        ]
