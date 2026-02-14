"""Tests for affiliate database operations."""

import pytest
import tempfile
import os
import json
import time

from rot.storage.database import Database


@pytest.fixture
async def db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    database = Database(path)
    await database.connect()
    await database._init_affiliates_tables()

    yield database

    await database.close()
    os.unlink(path)


# ============================================================================
# Affiliate CRUD tests
# ============================================================================

@pytest.mark.asyncio
async def test_create_affiliate(db):
    """Test creating an affiliate record."""
    affiliate_data = {
        "id": "aff_123",
        "user_id": "user_456",
        "referral_code": "john_a3f",
        "joined_at": 1234567890.0,
        "total_clicks": 0,
        "total_conversions": 0,
        "total_commissions_usd": 0.0,
        "pending_payout_usd": 0.0,
        "paid_out_usd": 0.0,
        "tier_breakdown": {},
        "status": "active",
        "payment_email": "john@example.com",
    }

    await db.create_affiliate(affiliate_data)

    # Verify it was created
    result = await db.get_affiliate_by_id("aff_123")
    assert result is not None
    assert result["user_id"] == "user_456"
    assert result["referral_code"] == "john_a3f"
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_get_affiliate_by_user(db):
    """Test retrieving affiliate by user ID."""
    affiliate_data = {
        "id": "aff_123",
        "user_id": "user_456",
        "referral_code": "jane_b4c",
        "joined_at": 1234567890.0,
        "total_clicks": 50,
        "total_conversions": 2,
        "total_commissions_usd": 20.0,
        "pending_payout_usd": 20.0,
        "paid_out_usd": 0.0,
        "tier_breakdown": {"pro": 2},
        "status": "active",
        "payment_email": "jane@example.com",
    }

    await db.create_affiliate(affiliate_data)

    result = await db.get_affiliate_by_user("user_456")
    assert result is not None
    assert result["id"] == "aff_123"
    assert result["referral_code"] == "jane_b4c"


@pytest.mark.asyncio
async def test_get_affiliate_by_code(db):
    """Test retrieving affiliate by referral code."""
    affiliate_data = {
        "id": "aff_789",
        "user_id": "user_012",
        "referral_code": "bob_c5d",
        "joined_at": 1234567890.0,
        "total_clicks": 100,
        "total_conversions": 5,
        "total_commissions_usd": 50.0,
        "pending_payout_usd": 50.0,
        "paid_out_usd": 0.0,
        "tier_breakdown": {"pro": 3, "premium": 2},
        "status": "active",
        "payment_email": "bob@example.com",
    }

    await db.create_affiliate(affiliate_data)

    result = await db.get_affiliate_by_code("bob_c5d")
    assert result is not None
    assert result["id"] == "aff_789"
    assert result["user_id"] == "user_012"


@pytest.mark.asyncio
async def test_increment_affiliate_clicks(db):
    """Test incrementing affiliate click count."""
    affiliate_data = {
        "id": "aff_123",
        "user_id": "user_456",
        "referral_code": "test_code",
        "joined_at": 1234567890.0,
        "total_clicks": 0,
        "total_conversions": 0,
        "total_commissions_usd": 0.0,
        "pending_payout_usd": 0.0,
        "paid_out_usd": 0.0,
        "tier_breakdown": {},
        "status": "active",
        "payment_email": "test@example.com",
    }

    await db.create_affiliate(affiliate_data)

    # Increment clicks
    await db.increment_affiliate_clicks("aff_123")
    await db.increment_affiliate_clicks("aff_123")
    await db.increment_affiliate_clicks("aff_123")

    result = await db.get_affiliate_by_id("aff_123")
    assert result["total_clicks"] == 3


@pytest.mark.asyncio
async def test_increment_affiliate_conversions(db):
    """Test incrementing affiliate conversion count and tier breakdown."""
    affiliate_data = {
        "id": "aff_123",
        "user_id": "user_456",
        "referral_code": "test_code",
        "joined_at": 1234567890.0,
        "total_clicks": 10,
        "total_conversions": 0,
        "total_commissions_usd": 0.0,
        "pending_payout_usd": 0.0,
        "paid_out_usd": 0.0,
        "tier_breakdown": {},
        "status": "active",
        "payment_email": "test@example.com",
    }

    await db.create_affiliate(affiliate_data)

    # Add conversions
    await db.increment_affiliate_conversions("aff_123", "pro")
    await db.increment_affiliate_conversions("aff_123", "pro")
    await db.increment_affiliate_conversions("aff_123", "premium")

    result = await db.get_affiliate_by_id("aff_123")
    assert result["total_conversions"] == 3
    assert result["tier_breakdown"]["pro"] == 2
    assert result["tier_breakdown"]["premium"] == 1


# ============================================================================
# Click tracking tests
# ============================================================================

@pytest.mark.asyncio
async def test_create_affiliate_click(db):
    """Test recording a referral click."""
    click_data = {
        "id": "click_123",
        "affiliate_id": "aff_456",
        "referral_code": "test_code",
        "clicked_at": 1234567890.0,
        "source": "twitter",
        "ip_address": "192.168.1.1",
        "converted": False,
        "converted_at": None,
        "user_id": None,
    }

    await db.create_affiliate_click(click_data)

    # Verify it was created
    row = await db.db.execute_fetchone(
        "SELECT * FROM affiliate_clicks WHERE id = ?", ("click_123",)
    )
    assert row is not None
    assert row[1] == "aff_456"  # affiliate_id
    assert row[2] == "test_code"  # referral_code


@pytest.mark.asyncio
async def test_mark_click_converted(db):
    """Test marking a click as converted."""
    click_data = {
        "id": "click_123",
        "affiliate_id": "aff_456",
        "referral_code": "test_code",
        "clicked_at": 1234567890.0,
        "source": "email",
        "ip_address": "192.168.1.1",
        "converted": False,
        "converted_at": None,
        "user_id": None,
    }

    await db.create_affiliate_click(click_data)

    # Mark as converted
    now = time.time()
    await db.mark_click_converted("click_123", "user_789", now)

    # Verify conversion
    row = await db.db.execute_fetchone(
        "SELECT converted, user_id, converted_at FROM affiliate_clicks WHERE id = ?",
        ("click_123",)
    )
    assert row[0] == 1  # converted
    assert row[1] == "user_789"  # user_id
    assert row[2] == now  # converted_at


@pytest.mark.asyncio
async def test_count_affiliate_clicks(db):
    """Test counting clicks for an affiliate."""
    # Create multiple clicks
    for i in range(5):
        click_data = {
            "id": f"click_{i}",
            "affiliate_id": "aff_123",
            "referral_code": "test_code",
            "clicked_at": 1234567890.0 + i,
            "source": "web",
            "ip_address": f"192.168.1.{i}",
            "converted": False,
            "converted_at": None,
            "user_id": None,
        }
        await db.create_affiliate_click(click_data)

    count = await db.count_affiliate_clicks("aff_123")
    assert count == 5


@pytest.mark.asyncio
async def test_count_affiliate_conversions(db):
    """Test counting conversions for an affiliate."""
    # Create clicks with some converted
    for i in range(5):
        click_data = {
            "id": f"click_{i}",
            "affiliate_id": "aff_123",
            "referral_code": "test_code",
            "clicked_at": 1234567890.0 + i,
            "source": "web",
            "ip_address": f"192.168.1.{i}",
            "converted": False,
            "converted_at": None,
            "user_id": None,
        }
        await db.create_affiliate_click(click_data)

    # Convert 2 of them
    await db.mark_click_converted("click_0", "user_1", time.time())
    await db.mark_click_converted("click_2", "user_2", time.time())

    count = await db.count_affiliate_conversions("aff_123")
    assert count == 2


# ============================================================================
# Commission tests
# ============================================================================

@pytest.mark.asyncio
async def test_create_commission(db):
    """Test creating a commission record."""
    commission_data = {
        "id": "comm_123",
        "affiliate_id": "aff_456",
        "user_id": "user_789",
        "subscription_tier": "premium",
        "amount_usd": 10.00,
        "recurring_monthly": True,
        "accrued_at": 1234567890.0,
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "payout_id": None,
        "paid_at": None,
        "status": "pending",
    }

    await db.create_commission(commission_data)

    # Verify it was created
    row = await db.db.execute_fetchone(
        "SELECT * FROM commissions WHERE id = ?", ("comm_123",)
    )
    assert row is not None
    assert row[1] == "aff_456"  # affiliate_id
    assert row[3] == "premium"  # subscription_tier
    assert row[4] == 10.00  # amount_usd


@pytest.mark.asyncio
async def test_get_affiliate_commissions(db):
    """Test retrieving commissions for an affiliate."""
    # Create multiple commissions
    for i in range(3):
        commission_data = {
            "id": f"comm_{i}",
            "affiliate_id": "aff_123",
            "user_id": f"user_{i}",
            "subscription_tier": "pro",
            "amount_usd": 4.00,
            "recurring_monthly": True,
            "accrued_at": 1234567890.0 + i,
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "payout_id": None,
            "paid_at": None,
            "status": "pending",
        }
        await db.create_commission(commission_data)

    commissions = await db.get_affiliate_commissions("aff_123")
    assert len(commissions) == 3


@pytest.mark.asyncio
async def test_get_pending_commissions(db):
    """Test retrieving pending commissions."""
    # Create commissions with different statuses
    for i in range(5):
        status = "pending" if i < 3 else "paid"
        commission_data = {
            "id": f"comm_{i}",
            "affiliate_id": "aff_123",
            "user_id": f"user_{i}",
            "subscription_tier": "pro",
            "amount_usd": 4.00,
            "recurring_monthly": True,
            "accrued_at": 1234567890.0 + i,
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "payout_id": None if status == "pending" else "payout_1",
            "paid_at": None if status == "pending" else 1234567900.0,
            "status": status,
        }
        await db.create_commission(commission_data)

    pending = await db.get_pending_commissions("aff_123")
    assert len(pending) == 3


@pytest.mark.asyncio
async def test_update_commission_status(db):
    """Test updating commission status."""
    commission_data = {
        "id": "comm_123",
        "affiliate_id": "aff_456",
        "user_id": "user_789",
        "subscription_tier": "premium",
        "amount_usd": 10.00,
        "recurring_monthly": True,
        "accrued_at": 1234567890.0,
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "payout_id": None,
        "paid_at": None,
        "status": "pending",
    }

    await db.create_commission(commission_data)

    # Update to paid
    now = time.time()
    await db.update_commission_status(
        "comm_123",
        payout_id="payout_999",
        paid_at=now,
        status="paid",
    )

    # Verify update
    row = await db.db.execute_fetchone(
        "SELECT payout_id, paid_at, status FROM commissions WHERE id = ?",
        ("comm_123",)
    )
    assert row[0] == "payout_999"
    assert row[1] == now
    assert row[2] == "paid"


# ============================================================================
# Payout tests
# ============================================================================

@pytest.mark.asyncio
async def test_create_payout(db):
    """Test creating a payout request."""
    payout_data = {
        "id": "payout_123",
        "affiliate_id": "aff_456",
        "amount_usd": 150.00,
        "commission_ids": ["comm_1", "comm_2", "comm_3"],
        "requested_at": 1234567890.0,
        "processed_at": None,
        "status": "pending",
        "payment_method": "paypal",
        "payment_email": "affiliate@example.com",
        "transaction_id": None,
        "notes": None,
    }

    await db.create_payout(payout_data)

    # Verify it was created
    result = await db.get_payout_by_id("payout_123")
    assert result is not None
    assert result["amount_usd"] == 150.00
    assert len(result["commission_ids"]) == 3
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_update_payout_status(db):
    """Test updating payout status."""
    payout_data = {
        "id": "payout_123",
        "affiliate_id": "aff_456",
        "amount_usd": 150.00,
        "commission_ids": ["comm_1", "comm_2"],
        "requested_at": 1234567890.0,
        "processed_at": None,
        "status": "pending",
        "payment_method": "stripe",
        "payment_email": "affiliate@example.com",
        "transaction_id": None,
        "notes": None,
    }

    await db.create_payout(payout_data)

    # Update to completed
    now = time.time()
    await db.update_payout_status(
        "payout_123",
        status="completed",
        processed_at=now,
        transaction_id="txn_abc123",
        notes="Processed successfully",
    )

    # Verify update
    result = await db.get_payout_by_id("payout_123")
    assert result["status"] == "completed"
    assert result["processed_at"] == now
    assert result["transaction_id"] == "txn_abc123"
    assert result["notes"] == "Processed successfully"


@pytest.mark.asyncio
async def test_get_affiliate_payouts(db):
    """Test retrieving all payouts for an affiliate."""
    # Create multiple payouts
    for i in range(3):
        payout_data = {
            "id": f"payout_{i}",
            "affiliate_id": "aff_123",
            "amount_usd": 100.00 + (i * 50),
            "commission_ids": [f"comm_{i}"],
            "requested_at": 1234567890.0 + i,
            "processed_at": None,
            "status": "pending",
            "payment_method": "paypal",
            "payment_email": "affiliate@example.com",
            "transaction_id": None,
            "notes": None,
        }
        await db.create_payout(payout_data)

    payouts = await db.get_affiliate_payouts("aff_123")
    assert len(payouts) == 3
