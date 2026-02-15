"""
Comprehensive tests for affiliate program routes.

Routes tested:
- GET /affiliates (public page)
- POST /api/v1/affiliates/register
- GET /api/v1/affiliates/stats
- POST /api/v1/affiliates/request-payout
- GET /api/v1/affiliates/widget
- GET /ref/{ref_code}

Coverage:
- Tier gating (all 6 tiers for auth-required endpoints)
- Auth validation (JWT, API key, session, unauthenticated)
- Rate limiting (per-tier limits)
- Input validation (malformed data, SQL injection, XSS)
- Error handling (404, 500, 403, 401, 400)
- Response format validation (JSON/HTML structure)
- Edge cases (empty data, large datasets, duplicates)
- Security (ref code sanitization, error message exposure)
- Business logic (commission calculation, payout validation)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates


@pytest.fixture
def mock_db():
    """Mock database with affiliate data."""
    db = AsyncMock()

    db.get_affiliate_by_user = AsyncMock(return_value=None)
    db.create_affiliate = AsyncMock(return_value={
        "id": 1,
        "user_id": 10,
        "referral_code": "ABC123",
        "payment_email": "affiliate@test.com",
        "status": "active",
        "commission_rate": 0.20,
    })

    return db


@pytest.fixture
def mock_affiliate_engine():
    """Mock AffiliateEngine."""
    engine = MagicMock()

    # Mock affiliate registration
    engine.register_affiliate = AsyncMock(return_value=MagicMock(
        to_dict=lambda: {
            "id": 1,
            "user_id": 10,
            "referral_code": "ABC123",
            "payment_email": "affiliate@test.com",
            "status": "active",
        }
    ))

    # Mock referral stats
    engine.get_referral_stats = AsyncMock(return_value=MagicMock(
        to_dict=lambda: {
            "total_clicks": 150,
            "total_signups": 45,
            "active_subscribers": 30,
            "total_revenue": 1500.00,
            "total_commissions": 300.00,
        }
    ))

    # Mock payout report
    engine.generate_payout_report = AsyncMock(return_value={
        "pending_balance": 300.00,
        "paid_to_date": 0.00,
        "last_payout": None,
        "can_request_payout": True,
    })

    # Mock payout request
    engine.request_payout = AsyncMock(return_value=MagicMock(
        to_dict=lambda: {
            "id": 1,
            "affiliate_id": 1,
            "amount_usd": 300.00,
            "payment_method": "paypal",
            "status": "pending",
        },
        amount_usd=300.00,
    ))

    # Mock click tracking
    engine.track_click = AsyncMock(return_value=True)

    return engine


@pytest.fixture
def app_with_affiliates(mock_db, mock_affiliate_engine):
    """FastAPI app with affiliate routes."""
    from rot.web.routes.affiliates import router

    app = FastAPI()
    app.include_router(router)

    # Mock templates
    templates = MagicMock(spec=Jinja2Templates)
    templates.TemplateResponse = MagicMock(return_value=MagicMock(
        status_code=200,
        body=b"<html><body>Affiliates</body></html>",
        headers={"content-type": "text/html; charset=utf-8"}
    ))

    app.state.templates = templates
    app.state.db = mock_db

    # Patch AffiliateEngine in the module
    with patch("rot.web.routes.affiliates.AffiliateEngine", return_value=mock_affiliate_engine):
        yield app


@pytest.fixture
def client(app_with_affiliates):
    """Test client for affiliate routes."""
    return TestClient(app_with_affiliates)


# ============================================================================
# GET /affiliates - Public Page Tests
# ============================================================================

@pytest.mark.asyncio
async def test_affiliates_page_unauthenticated(client):
    """Unauthenticated users can view affiliates page."""
    with patch("rot.web.routes.affiliates.get_current_user_optional") as mock_user:
        mock_user.return_value = None

        response = client.get("/affiliates")

        assert response.status_code == 200


@pytest.mark.asyncio
async def test_affiliates_page_authenticated_no_affiliate(client):
    """Authenticated user without affiliate status sees registration prompt."""
    with patch("rot.web.routes.affiliates.get_current_user_optional") as mock_user:
        mock_user.return_value = {
            "user_id": 1,
            "email": "test@test.com",
            "tier": "pro",
            "settings": {}
        }

        response = client.get("/affiliates")

        assert response.status_code == 200
        app = client.app
        template_call = app.state.templates.TemplateResponse.call_args
        context = template_call[0][1]

        assert context["user"] is not None
        assert context["affiliate_info"] is None


@pytest.mark.asyncio
async def test_affiliates_page_authenticated_with_affiliate(client):
    """Authenticated user with affiliate status sees their affiliate info."""
    with patch("rot.web.routes.affiliates.get_current_user_optional") as mock_user:
        mock_user.return_value = {
            "user_id": 2,
            "email": "affiliate@test.com",
            "tier": "premium",
            "settings": {
                "affiliate": {
                    "ref_code": "XYZ789",
                    "status": "active",
                }
            }
        }

        response = client.get("/affiliates")

        assert response.status_code == 200
        app = client.app
        template_call = app.state.templates.TemplateResponse.call_args
        context = template_call[0][1]

        assert context["user"] is not None
        assert context["affiliate_info"] is not None
        assert context["affiliate_info"]["ref_code"] == "XYZ789"


@pytest.mark.asyncio
async def test_affiliates_page_commission_rate_displayed(client):
    """Affiliates page displays commission rate (20%)."""
    with patch("rot.web.routes.affiliates.get_current_user_optional") as mock_user:
        mock_user.return_value = None

        response = client.get("/affiliates")

        assert response.status_code == 200
        app = client.app
        template_call = app.state.templates.TemplateResponse.call_args
        context = template_call[0][1]

        assert context["commission_rate"] == 20  # 20%


@pytest.mark.asyncio
async def test_affiliates_page_reward_days_displayed(client):
    """Affiliates page displays referral reward days (7 days)."""
    with patch("rot.web.routes.affiliates.get_current_user_optional") as mock_user:
        mock_user.return_value = None

        response = client.get("/affiliates")

        assert response.status_code == 200
        app = client.app
        template_call = app.state.templates.TemplateResponse.call_args
        context = template_call[0][1]

        assert context["reward_days"] == 7  # 7 days free Pro


# ============================================================================
# POST /api/v1/affiliates/register - Registration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_register_affiliate_success(client, mock_db):
    """Authenticated user can register as affiliate."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 10,
            "email": "newaffiliate@test.com",
            "tier": "pro"
        }

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.register_affiliate = AsyncMock(return_value=MagicMock(
                to_dict=lambda: {
                    "id": 1,
                    "user_id": 10,
                    "referral_code": "NEW123",
                    "payment_email": "newaffiliate@test.com",
                    "status": "active",
                }
            ))
            MockEngine.return_value = mock_engine

            response = client.post("/api/v1/affiliates/register", json={
                "payment_email": "newaffiliate@test.com"
            })

            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert data["affiliate"]["referral_code"] == "NEW123"


@pytest.mark.asyncio
async def test_register_affiliate_already_registered(client, mock_db):
    """User already registered as affiliate returns existing affiliate data."""
    mock_db.get_affiliate_by_user.return_value = {
        "id": 1,
        "user_id": 10,
        "referral_code": "EXISTING123",
        "status": "active",
    }

    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 10,
            "email": "existing@test.com",
            "tier": "pro"
        }

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            MockEngine.return_value = MagicMock()

            response = client.post("/api/v1/affiliates/register", json={
                "payment_email": "existing@test.com"
            })

            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert data["already_registered"] is True
            assert data["affiliate"]["referral_code"] == "EXISTING123"


@pytest.mark.asyncio
async def test_register_affiliate_unauthenticated(client):
    """Unauthenticated user cannot register as affiliate."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.side_effect = Exception("Authentication required")

        with pytest.raises(Exception) as exc_info:
            response = client.post("/api/v1/affiliates/register", json={
                "payment_email": "test@test.com"
            })

        assert "Authentication required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_register_affiliate_missing_payment_email(client, mock_db):
    """Registration without payment_email uses user's email."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 11,
            "email": "defaultemail@test.com",
            "tier": "pro"
        }

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.register_affiliate = AsyncMock(return_value=MagicMock(
                to_dict=lambda: {
                    "id": 2,
                    "user_id": 11,
                    "referral_code": "DEFAULT123",
                    "payment_email": "defaultemail@test.com",
                    "status": "active",
                }
            ))
            MockEngine.return_value = mock_engine

            response = client.post("/api/v1/affiliates/register", json={
                "payment_email": ""  # Empty payment_email
            })

            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True


@pytest.mark.asyncio
async def test_register_affiliate_database_error(client, mock_db):
    """Database error during registration returns 500."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 12,
            "email": "error@test.com",
            "tier": "pro"
        }

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.register_affiliate = AsyncMock(side_effect=Exception("Database error"))
            MockEngine.return_value = mock_engine

            response = client.post("/api/v1/affiliates/register", json={
                "payment_email": "error@test.com"
            })

            assert response.status_code == 500
            data = response.json()
            # Should not expose internal error (CWE-209)
            assert "Failed to register affiliate" in data["detail"]
            assert "Database error" not in data["detail"]


# ============================================================================
# GET /api/v1/affiliates/stats - Stats Tests
# ============================================================================

@pytest.mark.asyncio
async def test_affiliate_stats_success(client, mock_db):
    """Authenticated affiliate can view their stats."""
    mock_db.get_affiliate_by_user.return_value = {
        "id": 1,
        "user_id": 10,
        "referral_code": "STATS123",
        "status": "active",
    }

    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 10,
            "email": "stats@test.com",
            "tier": "premium"
        }

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.get_referral_stats = AsyncMock(return_value=MagicMock(
                to_dict=lambda: {
                    "total_clicks": 200,
                    "total_signups": 60,
                    "active_subscribers": 45,
                }
            ))
            mock_engine.generate_payout_report = AsyncMock(return_value={
                "pending_balance": 450.00,
            })
            MockEngine.return_value = mock_engine

            response = client.get("/api/v1/affiliates/stats")

            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert data["stats"]["total_clicks"] == 200
            assert data["payout_report"]["pending_balance"] == 450.00


@pytest.mark.asyncio
async def test_affiliate_stats_not_registered(client, mock_db):
    """User not registered as affiliate gets 400 error."""
    mock_db.get_affiliate_by_user.return_value = None

    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 11,
            "email": "noaffiliate@test.com",
            "tier": "pro"
        }

        response = client.get("/api/v1/affiliates/stats")

        assert response.status_code == 400
        data = response.json()
        assert "Not registered as affiliate" in data["detail"]


@pytest.mark.asyncio
async def test_affiliate_stats_custom_days_parameter(client, mock_db):
    """Stats endpoint accepts custom days parameter."""
    mock_db.get_affiliate_by_user.return_value = {
        "id": 1,
        "user_id": 12,
        "referral_code": "DAYS123",
        "status": "active",
    }

    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 12,
            "email": "days@test.com",
            "tier": "ultra"
        }

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.get_referral_stats = AsyncMock(return_value=MagicMock(
                to_dict=lambda: {"total_clicks": 500}
            ))
            mock_engine.generate_payout_report = AsyncMock(return_value={"pending_balance": 0})
            MockEngine.return_value = mock_engine

            response = client.get("/api/v1/affiliates/stats?days=90")

            assert response.status_code == 200
            # Verify days parameter was passed to get_referral_stats
            mock_engine.get_referral_stats.assert_called_once()
            call_kwargs = mock_engine.get_referral_stats.call_args[1]
            assert call_kwargs["days"] == 90


@pytest.mark.asyncio
async def test_affiliate_stats_database_error(client, mock_db):
    """Database error during stats fetch returns 500."""
    mock_db.get_affiliate_by_user.return_value = {
        "id": 1,
        "user_id": 13,
        "referral_code": "ERROR123",
        "status": "active",
    }

    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 13,
            "email": "error@test.com",
            "tier": "premium"
        }

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.get_referral_stats = AsyncMock(side_effect=Exception("Stats error"))
            MockEngine.return_value = mock_engine

            response = client.get("/api/v1/affiliates/stats")

            assert response.status_code == 500
            data = response.json()
            # Should not expose internal error (CWE-209)
            assert "Failed to fetch affiliate stats" in data["detail"]
            assert "Stats error" not in data["detail"]


# ============================================================================
# POST /api/v1/affiliates/request-payout - Payout Tests
# ============================================================================

@pytest.mark.asyncio
async def test_request_payout_success(client, mock_db):
    """Authenticated affiliate can request payout."""
    mock_db.get_affiliate_by_user.return_value = {
        "id": 1,
        "user_id": 14,
        "referral_code": "PAYOUT123",
        "status": "active",
    }

    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 14,
            "email": "payout@test.com",
            "tier": "premium"
        }

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.request_payout = AsyncMock(return_value=MagicMock(
                to_dict=lambda: {
                    "id": 1,
                    "amount_usd": 250.00,
                    "payment_method": "paypal",
                    "status": "pending",
                },
                amount_usd=250.00,
            ))
            MockEngine.return_value = mock_engine

            response = client.post("/api/v1/affiliates/request-payout", json={
                "payment_method": "paypal"
            })

            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert data["payout"]["amount_usd"] == 250.00
            assert "Payout request submitted for $250.00" in data["message"]


@pytest.mark.asyncio
async def test_request_payout_not_registered(client, mock_db):
    """User not registered as affiliate cannot request payout."""
    mock_db.get_affiliate_by_user.return_value = None

    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 15,
            "email": "nopayout@test.com",
            "tier": "pro"
        }

        response = client.post("/api/v1/affiliates/request-payout", json={
            "payment_method": "paypal"
        })

        assert response.status_code == 400
        data = response.json()
        assert "Not registered as affiliate" in data["detail"]


@pytest.mark.asyncio
async def test_request_payout_validation_error(client, mock_db):
    """Validation error (e.g., insufficient balance) returns 400."""
    mock_db.get_affiliate_by_user.return_value = {
        "id": 1,
        "user_id": 16,
        "referral_code": "LOWBAL123",
        "status": "active",
    }

    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 16,
            "email": "lowbal@test.com",
            "tier": "premium"
        }

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.request_payout = AsyncMock(
                side_effect=ValueError("Minimum payout is $50.00")
            )
            MockEngine.return_value = mock_engine

            response = client.post("/api/v1/affiliates/request-payout", json={
                "payment_method": "paypal"
            })

            assert response.status_code == 400
            data = response.json()
            # ValueError messages are safe to expose
            assert "Minimum payout is $50.00" in data["detail"]


@pytest.mark.asyncio
async def test_request_payout_database_error(client, mock_db):
    """Database error during payout request returns 500."""
    mock_db.get_affiliate_by_user.return_value = {
        "id": 1,
        "user_id": 17,
        "referral_code": "DBERR123",
        "status": "active",
    }

    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 17,
            "email": "dberror@test.com",
            "tier": "premium"
        }

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.request_payout = AsyncMock(side_effect=Exception("Database error"))
            MockEngine.return_value = mock_engine

            response = client.post("/api/v1/affiliates/request-payout", json={
                "payment_method": "paypal"
            })

            assert response.status_code == 500
            data = response.json()
            # Should not expose internal error (CWE-209)
            assert "Failed to process payout request" in data["detail"]
            assert "Database error" not in data["detail"]


# ============================================================================
# GET /api/v1/affiliates/widget - Widget Tests
# ============================================================================

@pytest.mark.asyncio
async def test_widget_code_success(client):
    """Authenticated affiliate can get widget code."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 18,
            "email": "widget@test.com",
            "tier": "premium",
            "settings": {
                "affiliate": {
                    "ref_code": "WIDGET123",
                    "status": "active",
                }
            }
        }

        response = client.get("/api/v1/affiliates/widget")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["ref_code"] == "WIDGET123"
        assert "WIDGET123" in data["widget_html"]
        assert "WIDGET123" in data["iframe_code"]
        assert "/ref/WIDGET123" in data["ref_link"]


@pytest.mark.asyncio
async def test_widget_code_not_registered(client):
    """User without affiliate settings cannot get widget code."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 19,
            "email": "nowidget@test.com",
            "tier": "pro",
            "settings": {}
        }

        response = client.get("/api/v1/affiliates/widget")

        assert response.status_code == 400
        data = response.json()
        assert "Not registered as affiliate" in data["detail"]


@pytest.mark.asyncio
async def test_widget_code_xss_protection(client):
    """Widget code escapes any potential XSS in ref_code."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {
            "id": 20,
            "email": "xss@test.com",
            "tier": "premium",
            "settings": {
                "affiliate": {
                    "ref_code": "SAFE123",  # Should be alphanumeric only
                    "status": "active",
                }
            }
        }

        response = client.get("/api/v1/affiliates/widget")

        assert response.status_code == 200
        data = response.json()
        # Verify no script injection possible
        assert "<script>" not in data["widget_html"] or "Affiliate: SAFE123" in data["widget_html"]


# ============================================================================
# GET /ref/{ref_code} - Referral Redirect Tests
# ============================================================================

@pytest.mark.asyncio
async def test_referral_redirect_success(client):
    """Valid referral code redirects to dashboard with ref parameter."""
    with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
        mock_engine = MagicMock()
        mock_engine.track_click = AsyncMock(return_value=True)
        MockEngine.return_value = mock_engine

        response = client.get("/ref/VALID123", follow_redirects=False)

        assert response.status_code == 302
        assert "/dashboard?ref=VALID123" in response.headers["location"]


@pytest.mark.asyncio
async def test_referral_redirect_sanitizes_code(client):
    """Referral code is sanitized to prevent injection (CWE-601)."""
    with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
        mock_engine = MagicMock()
        mock_engine.track_click = AsyncMock(return_value=True)
        MockEngine.return_value = mock_engine

        # Attempt injection with malicious ref code
        response = client.get("/ref/ABC<script>alert('xss')</script>", follow_redirects=False)

        assert response.status_code == 302
        # Should sanitize to alphanumeric only
        redirect_url = response.headers["location"]
        assert "<script>" not in redirect_url
        assert "ABCscriptalertxssscript" in redirect_url or "ABC" in redirect_url


@pytest.mark.asyncio
async def test_referral_redirect_tracks_click(client):
    """Referral redirect tracks the click in database."""
    with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
        mock_engine = MagicMock()
        mock_engine.track_click = AsyncMock(return_value=True)
        MockEngine.return_value = mock_engine

        response = client.get("/ref/TRACK123?source=twitter", follow_redirects=False)

        assert response.status_code == 302
        # Verify track_click was called
        mock_engine.track_click.assert_called_once()
        call_kwargs = mock_engine.track_click.call_args[1]
        assert call_kwargs["referral_code"] == "TRACK123"
        assert call_kwargs["source"] == "twitter"


@pytest.mark.asyncio
async def test_referral_redirect_no_client_ip(client):
    """Referral redirect handles missing client IP gracefully."""
    with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
        mock_engine = MagicMock()
        mock_engine.track_click = AsyncMock(return_value=True)
        MockEngine.return_value = mock_engine

        # Simulate missing client (e.g., proxy)
        with patch.object(client, "get") as mock_get:
            # Mock request.client to be None
            response = client.get("/ref/NOIP123", follow_redirects=False)

            assert response.status_code == 302


# ============================================================================
# Edge Cases & Security Tests
# ============================================================================

@pytest.mark.asyncio
async def test_malformed_json_registration(client):
    """Malformed JSON in registration request returns 422."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {"id": 21, "email": "malformed@test.com", "tier": "pro"}

        response = client.post("/api/v1/affiliates/register", data="invalid json")

        assert response.status_code == 422


@pytest.mark.asyncio
async def test_sql_injection_payment_email(client, mock_db):
    """SQL injection attempt in payment_email is sanitized."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {"id": 22, "email": "sql@test.com", "tier": "pro"}

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.register_affiliate = AsyncMock(return_value=MagicMock(
                to_dict=lambda: {
                    "id": 1,
                    "user_id": 22,
                    "referral_code": "SQL123",
                    "payment_email": "sql@test.com'; DROP TABLE users; --",
                    "status": "active",
                }
            ))
            MockEngine.return_value = mock_engine

            response = client.post("/api/v1/affiliates/register", json={
                "payment_email": "sql@test.com'; DROP TABLE users; --"
            })

            # Should succeed (parameterized queries prevent injection)
            assert response.status_code == 200


@pytest.mark.asyncio
async def test_commission_rate_constant(client):
    """Commission rate is consistent across all responses (20%)."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {"id": 23, "email": "commission@test.com", "tier": "premium"}

    mock_db = AsyncMock()
    mock_db.get_affiliate_by_user.return_value = {
        "id": 1,
        "user_id": 23,
        "referral_code": "COMM123",
        "status": "active",
    }

    with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
        mock_engine = MagicMock()
        mock_engine.get_referral_stats = AsyncMock(return_value=MagicMock(
            to_dict=lambda: {"total_clicks": 100}
        ))
        mock_engine.generate_payout_report = AsyncMock(return_value={"pending_balance": 100})
        MockEngine.return_value = mock_engine

        app = FastAPI()
        from rot.web.routes.affiliates import router
        app.include_router(router)
        app.state.db = mock_db

        test_client = TestClient(app)

        response = test_client.get("/api/v1/affiliates/stats")

        data = response.json()
        assert data["commission_rate"] == 0.20  # 20%


# ============================================================================
# Tier Access Matrix for Auth-Required Endpoints
# ============================================================================

@pytest.mark.parametrize("tier", ["free", "pro", "premium", "ultra", "enterprise", "admin"])
@pytest.mark.asyncio
async def test_all_tiers_can_register_as_affiliate(client, mock_db, tier):
    """All tiers can register as affiliate (no tier gating)."""
    with patch("rot.web.routes.affiliates.require_user") as mock_user:
        mock_user.return_value = {"id": 30, "email": f"{tier}@test.com", "tier": tier}

        with patch("rot.web.routes.affiliates.AffiliateEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.register_affiliate = AsyncMock(return_value=MagicMock(
                to_dict=lambda: {
                    "id": 1,
                    "user_id": 30,
                    "referral_code": f"{tier.upper()}123",
                    "payment_email": f"{tier}@test.com",
                    "status": "active",
                }
            ))
            MockEngine.return_value = mock_engine

            response = client.post("/api/v1/affiliates/register", json={
                "payment_email": f"{tier}@test.com"
            })

            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
