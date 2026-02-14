"""
Gamification module for badges, achievements, and user engagement tracking.

This module provides a comprehensive gamification system including:
- Badge definitions and unlock criteria
- User activity tracking (logins, streaks, trades, predictions)
- Badge eligibility evaluation and awarding
- Leaderboards and achievement timelines
"""

from .tracker import BadgeTracker
from .badges import BADGE_REGISTRY, get_badge, get_badge_by_id, get_badges_by_category, get_badges_by_rarity
from .leaderboard import GamificationLeaderboard
from .types import Badge, BadgeProgress, UserStats, Streak

__all__ = [
    "BadgeTracker",
    "BADGE_REGISTRY",
    "get_badge",
    "get_badge_by_id",
    "get_badges_by_category",
    "get_badges_by_rarity",
    "GamificationLeaderboard",
    "Badge",
    "BadgeProgress",
    "UserStats",
    "Streak",
]
