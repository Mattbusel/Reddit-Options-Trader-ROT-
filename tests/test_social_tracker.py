"""Tests for rot.social.tracker.AuthorTracker."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import List

import pytest

from rot.social.tracker import AuthorTracker, AuthorTrackerConfig, _NEUTRAL_THRESHOLD
from rot.social.types import AuthorPrediction, AuthorProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AID = "reddit:u_testuser"
_PLATFORM = "reddit"
_USERNAME = "testuser"


def _record(tracker: AuthorTracker, *, stance: str = "bullish", ticker: str = "AAPL",
            confidence: float = 0.7, author_id: str = _AID) -> AuthorPrediction:
    """Shorthand to record a prediction with sensible defaults."""
    return tracker.record_prediction(
        author_id=author_id,
        platform=_PLATFORM,
        username=_USERNAME,
        ticker=ticker,
        stance=stance,
        confidence=confidence,
    )


def _record_and_resolve(tracker: AuthorTracker, *, stance: str = "bullish",
                         pnl_pct: float = 5.0, author_id: str = _AID,
                         ticker: str = "AAPL") -> AuthorPrediction:
    """Record then immediately resolve a prediction."""
    pred = _record(tracker, stance=stance, ticker=ticker, author_id=author_id)
    return tracker.resolve_prediction(pred.id, author_id, pnl_pct)


def _fill_tracker(tracker: AuthorTracker, wins: int, losses: int,
                  author_id: str = _AID) -> None:
    """Populate a tracker with a given number of wins and losses."""
    for _ in range(wins):
        _record_and_resolve(tracker, stance="bullish", pnl_pct=5.0, author_id=author_id)
    for _ in range(losses):
        _record_and_resolve(tracker, stance="bullish", pnl_pct=-5.0, author_id=author_id)


# ===========================================================================
# Config tests
# ===========================================================================

class TestAuthorTrackerConfig:
    """Tests for AuthorTrackerConfig defaults and custom values."""

    def test_defaults(self):
        cfg = AuthorTrackerConfig()
        assert cfg.min_predictions_for_score == 10
        assert cfg.resolution_window_hours == 24
        assert cfg.max_pnl_pct == 50.0

    def test_custom_values(self):
        cfg = AuthorTrackerConfig(
            min_predictions_for_score=5,
            resolution_window_hours=12,
            max_pnl_pct=100.0,
        )
        assert cfg.min_predictions_for_score == 5
        assert cfg.resolution_window_hours == 12
        assert cfg.max_pnl_pct == 100.0

    def test_tracker_uses_default_config_when_none(self):
        tracker = AuthorTracker(config=None)
        assert tracker._config.min_predictions_for_score == 10

    def test_tracker_uses_provided_config(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=3)
        tracker = AuthorTracker(config=cfg)
        assert tracker._config.min_predictions_for_score == 3


# ===========================================================================
# record_prediction
# ===========================================================================

class TestRecordPrediction:
    """Tests for AuthorTracker.record_prediction."""

    def test_creates_prediction_with_correct_fields(self):
        tracker = AuthorTracker()
        pred = tracker.record_prediction(
            author_id=_AID,
            platform="reddit",
            username="testuser",
            ticker="tsla",
            stance="bullish",
            confidence=0.8,
            signal_id="sig_123",
        )
        assert pred.author_id == _AID
        assert pred.ticker == "TSLA"  # uppercased
        assert pred.stance == "bullish"
        assert pred.confidence == 0.8
        assert pred.signal_id == "sig_123"
        assert pred.outcome is None
        assert pred.pnl_pct is None
        assert pred.resolved_at is None
        assert not pred.is_resolved
        assert len(pred.id) == 16

    def test_creates_profile_on_first_prediction(self):
        tracker = AuthorTracker()
        _record(tracker)
        profile = tracker.get_profile(_AID)
        assert profile is not None
        assert profile.id == _AID
        assert profile.platform == "reddit"
        assert profile.username == "testuser"
        assert profile.total_signals == 1

    def test_increments_total_signals_on_subsequent_predictions(self):
        tracker = AuthorTracker()
        _record(tracker)
        _record(tracker, ticker="MSFT")
        profile = tracker.get_profile(_AID)
        assert profile.total_signals == 2

    def test_updates_last_seen(self):
        tracker = AuthorTracker()
        _record(tracker)
        first_profile = tracker.get_profile(_AID)
        time.sleep(0.01)
        _record(tracker, ticker="GOOG")
        second_profile = tracker.get_profile(_AID)
        assert second_profile.last_seen >= first_profile.last_seen

    def test_ticker_uppercased(self):
        tracker = AuthorTracker()
        pred = _record(tracker, ticker="aapl")
        assert pred.ticker == "AAPL"

    def test_signal_id_optional(self):
        tracker = AuthorTracker()
        pred = _record(tracker)
        assert pred.signal_id is None


# ===========================================================================
# resolve_prediction
# ===========================================================================

class TestResolvePrediction:
    """Tests for AuthorTracker.resolve_prediction."""

    def test_bullish_win(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bullish")
        resolved = tracker.resolve_prediction(pred.id, _AID, pnl_pct=5.0)
        assert resolved.outcome == "win"
        assert resolved.pnl_pct == 5.0
        assert resolved.is_win
        assert not resolved.is_loss
        assert resolved.is_resolved
        assert resolved.resolved_at is not None

    def test_bullish_loss(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bullish")
        resolved = tracker.resolve_prediction(pred.id, _AID, pnl_pct=-3.0)
        assert resolved.outcome == "loss"
        assert resolved.pnl_pct == -3.0
        assert resolved.is_loss

    def test_bearish_win(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bearish")
        resolved = tracker.resolve_prediction(pred.id, _AID, pnl_pct=-4.0)
        assert resolved.outcome == "win"
        assert resolved.pnl_pct == -4.0

    def test_bearish_loss(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bearish")
        resolved = tracker.resolve_prediction(pred.id, _AID, pnl_pct=3.0)
        assert resolved.outcome == "loss"
        assert resolved.pnl_pct == 3.0

    def test_neutral_dead_zone(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bullish")
        resolved = tracker.resolve_prediction(pred.id, _AID, pnl_pct=0.1)
        assert resolved.outcome == "neutral"

    def test_neutral_dead_zone_boundary(self):
        """pnl_pct exactly at the threshold boundary is still neutral."""
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bullish")
        resolved = tracker.resolve_prediction(pred.id, _AID, pnl_pct=_NEUTRAL_THRESHOLD - 0.01)
        assert resolved.outcome == "neutral"

    def test_mixed_stance_always_neutral(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="mixed")
        resolved = tracker.resolve_prediction(pred.id, _AID, pnl_pct=10.0)
        assert resolved.outcome == "neutral"

    def test_unknown_stance_always_neutral(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="unknown")
        resolved = tracker.resolve_prediction(pred.id, _AID, pnl_pct=-10.0)
        assert resolved.outcome == "neutral"

    def test_pnl_capped_at_max(self):
        cfg = AuthorTrackerConfig(max_pnl_pct=20.0)
        tracker = AuthorTracker(config=cfg)
        pred = _record(tracker, stance="bullish")
        resolved = tracker.resolve_prediction(pred.id, _AID, pnl_pct=100.0)
        assert resolved.pnl_pct == 20.0

    def test_pnl_capped_negative(self):
        cfg = AuthorTrackerConfig(max_pnl_pct=20.0)
        tracker = AuthorTracker(config=cfg)
        pred = _record(tracker, stance="bullish")
        resolved = tracker.resolve_prediction(pred.id, _AID, pnl_pct=-80.0)
        assert resolved.pnl_pct == -20.0

    def test_profile_win_count_incremented(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bullish")
        tracker.resolve_prediction(pred.id, _AID, pnl_pct=5.0)
        profile = tracker.get_profile(_AID)
        assert profile.win_count == 1
        assert profile.loss_count == 0

    def test_profile_loss_count_incremented(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bullish")
        tracker.resolve_prediction(pred.id, _AID, pnl_pct=-5.0)
        profile = tracker.get_profile(_AID)
        assert profile.win_count == 0
        assert profile.loss_count == 1

    def test_already_resolved_raises(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bullish")
        tracker.resolve_prediction(pred.id, _AID, pnl_pct=5.0)
        with pytest.raises(ValueError, match="already resolved"):
            tracker.resolve_prediction(pred.id, _AID, pnl_pct=2.0)

    def test_missing_author_raises(self):
        tracker = AuthorTracker()
        with pytest.raises(KeyError, match="No predictions for author"):
            tracker.resolve_prediction("fake_id", "fake_author", 5.0)

    def test_missing_prediction_raises(self):
        tracker = AuthorTracker()
        _record(tracker)
        with pytest.raises(KeyError, match="not found for author"):
            tracker.resolve_prediction("nonexistent_pred", _AID, 5.0)


# ===========================================================================
# resolve_predictions_batch
# ===========================================================================

class TestResolvePredictionsBatch:
    """Tests for AuthorTracker.resolve_predictions_batch."""

    def test_resolves_multiple(self):
        tracker = AuthorTracker()
        p1 = _record(tracker, stance="bullish")
        p2 = _record(tracker, stance="bearish", ticker="MSFT")
        results = tracker.resolve_predictions_batch([
            (p1.id, _AID, 5.0),
            (p2.id, _AID, -3.0),
        ])
        assert len(results) == 2
        assert results[0].outcome == "win"
        assert results[1].outcome == "win"

    def test_skips_bad_ids(self):
        tracker = AuthorTracker()
        p1 = _record(tracker, stance="bullish")
        results = tracker.resolve_predictions_batch([
            ("nonexistent", _AID, 5.0),
            (p1.id, _AID, 5.0),
        ])
        assert len(results) == 1
        assert results[0].outcome == "win"

    def test_skips_already_resolved(self):
        tracker = AuthorTracker()
        p1 = _record(tracker, stance="bullish")
        tracker.resolve_prediction(p1.id, _AID, 5.0)
        results = tracker.resolve_predictions_batch([
            (p1.id, _AID, 10.0),
        ])
        assert len(results) == 0

    def test_empty_input(self):
        tracker = AuthorTracker()
        results = tracker.resolve_predictions_batch([])
        assert results == []


# ===========================================================================
# get_profile, get_or_create_profile
# ===========================================================================

class TestProfileAccess:
    """Tests for get_profile and get_or_create_profile."""

    def test_get_profile_returns_none_for_unknown(self):
        tracker = AuthorTracker()
        assert tracker.get_profile("nobody") is None

    def test_get_profile_returns_existing(self):
        tracker = AuthorTracker()
        _record(tracker)
        profile = tracker.get_profile(_AID)
        assert profile is not None
        assert profile.id == _AID

    def test_get_or_create_returns_existing(self):
        tracker = AuthorTracker()
        _record(tracker)
        profile = tracker.get_or_create_profile(_AID, "reddit", "testuser")
        assert profile.total_signals == 1

    def test_get_or_create_creates_new(self):
        tracker = AuthorTracker()
        profile = tracker.get_or_create_profile("new_author", "twitter", "tweeter")
        assert profile.id == "new_author"
        assert profile.platform == "twitter"
        assert profile.username == "tweeter"
        assert profile.total_signals == 0
        # Should be persisted in cache
        assert tracker.get_profile("new_author") is not None


# ===========================================================================
# compute_author_stats
# ===========================================================================

class TestComputeAuthorStats:
    """Tests for AuthorTracker.compute_author_stats."""

    def test_below_threshold_returns_none_stats(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=10)
        tracker = AuthorTracker(config=cfg)
        # Only 5 predictions
        _fill_tracker(tracker, wins=3, losses=2)
        profile = tracker.compute_author_stats(_AID)
        assert profile.accuracy is None
        assert profile.roi_if_followed is None
        assert profile.sharpe is None
        assert profile.reputation_score is None

    def test_at_threshold_computes_stats(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=10)
        tracker = AuthorTracker(config=cfg)
        _fill_tracker(tracker, wins=7, losses=3)
        profile = tracker.compute_author_stats(_AID)
        assert profile.accuracy == pytest.approx(0.7)
        assert profile.roi_if_followed is not None
        assert profile.sharpe is not None
        assert profile.reputation_score is not None

    def test_accuracy_calculation(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)
        _fill_tracker(tracker, wins=8, losses=2)
        profile = tracker.compute_author_stats(_AID)
        assert profile.accuracy == pytest.approx(0.8)
        assert profile.win_count == 8
        assert profile.loss_count == 2

    def test_roi_calculation(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)
        # 2 wins at +5, 1 loss at -5 => mean = (5+5-5)/3 = 5/3
        _record_and_resolve(tracker, stance="bullish", pnl_pct=5.0)
        _record_and_resolve(tracker, stance="bullish", pnl_pct=5.0)
        _record_and_resolve(tracker, stance="bullish", pnl_pct=-5.0)
        profile = tracker.compute_author_stats(_AID)
        assert profile.roi_if_followed == pytest.approx(5.0 / 3.0)

    def test_sharpe_positive(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)
        # Consistent positive returns => positive Sharpe
        for _ in range(10):
            _record_and_resolve(tracker, stance="bullish", pnl_pct=3.0)
        profile = tracker.compute_author_stats(_AID)
        # All returns identical => std=0 => Sharpe=0 (special case)
        assert profile.sharpe == 0.0

    def test_sharpe_with_variance(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)
        _record_and_resolve(tracker, stance="bullish", pnl_pct=10.0)
        _record_and_resolve(tracker, stance="bullish", pnl_pct=-2.0)
        profile = tracker.compute_author_stats(_AID)
        # mean=4, std should be nonzero => positive Sharpe
        assert profile.sharpe is not None
        assert profile.sharpe > 0.0

    def test_reputation_score_in_range(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)
        _fill_tracker(tracker, wins=5, losses=5)
        profile = tracker.compute_author_stats(_AID)
        assert 0.0 <= profile.reputation_score <= 100.0

    def test_missing_author_raises(self):
        tracker = AuthorTracker()
        with pytest.raises(KeyError, match="not found"):
            tracker.compute_author_stats("nonexistent")

    def test_neutral_predictions_not_counted_as_decided(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)
        # 2 neutral + 1 win => only 1 decided, below threshold of 2
        pred1 = _record(tracker, stance="mixed")
        tracker.resolve_prediction(pred1.id, _AID, 5.0)
        pred2 = _record(tracker, stance="unknown")
        tracker.resolve_prediction(pred2.id, _AID, -5.0)
        _record_and_resolve(tracker, stance="bullish", pnl_pct=5.0)
        profile = tracker.compute_author_stats(_AID)
        # Only 1 decided (the bullish win), below threshold of 2
        assert profile.accuracy is None


# ===========================================================================
# get_leaderboard
# ===========================================================================

class TestGetLeaderboard:
    """Tests for AuthorTracker.get_leaderboard."""

    def test_sorted_by_reputation_desc(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)

        # Author A: 80% accuracy
        aid_a = "reddit:u_A"
        _fill_tracker(tracker, wins=8, losses=2, author_id=aid_a)

        # Author B: 50% accuracy
        aid_b = "reddit:u_B"
        for i in range(5):
            tracker.record_prediction(aid_b, "reddit", "B", "AAPL", "bullish", 0.5)
        for i in range(5):
            tracker.record_prediction(aid_b, "reddit", "B", "AAPL", "bullish", 0.5)
        preds_b = tracker.get_predictions(aid_b)
        for i, p in enumerate(preds_b):
            if not p.is_resolved:
                pnl = 5.0 if i < 5 else -5.0
                tracker.resolve_prediction(p.id, aid_b, pnl)

        board = tracker.get_leaderboard(min_predictions=2)
        assert len(board) >= 2
        # Higher accuracy (A) should rank above lower accuracy (B)
        a_idx = next(i for i, p in enumerate(board) if p.id == aid_a)
        b_idx = next(i for i, p in enumerate(board) if p.id == aid_b)
        assert a_idx < b_idx

    def test_min_predictions_filter(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)

        # Author with 5 decided predictions
        _fill_tracker(tracker, wins=3, losses=2)

        # Require 10 => nobody qualifies
        board = tracker.get_leaderboard(min_predictions=10)
        assert len(board) == 0

        # Require 2 => one author qualifies
        board = tracker.get_leaderboard(min_predictions=2)
        assert len(board) == 1

    def test_limit_parameter(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)

        for i in range(5):
            aid = f"reddit:u_author{i}"
            _fill_tracker(tracker, wins=3, losses=2, author_id=aid)

        board = tracker.get_leaderboard(min_predictions=2, limit=3)
        assert len(board) == 3

    def test_empty_tracker(self):
        tracker = AuthorTracker()
        board = tracker.get_leaderboard()
        assert board == []


# ===========================================================================
# get_predictions
# ===========================================================================

class TestGetPredictions:
    """Tests for AuthorTracker.get_predictions."""

    def test_returns_most_recent_first(self):
        tracker = AuthorTracker()
        p1 = _record(tracker, ticker="AAPL")
        time.sleep(0.01)
        p2 = _record(tracker, ticker="MSFT")
        preds = tracker.get_predictions(_AID)
        assert preds[0].ticker == "MSFT"
        assert preds[1].ticker == "AAPL"

    def test_limit(self):
        tracker = AuthorTracker()
        for _ in range(5):
            _record(tracker)
        preds = tracker.get_predictions(_AID, limit=3)
        assert len(preds) == 3

    def test_unknown_author_returns_empty(self):
        tracker = AuthorTracker()
        preds = tracker.get_predictions("nobody")
        assert preds == []


# ===========================================================================
# get_pending_predictions
# ===========================================================================

class TestGetPendingPredictions:
    """Tests for AuthorTracker.get_pending_predictions."""

    def test_age_filter(self):
        tracker = AuthorTracker()
        # Record a prediction with backdated created_at
        pred = _record(tracker, stance="bullish")
        # By default, min_age_hours=1.  Since the prediction was just created,
        # it should NOT appear as pending (too young).
        pending = tracker.get_pending_predictions(min_age_hours=1)
        assert len(pending) == 0

    def test_old_prediction_appears(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bullish")
        # Manually backdate the prediction by replacing it in the cache.
        old_pred = replace(pred, created_at=time.time() - 7200)  # 2h ago
        tracker._predictions[_AID] = [old_pred]
        pending = tracker.get_pending_predictions(min_age_hours=1)
        assert len(pending) == 1
        assert pending[0].id == old_pred.id

    def test_resolved_not_returned(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bullish")
        old_pred = replace(pred, created_at=time.time() - 7200)
        tracker._predictions[_AID] = [old_pred]
        tracker.resolve_prediction(old_pred.id, _AID, 5.0)
        pending = tracker.get_pending_predictions(min_age_hours=1)
        assert len(pending) == 0

    def test_ordered_oldest_first(self):
        tracker = AuthorTracker()
        now = time.time()
        p1 = _record(tracker, ticker="AAPL")
        p2 = _record(tracker, ticker="MSFT")
        # Backdate both
        tracker._predictions[_AID] = [
            replace(p1, created_at=now - 7200),
            replace(p2, created_at=now - 3700),
        ]
        pending = tracker.get_pending_predictions(min_age_hours=1)
        assert len(pending) == 2
        assert pending[0].created_at < pending[1].created_at


# ===========================================================================
# import / export
# ===========================================================================

class TestImportExport:
    """Tests for import_profile, import_prediction, export_profiles, export_predictions."""

    def test_import_profile(self):
        tracker = AuthorTracker()
        profile = AuthorProfile(
            id="reddit:u_imported",
            platform="reddit",
            username="imported",
            total_signals=5,
            win_count=3,
            loss_count=2,
        )
        tracker.import_profile(profile)
        assert tracker.get_profile("reddit:u_imported") is profile

    def test_import_prediction(self):
        tracker = AuthorTracker()
        pred = AuthorPrediction(
            id="pred_001",
            author_id=_AID,
            ticker="NVDA",
            stance="bullish",
            confidence=0.9,
        )
        tracker.import_prediction(pred)
        preds = tracker.get_predictions(_AID)
        assert len(preds) == 1
        assert preds[0].id == "pred_001"

    def test_export_profiles(self):
        tracker = AuthorTracker()
        _record(tracker, author_id="reddit:u_a1")
        tracker.record_prediction("reddit:u_a2", "reddit", "a2", "MSFT", "bearish", 0.5)
        profiles = tracker.export_profiles()
        assert len(profiles) == 2
        ids = {p.id for p in profiles}
        assert "reddit:u_a1" in ids
        assert "reddit:u_a2" in ids

    def test_export_predictions(self):
        tracker = AuthorTracker()
        _record(tracker, ticker="AAPL")
        _record(tracker, ticker="MSFT")
        tracker.record_prediction("reddit:u_other", "reddit", "other", "GOOG", "bearish", 0.5)
        all_preds = tracker.export_predictions()
        assert len(all_preds) == 3
        tickers = {p.ticker for p in all_preds}
        assert tickers == {"AAPL", "MSFT", "GOOG"}

    def test_export_empty(self):
        tracker = AuthorTracker()
        assert tracker.export_profiles() == []
        assert tracker.export_predictions() == []

    def test_round_trip_profile(self):
        """Import a profile, export it, verify identity."""
        tracker = AuthorTracker()
        profile = AuthorProfile(
            id="reddit:u_rt",
            platform="reddit",
            username="rt",
            total_signals=10,
        )
        tracker.import_profile(profile)
        exported = tracker.export_profiles()
        assert len(exported) == 1
        assert exported[0].id == profile.id
        assert exported[0].total_signals == 10

    def test_round_trip_prediction(self):
        """Import a prediction, export it, verify identity."""
        tracker = AuthorTracker()
        pred = AuthorPrediction(
            id="pred_rt",
            author_id="reddit:u_rt",
            ticker="SPY",
            stance="bearish",
            confidence=0.6,
            outcome="win",
            pnl_pct=-3.5,
            resolved_at=time.time(),
        )
        tracker.import_prediction(pred)
        exported = tracker.export_predictions()
        assert len(exported) == 1
        assert exported[0].id == "pred_rt"
        assert exported[0].outcome == "win"


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_tracker_leaderboard(self):
        tracker = AuthorTracker()
        assert tracker.get_leaderboard() == []

    def test_single_prediction(self):
        tracker = AuthorTracker()
        pred = _record(tracker)
        assert tracker.get_predictions(_AID) == [pred]
        assert tracker.export_predictions() == [pred]

    def test_many_predictions_performance(self):
        """Ensure many predictions don't blow up."""
        cfg = AuthorTrackerConfig(min_predictions_for_score=5)
        tracker = AuthorTracker(config=cfg)
        for i in range(100):
            pnl = 3.0 if i % 3 != 0 else -3.0
            _record_and_resolve(tracker, stance="bullish", pnl_pct=pnl)
        profile = tracker.compute_author_stats(_AID)
        assert profile.accuracy is not None
        assert profile.reputation_score is not None
        assert profile.win_count + profile.loss_count == 100
        preds = tracker.get_predictions(_AID)
        assert len(preds) == 100

    def test_zero_pnl_is_neutral(self):
        tracker = AuthorTracker()
        pred = _record(tracker, stance="bullish")
        resolved = tracker.resolve_prediction(pred.id, _AID, 0.0)
        assert resolved.outcome == "neutral"

    def test_multiple_authors_isolated(self):
        """Predictions for different authors don't interfere."""
        tracker = AuthorTracker()
        aid_a = "reddit:u_alpha"
        aid_b = "reddit:u_beta"
        _record_and_resolve(tracker, author_id=aid_a, pnl_pct=5.0)
        _record_and_resolve(tracker, author_id=aid_b, pnl_pct=-5.0)

        pa = tracker.get_profile(aid_a)
        pb = tracker.get_profile(aid_b)
        assert pa.win_count == 1
        assert pa.loss_count == 0
        assert pb.win_count == 0
        assert pb.loss_count == 1

    def test_all_losses_accuracy_zero(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)
        _fill_tracker(tracker, wins=0, losses=5)
        profile = tracker.compute_author_stats(_AID)
        assert profile.accuracy == 0.0

    def test_all_wins_accuracy_one(self):
        cfg = AuthorTrackerConfig(min_predictions_for_score=2)
        tracker = AuthorTracker(config=cfg)
        _fill_tracker(tracker, wins=5, losses=0)
        profile = tracker.compute_author_stats(_AID)
        assert profile.accuracy == 1.0
