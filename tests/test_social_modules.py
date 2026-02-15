"""Tests for rot.social — types, tracker, and manipulation detection.

Covers AuthorProfile, AuthorPrediction, ManipulationAlert, SentimentPropagation,
AuthorCluster, ContrarianSignal dataclasses. AuthorTracker record/resolve/stats/
leaderboard/import-export. ManipulationDetector coordinated posting, bot network,
pump-and-dump, baseline management, and helpers.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from rot.social.types import (
    ALERT_TYPES,
    AuthorCluster,
    AuthorPrediction,
    AuthorProfile,
    ContrarianSignal,
    ManipulationAlert,
    OUTCOMES,
    PLATFORMS,
    STANCES,
    SentimentPropagation,
)
from rot.social.tracker import AuthorTracker, AuthorTrackerConfig
from rot.social.manipulation import (
    ManipulationConfig,
    ManipulationDetector,
    _jaccard_similarity,
    _median,
    _safe_float,
    _safe_str,
    _TickerBaseline,
)


# ═══════════════════════════════════════════════════════════════════════════
# Part 1: Social Types
# ═══════════════════════════════════════════════════════════════════════════


class TestConstants:
    def test_platforms(self):
        assert "reddit" in PLATFORMS
        assert "stocktwits" in PLATFORMS
        assert "twitter" in PLATFORMS
        assert len(PLATFORMS) == 3

    def test_stances(self):
        assert "bullish" in STANCES
        assert "bearish" in STANCES
        assert "mixed" in STANCES
        assert "unknown" in STANCES

    def test_outcomes(self):
        assert "win" in OUTCOMES
        assert "loss" in OUTCOMES
        assert "neutral" in OUTCOMES

    def test_alert_types(self):
        assert "coordinated_posting" in ALERT_TYPES
        assert "bot_network" in ALERT_TYPES
        assert "pump_and_dump" in ALERT_TYPES


class TestAuthorProfile:
    def test_basic_creation(self):
        p = AuthorProfile(id="a1", platform="reddit", username="testuser")
        assert p.id == "a1"
        assert p.platform == "reddit"
        assert p.username == "testuser"
        assert p.total_signals == 0
        assert p.win_count == 0
        assert p.loss_count == 0

    def test_decided_count(self):
        p = AuthorProfile(id="a1", platform="reddit", username="u", win_count=5, loss_count=3)
        assert p.decided_count == 8

    def test_computed_accuracy(self):
        p = AuthorProfile(id="a1", platform="reddit", username="u", win_count=7, loss_count=3)
        assert p.computed_accuracy == 0.7

    def test_computed_accuracy_no_decided(self):
        p = AuthorProfile(id="a1", platform="reddit", username="u")
        assert p.computed_accuracy is None

    def test_to_dict(self):
        p = AuthorProfile(id="a1", platform="reddit", username="u", total_signals=5)
        d = p.to_dict()
        assert d["id"] == "a1"
        assert d["total_signals"] == 5

    def test_invalid_platform(self):
        with pytest.raises(ValueError, match="Invalid platform"):
            AuthorProfile(id="a1", platform="facebook", username="u")

    def test_empty_username(self):
        with pytest.raises(ValueError, match="username"):
            AuthorProfile(id="a1", platform="reddit", username="")

    def test_negative_total_signals(self):
        with pytest.raises(ValueError, match="total_signals"):
            AuthorProfile(id="a1", platform="reddit", username="u", total_signals=-1)

    def test_invalid_accuracy(self):
        with pytest.raises(ValueError, match="accuracy"):
            AuthorProfile(id="a1", platform="reddit", username="u", accuracy=1.5)

    def test_invalid_reputation(self):
        with pytest.raises(ValueError, match="reputation_score"):
            AuthorProfile(id="a1", platform="reddit", username="u", reputation_score=101.0)

    def test_frozen(self):
        p = AuthorProfile(id="a1", platform="reddit", username="u")
        with pytest.raises(AttributeError):
            p.username = "changed"  # type: ignore[misc]

    @pytest.mark.parametrize("platform", sorted(PLATFORMS))
    def test_all_platforms_valid(self, platform):
        p = AuthorProfile(id="a1", platform=platform, username="u")
        assert p.platform == platform


class TestAuthorPrediction:
    def test_basic_creation(self):
        p = AuthorPrediction(
            id="p1", author_id="a1", ticker="AAPL",
            stance="bullish", confidence=0.8,
        )
        assert p.id == "p1"
        assert p.ticker == "AAPL"
        assert p.stance == "bullish"
        assert p.confidence == 0.8
        assert not p.is_resolved
        assert not p.is_win
        assert not p.is_loss

    def test_resolved_prediction(self):
        p = AuthorPrediction(
            id="p1", author_id="a1", ticker="TSLA",
            stance="bearish", confidence=0.9,
            outcome="win", pnl_pct=-5.0,
        )
        assert p.is_resolved
        assert p.is_win
        assert not p.is_loss

    def test_to_dict(self):
        p = AuthorPrediction(
            id="p1", author_id="a1", ticker="SPY",
            stance="bullish", confidence=0.5,
        )
        d = p.to_dict()
        assert d["ticker"] == "SPY"
        assert d["outcome"] is None

    def test_invalid_stance(self):
        with pytest.raises(ValueError, match="Invalid stance"):
            AuthorPrediction(id="p1", author_id="a1", ticker="X", stance="up", confidence=0.5)

    def test_invalid_confidence(self):
        with pytest.raises(ValueError, match="confidence"):
            AuthorPrediction(id="p1", author_id="a1", ticker="X", stance="bullish", confidence=1.5)

    def test_invalid_outcome(self):
        with pytest.raises(ValueError, match="Invalid outcome"):
            AuthorPrediction(
                id="p1", author_id="a1", ticker="X",
                stance="bullish", confidence=0.5, outcome="maybe",
            )

    def test_empty_author_id(self):
        with pytest.raises(ValueError, match="author_id"):
            AuthorPrediction(id="p1", author_id="", ticker="X", stance="bullish", confidence=0.5)

    def test_empty_ticker(self):
        with pytest.raises(ValueError, match="ticker"):
            AuthorPrediction(id="p1", author_id="a1", ticker="", stance="bullish", confidence=0.5)

    @pytest.mark.parametrize("outcome", sorted(OUTCOMES))
    def test_all_outcomes_valid(self, outcome):
        p = AuthorPrediction(
            id="p1", author_id="a1", ticker="X",
            stance="bullish", confidence=0.5, outcome=outcome,
        )
        assert p.outcome == outcome


class TestManipulationAlert:
    def test_basic_creation(self):
        a = ManipulationAlert(
            id="m1", alert_type="bot_network",
            tickers=["AAPL"], authors=["a1", "a2"],
            evidence={"pattern": "test"}, severity=50.0,
        )
        assert a.alert_type == "bot_network"
        assert a.severity == 50.0
        assert not a.resolved

    def test_to_dict(self):
        a = ManipulationAlert(
            id="m1", alert_type="pump_and_dump",
            tickers=["GME"], authors=["a1"],
            evidence={}, severity=80.0,
        )
        d = a.to_dict()
        assert d["alert_type"] == "pump_and_dump"
        assert d["severity"] == 80.0

    def test_invalid_alert_type(self):
        with pytest.raises(ValueError, match="Invalid alert_type"):
            ManipulationAlert(
                id="m1", alert_type="fraud",
                tickers=["X"], authors=[], evidence={}, severity=50.0,
            )

    def test_invalid_severity(self):
        with pytest.raises(ValueError, match="severity"):
            ManipulationAlert(
                id="m1", alert_type="bot_network",
                tickers=["X"], authors=[], evidence={}, severity=101.0,
            )

    def test_empty_tickers(self):
        with pytest.raises(ValueError, match="tickers"):
            ManipulationAlert(
                id="m1", alert_type="bot_network",
                tickers=[], authors=[], evidence={}, severity=50.0,
            )


class TestSentimentPropagation:
    def test_basic_creation(self):
        sp = SentimentPropagation(
            id="sp1", ticker="AAPL",
            origin_sub="wallstreetbets", spread_to="options",
            origin_ts=1000.0, spread_ts=2000.0,
        )
        assert sp.lag_seconds == 1000.0

    def test_to_dict(self):
        sp = SentimentPropagation(
            id="sp1", ticker="TSLA",
            origin_sub="wsb", spread_to="stocks",
            origin_ts=100.0, spread_ts=200.0,
        )
        d = sp.to_dict()
        assert d["lag_seconds"] == 100.0

    def test_same_origin_spread_raises(self):
        with pytest.raises(ValueError, match="must differ"):
            SentimentPropagation(
                id="sp1", ticker="X",
                origin_sub="wsb", spread_to="wsb",
                origin_ts=100.0, spread_ts=200.0,
            )

    def test_empty_ticker(self):
        with pytest.raises(ValueError, match="ticker"):
            SentimentPropagation(
                id="sp1", ticker="",
                origin_sub="wsb", spread_to="stocks",
                origin_ts=100.0, spread_ts=200.0,
            )


class TestAuthorCluster:
    def test_basic_creation(self):
        c = AuthorCluster(
            id="c1", authors=["a1", "a2"],
            similarity_score=0.85, common_tickers=["AAPL"],
        )
        assert c.similarity_score == 0.85

    def test_to_dict(self):
        c = AuthorCluster(
            id="c1", authors=["a1", "a2"],
            similarity_score=0.5, common_tickers=["SPY"],
        )
        d = c.to_dict()
        assert d["similarity_score"] == 0.5

    def test_invalid_similarity(self):
        with pytest.raises(ValueError, match="similarity_score"):
            AuthorCluster(
                id="c1", authors=["a1", "a2"],
                similarity_score=1.5, common_tickers=[],
            )

    def test_too_few_authors(self):
        with pytest.raises(ValueError, match="at least 2"):
            AuthorCluster(
                id="c1", authors=["a1"],
                similarity_score=0.5, common_tickers=[],
            )


class TestContrarianSignal:
    def test_basic_creation(self):
        cs = ContrarianSignal(
            id="cs1", ticker="AAPL",
            contrarian_stance="bearish", consensus_stance="bullish",
            contrarian_authors=["a1"], consensus_author_count=10,
            strength=0.8,
        )
        assert cs.strength == 0.8

    def test_to_dict(self):
        cs = ContrarianSignal(
            id="cs1", ticker="TSLA",
            contrarian_stance="bullish", consensus_stance="bearish",
            contrarian_authors=["a1"], consensus_author_count=5,
            strength=0.6,
        )
        d = cs.to_dict()
        assert d["contrarian_stance"] == "bullish"

    def test_same_stance_raises(self):
        with pytest.raises(ValueError, match="must differ"):
            ContrarianSignal(
                id="cs1", ticker="X",
                contrarian_stance="bullish", consensus_stance="bullish",
                contrarian_authors=["a1"], consensus_author_count=5,
                strength=0.5,
            )

    def test_invalid_strength(self):
        with pytest.raises(ValueError, match="strength"):
            ContrarianSignal(
                id="cs1", ticker="X",
                contrarian_stance="bullish", consensus_stance="bearish",
                contrarian_authors=["a1"], consensus_author_count=5,
                strength=1.5,
            )

    def test_empty_contrarian_authors(self):
        with pytest.raises(ValueError, match="contrarian_authors"):
            ContrarianSignal(
                id="cs1", ticker="X",
                contrarian_stance="bullish", consensus_stance="bearish",
                contrarian_authors=[], consensus_author_count=5,
                strength=0.5,
            )


# ═══════════════════════════════════════════════════════════════════════════
# Part 2: AuthorTracker
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tracker():
    return AuthorTracker(AuthorTrackerConfig(min_predictions_for_score=3))


class TestAuthorTrackerConfig:
    def test_defaults(self):
        cfg = AuthorTrackerConfig()
        assert cfg.min_predictions_for_score == 10
        assert cfg.resolution_window_hours == 24
        assert cfg.max_pnl_pct == 50.0


class TestDetermineOutcome:
    @pytest.mark.parametrize("stance,pnl,expected", [
        ("bullish", 5.0, "win"),
        ("bullish", -5.0, "loss"),
        ("bearish", -5.0, "win"),
        ("bearish", 5.0, "loss"),
        ("bullish", 0.3, "neutral"),   # dead zone
        ("bearish", -0.3, "neutral"),  # dead zone
        ("bullish", 0.0, "neutral"),   # zero
        ("mixed", 10.0, "neutral"),    # non-directional
        ("unknown", -10.0, "neutral"), # non-directional
    ])
    def test_outcome(self, stance, pnl, expected):
        assert AuthorTracker._determine_outcome(stance, pnl) == expected

    def test_boundary_above_threshold(self):
        # 0.5 is the threshold — at 0.5, abs(0.5) < 0.5 is False
        assert AuthorTracker._determine_outcome("bullish", 0.5) == "win"

    def test_boundary_below_threshold(self):
        assert AuthorTracker._determine_outcome("bullish", 0.49) == "neutral"


class TestComputeSharpe:
    def test_empty_returns(self):
        assert AuthorTracker._compute_sharpe([]) == 0.0

    def test_single_return(self):
        assert AuthorTracker._compute_sharpe([5.0]) == 0.0

    def test_identical_returns(self):
        assert AuthorTracker._compute_sharpe([5.0, 5.0, 5.0]) == 0.0

    def test_positive_sharpe(self):
        returns = [2.0, 3.0, 4.0, 5.0, 6.0]
        sharpe = AuthorTracker._compute_sharpe(returns)
        assert sharpe > 0

    def test_negative_sharpe(self):
        returns = [-2.0, -3.0, -4.0, -5.0, -6.0]
        sharpe = AuthorTracker._compute_sharpe(returns)
        assert sharpe < 0

    def test_annualization(self):
        returns = [1.0, 2.0, 3.0, 4.0]
        sharpe = AuthorTracker._compute_sharpe(returns)
        # mean=2.5, std uses sample variance (n-1)
        n = len(returns)
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = math.sqrt(variance)
        expected = (mean / std) * math.sqrt(252)
        assert math.isclose(sharpe, expected, rel_tol=1e-6)


class TestRecordPrediction:
    def test_records_and_returns(self, tracker):
        pred = tracker.record_prediction(
            author_id="a1", platform="reddit", username="user1",
            ticker="aapl", stance="bullish", confidence=0.8,
        )
        assert pred.ticker == "AAPL"  # normalized
        assert pred.stance == "bullish"
        assert pred.confidence == 0.8
        assert not pred.is_resolved

    def test_creates_profile_on_first_prediction(self, tracker):
        tracker.record_prediction(
            author_id="a1", platform="reddit", username="user1",
            ticker="TSLA", stance="bearish", confidence=0.7,
        )
        profile = tracker.get_profile("a1")
        assert profile is not None
        assert profile.platform == "reddit"
        assert profile.total_signals == 1

    def test_increments_total_signals(self, tracker):
        for i in range(5):
            tracker.record_prediction(
                author_id="a1", platform="reddit", username="u",
                ticker="SPY", stance="bullish", confidence=0.5,
            )
        profile = tracker.get_profile("a1")
        assert profile.total_signals == 5

    def test_prediction_gets_unique_id(self, tracker):
        p1 = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="SPY", stance="bullish", confidence=0.5,
        )
        p2 = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="SPY", stance="bullish", confidence=0.5,
        )
        assert p1.id != p2.id

    def test_optional_signal_id(self, tracker):
        pred = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="SPY", stance="bullish", confidence=0.5,
            signal_id="sig_123",
        )
        assert pred.signal_id == "sig_123"


class TestResolvePrediction:
    def test_resolve_win(self, tracker):
        pred = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="AAPL", stance="bullish", confidence=0.8,
        )
        resolved = tracker.resolve_prediction(pred.id, "a1", 10.0)
        assert resolved.outcome == "win"
        assert resolved.pnl_pct == 10.0
        assert resolved.is_resolved

    def test_resolve_loss(self, tracker):
        pred = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="AAPL", stance="bullish", confidence=0.8,
        )
        resolved = tracker.resolve_prediction(pred.id, "a1", -10.0)
        assert resolved.outcome == "loss"

    def test_resolve_neutral_dead_zone(self, tracker):
        pred = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="AAPL", stance="bullish", confidence=0.8,
        )
        resolved = tracker.resolve_prediction(pred.id, "a1", 0.3)
        assert resolved.outcome == "neutral"

    def test_resolve_caps_pnl(self, tracker):
        pred = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="AAPL", stance="bullish", confidence=0.8,
        )
        resolved = tracker.resolve_prediction(pred.id, "a1", 100.0)
        assert resolved.pnl_pct == 50.0  # capped at max_pnl_pct

    def test_resolve_caps_negative_pnl(self, tracker):
        pred = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="AAPL", stance="bearish", confidence=0.8,
        )
        resolved = tracker.resolve_prediction(pred.id, "a1", -100.0)
        assert resolved.pnl_pct == -50.0

    def test_resolve_updates_win_count(self, tracker):
        pred = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="AAPL", stance="bullish", confidence=0.8,
        )
        tracker.resolve_prediction(pred.id, "a1", 10.0)
        profile = tracker.get_profile("a1")
        assert profile.win_count == 1

    def test_resolve_updates_loss_count(self, tracker):
        pred = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="AAPL", stance="bullish", confidence=0.8,
        )
        tracker.resolve_prediction(pred.id, "a1", -10.0)
        profile = tracker.get_profile("a1")
        assert profile.loss_count == 1

    def test_resolve_already_resolved_raises(self, tracker):
        pred = tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="AAPL", stance="bullish", confidence=0.8,
        )
        tracker.resolve_prediction(pred.id, "a1", 10.0)
        with pytest.raises(ValueError, match="already resolved"):
            tracker.resolve_prediction(pred.id, "a1", 5.0)

    def test_resolve_missing_author_raises(self, tracker):
        with pytest.raises(KeyError, match="No predictions"):
            tracker.resolve_prediction("xxx", "nonexistent", 5.0)

    def test_resolve_missing_prediction_raises(self, tracker):
        tracker.record_prediction(
            author_id="a1", platform="reddit", username="u",
            ticker="AAPL", stance="bullish", confidence=0.8,
        )
        with pytest.raises(KeyError, match="not found"):
            tracker.resolve_prediction("wrong_id", "a1", 5.0)


class TestResolvePredictionsBatch:
    def test_batch_resolve(self, tracker):
        p1 = tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)
        p2 = tracker.record_prediction("a1", "reddit", "u", "TSLA", "bearish", 0.9)
        results = tracker.resolve_predictions_batch([
            (p1.id, "a1", 5.0),
            (p2.id, "a1", -5.0),
        ])
        assert len(results) == 2
        assert results[0].outcome == "win"
        assert results[1].outcome == "win"  # bearish + neg = win

    def test_batch_skips_errors(self, tracker):
        p1 = tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)
        results = tracker.resolve_predictions_batch([
            (p1.id, "a1", 5.0),
            ("missing", "a1", 5.0),      # missing pred
            ("xxx", "missing", 5.0),      # missing author
        ])
        assert len(results) == 1


class TestComputeAuthorStats:
    def test_stats_below_min_predictions(self, tracker):
        pred = tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)
        tracker.resolve_prediction(pred.id, "a1", 10.0)
        profile = tracker.compute_author_stats("a1")
        assert profile.accuracy is None  # only 1 decided, min=3
        assert profile.reputation_score is None

    def test_stats_at_min_predictions(self, tracker):
        # min_predictions_for_score=3 in fixture
        for i in range(3):
            pred = tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)
            tracker.resolve_prediction(pred.id, "a1", 10.0)

        profile = tracker.compute_author_stats("a1")
        assert profile.accuracy == 1.0  # all wins
        assert profile.roi_if_followed > 0
        assert profile.sharpe is not None
        assert profile.reputation_score is not None

    def test_stats_mixed_outcomes(self, tracker):
        # 2 wins + 1 loss = 3 decided
        for pnl in [10.0, 10.0, -10.0]:
            pred = tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)
            tracker.resolve_prediction(pred.id, "a1", pnl)

        profile = tracker.compute_author_stats("a1")
        assert math.isclose(profile.accuracy, 2 / 3, rel_tol=1e-6)
        assert profile.win_count == 2
        assert profile.loss_count == 1

    def test_stats_missing_author(self, tracker):
        with pytest.raises(KeyError, match="not found"):
            tracker.compute_author_stats("nonexistent")

    def test_neutral_not_counted(self, tracker):
        # 3 neutrals (mixed stance) + 3 wins
        for _ in range(3):
            pred = tracker.record_prediction("a1", "reddit", "u", "SPY", "mixed", 0.5)
            tracker.resolve_prediction(pred.id, "a1", 10.0)
        for _ in range(3):
            pred = tracker.record_prediction("a1", "reddit", "u", "SPY", "bullish", 0.8)
            tracker.resolve_prediction(pred.id, "a1", 10.0)

        profile = tracker.compute_author_stats("a1")
        assert profile.win_count == 3
        assert profile.loss_count == 0
        assert profile.accuracy == 1.0  # 3/3

    def test_reputation_components(self, tracker):
        # Create a perfect record
        for _ in range(5):
            pred = tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.9)
            tracker.resolve_prediction(pred.id, "a1", 10.0)

        profile = tracker.compute_author_stats("a1")
        assert profile.reputation_score is not None
        assert profile.reputation_score > 50.0  # good trader


class TestGetOrCreateProfile:
    def test_creates_new(self, tracker):
        profile = tracker.get_or_create_profile("a1", "reddit", "user1")
        assert profile.total_signals == 0
        assert profile.platform == "reddit"

    def test_returns_existing(self, tracker):
        tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)
        profile = tracker.get_or_create_profile("a1", "reddit", "u")
        assert profile.total_signals == 1  # existing profile


class TestLeaderboard:
    def test_empty_tracker(self, tracker):
        lb = tracker.get_leaderboard()
        assert lb == []

    def test_filters_below_min(self, tracker):
        # Only 1 decided prediction; min_predictions=10 (default for leaderboard)
        pred = tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)
        tracker.resolve_prediction(pred.id, "a1", 10.0)
        lb = tracker.get_leaderboard(min_predictions=10)
        assert lb == []

    def test_includes_qualifying_authors(self, tracker):
        # min_predictions_for_score=3 in fixture
        for _ in range(5):
            pred = tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)
            tracker.resolve_prediction(pred.id, "a1", 10.0)

        lb = tracker.get_leaderboard(min_predictions=3)
        assert len(lb) == 1
        assert lb[0].id == "a1"

    def test_sorted_by_reputation(self, tracker):
        # Author a1: 5 wins
        for _ in range(5):
            pred = tracker.record_prediction("a1", "reddit", "u1", "AAPL", "bullish", 0.8)
            tracker.resolve_prediction(pred.id, "a1", 10.0)

        # Author a2: 3 wins + 2 losses (worse)
        for pnl in [10.0, 10.0, 10.0, -10.0, -10.0]:
            pred = tracker.record_prediction("a2", "reddit", "u2", "TSLA", "bullish", 0.7)
            tracker.resolve_prediction(pred.id, "a2", pnl)

        lb = tracker.get_leaderboard(min_predictions=3)
        assert len(lb) == 2
        assert lb[0].id == "a1"  # better reputation

    def test_limit(self, tracker):
        for i in range(5):
            aid = f"author_{i}"
            for _ in range(4):
                pred = tracker.record_prediction(aid, "reddit", f"u{i}", "SPY", "bullish", 0.8)
                tracker.resolve_prediction(pred.id, aid, 10.0)

        lb = tracker.get_leaderboard(min_predictions=3, limit=2)
        assert len(lb) == 2


class TestPredictionQueries:
    def test_get_predictions_empty(self, tracker):
        preds = tracker.get_predictions("nonexistent")
        assert preds == []

    def test_get_predictions_sorted_recent_first(self, tracker):
        with patch("rot.social.tracker.time") as mock_time:
            mock_time.time.return_value = 1000.0
            tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)
            mock_time.time.return_value = 2000.0
            tracker.record_prediction("a1", "reddit", "u", "TSLA", "bearish", 0.7)
            mock_time.time.return_value = 3000.0
            tracker.record_prediction("a1", "reddit", "u", "SPY", "bullish", 0.9)

        preds = tracker.get_predictions("a1")
        assert len(preds) == 3
        assert preds[0].ticker == "SPY"  # most recent first
        assert preds[2].ticker == "AAPL"  # oldest last

    def test_get_predictions_limit(self, tracker):
        for i in range(10):
            tracker.record_prediction("a1", "reddit", "u", f"T{i}", "bullish", 0.5)
        preds = tracker.get_predictions("a1", limit=3)
        assert len(preds) == 3

    def test_get_pending_predictions(self, tracker):
        with patch("rot.social.tracker.time") as mock_time:
            # Old prediction (2 hours ago)
            mock_time.time.return_value = time.time() - 7200
            tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)

            # Recent prediction (5 min ago)
            mock_time.time.return_value = time.time() - 300
            tracker.record_prediction("a1", "reddit", "u", "TSLA", "bearish", 0.7)

        pending = tracker.get_pending_predictions(min_age_hours=1)
        assert len(pending) == 1
        assert pending[0].ticker == "AAPL"


class TestImportExport:
    def test_import_export_profiles(self, tracker):
        profile = AuthorProfile(id="a1", platform="reddit", username="u", total_signals=10)
        tracker.import_profile(profile)
        exported = tracker.export_profiles()
        assert len(exported) == 1
        assert exported[0].id == "a1"

    def test_import_export_predictions(self, tracker):
        pred = AuthorPrediction(
            id="p1", author_id="a1", ticker="AAPL",
            stance="bullish", confidence=0.8,
        )
        tracker.import_prediction(pred)
        exported = tracker.export_predictions()
        assert len(exported) == 1
        assert exported[0].id == "p1"

    def test_import_multiple_authors(self, tracker):
        tracker.import_prediction(AuthorPrediction(
            id="p1", author_id="a1", ticker="AAPL", stance="bullish", confidence=0.8,
        ))
        tracker.import_prediction(AuthorPrediction(
            id="p2", author_id="a2", ticker="TSLA", stance="bearish", confidence=0.9,
        ))
        exported = tracker.export_predictions()
        assert len(exported) == 2

    def test_get_profile_after_import(self, tracker):
        profile = AuthorProfile(id="a1", platform="reddit", username="u")
        tracker.import_profile(profile)
        assert tracker.get_profile("a1") is not None
        assert tracker.get_profile("nonexistent") is None


# ═══════════════════════════════════════════════════════════════════════════
# Part 3: Manipulation Detection Helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestJaccardSimilarity:
    def test_identical_strings(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert _jaccard_similarity("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        sim = _jaccard_similarity("hello world foo", "hello bar foo")
        # intersection: {hello, foo}, union: {hello, world, foo, bar}
        assert math.isclose(sim, 2 / 4)

    def test_empty_both(self):
        assert _jaccard_similarity("", "") == 0.0

    def test_one_empty(self):
        assert _jaccard_similarity("hello", "") == 0.0

    def test_case_insensitive(self):
        assert _jaccard_similarity("HELLO WORLD", "hello world") == 1.0


class TestSafeFloat:
    def test_valid_number(self):
        assert _safe_float(42.5) == 42.5

    def test_string_number(self):
        assert _safe_float("3.14") == 3.14

    def test_none(self):
        assert _safe_float(None) == 0.0

    def test_none_custom_default(self):
        assert _safe_float(None, default=-1.0) == -1.0

    def test_invalid_string(self):
        assert _safe_float("abc") == 0.0

    def test_nan(self):
        assert _safe_float(float("nan")) == 0.0


class TestSafeStr:
    def test_normal_string(self):
        assert _safe_str("hello") == "hello"

    def test_none(self):
        assert _safe_str(None) == ""

    def test_number(self):
        assert _safe_str(42) == "42"


class TestMedian:
    def test_empty(self):
        assert _median([]) == 0.0

    def test_single(self):
        assert _median([5.0]) == 5.0

    def test_odd(self):
        assert _median([1.0, 3.0, 5.0]) == 3.0

    def test_even(self):
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_unsorted(self):
        assert _median([5.0, 1.0, 3.0]) == 3.0


class TestTickerBaseline:
    def test_initial_state(self):
        b = _TickerBaseline()
        assert b.signal_counts == []
        assert b.mean() == 0.0
        assert b.std() == 0.0

    def test_update(self):
        b = _TickerBaseline()
        b.update(10)
        b.update(20)
        assert b.signal_counts == [10, 20]
        assert b.mean() == 15.0

    def test_negative_count_clamped(self):
        b = _TickerBaseline()
        b.update(-5)
        assert b.signal_counts == [0]

    def test_max_window(self):
        b = _TickerBaseline()
        for i in range(25):
            b.update(i)
        assert len(b.signal_counts) == 20
        # Should contain the last 20 values (5..24)
        assert b.signal_counts[0] == 5
        assert b.signal_counts[-1] == 24

    def test_std_with_uniform_data(self):
        b = _TickerBaseline()
        for _ in range(5):
            b.update(10)
        assert b.std() == 0.0

    def test_std_with_varied_data(self):
        b = _TickerBaseline()
        for v in [10, 20, 30]:
            b.update(v)
        assert b.std() > 0

    def test_std_single_value(self):
        b = _TickerBaseline()
        b.update(10)
        assert b.std() == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Part 4: ManipulationConfig
# ═══════════════════════════════════════════════════════════════════════════


class TestManipulationConfig:
    def test_defaults(self):
        cfg = ManipulationConfig()
        assert cfg.coordination_window_s == 1800
        assert cfg.min_authors_for_coordination == 3
        assert cfg.bot_time_tolerance_s == 300
        assert cfg.bot_min_group_size == 3
        assert cfg.pump_volume_multiplier == 3.0
        assert cfg.pump_price_threshold_pct == 5.0
        assert cfg.min_severity_to_report == 30.0

    def test_invalid_coordination_window(self):
        with pytest.raises(ValueError, match="coordination_window_s"):
            ManipulationConfig(coordination_window_s=0)

    def test_invalid_bot_time_tolerance(self):
        with pytest.raises(ValueError, match="bot_time_tolerance_s"):
            ManipulationConfig(bot_time_tolerance_s=-1)

    def test_invalid_bot_min_group_size(self):
        with pytest.raises(ValueError, match="bot_min_group_size"):
            ManipulationConfig(bot_min_group_size=1)

    def test_invalid_pump_volume_multiplier(self):
        with pytest.raises(ValueError, match="pump_volume_multiplier"):
            ManipulationConfig(pump_volume_multiplier=0.5)

    def test_invalid_pump_price_threshold(self):
        with pytest.raises(ValueError, match="pump_price_threshold_pct"):
            ManipulationConfig(pump_price_threshold_pct=0.0)

    def test_invalid_min_authors(self):
        with pytest.raises(ValueError, match="min_authors_for_coordination"):
            ManipulationConfig(min_authors_for_coordination=1)

    def test_invalid_min_severity(self):
        with pytest.raises(ValueError, match="min_severity_to_report"):
            ManipulationConfig(min_severity_to_report=101.0)


# ═══════════════════════════════════════════════════════════════════════════
# Part 5: ManipulationDetector
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def detector():
    return ManipulationDetector(ManipulationConfig(
        min_severity_to_report=0.0,  # see all alerts in tests
        min_authors_for_coordination=2,
        bot_min_group_size=2,
    ))


def _make_signal(
    ticker: str = "AAPL",
    stance: str = "bullish",
    author: str = "user1",
    created_at: float = 0.0,
    confidence: float = 0.8,
    price_at_signal: float = 150.0,
    price_current: float = 155.0,
    post_title: str = "",
    subreddit: str = "wallstreetbets",
) -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "stance": stance,
        "author": author,
        "created_at": created_at if created_at > 0 else time.time(),
        "confidence": confidence,
        "price_at_signal": price_at_signal,
        "price_current": price_current,
        "post_title": post_title,
        "subreddit": subreddit,
    }


class TestDetectAll:
    def test_empty_signals(self, detector):
        alerts = detector.detect_all([])
        assert alerts == []

    def test_single_signal_no_alerts(self, detector):
        alerts = detector.detect_all([_make_signal()])
        assert alerts == []

    def test_sorted_by_severity_desc(self, detector):
        now = time.time()
        signals = [
            _make_signal(ticker="AAPL", author=f"user{i}", created_at=now + i, stance="bullish")
            for i in range(5)
        ]
        alerts = detector.detect_all(signals)
        for i in range(len(alerts) - 1):
            assert alerts[i].severity >= alerts[i + 1].severity

    def test_severity_filter(self):
        det = ManipulationDetector(ManipulationConfig(
            min_severity_to_report=90.0,
            min_authors_for_coordination=2,
        ))
        now = time.time()
        signals = [
            _make_signal(ticker="AAPL", author=f"u{i}", created_at=now + i * 10, stance="bullish")
            for i in range(3)
        ]
        alerts = det.detect_all(signals)
        for a in alerts:
            assert a.severity >= 90.0


class TestCoordinatedPosting:
    def test_same_ticker_same_stance_tight_window(self, detector):
        now = time.time()
        signals = [
            _make_signal(ticker="AAPL", author="user1", created_at=now, stance="bullish"),
            _make_signal(ticker="AAPL", author="user2", created_at=now + 60, stance="bullish"),
            _make_signal(ticker="AAPL", author="user3", created_at=now + 120, stance="bullish"),
        ]
        alerts = detector.detect_coordinated_posting(signals)
        assert len(alerts) >= 1
        assert alerts[0].alert_type == "coordinated_posting"
        assert "AAPL" in alerts[0].tickers

    def test_different_tickers_no_flag(self, detector):
        now = time.time()
        signals = [
            _make_signal(ticker="AAPL", author="user1", created_at=now, stance="bullish"),
            _make_signal(ticker="TSLA", author="user2", created_at=now + 60, stance="bullish"),
        ]
        alerts = detector.detect_coordinated_posting(signals)
        assert len(alerts) == 0

    def test_mixed_stances_no_flag(self, detector):
        now = time.time()
        signals = [
            _make_signal(ticker="AAPL", author="user1", created_at=now, stance="bullish"),
            _make_signal(ticker="AAPL", author="user2", created_at=now + 60, stance="bearish"),
            _make_signal(ticker="AAPL", author="user3", created_at=now + 120, stance="unknown"),
        ]
        alerts = detector.detect_coordinated_posting(signals)
        # Should not flag because directional stances are split
        coord_alerts = [a for a in alerts if a.alert_type == "coordinated_posting"]
        # Need 80% agreement — 1 bullish, 1 bearish out of 2 directional = 50%
        assert len(coord_alerts) == 0

    def test_wide_time_gap_no_flag(self, detector):
        now = time.time()
        signals = [
            _make_signal(ticker="AAPL", author="user1", created_at=now, stance="bullish"),
            _make_signal(ticker="AAPL", author="user2", created_at=now + 5000, stance="bullish"),
        ]
        alerts = detector.detect_coordinated_posting(signals)
        assert len(alerts) == 0

    def test_evidence_contains_authors(self, detector):
        now = time.time()
        signals = [
            _make_signal(ticker="GME", author="u1", created_at=now, stance="bullish"),
            _make_signal(ticker="GME", author="u2", created_at=now + 30, stance="bullish"),
        ]
        alerts = detector.detect_coordinated_posting(signals)
        if alerts:
            assert "authors" in alerts[0].evidence


class TestBotNetworkTiming:
    def test_synchronized_authors(self, detector):
        now = time.time()
        # Three authors posting at nearly the same times repeatedly
        signals = []
        for offset in [0, 100, 200, 300, 400]:
            for author in ["bot1", "bot2", "bot3"]:
                signals.append(_make_signal(
                    ticker="SPY", author=author,
                    created_at=now + offset + 5,  # small jitter
                    stance="bullish",
                ))
        alerts = detector.detect_bot_network(signals)
        timing_alerts = [
            a for a in alerts
            if a.alert_type == "bot_network"
            and a.evidence.get("sub_pattern") == "timing"
        ]
        # Should detect the bot network
        assert len(timing_alerts) >= 1

    def test_no_bot_with_random_timing(self, detector):
        now = time.time()
        signals = [
            _make_signal(author="u1", created_at=now, stance="bullish"),
            _make_signal(author="u2", created_at=now + 2000, stance="bullish"),
            _make_signal(author="u3", created_at=now + 5000, stance="bullish"),
        ]
        alerts = detector.detect_bot_network(signals)
        timing_alerts = [
            a for a in alerts
            if a.evidence.get("sub_pattern") == "timing"
        ]
        assert len(timing_alerts) == 0


class TestBotNetworkSimilarTitles:
    def test_identical_titles_different_authors(self, detector):
        now = time.time()
        signals = [
            _make_signal(author="u1", created_at=now, post_title="AAPL to the moon buy now"),
            _make_signal(author="u2", created_at=now + 100, post_title="AAPL to the moon buy now"),
            _make_signal(author="u3", created_at=now + 200, post_title="AAPL to the moon buy now"),
        ]
        alerts = detector.detect_bot_network(signals)
        content_alerts = [
            a for a in alerts
            if a.evidence.get("sub_pattern") == "similar_titles"
        ]
        assert len(content_alerts) >= 1

    def test_different_titles_no_flag(self, detector):
        now = time.time()
        signals = [
            _make_signal(author="u1", created_at=now, post_title="AAPL earnings today"),
            _make_signal(author="u2", created_at=now + 100, post_title="Tesla autopilot update"),
        ]
        alerts = detector.detect_bot_network(signals)
        content_alerts = [
            a for a in alerts
            if a.evidence.get("sub_pattern") == "similar_titles"
        ]
        assert len(content_alerts) == 0

    def test_same_author_not_flagged(self, detector):
        now = time.time()
        signals = [
            _make_signal(author="u1", created_at=now, post_title="AAPL to the moon buy now"),
            _make_signal(author="u1", created_at=now + 100, post_title="AAPL to the moon buy now"),
        ]
        alerts = detector.detect_bot_network(signals)
        content_alerts = [
            a for a in alerts
            if a.evidence.get("sub_pattern") == "similar_titles"
        ]
        assert len(content_alerts) == 0


class TestPumpAndDump:
    def test_high_volume_bullish_signals(self, detector):
        now = time.time()
        # Set up a low baseline
        detector._ticker_baselines["MEME"] = _TickerBaseline()
        detector._ticker_baselines["MEME"].update(1)
        detector._ticker_baselines["MEME"].update(1)

        # Create a volume spike
        signals = [
            _make_signal(
                ticker="MEME", author=f"user{i}",
                created_at=now - 100 + i * 10,
                stance="bullish",
                price_at_signal=10.0,
                price_current=12.0,
            )
            for i in range(10)
        ]
        alerts = detector.detect_pump_and_dump(signals)
        pump_alerts = [a for a in alerts if a.alert_type == "pump_and_dump"]
        assert len(pump_alerts) >= 1
        assert pump_alerts[0].tickers == ["MEME"]

    def test_no_pump_without_baseline_spike(self, detector):
        now = time.time()
        # High baseline means volume isn't unusual
        detector._ticker_baselines["SPY"] = _TickerBaseline()
        for _ in range(10):
            detector._ticker_baselines["SPY"].update(100)

        signals = [
            _make_signal(
                ticker="SPY", author=f"u{i}",
                created_at=now - 100 + i * 10,
                stance="bullish",
            )
            for i in range(5)
        ]
        alerts = detector.detect_pump_and_dump(signals)
        pump_alerts = [a for a in alerts if a.alert_type == "pump_and_dump"]
        assert len(pump_alerts) == 0

    def test_no_pump_if_bearish_majority(self, detector):
        now = time.time()
        detector._ticker_baselines["X"] = _TickerBaseline()
        detector._ticker_baselines["X"].update(1)

        signals = [
            _make_signal(ticker="X", author=f"u{i}", created_at=now - 50 + i, stance="bearish")
            for i in range(10)
        ]
        alerts = detector.detect_pump_and_dump(signals)
        pump_alerts = [a for a in alerts if a.alert_type == "pump_and_dump"]
        assert len(pump_alerts) == 0

    def test_empty_signals(self, detector):
        alerts = detector.detect_pump_and_dump([])
        assert alerts == []


class TestUpdateBaselines:
    def test_creates_baselines(self, detector):
        now = time.time()
        signals = [
            _make_signal(ticker="AAPL", created_at=now - 100),
            _make_signal(ticker="AAPL", created_at=now - 50),
            _make_signal(ticker="TSLA", created_at=now - 30),
        ]
        detector.update_baselines(signals)
        assert "AAPL" in detector.ticker_baselines
        assert "TSLA" in detector.ticker_baselines

    def test_empty_signals(self, detector):
        detector.update_baselines([])
        assert len(detector.ticker_baselines) == 0

    def test_evicts_stale_baselines(self, detector):
        stale_time = time.time() - 31 * 86400
        baseline = _TickerBaseline()
        baseline.last_updated = stale_time
        baseline.signal_counts = [5, 5, 5]
        detector._ticker_baselines["STALE"] = baseline

        now = time.time()
        signals = [_make_signal(ticker="FRESH", created_at=now)]
        detector.update_baselines(signals)

        assert "STALE" not in detector.ticker_baselines
        assert "FRESH" in detector.ticker_baselines


class TestFindTimeClusters:
    def test_single_signal(self, detector):
        clusters = detector._find_time_clusters([_make_signal(created_at=100)], 1800)
        assert clusters == []

    def test_two_signals_in_window(self, detector):
        signals = [
            _make_signal(created_at=100),
            _make_signal(created_at=200),
        ]
        clusters = detector._find_time_clusters(signals, 1800)
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_gap_splits_clusters(self, detector):
        signals = [
            _make_signal(created_at=100),
            _make_signal(created_at=200),
            _make_signal(created_at=5000),
            _make_signal(created_at=5100),
        ]
        clusters = detector._find_time_clusters(signals, 300)
        assert len(clusters) == 2


class TestComputePairwiseDeltas:
    def test_empty_lists(self, detector):
        assert detector._compute_pairwise_deltas([], []) == []
        assert detector._compute_pairwise_deltas([1.0], []) == []
        assert detector._compute_pairwise_deltas([], [1.0]) == []

    def test_exact_match(self, detector):
        deltas = detector._compute_pairwise_deltas([100.0], [100.0])
        assert deltas == [0.0]

    def test_finds_closest(self, detector):
        deltas = detector._compute_pairwise_deltas([100.0], [90.0, 200.0])
        assert deltas == [10.0]  # 100 - 90 = 10

    def test_multiple_timestamps(self, detector):
        ts1 = [100.0, 200.0, 300.0]
        ts2 = [105.0, 195.0, 310.0]
        deltas = detector._compute_pairwise_deltas(ts1, ts2)
        assert len(deltas) == 3
        assert deltas[0] == 5.0    # 100 -> 105
        assert deltas[1] == 5.0    # 200 -> 195
        assert deltas[2] == 10.0   # 300 -> 310


class TestMergePairsIntoGroups:
    def test_empty(self):
        assert ManipulationDetector._merge_pairs_into_groups([]) == []

    def test_single_pair(self):
        groups = ManipulationDetector._merge_pairs_into_groups([("a", "b")])
        assert len(groups) == 1
        assert groups[0] == {"a", "b"}

    def test_connected_pairs(self):
        groups = ManipulationDetector._merge_pairs_into_groups([
            ("a", "b"), ("b", "c"), ("d", "e"),
        ])
        assert len(groups) == 2
        # Find the group containing a
        abc_group = [g for g in groups if "a" in g][0]
        assert abc_group == {"a", "b", "c"}
        de_group = [g for g in groups if "d" in g][0]
        assert de_group == {"d", "e"}

    def test_fully_connected(self):
        groups = ManipulationDetector._merge_pairs_into_groups([
            ("a", "b"), ("b", "c"), ("c", "a"),
        ])
        assert len(groups) == 1
        assert groups[0] == {"a", "b", "c"}


class TestDetectorProperties:
    def test_config_property(self, detector):
        assert detector.config is not None
        assert isinstance(detector.config, ManipulationConfig)

    def test_ticker_baselines_property(self, detector):
        baselines = detector.ticker_baselines
        assert isinstance(baselines, dict)

    def test_ticker_baselines_is_copy(self, detector):
        baselines = detector.ticker_baselines
        baselines["FAKE"] = _TickerBaseline()
        assert "FAKE" not in detector.ticker_baselines


# ═══════════════════════════════════════════════════════════════════════════
# Part 6: Parametrized / Stress Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestParametrized:
    @pytest.mark.parametrize("stance", sorted(STANCES))
    def test_record_all_stances(self, tracker, stance):
        pred = tracker.record_prediction("a1", "reddit", "u", "SPY", stance, 0.5)
        assert pred.stance == stance

    @pytest.mark.parametrize("pnl,capped", [
        (100.0, 50.0),
        (-100.0, -50.0),
        (0.0, 0.0),
        (25.0, 25.0),
        (-25.0, -25.0),
    ])
    def test_pnl_capping(self, tracker, pnl, capped):
        pred = tracker.record_prediction("a1", "reddit", "u", "AAPL", "bullish", 0.8)
        resolved = tracker.resolve_prediction(pred.id, "a1", pnl)
        assert resolved.pnl_pct == capped

    @pytest.mark.parametrize("n_authors", [2, 5, 10, 20])
    def test_coordination_various_group_sizes(self, detector, n_authors):
        now = time.time()
        signals = [
            _make_signal(ticker="GME", author=f"user{i}", created_at=now + i * 5, stance="bullish")
            for i in range(n_authors)
        ]
        alerts = detector.detect_coordinated_posting(signals)
        if n_authors >= 2:
            assert len(alerts) >= 1

    @pytest.mark.parametrize("n_signals", [0, 1, 10, 50, 200])
    def test_detect_all_various_sizes(self, detector, n_signals):
        now = time.time()
        signals = [
            _make_signal(
                ticker="SPY", author=f"user{i % 5}",
                created_at=now + i, stance="bullish",
            )
            for i in range(n_signals)
        ]
        alerts = detector.detect_all(signals)
        assert isinstance(alerts, list)


class TestStress:
    def test_tracker_1000_predictions(self):
        tracker = AuthorTracker(AuthorTrackerConfig(min_predictions_for_score=3))
        for i in range(1000):
            aid = f"author_{i % 20}"
            pred = tracker.record_prediction(aid, "reddit", f"u{i % 20}", "AAPL", "bullish", 0.8)
            tracker.resolve_prediction(pred.id, aid, 5.0 if i % 3 != 0 else -5.0)

        lb = tracker.get_leaderboard(min_predictions=3, limit=10)
        assert len(lb) <= 10
        for p in lb:
            assert p.reputation_score is not None

    def test_detector_500_signals(self):
        det = ManipulationDetector(ManipulationConfig(min_severity_to_report=0.0))
        now = time.time()
        signals = [
            _make_signal(
                ticker=f"T{i % 10}",
                author=f"user{i % 30}",
                created_at=now + i * 10,
                stance="bullish" if i % 2 == 0 else "bearish",
            )
            for i in range(500)
        ]
        alerts = det.detect_all(signals)
        assert isinstance(alerts, list)

    def test_baseline_many_tickers(self):
        det = ManipulationDetector()
        now = time.time()
        signals = [
            _make_signal(ticker=f"TICK{i}", created_at=now - i * 86400)
            for i in range(100)
        ]
        det.update_baselines(signals)
        assert len(det.ticker_baselines) <= 100

    def test_leaderboard_many_authors(self):
        tracker = AuthorTracker(AuthorTrackerConfig(min_predictions_for_score=2))
        for i in range(50):
            aid = f"a_{i}"
            for j in range(5):
                pred = tracker.record_prediction(aid, "reddit", f"u{i}", "SPY", "bullish", 0.8)
                tracker.resolve_prediction(pred.id, aid, 10.0 - i * 0.5)

        lb = tracker.get_leaderboard(min_predictions=2, limit=20)
        assert len(lb) == 20
        # Verify sorted by reputation desc
        for k in range(len(lb) - 1):
            rep_a = lb[k].reputation_score if lb[k].reputation_score is not None else -1
            rep_b = lb[k + 1].reputation_score if lb[k + 1].reputation_score is not None else -1
            assert rep_a >= rep_b
