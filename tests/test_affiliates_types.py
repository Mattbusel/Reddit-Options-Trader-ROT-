"""Tests for affiliate types and dataclasses."""

import pytest

from rot.affiliates.types import Affiliate, Commission, Payout, ReferralStats


# ============================================================================
# Affiliate dataclass tests
# ============================================================================

def test_affiliate_creation():
    """Test creating an Affiliate instance."""
    affiliate = Affiliate(
        id="aff_123",
        user_id="user_456",
        referral_code="john_a3f",
        joined_at=1234567890.0,
        total_clicks=100,
        total_conversions=5,
        total_commissions_usd=50.00,
        pending_payout_usd=50.00,
        paid_out_usd=0.00,
        tier_breakdown={"pro": 3, "premium": 2},
        status="active",
        payment_email="john@example.com",
    )

    assert affiliate.id == "aff_123"
    assert affiliate.user_id == "user_456"
    assert affiliate.referral_code == "john_a3f"
    assert affiliate.total_clicks == 100
    assert affiliate.total_conversions == 5
    assert affiliate.status == "active"


def test_affiliate_to_dict():
    """Test Affiliate.to_dict() conversion."""
    affiliate = Affiliate(
        id="aff_123",
        user_id="user_456",
        referral_code="john_a3f",
        joined_at=1234567890.0,
        total_clicks=50,
        total_conversions=2,
        total_commissions_usd=20.00,
        pending_payout_usd=20.00,
        paid_out_usd=0.00,
        tier_breakdown={"pro": 2},
        status="active",
        payment_email="john@example.com",
    )

    result = affiliate.to_dict()

    assert result["id"] == "aff_123"
    assert result["referral_code"] == "john_a3f"
    assert result["total_clicks"] == 50
    assert result["tier_breakdown"] == {"pro": 2}
    assert result["status"] == "active"


def test_affiliate_frozen():
    """Test that Affiliate is frozen (immutable)."""
    affiliate = Affiliate(
        id="aff_123",
        user_id="user_456",
        referral_code="john_a3f",
        joined_at=1234567890.0,
        total_clicks=100,
        total_conversions=5,
        total_commissions_usd=50.00,
        pending_payout_usd=50.00,
        paid_out_usd=0.00,
        tier_breakdown={"pro": 3, "premium": 2},
        status="active",
        payment_email="john@example.com",
    )

    with pytest.raises(AttributeError):
        affiliate.total_clicks = 200


# ============================================================================
# Commission dataclass tests
# ============================================================================

def test_commission_creation():
    """Test creating a Commission instance."""
    commission = Commission(
        id="comm_123",
        affiliate_id="aff_456",
        user_id="user_789",
        subscription_tier="premium",
        amount_usd=10.00,
        recurring_monthly=True,
        accrued_at=1234567890.0,
        period_start="2025-01-01",
        period_end="2025-01-31",
        payout_id=None,
        paid_at=None,
        status="pending",
    )

    assert commission.id == "comm_123"
    assert commission.affiliate_id == "aff_456"
    assert commission.subscription_tier == "premium"
    assert commission.amount_usd == 10.00
    assert commission.recurring_monthly is True
    assert commission.status == "pending"


def test_commission_to_dict():
    """Test Commission.to_dict() conversion."""
    commission = Commission(
        id="comm_123",
        affiliate_id="aff_456",
        user_id="user_789",
        subscription_tier="pro",
        amount_usd=4.00,
        recurring_monthly=True,
        accrued_at=1234567890.0,
        period_start="2025-01-01",
        period_end="2025-01-31",
        payout_id=None,
        paid_at=None,
        status="pending",
    )

    result = commission.to_dict()

    assert result["id"] == "comm_123"
    assert result["subscription_tier"] == "pro"
    assert result["amount_usd"] == 4.00
    assert result["status"] == "pending"
    assert result["payout_id"] is None


def test_commission_paid():
    """Test Commission with paid status."""
    commission = Commission(
        id="comm_123",
        affiliate_id="aff_456",
        user_id="user_789",
        subscription_tier="ultra",
        amount_usd=20.00,
        recurring_monthly=True,
        accrued_at=1234567890.0,
        period_start="2025-01-01",
        period_end="2025-01-31",
        payout_id="payout_999",
        paid_at=1234567900.0,
        status="paid",
    )

    assert commission.status == "paid"
    assert commission.payout_id == "payout_999"
    assert commission.paid_at == 1234567900.0


# ============================================================================
# Payout dataclass tests
# ============================================================================

def test_payout_creation():
    """Test creating a Payout instance."""
    payout = Payout(
        id="payout_123",
        affiliate_id="aff_456",
        amount_usd=150.00,
        commission_ids=["comm_1", "comm_2", "comm_3"],
        requested_at=1234567890.0,
        processed_at=None,
        status="pending",
        payment_method="paypal",
        payment_email="affiliate@example.com",
        transaction_id=None,
        notes=None,
    )

    assert payout.id == "payout_123"
    assert payout.amount_usd == 150.00
    assert len(payout.commission_ids) == 3
    assert payout.status == "pending"
    assert payout.payment_method == "paypal"


def test_payout_to_dict():
    """Test Payout.to_dict() conversion."""
    payout = Payout(
        id="payout_123",
        affiliate_id="aff_456",
        amount_usd=200.00,
        commission_ids=["comm_1", "comm_2"],
        requested_at=1234567890.0,
        processed_at=None,
        status="pending",
        payment_method="stripe",
        payment_email="affiliate@example.com",
        transaction_id=None,
        notes=None,
    )

    result = payout.to_dict()

    assert result["id"] == "payout_123"
    assert result["amount_usd"] == 200.00
    assert result["commission_ids"] == ["comm_1", "comm_2"]
    assert result["status"] == "pending"
    assert result["payment_method"] == "stripe"


def test_payout_completed():
    """Test Payout with completed status."""
    payout = Payout(
        id="payout_123",
        affiliate_id="aff_456",
        amount_usd=150.00,
        commission_ids=["comm_1", "comm_2"],
        requested_at=1234567890.0,
        processed_at=1234567900.0,
        status="completed",
        payment_method="paypal",
        payment_email="affiliate@example.com",
        transaction_id="txn_abc123",
        notes="Processed successfully",
    )

    assert payout.status == "completed"
    assert payout.processed_at == 1234567900.0
    assert payout.transaction_id == "txn_abc123"
    assert payout.notes == "Processed successfully"


# ============================================================================
# ReferralStats dataclass tests
# ============================================================================

def test_referral_stats_creation():
    """Test creating a ReferralStats instance."""
    stats = ReferralStats(
        affiliate_id="aff_123",
        period_days=30,
        total_clicks=500,
        total_conversions=10,
        conversion_rate=0.02,
        total_commissions_usd=100.00,
        pending_commissions_usd=80.00,
        paid_commissions_usd=20.00,
        top_tier="premium",
        active_referrals=8,
    )

    assert stats.affiliate_id == "aff_123"
    assert stats.period_days == 30
    assert stats.total_clicks == 500
    assert stats.total_conversions == 10
    assert stats.conversion_rate == 0.02
    assert stats.top_tier == "premium"
    assert stats.active_referrals == 8


def test_referral_stats_to_dict():
    """Test ReferralStats.to_dict() conversion."""
    stats = ReferralStats(
        affiliate_id="aff_123",
        period_days=30,
        total_clicks=200,
        total_conversions=5,
        conversion_rate=0.025,
        total_commissions_usd=50.00,
        pending_commissions_usd=50.00,
        paid_commissions_usd=0.00,
        top_tier="pro",
        active_referrals=5,
    )

    result = stats.to_dict()

    assert result["affiliate_id"] == "aff_123"
    assert result["total_clicks"] == 200
    assert result["conversion_rate"] == 0.025
    assert result["total_commissions_usd"] == 50.00
    assert result["top_tier"] == "pro"


def test_referral_stats_high_conversion():
    """Test ReferralStats with high conversion rate."""
    stats = ReferralStats(
        affiliate_id="aff_456",
        period_days=7,
        total_clicks=100,
        total_conversions=20,
        conversion_rate=0.20,
        total_commissions_usd=200.00,
        pending_commissions_usd=150.00,
        paid_commissions_usd=50.00,
        top_tier="ultra",
        active_referrals=18,
    )

    assert stats.conversion_rate == 0.20
    assert stats.total_conversions == 20
    assert stats.top_tier == "ultra"
