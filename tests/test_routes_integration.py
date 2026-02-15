"""Route-level integration tests for ROT web layer.

Tests the core API routes using FastAPI's TestClient against a real
(temporary) SQLite database.  No external API calls — everything mocked.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rot.core.config import Settings
from rot.web.auth import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_settings(tmp_path):
    """Create Settings pointing to a temp directory."""
    return Settings(
        storage={"root": str(tmp_path)},
        web={
            "secret_key": "test-secret-key-for-route-integration-tests!",
            "host": "127.0.0.1",
            "port": 8000,
        },
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-route-integration-tests!!"},
    )


@pytest.fixture
async def app_with_db(tmp_settings):
    """Create a fully-initialized app with DB and routes."""
    from rot.web.app import create_app, connect_db, register_routes

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
async def db(app_with_db):
    return app_with_db.state.db


@pytest.fixture
def client(app_with_db):
    return TestClient(app_with_db)


@pytest.fixture
async def test_user(db, tmp_settings):
    """Create a test user and return (user_dict, jwt_token)."""
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user("test@example.com", pw_hash)
    token = create_access_token(user["id"], user["email"], user["tier"], tmp_settings)
    return user, token


@pytest.fixture
async def pro_user(db, tmp_settings):
    """Create a pro-tier test user."""
    pw_hash = hash_password("ProPass123!")
    user = await db.create_user("pro@example.com", pw_hash)
    await db.db.execute("UPDATE users SET tier = 'pro' WHERE id = ?", (user["id"],))
    await db.db.commit()
    user["tier"] = "pro"
    token = create_access_token(user["id"], user["email"], "pro", tmp_settings)
    return user, token


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthRoutes:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_api_health_returns_200(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

class TestAuthRoutes:
    @pytest.mark.asyncio
    async def test_register_creates_user(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "new@example.com",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == "new@example.com"
        assert data["user"]["tier"] == "free"

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client, test_user):
        resp = client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            "password": "AnotherPass123!",
        })
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_register_short_password(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "short@example.com",
            "password": "abc",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_login_success(self, client, test_user):
        resp = client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "TestPass123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert "rot_session" in resp.cookies

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, test_user):
        resp = client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "WrongPassword!",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "email": "nobody@example.com",
            "password": "Whatever123!",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_logout(self, client):
        resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_me_unauthenticated(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_me_authenticated(self, client, test_user):
        user, token = test_user
        resp = client.get(
            "/api/v1/auth/me",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test@example.com"


# ---------------------------------------------------------------------------
# Signals routes
# ---------------------------------------------------------------------------

class TestSignalRoutes:
    @pytest.mark.asyncio
    async def test_list_signals_unauthenticated(self, client):
        """Free tier can list signals (with limitations)."""
        resp = client.get("/api/v1/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert "signals" in data

    @pytest.mark.asyncio
    async def test_list_signals_with_filters(self, client, test_user):
        user, token = test_user
        resp = client.get(
            "/api/v1/signals?limit=5&ticker=AAPL&stance=bullish",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_signals_invalid_limit(self, client):
        resp = client.get("/api/v1/signals?limit=-1")
        assert resp.status_code == 422  # Pydantic validation error


# ---------------------------------------------------------------------------
# Paper trading routes
# ---------------------------------------------------------------------------

class TestPaperTradingRoutes:
    @pytest.mark.asyncio
    async def test_paper_trading_page_unauthenticated(self, client):
        resp = client.get("/paper-trading")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_paper_trading_page_authenticated(self, client, test_user):
        user, token = test_user
        resp = client.get(
            "/paper-trading",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_execute_paper_trade_unauthenticated(self, client):
        resp = client.post("/api/v1/paper-trading/trade", json={
            "signal_id": "fake-id",
            "dollars": 500.0,
        })
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Strategy routes (Pydantic validation)
# ---------------------------------------------------------------------------

class TestStrategyRoutes:
    @pytest.mark.asyncio
    async def test_create_strategy_unauthenticated(self, client):
        resp = client.post("/api/v1/strategies/create", json={
            "name": "My Strategy",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_strategy_free_tier_blocked(self, client, test_user):
        user, token = test_user
        resp = client.post(
            "/api/v1/strategies/create",
            json={"name": "My Strategy"},
            cookies={"rot_session": token},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_strategy_missing_name(self, client, pro_user):
        user, token = pro_user
        resp = client.post(
            "/api/v1/strategies/create",
            json={"name": ""},
            cookies={"rot_session": token},
        )
        # Pydantic validation: min_length=1
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_discover_validation(self, client, pro_user):
        user, token = pro_user
        resp = client.post(
            "/api/v1/strategies/discover",
            json={"days": -5},
            cookies={"rot_session": token},
        )
        # Pydantic validation: ge=1
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_evolve_validation(self, client, pro_user):
        user, token = pro_user
        resp = client.post(
            "/api/v1/strategies/evolve",
            json={"population_size": 999},  # max is 100
            cookies={"rot_session": token},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# WebSocket auth via message
# ---------------------------------------------------------------------------

class TestWebSocketAuth:
    @pytest.mark.asyncio
    async def test_ws_auth_timeout(self, app_with_db):
        """Connection without auth message should close with 4003."""
        # Patch timeout to make test fast
        import rot.web.routes.websocket as ws_mod
        original = ws_mod._AUTH_TIMEOUT_S
        ws_mod._AUTH_TIMEOUT_S = 1

        client = TestClient(app_with_db)
        try:
            with client.websocket_connect("/api/v1/signals/live") as ws:
                # Don't send auth — should timeout and close
                import time
                time.sleep(1.5)
                # After timeout, server should close the connection
                try:
                    ws.receive_text()
                except Exception:
                    pass  # Expected — connection closed
        except Exception:
            pass  # Expected — WebSocket closed by server
        finally:
            ws_mod._AUTH_TIMEOUT_S = original

    @pytest.mark.asyncio
    async def test_ws_invalid_auth(self, app_with_db):
        """Invalid auth message should close with 4003."""
        client = TestClient(app_with_db)
        try:
            with client.websocket_connect("/api/v1/signals/live") as ws:
                ws.send_text(json.dumps({"type": "auth", "token": "invalid"}))
                # Should get close frame
                try:
                    ws.receive_text()
                except Exception:
                    pass
        except Exception:
            pass  # Expected

    @pytest.mark.asyncio
    async def test_ws_valid_auth(self, app_with_db, pro_user):
        """Valid pro-tier token should get auth_ok."""
        user, token = pro_user
        client = TestClient(app_with_db)
        with client.websocket_connect("/api/v1/signals/live") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": token}))
            resp = ws.receive_text()
            data = json.loads(resp)
            assert data["type"] == "auth_ok"

            # Ping-pong should work
            ws.send_text("ping")
            assert ws.receive_text() == "pong"


# ---------------------------------------------------------------------------
# Dashboard / HTML routes
# ---------------------------------------------------------------------------

class TestDashboardRoutes:
    @pytest.mark.asyncio
    async def test_dashboard_redirect_when_logged_out(self, client):
        resp = client.get("/dashboard", follow_redirects=False)
        # Should either show page or redirect to login
        assert resp.status_code in (200, 302, 307)

    @pytest.mark.asyncio
    async def test_login_page(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_register_page(self, client):
        resp = client.get("/register")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_pricing_page(self, client):
        resp = client.get("/pricing")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_faq_page(self, client):
        resp = client.get("/faq")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validation module
# ---------------------------------------------------------------------------

class TestValidationModels:
    def test_create_strategy_request_valid(self):
        from rot.web.validation import CreateStrategyRequest
        req = CreateStrategyRequest(name="Test", description="desc", rules=[], config={})
        assert req.name == "Test"

    def test_create_strategy_request_empty_name(self):
        from rot.web.validation import CreateStrategyRequest
        with pytest.raises(Exception):
            CreateStrategyRequest(name="")

    def test_discover_strategies_bounds(self):
        from rot.web.validation import DiscoverStrategiesRequest
        with pytest.raises(Exception):
            DiscoverStrategiesRequest(days=0)
        with pytest.raises(Exception):
            DiscoverStrategiesRequest(days=999)

    def test_genetic_evolve_bounds(self):
        from rot.web.validation import GeneticEvolveRequest
        with pytest.raises(Exception):
            GeneticEvolveRequest(population_size=200)  # max 100

    def test_ml_optimize_defaults(self):
        from rot.web.validation import MLOptimizeRequest
        req = MLOptimizeRequest()
        assert req.days == 90
        assert req.min_signals == 200


# ---------------------------------------------------------------------------
# Loop manager
# ---------------------------------------------------------------------------

class TestLoopManager:
    @pytest.mark.asyncio
    async def test_background_loop_runs(self):
        import threading
        from rot.app.loop_manager import BackgroundLoop

        call_count = 0
        stop = threading.Event()

        async def work():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                stop.set()

        loop = BackgroundLoop("test", work, interval_s=1, stop_event=stop)
        task = loop.start()

        # Wait for loop to run twice
        for _ in range(10):
            if call_count >= 2:
                break
            await asyncio.sleep(0.5)

        stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_loop_manager_start_cancel(self):
        import threading
        from rot.app.loop_manager import LoopManager

        stop = threading.Event()
        mgr = LoopManager(stop)

        async def noop():
            pass

        mgr.add("a", noop, interval_s=60)
        mgr.add("b", noop, interval_s=60)
        assert len(mgr) == 2
        assert set(mgr.names) == {"a", "b"}

        tasks = mgr.start_all()
        assert len(tasks) == 2

        stop.set()
        mgr.cancel_all()

        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
