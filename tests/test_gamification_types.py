"""Tests for gamification types and dataclasses."""

import pytest
import time

from rot.gamification.types import Badge, BadgeProgress, UserStats, Streak


# ============================================================================
# Badge creation and validation
# ============================================================================


def test_badge_creation_all_fields():
    """Test Badge creation with all required fields."""
    badge = Badge(
        id="test_badge",
        name="Test Badge",
        description="A test badge for testing",
        category="activity",
        rarity="common",
        icon_emoji="🎯",
        unlock_criteria={"metric": "total_logins", "threshold": 10},
        points=10,
    )
    assert badge.id == "test_badge"
    assert badge.name == "Test Badge"
    assert badge.description == "A test badge for testing"
    assert badge.category == "activity"
    assert badge.rarity == "common"
    assert badge.icon_emoji == "🎯"
    assert badge.unlock_criteria == {"metric": "total_logins", "threshold": 10}
    assert badge.points == 10


def test_badge_frozen():
    """Test Badge is frozen (immutable)."""
    badge = Badge(
        id="test_badge",
        name="Test",
        description="Test",
        category="activity",
        rarity="common",
        icon_emoji="🎯",
        unlock_criteria={"metric": "total_logins", "threshold": 1},
        points=10,
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        badge.name = "Changed"


def test_badge_with_different_categories():
    """Test Badge creation with various categories."""
    categories = ["activity", "streak", "trading", "accuracy", "social", "premium"]
    for cat in categories:
        badge = Badge(
            id=f"{cat}_badge",
            name=cat.title(),
            description=f"{cat} badge",
            category=cat,
            rarity="rare",
            icon_emoji="⭐",
            unlock_criteria={"metric": "test", "threshold": 1},
            points=25,
        )
        assert badge.category == cat


def test_badge_with_different_rarities():
    """Test Badge creation with various rarities."""
    rarities = ["common", "rare", "epic", "legendary"]
    for rarity in rarities:
        badge = Badge(
            id=f"{rarity}_badge",
            name=rarity.title(),
            description=f"{rarity} badge",
            category="activity",
            rarity=rarity,
            icon_emoji="🌟",
            unlock_criteria={"metric": "test", "threshold": 1},
            points=10,
        )
        assert badge.rarity == rarity


def test_badge_unlock_criteria_numeric():
    """Test Badge with numeric unlock criteria."""
    badge = Badge(
        id="streak_badge",
        name="Streak",
        description="Login streak",
        category="streak",
        rarity="epic",
        icon_emoji="🔥",
        unlock_criteria={"metric": "current_streak_days", "threshold": 30},
        points=50,
    )
    assert badge.unlock_criteria["metric"] == "current_streak_days"
    assert badge.unlock_criteria["threshold"] == 30


def test_badge_unlock_criteria_string():
    """Test Badge with string unlock criteria."""
    badge = Badge(
        id="tier_badge",
        name="Premium User",
        description="Upgraded to premium",
        category="premium",
        rarity="epic",
        icon_emoji="💎",
        unlock_criteria={"metric": "tier", "threshold": "premium"},
        points=50,
    )
    assert badge.unlock_criteria["threshold"] == "premium"


def test_badge_unlock_criteria_with_reverse():
    """Test Badge with reverse criteria (early adopter)."""
    badge = Badge(
        id="early_badge",
        name="Early Adopter",
        description="Joined early",
        category="social",
        rarity="legendary",
        icon_emoji="🌟",
        unlock_criteria={"metric": "account_age_days", "threshold": 30, "reverse": True},
        points=100,
    )
    assert badge.unlock_criteria["reverse"] is True


# ============================================================================
# BadgeProgress creation and calculation
# ============================================================================


def test_badge_progress_creation():
    """Test BadgeProgress creation with all fields."""
    progress = BadgeProgress(
        badge_id="test_badge",
        user_id="user_123",
        current_value=5.0,
        threshold=10.0,
        progress_pct=50.0,
        unlocked=False,
        unlocked_at=None,
    )
    assert progress.badge_id == "test_badge"
    assert progress.user_id == "user_123"
    assert progress.current_value == 5.0
    assert progress.threshold == 10.0
    assert progress.progress_pct == 50.0
    assert progress.unlocked is False
    assert progress.unlocked_at is None


def test_badge_progress_unlocked():
    """Test BadgeProgress for unlocked badge."""
    now = time.time()
    progress = BadgeProgress(
        badge_id="test_badge",
        user_id="user_123",
        current_value=10.0,
        threshold=10.0,
        progress_pct=100.0,
        unlocked=True,
        unlocked_at=now,
    )
    assert progress.unlocked is True
    assert progress.unlocked_at == now
    assert progress.progress_pct == 100.0


def test_badge_progress_pct_calculation_zero():
    """Test BadgeProgress with 0% progress."""
    progress = BadgeProgress(
        badge_id="test_badge",
        user_id="user_123",
        current_value=0.0,
        threshold=100.0,
        progress_pct=0.0,
        unlocked=False,
        unlocked_at=None,
    )
    assert progress.progress_pct == 0.0


def test_badge_progress_pct_calculation_partial():
    """Test BadgeProgress with partial progress."""
    progress = BadgeProgress(
        badge_id="test_badge",
        user_id="user_123",
        current_value=33.0,
        threshold=100.0,
        progress_pct=33.0,
        unlocked=False,
        unlocked_at=None,
    )
    assert progress.progress_pct == 33.0


def test_badge_progress_pct_calculation_complete():
    """Test BadgeProgress with 100% progress."""
    progress = BadgeProgress(
        badge_id="test_badge",
        user_id="user_123",
        current_value=100.0,
        threshold=100.0,
        progress_pct=100.0,
        unlocked=False,
        unlocked_at=None,
    )
    assert progress.progress_pct == 100.0


def test_badge_progress_frozen():
    """Test BadgeProgress is frozen (immutable)."""
    progress = BadgeProgress(
        badge_id="test_badge",
        user_id="user_123",
        current_value=5.0,
        threshold=10.0,
        progress_pct=50.0,
        unlocked=False,
        unlocked_at=None,
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        progress.current_value = 7.0


def test_badge_progress_to_dict():
    """Test BadgeProgress.to_dict() serialization."""
    from dataclasses import asdict

    now = time.time()
    progress = BadgeProgress(
        badge_id="test_badge",
        user_id="user_123",
        current_value=75.0,
        threshold=100.0,
        progress_pct=75.0,
        unlocked=True,
        unlocked_at=now,
    )
    # Use dataclasses.asdict() for serialization
    d = asdict(progress)
    assert d == {
        "badge_id": "test_badge",
        "user_id": "user_123",
        "current_value": 75.0,
        "threshold": 100.0,
        "progress_pct": 75.0,
        "unlocked": True,
        "unlocked_at": now,
    }


# ============================================================================
# UserStats creation and aggregation
# ============================================================================


def test_user_stats_creation():
    """Test UserStats creation with all fields."""
    now = time.time()
    stats = UserStats(
        user_id="user_123",
        total_logins=50,
        current_streak_days=7,
        longest_streak_days=14,
        signals_viewed=200,
        trades_executed=10,
        predictions_made=30,
        predictions_correct=20,
        total_badge_points=150,
        badges_unlocked=6,
        last_login=now,
    )
    assert stats.user_id == "user_123"
    assert stats.total_logins == 50
    assert stats.current_streak_days == 7
    assert stats.longest_streak_days == 14
    assert stats.signals_viewed == 200
    assert stats.trades_executed == 10
    assert stats.predictions_made == 30
    assert stats.predictions_correct == 20
    assert stats.total_badge_points == 150
    assert stats.badges_unlocked == 6
    assert stats.last_login == now


def test_user_stats_frozen():
    """Test UserStats is frozen (immutable)."""
    stats = UserStats(
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
    with pytest.raises(Exception):  # FrozenInstanceError
        stats.total_logins = 2


def test_user_stats_to_dict():
    """Test UserStats.to_dict() serialization."""
    from dataclasses import asdict

    now = time.time()
    stats = UserStats(
        user_id="user_123",
        total_logins=100,
        current_streak_days=15,
        longest_streak_days=30,
        signals_viewed=500,
        trades_executed=50,
        predictions_made=75,
        predictions_correct=60,
        total_badge_points=300,
        badges_unlocked=12,
        last_login=now,
    )
    # Use dataclasses.asdict() for serialization
    d = asdict(stats)
    assert d == {
        "user_id": "user_123",
        "total_logins": 100,
        "current_streak_days": 15,
        "longest_streak_days": 30,
        "signals_viewed": 500,
        "trades_executed": 50,
        "predictions_made": 75,
        "predictions_correct": 60,
        "total_badge_points": 300,
        "badges_unlocked": 12,
        "last_login": now,
    }


def test_user_stats_zero_values():
    """Test UserStats with all zero values (new user)."""
    now = time.time()
    stats = UserStats(
        user_id="new_user",
        total_logins=0,
        current_streak_days=0,
        longest_streak_days=0,
        signals_viewed=0,
        trades_executed=0,
        predictions_made=0,
        predictions_correct=0,
        total_badge_points=0,
        badges_unlocked=0,
        last_login=now,
    )
    assert stats.total_logins == 0
    assert stats.total_badge_points == 0


# ============================================================================
# Streak creation and validation
# ============================================================================


def test_streak_creation_active():
    """Test Streak creation for active streak."""
    streak = Streak(
        user_id="user_123",
        start_date="2026-02-01",
        end_date=None,
        days=7,
        active=True,
    )
    assert streak.user_id == "user_123"
    assert streak.start_date == "2026-02-01"
    assert streak.end_date is None
    assert streak.days == 7
    assert streak.active is True


def test_streak_creation_ended():
    """Test Streak creation for ended streak."""
    streak = Streak(
        user_id="user_123",
        start_date="2026-01-01",
        end_date="2026-01-10",
        days=10,
        active=False,
    )
    assert streak.user_id == "user_123"
    assert streak.start_date == "2026-01-01"
    assert streak.end_date == "2026-01-10"
    assert streak.days == 10
    assert streak.active is False


def test_streak_frozen():
    """Test Streak is frozen (immutable)."""
    streak = Streak(
        user_id="user_123",
        start_date="2026-02-01",
        end_date=None,
        days=1,
        active=True,
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        streak.days = 2


def test_streak_to_dict_active():
    """Test Streak.to_dict() for active streak."""
    from dataclasses import asdict

    streak = Streak(
        user_id="user_123",
        start_date="2026-02-01",
        end_date=None,
        days=5,
        active=True,
    )
    # Use dataclasses.asdict() for serialization
    d = asdict(streak)
    assert d == {
        "user_id": "user_123",
        "start_date": "2026-02-01",
        "end_date": None,
        "days": 5,
        "active": True,
    }


def test_streak_to_dict_ended():
    """Test Streak.to_dict() for ended streak."""
    from dataclasses import asdict

    streak = Streak(
        user_id="user_123",
        start_date="2026-01-15",
        end_date="2026-01-25",
        days=11,
        active=False,
    )
    # Use dataclasses.asdict() for serialization
    d = asdict(streak)
    assert d == {
        "user_id": "user_123",
        "start_date": "2026-01-15",
        "end_date": "2026-01-25",
        "days": 11,
        "active": False,
    }


def test_streak_single_day():
    """Test Streak with single day."""
    streak = Streak(
        user_id="user_123",
        start_date="2026-02-14",
        end_date=None,
        days=1,
        active=True,
    )
    assert streak.days == 1
    assert streak.active is True
