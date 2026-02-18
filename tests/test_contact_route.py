"""
Comprehensive tests for the Contact Us page.

Routes tested:
- GET /contact

Coverage:
- Public access (unauthenticated)
- HTML response format
- Content validation (investor section, support section, email)
- SEO meta tags and JSON-LD structured data
- Breadcrumb navigation
- Response headers
- Method restrictions
- Email address correctness
- Template context values
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-contact-page!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes
from rot.web.routes.contact import CONTACT_EMAIL, _base_context


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-contact-page!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-contact-page!!"},
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
# Module-level constants
# ============================================================================


class TestContactConstants:
    """Contact module constants validation."""

    def test_contact_email_is_correct(self):
        """CONTACT_EMAIL must be mattbusel@gmail.com."""
        assert CONTACT_EMAIL == "mattbusel@gmail.com"

    def test_contact_email_is_string(self):
        """CONTACT_EMAIL is a plain string."""
        assert isinstance(CONTACT_EMAIL, str)

    def test_contact_email_has_at_sign(self):
        """CONTACT_EMAIL contains @ sign."""
        assert "@" in CONTACT_EMAIL

    def test_contact_email_has_domain(self):
        """CONTACT_EMAIL has a recognizable domain."""
        assert "gmail.com" in CONTACT_EMAIL


# ============================================================================
# GET /contact — Access & HTTP basics
# ============================================================================


class TestContactAccess:
    """Public access and HTTP method tests."""

    @pytest.mark.asyncio
    async def test_public_access_returns_200(self, client):
        """Unauthenticated users can access the contact page."""
        response = client.get("/contact")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_html_content_type(self, client):
        """Contact page returns HTML content type."""
        response = client.get("/contact")
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """Page does not require authentication."""
        response = client.get("/contact")
        assert response.status_code not in (401, 403)

    @pytest.mark.asyncio
    async def test_post_not_allowed(self, client):
        """POST method is rejected (405 or 403 via CSRF)."""
        response = client.post("/contact")
        assert response.status_code in (403, 405)

    @pytest.mark.asyncio
    async def test_delete_not_allowed(self, client):
        """DELETE method is not supported."""
        response = client.delete("/contact")
        assert response.status_code in (403, 405)

    @pytest.mark.asyncio
    async def test_response_is_not_empty(self, client):
        """Response body is not empty."""
        response = client.get("/contact")
        assert len(response.text) > 100


# ============================================================================
# GET /contact — Email address presence
# ============================================================================


class TestContactEmail:
    """Email address content validation."""

    @pytest.mark.asyncio
    async def test_contains_contact_email(self, client):
        """Page body contains the contact email address."""
        response = client.get("/contact")
        assert "mattbusel@gmail.com" in response.text

    @pytest.mark.asyncio
    async def test_email_appears_in_mailto_link(self, client):
        """Email is rendered as a mailto: href."""
        response = client.get("/contact")
        assert "mailto:mattbusel@gmail.com" in response.text

    @pytest.mark.asyncio
    async def test_email_appears_multiple_times(self, client):
        """Email appears more than once (cards + callout)."""
        response = client.get("/contact")
        assert response.text.count("mattbusel@gmail.com") >= 2

    @pytest.mark.asyncio
    async def test_investor_mailto_has_subject(self, client):
        """Investor mailto link includes a pre-filled subject."""
        response = client.get("/contact")
        assert "Investor" in response.text
        assert "subject=" in response.text


# ============================================================================
# GET /contact — Investor section
# ============================================================================


class TestContactInvestorSection:
    """Investor section content validation."""

    @pytest.mark.asyncio
    async def test_contains_investors_heading(self, client):
        """Page has a heading for investor inquiries."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "investor" in content

    @pytest.mark.asyncio
    async def test_contains_investor_cta(self, client):
        """Page has a call-to-action for investors."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "investor" in content and "email" in content

    @pytest.mark.asyncio
    async def test_mentions_partnerships(self, client):
        """Investor section mentions partnerships."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "partner" in content

    @pytest.mark.asyncio
    async def test_mentions_capital(self, client):
        """Investor section mentions capital."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "capital" in content

    @pytest.mark.asyncio
    async def test_mentions_enterprise(self, client):
        """Investor section mentions enterprise integrations."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "enterprise" in content


# ============================================================================
# GET /contact — Support / Issues section
# ============================================================================


class TestContactSupportSection:
    """Support / issues section content validation."""

    @pytest.mark.asyncio
    async def test_contains_issue_heading(self, client):
        """Page has a heading for issue/support."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "issue" in content or "support" in content

    @pytest.mark.asyncio
    async def test_mentions_bug(self, client):
        """Support section mentions bugs."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "bug" in content

    @pytest.mark.asyncio
    async def test_mentions_billing(self, client):
        """Support section mentions billing."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "billing" in content

    @pytest.mark.asyncio
    async def test_mentions_account(self, client):
        """Support section mentions account."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "account" in content

    @pytest.mark.asyncio
    async def test_support_mailto_has_subject(self, client):
        """Support mailto link includes a support subject."""
        response = client.get("/contact")
        assert "Support" in response.text


# ============================================================================
# GET /contact — Page header & title
# ============================================================================


class TestContactPageHeader:
    """Page title, header, and meta content."""

    @pytest.mark.asyncio
    async def test_html_title_contains_contact(self, client):
        """HTML <title> contains 'Contact'."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "<title>" in content
        assert "contact" in content

    @pytest.mark.asyncio
    async def test_h1_contains_contact(self, client):
        """Page has an h1 tag with 'Contact'."""
        response = client.get("/contact")
        assert "Contact" in response.text

    @pytest.mark.asyncio
    async def test_meta_description_present(self, client):
        """Meta description is present in the page."""
        response = client.get("/contact")
        assert 'name="description"' in response.text

    @pytest.mark.asyncio
    async def test_og_title_present(self, client):
        """Open Graph title is present."""
        response = client.get("/contact")
        assert 'og:title' in response.text

    @pytest.mark.asyncio
    async def test_subheading_mentions_investors(self, client):
        """Subheading or description references investors."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "investor" in content


# ============================================================================
# GET /contact — Breadcrumb navigation
# ============================================================================


class TestContactBreadcrumb:
    """Breadcrumb navigation structure."""

    @pytest.mark.asyncio
    async def test_breadcrumb_home_link(self, client):
        """Breadcrumb includes a link to Home (/)."""
        response = client.get("/contact")
        assert 'href="/"' in response.text

    @pytest.mark.asyncio
    async def test_breadcrumb_contact_text(self, client):
        """Breadcrumb shows 'Contact' as current page."""
        response = client.get("/contact")
        assert "Contact" in response.text

    @pytest.mark.asyncio
    async def test_breadcrumb_schema_markup(self, client):
        """Breadcrumb has schema.org BreadcrumbList markup."""
        response = client.get("/contact")
        assert "BreadcrumbList" in response.text


# ============================================================================
# GET /contact — JSON-LD structured data
# ============================================================================


class TestContactStructuredData:
    """JSON-LD structured data for SEO."""

    @pytest.mark.asyncio
    async def test_contains_jsonld_script(self, client):
        """Page contains a JSON-LD script tag."""
        response = client.get("/contact")
        assert 'application/ld+json' in response.text

    @pytest.mark.asyncio
    async def test_jsonld_type_is_contact_page(self, client):
        """JSON-LD type is ContactPage."""
        response = client.get("/contact")
        assert "ContactPage" in response.text

    @pytest.mark.asyncio
    async def test_jsonld_schema_context(self, client):
        """JSON-LD includes schema.org context."""
        response = client.get("/contact")
        assert "schema.org" in response.text

    @pytest.mark.asyncio
    async def test_jsonld_has_name(self, client):
        """JSON-LD schema includes a name field."""
        response = client.get("/contact")
        assert "Contact ROT" in response.text


# ============================================================================
# GET /contact — Navigation & links
# ============================================================================


class TestContactNavigation:
    """Internal navigation links on the page."""

    @pytest.mark.asyncio
    async def test_contains_faq_link(self, client):
        """Page links back to the FAQ page."""
        response = client.get("/contact")
        assert 'href="/faq"' in response.text

    @pytest.mark.asyncio
    async def test_contains_dashboard_link(self, client):
        """Page links to the live dashboard."""
        response = client.get("/contact")
        assert 'href="/dashboard"' in response.text

    @pytest.mark.asyncio
    async def test_unauthenticated_shows_signup_cta(self, client):
        """Unauthenticated visitors see a Sign Up CTA."""
        response = client.get("/contact")
        content = response.text.lower()
        assert "sign up" in content or "register" in content


# ============================================================================
# _base_context helper (unit test, no HTTP)
# ============================================================================


class TestBaseContextHelper:
    """Unit tests for the _base_context helper function."""

    def test_free_tier_defaults(self):
        """No user → defaults to free tier."""

        class FakeRequest:
            app = type("App", (), {"state": type("State", (), {"settings": type("S", (), {"stripe": type("St", (), {"secret_key": ""})()})()})()})()

        ctx = _base_context(FakeRequest(), None)
        assert ctx["tier"] == "free"
        assert ctx["user"] is None
        assert "bg-gray-700" in ctx["tier_badge_class"]

    def test_pro_tier_badge(self):
        """Pro user gets blue badge class."""

        class FakeRequest:
            app = type("App", (), {"state": type("State", (), {"settings": type("S", (), {"stripe": type("St", (), {"secret_key": ""})()})()})()})()

        ctx = _base_context(FakeRequest(), {"tier": "pro"})
        assert ctx["tier"] == "pro"
        assert "blue" in ctx["tier_badge_class"]

    def test_premium_tier_badge(self):
        """Premium user gets purple badge class."""

        class FakeRequest:
            app = type("App", (), {"state": type("State", (), {"settings": type("S", (), {"stripe": type("St", (), {"secret_key": ""})()})()})()})()

        ctx = _base_context(FakeRequest(), {"tier": "premium"})
        assert "purple" in ctx["tier_badge_class"]

    def test_stripe_enabled_false_when_no_key(self):
        """stripe_enabled is False when no Stripe key configured."""

        class FakeRequest:
            app = type("App", (), {"state": type("State", (), {"settings": type("S", (), {"stripe": type("St", (), {"secret_key": ""})()})()})()})()

        ctx = _base_context(FakeRequest(), None)
        assert ctx["stripe_enabled"] is False

    def test_stripe_enabled_true_when_key_present(self):
        """stripe_enabled is True when Stripe key is configured."""

        class FakeRequest:
            app = type("App", (), {"state": type("State", (), {"settings": type("S", (), {"stripe": type("St", (), {"secret_key": "sk_test_abc"})()})()})()})()

        ctx = _base_context(FakeRequest(), None)
        assert ctx["stripe_enabled"] is True

    def test_context_contains_required_keys(self):
        """Context dict has all required template keys."""

        class FakeRequest:
            app = type("App", (), {"state": type("State", (), {"settings": type("S", (), {"stripe": type("St", (), {"secret_key": ""})()})()})()})()

        ctx = _base_context(FakeRequest(), None)
        for key in ("request", "user", "tier", "tier_badge_class", "stripe_enabled"):
            assert key in ctx
