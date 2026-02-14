"""
Affiliate database mixin.

Provides database methods for affiliate tracking, commissions, and payouts.
"""

import json
import time
from typing import Any, Dict, List, Optional


class AffiliatesMixin:
    """
    Database methods for affiliate program features.

    Tables:
    - affiliates: Affiliate partner records
    - commissions: Commission records (20% recurring)
    - affiliate_clicks: Referral link click tracking
    - payouts: Payout requests and history
    """

    async def _init_affiliates_tables(self) -> None:
        """Create affiliate tables if they don't exist."""
        # Affiliates table
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS affiliates (
                id TEXT PRIMARY KEY,
                user_id TEXT UNIQUE NOT NULL,
                referral_code TEXT UNIQUE NOT NULL,
                joined_at REAL NOT NULL,
                total_clicks INTEGER DEFAULT 0,
                total_conversions INTEGER DEFAULT 0,
                total_commissions_usd REAL DEFAULT 0.0,
                pending_payout_usd REAL DEFAULT 0.0,
                paid_out_usd REAL DEFAULT 0.0,
                tier_breakdown TEXT DEFAULT '{}',
                status TEXT DEFAULT 'active',
                payment_email TEXT,
                created_at REAL,
                updated_at REAL
            )
            """
        )

        # Commissions table
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS commissions (
                id TEXT PRIMARY KEY,
                affiliate_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                subscription_tier TEXT NOT NULL,
                amount_usd REAL NOT NULL,
                recurring_monthly INTEGER DEFAULT 1,
                accrued_at REAL NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                payout_id TEXT,
                paid_at REAL,
                status TEXT DEFAULT 'pending',
                created_at REAL
            )
            """
        )

        # Affiliate clicks table
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS affiliate_clicks (
                id TEXT PRIMARY KEY,
                affiliate_id TEXT NOT NULL,
                referral_code TEXT NOT NULL,
                clicked_at REAL NOT NULL,
                source TEXT,
                ip_address TEXT,
                converted INTEGER DEFAULT 0,
                converted_at REAL,
                user_id TEXT
            )
            """
        )

        # Payouts table
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS payouts (
                id TEXT PRIMARY KEY,
                affiliate_id TEXT NOT NULL,
                amount_usd REAL NOT NULL,
                commission_ids TEXT NOT NULL,
                requested_at REAL NOT NULL,
                processed_at REAL,
                status TEXT DEFAULT 'pending',
                payment_method TEXT DEFAULT 'paypal',
                payment_email TEXT,
                transaction_id TEXT,
                notes TEXT
            )
            """
        )

        # Create indexes
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_affiliates_user ON affiliates(user_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_affiliates_code ON affiliates(referral_code)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_commissions_affiliate ON commissions(affiliate_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_commissions_user ON commissions(user_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_commissions_status ON commissions(status)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_clicks_affiliate ON affiliate_clicks(affiliate_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_clicks_code ON affiliate_clicks(referral_code)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_clicks_converted ON affiliate_clicks(converted, clicked_at)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_payouts_affiliate ON payouts(affiliate_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_payouts_status ON payouts(status)"
        )
        await self.db.commit()

    # === Affiliate Methods ===

    async def create_affiliate(self, affiliate_data: Dict[str, Any]) -> None:
        """Create a new affiliate record."""
        now = time.time()
        tier_breakdown = json.dumps(affiliate_data.get("tier_breakdown", {}))

        await self.db.execute(
            """
            INSERT INTO affiliates (
                id, user_id, referral_code, joined_at, total_clicks, total_conversions,
                total_commissions_usd, pending_payout_usd, paid_out_usd, tier_breakdown,
                status, payment_email, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                affiliate_data["id"],
                affiliate_data["user_id"],
                affiliate_data["referral_code"],
                affiliate_data["joined_at"],
                affiliate_data.get("total_clicks", 0),
                affiliate_data.get("total_conversions", 0),
                affiliate_data.get("total_commissions_usd", 0.0),
                affiliate_data.get("pending_payout_usd", 0.0),
                affiliate_data.get("paid_out_usd", 0.0),
                tier_breakdown,
                affiliate_data.get("status", "active"),
                affiliate_data.get("payment_email", ""),
                now,
                now,
            ),
        )
        await self.db.commit()

    async def get_affiliate_by_id(self, affiliate_id: str) -> Optional[Dict[str, Any]]:
        """Get affiliate by ID."""
        row = await self.execute_fetchone(
            "SELECT * FROM affiliates WHERE id = ?", (affiliate_id,)
        )
        return self._affiliate_row_to_dict(row) if row else None

    async def get_affiliate_by_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get affiliate by user ID."""
        row = await self.execute_fetchone(
            "SELECT * FROM affiliates WHERE user_id = ?", (user_id,)
        )
        return self._affiliate_row_to_dict(row) if row else None

    async def get_affiliate_by_code(self, referral_code: str) -> Optional[Dict[str, Any]]:
        """Get affiliate by referral code."""
        row = await self.execute_fetchone(
            "SELECT * FROM affiliates WHERE referral_code = ?", (referral_code,)
        )
        return self._affiliate_row_to_dict(row) if row else None

    async def increment_affiliate_clicks(self, affiliate_id: str) -> None:
        """Increment affiliate's total click count."""
        now = time.time()
        await self.db.execute(
            "UPDATE affiliates SET total_clicks = total_clicks + 1, updated_at = ? WHERE id = ?",
            (now, affiliate_id),
        )
        await self.db.commit()

    async def increment_affiliate_conversions(
        self, affiliate_id: str, tier: str
    ) -> None:
        """Increment affiliate's conversion count and update tier breakdown."""
        # Get current tier breakdown
        row = await self.execute_fetchone(
            "SELECT tier_breakdown FROM affiliates WHERE id = ?", (affiliate_id,)
        )
        if not row:
            return

        tier_breakdown = json.loads(row[0]) if row[0] else {}
        tier_breakdown[tier] = tier_breakdown.get(tier, 0) + 1

        now = time.time()
        await self.db.execute(
            """
            UPDATE affiliates
            SET total_conversions = total_conversions + 1,
                tier_breakdown = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(tier_breakdown), now, affiliate_id),
        )
        await self.db.commit()

    async def increment_affiliate_commissions(
        self, affiliate_id: str, amount: float
    ) -> None:
        """Increment affiliate's commission totals."""
        now = time.time()
        await self.db.execute(
            """
            UPDATE affiliates
            SET total_commissions_usd = total_commissions_usd + ?,
                pending_payout_usd = pending_payout_usd + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (amount, amount, now, affiliate_id),
        )
        await self.db.commit()

    async def update_affiliate_payout_balances(
        self, affiliate_id: str, amount: float
    ) -> None:
        """Update affiliate balances after payout (subtract pending, add paid)."""
        now = time.time()
        await self.db.execute(
            """
            UPDATE affiliates
            SET pending_payout_usd = pending_payout_usd - ?,
                paid_out_usd = paid_out_usd + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (amount, amount, now, affiliate_id),
        )
        await self.db.commit()

    # === Click Tracking Methods ===

    async def create_affiliate_click(self, click_data: Dict[str, Any]) -> None:
        """Record a referral link click."""
        await self.db.execute(
            """
            INSERT INTO affiliate_clicks (
                id, affiliate_id, referral_code, clicked_at, source, ip_address,
                converted, converted_at, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                click_data["id"],
                click_data["affiliate_id"],
                click_data["referral_code"],
                click_data["clicked_at"],
                click_data.get("source", ""),
                click_data.get("ip_address", ""),
                0,
                None,
                None,
            ),
        )
        await self.db.commit()

    async def get_recent_unconverted_click(
        self, user_id: str, since: float
    ) -> Optional[Dict[str, Any]]:
        """Get most recent unconverted click for a user within time window."""
        # Note: This assumes we can match user_id to IP or other identifier
        # In reality, you'd need to track user sessions/cookies
        # For now, we'll use a simplified approach
        row = await self.execute_fetchone(
            """
            SELECT * FROM affiliate_clicks
            WHERE converted = 0 AND clicked_at >= ?
            ORDER BY clicked_at DESC
            LIMIT 1
            """,
            (since,),
        )
        return self._click_row_to_dict(row) if row else None

    async def mark_click_converted(
        self, click_id: str, user_id: str, converted_at: float
    ) -> None:
        """Mark a click as converted."""
        await self.db.execute(
            """
            UPDATE affiliate_clicks
            SET converted = 1, converted_at = ?, user_id = ?
            WHERE id = ?
            """,
            (converted_at, user_id, click_id),
        )
        await self.db.commit()

    async def count_affiliate_clicks(
        self, affiliate_id: str, since: Optional[float] = None
    ) -> int:
        """Count clicks for an affiliate, optionally filtered by date."""
        if since:
            row = await self.execute_fetchone(
                "SELECT COUNT(*) FROM affiliate_clicks WHERE affiliate_id = ? AND clicked_at >= ?",
                (affiliate_id, since),
            )
        else:
            row = await self.execute_fetchone(
                "SELECT COUNT(*) FROM affiliate_clicks WHERE affiliate_id = ?",
                (affiliate_id,),
            )
        return row[0] if row else 0

    async def count_affiliate_conversions(
        self, affiliate_id: str, since: Optional[float] = None
    ) -> int:
        """Count conversions for an affiliate, optionally filtered by date."""
        if since:
            row = await self.execute_fetchone(
                "SELECT COUNT(*) FROM affiliate_clicks WHERE affiliate_id = ? AND converted = 1 AND converted_at >= ?",
                (affiliate_id, since),
            )
        else:
            row = await self.execute_fetchone(
                "SELECT COUNT(*) FROM affiliate_clicks WHERE affiliate_id = ? AND converted = 1",
                (affiliate_id,),
            )
        return row[0] if row else 0

    # === Commission Methods ===

    async def create_commission(self, commission_data: Dict[str, Any]) -> None:
        """Create a commission record."""
        now = time.time()
        await self.db.execute(
            """
            INSERT INTO commissions (
                id, affiliate_id, user_id, subscription_tier, amount_usd,
                recurring_monthly, accrued_at, period_start, period_end,
                payout_id, paid_at, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                commission_data["id"],
                commission_data["affiliate_id"],
                commission_data["user_id"],
                commission_data["subscription_tier"],
                commission_data["amount_usd"],
                1 if commission_data.get("recurring_monthly", True) else 0,
                commission_data["accrued_at"],
                commission_data["period_start"],
                commission_data["period_end"],
                None,
                None,
                "pending",
                now,
            ),
        )
        await self.db.commit()

    async def get_affiliate_commissions(
        self,
        affiliate_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get commissions for an affiliate, optionally filtered by date range."""
        if start_date and end_date:
            rows = await self.execute_fetchall(
                """
                SELECT * FROM commissions
                WHERE affiliate_id = ? AND period_start >= ? AND period_end <= ?
                ORDER BY accrued_at DESC
                """,
                (affiliate_id, start_date, end_date),
            )
        else:
            rows = await self.execute_fetchall(
                "SELECT * FROM commissions WHERE affiliate_id = ? ORDER BY accrued_at DESC",
                (affiliate_id,),
            )
        return [self._commission_row_to_dict(row) for row in rows]

    async def get_pending_commissions(self, affiliate_id: str) -> List[Dict[str, Any]]:
        """Get all pending (unpaid) commissions for an affiliate."""
        rows = await self.execute_fetchall(
            "SELECT * FROM commissions WHERE affiliate_id = ? AND status = 'pending' ORDER BY accrued_at",
            (affiliate_id,),
        )
        return [self._commission_row_to_dict(row) for row in rows]

    async def update_commission_status(
        self,
        commission_id: str,
        payout_id: Optional[str] = None,
        paid_at: Optional[float] = None,
        status: str = "paid",
    ) -> None:
        """Update commission status and payment info."""
        await self.db.execute(
            "UPDATE commissions SET payout_id = ?, paid_at = ?, status = ? WHERE id = ?",
            (payout_id, paid_at, status, commission_id),
        )
        await self.db.commit()

    async def get_affiliate_commission_totals(
        self, affiliate_id: str, since: Optional[float] = None
    ) -> Dict[str, float]:
        """Get commission totals (total, pending, paid) for an affiliate."""
        if since:
            row = await self.execute_fetchone(
                """
                SELECT
                    SUM(amount_usd) as total,
                    SUM(CASE WHEN status = 'pending' THEN amount_usd ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'paid' THEN amount_usd ELSE 0 END) as paid
                FROM commissions
                WHERE affiliate_id = ? AND accrued_at >= ?
                """,
                (affiliate_id, since),
            )
        else:
            row = await self.execute_fetchone(
                """
                SELECT
                    SUM(amount_usd) as total,
                    SUM(CASE WHEN status = 'pending' THEN amount_usd ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'paid' THEN amount_usd ELSE 0 END) as paid
                FROM commissions
                WHERE affiliate_id = ?
                """,
                (affiliate_id,),
            )

        if row:
            return {
                "total": row[0] or 0.0,
                "pending": row[1] or 0.0,
                "paid": row[2] or 0.0,
            }
        return {"total": 0.0, "pending": 0.0, "paid": 0.0}

    async def get_affiliate_tier_breakdown(self, affiliate_id: str) -> Dict[str, int]:
        """Get tier breakdown from affiliate record."""
        row = await self.execute_fetchone(
            "SELECT tier_breakdown FROM affiliates WHERE id = ?", (affiliate_id,)
        )
        if row and row[0]:
            return json.loads(row[0])
        return {}

    async def get_active_referral_subscriptions(self) -> List[Dict[str, Any]]:
        """Get all active referral subscriptions for monthly commission processing."""
        # This needs to join with subscriptions table
        # Simplified version - in reality would check subscription status
        rows = await self.execute_fetchall(
            """
            SELECT DISTINCT c.affiliate_id, c.user_id, c.subscription_tier as tier
            FROM commissions c
            WHERE c.status IN ('pending', 'paid')
            AND c.recurring_monthly = 1
            """
        )
        return [
            {"affiliate_id": row[0], "user_id": row[1], "tier": row[2]} for row in rows
        ]

    async def count_active_referrals(self, affiliate_id: str) -> int:
        """Count currently active referred subscriptions."""
        # Simplified - would need to check subscription status in real implementation
        row = await self.execute_fetchone(
            """
            SELECT COUNT(DISTINCT user_id)
            FROM commissions
            WHERE affiliate_id = ? AND status IN ('pending', 'paid') AND recurring_monthly = 1
            """,
            (affiliate_id,),
        )
        return row[0] if row else 0

    # === Payout Methods ===

    async def create_payout(self, payout_data: Dict[str, Any]) -> None:
        """Create a payout request."""
        commission_ids_json = json.dumps(payout_data.get("commission_ids", []))

        await self.db.execute(
            """
            INSERT INTO payouts (
                id, affiliate_id, amount_usd, commission_ids, requested_at,
                processed_at, status, payment_method, payment_email,
                transaction_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payout_data["id"],
                payout_data["affiliate_id"],
                payout_data["amount_usd"],
                commission_ids_json,
                payout_data["requested_at"],
                None,
                "pending",
                payout_data.get("payment_method", "paypal"),
                payout_data.get("payment_email", ""),
                None,
                None,
            ),
        )
        await self.db.commit()

    async def get_payout_by_id(self, payout_id: str) -> Optional[Dict[str, Any]]:
        """Get payout by ID."""
        row = await self.execute_fetchone(
            "SELECT * FROM payouts WHERE id = ?", (payout_id,)
        )
        return self._payout_row_to_dict(row) if row else None

    async def update_payout_status(
        self,
        payout_id: str,
        status: str,
        processed_at: Optional[float] = None,
        transaction_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Update payout status and details."""
        await self.db.execute(
            """
            UPDATE payouts
            SET status = ?, processed_at = ?, transaction_id = ?, notes = ?
            WHERE id = ?
            """,
            (status, processed_at, transaction_id, notes, payout_id),
        )
        await self.db.commit()

    async def get_affiliate_payouts(self, affiliate_id: str) -> List[Dict[str, Any]]:
        """Get all payouts for an affiliate."""
        rows = await self.execute_fetchall(
            "SELECT * FROM payouts WHERE affiliate_id = ? ORDER BY requested_at DESC",
            (affiliate_id,),
        )
        return [self._payout_row_to_dict(row) for row in rows]

    # === Helper Methods ===

    def _affiliate_row_to_dict(self, row) -> Dict[str, Any]:
        """Convert affiliate row to dict."""
        if not row:
            return {}
        tier_breakdown = json.loads(row[9]) if row[9] else {}
        return {
            "id": row[0],
            "user_id": row[1],
            "referral_code": row[2],
            "joined_at": row[3],
            "total_clicks": row[4],
            "total_conversions": row[5],
            "total_commissions_usd": row[6],
            "pending_payout_usd": row[7],
            "paid_out_usd": row[8],
            "tier_breakdown": tier_breakdown,
            "status": row[10],
            "payment_email": row[11],
            "created_at": row[12],
            "updated_at": row[13],
        }

    def _commission_row_to_dict(self, row) -> Dict[str, Any]:
        """Convert commission row to dict."""
        if not row:
            return {}
        return {
            "id": row[0],
            "affiliate_id": row[1],
            "user_id": row[2],
            "subscription_tier": row[3],
            "amount_usd": row[4],
            "recurring_monthly": bool(row[5]),
            "accrued_at": row[6],
            "period_start": row[7],
            "period_end": row[8],
            "payout_id": row[9],
            "paid_at": row[10],
            "status": row[11],
            "created_at": row[12],
        }

    def _click_row_to_dict(self, row) -> Dict[str, Any]:
        """Convert click row to dict."""
        if not row:
            return {}
        return {
            "id": row[0],
            "affiliate_id": row[1],
            "referral_code": row[2],
            "clicked_at": row[3],
            "source": row[4],
            "ip_address": row[5],
            "converted": bool(row[6]),
            "converted_at": row[7],
            "user_id": row[8],
        }

    def _payout_row_to_dict(self, row) -> Dict[str, Any]:
        """Convert payout row to dict."""
        if not row:
            return {}
        commission_ids = json.loads(row[3]) if row[3] else []
        return {
            "id": row[0],
            "affiliate_id": row[1],
            "amount_usd": row[2],
            "commission_ids": commission_ids,
            "requested_at": row[4],
            "processed_at": row[5],
            "status": row[6],
            "payment_method": row[7],
            "payment_email": row[8],
            "transaction_id": row[9],
            "notes": row[10],
        }
