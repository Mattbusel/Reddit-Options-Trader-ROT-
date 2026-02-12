from __future__ import annotations

import calendar
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from html import unescape
from typing import List

import feedparser

from rot.core.types import Post, ThreadSnapshot
from rot.ingest.seen_store import SeenStore

log = logging.getLogger(__name__)

# Regex to strip HTML tags from RSS description/content
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str | None) -> str:
    """Remove HTML tags and unescape entities."""
    if not raw:
        return ""
    text = _HTML_TAG_RE.sub("", raw)
    return unescape(text).strip()


def _item_id(entry: dict, feed_url: str) -> str:
    """Deterministic ID from GUID, link, or title hash."""
    guid = entry.get("id") or entry.get("link") or ""
    if guid:
        return hashlib.sha256(guid.encode()).hexdigest()[:16]
    # Fallback: hash title + feed URL
    raw = (entry.get("title", "") + feed_url).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _parse_published(entry: dict) -> int:
    """Extract published timestamp as epoch int."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return int(calendar.timegm(parsed))
            except Exception:
                pass
    return int(time.time())


@dataclass
class RSSFeedConfig:
    """Configuration for a single RSS feed."""

    url: str
    label: str
    poll_interval_s: int = 300


class RSSIngestor:
    """Polls multiple RSS/Atom feeds and produces ThreadSnapshot objects.

    Each RSS item maps to a Post:
      - id: "rss_" + sha256(guid)[:16] (prefixed to avoid Reddit ID collision)
      - subreddit: feed label (e.g. "reuters-markets")
      - title: entry title
      - selftext: HTML-stripped description/content (truncated to 2000 chars)
      - score: 0, num_comments: 0 (RSS has no engagement metrics)
      - permalink: entry link
      - flair: "rss" (used by TrendEngine for RSS bypass detection)
      - author: entry author or feed title

    Deduplication: reuses SeenStore. Since RSS items have static score=0 and
    num_comments=0, is_changed() returns True only on first encounter, giving
    exact-once semantics with zero changes to SeenStore.

    Per-feed throttling: each feed has its own ``poll_interval_s``.
    On every ``poll()`` call, feeds whose interval has not elapsed are
    silently skipped — no network request, no log spam.
    """

    def __init__(
        self,
        feeds: List[RSSFeedConfig],
        state_path: str = "storage/seen_rss.json",
        max_age_s: int = 2 * 24 * 3600,
        max_entries_per_feed: int = 50,
    ) -> None:
        self.feeds = feeds
        self.max_entries_per_feed = max_entries_per_feed
        self.seen = SeenStore(path=state_path, max_age_s=max_age_s)
        self._last_poll: dict[str, float] = {}  # label → epoch of last poll

    def poll(self) -> List[ThreadSnapshot]:
        now = int(time.time())
        snaps: List[ThreadSnapshot] = []

        self.seen.load()

        for feed_cfg in self.feeds:
            # Per-feed throttle: skip if interval hasn't elapsed
            last = self._last_poll.get(feed_cfg.label, 0.0)
            if (now - last) < feed_cfg.poll_interval_s:
                continue
            self._last_poll[feed_cfg.label] = now

            try:
                parsed = feedparser.parse(feed_cfg.url)
            except Exception as e:
                log.warning("RSS feed parse error (%s): %s", feed_cfg.label, e)
                continue

            # Log feed status for debugging
            status = getattr(parsed, "status", None)
            bozo = getattr(parsed, "bozo", False)
            n_entries = len(parsed.entries) if parsed.entries else 0

            # Skip feeds returning HTTP errors (dead feeds)
            if isinstance(status, int) and status in (403, 404, 410):
                log.warning(
                    "RSS feed %s returned HTTP %d — skipping (url=%s)",
                    feed_cfg.label, status, feed_cfg.url,
                )
                continue
            if isinstance(status, int) and status >= 500:
                log.warning(
                    "RSS feed %s returned HTTP %d — server error, skipping",
                    feed_cfg.label, status,
                )
                continue

            if bozo:
                bozo_exc = getattr(parsed, "bozo_exception", "unknown")
                log.warning(
                    "RSS feed %s: bozo=%s status=%s entries=%d exc=%s",
                    feed_cfg.label, bozo, status, n_entries, bozo_exc,
                )
            else:
                log.info(
                    "RSS feed %s: status=%s entries=%d",
                    feed_cfg.label, status, n_entries,
                )

            if n_entries == 0:
                log.warning("RSS feed %s returned 0 entries (url=%s)", feed_cfg.label, feed_cfg.url)
                continue

            feed_title = getattr(parsed.feed, "title", feed_cfg.label) or feed_cfg.label

            # Cap entries per feed to prevent bloat (e.g. DoD returns 500+)
            entries = parsed.entries[:self.max_entries_per_feed]

            for entry in entries:
                item_id = f"rss_{_item_id(entry, feed_cfg.url)}"

                # Dedup: RSS score/comments never change, so is_changed
                # returns True only for genuinely new items
                if not self.seen.is_changed(item_id, 0, 0):
                    continue

                published = _parse_published(entry)

                # Extract and clean content
                title = (entry.get("title") or "").strip()
                raw_body = entry.get("summary", "") or entry.get("description", "")
                # Some feeds put richer content in content[0].value
                if hasattr(entry, "content") and entry.content:
                    raw_body = entry.content[0].get("value", raw_body)
                selftext = _strip_html(raw_body)

                link = entry.get("link", "")
                author = entry.get("author") or feed_title

                post = Post(
                    id=item_id,
                    created_utc=published,
                    subreddit=feed_cfg.label,
                    title=title,
                    selftext=selftext[:2000],
                    url=link,
                    score=0,
                    num_comments=0,
                    upvote_ratio=None,
                    author=author,
                    permalink=link,
                    flair="rss",
                    is_crosspost=False,
                )

                snaps.append(ThreadSnapshot(snapshot_ts=now, post=post))
                self.seen.update(item_id, 0, 0, now)

        self.seen.save()
        log.info("RSS poll complete: %d new items from %d feeds", len(snaps), len(self.feeds))
        return snaps
