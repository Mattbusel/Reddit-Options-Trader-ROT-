"""Tests for affiliate engine."""

import pytest
import tempfile
import os
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from rot.affiliates.engine import AffiliateEngine, TIER_COMMISSION_RATES, MINIMUM_PAYOUT_USD
from rot.storage.database import Database


@pytest.fixture
async def db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    database = Database(path)
    await database.connect()
    await database._init_affiliates_tables()

    # Create a mock user for testing
    await database.db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT,
            created_at REAL
        )
        """
    )
    await database.db.execute(
        "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
        ("user_123", "john@example.com", time.time())
    )
    await database.db.commit()

    yield database

    await database.close()
    os.unlink(path)


@pytest.fixture
def engine(db):
    """Create affiliate engine instance."""
    return AffiliateEngine(db)


# ============================================================================
# Registration tests
# ============================================================================

@pytest.mark.asyncio
async def test_register_affiliate(db, engine):
    """Test registering a new affiliate."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    assert affiliate.user_id == "user_123"
    assert affiliate.payment_email == "john@example.com"
    assert len(affiliate.referral_code) == 8  # prefix_suffix format
    assert affiliate.status == "active"
    assert affiliate.total_clicks == 0
    assert affiliate.total_conversions == 0


@pytest.mark.asyncio
async def test_register_affiliate_duplicate(db, engine):
    """Test that registering duplicate affiliate raises error."""
    # Register first time
    await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Try to register again
    with pytest.raises(ValueError, match="already registered"):
        await engine.register_affiliate(
            user_id="user_123",
            payment_email="john@example.com",
        )


@pytest.mark.asyncio
async def test_register_affiliate_generates_unique_code(db, engine):
    """Test that affiliate registration generates unique codes."""
    # Create another user
    await db.db.execute(
        "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
        ("user_456", "jane@example.com", time.time())
    )
    await db.db.commit()

    affiliate1 = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    affiliate2 = await engine.register_affiliate(
        user_id="user_456",
        payment_email="jane@example.com",
    )

    assert affiliate1.referral_code != affiliate2.referral_code


# ============================================================================
# Click tracking tests
# ============================================================================

@pytest.mark.asyncio
async def test_track_click(db, engine):
    """Test tracking a referral click."""
    # Register affiliate first
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Track click
    result = await engine.track_click(
        referral_code=affiliate.referral_code,
        source="twitter",
        ip_address="192.168.1.1",
    )

    assert result is True

    # Verify click was recorded
    count = await db.count_affiliate_clicks(affiliate.id)
    assert count == 1


@pytest.mark.asyncio
async def test_track_click_invalid_code(db, engine):
    """Test tracking click with invalid referral code."""
    result = await engine.track_click(
        referral_code="invalid_code",
        source="web",
        ip_address="192.168.1.1",
    )

    assert result is False


@pytest.mark.asyncio
async def test_track_multiple_clicks(db, engine):
    """Test tracking multiple clicks."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Track multiple clicks
    for i in range(5):
        await engine.track_click(
            referral_code=affiliate.referral_code,
            source="web",
            ip_address=f"192.168.1.{i}",
        )

    # Verify all clicks were recorded
    count = await db.count_affiliate_clicks(affiliate.id)
    assert count == 5


# ============================================================================
# Commission computation tests
# ============================================================================

@pytest.mark.asyncio
async def test_compute_commission_pro(db, engine):
    """Test computing commission for Pro tier."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    commission = await engine.compute_commission(
        affiliate_id=affiliate.id,
        user_id="user_456",
        subscription_tier="pro",
    )

    assert commission.affiliate_id == affiliate.id
    assert commission.subscription_tier == "pro"
    assert commission.amount_usd == TIER_COMMISSION_RATES["pro"]
    assert commission.status == "pending"
    assert commission.recurring_monthly is True


@pytest.mark.asyncio
async def test_compute_commission_premium(db, engine):
    """Test computing commission for Premium tier."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    commission = await engine.compute_commission(
        affiliate_id=affiliate.id,
        user_id="user_456",
        subscription_tier="premium",
    )

    assert commission.subscription_tier == "premium"
    assert commission.amount_usd == TIER_COMMISSION_RATES["premium"]


@pytest.mark.asyncio
async def test_compute_commission_ultra(db, engine):
    """Test computing commission for Ultra tier."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    commission = await engine.compute_commission(
        affiliate_id=affiliate.id,
        user_id="user_456",
        subscription_tier="ultra",
    )

    assert commission.subscription_tier == "ultra"
    assert commission.amount_usd == TIER_COMMISSION_RATES["ultra"]


# ============================================================================
# Payout tests
# ============================================================================

@pytest.mark.asyncio
async def test_request_payout_success(db, engine):
    """Test successful payout request."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Create enough commissions to meet minimum threshold
    for i in range(10):
        await engine.compute_commission(
            affiliate_id=affiliate.id,
            user_id=f"user_{i}",
            subscription_tier="premium",  # $10 each
        )

    # Request payout
    payout = await engine.request_payout(
        affiliate_id=affiliate.id,
        payment_method="paypal",
    )

    assert payout.affiliate_id == affiliate.id
    assert payout.amount_usd == 100.0  # 10 commissions * $10
    assert payout.status == "pending"
    assert payout.payment_method == "paypal"
    assert len(payout.commission_ids) == 10


@pytest.mark.asyncio
async def test_request_payout_below_minimum(db, engine):
    """Test payout request below minimum threshold."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Create only one commission ($4)
    await engine.compute_commission(
        affiliate_id=affiliate.id,
        user_id="user_456",
        subscription_tier="pro",
    )

    # Try to request payout
    with pytest.raises(ValueError, match="below minimum"):
        await engine.request_payout(
            affiliate_id=affiliate.id,
            payment_method="paypal",
        )


@pytest.mark.asyncio
async def test_mark_paid_out(db, engine):
    """Test marking a payout as completed."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Create commissions and request payout
    for i in range(10):
        await engine.compute_commission(
            affiliate_id=affiliate.id,
            user_id=f"user_{i}",
            subscription_tier="premium",
        )

    payout = await engine.request_payout(
        affiliate_id=affiliate.id,
        payment_method="stripe",
    )

    # Mark as paid
    await engine.mark_paid_out(
        payout_id=payout.id,
        transaction_id="txn_abc123",
        notes="Processed successfully",
    )

    # Verify payout was updated
    updated_payout = await db.get_payout_by_id(payout.id)
    assert updated_payout["status"] == "completed"
    assert updated_payout["transaction_id"] == "txn_abc123"

    # Verify commissions were marked as paid
    pending = await db.get_pending_commissions(affiliate.id)
    assert len(pending) == 0  # All should be paid now


# ============================================================================
# Statistics tests
# ============================================================================

@pytest.mark.asyncio
async def test_get_referral_stats(db, engine):
    """Test getting referral statistics."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Track some clicks
    for i in range(10):
        await engine.track_click(
            referral_code=affiliate.referral_code,
            source="web",
            ip_address=f"192.168.1.{i}",
        )

    # Create some commissions
    for i in range(3):
        await engine.compute_commission(
            affiliate_id=affiliate.id,
            user_id=f"user_{i}",
            subscription_tier="premium",
        )

    # Get stats
    stats = await engine.get_referral_stats(affiliate.id, days=30)

    assert stats.affiliate_id == affiliate.id
    assert stats.total_clicks >= 10
    assert stats.total_commissions_usd >= 30.0  # 3 * $10


@pytest.mark.asyncio
async def test_generate_payout_report(db, engine):
    """Test generating a payout report."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Create commissions
    for i in range(5):
        await engine.compute_commission(
            affiliate_id=affiliate.id,
            user_id=f"user_{i}",
            subscription_tier="pro",
        )

    # Generate report
    report = await engine.generate_payout_report(affiliate.id)

    assert report["affiliate_id"] == affiliate.id
    assert report["total_commissions"] == 20.0  # 5 * $4
    assert report["pending_commissions"] == 20.0
    assert report["commission_count"] == 5
    assert report["can_request_payout"] is False  # Below $100 minimum


@pytest.mark.asyncio
async def test_payout_report_can_request(db, engine):
    """Test payout report shows when payout can be requested."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Create enough commissions to meet threshold
    for i in range(10):
        await engine.compute_commission(
            affiliate_id=affiliate.id,
            user_id=f"user_{i}",
            subscription_tier="premium",
        )

    # Generate report
    report = await engine.generate_payout_report(affiliate.id)

    assert report["total_commissions"] == 100.0
    assert report["can_request_payout"] is True
    assert report["minimum_payout"] == MINIMUM_PAYOUT_USD


# ============================================================================
# Code generation tests
# ============================================================================

@pytest.mark.asyncio
async def test_generate_unique_code_from_email(db, engine):
    """Test code generation uses email prefix."""
    # Mock user with specific email
    await db.db.execute(
        "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
        ("user_999", "alice@example.com", time.time())
    )
    await db.db.commit()

    affiliate = await engine.register_affiliate(
        user_id="user_999",
        payment_email="alice@example.com",
    )

    # Code should start with email prefix
    assert affiliate.referral_code.startswith("alic")


@pytest.mark.asyncio
async def test_generate_unique_code_collision_handling(db, engine):
    """Test that code generation handles collisions."""
    # Register multiple affiliates and ensure unique codes
    codes = set()

    for i in range(5):
        await db.db.execute(
            "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
            (f"user_{i}", f"test{i}@example.com", time.time())
        )
    await db.db.commit()

    for i in range(5):
        affiliate = await engine.register_affiliate(
            user_id=f"user_{i}",
            payment_email=f"test{i}@example.com",
        )
        codes.add(affiliate.referral_code)

    # All codes should be unique
    assert len(codes) == 5


# ============================================================================
# Tier breakdown tests
# ============================================================================

@pytest.mark.asyncio
async def test_tier_breakdown_tracking(db, engine):
    """Test that tier breakdown is tracked correctly."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Create commissions for different tiers
    await engine.compute_commission(
        affiliate_id=affiliate.id, user_id="user_1", subscription_tier="pro"
    )
    await engine.compute_commission(
        affiliate_id=affiliate.id, user_id="user_2", subscription_tier="pro"
    )
    await engine.compute_commission(
        affiliate_id=affiliate.id, user_id="user_3", subscription_tier="premium"
    )
    await engine.compute_commission(
        affiliate_id=affiliate.id, user_id="user_4", subscription_tier="ultra"
    )

    # Get updated affiliate
    updated = await db.get_affiliate_by_id(affiliate.id)
    tier_breakdown = updated["tier_breakdown"]

    # Note: tier_breakdown only tracks conversions, not commissions
    # So we need to increment conversions separately
    await db.increment_affiliate_conversions(affiliate.id, "pro")
    await db.increment_affiliate_conversions(affiliate.id, "pro")
    await db.increment_affiliate_conversions(affiliate.id, "premium")
    await db.increment_affiliate_conversions(affiliate.id, "ultra")

    updated = await db.get_affiliate_by_id(affiliate.id)
    assert updated["tier_breakdown"]["pro"] == 2
    assert updated["tier_breakdown"]["premium"] == 1
    assert updated["tier_breakdown"]["ultra"] == 1


# ============================================================================
# Edge cases
# ============================================================================

@pytest.mark.asyncio
async def test_payout_with_no_commissions(db, engine):
    """Test payout request with no commissions."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    with pytest.raises(ValueError, match="below minimum"):
        await engine.request_payout(
            affiliate_id=affiliate.id,
            payment_method="paypal",
        )


@pytest.mark.asyncio
async def test_commission_updates_affiliate_totals(db, engine):
    """Test that creating commission updates affiliate totals."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # Create a commission
    await engine.compute_commission(
        affiliate_id=affiliate.id,
        user_id="user_456",
        subscription_tier="premium",
    )

    # Check affiliate was updated
    updated = await db.get_affiliate_by_id(affiliate.id)
    assert updated["total_commissions_usd"] == 10.0
    assert updated["pending_payout_usd"] == 10.0


@pytest.mark.asyncio
async def test_multiple_payouts(db, engine):
    """Test requesting multiple payouts over time."""
    affiliate = await engine.register_affiliate(
        user_id="user_123",
        payment_email="john@example.com",
    )

    # First batch of commissions
    for i in range(10):
        await engine.compute_commission(
            affiliate_id=affiliate.id,
            user_id=f"user_batch1_{i}",
            subscription_tier="premium",
        )

    # First payout
    payout1 = await engine.request_payout(affiliate.id)
    await engine.mark_paid_out(payout1.id, transaction_id="txn_1")

    # Second batch of commissions
    for i in range(10):
        await engine.compute_commission(
            affiliate_id=affiliate.id,
            user_id=f"user_batch2_{i}",
            subscription_tier="premium",
        )

    # Second payout
    payout2 = await engine.request_payout(affiliate.id)

    # Verify both payouts exist
    payouts = await db.get_affiliate_payouts(affiliate.id)
    assert len(payouts) == 2
    assert payouts[0]["status"] in ["completed", "pending"]
