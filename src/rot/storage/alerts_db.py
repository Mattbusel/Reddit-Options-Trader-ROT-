"""
Email alert settings, digest tracking, X posting mixin.

Provides database operations for:
  - Email alert settings (digest, realtime)
  - X/Twitter post tracking
  - User visit tracking

Assumes self.db (aiosqlite Connection) exists.
"""

import time
from typing import Any, Dict, List, Optional


class AlertsMixin:
    """Email alert settings, digest tracking, X posting. Assumes self.db (aiosqlite Connection) exists."""

    # ── User Visit Tracking ──

    async def update_last_visit(self, user_id: str) -> None:
        """Update the user's last_visit_at timestamp in settings."""
        user = await self.get_user_by_id(user_id)
        if not user:
            return
        settings = user.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
        settings["last_visit_at"] = time.time()
        await self.update_user_settings(user_id, settings)

    # ── X / Twitter posting ──

    async def get_top_signal_for_x_post(
        self, min_confidence: float = 0.7
    ) -> Optional[Dict[str, Any]]:
        """Get the best recent signal that hasn't been posted to X yet.

        Picks the highest-confidence signal from the last 6 hours that:
          - meets the confidence threshold
          - has a tradeable strategy (not 'none')
          - hasn't already been posted
          - isn't the same ticker as the most recent post (avoids repeats)
        """
        cutoff = time.time() - 21600  # last 6 hours

        # Get the most recently posted ticker to avoid back-to-back duplicates
        async with self.db.execute(
            "SELECT ticker FROM x_posts ORDER BY posted_at DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            last_ticker = row[0] if row else None

        query = """
            SELECT id, ticker, stance, confidence, event_type,
                   strategy, time_horizon, created_at, post_title,
                   subreddit, reasoning
            FROM signals
            WHERE created_at > ?
              AND confidence >= ?
              AND strategy != 'none'
              AND ticker != 'UNKNOWN'
              AND id NOT IN (SELECT signal_id FROM x_posts)
        """
        params: list = [cutoff, min_confidence]

        if last_ticker:
            query += " AND ticker != ?"
            params.append(last_ticker)

        query += " ORDER BY confidence DESC, created_at DESC LIMIT 1"

        async with self.db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def record_x_post(
        self, signal_id: str, ticker: str, tweet_id: str, tweet_text: str
    ) -> None:
        """Record that a signal was posted to X/Twitter."""
        await self.db.execute(
            "INSERT INTO x_posts (signal_id, ticker, tweet_id, tweet_text, posted_at) VALUES (?, ?, ?, ?, ?)",
            (signal_id, ticker, tweet_id, tweet_text, time.time()),
        )
        await self.db.commit()
