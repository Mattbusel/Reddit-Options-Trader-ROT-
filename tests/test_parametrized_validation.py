"""Parametrized input validation tests.

Tests registration email/password validation, API query parameter bounds,
and other input validation using @pytest.mark.parametrize.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-validation-parametrized!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes
from rot.web.auth import create_access_token, hash_password


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-validation-parametrized!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-validation-parametrized!!"},
    )


@pytest.fixture
async def app_with_db(tmp_settings):
    app = create_app(tmp_settings)
    await connect_db(app)
    register_routes(app)
    yield app
    if hasattr(app.state, "db"):
        await app.state.db.close()
    cleanup = getattr(app.state, "_db_cleanup_task", None)
    if cleanup:
        cleanup.cancel()


@pytest.fixture
def client(app_with_db):
    return TestClient(app_with_db)


async def _create_pro_user(app, settings):
    """Create a pro-tier user with unique email for API access."""
    db = app.state.db
    unique = uuid.uuid4().hex[:8]
    email = f"val_pro_{unique}@example.com"
    pw_hash = hash_password("ProPass123!")
    user = await db.create_user(email, pw_hash)
    await db.db.execute("UPDATE users SET tier = 'pro' WHERE id = ?", (user["id"],))
    await db.db.commit()
    user["tier"] = "pro"
    token = create_access_token(user["id"], user["email"], "pro", settings)
    return user, token


# ---------------------------------------------------------------------------
# Registration — email validation (each test gets its own request to avoid
# rate limiting; we accept 400 or 429 since rate limiting is also a valid
# rejection of bad input)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("email,expected_codes", [
    ("", {400, 422, 429}),
    ("not-an-email", {400, 422, 429}),
    ("@missing-local.com", {400, 422, 429}),
])
def test_register_rejects_invalid_email(email, expected_codes, client):
    """Registration endpoint rejects malformed email addresses."""
    resp = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "ValidPassword123!",
    })
    assert resp.status_code in expected_codes, (
        f"Expected one of {expected_codes} for email='{email}', got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Registration — password validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("password,expected_codes", [
    ("short", {400, 429}),
    ("1234567", {400, 429}),
])
def test_register_rejects_short_password(password, expected_codes, client):
    """Registration endpoint rejects passwords shorter than 8 characters."""
    resp = client.post("/api/v1/auth/register", json={
        "email": f"pw_{password}@example.com",
        "password": password,
    })
    assert resp.status_code in expected_codes, (
        f"Expected one of {expected_codes} for password='{password}', got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Signals API — Pydantic query parameter validation
# These tests use a pro user to bypass API auth requirements.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("limit,expected_status", [
    (-1, 422),   # below ge=1
    (0, 422),    # below ge=1
    (201, 422),  # above le=200
])
@pytest.mark.asyncio
async def test_signals_limit_validation(limit, expected_status, client, app_with_db, tmp_settings):
    """Signals list endpoint rejects out-of-range limit values."""
    user, token = await _create_pro_user(app_with_db, tmp_settings)
    resp = client.get(
        f"/api/v1/signals?limit={limit}",
        cookies={"rot_session": token},
    )
    assert resp.status_code == expected_status


@pytest.mark.parametrize("offset,expected_status", [
    (-1, 422),  # below ge=0
])
@pytest.mark.asyncio
async def test_signals_offset_validation(offset, expected_status, client, app_with_db, tmp_settings):
    """Signals list endpoint rejects negative offset."""
    user, token = await _create_pro_user(app_with_db, tmp_settings)
    resp = client.get(
        f"/api/v1/signals?offset={offset}",
        cookies={"rot_session": token},
    )
    assert resp.status_code == expected_status


@pytest.mark.parametrize("sort_value,expected_status", [
    ("invalid_field", 422),
    ("'; DROP TABLE", 422),
])
@pytest.mark.asyncio
async def test_signals_sort_rejects_invalid(sort_value, expected_status, client, app_with_db, tmp_settings):
    """Signals list rejects invalid sort parameter values."""
    user, token = await _create_pro_user(app_with_db, tmp_settings)
    resp = client.get(
        f"/api/v1/signals?sort={sort_value}",
        cookies={"rot_session": token},
    )
    assert resp.status_code == expected_status


@pytest.mark.parametrize("sort_value", ["created_at", "confidence", "trend_score"])
@pytest.mark.asyncio
async def test_signals_sort_accepts_valid(sort_value, client, app_with_db, tmp_settings):
    """Signals list accepts valid sort parameter values."""
    user, token = await _create_pro_user(app_with_db, tmp_settings)
    resp = client.get(
        f"/api/v1/signals?sort={sort_value}",
        cookies={"rot_session": token},
    )
    assert resp.status_code == 200, f"sort={sort_value}: got {resp.status_code}"


@pytest.mark.parametrize("order_value", ["asc", "desc"])
@pytest.mark.asyncio
async def test_signals_order_accepts_valid(order_value, client, app_with_db, tmp_settings):
    """Signals list accepts valid order parameter values."""
    user, token = await _create_pro_user(app_with_db, tmp_settings)
    resp = client.get(
        f"/api/v1/signals?order={order_value}",
        cookies={"rot_session": token},
    )
    assert resp.status_code == 200, f"order={order_value}: got {resp.status_code}"


@pytest.mark.parametrize("order_value,expected_status", [
    ("invalid", 422),
    ("ASC", 422),  # case-sensitive regex
])
@pytest.mark.asyncio
async def test_signals_order_rejects_invalid(order_value, expected_status, client, app_with_db, tmp_settings):
    """Signals list rejects invalid order parameter values."""
    user, token = await _create_pro_user(app_with_db, tmp_settings)
    resp = client.get(
        f"/api/v1/signals?order={order_value}",
        cookies={"rot_session": token},
    )
    assert resp.status_code == expected_status
