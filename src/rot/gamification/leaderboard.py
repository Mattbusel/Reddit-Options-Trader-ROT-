"""
Gamification leaderboard queries.

This module provides leaderboard functionality for badges, streaks,
and achievement timelines.
"""

from typing import List, Dict, Optional
from .types import UserStats, Badge
from .badges import get_badge


class GamificationLeaderboard:
    """
    Gamification leaderboard queries.

    Provides various leaderboard views for user competition
    and achievement tracking.
    """

    def __init__(self, db):
        """
        Initialize the leaderboard.

        Args:
            db: Database instance
        """
        self.db = db

    async def get_top_by_points(self, limit: int = 10) -> List[Dict]:
        """
        Get top users by total badge points.

        Args:
            limit: Number of users to return

        Returns:
            List of dicts with user_id, total_badge_points, badges_unlocked
        """
        return await self.db.get_badge_leaderboard("points", limit)

    async def get_top_by_streak(self, limit: int = 10) -> List[Dict]:
        """
        Get top users by current login streak.

        Args:
            limit: Number of users to return

        Returns:
            List of dicts with user_id, current_streak_days
        """
        return await self.db.get_badge_leaderboard("streak", limit)

    async def get_top_by_badges(self, limit: int = 10) -> List[Dict]:
        """
        Get top users by number of badges unlocked.

        Args:
            limit: Number of users to return

        Returns:
            List of dicts with user_id, badges_unlocked
        """
        return await self.db.get_badge_leaderboard("badges", limit)

    async def get_rare_badge_holders(self, badge_id: str) -> List[str]:
        """
        Get all users who have unlocked a specific badge.

        Args:
            badge_id: Badge identifier

        Returns:
            List of user IDs
        """
        return await self.db.get_badge_holders(badge_id)

    async def get_achievement_timeline(self, user_id: str) -> List[Dict]:
        """
        Get chronological badge unlock history for a user.

        Args:
            user_id: User identifier

        Returns:
            List of dicts with badge_id, badge_name, unlocked_at, points
            sorted by unlocked_at (oldest first)
        """
        badge_records = await self.db.get_user_badge_timeline(user_id)

        # Enrich with badge details
        timeline = []
        for record in badge_records:
            badge = get_badge(record["badge_id"])
            if badge:
                timeline.append({
                    "badge_id": badge.id,
                    "badge_name": badge.name,
                    "badge_emoji": badge.icon_emoji,
                    "badge_rarity": badge.rarity,
                    "points": badge.points,
                    "unlocked_at": record["unlocked_at"],
                })

        return timeline

    async def get_top_by(self, sort_by: str, limit: int) -> List[Dict]:
        """
        Generic top users query.

        Args:
            sort_by: "points", "streak", or "badges"
            limit: Number of users to return

        Returns:
            List of user stat dicts
        """
        if sort_by == "points":
            return await self.get_top_by_points(limit)
        elif sort_by == "streak":
            return await self.get_top_by_streak(limit)
        elif sort_by == "badges":
            return await self.get_top_by_badges(limit)
        else:
            return []

    async def get_user_rank(self, user_id: str, sort_by: str = "points") -> Optional[int]:
        """
        Get user's rank on a specific leaderboard.

        Args:
            user_id: User identifier
            sort_by: "points", "streak", or "badges"

        Returns:
            Rank (1-indexed) or None if not ranked
        """
        return await self.db.get_user_leaderboard_rank(user_id, sort_by)

    async def get_category_leaders(self, category: str, limit: int = 5) -> List[Dict]:
        """
        Get users with most badges in a specific category.

        Args:
            category: Badge category (activity, streak, trading, accuracy, social, premium)
            limit: Number of users to return

        Returns:
            List of dicts with user_id, category_badge_count
        """
        return await self.db.get_category_badge_leaders(category, limit)
