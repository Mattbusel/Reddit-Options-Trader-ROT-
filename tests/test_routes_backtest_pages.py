"""Backtest route tests.

Tests for the backtest dashboard, run, Monte Carlo, walk-forward,
optimizer, strategy CRUD, saved result, export, and compare pages.
Covers tier gating (free blocked, pro basic, premium MC/WF, ultra optimizer).
"""
from __future__ import annotations

import json
import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-backtest-route-tests-1234!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes
from rot.web.auth import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-backtest-route-tests-1234!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-backtest-route-tests-1234!"},
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_user(app, settings, tier="free"):
    """Create a user at the given tier and return (user_dict, jwt_token)."""
    db = app.state.db
    unique = uuid.uuid4().hex[:8]
    email = f"bt_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


async def _insert_signal(db, ticker="AAPL", stance="bullish", confidence=0.75):
    """Insert a signal row for backtest consumption."""
    sig_id = uuid.uuid4().hex
    now = time.time()
    await db.db.execute(
        """INSERT INTO signals
           (id, created_at, ticker, event_type, stance, time_horizon,
            confidence, trend_score, quality_score, strategy, subreddit,
            post_title, post_url, reasoning, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sig_id, now, ticker, "earnings_rumor", stance, "short",
         confidence, 5.0, 0.8, "long_call", "wallstreetbets",
         f"Test {ticker}", f"https://reddit.com/test",
         '{"thesis":"test"}', "reddit"),
    )
    await db.db.commit()
    return sig_id


async def _insert_backtest_run(db, user_id, config_dict=None, result_dict=None):
    """Insert a saved backtest run row and return its id."""
    run_id = uuid.uuid4().hex
    now = time.time()
    config = config_dict or {
        "starting_capital": 10000.0,
        "position_size_mode": "fixed_pct",
        "position_size_pct": 5.0,
        "max_concurrent_positions": 5,
        "stop_loss_pct": 0.0,
        "take_profit_pct": 0.0,
        "min_confidence": 0.0,
        "days": 30,
    }
    result = result_dict or {
        "total_return_pct": 12.5,
        "total_trades": 10,
        "win_rate": 0.7,
        "max_drawdown_pct": 3.2,
        "sharpe_ratio": 1.5,
        "trades": [
            {
                "signal_id": "test",
                "ticker": "AAPL",
                "stance": "bullish",
                "strategy": "long_call",
                "event_type": "earnings_rumor",
                "confidence": 0.8,
                "entry_time": now - 86400,
                "entry_price": 150.0,
                "exit_price": 155.0,
                "pnl_pct": 3.3,
                "pnl_dollars": 330.0,
                "is_win": True,
            }
        ],
    }
    await db.db.execute(
        """INSERT INTO backtest_runs
           (id, user_id, name, config_json, result_json, risk_json, monte_carlo_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, user_id, "Test Run", json.dumps(config), json.dumps(result),
         "{}", "{}", now),
    )
    await db.db.commit()
    return run_id


# ═══════════════════════════════════════════════════════════════════════════
# Backtest Main Page (/backtest)
# ═══════════════════════════════════════════════════════════════════════════

class TestBacktestPage:
    """Tests for GET /backtest — main backtest dashboard."""

    @pytest.mark.asyncio
    async def test_anonymous_redirects_to_login(self, client):
        """Anonymous user redirected to /login."""
        resp = client.get("/backtest", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_free_redirects_to_pricing(self, client, app_with_db, tmp_settings):
        """Free tier redirected to /pricing."""
        _, token = await _create_user(app_with_db, tmp_settings, "free")
        resp = client.get("/backtest", cookies={"rot_session": token}, follow_redirects=False)
        assert resp.status_code == 302
        assert "/pricing" in resp.headers.get("location", "")

    @pytest.mark.parametrize("tier", ["pro", "premium", "ultra"])
    @pytest.mark.asyncio
    async def test_paid_tiers_can_access(self, tier, client, app_with_db, tmp_settings):
        """Paid tiers can access backtest page."""
        _, token = await _create_user(app_with_db, tmp_settings, tier)
        resp = client.get("/backtest", cookies={"rot_session": token})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_page_contains_html(self, client, app_with_db, tmp_settings):
        """Backtest page returns HTML content."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.get("/backtest", cookies={"rot_session": token})
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ═══════════════════════════════════════════════════════════════════════════
# Backtest Run (/backtest/run)
# ═══════════════════════════════════════════════════════════════════════════

class TestBacktestRun:
    """Tests for POST /backtest/run — execute a backtest."""

    @pytest.mark.asyncio
    async def test_free_blocked(self, client, app_with_db, tmp_settings):
        """Free tier cannot run backtests."""
        _, token = await _create_user(app_with_db, tmp_settings, "free")
        resp = client.post(
            "/backtest/run",
            data={"starting_capital": "10000", "days": "30"},
            cookies={"rot_session": token},
        )
        assert resp.status_code in (302, 403)

    @pytest.mark.asyncio
    async def test_pro_can_run_backtest(self, client, app_with_db, tmp_settings):
        """Pro tier can run a backtest."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        # Insert some signals for the backtest to consume
        for t in ["AAPL", "TSLA", "NVDA"]:
            await _insert_signal(db, t)
        resp = client.post(
            "/backtest/run",
            data={
                "starting_capital": "10000",
                "position_size_mode": "fixed_pct",
                "position_size_pct": "5.0",
                "max_concurrent_positions": "5",
                "stop_loss_pct": "0",
                "take_profit_pct": "0",
                "min_confidence": "0",
                "strategy_filter": "",
                "event_type_filter": "",
                "stance_filter": "",
                "ticker_filter": "",
                "days": "30",
                "use_1d_price": "true",
            },
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("capital", ["1000", "10000", "100000", "1000000"])
    @pytest.mark.asyncio
    async def test_different_capitals(self, capital, client, app_with_db, tmp_settings):
        """Different starting capitals are accepted."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.post(
            "/backtest/run",
            data={
                "starting_capital": capital,
                "position_size_mode": "fixed_pct",
                "position_size_pct": "5.0",
                "max_concurrent_positions": "5",
                "stop_loss_pct": "0",
                "take_profit_pct": "0",
                "min_confidence": "0",
                "strategy_filter": "",
                "event_type_filter": "",
                "stance_filter": "",
                "ticker_filter": "",
                "days": "30",
                "use_1d_price": "true",
            },
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("stance_filter", ["bullish", "bearish", ""])
    @pytest.mark.asyncio
    async def test_stance_filters(self, stance_filter, client, app_with_db, tmp_settings):
        """Stance filters work."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.post(
            "/backtest/run",
            data={
                "starting_capital": "10000",
                "position_size_mode": "fixed_pct",
                "position_size_pct": "5.0",
                "max_concurrent_positions": "5",
                "stop_loss_pct": "0",
                "take_profit_pct": "0",
                "min_confidence": "0",
                "strategy_filter": "",
                "event_type_filter": "",
                "stance_filter": stance_filter,
                "ticker_filter": "",
                "days": "30",
                "use_1d_price": "true",
            },
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("days", ["7", "30", "90"])
    @pytest.mark.asyncio
    async def test_different_day_ranges(self, days, client, app_with_db, tmp_settings):
        """Different day ranges accepted (capped by tier)."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.post(
            "/backtest/run",
            data={
                "starting_capital": "10000",
                "position_size_mode": "fixed_pct",
                "position_size_pct": "5.0",
                "max_concurrent_positions": "5",
                "stop_loss_pct": "0",
                "take_profit_pct": "0",
                "min_confidence": "0",
                "strategy_filter": "",
                "event_type_filter": "",
                "stance_filter": "",
                "ticker_filter": "",
                "days": days,
                "use_1d_price": "true",
            },
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_ticker_filter(self, client, app_with_db, tmp_settings):
        """Ticker filter uppercased."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        await _insert_signal(db, "AAPL")
        resp = client.post(
            "/backtest/run",
            data={
                "starting_capital": "10000",
                "position_size_mode": "fixed_pct",
                "position_size_pct": "5.0",
                "max_concurrent_positions": "5",
                "stop_loss_pct": "0",
                "take_profit_pct": "0",
                "min_confidence": "0",
                "strategy_filter": "",
                "event_type_filter": "",
                "stance_filter": "",
                "ticker_filter": "aapl",
                "days": "30",
                "use_1d_price": "true",
            },
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Monte Carlo (/backtest/monte-carlo/{run_id})
# ═══════════════════════════════════════════════════════════════════════════

class TestMonteCarlo:
    """Tests for POST /backtest/monte-carlo/{run_id} — premium+."""

    @pytest.mark.asyncio
    async def test_pro_blocked(self, client, app_with_db, tmp_settings):
        """Pro tier blocked from Monte Carlo."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        run_id = await _insert_backtest_run(db, user["id"])
        resp = client.post(
            f"/backtest/monte-carlo/{run_id}",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_premium_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can run Monte Carlo."""
        user, token = await _create_user(app_with_db, tmp_settings, "premium")
        db = app_with_db.state.db
        run_id = await _insert_backtest_run(db, user["id"])
        resp = client.post(
            f"/backtest/monte-carlo/{run_id}",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_run_not_found(self, client, app_with_db, tmp_settings):
        """Monte Carlo on nonexistent run returns 404."""
        _, token = await _create_user(app_with_db, tmp_settings, "premium")
        resp = client.post(
            "/backtest/monte-carlo/nonexistent-id",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_ultra_allowed(self, client, app_with_db, tmp_settings):
        """Ultra tier can run Monte Carlo."""
        user, token = await _create_user(app_with_db, tmp_settings, "ultra")
        db = app_with_db.state.db
        run_id = await _insert_backtest_run(db, user["id"])
        resp = client.post(
            f"/backtest/monte-carlo/{run_id}",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Walk-Forward (/backtest/walk-forward/{run_id})
# ═══════════════════════════════════════════════════════════════════════════

class TestWalkForward:
    """Tests for POST /backtest/walk-forward/{run_id} — premium+."""

    @pytest.mark.asyncio
    async def test_pro_blocked(self, client, app_with_db, tmp_settings):
        """Pro tier blocked from walk-forward."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        run_id = await _insert_backtest_run(db, user["id"])
        resp = client.post(
            f"/backtest/walk-forward/{run_id}",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_premium_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can run walk-forward."""
        user, token = await _create_user(app_with_db, tmp_settings, "premium")
        db = app_with_db.state.db
        run_id = await _insert_backtest_run(db, user["id"])
        resp = client.post(
            f"/backtest/walk-forward/{run_id}",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_run_not_found(self, client, app_with_db, tmp_settings):
        """Walk-forward on nonexistent run returns 404."""
        _, token = await _create_user(app_with_db, tmp_settings, "premium")
        resp = client.post(
            "/backtest/walk-forward/nonexistent-id",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Optimizer (/backtest/optimize)
# ═══════════════════════════════════════════════════════════════════════════

class TestOptimizer:
    """Tests for POST /backtest/optimize — ultra+."""

    @pytest.mark.parametrize("tier,expected_ok", [
        ("pro", False),
        ("premium", False),
        ("ultra", True),
    ])
    @pytest.mark.asyncio
    async def test_tier_gating(self, tier, expected_ok, client, app_with_db, tmp_settings):
        """Optimizer requires ultra+."""
        _, token = await _create_user(app_with_db, tmp_settings, tier)
        resp = client.post(
            "/backtest/optimize",
            data={"days": "30", "strategy_filter": "", "stance_filter": ""},
            cookies={"rot_session": token},
        )
        if expected_ok:
            assert resp.status_code == 200
        else:
            assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# Strategy CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestStrategyCRUD:
    """Tests for strategy save and delete."""

    @pytest.mark.asyncio
    async def test_save_requires_ultra(self, client, app_with_db, tmp_settings):
        """Strategy save requires ultra tier."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.post(
            "/backtest/strategies/save",
            data={"name": "My Strategy", "description": "test", "config_json": "{}"},
            cookies={"rot_session": token},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_ultra_can_save(self, client, app_with_db, tmp_settings):
        """Ultra tier can save a strategy."""
        _, token = await _create_user(app_with_db, tmp_settings, "ultra")
        resp = client.post(
            "/backtest/strategies/save",
            data={"name": "My Strategy", "description": "test", "config_json": "{}"},
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_save_requires_name(self, client, app_with_db, tmp_settings):
        """Strategy save without name returns error."""
        _, token = await _create_user(app_with_db, tmp_settings, "ultra")
        resp = client.post(
            "/backtest/strategies/save",
            data={"name": "", "description": "test", "config_json": "{}"},
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200  # returns HTML error message
        assert b"required" in resp.content.lower() or b"Name" in resp.content

    @pytest.mark.asyncio
    async def test_delete_unauthenticated(self, client):
        """Delete strategy unauthenticated returns 401."""
        resp = client.delete("/backtest/strategies/some-id")
        assert resp.status_code in (401, 405)

    @pytest.mark.asyncio
    async def test_delete_authenticated(self, client, app_with_db, tmp_settings):
        """Authenticated user can delete their strategy."""
        user, token = await _create_user(app_with_db, tmp_settings, "ultra")
        # Deleting non-existent strategy is a no-op
        resp = client.delete(
            "/backtest/strategies/nonexistent-id",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Saved Result (/backtest/result/{run_id})
# ═══════════════════════════════════════════════════════════════════════════

class TestSavedResult:
    """Tests for GET /backtest/result/{run_id}."""

    @pytest.mark.asyncio
    async def test_free_redirects(self, client, app_with_db, tmp_settings):
        """Free tier redirected from result page."""
        _, token = await _create_user(app_with_db, tmp_settings, "free")
        resp = client.get(
            "/backtest/result/any-id",
            cookies={"rot_session": token},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    @pytest.mark.asyncio
    async def test_run_not_found_redirects(self, client, app_with_db, tmp_settings):
        """Nonexistent run redirects to backtest page."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.get(
            "/backtest/result/nonexistent",
            cookies={"rot_session": token},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/backtest" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_pro_can_view_result(self, client, app_with_db, tmp_settings):
        """Pro tier can view saved backtest result."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        run_id = await _insert_backtest_run(db, user["id"])
        resp = client.get(
            f"/backtest/result/{run_id}",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Export (/api/v1/backtest/export/{run_id})
# ═══════════════════════════════════════════════════════════════════════════

class TestBacktestExport:
    """Tests for GET /api/v1/backtest/export/{run_id}."""

    @pytest.mark.parametrize("tier,expected_ok", [
        ("pro", False),
        ("premium", False),
        ("ultra", True),
    ])
    @pytest.mark.asyncio
    async def test_export_tier_gating(self, tier, expected_ok, client, app_with_db, tmp_settings):
        """Export requires ultra+."""
        user, token = await _create_user(app_with_db, tmp_settings, tier)
        db = app_with_db.state.db
        run_id = await _insert_backtest_run(db, user["id"])
        resp = client.get(
            f"/api/v1/backtest/export/{run_id}",
            cookies={"rot_session": token},
        )
        if expected_ok:
            assert resp.status_code == 200
        else:
            assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_export_json(self, client, app_with_db, tmp_settings):
        """Export as JSON."""
        user, token = await _create_user(app_with_db, tmp_settings, "ultra")
        db = app_with_db.state.db
        run_id = await _insert_backtest_run(db, user["id"])
        resp = client.get(
            f"/api/v1/backtest/export/{run_id}?fmt=json",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_export_csv(self, client, app_with_db, tmp_settings):
        """Export as CSV."""
        user, token = await _create_user(app_with_db, tmp_settings, "ultra")
        db = app_with_db.state.db
        run_id = await _insert_backtest_run(db, user["id"])
        resp = client.get(
            f"/api/v1/backtest/export/{run_id}?fmt=csv",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_export_not_found(self, client, app_with_db, tmp_settings):
        """Export nonexistent run returns 404."""
        _, token = await _create_user(app_with_db, tmp_settings, "ultra")
        resp = client.get(
            "/api/v1/backtest/export/nonexistent-id",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Compare Page (/backtest/compare)
# ═══════════════════════════════════════════════════════════════════════════

class TestBacktestCompare:
    """Tests for GET /backtest/compare."""

    @pytest.mark.parametrize("tier,expected_ok", [
        ("pro", False),
        ("premium", False),
        ("ultra", True),
    ])
    @pytest.mark.asyncio
    async def test_compare_tier_gating(self, tier, expected_ok, client, app_with_db, tmp_settings):
        """Compare requires ultra+."""
        _, token = await _create_user(app_with_db, tmp_settings, tier)
        resp = client.get(
            "/backtest/compare",
            cookies={"rot_session": token},
            follow_redirects=False,
        )
        if expected_ok:
            assert resp.status_code == 200
        else:
            assert resp.status_code == 302

    @pytest.mark.asyncio
    async def test_compare_page_html(self, client, app_with_db, tmp_settings):
        """Compare page returns HTML."""
        _, token = await _create_user(app_with_db, tmp_settings, "ultra")
        resp = client.get("/backtest/compare", cookies={"rot_session": token})
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ═══════════════════════════════════════════════════════════════════════════
# Backtest Config Validation
# ═══════════════════════════════════════════════════════════════════════════

class TestBacktestConfigEdgeCases:
    """Edge cases for backtest run parameters."""

    @pytest.mark.parametrize("position_size_mode", ["fixed_pct", "kelly", "equal_weight"])
    @pytest.mark.asyncio
    async def test_position_size_modes(self, position_size_mode, client, app_with_db, tmp_settings):
        """Different position size modes are handled."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.post(
            "/backtest/run",
            data={
                "starting_capital": "10000",
                "position_size_mode": position_size_mode,
                "position_size_pct": "5.0",
                "max_concurrent_positions": "5",
                "stop_loss_pct": "0",
                "take_profit_pct": "0",
                "min_confidence": "0",
                "strategy_filter": "",
                "event_type_filter": "",
                "stance_filter": "",
                "ticker_filter": "",
                "days": "30",
                "use_1d_price": "true",
            },
            cookies={"rot_session": token},
        )
        # Pro may not have access to all modes — either 200 (accepted) or
        # mode was reset to fixed_pct and still returns 200
        assert resp.status_code == 200

    @pytest.mark.parametrize("stop_loss,take_profit", [
        ("0", "0"),
        ("5", "10"),
        ("10", "20"),
        ("2", "5"),
    ])
    @pytest.mark.asyncio
    async def test_stop_take_profit_combos(self, stop_loss, take_profit, client, app_with_db, tmp_settings):
        """Various stop loss / take profit combinations."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.post(
            "/backtest/run",
            data={
                "starting_capital": "10000",
                "position_size_mode": "fixed_pct",
                "position_size_pct": "5.0",
                "max_concurrent_positions": "5",
                "stop_loss_pct": stop_loss,
                "take_profit_pct": take_profit,
                "min_confidence": "0",
                "strategy_filter": "",
                "event_type_filter": "",
                "stance_filter": "",
                "ticker_filter": "",
                "days": "30",
                "use_1d_price": "true",
            },
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("max_positions", ["1", "3", "5", "10"])
    @pytest.mark.asyncio
    async def test_max_concurrent_positions(self, max_positions, client, app_with_db, tmp_settings):
        """Different max concurrent position values."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.post(
            "/backtest/run",
            data={
                "starting_capital": "10000",
                "position_size_mode": "fixed_pct",
                "position_size_pct": "5.0",
                "max_concurrent_positions": max_positions,
                "stop_loss_pct": "0",
                "take_profit_pct": "0",
                "min_confidence": "0",
                "strategy_filter": "",
                "event_type_filter": "",
                "stance_filter": "",
                "ticker_filter": "",
                "days": "30",
                "use_1d_price": "true",
            },
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("min_conf", ["0", "30", "50", "70", "90"])
    @pytest.mark.asyncio
    async def test_min_confidence_values(self, min_conf, client, app_with_db, tmp_settings):
        """Min confidence (percentage input, converted to 0-1 by route)."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.post(
            "/backtest/run",
            data={
                "starting_capital": "10000",
                "position_size_mode": "fixed_pct",
                "position_size_pct": "5.0",
                "max_concurrent_positions": "5",
                "stop_loss_pct": "0",
                "take_profit_pct": "0",
                "min_confidence": min_conf,
                "strategy_filter": "",
                "event_type_filter": "",
                "stance_filter": "",
                "ticker_filter": "",
                "days": "30",
                "use_1d_price": "true",
            },
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200
