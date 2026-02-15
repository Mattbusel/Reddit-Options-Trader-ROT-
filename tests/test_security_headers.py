"""Tests for security headers middleware.

Validates that all HTTP responses include required security headers:
- Content-Security-Policy
- X-Content-Type-Options
- X-Frame-Options
- Referrer-Policy
- X-XSS-Protection
- Permissions-Policy
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Set env vars BEFORE importing Settings to avoid validation errors
os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-security-header-tests-32c")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app


@pytest.fixture
def client():
    """Create test client with security headers middleware active."""
    settings = Settings()
    app = create_app(settings)
    return TestClient(app)


class TestSecurityHeaders:
    """Test that security headers are present on responses."""

    def test_x_content_type_options(self, client):
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        response = client.get("/health")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, client):
        response = client.get("/health")
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_x_xss_protection(self, client):
        response = client.get("/health")
        assert response.headers.get("X-XSS-Protection") == "0"

    def test_permissions_policy(self, client):
        response = client.get("/health")
        policy = response.headers.get("Permissions-Policy", "")
        assert "camera=()" in policy
        assert "microphone=()" in policy

    def test_csp_present(self, client):
        response = client.get("/health")
        csp = response.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp

    def test_csp_allows_tailwind_cdn(self, client):
        response = client.get("/health")
        csp = response.headers.get("Content-Security-Policy", "")
        assert "https://cdn.tailwindcss.com" in csp

    def test_csp_allows_stripe(self, client):
        response = client.get("/health")
        csp = response.headers.get("Content-Security-Policy", "")
        assert "https://js.stripe.com" in csp
        assert "https://api.stripe.com" in csp

    def test_csp_allows_websockets(self, client):
        response = client.get("/health")
        csp = response.headers.get("Content-Security-Policy", "")
        assert "ws:" in csp
        assert "wss:" in csp

    def test_headers_on_404(self, client):
        """Security headers should be present even on error responses."""
        response = client.get("/nonexistent-page-12345")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
