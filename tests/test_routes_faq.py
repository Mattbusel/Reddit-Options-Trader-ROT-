"""
Comprehensive tests for FAQ route (public access).

Routes tested:
- GET /faq

Coverage:
- Public access (unauthenticated & all tiers)
- HTML response format
- Content validation
- SEO schema validation
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-faq-tests!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-faq-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-faq-tests!!"},
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
# GET /faq - FAQ Page Tests
# ============================================================================

class TestFAQPage:
    @pytest.mark.asyncio
    async def test_faq_page_public_access(self, client):
        """Unauthenticated users can access FAQ."""
        response = client.get("/faq")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_faq_page_html_content(self, client):
        """FAQ page returns HTML."""
        response = client.get("/faq")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_faq_page_contains_win_rate_info(self, client):
        """FAQ contains win rate information."""
        response = client.get("/faq")
        assert response.status_code == 200
        assert b"win rate" in response.content.lower() or b"Win Rate" in response.content

    @pytest.mark.asyncio
    async def test_faq_page_contains_stance_info(self, client):
        """FAQ contains stance information."""
        response = client.get("/faq")
        assert response.status_code == 200
        content = response.content.lower()
        assert b"bullish" in content or b"bearish" in content

    @pytest.mark.asyncio
    async def test_faq_page_contains_threshold_info(self, client):
        """FAQ contains 0.5% threshold information."""
        response = client.get("/faq")
        assert response.status_code == 200
        assert b"0.5%" in response.content or b"0.5" in response.content

    @pytest.mark.asyncio
    async def test_faq_page_contains_schema_org(self, client):
        """FAQ page includes JSON-LD schema."""
        response = client.get("/faq")
        assert response.status_code == 200
        content = response.content.decode()
        assert "schema.org" in content
        assert "FAQPage" in content

    @pytest.mark.asyncio
    async def test_faq_page_multiple_questions(self, client):
        """FAQ page contains multiple question-answer pairs."""
        response = client.get("/faq")
        assert response.status_code == 200
        content = response.content.lower()
        # Check for at least a few FAQ topics
        topics = [b"signal", b"price", b"confidence", b"credibility"]
        matches = sum(1 for topic in topics if topic in content)
        assert matches >= 3

    @pytest.mark.asyncio
    async def test_faq_page_contains_disclaimer(self, client):
        """FAQ contains financial disclaimer."""
        response = client.get("/faq")
        assert response.status_code == 200
        content = response.content.lower()
        # Should mention advice/disclaimer somewhere
        assert b"advice" in content or b"disclaimer" in content or b"financial" in content
