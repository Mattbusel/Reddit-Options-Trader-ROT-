"""Tests for src/rot/ranking.py"""
from __future__ import annotations

import pytest

from rot.ranking import (
    RankingDimension,
    SignalRanker,
    TierRanking,
    _score_to_tier,
)


# ---------------------------------------------------------------------------
# Tier scoring helper
# ---------------------------------------------------------------------------


class TestScoreToTier:
    def test_s_tier(self):
        assert _score_to_tier(0.9) == "S"

    def test_a_tier(self):
        assert _score_to_tier(0.7) == "A"

    def test_b_tier(self):
        assert _score_to_tier(0.5) == "B"

    def test_c_tier(self):
        assert _score_to_tier(0.3) == "C"

    def test_d_tier_zero(self):
        assert _score_to_tier(0.0) == "D"

    def test_d_tier_near_zero(self):
        assert _score_to_tier(0.1) == "D"

    def test_boundary_exactly_0_8_is_a(self):
        # score > 0.8 is S; score == 0.8 falls to A
        assert _score_to_tier(0.8) == "A"

    def test_just_above_0_8_is_s(self):
        assert _score_to_tier(0.801) == "S"


# ---------------------------------------------------------------------------
# RankingDimension enum
# ---------------------------------------------------------------------------


class TestRankingDimension:
    def test_all_five_dimensions_exist(self):
        dims = list(RankingDimension)
        assert len(dims) == 5

    def test_string_value_lookup(self):
        assert RankingDimension("sentiment") == RankingDimension.SENTIMENT

    def test_invalid_dimension_raises(self):
        with pytest.raises(ValueError):
            RankingDimension("nonexistent")


# ---------------------------------------------------------------------------
# SignalRanker construction
# ---------------------------------------------------------------------------


class TestSignalRankerConstruction:
    def test_default_weights_equal(self):
        r = SignalRanker()
        weights = r.weights
        assert len(weights) == len(RankingDimension)
        # All equal; each should be 1/5
        for v in weights.values():
            assert abs(v - 0.2) < 1e-9

    def test_custom_weights_normalised(self):
        r = SignalRanker(weights={RankingDimension.SENTIMENT: 2.0, RankingDimension.IV_RANK: 3.0})
        total = sum(r.weights.values())
        assert abs(total - 1.0) < 1e-9

    def test_update_weights(self):
        r = SignalRanker()
        r.update_weights({RankingDimension.MOMENTUM: 10.0})
        total = sum(r.weights.values())
        assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# SignalRanker.rank()
# ---------------------------------------------------------------------------


def _full_scores(v: float) -> dict:
    return {dim: v for dim in RankingDimension}


class TestSignalRankerRank:
    def test_rank_returns_list(self):
        r = SignalRanker()
        result = r.rank(["AAPL"], {"AAPL": _full_scores(0.5)})
        assert isinstance(result, list)

    def test_rank_result_type(self):
        r = SignalRanker()
        result = r.rank(["AAPL"], {"AAPL": _full_scores(0.5)})
        assert isinstance(result[0], TierRanking)

    def test_rank_sorted_descending(self):
        r = SignalRanker()
        scores = {
            "AAPL": _full_scores(0.9),
            "TSLA": _full_scores(0.3),
            "NVDA": _full_scores(0.6),
        }
        result = r.rank(["AAPL", "TSLA", "NVDA"], scores)
        for i in range(len(result) - 1):
            assert result[i].score >= result[i + 1].score

    def test_rank_all_tickers_included(self):
        r = SignalRanker()
        tickers = ["AAPL", "TSLA", "NVDA"]
        result = r.rank(tickers, {t: _full_scores(0.5) for t in tickers})
        assert {r.ticker for r in result} == set(tickers)

    def test_rank_missing_scores_default_zero(self):
        r = SignalRanker()
        result = r.rank(["AAPL"], {})
        assert result[0].score == 0.0
        assert result[0].tier == "D"

    def test_rank_s_tier_assigned(self):
        r = SignalRanker()
        result = r.rank(["AAPL"], {"AAPL": _full_scores(1.0)})
        assert result[0].tier == "S"

    def test_rank_d_tier_assigned(self):
        r = SignalRanker()
        result = r.rank(["AAPL"], {"AAPL": _full_scores(0.0)})
        assert result[0].tier == "D"

    def test_rank_string_dimension_keys(self):
        """String keys should be accepted as well as enum keys."""
        r = SignalRanker()
        scores = {"AAPL": {"sentiment": 1.0, "momentum": 1.0}}
        result = r.rank(["AAPL"], scores)
        assert result[0].score > 0.0

    def test_rank_partial_dimensions(self):
        r = SignalRanker()
        scores = {"AAPL": {RankingDimension.SENTIMENT: 1.0}}
        result = r.rank(["AAPL"], scores)
        assert 0.0 < result[0].score < 1.0

    def test_rank_breakdown_keys(self):
        r = SignalRanker()
        result = r.rank(["AAPL"], {"AAPL": _full_scores(0.5)})
        expected_keys = {d.value for d in RankingDimension}
        assert set(result[0].breakdown.keys()) == expected_keys

    def test_rank_breakdown_sums_to_score(self):
        r = SignalRanker()
        result = r.rank(["AAPL"], {"AAPL": _full_scores(0.8)})
        total = sum(result[0].breakdown.values())
        assert abs(total - result[0].score) < 1e-9

    def test_rank_weighted_ranker(self):
        """Heavier weight on SENTIMENT should pull AAPL (high sentiment) higher."""
        r = SignalRanker(weights={RankingDimension.SENTIMENT: 10.0})
        scores = {
            "AAPL": {RankingDimension.SENTIMENT: 1.0, RankingDimension.IV_RANK: 0.0},
            "TSLA": {RankingDimension.SENTIMENT: 0.0, RankingDimension.IV_RANK: 1.0},
        }
        result = r.rank(["AAPL", "TSLA"], scores)
        assert result[0].ticker == "AAPL"

    def test_rank_updates_last_rankings(self):
        r = SignalRanker()
        r.rank(["AAPL"], {"AAPL": _full_scores(0.5)})
        assert len(r._last_rankings) >= 1

    def test_rank_empty_tickers(self):
        r = SignalRanker()
        result = r.rank([], {})
        assert result == []


# ---------------------------------------------------------------------------
# SignalRanker.leaderboard()
# ---------------------------------------------------------------------------


class TestLeaderboard:
    def test_leaderboard_no_rankings_returns_message(self):
        r = SignalRanker()
        output = r.leaderboard()
        assert "no rankings" in output.lower() or "call rank" in output.lower()

    def test_leaderboard_contains_ticker(self):
        r = SignalRanker()
        r.rank(["AAPL"], {"AAPL": _full_scores(0.8)})
        board = r.leaderboard()
        assert "AAPL" in board

    def test_leaderboard_respects_top_n(self):
        r = SignalRanker()
        tickers = [f"T{i}" for i in range(20)]
        r.rank(tickers, {t: _full_scores(0.5) for t in tickers})
        board = r.leaderboard(top_n=5)
        # Only 5 rows of data expected; check no more than 5 ticker names appear
        rows = [line for line in board.split("\n") if line.strip() and line[0].isdigit() or (line and line.strip()[0].isdigit())]
        assert len(rows) <= 5

    def test_leaderboard_returns_string(self):
        r = SignalRanker()
        r.rank(["AAPL"], {"AAPL": _full_scores(0.5)})
        assert isinstance(r.leaderboard(), str)

    def test_leaderboard_tier_in_output(self):
        r = SignalRanker()
        r.rank(["AAPL"], {"AAPL": _full_scores(1.0)})
        board = r.leaderboard()
        assert "S" in board
