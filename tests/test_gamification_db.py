"""Tests for gamification database mixin."""

import pytest
import time
from rot.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    """Create a test database with schema initialized."""
    database = Database(db_path=str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def test_user(db):
    """Create a test user for gamification tests."""
    user_id = "test_user_123"
    await db.db.execute(
        """INSERT INTO users (id, email, password_hash, tier, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, "test@example.com", "hashed_pw", "pro", time.time()),
    )
    await db.db.commit()
    return user_id


# ============================================================================
# user_stats table CRUD tests
# ============================================================================


async def test_create_user_stats(db, test_user):
    """Test creating initial user stats record."""
    now = time.time()
    await db.create_user_stats(test_user, now)

    stats = await db.get_user_stats(test_user)
    assert stats is not None
    assert stats.user_id == test_user
    assert stats.total_logins == 1
    assert stats.current_streak_days == 1
    assert stats.longest_streak_days == 1
    assert stats.signals_viewed == 0
    assert stats.trades_executed == 0
    assert stats.predictions_made == 0
    assert stats.predictions_correct == 0
    assert stats.total_badge_points == 0
    assert stats.badges_unlocked == 0
    assert stats.last_login == now


async def test_get_user_stats_nonexistent(db):
    """Test getting stats for nonexistent user returns None."""
    stats = await db.get_user_stats("nonexistent_user")
    assert stats is None


async def test_increment_user_stat(db, test_user):
    """Test incrementing a user stat."""
    now = time.time()
    await db.create_user_stats(test_user, now)

    await db.increment_user_stat(test_user, "signals_viewed", 5)

    stats = await db.get_user_stats(test_user)
    assert stats.signals_viewed == 5


async def test_increment_user_stat_creates_if_missing(db):
    """Test increment creates user_stats if it doesn't exist."""
    user_id = "new_user_456"

    await db.increment_user_stat(user_id, "trades_executed", 3)

    stats = await db.get_user_stats(user_id)
    assert stats is not None
    assert stats.trades_executed == 3


async def test_increment_user_stat_multiple_times(db, test_user):
    """Test incrementing a stat multiple times accumulates."""
    now = time.time()
    await db.create_user_stats(test_user, now)

    await db.increment_user_stat(test_user, "predictions_made", 1)
    await db.increment_user_stat(test_user, "predictions_made", 1)
    await db.increment_user_stat(test_user, "predictions_made", 1)

    stats = await db.get_user_stats(test_user)
    assert stats.predictions_made == 3


async def test_update_user_stat(db, test_user):
    """Test setting a user stat to specific value."""
    now = time.time()
    await db.create_user_stats(test_user, now)

    await db.update_user_stat(test_user, "current_streak_days", 15)

    stats = await db.get_user_stats(test_user)
    assert stats.current_streak_days == 15


async def test_update_user_stat_creates_if_missing(db):
    """Test update creates user_stats if it doesn't exist."""
    user_id = "new_user_789"

    await db.update_user_stat(user_id, "longest_streak_days", 20)

    stats = await db.get_user_stats(user_id)
    assert stats is not None
    assert stats.longest_streak_days == 20


async def test_update_user_stat_overwrites(db, test_user):
    """Test update overwrites previous value."""
    now = time.time()
    await db.create_user_stats(test_user, now)

    await db.update_user_stat(test_user, "current_streak_days", 5)
    await db.update_user_stat(test_user, "current_streak_days", 10)

    stats = await db.get_user_stats(test_user)
    assert stats.current_streak_days == 10


async def test_get_user_stat_value(db, test_user):
    """Test getting a specific stat value."""
    now = time.time()
    await db.create_user_stats(test_user, now)
    await db.update_user_stat(test_user, "total_badge_points", 150)

    value = await db.get_user_stat_value(test_user, "total_badge_points")
    assert value == 150


async def test_get_user_stat_value_nonexistent_user(db):
    """Test getting stat value for nonexistent user returns None."""
    value = await db.get_user_stat_value("nonexistent", "signals_viewed")
    assert value is None


# ============================================================================
# user_badges table CRUD tests
# ============================================================================


async def test_award_user_badge(db, test_user):
    """Test awarding a badge to a user."""
    now = time.time()
    await db.award_user_badge(test_user, "first_steps", now)

    badges = await db.get_user_badges(test_user)
    assert "first_steps" in badges
    assert len(badges) == 1


async def test_award_user_badge_dedup_logic(db, test_user):
    """Test awarding same badge twice doesn't create duplicates."""
    now = time.time()
    await db.award_user_badge(test_user, "first_steps", now)
    await db.award_user_badge(test_user, "first_steps", now + 10)

    badges = await db.get_user_badges(test_user)
    assert badges.count("first_steps") == 1


async def test_get_user_badges_empty(db, test_user):
    """Test getting badges for user with no badges."""
    badges = await db.get_user_badges(test_user)
    assert badges == []


async def test_get_user_badges_multiple(db, test_user):
    """Test getting multiple badges for a user."""
    now = time.time()
    await db.award_user_badge(test_user, "first_steps", now)
    await db.award_user_badge(test_user, "weekly_warrior", now + 100)
    await db.award_user_badge(test_user, "signal_seeker", now + 200)

    badges = await db.get_user_badges(test_user)
    assert len(badges) == 3
    assert "first_steps" in badges
    assert "weekly_warrior" in badges
    assert "signal_seeker" in badges


async def test_get_user_badges_ordered_by_unlock_time(db, test_user):
    """Test badges are returned in unlock order."""
    now = time.time()
    await db.award_user_badge(test_user, "badge_c", now + 200)
    await db.award_user_badge(test_user, "badge_a", now)
    await db.award_user_badge(test_user, "badge_b", now + 100)

    badges = await db.get_user_badges(test_user)
    assert badges == ["badge_a", "badge_b", "badge_c"]


async def test_get_badge_unlock_time(db, test_user):
    """Test getting unlock timestamp for a badge."""
    now = time.time()
    await db.award_user_badge(test_user, "first_steps", now)

    unlock_time = await db.get_badge_unlock_time(test_user, "first_steps")
    assert unlock_time == now


async def test_get_badge_unlock_time_nonexistent(db, test_user):
    """Test getting unlock time for badge user doesn't have."""
    unlock_time = await db.get_badge_unlock_time(test_user, "nonexistent_badge")
    assert unlock_time is None


async def test_get_badge_holders(db):
    """Test getting all users who have a specific badge."""
    now = time.time()
    user1 = "user_1"
    user2 = "user_2"
    user3 = "user_3"

    await db.award_user_badge(user1, "weekly_warrior", now)
    await db.award_user_badge(user2, "weekly_warrior", now + 100)
    await db.award_user_badge(user3, "first_steps", now + 200)  # Different badge

    holders = await db.get_badge_holders("weekly_warrior")
    assert len(holders) == 2
    assert user1 in holders
    assert user2 in holders
    assert user3 not in holders


async def test_get_user_badge_timeline(db, test_user):
    """Test getting chronological badge unlock history."""
    now = time.time()
    await db.award_user_badge(test_user, "badge_a", now)
    await db.award_user_badge(test_user, "badge_b", now + 100)
    await db.award_user_badge(test_user, "badge_c", now + 200)

    timeline = await db.get_user_badge_timeline(test_user)
    assert len(timeline) == 3
    assert timeline[0]["badge_id"] == "badge_a"
    assert timeline[1]["badge_id"] == "badge_b"
    assert timeline[2]["badge_id"] == "badge_c"
    assert timeline[0]["unlocked_at"] == now
    assert timeline[1]["unlocked_at"] == now + 100


async def test_get_user_badge_timeline_empty(db, test_user):
    """Test timeline for user with no badges."""
    timeline = await db.get_user_badge_timeline(test_user)
    assert timeline == []


# ============================================================================
# user_streaks table CRUD tests
# ============================================================================


async def test_create_streak(db, test_user):
    """Test creating a new login streak."""
    await db.create_streak(test_user, "2026-02-01")

    streak = await db.get_active_streak(test_user)
    assert streak is not None
    assert streak["start_date"] == "2026-02-01"
    assert streak["days"] == 1


async def test_end_active_streak(db, test_user):
    """Test ending the currently active streak."""
    await db.create_streak(test_user, "2026-02-01")
    await db.update_active_streak_days(test_user, 7)

    await db.end_active_streak(test_user, "2026-02-07")

    streak = await db.get_active_streak(test_user)
    assert streak is None


async def test_update_active_streak_days(db, test_user):
    """Test updating the day count for active streak."""
    await db.create_streak(test_user, "2026-02-01")

    await db.update_active_streak_days(test_user, 10)

    streak = await db.get_active_streak(test_user)
    assert streak["days"] == 10


async def test_get_active_streak_none(db, test_user):
    """Test getting active streak when none exists."""
    streak = await db.get_active_streak(test_user)
    assert streak is None


async def test_create_multiple_streaks_only_one_active(db, test_user):
    """Test only one streak can be active at a time."""
    # Create first streak and end it
    await db.create_streak(test_user, "2026-01-01")
    await db.update_active_streak_days(test_user, 7)
    await db.end_active_streak(test_user, "2026-01-07")

    # Create second streak
    await db.create_streak(test_user, "2026-02-01")

    # Only the second one should be active
    streak = await db.get_active_streak(test_user)
    assert streak is not None
    assert streak["start_date"] == "2026-02-01"


# ============================================================================
# Leaderboard query tests
# ============================================================================


async def test_get_badge_leaderboard_by_points(db):
    """Test badge leaderboard sorted by points."""
    now = time.time()
    await db.create_user_stats("user_a", now)
    await db.create_user_stats("user_b", now)
    await db.create_user_stats("user_c", now)

    await db.update_user_stat("user_a", "total_badge_points", 100)
    await db.update_user_stat("user_b", "total_badge_points", 250)
    await db.update_user_stat("user_c", "total_badge_points", 50)

    leaderboard = await db.get_badge_leaderboard("points", 10)

    assert len(leaderboard) == 3
    assert leaderboard[0]["user_id"] == "user_b"
    assert leaderboard[0]["total_badge_points"] == 250
    assert leaderboard[1]["user_id"] == "user_a"
    assert leaderboard[2]["user_id"] == "user_c"


async def test_get_badge_leaderboard_by_streak(db):
    """Test badge leaderboard sorted by streak."""
    now = time.time()
    await db.create_user_stats("user_a", now)
    await db.create_user_stats("user_b", now)
    await db.create_user_stats("user_c", now)

    await db.update_user_stat("user_a", "current_streak_days", 10)
    await db.update_user_stat("user_b", "current_streak_days", 30)
    await db.update_user_stat("user_c", "current_streak_days", 5)

    leaderboard = await db.get_badge_leaderboard("streak", 10)

    assert len(leaderboard) == 3
    assert leaderboard[0]["user_id"] == "user_b"
    assert leaderboard[0]["current_streak_days"] == 30
    assert leaderboard[1]["user_id"] == "user_a"
    assert leaderboard[2]["user_id"] == "user_c"


async def test_get_badge_leaderboard_by_badges(db):
    """Test badge leaderboard sorted by badge count."""
    now = time.time()
    await db.create_user_stats("user_a", now)
    await db.create_user_stats("user_b", now)
    await db.create_user_stats("user_c", now)

    await db.update_user_stat("user_a", "badges_unlocked", 5)
    await db.update_user_stat("user_b", "badges_unlocked", 12)
    await db.update_user_stat("user_c", "badges_unlocked", 3)

    leaderboard = await db.get_badge_leaderboard("badges", 10)

    assert len(leaderboard) == 3
    assert leaderboard[0]["user_id"] == "user_b"
    assert leaderboard[0]["badges_unlocked"] == 12
    assert leaderboard[1]["user_id"] == "user_a"
    assert leaderboard[2]["user_id"] == "user_c"


async def test_get_badge_leaderboard_limit(db):
    """Test badge leaderboard respects limit."""
    now = time.time()
    for i in range(10):
        user_id = f"user_{i}"
        await db.create_user_stats(user_id, now)
        await db.update_user_stat(user_id, "total_badge_points", i * 10)

    leaderboard = await db.get_badge_leaderboard("points", 5)

    assert len(leaderboard) == 5


async def test_get_badge_leaderboard_excludes_zero_values(db):
    """Test leaderboard excludes users with zero values."""
    now = time.time()
    await db.create_user_stats("user_a", now)
    await db.create_user_stats("user_b", now)

    await db.update_user_stat("user_a", "total_badge_points", 100)
    # user_b has 0 points

    leaderboard = await db.get_badge_leaderboard("points", 10)

    assert len(leaderboard) == 1
    assert leaderboard[0]["user_id"] == "user_a"


async def test_get_badge_leaderboard_invalid_sort_by(db):
    """Test leaderboard returns empty for invalid sort_by."""
    leaderboard = await db.get_badge_leaderboard("invalid", 10)
    assert leaderboard == []


async def test_get_user_leaderboard_rank_by_points(db):
    """Test getting user's rank on points leaderboard."""
    now = time.time()
    await db.create_user_stats("user_a", now)
    await db.create_user_stats("user_b", now)
    await db.create_user_stats("user_c", now)

    await db.update_user_stat("user_a", "total_badge_points", 100)
    await db.update_user_stat("user_b", "total_badge_points", 250)
    await db.update_user_stat("user_c", "total_badge_points", 150)

    rank = await db.get_user_leaderboard_rank("user_c", "points")
    assert rank == 2  # Behind user_b


async def test_get_user_leaderboard_rank_by_streak(db):
    """Test getting user's rank on streak leaderboard."""
    now = time.time()
    await db.create_user_stats("user_a", now)
    await db.create_user_stats("user_b", now)
    await db.create_user_stats("user_c", now)

    await db.update_user_stat("user_a", "current_streak_days", 10)
    await db.update_user_stat("user_b", "current_streak_days", 5)
    await db.update_user_stat("user_c", "current_streak_days", 15)

    rank = await db.get_user_leaderboard_rank("user_c", "streak")
    assert rank == 1  # Top of leaderboard


async def test_get_user_leaderboard_rank_by_badges(db):
    """Test getting user's rank on badges leaderboard."""
    now = time.time()
    await db.create_user_stats("user_a", now)
    await db.create_user_stats("user_b", now)

    await db.update_user_stat("user_a", "badges_unlocked", 8)
    await db.update_user_stat("user_b", "badges_unlocked", 12)

    rank = await db.get_user_leaderboard_rank("user_a", "badges")
    assert rank == 2


async def test_get_user_leaderboard_rank_invalid_sort_by(db, test_user):
    """Test getting rank with invalid sort_by returns None."""
    rank = await db.get_user_leaderboard_rank(test_user, "invalid")
    assert rank is None


# ============================================================================
# Helper method tests
# ============================================================================


async def test_get_trades_today_count(db, test_user):
    """Test getting count of trades executed today."""
    # Note: This test assumes paper_trades table exists
    # For now, just verify it doesn't crash
    count = await db.get_trades_today_count(test_user)
    assert isinstance(count, int)
    assert count >= 0


async def test_get_watchlist_count(db, test_user):
    """Test getting count of watchlist tickers."""
    count = await db.get_watchlist_count(test_user)
    assert isinstance(count, int)
    assert count >= 0


async def test_get_filter_preset_count(db, test_user):
    """Test getting count of filter presets."""
    count = await db.get_filter_preset_count(test_user)
    assert isinstance(count, int)
    assert count >= 0


# ============================================================================
# Integration tests
# ============================================================================


async def test_full_badge_unlock_flow(db, test_user):
    """Test complete flow from stats to badge unlock."""
    now = time.time()

    # Create stats
    await db.create_user_stats(test_user, now)

    # Award first badge
    await db.award_user_badge(test_user, "first_steps", now)

    # Update stats to reflect badge
    await db.increment_user_stat(test_user, "badges_unlocked", 1)
    await db.increment_user_stat(test_user, "total_badge_points", 10)

    # Verify stats
    stats = await db.get_user_stats(test_user)
    assert stats.badges_unlocked == 1
    assert stats.total_badge_points == 10

    # Verify badges
    badges = await db.get_user_badges(test_user)
    assert "first_steps" in badges


async def test_streak_progression(db, test_user):
    """Test streak creation, update, and ending."""
    # Start streak
    await db.create_streak(test_user, "2026-02-01")

    # Update for 7 days
    await db.update_active_streak_days(test_user, 7)

    streak = await db.get_active_streak(test_user)
    assert streak["days"] == 7

    # End streak
    await db.end_active_streak(test_user, "2026-02-07")

    # Verify no active streak
    active = await db.get_active_streak(test_user)
    assert active is None

    # Start new streak
    await db.create_streak(test_user, "2026-02-10")

    new_streak = await db.get_active_streak(test_user)
    assert new_streak is not None
    assert new_streak["start_date"] == "2026-02-10"
    assert new_streak["days"] == 1
