"""Affiliate engine — manages referral tracking, commission calculation, and payouts."""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from rot.affiliates.types import Affiliate, Commission, Payout, ReferralStats

log = logging.getLogger(__name__)

# Commission rates by tier (20% of monthly subscription)
TIER_COMMISSION_RATES: Dict[str, float] = {
    "pro": 4.00,        # 20% of $20/mo
    "premium": 10.00,   # 20% of $50/mo
    "ultra": 20.00,     # 20% of $100/mo
    "enterprise": 40.00, # 20% of $200/mo (estimated)
}

# Configuration
ATTRIBUTION_WINDOW_DAYS = 30  # Click must be within 30 days of conversion
MINIMUM_PAYOUT_USD = 100.00   # Minimum balance for payout request
REFERRAL_CODE_LENGTH = 8      # Length of generated referral codes


class AffiliateEngine:
    """
    Affiliate program engine.

    Handles:
    - Affiliate registration and code generation
    - Click tracking
    - Conversion attribution (30-day window)
    - Commission calculation (20% recurring)
    - Monthly commission accrual
    - Payout processing
    - Statistics and reporting
    """

    def __init__(self, db):
        """Initialize affiliate engine with database connection."""
        self.db = db

    async def register_affiliate(self, user_id: str, payment_email: str = "") -> Affiliate:
        """
        Register a new affiliate and generate unique referral code.

        Args:
            user_id: User ID to register as affiliate
            payment_email: Optional payment email (defaults to user's email)

        Returns:
            Affiliate: New affiliate record

        Raises:
            ValueError: If user is already registered as affiliate
        """
        # Check if already registered
        existing = await self.db.get_affiliate_by_user(user_id)
        if existing:
            raise ValueError(f"User {user_id} is already registered as affiliate")

        # Get user info for code generation
        user = await self.db.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Generate unique referral code
        ref_code = await self._generate_unique_code(user.get("email", ""))

        # Create affiliate record
        affiliate_id = str(uuid.uuid4())
        now = time.time()

        affiliate_data = {
            "id": affiliate_id,
            "user_id": user_id,
            "referral_code": ref_code,
            "joined_at": now,
            "total_clicks": 0,
            "total_conversions": 0,
            "total_commissions_usd": 0.0,
            "pending_payout_usd": 0.0,
            "paid_out_usd": 0.0,
            "tier_breakdown": {},
            "status": "active",
            "payment_email": payment_email or user.get("email", ""),
        }

        await self.db.create_affiliate(affiliate_data)

        log.info("Registered new affiliate: user=%s code=%s", user_id, ref_code)

        return Affiliate(**affiliate_data)

    async def track_click(
        self, referral_code: str, source: str = "", ip_address: str = ""
    ) -> bool:
        """
        Track a referral link click.

        Args:
            referral_code: Affiliate's referral code
            source: Traffic source (utm_source, etc.)
            ip_address: User's IP address

        Returns:
            bool: True if click was tracked, False if invalid code
        """
        # Verify referral code exists
        affiliate = await self.db.get_affiliate_by_code(referral_code)
        if not affiliate:
            log.warning("Invalid referral code: %s", referral_code)
            return False

        # Record click
        click_id = str(uuid.uuid4())
        now = time.time()

        click_data = {
            "id": click_id,
            "affiliate_id": affiliate["id"],
            "referral_code": referral_code,
            "clicked_at": now,
            "source": source,
            "ip_address": ip_address,
            "converted": False,
            "converted_at": None,
            "user_id": None,
        }

        await self.db.create_affiliate_click(click_data)

        # Increment affiliate click counter
        await self.db.increment_affiliate_clicks(affiliate["id"])

        log.debug("Tracked click: code=%s source=%s", referral_code, source)

        return True

    async def attribute_conversion(
        self, user_id: str, subscription_tier: str
    ) -> Optional[str]:
        """
        Attribute a subscription conversion to an affiliate.

        Looks for a recent click (within 30-day window) and creates the
        initial commission record.

        Args:
            user_id: User who subscribed
            subscription_tier: Subscription tier (pro, premium, ultra, enterprise)

        Returns:
            Optional[str]: Affiliate ID if attributed, None otherwise
        """
        # Find most recent click within attribution window
        now = time.time()
        window_start = now - (ATTRIBUTION_WINDOW_DAYS * 86400)

        click = await self.db.get_recent_unconverted_click(user_id, window_start)
        if not click:
            log.debug("No attributable click found for user %s", user_id)
            return None

        affiliate_id = click["affiliate_id"]

        # Mark click as converted
        await self.db.mark_click_converted(click["id"], user_id, now)

        # Increment conversion counter
        await self.db.increment_affiliate_conversions(affiliate_id, subscription_tier)

        # Create initial commission
        commission = await self.compute_commission(
            affiliate_id=affiliate_id,
            user_id=user_id,
            subscription_tier=subscription_tier,
        )

        log.info(
            "Attributed conversion: affiliate=%s user=%s tier=%s commission=$%.2f",
            affiliate_id[:8], user_id[:8], subscription_tier, commission.amount_usd,
        )

        return affiliate_id

    async def compute_commission(
        self,
        affiliate_id: str,
        user_id: str,
        subscription_tier: str,
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
    ) -> Commission:
        """
        Compute and create a commission record.

        Args:
            affiliate_id: Affiliate earning the commission
            user_id: Referred user
            subscription_tier: Subscription tier
            period_start: Billing period start (YYYY-MM-DD)
            period_end: Billing period end (YYYY-MM-DD)

        Returns:
            Commission: New commission record
        """
        # Calculate commission amount
        amount = TIER_COMMISSION_RATES.get(subscription_tier, 0.0)

        # Default to current month if no period specified
        if not period_start or not period_end:
            now = datetime.now(timezone.utc)
            period_start = now.strftime("%Y-%m-01")
            # Last day of month
            next_month = now.replace(day=28) + timedelta(days=4)
            period_end = (next_month - timedelta(days=next_month.day)).strftime("%Y-%m-%d")

        # Create commission
        commission_id = str(uuid.uuid4())
        now = time.time()

        commission_data = {
            "id": commission_id,
            "affiliate_id": affiliate_id,
            "user_id": user_id,
            "subscription_tier": subscription_tier,
            "amount_usd": amount,
            "recurring_monthly": True,
            "accrued_at": now,
            "period_start": period_start,
            "period_end": period_end,
            "payout_id": None,
            "paid_at": None,
            "status": "pending",
        }

        await self.db.create_commission(commission_data)

        # Update affiliate pending balance
        await self.db.increment_affiliate_commissions(affiliate_id, amount)

        return Commission(**commission_data)

    async def process_monthly_commissions(self, month: Optional[str] = None) -> int:
        """
        Process recurring monthly commissions for all active subscriptions.

        This should be called at the start of each month to accrue commissions
        for all active referred subscriptions.

        Args:
            month: Month to process (YYYY-MM format). Defaults to current month.

        Returns:
            int: Number of commissions created
        """
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")

        log.info("Processing monthly commissions for %s", month)

        # Get all active referral subscriptions
        active_referrals = await self.db.get_active_referral_subscriptions()

        commission_count = 0

        for referral in active_referrals:
            try:
                # Compute billing period
                year, mon = month.split("-")
                period_start = f"{year}-{mon}-01"
                # Last day of month
                dt = datetime(int(year), int(mon), 1)
                next_month = dt.replace(day=28) + timedelta(days=4)
                period_end = (next_month - timedelta(days=next_month.day)).strftime("%Y-%m-%d")

                # Create commission
                await self.compute_commission(
                    affiliate_id=referral["affiliate_id"],
                    user_id=referral["user_id"],
                    subscription_tier=referral["tier"],
                    period_start=period_start,
                    period_end=period_end,
                )

                commission_count += 1

            except Exception as e:
                log.error(
                    "Error processing commission for referral %s: %s",
                    referral.get("user_id", "?"), e,
                )

        log.info("Processed %d monthly commissions", commission_count)

        return commission_count

    async def generate_payout_report(
        self,
        affiliate_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a payout report for an affiliate.

        Args:
            affiliate_id: Affiliate ID
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)

        Returns:
            dict: Payout report with commissions, totals, breakdown
        """
        # Get affiliate
        affiliate = await self.db.get_affiliate_by_id(affiliate_id)
        if not affiliate:
            raise ValueError(f"Affiliate {affiliate_id} not found")

        # Get commissions in date range
        commissions = await self.db.get_affiliate_commissions(
            affiliate_id, start_date, end_date
        )

        # Calculate totals
        total_pending = sum(c["amount_usd"] for c in commissions if c["status"] == "pending")
        total_paid = sum(c["amount_usd"] for c in commissions if c["status"] == "paid")
        total_all = sum(c["amount_usd"] for c in commissions)

        # Tier breakdown
        tier_breakdown = {}
        for comm in commissions:
            tier = comm["subscription_tier"]
            tier_breakdown[tier] = tier_breakdown.get(tier, 0) + comm["amount_usd"]

        return {
            "affiliate_id": affiliate_id,
            "referral_code": affiliate["referral_code"],
            "period_start": start_date,
            "period_end": end_date,
            "total_commissions": total_all,
            "pending_commissions": total_pending,
            "paid_commissions": total_paid,
            "commission_count": len(commissions),
            "tier_breakdown": tier_breakdown,
            "commissions": commissions,
            "can_request_payout": total_pending >= MINIMUM_PAYOUT_USD,
            "minimum_payout": MINIMUM_PAYOUT_USD,
        }

    async def request_payout(
        self,
        affiliate_id: str,
        payment_method: str = "paypal",
    ) -> Payout:
        """
        Request a payout for an affiliate.

        Args:
            affiliate_id: Affiliate ID
            payment_method: Payment method (paypal, stripe, bank_transfer, manual)

        Returns:
            Payout: New payout request

        Raises:
            ValueError: If pending balance is below minimum threshold
        """
        # Get affiliate
        affiliate = await self.db.get_affiliate_by_id(affiliate_id)
        if not affiliate:
            raise ValueError(f"Affiliate {affiliate_id} not found")

        # Check pending balance
        pending = affiliate.get("pending_payout_usd", 0.0)
        if pending < MINIMUM_PAYOUT_USD:
            raise ValueError(
                f"Pending balance ${pending:.2f} is below minimum ${MINIMUM_PAYOUT_USD:.2f}"
            )

        # Get all pending commissions
        pending_commissions = await self.db.get_pending_commissions(affiliate_id)
        commission_ids = [c["id"] for c in pending_commissions]

        # Create payout request
        payout_id = str(uuid.uuid4())
        now = time.time()

        payout_data = {
            "id": payout_id,
            "affiliate_id": affiliate_id,
            "amount_usd": pending,
            "commission_ids": commission_ids,
            "requested_at": now,
            "processed_at": None,
            "status": "pending",
            "payment_method": payment_method,
            "payment_email": affiliate.get("payment_email", ""),
            "transaction_id": None,
            "notes": None,
        }

        await self.db.create_payout(payout_data)

        log.info(
            "Payout requested: affiliate=%s amount=$%.2f commissions=%d",
            affiliate_id[:8], pending, len(commission_ids),
        )

        return Payout(**payout_data)

    async def mark_paid_out(
        self,
        payout_id: str,
        transaction_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        """
        Mark a payout as completed (admin function).

        Args:
            payout_id: Payout ID
            transaction_id: External payment processor transaction ID
            notes: Admin notes
        """
        # Get payout
        payout = await self.db.get_payout_by_id(payout_id)
        if not payout:
            raise ValueError(f"Payout {payout_id} not found")

        now = time.time()

        # Update payout status
        await self.db.update_payout_status(
            payout_id,
            status="completed",
            processed_at=now,
            transaction_id=transaction_id,
            notes=notes,
        )

        # Mark all commissions as paid
        commission_ids = payout.get("commission_ids", [])
        if isinstance(commission_ids, str):
            import json
            commission_ids = json.loads(commission_ids)

        for comm_id in commission_ids:
            await self.db.update_commission_status(
                comm_id, payout_id=payout_id, paid_at=now, status="paid"
            )

        # Update affiliate balances
        amount = payout.get("amount_usd", 0.0)
        affiliate_id = payout.get("affiliate_id", "")
        await self.db.update_affiliate_payout_balances(affiliate_id, amount)

        log.info("Payout marked complete: id=%s amount=$%.2f", payout_id[:8], amount)

    async def get_referral_stats(
        self, affiliate_id: str, days: int = 30
    ) -> ReferralStats:
        """
        Get aggregate referral statistics for an affiliate.

        Args:
            affiliate_id: Affiliate ID
            days: Number of days to include in stats (default: 30)

        Returns:
            ReferralStats: Aggregate statistics
        """
        # Get affiliate
        affiliate = await self.db.get_affiliate_by_id(affiliate_id)
        if not affiliate:
            raise ValueError(f"Affiliate {affiliate_id} not found")

        # Calculate date range
        now = time.time()
        start_time = now - (days * 86400)

        # Get stats from DB
        clicks = await self.db.count_affiliate_clicks(affiliate_id, start_time)
        conversions = await self.db.count_affiliate_conversions(affiliate_id, start_time)
        conversion_rate = conversions / clicks if clicks > 0 else 0.0

        # Get commission totals
        commission_data = await self.db.get_affiliate_commission_totals(
            affiliate_id, start_time
        )
        total_commissions = commission_data.get("total", 0.0)
        pending_commissions = commission_data.get("pending", 0.0)
        paid_commissions = commission_data.get("paid", 0.0)

        # Get tier breakdown
        tier_breakdown = await self.db.get_affiliate_tier_breakdown(affiliate_id)
        top_tier = max(tier_breakdown, key=tier_breakdown.get) if tier_breakdown else "none"

        # Get active referral count
        active_referrals = await self.db.count_active_referrals(affiliate_id)

        return ReferralStats(
            affiliate_id=affiliate_id,
            period_days=days,
            total_clicks=clicks,
            total_conversions=conversions,
            conversion_rate=round(conversion_rate, 4),
            total_commissions_usd=round(total_commissions, 2),
            pending_commissions_usd=round(pending_commissions, 2),
            paid_commissions_usd=round(paid_commissions, 2),
            top_tier=top_tier,
            active_referrals=active_referrals,
        )

    # ── Private helpers ──

    async def _generate_unique_code(self, email: str) -> str:
        """
        Generate a unique 8-character referral code.

        Format: {prefix}_{random}
        Example: john_a3f

        Args:
            email: User's email for prefix generation

        Returns:
            str: Unique referral code
        """
        # Extract prefix from email
        prefix = email.split("@")[0][:4].lower() if email else "rot"
        prefix = "".join(c for c in prefix if c.isalnum())  # Remove special chars
        if not prefix:
            prefix = "user"

        # Try up to 10 times to generate unique code
        for _ in range(10):
            suffix = secrets.token_hex(2)  # 4 hex chars
            code = f"{prefix}_{suffix}"

            # Check if code already exists
            existing = await self.db.get_affiliate_by_code(code)
            if not existing:
                return code

        # Fallback to fully random code if all attempts fail
        return f"rot_{secrets.token_hex(3)}"
