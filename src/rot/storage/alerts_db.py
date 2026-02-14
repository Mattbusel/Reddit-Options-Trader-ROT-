"""
Email alert settings, digest tracking, X posting mixin.

Provides database operations for:
  - Email alert settings (digest, realtime)
  - X/Twitter post tracking
  - User visit tracking

Assumes self.db (aiosqlite Connection) exists.
"""

import json
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

    # ── Email Alert Settings ──

    async def get_users_for_digest(self) -> List[Dict[str, Any]]:
        """Get users who need a daily digest email."""
        cutoff = time.time() - 86400  # users not emailed in last 24h
        query = """
            SELECT u.id, u.email, u.tier, eas.*
            FROM email_alert_settings eas
            JOIN users u ON eas.user_id = u.id
            WHERE eas.enabled = 1 AND eas.digest_enabled = 1
                  AND eas.last_digest_at < ?
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_users_for_realtime_alert(
        self, ticker: str, stance: str, confidence: float, event_type: str
    ) -> List[Dict[str, Any]]:
        """Get users whose realtime alert filters match a signal."""
        query = """
            SELECT u.id, u.email, u.tier, eas.*
            FROM email_alert_settings eas
            JOIN users u ON eas.user_id = u.id
            WHERE eas.enabled = 1 AND eas.realtime_enabled = 1
                  AND ? >= eas.min_confidence
                  AND u.tier IN ('pro', 'premium', 'ultra', 'enterprise')
        """
        async with self.db.execute(query, (confidence,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                # Parse JSON filter fields
                for key in ("tickers", "stances", "event_types"):
                    if key in d and isinstance(d[key], str):
                        try:
                            d[key] = json.loads(d[key])
                        except (json.JSONDecodeError, TypeError):
                            d[key] = []
                # Check filter match
                filter_tickers = d.get("tickers", [])
                filter_stances = d.get("stances", [])
                filter_events = d.get("event_types", [])

                if filter_tickers and ticker.upper() not in filter_tickers:
                    continue
                if filter_stances and stance not in filter_stances:
                    continue
                if filter_events and event_type not in filter_events:
                    continue
                results.append(d)
            return results

    async def get_users_with_watchlist_ticker(self, ticker: str) -> List[Dict[str, Any]]:
        """Get paid users who have this ticker on their watchlist (stored in settings JSON)."""
        query = """
            SELECT id, email, tier, settings
            FROM users
            WHERE tier IN ('pro', 'premium', 'ultra', 'enterprise')
        """
        async with self.db.execute(query) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                settings = d.get("settings", "{}")
                if isinstance(settings, str):
                    try:
                        settings = json.loads(settings)
                    except (json.JSONDecodeError, TypeError):
                        settings = {}
                watchlist = settings.get("watchlist", [])
                if isinstance(watchlist, list) and ticker.upper() in [t.upper() for t in watchlist]:
                    results.append(d)
            return results

    async def update_digest_sent(self, user_id: str) -> None:
        """Mark that a digest was sent to the user."""
        await self.db.execute(
            "UPDATE email_alert_settings SET last_digest_at = ? WHERE user_id = ?",
            (time.time(), user_id),
        )
        await self.db.commit()

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
