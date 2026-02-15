"""Tests for NonceTemplates — CSP nonce auto-injection into template context."""
from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

# Set env vars BEFORE importing Settings
os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-nonce-template-tests-32c")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app
from rot.web.nonce_templates import NonceTemplates


class TestNonceTemplatesUnit:
    """Unit tests for the NonceTemplates subclass."""

    def test_is_subclass_of_jinja2_templates(self):
        from fastapi.templating import Jinja2Templates
        assert issubclass(NonceTemplates, Jinja2Templates)

    def test_injects_nonce_from_request_state(self, tmp_path):
        """When request.state.csp_nonce is set, it appears in context."""
        from starlette.requests import Request
        from starlette.datastructures import State

        # Write a minimal template
        (tmp_path / "test.html").write_text("<html>{{ csp_nonce }}</html>")
        templates = NonceTemplates(directory=str(tmp_path))

        # Create a mock request with csp_nonce on state
        scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}
        request = Request(scope)
        request.state.csp_nonce = "test-nonce-abc123"

        context = {"request": request}
        response = templates.TemplateResponse("test.html", context)

        # The nonce should appear in the rendered body
        body = response.body.decode()
        assert "test-nonce-abc123" in body

    def test_does_not_overwrite_explicit_nonce(self, tmp_path):
        """If csp_nonce is already in context, don't overwrite it."""
        from starlette.requests import Request

        (tmp_path / "test.html").write_text("<html>{{ csp_nonce }}</html>")
        templates = NonceTemplates(directory=str(tmp_path))

        scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}
        request = Request(scope)
        request.state.csp_nonce = "from-middleware"

        context = {"request": request, "csp_nonce": "explicit-nonce"}
        response = templates.TemplateResponse("test.html", context)

        body = response.body.decode()
        assert "explicit-nonce" in body
        assert "from-middleware" not in body

    def test_graceful_without_request_state(self, tmp_path):
        """When request.state has no csp_nonce, no error occurs."""
        from starlette.requests import Request

        (tmp_path / "test.html").write_text("<html>{{ csp_nonce|default('none') }}</html>")
        templates = NonceTemplates(directory=str(tmp_path))

        scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}
        request = Request(scope)

        context = {"request": request}
        response = templates.TemplateResponse("test.html", context)

        body = response.body.decode()
        assert "none" in body


class TestNonceInCSPHeader:
    """Integration: verify CSP header and template nonce match."""

    @pytest.fixture
    def client(self):
        settings = Settings()
        app = create_app(settings)
        return TestClient(app)

    def test_csp_header_contains_nonce(self, client):
        import re
        response = client.get("/health")
        csp = response.headers.get("Content-Security-Policy", "")
        assert "nonce-" in csp
        # script-src must NOT have unsafe-inline (style-src is allowed to)
        script_src = re.search(r"script-src\s+([^;]+)", csp)
        assert script_src, "No script-src directive found"
        assert "'unsafe-inline'" not in script_src.group(1)

    def test_nonce_unique_per_request(self, client):
        import re
        r1 = client.get("/health")
        r2 = client.get("/health")
        csp1 = r1.headers["Content-Security-Policy"]
        csp2 = r2.headers["Content-Security-Policy"]
        nonce1 = re.search(r"'nonce-([^']+)'", csp1).group(1)
        nonce2 = re.search(r"'nonce-([^']+)'", csp2).group(1)
        assert nonce1 != nonce2

    def test_nonce_in_script_src_and_style_uses_unsafe_inline(self, client):
        import re
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        nonce_match = re.search(r"'nonce-([^']+)'", csp)
        assert nonce_match, "No nonce found in CSP"
        nonce = nonce_match.group(1)
        assert f"script-src 'self' 'nonce-{nonce}'" in csp
        # style-src uses unsafe-inline (Tailwind CDN generates styles at runtime)
        assert "style-src 'self' 'unsafe-inline'" in csp

    def test_csp_still_allows_cdn_domains(self, client):
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        assert "https://cdn.tailwindcss.com" in csp
        assert "https://js.stripe.com" in csp
        assert "https://api.stripe.com" in csp
