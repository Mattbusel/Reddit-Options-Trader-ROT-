"""
Comprehensive tests for ticker ranker module.

Modules tested:
- rot.trend.ticker_ranker

Coverage:
- top_ticker_candidates with SymbolValidator
- Symbol validation and normalization
- Filtering invalid symbols
- Deduplication of symbols
- Limiting symbols per candidate (max 5)
- Sorting by trend_score
- Edge cases (no symbols, invalid symbols, empty candidates)
"""
from __future__ import annotations

from unittest.mock import Mock

from rot.core.types import Post, ThreadSnapshot, TrendCandidate
from rot.trend.ticker_ranker import top_ticker_candidates


def _make_candidate(key: str, score: float) -> TrendCandidate:
    """Helper to create a TrendCandidate."""
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


class TestTopTickerCandidates:
    def test_basic_filtering(self):
        """Valid symbols are included, invalid are filtered."""
        validator = Mock()
        validator.normalize.side_effect = lambda x: x.upper()
        validator.is_valid.side_effect = lambda x: x in ["AAPL", "MSFT"]

        candidates = [
            _make_candidate("tech_trend", 0.8),
        ]
        extracted = {
            "tech_trend": ["aapl", "msft", "invalid"],
        }

        result = top_ticker_candidates(candidates, extracted, validator, n=5)

        assert len(result) == 1
        assert result[0][0].key == "tech_trend"
        assert set(result[0][1]) == {"AAPL", "MSFT"}

    def test_normalization(self):
        """Symbols are normalized before validation."""
        validator = Mock()
        validator.normalize.side_effect = lambda x: x.upper().strip()
        validator.is_valid.side_effect = lambda x: x == "AAPL"

        candidates = [_make_candidate("trend1", 0.7)]
        extracted = {"trend1": ["aapl", " aapl ", "AAPL"]}

        result = top_ticker_candidates(candidates, extracted, validator, n=5)

        assert len(result) == 1
        # Should deduplicate after normalization
        assert result[0][1] == ["AAPL"]

    def test_sorting_by_score(self):
        """Results are sorted by trend_score descending."""
        validator = Mock()
        validator.normalize.side_effect = lambda x: x.upper()
        validator.is_valid.return_value = True

        candidates = [
            _make_candidate("trend1", 0.3),
            _make_candidate("trend2", 0.9),
            _make_candidate("trend3", 0.5),
        ]
        extracted = {
            "trend1": ["A"],
            "trend2": ["B"],
            "trend3": ["C"],
        }

        result = top_ticker_candidates(candidates, extracted, validator, n=3)

        assert len(result) == 3
        assert result[0][0].key == "trend2"  # 0.9
        assert result[1][0].key == "trend3"  # 0.5
        assert result[2][0].key == "trend1"  # 0.3

    def test_limit_n(self):
        """Returns at most n results."""
        validator = Mock()
        validator.normalize.side_effect = lambda x: x.upper()
        validator.is_valid.return_value = True

        candidates = [
            _make_candidate(f"trend{i}", i / 10.0)
            for i in range(10)
        ]
        extracted = {f"trend{i}": [f"SYM{i}"] for i in range(10)}

        result = top_ticker_candidates(candidates, extracted, validator, n=3)

        assert len(result) == 3

    def test_limit_symbols_per_candidate(self):
        """Each candidate gets at most 5 symbols."""
        validator = Mock()
        validator.normalize.side_effect = lambda x: x.upper()
        validator.is_valid.return_value = True

        candidates = [_make_candidate("trend1", 0.8)]
        extracted = {
            "trend1": [f"SYM{i}" for i in range(10)],
        }

        result = top_ticker_candidates(candidates, extracted, validator, n=5)

        assert len(result) == 1
        assert len(result[0][1]) == 5

    def test_no_valid_symbols(self):
        """Candidates with no valid symbols are excluded."""
        validator = Mock()
        validator.normalize.side_effect = lambda x: x.upper()
        validator.is_valid.return_value = False  # All invalid

        candidates = [_make_candidate("trend1", 0.8)]
        extracted = {"trend1": ["invalid1", "invalid2"]}

        result = top_ticker_candidates(candidates, extracted, validator, n=5)

        assert len(result) == 0

    def test_missing_extracted_key(self):
        """Candidates without extracted symbols are excluded."""
        validator = Mock()
        validator.normalize.side_effect = lambda x: x.upper()
        validator.is_valid.return_value = True

        candidates = [_make_candidate("trend1", 0.8)]
        extracted = {}  # No extracted symbols

        result = top_ticker_candidates(candidates, extracted, validator, n=5)

        assert len(result) == 0

    def test_empty_candidates(self):
        """Empty candidates list returns empty list."""
        validator = Mock()

        result = top_ticker_candidates([], {}, validator, n=5)

        assert result == []

    def test_symbol_deduplication(self):
        """Duplicate symbols (after normalization) are deduplicated."""
        validator = Mock()
        validator.normalize.side_effect = lambda x: x.upper()
        validator.is_valid.return_value = True

        candidates = [_make_candidate("trend1", 0.8)]
        extracted = {
            "trend1": ["aapl", "AAPL", "aapl", "msft"],
        }

        result = top_ticker_candidates(candidates, extracted, validator, n=5)

        assert len(result) == 1
        assert set(result[0][1]) == {"AAPL", "MSFT"}

    def test_sorted_symbols(self):
        """Symbols within each candidate are sorted."""
        validator = Mock()
        validator.normalize.side_effect = lambda x: x.upper()
        validator.is_valid.return_value = True

        candidates = [_make_candidate("trend1", 0.8)]
        extracted = {
            "trend1": ["TSLA", "AAPL", "MSFT"],
        }

        result = top_ticker_candidates(candidates, extracted, validator, n=5)

        assert result[0][1] == ["AAPL", "MSFT", "TSLA"]  # Alphabetical


class TestIntegration:
    def test_full_workflow(self):
        """Full workflow with multiple candidates and symbols."""
        validator = Mock()
        validator.normalize.side_effect = lambda x: x.upper().strip()
        validator.is_valid.side_effect = lambda x: x in ["AAPL", "MSFT", "TSLA", "NVDA"]

        candidates = [
            _make_candidate("tech_trend", 0.9),
            _make_candidate("ev_trend", 0.7),
            _make_candidate("spam_trend", 0.5),
        ]
        extracted = {
            "tech_trend": ["aapl", "msft", "nvda"],
            "ev_trend": ["tsla", "invalid"],
            "spam_trend": ["invalid1", "invalid2"],  # No valid symbols
        }

        result = top_ticker_candidates(candidates, extracted, validator, n=5)

        assert len(result) == 2  # spam_trend excluded
        assert result[0][0].key == "tech_trend"
        assert result[0][1] == ["AAPL", "MSFT", "NVDA"]
        assert result[1][0].key == "ev_trend"
        assert result[1][1] == ["TSLA"]
