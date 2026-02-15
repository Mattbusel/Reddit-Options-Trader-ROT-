"""
Badge tracking engine.

This module tracks user actions and awards badges when unlock criteria are met.
It handles login streaks, activity tracking, and badge eligibility evaluation.
"""

import time
from datetime import datetime

from .badges import BADGE_REGISTRY, get_badge
from .types import Badge, BadgeProgress, UserStats


class BadgeTracker:
    """
    Tracks user actions and awards badges.

    The tracker integrates with the database to record user activity,
    maintain streak tracking, and evaluate badge unlock eligibility.
    """

    def __init__(self, db):
        """
        Initialize the badge tracker.

        Args:
            db: Database instance for persistence
        """
        self.db = db

    async def record_login(self, user_id: str) -> dict:
        """
        Record a user login and update streak tracking.

        Args:
            user_id: User identifier

        Returns:
            Dict with login info and streak status:
            {
                "login_count": int,
                "streak_continued": bool,
                "current_streak": int,
                "new_badges": List[str]
            }
        """
        now = time.time()
        stats = await self.db.get_user_stats(user_id)

        if stats is None:
            # First login ever
            await self.db.create_user_stats(user_id, now)
            await self._start_new_streak(user_id, now)
            new_badges = await self.evaluate_badge_eligibility(user_id)
            return {
                "login_count": 1,
                "streak_continued": True,
                "current_streak": 1,
                "new_badges": new_badges,
            }

        # Calculate time since last login
        time_since_last = now - stats.last_login
        hours_since_last = time_since_last / 3600

        # Update login count
        await self.db.increment_user_stat(user_id, "total_logins", 1)
        await self.db.update_user_stat(user_id, "last_login", now)

        # Check streak status
        if hours_since_last <= 24:
            # Streak continues
            new_streak_days = stats.current_streak_days + 1
            await self.db.update_user_stat(user_id, "current_streak_days", new_streak_days)

            # Update longest streak if necessary
            if new_streak_days > stats.longest_streak_days:
                await self.db.update_user_stat(user_id, "longest_streak_days", new_streak_days)

            # Update active streak record
            await self._update_streak_days(user_id, new_streak_days)

            new_badges = await self.evaluate_badge_eligibility(user_id)
            return {
                "login_count": stats.total_logins + 1,
                "streak_continued": True,
                "current_streak": new_streak_days,
                "new_badges": new_badges,
            }
        else:
            # Streak broken - end current streak and start new one
            await self._end_current_streak(user_id, now)
            await self._start_new_streak(user_id, now)
            await self.db.update_user_stat(user_id, "current_streak_days", 1)

            new_badges = await self.evaluate_badge_eligibility(user_id)
            return {
                "login_count": stats.total_logins + 1,
                "streak_continued": False,
                "current_streak": 1,
                "new_badges": new_badges,
            }

    async def record_signal_view(self, user_id: str, signal_id: str) -> None:
        """
        Record a signal view.

        Args:
            user_id: User identifier
            signal_id: Signal identifier
        """
        await self.db.increment_user_stat(user_id, "signals_viewed", 1)
        await self.evaluate_badge_eligibility(user_id)

    async def record_trade_executed(self, user_id: str, trade_id: str, notional_value: float = 0.0) -> None:
        """
        Record a trade execution.

        Args:
            user_id: User identifier
            trade_id: Trade identifier
            notional_value: Trade notional value in dollars
        """
        await self.db.increment_user_stat(user_id, "trades_executed", 1)

        # Track max trade notional for whale badge
        if notional_value > 0:
            stats = await self.db.get_user_stats(user_id)
            current_max = stats.to_dict().get("max_trade_notional", 0) if stats else 0
            if notional_value > current_max:
                await self.db.update_user_stat(user_id, "max_trade_notional", notional_value)

        # Check for day trader badge (10 trades in 1 day)
        await self._check_day_trader_badge(user_id)

        await self.evaluate_badge_eligibility(user_id)

    async def record_prediction(self, user_id: str, signal_id: str, correct: bool) -> None:
        """
        Record a prediction and its outcome.

        Args:
            user_id: User identifier
            signal_id: Signal identifier
            correct: Whether the prediction was correct
        """
        await self.db.increment_user_stat(user_id, "predictions_made", 1)

        if correct:
            await self.db.increment_user_stat(user_id, "predictions_correct", 1)
            # Track consecutive correct for sniper badge
            await self._update_consecutive_correct(user_id, correct=True)
        else:
            # Reset consecutive streak
            await self._update_consecutive_correct(user_id, correct=False)

        await self.evaluate_badge_eligibility(user_id)

    async def check_streak_broken(self, user_id: str) -> bool:
        """
        Check if user's streak should be broken (24h+ since last login).

        Args:
            user_id: User identifier

        Returns:
            True if streak was broken
        """
        stats = await self.db.get_user_stats(user_id)
        if stats is None or stats.current_streak_days == 0:
            return False

        now = time.time()
        time_since_last = now - stats.last_login
        hours_since_last = time_since_last / 3600

        if hours_since_last > 24:
            await self._end_current_streak(user_id, now)
            await self.db.update_user_stat(user_id, "current_streak_days", 0)
            return True

        return False

    async def evaluate_badge_eligibility(self, user_id: str) -> list[str]:
        """
        Evaluate all badges and award any newly unlocked ones.

        Args:
            user_id: User identifier

        Returns:
            List of newly unlocked badge IDs
        """
        stats = await self.db.get_user_stats(user_id)
        if stats is None:
            return []

        unlocked_badges = await self.db.get_user_badges(user_id)
        new_badges = []

        for badge in BADGE_REGISTRY:
            # Skip if already unlocked
            if badge.id in unlocked_badges:
                continue

            # Check eligibility
            if await self._check_badge_criteria(user_id, badge, stats):
                await self.award_badge(user_id, badge.id)
                new_badges.append(badge.id)

        return new_badges

    async def award_badge(self, user_id: str, badge_id: str) -> bool:
        """
        Award a badge to a user.

        Args:
            user_id: User identifier
            badge_id: Badge identifier

        Returns:
            True if badge was awarded (False if already unlocked)
        """
        # Check if already unlocked
        unlocked = await self.db.get_user_badges(user_id)
        if badge_id in unlocked:
            return False

        # Award badge
        now = time.time()
        await self.db.award_user_badge(user_id, badge_id, now)

        # Update stats
        badge = get_badge(badge_id)
        if badge:
            await self.db.increment_user_stat(user_id, "badges_unlocked", 1)
            await self.db.increment_user_stat(user_id, "total_badge_points", badge.points)

        return True

    async def get_user_badges(self, user_id: str) -> list[Badge]:
        """
        Get all badges unlocked by a user.

        Args:
            user_id: User identifier

        Returns:
            List of Badge objects
        """
        badge_ids = await self.db.get_user_badges(user_id)
        return [get_badge(bid) for bid in badge_ids if get_badge(bid)]

    async def get_badge_progress(self, user_id: str) -> list[BadgeProgress]:
        """
        Get progress toward each locked badge.

        Args:
            user_id: User identifier

        Returns:
            List of BadgeProgress objects for all badges (locked and unlocked)
        """
        stats = await self.db.get_user_stats(user_id)
        unlocked_badges = await self.db.get_user_badges(user_id)
        progress_list = []

        for badge in BADGE_REGISTRY:
            if badge.id in unlocked_badges:
                # Already unlocked
                unlock_time = await self.db.get_badge_unlock_time(user_id, badge.id)
                progress_list.append(
                    BadgeProgress(
                        badge_id=badge.id,
                        user_id=user_id,
                        current_value=badge.unlock_criteria["threshold"],
                        threshold=badge.unlock_criteria["threshold"],
                        progress_pct=100.0,
                        unlocked=True,
                        unlocked_at=unlock_time,
                    )
                )
            else:
                # Calculate progress
                if stats is None:
                    # No stats yet - show all badges at 0% progress
                    threshold = badge.unlock_criteria.get("threshold", 1)
                    progress_list.append(
                        BadgeProgress(
                            badge_id=badge.id,
                            user_id=user_id,
                            current_value=0,
                            threshold=threshold,
                            progress_pct=0.0,
                            unlocked=False,
                            unlocked_at=None,
                        )
                    )
                else:
                    current_value = await self._get_metric_value(user_id, badge, stats)
                    threshold = badge.unlock_criteria.get("threshold", 1)

                    if isinstance(threshold, str):
                        # String comparison (e.g., tier badges)
                        progress_pct = 100.0 if current_value == threshold else 0.0
                    else:
                        # Numeric comparison
                        progress_pct = min(100.0, (float(current_value) / float(threshold)) * 100)

                    progress_list.append(
                        BadgeProgress(
                            badge_id=badge.id,
                            user_id=user_id,
                            current_value=current_value,
                            threshold=threshold,
                            progress_pct=progress_pct,
                            unlocked=False,
                            unlocked_at=None,
                        )
                    )

        return progress_list

    # === Private Helper Methods ===

    async def _check_badge_criteria(self, user_id: str, badge: Badge, stats: UserStats) -> bool:
        """Check if badge unlock criteria are met."""
        threshold = badge.unlock_criteria.get("threshold")
        reverse = badge.unlock_criteria.get("reverse", False)

        current_value = await self._get_metric_value(user_id, badge, stats)

        if isinstance(threshold, str):
            # String comparison (e.g., tier)
            return current_value == threshold
        else:
            # Numeric comparison
            if reverse:
                # For early adopter badge - account age must be <= threshold
                return float(current_value) <= float(threshold)
            else:
                return float(current_value) >= float(threshold)

    async def _get_metric_value(self, user_id: str, badge: Badge, stats: UserStats):
        """Get the current value for a badge's metric."""
        metric = badge.unlock_criteria.get("metric")

        # Map metrics to stats fields
        metric_map = {
            "total_logins": stats.total_logins,
            "current_streak_days": stats.current_streak_days,
            "longest_streak_days": stats.longest_streak_days,
            "signals_viewed": stats.signals_viewed,
            "trades_executed": stats.trades_executed,
            "predictions_correct": stats.predictions_correct,
            "predictions_made": stats.predictions_made,
        }

        if metric in metric_map:
            return metric_map[metric]

        # Special metrics that need DB queries
        if metric == "tier":
            user = await self.db.get_user_by_id(user_id)
            return user.get("tier", "free") if user else "free"
        elif metric == "consecutive_correct":
            return await self.db.get_user_stat_value(user_id, "consecutive_correct") or 0
        elif metric == "trades_in_day":
            return await self.db.get_trades_today_count(user_id)
        elif metric == "max_trade_notional":
            return await self.db.get_user_stat_value(user_id, "max_trade_notional") or 0
        elif metric == "watchlist_tickers":
            return await self.db.get_watchlist_count(user_id)
        elif metric == "filter_presets":
            return await self.db.get_filter_preset_count(user_id)
        elif metric == "account_age_days":
            user = await self.db.get_user_by_id(user_id)
            if user and user.get("created_at"):
                age_seconds = time.time() - user["created_at"]
                return age_seconds / 86400  # Convert to days
            return 999999  # Very old if no created_at

        return 0

    async def _start_new_streak(self, user_id: str, timestamp: float) -> None:
        """Start a new login streak."""
        date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        await self.db.create_streak(user_id, date_str)

    async def _end_current_streak(self, user_id: str, timestamp: float) -> None:
        """End the current active streak."""
        date_str = datetime.fromtimestamp(timestamp - 86400).strftime("%Y-%m-%d")  # Yesterday
        await self.db.end_active_streak(user_id, date_str)

    async def _update_streak_days(self, user_id: str, days: int) -> None:
        """Update the day count for the active streak."""
        await self.db.update_active_streak_days(user_id, days)

    async def _update_consecutive_correct(self, user_id: str, correct: bool) -> None:
        """Update consecutive correct predictions counter."""
        if correct:
            current = await self.db.get_user_stat_value(user_id, "consecutive_correct") or 0
            await self.db.update_user_stat(user_id, "consecutive_correct", current + 1)
        else:
            await self.db.update_user_stat(user_id, "consecutive_correct", 0)

    async def _check_day_trader_badge(self, user_id: str) -> None:
        """Check if user has executed 10 trades today."""
        # This is handled by evaluate_badge_eligibility via trades_in_day metric
        pass
