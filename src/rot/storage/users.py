"""User account management mixin for Database class.

User account management. Assumes self.db (aiosqlite Connection) exists.

This mixin handles operations on the users, subscriptions, and email_alert_settings tables.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional


class UsersMixin:
    """User account management mixin.

    Assumes self.db (aiosqlite Connection) exists.

    Handles operations on:
    - users table (account creation, authentication, settings)
    - subscriptions table (Stripe subscription tracking)
    - email_alert_settings table (email alert preferences)
    """

    # ── User CRUD ──

    async def create_user(self, email: str, password_hash: str) -> Dict[str, Any]:
        """Create a new user account.

        Args:
            email: User email address (unique)
            password_hash: bcrypt password hash

        Returns:
            Dict with user data: id, email, tier, created_at, settings
        """
        user_id = str(uuid.uuid4())[:12]
        now = time.time()
        await self.db.execute(
            "INSERT INTO users (id, email, password_hash, tier, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, password_hash, "free", now),
        )
        await self.db.commit()
        return {"id": user_id, "email": email, "tier": "free", "created_at": now, "settings": {}}

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email address.

        Args:
            email: Email address to look up

        Returns:
            User dict or None if not found
        """
        async with self.db.execute("SELECT * FROM users WHERE email = ?", (email,)) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID.

        Args:
            user_id: User ID to look up

        Returns:
            User dict or None if not found
        """
        async with self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def get_user_by_api_key_hash(self, api_key_hash: str) -> Optional[Dict[str, Any]]:
        """Get user by API key hash.

        Args:
            api_key_hash: SHA-256 hash of API key

        Returns:
            User dict or None if not found
        """
        async with self.db.execute(
            "SELECT * FROM users WHERE api_key_hash = ?", (api_key_hash,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def update_user_tier(self, user_id: str, tier: str) -> None:
        """Update user's subscription tier.

        Args:
            user_id: User ID
            tier: New tier (free/pro/premium/ultra/enterprise)
        """
        await self.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user_id))
        await self.db.commit()

    async def set_user_api_key(self, user_id: str, api_key_hash: str) -> None:
        """Set or update user's API key hash.

        Args:
            user_id: User ID
            api_key_hash: SHA-256 hash of API key
        """
        await self.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?", (api_key_hash, user_id)
        )
        await self.db.commit()

    async def update_user_password(self, user_id: str, password_hash: str) -> None:
        """Update user's password hash.

        Args:
            user_id: User ID
            password_hash: New bcrypt password hash
        """
        await self.db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
        )
        await self.db.commit()

    async def update_user_settings(self, user_id: str, settings: Dict[str, Any]) -> None:
        """Update user's settings JSON.

        Args:
            user_id: User ID
            settings: Settings dict (watchlist, filter_presets, llm_settings, etc.)
        """
        await self.db.execute(
            "UPDATE users SET settings = ? WHERE id = ?", (json.dumps(settings), user_id)
        )
        await self.db.commit()

    # ── Subscriptions ──

    async def upsert_subscription(self, user_id: str, data: Dict[str, Any]) -> None:
        """Create or update a subscription record.

        Args:
            user_id: User ID
            data: Dict with subscription fields (stripe_customer_id, stripe_subscription_id,
                  tier, status, current_period_end)
        """
        now = time.time()
        existing = await self.get_subscription(user_id)
        if existing:
            await self.db.execute(
                """UPDATE subscriptions SET
                    stripe_customer_id = ?, stripe_subscription_id = ?,
                    tier = ?, status = ?, current_period_end = ?, updated_at = ?
                   WHERE user_id = ?""",
                (
                    data.get("stripe_customer_id", existing.get("stripe_customer_id")),
                    data.get("stripe_subscription_id", existing.get("stripe_subscription_id")),
                    data.get("tier", existing.get("tier")),
                    data.get("status", existing.get("status")),
                    data.get("current_period_end", existing.get("current_period_end")),
                    now,
                    user_id,
                ),
            )
        else:
            sub_id = str(uuid.uuid4())[:12]
            await self.db.execute(
                """INSERT INTO subscriptions
                   (id, user_id, stripe_customer_id, stripe_subscription_id,
                    tier, status, current_period_end, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sub_id,
                    user_id,
                    data.get("stripe_customer_id", ""),
                    data.get("stripe_subscription_id", ""),
                    data.get("tier", "free"),
                    data.get("status", "active"),
                    data.get("current_period_end"),
                    now,
                    now,
                ),
            )
        await self.db.commit()

    async def get_subscription(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get subscription record for a user.

        Args:
            user_id: User ID

        Returns:
            Subscription dict or None if not found
        """
        async with self.db.execute(
            "SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def get_subscription_by_stripe_id(
        self, stripe_subscription_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get subscription by Stripe subscription ID.

        Args:
            stripe_subscription_id: Stripe subscription ID

        Returns:
            Subscription dict or None if not found
        """
        async with self.db.execute(
            "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?",
            (stripe_subscription_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    # ── Email Alert Settings ──

    async def upsert_email_alert_settings(
        self, user_id: str, settings: Dict[str, Any]
    ) -> None:
        """Create or update email alert settings for a user.

        Args:
            user_id: User ID
            settings: Dict with alert fields (enabled, digest_enabled, realtime_enabled,
                     min_confidence, tickers, stances, event_types, webhook_url)
        """
        existing = await self.get_email_alert_settings(user_id)
        if existing:
            set_clauses = []
            params = []
            for col in ("enabled", "digest_enabled", "realtime_enabled",
                         "min_confidence", "tickers", "stances", "event_types",
                         "webhook_url"):
                if col in settings:
                    set_clauses.append(f"{col} = ?")
                    val = settings[col]
                    if isinstance(val, (list, dict)):
                        val = json.dumps(val)
                    params.append(val)
            if set_clauses:
                params.append(user_id)
                query = f"UPDATE email_alert_settings SET {', '.join(set_clauses)} WHERE user_id = ?"  # nosec B608 - SQL uses constants only, values parameterized
                await self.db.execute(query, params)
                await self.db.commit()
        else:
            tickers = json.dumps(settings.get("tickers", []))
            stances = json.dumps(settings.get("stances", []))
            event_types = json.dumps(settings.get("event_types", []))
            await self.db.execute(
                """INSERT INTO email_alert_settings
                   (user_id, enabled, digest_enabled, realtime_enabled,
                    min_confidence, tickers, stances, event_types, webhook_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    settings.get("enabled", 0),
                    settings.get("digest_enabled", 1),
                    settings.get("realtime_enabled", 0),
                    settings.get("min_confidence", 0.6),
                    tickers, stances, event_types,
                    settings.get("webhook_url", ""),
                ),
            )
            await self.db.commit()

    async def get_email_alert_settings(
        self, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get email alert settings for a user.

        Args:
            user_id: User ID

        Returns:
            Settings dict with parsed JSON fields or None if not found
        """
        async with self.db.execute(
            "SELECT * FROM email_alert_settings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            for key in ("tickers", "stances", "event_types"):
                if key in d and isinstance(d[key], str):
                    try:
                        d[key] = json.loads(d[key])
                    except (json.JSONDecodeError, TypeError):
                        d[key] = []
            return d

    async def get_users_for_digest(self) -> List[Dict[str, Any]]:
        """Get users who need a daily digest email.

        Returns users where:
        - Email alerts are enabled
        - Digest is enabled
        - Last digest was sent more than 24 hours ago

        Returns:
            List of user dicts with email alert settings joined
        """
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
        """Get users whose realtime alert filters match a signal.

        Filters users by:
        - Realtime alerts enabled
        - Paid tier (pro+)
        - Confidence meets threshold
        - Ticker, stance, event_type match user filters (if set)

        Args:
            ticker: Signal ticker
            stance: Signal stance
            confidence: Signal confidence
            event_type: Signal event type

        Returns:
            List of matching user dicts with parsed filter fields
        """
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
        """Get paid users who have this ticker on their watchlist.

        Watchlist is stored in users.settings JSON under 'watchlist' key.

        Args:
            ticker: Ticker symbol to search for

        Returns:
            List of user dicts with this ticker in their watchlist
        """
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
        """Mark that a digest was sent to the user.

        Updates last_digest_at to current time.

        Args:
            user_id: User ID
        """
        await self.db.execute(
            "UPDATE email_alert_settings SET last_digest_at = ? WHERE user_id = ?",
            (time.time(), user_id),
        )
        await self.db.commit()

    # ── API Usage Tracking ──

    async def track_api_call(self, user_id: str) -> None:
        """Track an API call for rate limiting.

        Args:
            user_id: User ID making the API call
        """
        now = time.time()
        await self.db.execute(
            "INSERT INTO api_usage (user_id, called_at) VALUES (?, ?)",
            (user_id, now),
        )
        await self.db.commit()

    async def record_api_call(self, user_id: str, endpoint: str, ip: str = "") -> None:
        """Record an API call with endpoint and IP tracking.

        Args:
            user_id: User ID making the API call
            endpoint: API endpoint path
            ip: IP address of the caller
        """
        now = time.time()
        await self.db.execute(
            "INSERT INTO api_usage (user_id, endpoint, called_at, ip_address) VALUES (?, ?, ?, ?)",
            (user_id, endpoint, now, ip),
        )
        await self.db.commit()

    async def get_api_call_count(self, user_id: str, since: float) -> int:
        """Get count of API calls since a timestamp.

        Args:
            user_id: User ID
            since: Unix timestamp to count from

        Returns:
            Number of API calls since the timestamp
        """
        async with self.db.execute(
            "SELECT COUNT(*) FROM api_usage WHERE user_id = ? AND called_at > ?",
            (user_id, since),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert sqlite Row to dict, parsing JSON fields.

    Parses JSON fields: settings

    Args:
        row: sqlite Row object

    Returns:
        Dict with parsed JSON fields
    """
    if row is None:
        return {}
    d = dict(row)
    # Only parse settings for user tables (not market_data, reasoning, etc.)
    for key in ("settings",):
        if key in d:
            val = d[key]
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    d[key] = parsed if isinstance(parsed, dict) else {}
                except (json.JSONDecodeError, TypeError):
                    d[key] = {}
            elif not isinstance(val, dict):
                d[key] = {}
    return d
