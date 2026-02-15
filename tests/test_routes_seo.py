"""
Comprehensive tests for SEO routes (all public access).

Routes tested:
- GET /robots.txt
- GET /llms.txt
- GET /sitemap.xml
- GET /og-image.svg
- GET /favicon.svg

Coverage:
- Public access (no authentication required)
- Response formats (text/plain, application/xml, image/svg+xml)
- Content validation
- Cache headers
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-seo-tests!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-seo-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-seo-tests!!"},
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


# ============================================================================
# GET /robots.txt - Robots File Tests
# ============================================================================

class TestRobotsTxt:
    @pytest.mark.asyncio
    async def test_robots_public_access(self, client):
        """Robots.txt is publicly accessible."""
        response = client.get("/robots.txt")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_robots_content_type(self, client):
        """Robots.txt returns plain text."""
        response = client.get("/robots.txt")
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_robots_contains_user_agent(self, client):
        """Robots.txt contains User-agent directive."""
        response = client.get("/robots.txt")
        assert response.status_code == 200
        assert b"User-agent:" in response.content

    @pytest.mark.asyncio
    async def test_robots_contains_sitemap(self, client):
        """Robots.txt contains Sitemap directive."""
        response = client.get("/robots.txt")
        assert response.status_code == 200
        assert b"Sitemap:" in response.content


# ============================================================================
# GET /llms.txt - LLMs File Tests
# ============================================================================

class TestLlmsTxt:
    @pytest.mark.asyncio
    async def test_llms_public_access(self, client):
        """Llms.txt is publicly accessible."""
        response = client.get("/llms.txt")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_llms_content_type(self, client):
        """Llms.txt returns plain text."""
        response = client.get("/llms.txt")
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_llms_contains_rot_info(self, client):
        """Llms.txt contains ROT platform information."""
        response = client.get("/llms.txt")
        assert response.status_code == 200
        content = response.content.lower()
        assert b"rot" in content or b"reddit" in content or b"options" in content

    @pytest.mark.asyncio
    async def test_llms_contains_api_info(self, client):
        """Llms.txt contains API information."""
        response = client.get("/llms.txt")
        assert response.status_code == 200
        assert b"API" in response.content or b"api" in response.content


# ============================================================================
# GET /sitemap.xml - Sitemap Tests
# ============================================================================

class TestSitemapXml:
    @pytest.mark.asyncio
    async def test_sitemap_public_access(self, client):
        """Sitemap.xml is publicly accessible."""
        response = client.get("/sitemap.xml")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_sitemap_content_type(self, client):
        """Sitemap.xml returns application/xml."""
        response = client.get("/sitemap.xml")
        assert response.status_code == 200
        assert "application/xml" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_sitemap_contains_xml_declaration(self, client):
        """Sitemap.xml contains XML declaration."""
        response = client.get("/sitemap.xml")
        assert response.status_code == 200
        assert b"<?xml" in response.content

    @pytest.mark.asyncio
    async def test_sitemap_contains_urlset(self, client):
        """Sitemap.xml contains urlset element."""
        response = client.get("/sitemap.xml")
        assert response.status_code == 200
        assert b"<urlset" in response.content

    @pytest.mark.asyncio
    async def test_sitemap_contains_public_pages(self, client):
        """Sitemap.xml contains public pages."""
        response = client.get("/sitemap.xml")
        assert response.status_code == 200
        content = response.content
        # Should contain at least some public pages
        assert b"<loc>" in content and b"</loc>" in content


# ============================================================================
# GET /og-image.svg - Open Graph Image Tests
# ============================================================================

class TestOgImage:
    @pytest.mark.asyncio
    async def test_og_image_public_access(self, client):
        """OG image is publicly accessible."""
        response = client.get("/og-image.svg")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_og_image_content_type(self, client):
        """OG image returns SVG."""
        response = client.get("/og-image.svg")
        assert response.status_code == 200
        assert "image/svg+xml" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_og_image_cache_headers(self, client):
        """OG image has cache headers."""
        response = client.get("/og-image.svg")
        assert response.status_code == 200
        assert "cache-control" in response.headers

    @pytest.mark.asyncio
    async def test_og_image_contains_svg(self, client):
        """OG image contains SVG markup."""
        response = client.get("/og-image.svg")
        assert response.status_code == 200
        assert b"<svg" in response.content


# ============================================================================
# GET /favicon.svg - Favicon Tests
# ============================================================================

class TestFavicon:
    @pytest.mark.asyncio
    async def test_favicon_public_access(self, client):
        """Favicon is publicly accessible."""
        response = client.get("/favicon.svg")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_favicon_content_type(self, client):
        """Favicon returns SVG."""
        response = client.get("/favicon.svg")
        assert response.status_code == 200
        assert "image/svg+xml" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_favicon_cache_headers(self, client):
        """Favicon has cache headers."""
        response = client.get("/favicon.svg")
        assert response.status_code == 200
        assert "cache-control" in response.headers

    @pytest.mark.asyncio
    async def test_favicon_contains_svg(self, client):
        """Favicon contains SVG markup."""
        response = client.get("/favicon.svg")
        assert response.status_code == 200
        assert b"<svg" in response.content
