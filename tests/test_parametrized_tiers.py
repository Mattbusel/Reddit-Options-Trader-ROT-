"""Parametrized tier-gating tests.

Tests that tier-gated HTML pages and API endpoints respond correctly
across all tiers. Uses parametrize over (endpoint, tier) matrices
to efficiently cover many combinations.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-tier-parametrized-tests!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes
from rot.web.auth import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-tier-parametrized-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-tier-parametrized-tests!!"},
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


async def _create_user_at_tier(app, settings, tier: str):
    """Helper to create a user at a given tier with a unique email."""
    db = app.state.db
    unique = uuid.uuid4().hex[:8]
    email = f"tier_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ---------------------------------------------------------------------------
# HTML pages — all tiers should get 200 (gating is in-page, not 403)
# ---------------------------------------------------------------------------

TIERS = ["free", "pro", "premium", "ultra", "enterprise"]

HTML_PAGES = [
    "/paper-trading",
    "/pricing",
    "/faq",
]


@pytest.mark.parametrize("page", HTML_PAGES)
@pytest.mark.parametrize("tier", TIERS)
@pytest.mark.asyncio
async def test_html_page_accessible_all_tiers(page, tier, client, app_with_db, tmp_settings):
    """HTML pages return 200 for all authenticated tiers."""
    user, token = await _create_user_at_tier(app_with_db, tmp_settings, tier)
    resp = client.get(page, cookies={"rot_session": token})
    assert resp.status_code == 200, f"{page} returned {resp.status_code} for tier={tier}"


# ---------------------------------------------------------------------------
# API endpoints — auth required returns 401/403 for unauthenticated
# ---------------------------------------------------------------------------

API_AUTH_REQUIRED = [
    ("POST", "/api/v1/paper-trading/trade"),
    ("GET", "/api/v1/paper-trading/portfolio"),
    ("GET", "/api/v1/auth/me"),
]


@pytest.mark.parametrize("method,path", API_AUTH_REQUIRED)
def test_api_requires_auth(method, path, client):
    """API endpoints that require auth return 401 or 403 when unauthenticated."""
    if method == "GET":
        resp = client.get(path)
    else:
        resp = client.post(path, json={})
    assert resp.status_code in (401, 403, 422), f"{method} {path} returned {resp.status_code}"


# ---------------------------------------------------------------------------
# Performance history tier gating — free blocked, pro+ allowed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tier,expected_status", [
    ("free", 403),
    ("pro", 200),
    ("premium", 200),
    ("ultra", 200),
    ("enterprise", 200),
])
@pytest.mark.asyncio
async def test_performance_history_tier_gating(tier, expected_status, client, app_with_db, tmp_settings):
    """Performance history is blocked for free tier, allowed for pro+."""
    user, token = await _create_user_at_tier(app_with_db, tmp_settings, tier)
    resp = client.get("/api/v1/performance/history", cookies={"rot_session": token})
    assert resp.status_code == expected_status, (
        f"GET /api/v1/performance/history expected {expected_status} for tier={tier}, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Public endpoints — no auth required, always 200
# ---------------------------------------------------------------------------

PUBLIC_ENDPOINTS = [
    "/health",
    "/api/v1/health",
]


@pytest.mark.parametrize("endpoint", PUBLIC_ENDPOINTS)
def test_public_endpoints_always_200(endpoint, client):
    """Public endpoints return 200 without any authentication."""
    resp = client.get(endpoint)
    assert resp.status_code == 200
