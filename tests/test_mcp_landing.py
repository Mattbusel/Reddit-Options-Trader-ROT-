"""
Comprehensive tests for the MCP Server landing page.

Routes tested:
- GET /mcp-server

Coverage:
- Public access (unauthenticated)
- HTML response format
- Content validation (hero, tools, prompts, code blocks)
- SEO meta tags and structured data
- Template context (example_prompts list)
- Response headers
- Breadcrumb navigation
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-mcp-landing!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-mcp-landing!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-mcp-landing!!"},
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
# GET /mcp-server — Public Access
# ============================================================================


class TestMcpLandingAccess:
    """Public access and basic response tests."""

    @pytest.mark.asyncio
    async def test_public_access(self, client):
        """Unauthenticated users can access the MCP page."""
        response = client.get("/mcp-server")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_html(self, client):
        """MCP page returns HTML content type."""
        response = client.get("/mcp-server")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """Page does not require authentication."""
        response = client.get("/mcp-server")
        assert response.status_code != 401
        assert response.status_code != 403

    @pytest.mark.asyncio
    async def test_post_not_allowed(self, client):
        """POST method is rejected (405 or 403 via CSRF)."""
        response = client.post("/mcp-server")
        assert response.status_code in (403, 405)


# ============================================================================
# GET /mcp-server — Hero Section Content
# ============================================================================


class TestMcpLandingHero:
    """Hero section content validation."""

    @pytest.mark.asyncio
    async def test_contains_first_financial(self, client):
        """Hero mentions 'first financial intelligence MCP server'."""
        response = client.get("/mcp-server")
        content = response.text.lower()
        assert "first" in content
        assert "financial" in content
        assert "mcp" in content

    @pytest.mark.asyncio
    async def test_contains_zero_install(self, client):
        """Hero mentions zero install."""
        response = client.get("/mcp-server")
        content = response.text.lower()
        assert "zero install" in content or "no install" in content or "no packages" in content

    @pytest.mark.asyncio
    async def test_contains_no_api_key(self, client):
        """Hero mentions no API key needed."""
        response = client.get("/mcp-server")
        content = response.text.lower()
        assert "no api key" in content

    @pytest.mark.asyncio
    async def test_contains_free(self, client):
        """Hero mentions free access."""
        response = client.get("/mcp-server")
        content = response.text.lower()
        assert "free" in content


# ============================================================================
# GET /mcp-server — Connection Instructions
# ============================================================================


class TestMcpLandingConnection:
    """Connection instructions and code blocks."""

    @pytest.mark.asyncio
    async def test_contains_mcp_url(self, client):
        """Page includes the MCP server URL."""
        response = client.get("/mcp-server")
        assert "web-production-71423.up.railway.app/mcp" in response.text

    @pytest.mark.asyncio
    async def test_contains_claude_desktop_config(self, client):
        """Page includes Claude Desktop JSON config."""
        response = client.get("/mcp-server")
        assert "mcpServers" in response.text
        assert "claude_desktop_config" in response.text

    @pytest.mark.asyncio
    async def test_contains_cursor_mention(self, client):
        """Page mentions Cursor as a compatible client."""
        response = client.get("/mcp-server")
        assert "Cursor" in response.text

    @pytest.mark.asyncio
    async def test_contains_windsurf_mention(self, client):
        """Page mentions Windsurf as a compatible client."""
        response = client.get("/mcp-server")
        assert "Windsurf" in response.text

    @pytest.mark.asyncio
    async def test_contains_copy_button(self, client):
        """Page includes copy-to-clipboard functionality."""
        response = client.get("/mcp-server")
        assert "copyCode" in response.text

    @pytest.mark.asyncio
    async def test_contains_30_seconds(self, client):
        """Page mentions 30-second setup."""
        response = client.get("/mcp-server")
        assert "30 Second" in response.text or "30 second" in response.text


# ============================================================================
# GET /mcp-server — Tool Documentation
# ============================================================================


class TestMcpLandingTools:
    """Tool cards and documentation."""

    @pytest.mark.asyncio
    async def test_contains_get_trending_tickers(self, client):
        """Page documents get_trending_tickers tool."""
        response = client.get("/mcp-server")
        assert "get_trending_tickers" in response.text

    @pytest.mark.asyncio
    async def test_contains_get_signals(self, client):
        """Page documents get_signals tool."""
        response = client.get("/mcp-server")
        assert "get_signals" in response.text

    @pytest.mark.asyncio
    async def test_contains_get_sentiment(self, client):
        """Page documents get_sentiment tool."""
        response = client.get("/mcp-server")
        assert "get_sentiment" in response.text

    @pytest.mark.asyncio
    async def test_contains_get_market_overview(self, client):
        """Page documents get_market_overview tool."""
        response = client.get("/mcp-server")
        assert "get_market_overview" in response.text

    @pytest.mark.asyncio
    async def test_contains_get_unusual_activity(self, client):
        """Page documents get_unusual_activity tool."""
        response = client.get("/mcp-server")
        assert "get_unusual_activity" in response.text

    @pytest.mark.asyncio
    async def test_contains_get_sports_feed(self, client):
        """Page documents get_sports_feed tool."""
        response = client.get("/mcp-server")
        assert "get_sports_feed" in response.text

    @pytest.mark.asyncio
    async def test_contains_search_signals(self, client):
        """Page documents search_signals tool."""
        response = client.get("/mcp-server")
        assert "search_signals" in response.text

    @pytest.mark.asyncio
    async def test_all_seven_tools_present(self, client):
        """All 7 MCP tools are documented on the page."""
        response = client.get("/mcp-server")
        tools = [
            "get_trending_tickers",
            "get_signals",
            "get_sentiment",
            "get_market_overview",
            "get_unusual_activity",
            "get_sports_feed",
            "search_signals",
        ]
        for tool in tools:
            assert tool in response.text, f"Tool {tool} not found on page"


# ============================================================================
# GET /mcp-server — Example Prompts
# ============================================================================


class TestMcpLandingPrompts:
    """Example prompt pills."""

    @pytest.mark.asyncio
    async def test_contains_trending_prompt(self, client):
        """Page includes a trending stocks prompt."""
        response = client.get("/mcp-server")
        assert "trending" in response.text.lower()

    @pytest.mark.asyncio
    async def test_contains_sentiment_prompt(self, client):
        """Page includes a sentiment prompt."""
        response = client.get("/mcp-server")
        assert "sentiment" in response.text.lower()

    @pytest.mark.asyncio
    async def test_contains_bearish_prompt(self, client):
        """Page includes a bearish signals prompt."""
        response = client.get("/mcp-server")
        assert "bearish" in response.text.lower()

    @pytest.mark.asyncio
    async def test_contains_fda_prompt(self, client):
        """Page includes an FDA approval prompt."""
        response = client.get("/mcp-server")
        assert "FDA" in response.text

    @pytest.mark.asyncio
    async def test_contains_nfl_prompt(self, client):
        """Page includes a sports/NFL prompt."""
        response = client.get("/mcp-server")
        assert "NFL" in response.text

    @pytest.mark.asyncio
    async def test_prompt_count(self, client):
        """Page renders multiple example prompts."""
        response = client.get("/mcp-server")
        # Each prompt is wrapped in a prompt-pill div
        assert response.text.count("prompt-pill") >= 8


# ============================================================================
# GET /mcp-server — Resources Section
# ============================================================================


class TestMcpLandingResources:
    """MCP resource documentation."""

    @pytest.mark.asyncio
    async def test_contains_status_resource(self, client):
        """Page documents rot://status resource."""
        response = client.get("/mcp-server")
        assert "rot://status" in response.text

    @pytest.mark.asyncio
    async def test_contains_pricing_resource(self, client):
        """Page documents rot://pricing resource."""
        response = client.get("/mcp-server")
        assert "rot://pricing" in response.text


# ============================================================================
# GET /mcp-server — SEO and Metadata
# ============================================================================


class TestMcpLandingSEO:
    """SEO meta tags and structured data."""

    @pytest.mark.asyncio
    async def test_title_tag(self, client):
        """Page has an appropriate title tag."""
        response = client.get("/mcp-server")
        assert "MCP Server" in response.text
        assert "<title>" in response.text

    @pytest.mark.asyncio
    async def test_meta_description(self, client):
        """Page has a meta description."""
        response = client.get("/mcp-server")
        assert 'name="description"' in response.text

    @pytest.mark.asyncio
    async def test_og_title(self, client):
        """Page has Open Graph title."""
        response = client.get("/mcp-server")
        assert 'property="og:title"' in response.text

    @pytest.mark.asyncio
    async def test_twitter_card(self, client):
        """Page has Twitter card meta tags."""
        response = client.get("/mcp-server")
        assert 'name="twitter:title"' in response.text

    @pytest.mark.asyncio
    async def test_structured_data(self, client):
        """Page has JSON-LD structured data."""
        response = client.get("/mcp-server")
        assert "application/ld+json" in response.text
        assert "SoftwareApplication" in response.text

    @pytest.mark.asyncio
    async def test_breadcrumbs(self, client):
        """Page has breadcrumb navigation."""
        response = client.get("/mcp-server")
        assert "BreadcrumbList" in response.text
        assert "MCP Server" in response.text


# ============================================================================
# GET /mcp-server — Why This Matters Section
# ============================================================================


class TestMcpLandingValueProp:
    """Value proposition section."""

    @pytest.mark.asyncio
    async def test_institutional_grade_mention(self, client):
        """Page mentions institutional-grade data."""
        response = client.get("/mcp-server")
        content = response.text.lower()
        assert "institutional" in content

    @pytest.mark.asyncio
    async def test_real_time_pipeline_mention(self, client):
        """Page mentions real-time pipeline."""
        response = client.get("/mcp-server")
        content = response.text.lower()
        assert "real-time" in content or "real time" in content

    @pytest.mark.asyncio
    async def test_contains_dashboard_link(self, client):
        """Page links to the live dashboard."""
        response = client.get("/mcp-server")
        assert "/dashboard" in response.text

    @pytest.mark.asyncio
    async def test_contains_github_link(self, client):
        """Page links to GitHub."""
        response = client.get("/mcp-server")
        assert "github.com/Mattbusel/Reddit-Options-Trader-ROT-" in response.text


# ============================================================================
# GET /mcp-server — Compatible Clients
# ============================================================================


class TestMcpLandingClients:
    """Compatible AI clients section."""

    @pytest.mark.asyncio
    async def test_claude_desktop(self, client):
        """Page lists Claude Desktop as compatible."""
        response = client.get("/mcp-server")
        assert "Claude Desktop" in response.text

    @pytest.mark.asyncio
    async def test_cursor_client(self, client):
        """Page lists Cursor as compatible."""
        response = client.get("/mcp-server")
        assert "Cursor" in response.text

    @pytest.mark.asyncio
    async def test_windsurf_client(self, client):
        """Page lists Windsurf as compatible."""
        response = client.get("/mcp-server")
        assert "Windsurf" in response.text

    @pytest.mark.asyncio
    async def test_any_mcp_client(self, client):
        """Page mentions any MCP client."""
        response = client.get("/mcp-server")
        assert "Any MCP Client" in response.text


# ============================================================================
# Route Module Unit Tests
# ============================================================================


class TestMcpLandingModule:
    """Unit tests for the mcp_landing route module."""

    def test_example_prompts_not_empty(self):
        """EXAMPLE_PROMPTS list is populated."""
        from rot.web.routes.mcp_landing import EXAMPLE_PROMPTS
        assert len(EXAMPLE_PROMPTS) >= 7

    def test_example_prompts_are_strings(self):
        """All example prompts are strings."""
        from rot.web.routes.mcp_landing import EXAMPLE_PROMPTS
        for prompt in EXAMPLE_PROMPTS:
            assert isinstance(prompt, str)
            assert len(prompt) > 10

    def test_example_prompts_are_questions(self):
        """Most example prompts end with question mark or are directives."""
        from rot.web.routes.mcp_landing import EXAMPLE_PROMPTS
        question_count = sum(1 for p in EXAMPLE_PROMPTS if p.endswith("?"))
        assert question_count >= 3

    def test_base_context_no_user(self):
        """_base_context with no user returns free tier."""
        from unittest.mock import MagicMock
        from rot.web.routes.mcp_landing import _base_context
        mock_request = MagicMock()
        mock_request.app.state.settings.stripe.secret_key = ""
        ctx = _base_context(mock_request, None)
        assert ctx["tier"] == "free"
        assert ctx["user"] is None
        assert "bg-gray-700" in ctx["tier_badge_class"]

    def test_base_context_pro_user(self):
        """_base_context with pro user returns pro tier badge."""
        from unittest.mock import MagicMock
        from rot.web.routes.mcp_landing import _base_context
        mock_request = MagicMock()
        mock_request.app.state.settings.stripe.secret_key = ""
        user = {"id": 1, "email": "test@test.com", "tier": "pro"}
        ctx = _base_context(mock_request, user)
        assert ctx["tier"] == "pro"
        assert "bg-blue-700" in ctx["tier_badge_class"]

    def test_base_context_admin_user(self):
        """_base_context with admin user returns admin tier badge."""
        from unittest.mock import MagicMock
        from rot.web.routes.mcp_landing import _base_context
        mock_request = MagicMock()
        mock_request.app.state.settings.stripe.secret_key = ""
        user = {"id": 1, "email": "admin@test.com", "tier": "admin"}
        ctx = _base_context(mock_request, user)
        assert ctx["tier"] == "admin"
        assert "bg-red-700" in ctx["tier_badge_class"]

    def test_base_context_includes_request(self):
        """_base_context includes request object."""
        from unittest.mock import MagicMock
        from rot.web.routes.mcp_landing import _base_context
        mock_request = MagicMock()
        mock_request.app.state.settings.stripe.secret_key = "sk_test_123"
        ctx = _base_context(mock_request, None)
        assert ctx["request"] is mock_request
        assert ctx["stripe_enabled"] is True

    def test_base_context_stripe_disabled(self):
        """_base_context with no stripe key reports disabled."""
        from unittest.mock import MagicMock
        from rot.web.routes.mcp_landing import _base_context
        mock_request = MagicMock()
        mock_request.app.state.settings.stripe.secret_key = ""
        ctx = _base_context(mock_request, None)
        assert ctx["stripe_enabled"] is False

    def test_base_context_unknown_tier_falls_back(self):
        """_base_context with unknown tier falls back to free badge."""
        from unittest.mock import MagicMock
        from rot.web.routes.mcp_landing import _base_context
        mock_request = MagicMock()
        mock_request.app.state.settings.stripe.secret_key = ""
        user = {"tier": "nonexistent_tier"}
        ctx = _base_context(mock_request, user)
        assert ctx["tier"] == "nonexistent_tier"
        assert "bg-gray-700" in ctx["tier_badge_class"]

    def test_router_has_mcp_server_route(self):
        """Router has the /mcp-server GET route registered."""
        from rot.web.routes.mcp_landing import router
        paths = [route.path for route in router.routes]
        assert "/mcp-server" in paths
