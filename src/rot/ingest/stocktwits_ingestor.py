from __future__ import annotations

import logging
import time
from typing import List

import httpx

from rot.core.retry import retry_with_backoff
from rot.core.types import Post, ThreadSnapshot
from rot.ingest.seen_store import SeenStore

log = logging.getLogger(__name__)

BASE_URL = "https://api.stocktwits.com/api/2"


class StockTwitsIngestor:
    """Poll StockTwits public API for symbol streams and trending tickers.

    Free API (no auth required):
      - Symbol stream: /streams/symbol/{symbol}.json
      - Trending:      /trending/symbols.json

    Maps StockTwits messages to Post objects with:
      - id: "stocktwits_{message_id}"
      - subreddit: "stocktwits"
      - flair: "stocktwits"  (used by TrendEngine for bypass detection)
      - score: likes count
    """

    def __init__(
        self,
        symbols: List[str],
        state_path: str = "storage/seen_stocktwits.json",
        trending_enabled: bool = True,
        max_age_s: int = 7 * 24 * 3600,
    ) -> None:
        self.symbols = symbols
        self.trending_enabled = trending_enabled
        self.seen = SeenStore(path=state_path, max_age_s=max_age_s)
        self._client = httpx.Client(timeout=15.0, follow_redirects=True)

    def poll(self) -> List[ThreadSnapshot]:
        """Fetch the latest StockTwits messages for all configured symbols and return snapshots."""
        now = int(time.time())
        snaps: List[ThreadSnapshot] = []

        self.seen.load()

        # Fetch trending symbols
        if self.trending_enabled:
            snaps.extend(self._poll_trending(now))

        # Fetch per-symbol streams
        for symbol in self.symbols:
            snaps.extend(self._poll_symbol(symbol, now))

        self.seen.save()
        log.info("StockTwits poll complete: %d new items (%d symbols)", len(snaps), len(self.symbols))
        return snaps

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        retryable_exceptions=(httpx.HTTPError, ConnectionError, TimeoutError, OSError),
    )
    def _fetch_trending(self):
        """Fetch trending symbols with retry logic."""
        resp = self._client.get(f"{BASE_URL}/trending/symbols.json")
        resp.raise_for_status()
        return resp.json()

    def _poll_trending(self, now: int) -> List[ThreadSnapshot]:
        snaps: List[ThreadSnapshot] = []
        try:
            data = self._fetch_trending()

            for sym_obj in data.get("symbols", [])[:15]:
                symbol = sym_obj.get("symbol", "")
                if not symbol:
                    continue
                post_id = f"stocktwits_trending_{symbol}_{now // 3600}"
                if not self.seen.is_changed(post_id, 0, 0):
                    continue

                wl_count = sym_obj.get("watchlist_count", 0)
                post = Post(
                    id=post_id,
                    created_utc=now,
                    subreddit="stocktwits",
                    title=f"${symbol} trending on StockTwits (watchlist: {wl_count:,})",
                    selftext=f"${symbol} is currently trending on StockTwits with {wl_count:,} watchers.",
                    url=f"https://stocktwits.com/symbol/{symbol}",
                    score=wl_count,
                    num_comments=0,
                    upvote_ratio=None,
                    author="stocktwits_trending",
                    permalink=f"https://stocktwits.com/symbol/{symbol}",
                    flair="stocktwits",
                    is_crosspost=False,
                )
                snaps.append(ThreadSnapshot(snapshot_ts=now, post=post))
                self.seen.update(post_id, 0, 0, now)

        except Exception as e:
            log.warning("StockTwits trending fetch error: %s", e)

        return snaps

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        retryable_exceptions=(httpx.HTTPError, ConnectionError, TimeoutError, OSError),
    )
    def _fetch_symbol(self, symbol: str):
        """Fetch symbol stream with retry logic."""
        resp = self._client.get(f"{BASE_URL}/streams/symbol/{symbol}.json")
        resp.raise_for_status()
        return resp.json()

    def _poll_symbol(self, symbol: str, now: int) -> List[ThreadSnapshot]:
        snaps: List[ThreadSnapshot] = []
        try:
            data = self._fetch_symbol(symbol)

            for msg in data.get("messages", [])[:20]:
                msg_id = msg.get("id")
                if not msg_id:
                    continue
                post_id = f"stocktwits_{msg_id}"

                likes = 0
                likes_obj = msg.get("likes")
                if isinstance(likes_obj, dict):
                    likes = likes_obj.get("total", 0)
                elif isinstance(likes_obj, int):
                    likes = likes_obj

                if not self.seen.is_changed(post_id, likes, 0):
                    continue

                body = msg.get("body", "")
                user = msg.get("user", {})
                created_at = msg.get("created_at", "")

                # Extract StockTwits native sentiment if available
                sentiment = ""
                entities = msg.get("entities", {})
                if isinstance(entities, dict):
                    st_sentiment = entities.get("sentiment")
                    if isinstance(st_sentiment, dict):
                        sentiment = st_sentiment.get("basic", "")

                selftext = body
                if sentiment:
                    selftext = f"[StockTwits sentiment: {sentiment}] {body}"

                post = Post(
                    id=post_id,
                    created_utc=_parse_date(created_at, now),
                    subreddit="stocktwits",
                    title=body[:200],
                    selftext=selftext,
                    url=f"https://stocktwits.com/{user.get('username', '')}/message/{msg_id}",
                    score=likes,
                    num_comments=0,
                    upvote_ratio=None,
                    author=user.get("username", "unknown"),
                    permalink=f"https://stocktwits.com/{user.get('username', '')}/message/{msg_id}",
                    flair="stocktwits",
                    is_crosspost=False,
                )
                snaps.append(ThreadSnapshot(snapshot_ts=now, post=post))
                self.seen.update(post_id, likes, 0, now)

        except Exception as e:
            log.warning("StockTwits symbol %s fetch error: %s", symbol, e)

        return snaps


def _parse_date(date_str: str, fallback: int) -> int:
    """Parse StockTwits ISO date string to epoch seconds."""
    if not date_str:
        return fallback
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return fallback
