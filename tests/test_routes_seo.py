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
- Sitemap priority and changefreq attributes
- robots.txt disallow directives
- Auth page noindex directives (template-level)
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

    @pytest.mark.asyncio
    async def test_robots_blocks_api(self, client):
        """Robots.txt blocks /api/ from crawling."""
        response = client.get("/robots.txt")
        assert b"Disallow: /api/" in response.content

    @pytest.mark.asyncio
    async def test_robots_blocks_auth_pages(self, client):
        """Robots.txt blocks all auth/account pages."""
        response = client.get("/robots.txt")
        text = response.text
        for path in ["/account", "/login", "/register", "/logout",
                     "/forgot-password", "/reset-password"]:
            assert f"Disallow: {path}" in text

    @pytest.mark.asyncio
    async def test_robots_blocks_internal_pages(self, client):
        """Robots.txt blocks internal/private paths."""
        response = client.get("/robots.txt")
        text = response.text
        for path in ["/checkout", "/portal", "/webhook", "/errors/", "/static/"]:
            assert f"Disallow: {path}" in text

    @pytest.mark.asyncio
    async def test_robots_allows_root(self, client):
        """Robots.txt allows root crawling."""
        response = client.get("/robots.txt")
        assert b"Allow: /" in response.content

    @pytest.mark.asyncio
    async def test_robots_sitemap_uses_base_url(self, client):
        """Robots.txt Sitemap URL uses the request base URL."""
        response = client.get("/robots.txt")
        assert b"Sitemap: http://testserver/sitemap.xml" in response.content


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

    @pytest.mark.asyncio
    async def test_llms_contains_key_pages(self, client):
        """Llms.txt lists key public pages."""
        response = client.get("/llms.txt")
        text = response.text
        for page in ["/glossary", "/hall-of-legends", "/pricing",
                     "/dashboard", "/news", "/sports-tracker"]:
            assert page in text

    @pytest.mark.asyncio
    async def test_llms_contains_data_section(self, client):
        """Llms.txt describes the data model."""
        response = client.get("/llms.txt")
        assert b"## Data" in response.content

    @pytest.mark.asyncio
    async def test_llms_contains_sports_section(self, client):
        """Llms.txt describes sports betting features."""
        response = client.get("/llms.txt")
        assert b"Sports Betting" in response.content


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

    @pytest.mark.asyncio
    async def test_sitemap_contains_priority_tags(self, client):
        """Sitemap.xml includes priority for each URL."""
        response = client.get("/sitemap.xml")
        text = response.text
        assert "<priority>" in text

    @pytest.mark.asyncio
    async def test_sitemap_homepage_has_highest_priority(self, client):
        """Homepage has priority 1.0 in sitemap."""
        response = client.get("/sitemap.xml")
        text = response.text
        # Homepage entry should contain priority 1.0
        home_idx = text.index("http://testserver/</loc>")
        priority_after = text[home_idx:home_idx + 200]
        assert "<priority>1.0</priority>" in priority_after

    @pytest.mark.asyncio
    async def test_sitemap_contains_changefreq(self, client):
        """Sitemap.xml includes changefreq for each URL."""
        response = client.get("/sitemap.xml")
        text = response.text
        assert "<changefreq>" in text

    @pytest.mark.asyncio
    async def test_sitemap_includes_all_expected_pages(self, client):
        """Sitemap includes all major public pages."""
        response = client.get("/sitemap.xml")
        text = response.text
        expected_paths = [
            "/", "/dashboard", "/pricing", "/glossary",
            "/hall-of-legends", "/wall-of-shame", "/ceo-rap-sheet",
            "/faq", "/news", "/sentiment", "/sports-tracker",
            "/weekly-wrap", "/leaderboard", "/congress-tracker",
            "/unusual-activity", "/correlations", "/brokers",
            "/badges", "/widgets", "/tradingview",
        ]
        for path in expected_paths:
            assert f"http://testserver{path}</loc>" in text, (
                f"Missing from sitemap: {path}"
            )

    @pytest.mark.asyncio
    async def test_sitemap_excludes_auth_pages(self, client):
        """Sitemap does NOT include auth/private pages."""
        response = client.get("/sitemap.xml")
        text = response.text
        for path in ["/login", "/register", "/account", "/logout",
                     "/forgot-password", "/reset-password", "/api/"]:
            assert path + "</loc>" not in text, (
                f"Auth page should not be in sitemap: {path}"
            )

    @pytest.mark.asyncio
    async def test_sitemap_url_count(self, client):
        """Sitemap has at least 20 URLs."""
        response = client.get("/sitemap.xml")
        text = response.text
        url_count = text.count("<url>")
        assert url_count >= 20, f"Only {url_count} URLs in sitemap, expected >= 20"


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

    @pytest.mark.asyncio
    async def test_og_image_dimensions(self, client):
        """OG image has correct 1200x630 dimensions."""
        response = client.get("/og-image.svg")
        text = response.text
        assert 'width="1200"' in text
        assert 'height="630"' in text

    @pytest.mark.asyncio
    async def test_og_image_contains_branding(self, client):
        """OG image contains ROT branding text."""
        response = client.get("/og-image.svg")
        text = response.text
        assert "ROT" in text
        assert "Reddit Options Trader" in text


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

    @pytest.mark.asyncio
    async def test_favicon_long_cache(self, client):
        """Favicon has long cache TTL (1 week)."""
        response = client.get("/favicon.svg")
        cache = response.headers.get("cache-control", "")
        assert "604800" in cache


# ============================================================================
# Unit Tests for _PUBLIC_PAGES data structure
# ============================================================================

class TestPublicPagesConfig:
    def test_public_pages_are_tuples(self):
        """Each entry in _PUBLIC_PAGES is a 3-tuple."""
        from rot.web.routes.seo import _PUBLIC_PAGES
        for entry in _PUBLIC_PAGES:
            assert len(entry) == 3, f"Expected 3-tuple, got {entry}"

    def test_public_pages_paths_start_with_slash(self):
        """All paths start with /."""
        from rot.web.routes.seo import _PUBLIC_PAGES
        for path, _, _ in _PUBLIC_PAGES:
            assert path.startswith("/"), f"Path missing leading slash: {path}"

    def test_public_pages_valid_changefreq(self):
        """All changefreq values are valid sitemap values."""
        from rot.web.routes.seo import _PUBLIC_PAGES
        valid = {"always", "hourly", "daily", "weekly", "monthly", "yearly", "never"}
        for path, changefreq, _ in _PUBLIC_PAGES:
            assert changefreq in valid, (
                f"Invalid changefreq '{changefreq}' for {path}"
            )

    def test_public_pages_valid_priority(self):
        """All priority values are between 0.0 and 1.0."""
        from rot.web.routes.seo import _PUBLIC_PAGES
        for path, _, priority in _PUBLIC_PAGES:
            val = float(priority)
            assert 0.0 <= val <= 1.0, (
                f"Invalid priority '{priority}' for {path}"
            )

    def test_public_pages_no_auth_paths(self):
        """No auth/private paths in the public pages list."""
        from rot.web.routes.seo import _PUBLIC_PAGES
        blocked = {"/login", "/register", "/account", "/logout",
                   "/forgot-password", "/reset-password", "/api",
                   "/checkout", "/portal", "/webhook"}
        paths = {path for path, _, _ in _PUBLIC_PAGES}
        overlap = paths & blocked
        assert not overlap, f"Auth/private paths in sitemap: {overlap}"

    def test_public_pages_no_duplicates(self):
        """No duplicate paths in the public pages list."""
        from rot.web.routes.seo import _PUBLIC_PAGES
        paths = [path for path, _, _ in _PUBLIC_PAGES]
        assert len(paths) == len(set(paths)), "Duplicate paths found"

    def test_homepage_has_priority_one(self):
        """Homepage (/) has priority 1.0."""
        from rot.web.routes.seo import _PUBLIC_PAGES
        for path, _, priority in _PUBLIC_PAGES:
            if path == "/":
                assert priority == "1.0"
                return
        pytest.fail("Homepage (/) not found in _PUBLIC_PAGES")

    def test_minimum_page_count(self):
        """At least 20 pages in sitemap."""
        from rot.web.routes.seo import _PUBLIC_PAGES
        assert len(_PUBLIC_PAGES) >= 20
