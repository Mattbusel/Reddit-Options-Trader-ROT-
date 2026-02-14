"""
Gamification types and dataclasses.

This module defines the core data structures for the badge and achievement system,
including badges, user progress, statistics, and streak tracking.
"""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class Badge:
    """
    A badge that can be unlocked by users.

    Attributes:
        id: Unique badge identifier (e.g., "first_steps")
        name: Display name (e.g., "First Steps")
        description: What the badge represents
        category: Badge category for organization
        rarity: Badge rarity level (affects points)
        icon_emoji: Emoji icon for display
        unlock_criteria: Dict with metric and threshold (e.g., {"metric": "login_days", "threshold": 7})
        points: Badge point value (common=10, rare=25, epic=50, legendary=100)
    """
    id: str
    name: str
    description: str
    category: Literal["activity", "streak", "trading", "accuracy", "social", "premium"]
    rarity: Literal["common", "rare", "epic", "legendary"]
    icon_emoji: str
    unlock_criteria: dict
    points: int


@dataclass(frozen=True)
class BadgeProgress:
    """
    User's progress toward unlocking a specific badge.

    Attributes:
        badge_id: Badge being tracked
        user_id: User tracking progress
        current_value: Current metric value
        threshold: Target value to unlock
        progress_pct: Progress percentage (0-100)
        unlocked: Whether badge has been unlocked
        unlocked_at: Unix timestamp of unlock (None if locked)
    """
    badge_id: str
    user_id: str
    current_value: float
    threshold: float
    progress_pct: float
    unlocked: bool
    unlocked_at: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "badge_id": self.badge_id,
            "user_id": self.user_id,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "progress_pct": self.progress_pct,
            "unlocked": self.unlocked,
            "unlocked_at": self.unlocked_at,
        }


@dataclass(frozen=True)
class UserStats:
    """
    Comprehensive user statistics for gamification.

    Tracks all user activity metrics used for badge unlocking
    and leaderboard rankings.

    Attributes:
        user_id: User identifier
        total_logins: Lifetime login count
        current_streak_days: Current consecutive login streak
        longest_streak_days: Longest ever login streak
        signals_viewed: Total signals viewed
        trades_executed: Total trades executed
        predictions_made: Total predictions made
        predictions_correct: Total correct predictions
        total_badge_points: Sum of all unlocked badge points
        badges_unlocked: Count of unlocked badges
        last_login: Unix timestamp of last login
    """
    user_id: str
    total_logins: int
    current_streak_days: int
    longest_streak_days: int
    signals_viewed: int
    trades_executed: int
    predictions_made: int
    predictions_correct: int
    total_badge_points: int
    badges_unlocked: int
    last_login: float

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "user_id": self.user_id,
            "total_logins": self.total_logins,
            "current_streak_days": self.current_streak_days,
            "longest_streak_days": self.longest_streak_days,
            "signals_viewed": self.signals_viewed,
            "trades_executed": self.trades_executed,
            "predictions_made": self.predictions_made,
            "predictions_correct": self.predictions_correct,
            "total_badge_points": self.total_badge_points,
            "badges_unlocked": self.badges_unlocked,
            "last_login": self.last_login,
        }


@dataclass(frozen=True)
class Streak:
    """
    A login streak period.

    Tracks consecutive login days. A streak continues if the user logs in
    within 24 hours of their last login. A gap > 24h ends the current streak.

    Attributes:
        user_id: User identifier
        start_date: Streak start date (YYYY-MM-DD)
        end_date: Streak end date (None if active)
        days: Number of consecutive days
        active: Whether this is the current active streak
    """
    user_id: str
    start_date: str
    end_date: Optional[str]
    days: int
    active: bool

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "user_id": self.user_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "days": self.days,
            "active": self.active,
        }
