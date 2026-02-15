"""
Comprehensive tests for glossary route (public access).

Routes tested:
- GET /glossary

Coverage:
- Public access (unauthenticated & all tiers)
- HTML response format
- Content validation (WSB terms)
- Filtering (category, letter)
- SEO schema validation
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-glossary-tests!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-glossary-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-glossary-tests!!"},
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
# GET /glossary - Glossary Page Tests
# ============================================================================

class TestGlossaryPage:
    @pytest.mark.asyncio
    async def test_glossary_page_public_access(self, client):
        """Unauthenticated users can access glossary."""
        response = client.get("/glossary")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_glossary_page_html_content(self, client):
        """Glossary page returns HTML."""
        response = client.get("/glossary")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_glossary_contains_wsb_terms(self, client):
        """Glossary contains WSB trading terms."""
        response = client.get("/glossary")
        assert response.status_code == 200
        content = response.content.lower()
        # Check for some iconic WSB terms
        wsb_terms = [b"yolo", b"diamond hands", b"tendies", b"ape"]
        matches = sum(1 for term in wsb_terms if term in content)
        assert matches >= 3

    @pytest.mark.asyncio
    async def test_glossary_contains_options_terms(self, client):
        """Glossary contains options trading terms."""
        response = client.get("/glossary")
        assert response.status_code == 200
        content = response.content.lower()
        # Check for options terms
        options_terms = [b"calls", b"puts", b"otm", b"itm"]
        matches = sum(1 for term in options_terms if term in content)
        assert matches >= 2

    @pytest.mark.asyncio
    async def test_glossary_contains_schema_org(self, client):
        """Glossary page includes JSON-LD schema."""
        response = client.get("/glossary")
        assert response.status_code == 200
        content = response.content.decode()
        assert "schema.org" in content
        assert "FAQPage" in content

    @pytest.mark.asyncio
    async def test_glossary_category_filter_strategy(self, client):
        """Glossary can filter by strategy category."""
        response = client.get("/glossary?category=strategy")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_glossary_category_filter_emotion(self, client):
        """Glossary can filter by emotion category."""
        response = client.get("/glossary?category=emotion")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_glossary_category_filter_culture(self, client):
        """Glossary can filter by culture category."""
        response = client.get("/glossary?category=culture")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_glossary_category_filter_instrument(self, client):
        """Glossary can filter by instrument category."""
        response = client.get("/glossary?category=instrument")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_glossary_category_filter_insult(self, client):
        """Glossary can filter by insult category."""
        response = client.get("/glossary?category=insult")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_glossary_letter_filter(self, client):
        """Glossary can filter by first letter."""
        response = client.get("/glossary?letter=Y")
        assert response.status_code == 200
        content = response.content.lower()
        # Should contain YOLO
        assert b"yolo" in content

    @pytest.mark.asyncio
    async def test_glossary_combined_filters(self, client):
        """Glossary can apply multiple filters."""
        response = client.get("/glossary?category=strategy&letter=Y")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_glossary_all_categories_link(self, client):
        """Glossary all filter works."""
        response = client.get("/glossary?category=all")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_glossary_contains_degen_ratings(self, client):
        """Glossary includes degen rating system."""
        response = client.get("/glossary")
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference degen ratings somehow
        assert b"degen" in content or b"rating" in content

    @pytest.mark.asyncio
    async def test_glossary_contains_definitions(self, client):
        """Glossary terms have definitions."""
        response = client.get("/glossary")
        assert response.status_code == 200
        content = response.content.lower()
        # Should have definition text
        assert b"definition" in content or b"mean" in content

    @pytest.mark.asyncio
    async def test_glossary_contains_examples(self, client):
        """Glossary terms have usage examples."""
        response = client.get("/glossary")
        assert response.status_code == 200
        content = response.content.lower()
        # Should have examples
        assert b"example" in content or b"usage" in content
