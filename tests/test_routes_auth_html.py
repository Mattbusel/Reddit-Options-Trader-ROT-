"""HTML auth flow route tests.

Tests for login form, register form, logout, forgot-password HTML endpoints.
Uses both individual and parametrized tests.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-auth-html-route-tests!!")
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
        web={"secret_key": "test-secret-key-for-auth-html-route-tests!!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-auth-html-route-tests!!!!"},
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


async def _create_test_user(app, settings, email=None, password="TestPass123!"):
    """Create a test user with given email, return (user, token)."""
    if email is None:
        email = f"authhtml_{uuid.uuid4().hex[:8]}@example.com"
    db = app.state.db
    pw_hash = hash_password(password)
    user = await db.create_user(email, pw_hash)
    token = create_access_token(user["id"], user["email"], user["tier"], settings)
    return user, token


async def _clear_rate_limits(app):
    """Clear the auth_attempts table to prevent rate limiting in tests."""
    db = app.state.db
    try:
        await db.db.execute("DELETE FROM auth_attempts")
        await db.db.commit()
    except Exception:
        pass  # Table may not exist in fresh DBs


def _get_csrf_token(client, path="/login"):
    """GET a page to obtain the CSRF cookie, return the token string."""
    resp = client.get(path)
    csrf = resp.cookies.get("rot_csrf")
    return csrf


def _post_form_with_csrf(client, path, data, csrf_token=None, follow_redirects=True):
    """POST form data with CSRF token properly set."""
    if csrf_token is None:
        csrf_token = _get_csrf_token(client, path)
    data["csrf_token"] = csrf_token
    return client.post(
        path,
        data=data,
        cookies={"rot_csrf": csrf_token},
        follow_redirects=follow_redirects,
    )


# ---------------------------------------------------------------------------
# Login form
# ---------------------------------------------------------------------------

class TestLoginForm:
    @pytest.mark.asyncio
    async def test_login_page_renders(self, client):
        """GET /login returns 200 with HTML."""
        resp = client.get("/login")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_login_form_success_redirects(self, client, app_with_db, tmp_settings):
        """POST /login with valid credentials redirects to /dashboard."""
        await _clear_rate_limits(app_with_db)
        email = f"login_ok_{uuid.uuid4().hex[:6]}@example.com"
        await _create_test_user(app_with_db, tmp_settings, email=email)
        resp = _post_form_with_csrf(
            client, "/login",
            {"email": email, "password": "TestPass123!"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_login_form_wrong_password_returns_page(self, client, app_with_db, tmp_settings):
        """POST /login with wrong password returns login page with error."""
        await _clear_rate_limits(app_with_db)
        email = f"wrongpw_{uuid.uuid4().hex[:6]}@example.com"
        await _create_test_user(app_with_db, tmp_settings, email=email)
        resp = _post_form_with_csrf(
            client, "/login",
            {"email": email, "password": "WrongPass!"},
        )
        assert resp.status_code == 200
        assert b"Invalid" in resp.content or b"invalid" in resp.content

    @pytest.mark.asyncio
    async def test_login_form_nonexistent_email(self, client, app_with_db):
        """POST /login with unknown email returns login page with error."""
        await _clear_rate_limits(app_with_db)
        resp = _post_form_with_csrf(
            client, "/login",
            {"email": "nobody@example.com", "password": "SomePass123!"},
        )
        assert resp.status_code == 200
        assert b"Invalid" in resp.content or b"invalid" in resp.content


# ---------------------------------------------------------------------------
# Register form
# ---------------------------------------------------------------------------

class TestRegisterForm:
    @pytest.mark.asyncio
    async def test_register_page_renders(self, client):
        """GET /register returns 200 with HTML."""
        resp = client.get("/register")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_register_form_success_redirects(self, client, app_with_db):
        """POST /register with valid data redirects to /dashboard."""
        await _clear_rate_limits(app_with_db)
        unique = uuid.uuid4().hex[:8]
        resp = _post_form_with_csrf(
            client, "/register",
            {
                "email": f"newuser_{unique}@example.com",
                "password": "SecurePass123!",
                "confirm_password": "SecurePass123!",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_register_form_password_mismatch(self, client, app_with_db):
        """POST /register with mismatched passwords shows error."""
        await _clear_rate_limits(app_with_db)
        unique = uuid.uuid4().hex[:8]
        resp = _post_form_with_csrf(
            client, "/register",
            {
                "email": f"mismatch_{unique}@example.com",
                "password": "SecurePass123!",
                "confirm_password": "DifferentPass123!",
            },
        )
        assert resp.status_code == 200
        assert b"match" in resp.content.lower()

    @pytest.mark.asyncio
    async def test_register_form_short_password(self, client, app_with_db):
        """POST /register with short password shows error."""
        await _clear_rate_limits(app_with_db)
        unique = uuid.uuid4().hex[:8]
        resp = _post_form_with_csrf(
            client, "/register",
            {
                "email": f"short_{unique}@example.com",
                "password": "abc",
                "confirm_password": "abc",
            },
        )
        assert resp.status_code == 200
        assert b"8 character" in resp.content or b"characters" in resp.content

    @pytest.mark.asyncio
    async def test_register_form_duplicate_email(self, client, app_with_db, tmp_settings):
        """POST /register with existing email shows error."""
        await _clear_rate_limits(app_with_db)
        unique = uuid.uuid4().hex[:8]
        email = f"dup_{unique}@example.com"
        await _create_test_user(app_with_db, tmp_settings, email=email)
        resp = _post_form_with_csrf(
            client, "/register",
            {
                "email": email,
                "password": "AnotherPass123!",
                "confirm_password": "AnotherPass123!",
            },
        )
        assert resp.status_code == 200
        assert b"already" in resp.content.lower()


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_clears_cookie(self, client, app_with_db, tmp_settings):
        """GET /logout removes the rot_session cookie."""
        user, token = await _create_test_user(app_with_db, tmp_settings, f"logout_{uuid.uuid4().hex[:6]}@example.com")
        resp = client.get(
            "/logout",
            cookies={"rot_session": token},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/" in resp.headers.get("location", "")


# ---------------------------------------------------------------------------
# Forgot password
# ---------------------------------------------------------------------------

class TestForgotPassword:
    @pytest.mark.asyncio
    async def test_forgot_password_page_renders(self, client):
        """GET /forgot-password returns 200."""
        resp = client.get("/forgot-password")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_forgot_password_unknown_email(self, client, app_with_db):
        """POST /forgot-password with unknown email shows error."""
        await _clear_rate_limits(app_with_db)
        resp = _post_form_with_csrf(
            client, "/forgot-password",
            {"email": "noone@nowhere.com"},
        )
        assert resp.status_code == 200
        # Should show "no account" type error
        assert b"No account" in resp.content or b"not found" in resp.content.lower()
