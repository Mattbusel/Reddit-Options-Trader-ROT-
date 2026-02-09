from __future__ import annotations

import time

from rot.core.types import Post, ThreadSnapshot
from rot.trend.trend_engine import TrendEngine
from rot.trend.trend_store import TrendStore


def _rss_snap(post_id: str = "rss_abc", age_s: int = 600) -> ThreadSnapshot:
    """Create an RSS-sourced ThreadSnapshot with a given age."""
    now = int(time.time())
    return ThreadSnapshot(
        snapshot_ts=now,
        post=Post(
            id=post_id,
            created_utc=now - age_s,
            subreddit="reuters-markets",
            title="$AAPL beats earnings expectations",
            selftext="Apple reported strong Q4 results.",
            url="https://reuters.com/article/1",
            score=0,
            num_comments=0,
            upvote_ratio=None,
            author="Reuters",
            permalink="https://reuters.com/article/1",
            flair="rss",
        ),
    )


def _reddit_snap(post_id: str = "reddit_1", score: int = 10, comments: int = 5) -> ThreadSnapshot:
    """Create a Reddit-sourced ThreadSnapshot."""
    now = int(time.time())
    return ThreadSnapshot(
        snapshot_ts=now,
        post=Post(
            id=post_id,
            created_utc=now - 200,
            subreddit="wallstreetbets",
            title="$TSLA moon mission",
            selftext="To the moon!",
            url="https://reddit.com/r/wsb/1",
            score=score,
            num_comments=comments,
            upvote_ratio=0.9,
            author="u_trader",
            permalink="https://reddit.com/r/wsb/1",
            flair="DD",
        ),
    )


class TestTrendEngineRSSBypass:
    def test_rss_bypass_creates_candidate(self, tmp_path):
        engine = TrendEngine(
            store=TrendStore(path=str(tmp_path / "trend.json")),
            rss_bypass=True,
            rss_max_age_s=3600,
            rss_synthetic_score=0.5,
        )
        snaps = [_rss_snap(age_s=300)]  # 5 min old
        candidates = engine.detect(snaps)
        assert len(candidates) == 1
        assert candidates[0].reason == "rss_bypass"
        assert candidates[0].trend_score == 0.5

    def test_rss_bypass_respects_freshness(self, tmp_path):
        engine = TrendEngine(
            store=TrendStore(path=str(tmp_path / "trend.json")),
            rss_bypass=True,
            rss_max_age_s=3600,
        )
        # Item is 2 hours old, max_age is 1 hour -> should be filtered
        snaps = [_rss_snap(age_s=7200)]
        candidates = engine.detect(snaps)
        assert len(candidates) == 0

    def test_rss_bypass_disabled_no_candidates(self, tmp_path):
        engine = TrendEngine(
            store=TrendStore(path=str(tmp_path / "trend.json")),
            rss_bypass=False,
        )
        snaps = [_rss_snap()]
        candidates = engine.detect(snaps)
        # Without bypass, RSS items (score=0) never pass rate detection
        assert len(candidates) == 0

    def test_rss_freshness_score_calculated(self, tmp_path):
        engine = TrendEngine(
            store=TrendStore(path=str(tmp_path / "trend.json")),
            rss_bypass=True,
            rss_max_age_s=3600,
            rss_synthetic_score=0.5,
        )
        # 1800s old out of 3600s max = freshness should be ~0.5
        snaps = [_rss_snap(age_s=1800)]
        candidates = engine.detect(snaps)
        assert len(candidates) == 1
        freshness = candidates[0].features["freshness"]
        assert 0.45 <= freshness <= 0.55  # approximately 0.5

    def test_reddit_items_unaffected_by_bypass(self, tmp_path):
        """Ensure bypass only applies to flair='rss' items."""
        engine = TrendEngine(
            store=TrendStore(path=str(tmp_path / "trend.json")),
            rss_bypass=True,
            threshold=0.01,
        )
        # First reddit snapshot (creates baseline in store)
        snap1 = _reddit_snap(score=10, comments=5)
        engine.detect([snap1])

        # Second reddit snapshot with increased engagement
        snap2 = ThreadSnapshot(
            snapshot_ts=snap1.snapshot_ts + 100,
            post=Post(
                id="reddit_1",
                created_utc=snap1.post.created_utc,
                subreddit="wallstreetbets",
                title="$TSLA moon mission",
                selftext="To the moon!",
                url="https://reddit.com/r/wsb/1",
                score=50,
                num_comments=25,
                upvote_ratio=0.9,
                author="u_trader",
                permalink="https://reddit.com/r/wsb/1",
                flair="DD",
            ),
        )
        candidates = engine.detect([snap2])
        # Reddit item should pass through normal rate detection
        assert len(candidates) == 1
        assert candidates[0].reason == "rate_threshold"

    def test_mixed_rss_and_reddit(self, tmp_path):
        """RSS and Reddit items in same batch are handled correctly."""
        engine = TrendEngine(
            store=TrendStore(path=str(tmp_path / "trend.json")),
            rss_bypass=True,
            rss_max_age_s=3600,
            rss_synthetic_score=0.5,
            threshold=0.01,
        )
        rss = _rss_snap(post_id="rss_1", age_s=300)
        reddit = _reddit_snap(post_id="reddit_1")

        candidates = engine.detect([rss, reddit])
        # RSS item should be bypassed, Reddit item is first-seen (no candidate)
        assert len(candidates) == 1
        assert candidates[0].reason == "rss_bypass"
