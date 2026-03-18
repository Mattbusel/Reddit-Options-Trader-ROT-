from __future__ import annotations

import os
import time
from typing import List, Optional

import praw

from rot.core.types import Comment, Post, ThreadSnapshot
from rot.ingest.seen_store import SeenStore


class RedditIngestor:
    """PRAW-backed Reddit ingestor with dedupe + persisted seen state.

    Uses env vars:
      ROT_REDDIT_CLIENT_ID
      ROT_REDDIT_CLIENT_SECRET
      ROT_REDDIT_USER_AGENT

    listing: rising | hot | new | top
    """

    def __init__(
        self,
        subreddits: List[str],
        listing: str = "rising",
        limit_per_sub: int = 10,
        include_comments: bool = False,
        top_comments: int = 10,
        state_path: str = "storage/seen_posts.json",
    ) -> None:
        """Initialize the Reddit ingestor.

        Args:
            subreddits: List of subreddit names to monitor (without ``r/`` prefix).
            listing: Feed type — one of ``"rising"``, ``"hot"``, ``"new"``, ``"top"``.
            limit_per_sub: Maximum posts to fetch per subreddit per poll cycle.
            include_comments: Whether to fetch and attach top-level comments.
            top_comments: Number of top comments to include when
                ``include_comments`` is ``True``.
            state_path: Path to the JSON file used to persist seen-post state
                across restarts.

        Raises:
            RuntimeError: If ``ROT_REDDIT_CLIENT_ID``, ``ROT_REDDIT_CLIENT_SECRET``,
                or ``ROT_REDDIT_USER_AGENT`` environment variables are not set.
        """
        self.subreddits = subreddits
        self.listing = listing
        self.limit_per_sub = limit_per_sub
        self.include_comments = include_comments
        self.top_comments = top_comments
        self.seen = SeenStore(path=state_path)

        cid = os.getenv("ROT_REDDIT_CLIENT_ID")
        csec = os.getenv("ROT_REDDIT_CLIENT_SECRET")
        ua = os.getenv("ROT_REDDIT_USER_AGENT")
        if not cid or not csec or not ua:
            raise RuntimeError(
                "Missing Reddit creds. Set ROT_REDDIT_CLIENT_ID, ROT_REDDIT_CLIENT_SECRET, ROT_REDDIT_USER_AGENT"
            )

        self.reddit = praw.Reddit(
            client_id=cid,
            client_secret=csec,
            user_agent=ua,
        )

    def _iter_listing(self, sr: praw.models.Subreddit):
        if self.listing == "rising":
            return sr.rising(limit=self.limit_per_sub)
        if self.listing == "hot":
            return sr.hot(limit=self.limit_per_sub)
        if self.listing == "new":
            return sr.new(limit=self.limit_per_sub)
        if self.listing == "top":
            return sr.top(limit=self.limit_per_sub)
        raise ValueError(f"Unknown listing: {self.listing}")

    def poll(self) -> List[ThreadSnapshot]:
        """Fetch the latest posts from all configured subreddits and return thread snapshots."""
        now = int(time.time())
        snaps: List[ThreadSnapshot] = []

        # Ensure state is loaded
        self.seen.load()

        for name in self.subreddits:
            sr = self.reddit.subreddit(name)
            for sub in self._iter_listing(sr):
                post_id = sub.id
                score = int(getattr(sub, "score", 0))
                num_comments = int(getattr(sub, "num_comments", 0))

                # Dedupe: only emit if new or changed score/comments
                if not self.seen.is_changed(post_id, score, num_comments):
                    continue

                upvote_ratio: Optional[float] = getattr(sub, "upvote_ratio", None)
                author = getattr(sub, "author", None)
                author_name = author.name if author else "[deleted]"

                p = Post(
                    id=post_id,
                    created_utc=int(getattr(sub, "created_utc", now)),
                    subreddit=str(getattr(sub, "subreddit", name)),
                    title=sub.title or "",
                    selftext=getattr(sub, "selftext", "") or "",
                    url=getattr(sub, "url", "") or "",
                    score=score,
                    num_comments=num_comments,
                    upvote_ratio=upvote_ratio,
                    author=author_name,
                    permalink="https://www.reddit.com" + getattr(sub, "permalink", ""),
                    flair=getattr(sub, "link_flair_text", None),
                    is_crosspost=bool(getattr(sub, "crosspost_parent", None)),
                )

                comments: List[Comment] = []
                if self.include_comments:
                    try:
                        sub.comments.replace_more(limit=0)
                        for c in sub.comments[: self.top_comments]:
                            cauthor = getattr(c, "author", None)
                            cauthor_name = cauthor.name if cauthor else "[deleted]"
                            comments.append(
                                Comment(
                                    id=getattr(c, "id", ""),
                                    created_utc=int(getattr(c, "created_utc", now)),
                                    author=cauthor_name,
                                    body=getattr(c, "body", "") or "",
                                    score=int(getattr(c, "score", 0)),
                                )
                            )
                    except Exception:
                        comments = []

                snaps.append(ThreadSnapshot(snapshot_ts=now, post=p, top_comments=comments))

                # Update state as soon as we accept the post
                self.seen.update(post_id, score, num_comments, now)

        # Persist state once per poll
        self.seen.save()
        return snaps
