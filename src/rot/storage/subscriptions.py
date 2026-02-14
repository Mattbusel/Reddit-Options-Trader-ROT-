"""
Stripe subscription tracking mixin.

Assumes self.db (aiosqlite Connection) exists.
"""
import time
import uuid
from typing import Any, Dict, Optional

__all__ = ["SubscriptionsMixin"]


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert aiosqlite Row to dict."""
    return dict(row) if row else {}


class SubscriptionsMixin:
    """Stripe subscription tracking. Assumes self.db (aiosqlite Connection) exists."""

    # ── Subscriptions ──

    async def upsert_subscription(self, user_id: str, data: Dict[str, Any]) -> None:
        """
        Create or update a subscription record.

        Args:
            user_id: User ID
            data: Dict with optional keys:
                - stripe_customer_id: Stripe customer ID
                - stripe_subscription_id: Stripe subscription ID
                - tier: Subscription tier (free/pro/premium/ultra/enterprise)
                - status: Subscription status (active/canceled/past_due)
                - current_period_end: Unix timestamp of period end
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
        """
        Get subscription by user ID.

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
        """
        Get subscription by Stripe subscription ID.

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

    async def create_subscription(
        self,
        user_id: str,
        stripe_customer_id: str,
        stripe_subscription_id: str,
        tier: str,
        current_period_end: Optional[float] = None,
    ) -> str:
        """
        Create a new subscription record.

        Args:
            user_id: User ID
            stripe_customer_id: Stripe customer ID
            stripe_subscription_id: Stripe subscription ID
            tier: Subscription tier
            current_period_end: Optional Unix timestamp of period end

        Returns:
            Created subscription ID
        """
        await self.upsert_subscription(
            user_id,
            {
                "stripe_customer_id": stripe_customer_id,
                "stripe_subscription_id": stripe_subscription_id,
                "tier": tier,
                "status": "active",
                "current_period_end": current_period_end,
            },
        )
        sub = await self.get_subscription(user_id)
        return sub["id"] if sub else ""

    async def update_subscription_status(
        self,
        user_id: str,
        status: str,
        current_period_end: Optional[float] = None,
    ) -> None:
        """
        Update subscription status.

        Args:
            user_id: User ID
            status: New status (active/canceled/past_due)
            current_period_end: Optional Unix timestamp of period end
        """
        data = {"status": status}
        if current_period_end is not None:
            data["current_period_end"] = current_period_end
        await self.upsert_subscription(user_id, data)

    async def cancel_subscription(self, user_id: str) -> None:
        """
        Cancel a subscription (set status to canceled, keep tier until period ends).

        Args:
            user_id: User ID
        """
        await self.update_subscription_status(user_id, "canceled")

    async def get_active_subscriptions(self) -> list[Dict[str, Any]]:
        """
        Get all active subscriptions.

        Returns:
            List of subscription dicts with status='active'
        """
        async with self.db.execute(
            "SELECT * FROM subscriptions WHERE status = 'active'"
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]
