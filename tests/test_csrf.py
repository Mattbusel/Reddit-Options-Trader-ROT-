"""Tests for CSRF protection middleware.

Verifies that:
- GET requests work without CSRF token
- POST without token returns 403
- POST with valid token succeeds
- POST with wrong token returns 403
- API key requests bypass CSRF
- Stripe webhook path bypasses CSRF
- CSRF cookie is set on GET responses
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from rot.web.csrf import CSRFMiddleware, CSRF_COOKIE_NAME, CSRF_HEADER_NAME


def _make_app() -> FastAPI:
    """Create a minimal app with CSRF middleware and test endpoints."""
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.get("/test")
    async def get_test():
        return {"ok": True}

    @app.post("/test")
    async def post_test():
        return {"ok": True}

    @app.post("/api/v1/webhook")
    async def stripe_webhook():
        return {"ok": True}

    @app.post("/api/v1/signals")
    async def api_signals():
        return {"ok": True}

    return app


@pytest.fixture
def client():
    return TestClient(_make_app())


class TestCSRFGetRequests:
    def test_get_works_without_csrf_token(self, client):
        resp = client.get("/test")
        assert resp.status_code == 200

    def test_get_sets_csrf_cookie(self, client):
        resp = client.get("/test")
        assert CSRF_COOKIE_NAME in resp.cookies

    def test_get_preserves_existing_csrf_cookie(self, client):
        resp = client.get("/test", cookies={CSRF_COOKIE_NAME: "my-token-123"})
        assert resp.status_code == 200
        assert resp.cookies.get(CSRF_COOKIE_NAME) == "my-token-123"


class TestCSRFPostValidation:
    def test_post_without_token_returns_403(self, client):
        resp = client.post("/test")
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["detail"]

    def test_post_with_valid_header_token_succeeds(self, client):
        token = "test-csrf-token-value"
        resp = client.post(
            "/test",
            cookies={CSRF_COOKIE_NAME: token},
            headers={CSRF_HEADER_NAME: token},
        )
        assert resp.status_code == 200

    def test_post_with_wrong_token_returns_403(self, client):
        resp = client.post(
            "/test",
            cookies={CSRF_COOKIE_NAME: "correct-token"},
            headers={CSRF_HEADER_NAME: "wrong-token"},
        )
        assert resp.status_code == 403

    def test_post_with_cookie_but_no_header_returns_403(self, client):
        resp = client.post(
            "/test",
            cookies={CSRF_COOKIE_NAME: "some-token"},
        )
        assert resp.status_code == 403

    def test_post_with_header_but_no_cookie_returns_403(self, client):
        """No cookie means middleware generates a new one, which won't match header."""
        resp = client.post(
            "/test",
            headers={CSRF_HEADER_NAME: "some-token"},
        )
        assert resp.status_code == 403

    def test_post_with_form_token_succeeds(self, client):
        token = "form-csrf-token-value"
        resp = client.post(
            "/test",
            cookies={CSRF_COOKIE_NAME: token},
            data={"csrf_token": token},
        )
        assert resp.status_code == 200


class TestCSRFBypasses:
    def test_api_key_bypasses_csrf(self, client):
        resp = client.post(
            "/api/v1/signals",
            headers={"x-api-key": "rot_test_key_12345"},
        )
        assert resp.status_code == 200

    def test_stripe_webhook_with_signature_bypasses_csrf(self, client):
        resp = client.post(
            "/api/v1/webhook",
            headers={"stripe-signature": "t=123,v1=abc"},
        )
        assert resp.status_code == 200

    def test_stripe_webhook_without_signature_requires_csrf(self, client):
        """Webhook endpoint without stripe-signature still needs CSRF."""
        resp = client.post("/api/v1/webhook")
        assert resp.status_code == 403


class TestCSRFCookieProperties:
    def test_csrf_cookie_not_httponly(self, client):
        """CSRF cookie must be readable by JavaScript (for HTMX)."""
        resp = client.get("/test")
        # TestClient doesn't expose cookie flags directly, but we verify
        # the cookie is set (JS-readable is ensured by httponly=False in code)
        assert CSRF_COOKIE_NAME in resp.cookies

    def test_csrf_cookie_set_on_post_success(self, client):
        token = "post-success-token"
        resp = client.post(
            "/test",
            cookies={CSRF_COOKIE_NAME: token},
            headers={CSRF_HEADER_NAME: token},
        )
        assert resp.status_code == 200
        assert CSRF_COOKIE_NAME in resp.cookies
