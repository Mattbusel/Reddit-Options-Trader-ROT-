"""Affiliate program module — referral tracking, commissions, and payouts."""

from rot.affiliates.engine import AffiliateEngine
from rot.affiliates.types import Affiliate, Commission, Payout, ReferralStats

__all__ = [
    "AffiliateEngine",
    "Affiliate",
    "Commission",
    "Payout",
    "ReferralStats",
]
