"""
Affiliate program types and dataclasses.

This module defines the core data structures for the affiliate/referral system,
including affiliates, commissions, payouts, and referral statistics.
"""

from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any


@dataclass(frozen=True)
class Affiliate:
    """
    An affiliate partner in the referral program.

    Attributes:
        id: Unique affiliate identifier
        user_id: Associated user account ID
        referral_code: Unique 8-char referral code (e.g., "john_a3f")
        joined_at: Unix timestamp of affiliate registration
        total_clicks: Lifetime referral link clicks
        total_conversions: Lifetime successful conversions (paid signups)
        total_commissions_usd: Total commissions earned (all time)
        pending_payout_usd: Commissions accrued but not yet paid out
        paid_out_usd: Total commissions paid out
        tier_breakdown: Dict of conversions by tier (e.g., {"pro": 5, "premium": 2})
        status: Affiliate account status
        payment_email: PayPal/Stripe email for payouts
    """
    id: str
    user_id: str
    referral_code: str
    joined_at: float
    total_clicks: int
    total_conversions: int
    total_commissions_usd: float
    pending_payout_usd: float
    paid_out_usd: float
    tier_breakdown: Dict[str, int]
    status: Literal["active", "suspended", "inactive"]
    payment_email: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "referral_code": self.referral_code,
            "joined_at": self.joined_at,
            "total_clicks": self.total_clicks,
            "total_conversions": self.total_conversions,
            "total_commissions_usd": self.total_commissions_usd,
            "pending_payout_usd": self.pending_payout_usd,
            "paid_out_usd": self.paid_out_usd,
            "tier_breakdown": self.tier_breakdown,
            "status": self.status,
            "payment_email": self.payment_email,
        }


@dataclass(frozen=True)
class Commission:
    """
    A commission earned from a referral conversion.

    Commissions are calculated as 20% of the monthly subscription fee
    and are accrued monthly for active subscriptions.

    Attributes:
        id: Unique commission identifier
        affiliate_id: Affiliate who earned this commission
        user_id: Customer who was referred (converted user)
        subscription_tier: Subscription tier (pro, premium, ultra, enterprise)
        amount_usd: Commission amount in USD
        recurring_monthly: Whether this is a recurring monthly commission
        accrued_at: Unix timestamp when commission was accrued
        period_start: Billing period start (YYYY-MM-DD)
        period_end: Billing period end (YYYY-MM-DD)
        payout_id: Associated payout ID (None if unpaid)
        paid_at: Unix timestamp when paid (None if unpaid)
        status: Commission status
    """
    id: str
    affiliate_id: str
    user_id: str
    subscription_tier: Literal["pro", "premium", "ultra", "enterprise"]
    amount_usd: float
    recurring_monthly: bool
    accrued_at: float
    period_start: str
    period_end: str
    payout_id: Optional[str]
    paid_at: Optional[float]
    status: Literal["pending", "paid", "cancelled"]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "affiliate_id": self.affiliate_id,
            "user_id": self.user_id,
            "subscription_tier": self.subscription_tier,
            "amount_usd": self.amount_usd,
            "recurring_monthly": self.recurring_monthly,
            "accrued_at": self.accrued_at,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "payout_id": self.payout_id,
            "paid_at": self.paid_at,
            "status": self.status,
        }


@dataclass(frozen=True)
class Payout:
    """
    A payout batch to an affiliate.

    Payouts are processed when an affiliate's pending balance reaches
    the minimum threshold ($100).

    Attributes:
        id: Unique payout identifier
        affiliate_id: Affiliate receiving payout
        amount_usd: Total payout amount
        commission_ids: List of commission IDs included in this payout
        requested_at: Unix timestamp of payout request
        processed_at: Unix timestamp when payout was processed (None if pending)
        status: Payout status
        payment_method: Payment method (paypal, stripe, bank_transfer)
        payment_email: Email where payment was sent
        transaction_id: External payment processor transaction ID
        notes: Admin notes or error messages
    """
    id: str
    affiliate_id: str
    amount_usd: float
    commission_ids: list[str]
    requested_at: float
    processed_at: Optional[float]
    status: Literal["pending", "processing", "completed", "failed", "cancelled"]
    payment_method: Literal["paypal", "stripe", "bank_transfer", "manual"]
    payment_email: str
    transaction_id: Optional[str]
    notes: Optional[str]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "affiliate_id": self.affiliate_id,
            "amount_usd": self.amount_usd,
            "commission_ids": self.commission_ids,
            "requested_at": self.requested_at,
            "processed_at": self.processed_at,
            "status": self.status,
            "payment_method": self.payment_method,
            "payment_email": self.payment_email,
            "transaction_id": self.transaction_id,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ReferralStats:
    """
    Aggregate referral statistics for an affiliate over a time period.

    Attributes:
        affiliate_id: Affiliate identifier
        period_days: Number of days in reporting period
        total_clicks: Total clicks in period
        total_conversions: Total conversions in period
        conversion_rate: Click-to-conversion rate (0.0-1.0)
        total_commissions_usd: Total commissions earned in period
        pending_commissions_usd: Unpaid commissions in period
        paid_commissions_usd: Paid commissions in period
        top_tier: Most common subscription tier
        active_referrals: Count of currently active referred subscriptions
    """
    affiliate_id: str
    period_days: int
    total_clicks: int
    total_conversions: int
    conversion_rate: float
    total_commissions_usd: float
    pending_commissions_usd: float
    paid_commissions_usd: float
    top_tier: str
    active_referrals: int

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "affiliate_id": self.affiliate_id,
            "period_days": self.period_days,
            "total_clicks": self.total_clicks,
            "total_conversions": self.total_conversions,
            "conversion_rate": self.conversion_rate,
            "total_commissions_usd": self.total_commissions_usd,
            "pending_commissions_usd": self.pending_commissions_usd,
            "paid_commissions_usd": self.paid_commissions_usd,
            "top_tier": self.top_tier,
            "active_referrals": self.active_referrals,
        }
