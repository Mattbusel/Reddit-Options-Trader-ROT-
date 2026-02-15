"""
Comprehensive tests for trend ranker module.

Modules tested:
- rot.trend.ranker

Coverage:
- top_n_candidates with various n values
- Sorting by trend_score (descending)
- Edge cases (empty list, n=0, n > len)
"""
from __future__ import annotations

from rot.core.types import Comment, Post, ThreadSnapshot, TrendCandidate
from rot.trend.ranker import top_n_candidates


def _make_candidate(key: str, score: float) -> TrendCandidate:
    """Helper to create a TrendCandidate with minimal fields."""
    post = Post(
        id="p1",
        created_utc=123,
        subreddit="test",
        title="t",
        selftext="s",
        url="u",
        score=0,
        num_comments=0,
        upvote_ratio=None,
        author="a",
        permalink="p",
    )
    snapshot = ThreadSnapshot(snapshot_ts=123, post=post)
    return TrendCandidate(
        key=key,
        window_s=300,
        features={"volume": 1.0},
        trend_score=score,
        reason="test",
        snapshot=snapshot,
    )


class TestTopNCandidates:
    def test_top_n_basic(self):
        """Returns top n candidates sorted by score."""
        candidates = [
            _make_candidate("A", 0.5),
            _make_candidate("B", 0.9),
            _make_candidate("C", 0.3),
            _make_candidate("D", 0.7),
        ]

        result = top_n_candidates(candidates, n=2)

        assert len(result) == 2
        assert result[0].key == "B"  # 0.9 score
        assert result[1].key == "D"  # 0.7 score

    def test_top_n_sorted_descending(self):
        """Candidates are sorted in descending order by score."""
        candidates = [
            _make_candidate("A", 0.1),
            _make_candidate("B", 0.5),
            _make_candidate("C", 0.9),
            _make_candidate("D", 0.3),
        ]

        result = top_n_candidates(candidates, n=4)

        assert result[0].trend_score == 0.9
        assert result[1].trend_score == 0.5
        assert result[2].trend_score == 0.3
        assert result[3].trend_score == 0.1

    def test_top_n_zero(self):
        """n=0 returns empty list."""
        candidates = [_make_candidate("A", 0.5)]

        result = top_n_candidates(candidates, n=0)

        assert result == []

    def test_top_n_greater_than_length(self):
        """n > len(candidates) returns all candidates."""
        candidates = [
            _make_candidate("A", 0.5),
            _make_candidate("B", 0.3),
        ]

        result = top_n_candidates(candidates, n=10)

        assert len(result) == 2
        assert result[0].key == "A"
        assert result[1].key == "B"

    def test_top_n_empty_list(self):
        """Empty candidates list returns empty list."""
        result = top_n_candidates([], n=5)

        assert result == []

    def test_top_n_default_n(self):
        """Default n=5 is used."""
        candidates = [_make_candidate(f"T{i}", i / 10.0) for i in range(10)]

        result = top_n_candidates(candidates)

        assert len(result) == 5
        # Should be top 5 scores: 0.9, 0.8, 0.7, 0.6, 0.5
        assert result[0].trend_score == 0.9

    def test_top_n_preserves_candidate_data(self):
        """Returned candidates preserve all original data."""
        candidates = [_make_candidate("AAPL", 0.8)]

        result = top_n_candidates(candidates, n=1)

        assert result[0].key == "AAPL"
        assert result[0].trend_score == 0.8
        assert result[0].reason == "test"
        assert result[0].features["volume"] == 1.0

    def test_top_n_equal_scores(self):
        """Equal scores are handled (stable sort)."""
        candidates = [
            _make_candidate("A", 0.5),
            _make_candidate("B", 0.5),
            _make_candidate("C", 0.5),
        ]

        result = top_n_candidates(candidates, n=2)

        assert len(result) == 2
        # All have same score, so first 2 are returned (stable sort)
        assert result[0].trend_score == 0.5
        assert result[1].trend_score == 0.5
