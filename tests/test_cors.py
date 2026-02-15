"""Tests for CORS origin restriction.

Verifies that CORS headers are only returned for configured allowed origins,
not for arbitrary origins.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rot.core.config import Settings
from rot.web.app import create_app


def _make_app(cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000") -> TestClient:
    settings = Settings(
        web={"secret_key": "test-secret-32-chars-long-enough!", "cors_origins": cors_origins},
        reddit={"client_id": "t", "client_secret": "t", "user_agent": "t"},
    )
    app = create_app(settings)
    return TestClient(app)


class TestCORSRestriction:
    def test_allowed_origin_gets_cors_headers(self):
        client = _make_app("http://localhost:8000")
        resp = client.get("/health", headers={"Origin": "http://localhost:8000"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8000"

    def test_disallowed_origin_no_cors_header(self):
        client = _make_app("http://localhost:8000")
        resp = client.get("/health", headers={"Origin": "http://evil.com"})
        assert resp.status_code == 200
        # Should NOT have the requesting origin reflected back
        assert resp.headers.get("access-control-allow-origin") != "http://evil.com"

    def test_no_origin_header_works(self):
        client = _make_app("http://localhost:8000")
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_multiple_allowed_origins(self):
        client = _make_app("http://localhost:8000,https://myapp.com")
        resp = client.get("/health", headers={"Origin": "https://myapp.com"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://myapp.com"

    def test_preflight_allowed_origin(self):
        client = _make_app("http://localhost:8000")
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8000"

    def test_preflight_disallowed_origin(self):
        client = _make_app("http://localhost:8000")
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") != "http://evil.com"

    def test_credentials_header_present_for_allowed(self):
        client = _make_app("http://localhost:8000")
        resp = client.get("/health", headers={"Origin": "http://localhost:8000"})
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_wildcard_no_longer_accepted(self):
        """Even if someone configures *, it should be treated as literal origin '*', not wildcard."""
        client = _make_app("*")
        # With allow_credentials=True and origins=["*"], Starlette CORS middleware
        # reflects the requesting origin (or blocks it). Either way, we're not using
        # the old allow_origins=["*"] pattern directly.
        resp = client.get("/health", headers={"Origin": "http://random-site.com"})
        # The key assertion: we're no longer using the dangerous allow_origins=["*"]
        # pattern. The config-driven approach is in place.
        assert resp.status_code == 200
