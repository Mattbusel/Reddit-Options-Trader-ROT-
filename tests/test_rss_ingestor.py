from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from rot.core.types import Post, ThreadSnapshot
from rot.ingest.rss_ingestor import (
    RSSIngestor,
    RSSFeedConfig,
    _strip_html,
    _item_id,
    _parse_published,
)


class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_unescapes_entities(self):
        assert _strip_html("AT&amp;T &lt;rocks&gt;") == "AT&T <rocks>"

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_none_input(self):
        assert _strip_html(None) == ""

    def test_plain_text_passthrough(self):
        assert _strip_html("no html here") == "no html here"


class TestItemId:
    def test_uses_guid(self):
        entry = {"id": "https://example.com/article/123"}
        result = _item_id(entry, "https://feed.example.com")
        assert len(result) == 16
        assert result.isalnum()

    def test_uses_link_fallback(self):
        entry = {"link": "https://example.com/article/456"}
        result = _item_id(entry, "https://feed.example.com")
        assert len(result) == 16

    def test_uses_title_hash_last_resort(self):
        entry = {"title": "Breaking News"}
        result = _item_id(entry, "https://feed.example.com")
        assert len(result) == 16

    def test_deterministic(self):
        entry = {"id": "guid-1"}
        assert _item_id(entry, "feed") == _item_id(entry, "feed")

    def test_different_guids_different_ids(self):
        e1 = {"id": "guid-1"}
        e2 = {"id": "guid-2"}
        assert _item_id(e1, "feed") != _item_id(e2, "feed")


class TestParsePublished:
    def test_with_published_parsed(self):
        entry = {"published_parsed": time.gmtime(1700000000)}
        result = _parse_published(entry)
        assert result == 1700000000

    def test_fallback_to_current_time(self):
        entry = {}
        result = _parse_published(entry)
        assert abs(result - int(time.time())) < 5


class TestRSSIngestor:
    def _make_feed_result(self, entries):
        """Build a mock feedparser result."""
        feed = MagicMock()
        feed.title = "Test Feed"
        result = MagicMock()
        result.feed = feed
        result.entries = entries
        return result

    def _make_entry(
        self,
        title="Test Article",
        guid="guid-1",
        link="https://example.com/1",
        summary="<p>Body text</p>",
        published_parsed=None,
    ):
        entry = {
            "id": guid,
            "title": title,
            "link": link,
            "summary": summary,
            "author": "Test Author",
            "published_parsed": published_parsed or time.gmtime(),
        }
        return entry

    @patch("rot.ingest.rss_ingestor.feedparser.parse")
    def test_basic_poll(self, mock_parse, tmp_path):
        entry = self._make_entry()
        mock_parse.return_value = self._make_feed_result([entry])

        ingestor = RSSIngestor(
            feeds=[RSSFeedConfig(url="https://feed.example.com", label="test-feed")],
            state_path=str(tmp_path / "seen.json"),
        )
        snaps = ingestor.poll()

        assert len(snaps) == 1
        assert isinstance(snaps[0], ThreadSnapshot)
        assert snaps[0].post.subreddit == "test-feed"
        assert snaps[0].post.flair == "rss"
        assert snaps[0].post.score == 0
        assert snaps[0].post.num_comments == 0
        assert snaps[0].post.selftext == "Body text"  # HTML stripped

    @patch("rot.ingest.rss_ingestor.feedparser.parse")
    def test_dedup_on_second_poll(self, mock_parse, tmp_path):
        entry = self._make_entry()
        mock_parse.return_value = self._make_feed_result([entry])

        ingestor = RSSIngestor(
            feeds=[RSSFeedConfig(url="https://feed.example.com", label="test-feed")],
            state_path=str(tmp_path / "seen.json"),
        )

        snaps1 = ingestor.poll()
        assert len(snaps1) == 1

        # Second poll with same item: should be deduped
        snaps2 = ingestor.poll()
        assert len(snaps2) == 0

    @patch("rot.ingest.rss_ingestor.feedparser.parse")
    def test_multiple_feeds(self, mock_parse, tmp_path):
        entry1 = self._make_entry(title="Article 1", guid="g1")
        entry2 = self._make_entry(title="Article 2", guid="g2")

        mock_parse.side_effect = [
            self._make_feed_result([entry1]),
            self._make_feed_result([entry2]),
        ]

        ingestor = RSSIngestor(
            feeds=[
                RSSFeedConfig(url="https://feed1.example.com", label="feed-1"),
                RSSFeedConfig(url="https://feed2.example.com", label="feed-2"),
            ],
            state_path=str(tmp_path / "seen.json"),
        )
        snaps = ingestor.poll()
        assert len(snaps) == 2
        labels = {s.post.subreddit for s in snaps}
        assert labels == {"feed-1", "feed-2"}

    @patch("rot.ingest.rss_ingestor.feedparser.parse")
    def test_id_prefix(self, mock_parse, tmp_path):
        entry = self._make_entry()
        mock_parse.return_value = self._make_feed_result([entry])

        ingestor = RSSIngestor(
            feeds=[RSSFeedConfig(url="https://feed.example.com", label="test")],
            state_path=str(tmp_path / "seen.json"),
        )
        snaps = ingestor.poll()
        assert snaps[0].post.id.startswith("rss_")

    @patch("rot.ingest.rss_ingestor.feedparser.parse")
    def test_feed_parse_failure_skipped(self, mock_parse, tmp_path):
        mock_parse.side_effect = Exception("Network error")

        ingestor = RSSIngestor(
            feeds=[RSSFeedConfig(url="https://broken.example.com", label="broken")],
            state_path=str(tmp_path / "seen.json"),
        )
        snaps = ingestor.poll()
        assert len(snaps) == 0  # Graceful failure

    @patch("rot.ingest.rss_ingestor.feedparser.parse")
    def test_author_uses_entry_author(self, mock_parse, tmp_path):
        entry = self._make_entry()
        entry["author"] = "John Doe"
        mock_parse.return_value = self._make_feed_result([entry])

        ingestor = RSSIngestor(
            feeds=[RSSFeedConfig(url="https://feed.example.com", label="test")],
            state_path=str(tmp_path / "seen.json"),
        )
        snaps = ingestor.poll()
        assert snaps[0].post.author == "John Doe"

    @patch("rot.ingest.rss_ingestor.feedparser.parse")
    def test_selftext_truncated(self, mock_parse, tmp_path):
        long_body = "<p>" + "x" * 3000 + "</p>"
        entry = self._make_entry(summary=long_body)
        mock_parse.return_value = self._make_feed_result([entry])

        ingestor = RSSIngestor(
            feeds=[RSSFeedConfig(url="https://feed.example.com", label="test")],
            state_path=str(tmp_path / "seen.json"),
        )
        snaps = ingestor.poll()
        assert len(snaps[0].post.selftext) <= 2000
