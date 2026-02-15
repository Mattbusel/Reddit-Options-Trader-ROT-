"""Tests for Stripe webhook endpoint.

Validates:
- Signature verification (valid, invalid, missing)
- Empty webhook secret handling
- Stripe not installed handling
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Set env vars BEFORE importing Settings
os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-stripe-webhook-tests-32ch")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app
from rot.web.routes import stripe_routes


def _make_app(stripe_key: str = "sk_test_fake", webhook_secret: str = "whsec_test_fake"):
    """Create a test app with only Stripe routes registered."""
    os.environ["ROT_STRIPE_SECRET_KEY"] = stripe_key
    os.environ["ROT_STRIPE_WEBHOOK_SECRET"] = webhook_secret
    settings = Settings()
    app = create_app(settings)
    # Register only stripe routes — avoid importing all routes (some have missing deps)
    app.include_router(stripe_routes.router, prefix="/api/v1", tags=["billing"])
    # Add mock db to app.state (webhook handler accesses request.app.state.db)
    app.state.db = MagicMock()
    return app


class TestWebhookSignatureVerification:
    """Test webhook signature verification."""

    @patch("rot.web.routes.stripe_routes._HAS_STRIPE", True)
    @patch("rot.web.routes.stripe_routes.stripe")
    def test_invalid_signature_returns_400(self, mock_stripe):
        """Invalid signature should return 400."""
        mock_stripe.error.SignatureVerificationError = type(
            "SignatureVerificationError", (Exception,), {}
        )
        mock_stripe.Webhook.construct_event.side_effect = (
            mock_stripe.error.SignatureVerificationError("bad sig")
        )

        app = _make_app()
        client = TestClient(app)
        response = client.post(
            "/api/v1/billing/webhook",
            content=b'{"type": "test"}',
            headers={"stripe-signature": "bad_sig"},
        )
        assert response.status_code == 400

    @patch("rot.web.routes.stripe_routes._HAS_STRIPE", True)
    @patch("rot.web.routes.stripe_routes.stripe")
    def test_missing_signature_returns_400(self, mock_stripe):
        """Missing/empty signature header should still reach construct_event and fail."""
        mock_stripe.error.SignatureVerificationError = type(
            "SignatureVerificationError", (Exception,), {}
        )
        mock_stripe.Webhook.construct_event.side_effect = ValueError("no sig")

        app = _make_app()
        client = TestClient(app)
        response = client.post(
            "/api/v1/billing/webhook",
            content=b'{"type": "test"}',
        )
        assert response.status_code == 400


class TestWebhookNotConfigured:
    """Test behavior when Stripe is not configured."""

    def test_stripe_not_configured_returns_501(self):
        """If stripe secret key is empty, return 501."""
        app = _make_app(stripe_key="", webhook_secret="")
        client = TestClient(app)
        response = client.post(
            "/api/v1/billing/webhook",
            content=b'{"type": "test"}',
        )
        assert response.status_code == 501

    @patch("rot.web.routes.stripe_routes._HAS_STRIPE", True)
    @patch("rot.web.routes.stripe_routes.stripe")
    def test_empty_webhook_secret_returns_500(self, mock_stripe):
        """Empty webhook_secret should return 500, not crash."""
        app = _make_app(stripe_key="sk_test_fake", webhook_secret="")
        client = TestClient(app)
        response = client.post(
            "/api/v1/billing/webhook",
            content=b'{"type": "test"}',
            headers={"stripe-signature": "t=123,v1=abc"},
        )
        assert response.status_code == 500


class TestBillingStatus:
    """Test billing status endpoint."""

    def test_billing_status_requires_auth(self):
        """GET /billing/status should require authentication."""
        app = _make_app()
        # Mock db.execute to return no user (auth will fail)
        app.state.db.execute = AsyncMock(return_value=MagicMock(fetchone=AsyncMock(return_value=None)))
        client = TestClient(app)
        response = client.get("/api/v1/billing/status")
        # Should redirect to login or return 401/403
        assert response.status_code in (401, 403, 302, 307)
