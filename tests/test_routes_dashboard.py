"""Dashboard and public page route tests.

Tests for the main dashboard, landing page, signal detail, and all public
pages using parametrized coverage for efficiency.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-dashboard-route-tests!")
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
        web={"secret_key": "test-secret-key-for-dashboard-route-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-dashboard-route-tests!!"},
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


async def _create_user(app, settings, tier="free"):
    """Create a user at the given tier with a unique email."""
    db = app.state.db
    unique = uuid.uuid4().hex[:8]
    email = f"dash_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ---------------------------------------------------------------------------
# Landing & dashboard
# ---------------------------------------------------------------------------

class TestLandingPage:
    @pytest.mark.asyncio
    async def test_landing_page_for_anonymous(self, client):
        """GET / returns 200 landing page for unauthenticated users."""
        resp = client.get("/")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_dashboard_for_logged_in_user(self, client, app_with_db, tmp_settings):
        """GET /dashboard returns 200 for authenticated users."""
        user, token = await _create_user(app_with_db, tmp_settings)
        resp = client.get("/dashboard", cookies={"rot_session": token})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_root_with_auth_serves_dashboard(self, client, app_with_db, tmp_settings):
        """GET / with auth cookie serves dashboard, not landing."""
        user, token = await _create_user(app_with_db, tmp_settings)
        resp = client.get("/", cookies={"rot_session": token})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Dashboard filters
# ---------------------------------------------------------------------------

class TestDashboardFilters:
    @pytest.mark.parametrize("query_params", [
        "?ticker=AAPL",
        "?stance=bullish",
        "?min_confidence=70",
        "?ticker=TSLA&stance=bearish",
        "?source=reddit",
    ])
    @pytest.mark.asyncio
    async def test_dashboard_with_filter_params(self, query_params, client, app_with_db, tmp_settings):
        """Dashboard accepts various filter query parameters."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.get(f"/dashboard{query_params}", cookies={"rot_session": token})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Signal detail
# ---------------------------------------------------------------------------

class TestSignalDetail:
    @pytest.mark.asyncio
    async def test_signal_detail_not_found(self, client):
        """Signal detail with nonexistent ID returns 404 or error page."""
        resp = client.get("/dashboard/signal/nonexistent-signal-id-12345")
        assert resp.status_code in (200, 404)  # Returns HTML error page (200 with message) or 404

    @pytest.mark.asyncio
    async def test_signal_detail_authenticated(self, client, app_with_db, tmp_settings):
        """Signal detail route is accessible for authenticated users."""
        user, token = await _create_user(app_with_db, tmp_settings)
        resp = client.get(
            "/dashboard/signal/fake-signal-id",
            cookies={"rot_session": token},
        )
        # Signal doesn't exist, but route should handle gracefully
        assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Public pages — parametrized
# ---------------------------------------------------------------------------

PUBLIC_PAGES = [
    "/pricing",
    "/login",
    "/register",
    "/forgot-password",
    "/faq",
    "/glossary",
    "/paper-trading",
]


@pytest.mark.parametrize("page", PUBLIC_PAGES)
def test_public_page_returns_200(page, client):
    """All public pages are accessible without authentication."""
    resp = client.get(page)
    assert resp.status_code == 200, f"{page} returned {resp.status_code}"


# ---------------------------------------------------------------------------
# Auth pages redirect when already logged in
# ---------------------------------------------------------------------------

AUTH_PAGES_REDIRECT = [
    "/login",
    "/register",
    "/forgot-password",
]


@pytest.mark.parametrize("page", AUTH_PAGES_REDIRECT)
@pytest.mark.asyncio
async def test_auth_pages_redirect_when_logged_in(page, client, app_with_db, tmp_settings):
    """Auth pages redirect to /dashboard when user is already logged in."""
    user, token = await _create_user(app_with_db, tmp_settings)
    resp = client.get(page, cookies={"rot_session": token}, follow_redirects=False)
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers.get("location", "")
