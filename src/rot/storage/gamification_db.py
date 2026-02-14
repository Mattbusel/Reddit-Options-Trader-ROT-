"""
Gamification database mixin.

Provides database methods for badge tracking, user stats, streaks, and leaderboards.
"""

import time
import json
from typing import List, Dict, Optional


class GamificationMixin:
    """
    Database methods for gamification features.

    Tables:
    - user_stats: User activity statistics
    - user_badges: Badge unlock records
    - user_streaks: Login streak history
    """

    async def _init_gamification_tables(self) -> None:
        """Create gamification tables if they don't exist."""
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT PRIMARY KEY,
                total_logins INTEGER DEFAULT 0,
                current_streak_days INTEGER DEFAULT 0,
                longest_streak_days INTEGER DEFAULT 0,
                last_login REAL,
                signals_viewed INTEGER DEFAULT 0,
                trades_executed INTEGER DEFAULT 0,
                predictions_made INTEGER DEFAULT 0,
                predictions_correct INTEGER DEFAULT 0,
                total_badge_points INTEGER DEFAULT 0,
                badges_unlocked INTEGER DEFAULT 0,
                consecutive_correct INTEGER DEFAULT 0,
                max_trade_notional REAL DEFAULT 0.0,
                created_at REAL,
                updated_at REAL
            )
            """
        )

        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_badges (
                user_id TEXT,
                badge_id TEXT,
                unlocked_at REAL,
                PRIMARY KEY (user_id, badge_id)
            )
            """
        )

        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_streaks (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                start_date TEXT,
                end_date TEXT,
                days INTEGER,
                active INTEGER,
                created_at REAL
            )
            """
        )

        # Create indexes
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_badges_user ON user_badges(user_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_badges_badge ON user_badges(badge_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_streaks_user ON user_streaks(user_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_streaks_active ON user_streaks(user_id, active)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_stats_points ON user_stats(total_badge_points DESC)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_stats_streak ON user_stats(current_streak_days DESC)"
        )
        await self.db.commit()

    # === User Stats Methods ===

    async def get_user_stats(self, user_id: str):
        """Get user statistics."""
        from rot.gamification.types import UserStats

        async with self.db.execute(
            "SELECT * FROM user_stats WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return UserStats(
            user_id=row[0],
            total_logins=row[1],
            current_streak_days=row[2],
            longest_streak_days=row[3],
            signals_viewed=row[5],
            trades_executed=row[6],
            predictions_made=row[7],
            predictions_correct=row[8],
            total_badge_points=row[9],
            badges_unlocked=row[10],
            last_login=row[4],
        )

    async def create_user_stats(self, user_id: str, timestamp: float) -> None:
        """Create initial user stats record."""
        await self.db.execute(
            """
            INSERT INTO user_stats (
                user_id, total_logins, current_streak_days, longest_streak_days,
                last_login, signals_viewed, trades_executed, predictions_made,
                predictions_correct, total_badge_points, badges_unlocked,
                consecutive_correct, max_trade_notional, created_at, updated_at
            ) VALUES (?, 1, 1, 1, ?, 0, 0, 0, 0, 0, 0, 0, 0.0, ?, ?)
            """,
            (user_id, timestamp, timestamp, timestamp),
        )
        await self.db.commit()

    async def increment_user_stat(self, user_id: str, stat_name: str, amount: int = 1) -> None:
        """Increment a user stat by a given amount."""
        # Ensure user_stats row exists
        async with self.db.execute("SELECT user_id FROM user_stats WHERE user_id = ?", (user_id,)) as cursor:

            existing = await cursor.fetchone()

        if not existing:
            await self.create_user_stats(user_id, time.time())

        # Update stat
        now = time.time()
        await self.db.execute(
            f"UPDATE user_stats SET {stat_name} = {stat_name} + ?, updated_at = ? WHERE user_id = ?",
            (amount, now, user_id),
        )
        await self.db.commit()

    async def update_user_stat(self, user_id: str, stat_name: str, value: float) -> None:
        """Set a user stat to a specific value."""
        # Ensure user_stats row exists
        async with self.db.execute("SELECT user_id FROM user_stats WHERE user_id = ?", (user_id,)) as cursor:

            existing = await cursor.fetchone()

        if not existing:
            await self.create_user_stats(user_id, time.time())

        # Update stat
        now = time.time()
        await self.db.execute(
            f"UPDATE user_stats SET {stat_name} = ?, updated_at = ? WHERE user_id = ?",
            (value, now, user_id),
        )
        await self.db.commit()

    async def get_user_stat_value(self, user_id: str, stat_name: str) -> Optional[float]:
        """Get a specific user stat value."""
        async with self.db.execute(
            f"SELECT {stat_name} FROM user_stats WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    # === Badge Methods ===

    async def award_user_badge(self, user_id: str, badge_id: str, timestamp: float) -> None:
        """Award a badge to a user."""
        await self.db.execute(
            "INSERT OR IGNORE INTO user_badges (user_id, badge_id, unlocked_at) VALUES (?, ?, ?)",
            (user_id, badge_id, timestamp),
        )
        await self.db.commit()

    async def get_user_badges(self, user_id: str) -> List[str]:
        """Get list of badge IDs unlocked by a user."""
        async with self.db.execute("SELECT badge_id FROM user_badges WHERE user_id = ? ORDER BY unlocked_at", (user_id,)) as cursor:

            rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_badge_unlock_time(self, user_id: str, badge_id: str) -> Optional[float]:
        """Get the timestamp when a badge was unlocked."""
        async with self.db.execute(
            "SELECT unlocked_at FROM user_badges WHERE user_id = ? AND badge_id = ?",
            (user_id, badge_id),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    async def get_badge_holders(self, badge_id: str) -> List[str]:
        """Get all users who have unlocked a specific badge."""
        async with self.db.execute("SELECT user_id FROM user_badges WHERE badge_id = ? ORDER BY unlocked_at", (badge_id,)) as cursor:

            rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_user_badge_timeline(self, user_id: str) -> List[Dict]:
        """Get chronological badge unlock history."""
        async with self.db.execute("SELECT badge_id, unlocked_at FROM user_badges WHERE user_id = ? ORDER BY unlocked_at", (user_id,)) as cursor:

            rows = await cursor.fetchall()
        return [{"badge_id": row[0], "unlocked_at": row[1]} for row in rows]

    # === Streak Methods ===

    async def create_streak(self, user_id: str, start_date: str) -> None:
        """Create a new login streak."""
        import uuid

        streak_id = str(uuid.uuid4())
        now = time.time()

        await self.db.execute(
            "INSERT INTO user_streaks (id, user_id, start_date, end_date, days, active, created_at) VALUES (?, ?, ?, NULL, 1, 1, ?)",
            (streak_id, user_id, start_date, now),
        )
        await self.db.commit()

    async def end_active_streak(self, user_id: str, end_date: str) -> None:
        """End the currently active streak."""
        await self.db.execute(
            "UPDATE user_streaks SET end_date = ?, active = 0 WHERE user_id = ? AND active = 1",
            (end_date, user_id),
        )
        await self.db.commit()

    async def update_active_streak_days(self, user_id: str, days: int) -> None:
        """Update the day count for the active streak."""
        await self.db.execute(
            "UPDATE user_streaks SET days = ? WHERE user_id = ? AND active = 1",
            (days, user_id),
        )
        await self.db.commit()

    async def get_active_streak(self, user_id: str) -> Optional[Dict]:
        """Get the current active streak."""
        async with self.db.execute(
            "SELECT id, start_date, days FROM user_streaks WHERE user_id = ? AND active = 1",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return {"id": row[0], "start_date": row[1], "days": row[2]}

    # === Leaderboard Methods ===

    async def get_badge_leaderboard(self, sort_by: str, limit: int) -> List[Dict]:
        """Get top users on badge leaderboards."""
        if sort_by == "points":
            async with self.db.execute(
                """
                SELECT user_id, total_badge_points, badges_unlocked
                FROM user_stats
                WHERE total_badge_points > 0
                ORDER BY total_badge_points DESC, badges_unlocked DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
            return [
                {
                    "user_id": row[0],
                    "total_badge_points": row[1],
                    "badges_unlocked": row[2],
                }
                for row in rows
            ]
        elif sort_by == "streak":
            async with self.db.execute(
                """
                SELECT user_id, current_streak_days, longest_streak_days
                FROM user_stats
                WHERE current_streak_days > 0
                ORDER BY current_streak_days DESC, longest_streak_days DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
            return [
                {
                    "user_id": row[0],
                    "current_streak_days": row[1],
                    "longest_streak_days": row[2],
                }
                for row in rows
            ]
        elif sort_by == "badges":
            async with self.db.execute(
                """
                SELECT user_id, badges_unlocked, total_badge_points
                FROM user_stats
                WHERE badges_unlocked > 0
                ORDER BY badges_unlocked DESC, total_badge_points DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
            return [
                {
                    "user_id": row[0],
                    "badges_unlocked": row[1],
                    "total_badge_points": row[2],
                }
                for row in rows
            ]
        else:
            return []

    async def get_user_leaderboard_rank(self, user_id: str, sort_by: str) -> Optional[int]:
        """Get user's rank on a specific leaderboard."""
        if sort_by == "points":
            async with self.db.execute(
                """
                SELECT COUNT(*) + 1
                FROM user_stats
                WHERE total_badge_points > (
                    SELECT total_badge_points FROM user_stats WHERE user_id = ?
                )
                """,
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
        elif sort_by == "streak":
            async with self.db.execute(
                """
                SELECT COUNT(*) + 1
                FROM user_stats
                WHERE current_streak_days > (
                    SELECT current_streak_days FROM user_stats WHERE user_id = ?
                )
                """,
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
        elif sort_by == "badges":
            async with self.db.execute(
                """
                SELECT COUNT(*) + 1
                FROM user_stats
                WHERE badges_unlocked > (
                    SELECT badges_unlocked FROM user_stats WHERE user_id = ?
                )
                """,
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
        else:
            return None

        return row[0] if row else None

    async def get_category_badge_leaders(self, category: str, limit: int = 5) -> List[Dict]:
        """Get users with most badges in a specific category."""
        # This requires joining with badge metadata, which is in Python
        # For now, return empty - can be implemented if needed
        return []

    # === Helper Methods ===

    async def get_trades_today_count(self, user_id: str) -> int:
        """Get count of trades executed today."""
        from datetime import datetime, timedelta

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_ts = today_start.timestamp()

        async with self.db.execute(
            """
            SELECT COUNT(*)
            FROM paper_trades
            WHERE user_id = ? AND created_at >= ?
            """,
            (user_id, today_start_ts),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_watchlist_count(self, user_id: str) -> int:
        """Get count of tickers in user's watchlist."""
        # Assuming watchlist is stored in user_settings as JSON
        user = await self.get_user_by_id(user_id)
        if not user:
            return 0

        settings = user.get("settings", {})
        if isinstance(settings, str):
            import json
            settings = json.loads(settings)

        watchlist = settings.get("watchlist", [])
        return len(watchlist) if isinstance(watchlist, list) else 0

    async def get_filter_preset_count(self, user_id: str) -> int:
        """Get count of filter presets created by user."""
        # Assuming filter presets are stored in user_settings as JSON
        user = await self.get_user_by_id(user_id)
        if not user:
            return 0

        settings = user.get("settings", {})
        if isinstance(settings, str):
            import json
            settings = json.loads(settings)

        presets = settings.get("filter_presets", [])
        return len(presets) if isinstance(presets, list) else 0
