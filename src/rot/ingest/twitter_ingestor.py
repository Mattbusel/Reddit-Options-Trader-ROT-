from __future__ import annotations

import logging
import time
from typing import List

import httpx

from rot.core.types import Post, ThreadSnapshot
from rot.ingest.seen_store import SeenStore

log = logging.getLogger(__name__)

BASE_URL = "https://api.twitter.com/2"


class TwitterIngestor:
    """Poll Twitter/X API v2 for cashtag mentions and specific accounts.

    Requires a Bearer Token (Twitter API v2 Basic access).
    Search endpoint: GET /tweets/search/recent

    Maps tweets to Post objects with:
      - id: "twitter_{tweet_id}"
      - subreddit: "twitter"
      - flair: "twitter"  (used by TrendEngine for bypass detection)
      - score: like_count + retweet_count * 2
      - num_comments: reply_count
    """

    def __init__(
        self,
        bearer_token: str,
        cashtags: List[str],
        accounts: List[str],
        state_path: str = "storage/seen_twitter.json",
        max_results: int = 20,
        max_age_s: int = 7 * 24 * 3600,
    ) -> None:
        self.bearer_token = bearer_token
        self.cashtags = cashtags
        self.accounts = accounts
        self.max_results = min(max_results, 100)  # API max is 100
        self.seen = SeenStore(path=state_path, max_age_s=max_age_s)
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=15.0,
            follow_redirects=True,
        )

    def poll(self) -> List[ThreadSnapshot]:
        now = int(time.time())
        snaps: List[ThreadSnapshot] = []

        self.seen.load()

        # Search cashtags
        for tag in self.cashtags:
            snaps.extend(self._search(f"${tag} -is:retweet", "cashtag", now))

        # Search accounts
        for account in self.accounts:
            snaps.extend(self._search(f"from:{account} -is:retweet", account, now))

        self.seen.save()
        log.info(
            "Twitter poll complete: %d new items (%d cashtags, %d accounts)",
            len(snaps), len(self.cashtags), len(self.accounts),
        )
        return snaps

    def _search(self, query: str, source_label: str, now: int) -> List[ThreadSnapshot]:
        snaps: List[ThreadSnapshot] = []
        try:
            params = {
                "query": query,
                "max_results": self.max_results,
                "tweet.fields": "public_metrics,created_at,author_id",
            }
            resp = self._client.get(f"{BASE_URL}/tweets/search/recent", params=params)
            resp.raise_for_status()
            data = resp.json()

            for tweet in data.get("data", []):
                tweet_id = tweet.get("id")
                if not tweet_id:
                    continue
                post_id = f"twitter_{tweet_id}"

                metrics = tweet.get("public_metrics", {})
                likes = metrics.get("like_count", 0)
                retweets = metrics.get("retweet_count", 0)
                replies = metrics.get("reply_count", 0)
                score = likes + retweets * 2

                if not self.seen.is_changed(post_id, score, replies):
                    continue

                text = tweet.get("text", "")
                created_at = tweet.get("created_at", "")
                author_id = tweet.get("author_id", "unknown")

                post = Post(
                    id=post_id,
                    created_utc=_parse_date(created_at, now),
                    subreddit="twitter",
                    title=text[:200],
                    selftext=text,
                    url=f"https://twitter.com/i/web/status/{tweet_id}",
                    score=score,
                    num_comments=replies,
                    upvote_ratio=None,
                    author=author_id,
                    permalink=f"https://twitter.com/i/web/status/{tweet_id}",
                    flair="twitter",
                    is_crosspost=False,
                )
                snaps.append(ThreadSnapshot(snapshot_ts=now, post=post))
                self.seen.update(post_id, score, replies, now)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                log.warning("Twitter rate limited for query '%s'", query)
            else:
                log.warning("Twitter API error for '%s': %s", query, e)
        except Exception as e:
            log.warning("Twitter fetch error for '%s': %s", query, e)

        return snaps


def _parse_date(date_str: str, fallback: int) -> int:
    """Parse Twitter ISO 8601 date to epoch seconds."""
    if not date_str:
        return fallback
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return fallback
