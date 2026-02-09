from __future__ import annotations

from rot.core.types import Post, ThreadSnapshot
from rot.ingest.multi_ingestor import MultiSourceIngestor


def _make_snap(post_id: str, subreddit: str = "test") -> ThreadSnapshot:
    return ThreadSnapshot(
        snapshot_ts=1700000000,
        post=Post(
            id=post_id,
            created_utc=1700000000,
            subreddit=subreddit,
            title="Test title",
            selftext="",
            url="",
            score=0,
            num_comments=0,
            upvote_ratio=None,
            author="author",
            permalink="",
        ),
    )


class FakeIngestor:
    def __init__(self, snapshots):
        self._snaps = snapshots

    def poll(self):
        return self._snaps


class FailingIngestor:
    def poll(self):
        raise RuntimeError("boom")


class TestMultiSourceIngestor:
    def test_combines_sources(self):
        a = FakeIngestor([_make_snap("a1"), _make_snap("a2")])
        b = FakeIngestor([_make_snap("b1")])
        multi = MultiSourceIngestor([a, b])
        snaps = multi.poll()
        assert len(snaps) == 3

    def test_one_failure_doesnt_block_others(self):
        good = FakeIngestor([_make_snap("g1")])
        bad = FailingIngestor()
        multi = MultiSourceIngestor([bad, good])
        snaps = multi.poll()
        assert len(snaps) == 1
        assert snaps[0].post.id == "g1"

    def test_empty_ingestors(self):
        multi = MultiSourceIngestor([FakeIngestor([]), FakeIngestor([])])
        assert multi.poll() == []

    def test_single_ingestor(self):
        single = FakeIngestor([_make_snap("s1")])
        multi = MultiSourceIngestor([single])
        snaps = multi.poll()
        assert len(snaps) == 1

    def test_preserves_source_info(self):
        a = FakeIngestor([_make_snap("a1", subreddit="reddit-wsb")])
        b = FakeIngestor([_make_snap("b1", subreddit="rss-reuters")])
        multi = MultiSourceIngestor([a, b])
        snaps = multi.poll()
        subs = {s.post.subreddit for s in snaps}
        assert subs == {"reddit-wsb", "rss-reuters"}
