"""Tests for badge tracking engine."""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock

from rot.gamification.tracker import BadgeTracker
from rot.gamification.types import UserStats, Badge, BadgeProgress
from rot.gamification.badges import BADGE_REGISTRY, get_badge_by_id


@pytest.fixture
def mock_db():
    """Create a mock database for testing."""
    db = MagicMock()

    # Mock common database responses
    db.get_user_stats = AsyncMock(return_value=None)
    db.create_user_stats = AsyncMock()
    db.increment_user_stat = AsyncMock()
    db.update_user_stat = AsyncMock()
    db.get_user_stat_value = AsyncMock(return_value=0)
    db.get_user_badges = AsyncMock(return_value=[])
    db.award_user_badge = AsyncMock()
    db.get_badge_unlock_time = AsyncMock(return_value=None)
    db.create_streak = AsyncMock()
    db.end_active_streak = AsyncMock()
    db.update_active_streak_days = AsyncMock()
    db.get_user_by_id = AsyncMock(return_value={"tier": "free", "created_at": time.time()})
    db.get_trades_today_count = AsyncMock(return_value=0)
    db.get_watchlist_count = AsyncMock(return_value=0)
    db.get_filter_preset_count = AsyncMock(return_value=0)

    return db


@pytest.fixture
def tracker(mock_db):
    """Create a BadgeTracker instance with mock database."""
    return BadgeTracker(mock_db)


# ============================================================================
# Login tracking tests
# ============================================================================


async def test_record_login_first_time(tracker, mock_db):
    """Test recording first login for new user."""
    mock_db.get_user_stats.return_value = None

    result = await tracker.record_login("user_123")

    # Verify user stats were created
    mock_db.create_user_stats.assert_called_once()
    args = mock_db.create_user_stats.call_args[0]
    assert args[0] == "user_123"

    # Verify streak was started
    mock_db.create_streak.assert_called_once()

    # Verify return value
    assert result["login_count"] == 1
    assert result["streak_continued"] is True
    assert result["current_streak"] == 1
    assert isinstance(result["new_badges"], list)


async def test_record_login_increment_count(tracker, mock_db):
    """Test login increments count and updates timestamp."""
    now = time.time()
    yesterday = now - 20 * 3600  # 20 hours ago

    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=10,
        current_streak_days=5,
        longest_streak_days=10,
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=yesterday,
    )

    await tracker.record_login("user_123")

    # Verify login count was incremented
    mock_db.increment_user_stat.assert_called_once_with("user_123", "total_logins", 1)

    # Verify last_login was updated
    calls = mock_db.update_user_stat.call_args_list
    assert any(call[0][1] == "last_login" for call in calls)


async def test_record_login_update_timestamp(tracker, mock_db):
    """Test login updates last_login timestamp."""
    yesterday = time.time() - 20 * 3600

    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=5,
        current_streak_days=3,
        longest_streak_days=5,
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=yesterday,
    )

    before = time.time()
    await tracker.record_login("user_123")
    after = time.time()

    # Check that last_login was updated to a recent timestamp
    calls = [c for c in mock_db.update_user_stat.call_args_list if c[0][1] == "last_login"]
    assert len(calls) > 0
    timestamp = calls[0][0][2]
    assert before <= timestamp <= after


# ============================================================================
# Streak continuation tests
# ============================================================================


async def test_record_login_streak_continues_within_24h(tracker, mock_db):
    """Test streak continues when logging in within 24 hours."""
    now = time.time()
    twenty_hours_ago = now - 20 * 3600

    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=5,
        current_streak_days=4,
        longest_streak_days=10,
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=twenty_hours_ago,
    )

    result = await tracker.record_login("user_123")

    # Verify streak continued
    assert result["streak_continued"] is True
    assert result["current_streak"] == 5

    # Verify streak days were updated
    mock_db.update_active_streak_days.assert_called_once_with("user_123", 5)


async def test_record_login_streak_updates_longest(tracker, mock_db):
    """Test longest streak is updated when current exceeds it."""
    now = time.time()
    yesterday = now - 20 * 3600

    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=15,
        current_streak_days=14,
        longest_streak_days=14,  # Current will become 15 and exceed this
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=yesterday,
    )

    await tracker.record_login("user_123")

    # Verify longest streak was updated to 15
    update_calls = mock_db.update_user_stat.call_args_list
    longest_call = [c for c in update_calls if c[0][1] == "longest_streak_days"]
    assert len(longest_call) == 1
    assert longest_call[0][0][2] == 15


# ============================================================================
# Streak broken tests
# ============================================================================


async def test_record_login_streak_broken_after_24h(tracker, mock_db):
    """Test streak is broken when logging in after 24h gap."""
    now = time.time()
    two_days_ago = now - 50 * 3600  # >24 hours

    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=20,
        current_streak_days=7,
        longest_streak_days=15,
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=two_days_ago,
    )

    result = await tracker.record_login("user_123")

    # Verify streak was broken
    assert result["streak_continued"] is False
    assert result["current_streak"] == 1

    # Verify old streak was ended
    mock_db.end_active_streak.assert_called_once()

    # Verify new streak was started
    mock_db.create_streak.assert_called_once()

    # Verify current_streak_days was reset to 1
    update_calls = mock_db.update_user_stat.call_args_list
    streak_call = [c for c in update_calls if c[0][1] == "current_streak_days"]
    assert len(streak_call) == 1
    assert streak_call[0][0][2] == 1


async def test_check_streak_broken_returns_true_after_24h(tracker, mock_db):
    """Test check_streak_broken detects broken streak."""
    now = time.time()
    two_days_ago = now - 50 * 3600

    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=10,
        current_streak_days=5,
        longest_streak_days=10,
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=two_days_ago,
    )

    result = await tracker.check_streak_broken("user_123")

    assert result is True
    mock_db.end_active_streak.assert_called_once()


async def test_check_streak_broken_returns_false_within_24h(tracker, mock_db):
    """Test check_streak_broken returns False for active streak."""
    now = time.time()
    yesterday = now - 20 * 3600

    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=10,
        current_streak_days=5,
        longest_streak_days=10,
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=yesterday,
    )

    result = await tracker.check_streak_broken("user_123")

    assert result is False
    mock_db.end_active_streak.assert_not_called()


# ============================================================================
# Signal view tracking tests
# ============================================================================


async def test_record_signal_view(tracker, mock_db):
    """Test recording signal view increments counter."""
    await tracker.record_signal_view("user_123", "signal_456")

    mock_db.increment_user_stat.assert_called_once_with("user_123", "signals_viewed", 1)


async def test_record_signal_view_evaluates_badges(tracker, mock_db):
    """Test signal view triggers badge evaluation."""
    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=1,
        current_streak_days=1,
        longest_streak_days=1,
        signals_viewed=49,  # One away from badge
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=time.time(),
    )

    await tracker.record_signal_view("user_123", "signal_456")

    # Badge evaluation should be called
    mock_db.get_user_stats.assert_called()


# ============================================================================
# Trade execution tracking tests
# ============================================================================


async def test_record_trade_executed(tracker, mock_db):
    """Test recording trade execution increments counter."""
    await tracker.record_trade_executed("user_123", "trade_789")

    mock_db.increment_user_stat.assert_called_with("user_123", "trades_executed", 1)


async def test_record_trade_executed_with_notional_value(tracker, mock_db):
    """Test recording trade with notional value updates max."""
    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=1,
        current_streak_days=1,
        longest_streak_days=1,
        signals_viewed=0,
        trades_executed=5,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=time.time(),
    )
    mock_db.get_user_stat_value.return_value = 5000.0  # Previous max

    await tracker.record_trade_executed("user_123", "trade_789", notional_value=15000.0)

    # Should update max_trade_notional
    update_calls = mock_db.update_user_stat.call_args_list
    notional_calls = [c for c in update_calls if c[0][1] == "max_trade_notional"]
    assert len(notional_calls) == 1
    assert notional_calls[0][0][2] == 15000.0


async def test_record_trade_executed_does_not_update_lower_notional(tracker, mock_db):
    """Test trade with lower notional doesn't update max."""
    stats_dict = {
        "max_trade_notional": 20000.0
    }

    mock_stats = UserStats(
        user_id="user_123",
        total_logins=1,
        current_streak_days=1,
        longest_streak_days=1,
        signals_viewed=0,
        trades_executed=5,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=time.time(),
    )
    mock_stats.to_dict = lambda: stats_dict

    mock_db.get_user_stats.return_value = mock_stats

    await tracker.record_trade_executed("user_123", "trade_789", notional_value=5000.0)

    # Should NOT update max_trade_notional
    update_calls = mock_db.update_user_stat.call_args_list
    notional_calls = [c for c in update_calls if len(c[0]) > 1 and c[0][1] == "max_trade_notional"]
    assert len(notional_calls) == 0


# ============================================================================
# Prediction recording tests
# ============================================================================


async def test_record_prediction_correct(tracker, mock_db):
    """Test recording correct prediction."""
    await tracker.record_prediction("user_123", "signal_456", correct=True)

    # Should increment both predictions_made and predictions_correct
    calls = mock_db.increment_user_stat.call_args_list
    assert ("user_123", "predictions_made", 1) in [c[0] for c in calls]
    assert ("user_123", "predictions_correct", 1) in [c[0] for c in calls]


async def test_record_prediction_incorrect(tracker, mock_db):
    """Test recording incorrect prediction."""
    await tracker.record_prediction("user_123", "signal_456", correct=False)

    # Should only increment predictions_made
    calls = mock_db.increment_user_stat.call_args_list
    assert ("user_123", "predictions_made", 1) in [c[0] for c in calls]

    # Should NOT increment predictions_correct
    assert ("user_123", "predictions_correct", 1) not in [c[0] for c in calls]


async def test_record_prediction_correct_tracks_consecutive(tracker, mock_db):
    """Test consecutive correct predictions are tracked."""
    mock_db.get_user_stat_value.return_value = 3  # Already 3 in a row

    await tracker.record_prediction("user_123", "signal_456", correct=True)

    # Should update consecutive_correct to 4
    update_calls = mock_db.update_user_stat.call_args_list
    consecutive_calls = [c for c in update_calls if c[0][1] == "consecutive_correct"]
    assert len(consecutive_calls) == 1
    assert consecutive_calls[0][0][2] == 4


async def test_record_prediction_incorrect_resets_consecutive(tracker, mock_db):
    """Test incorrect prediction resets consecutive counter."""
    mock_db.get_user_stat_value.return_value = 4  # Was on a streak

    await tracker.record_prediction("user_123", "signal_456", correct=False)

    # Should reset consecutive_correct to 0
    update_calls = mock_db.update_user_stat.call_args_list
    consecutive_calls = [c for c in update_calls if c[0][1] == "consecutive_correct"]
    assert len(consecutive_calls) == 1
    assert consecutive_calls[0][0][2] == 0


# ============================================================================
# Badge eligibility evaluation tests
# ============================================================================


async def test_evaluate_badge_eligibility_no_stats(tracker, mock_db):
    """Test badge evaluation with no user stats returns empty."""
    mock_db.get_user_stats.return_value = None

    badges = await tracker.evaluate_badge_eligibility("user_123")

    assert badges == []


async def test_evaluate_badge_eligibility_already_unlocked(tracker, mock_db):
    """Test already unlocked badges are skipped."""
    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=100,
        current_streak_days=1,
        longest_streak_days=1,
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=10,
        badges_unlocked=1,
        last_login=time.time(),
    )
    mock_db.get_user_badges.return_value = ["first_steps"]  # Already has this

    badges = await tracker.evaluate_badge_eligibility("user_123")

    # Should not award first_steps again
    assert "first_steps" not in badges


async def test_evaluate_badge_eligibility_meets_criteria(tracker, mock_db):
    """Test badge is awarded when criteria are met."""
    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=1,
        current_streak_days=1,
        longest_streak_days=1,
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=time.time(),
    )
    mock_db.get_user_badges.return_value = []

    badges = await tracker.evaluate_badge_eligibility("user_123")

    # Should award first_steps badge
    assert "first_steps" in badges


# ============================================================================
# Badge awarding tests
# ============================================================================


async def test_award_badge_success(tracker, mock_db):
    """Test successfully awarding a badge."""
    mock_db.get_user_badges.return_value = []

    result = await tracker.award_badge("user_123", "first_steps")

    assert result is True
    mock_db.award_user_badge.assert_called_once()


async def test_award_badge_prevents_duplicates(tracker, mock_db):
    """Test badge cannot be awarded twice."""
    mock_db.get_user_badges.return_value = ["first_steps"]

    result = await tracker.award_badge("user_123", "first_steps")

    assert result is False
    mock_db.award_user_badge.assert_not_called()


async def test_award_badge_updates_stats(tracker, mock_db):
    """Test awarding badge updates user stats."""
    mock_db.get_user_badges.return_value = []

    await tracker.award_badge("user_123", "first_steps")

    # Should increment badges_unlocked and total_badge_points
    calls = mock_db.increment_user_stat.call_args_list
    assert ("user_123", "badges_unlocked", 1) in [c[0] for c in calls]
    assert ("user_123", "total_badge_points", 10) in [c[0] for c in calls]


# ============================================================================
# Badge progress calculation tests
# ============================================================================


async def test_get_badge_progress_no_stats(tracker, mock_db):
    """Test get_badge_progress with no user stats."""
    mock_db.get_user_stats.return_value = None

    progress = await tracker.get_badge_progress("user_123")

    assert progress == []


async def test_get_badge_progress_locked_badges(tracker, mock_db):
    """Test progress calculation for locked badges."""
    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=3,
        current_streak_days=1,
        longest_streak_days=1,
        signals_viewed=25,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=10,
        badges_unlocked=1,
        last_login=time.time(),
    )
    mock_db.get_user_badges.return_value = ["first_steps"]

    progress_list = await tracker.get_badge_progress("user_123")

    # Find signal_seeker badge (50 signals needed, have 25)
    signal_seeker = [p for p in progress_list if p.badge_id == "signal_seeker"]
    assert len(signal_seeker) == 1
    assert signal_seeker[0].current_value == 25
    assert signal_seeker[0].threshold == 50
    assert signal_seeker[0].progress_pct == 50.0
    assert signal_seeker[0].unlocked is False


async def test_get_badge_progress_unlocked_badges(tracker, mock_db):
    """Test progress shows 100% for unlocked badges."""
    now = time.time()
    mock_db.get_user_stats.return_value = UserStats(
        user_id="user_123",
        total_logins=1,
        current_streak_days=1,
        longest_streak_days=1,
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=10,
        badges_unlocked=1,
        last_login=now,
    )
    mock_db.get_user_badges.return_value = ["first_steps"]
    mock_db.get_badge_unlock_time.return_value = now

    progress_list = await tracker.get_badge_progress("user_123")

    # Find first_steps badge
    first_steps = [p for p in progress_list if p.badge_id == "first_steps"]
    assert len(first_steps) == 1
    assert first_steps[0].progress_pct == 100.0
    assert first_steps[0].unlocked is True
    assert first_steps[0].unlocked_at == now


async def test_get_user_badges(tracker, mock_db):
    """Test getting all user badges."""
    mock_db.get_user_badges.return_value = ["first_steps", "weekly_warrior"]

    badges = await tracker.get_user_badges("user_123")

    assert len(badges) == 2
    assert all(isinstance(b, Badge) for b in badges)
    assert any(b.id == "first_steps" for b in badges)
    assert any(b.id == "weekly_warrior" for b in badges)
