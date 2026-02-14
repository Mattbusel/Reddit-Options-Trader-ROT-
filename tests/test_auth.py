"""
Test suite for authentication module (Work Stream 4).

Covers:
- Password hashing and verification
- JWT creation and validation
- API key generation and hashing
- Admin elevation
- get_current_user_optional() priority order
- require_user() authentication check
- require_tier() tier checking
"""
import json
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import HTTPException, Request
from jose import jwt

from rot.web.auth import (
    create_access_token,
    generate_api_key,
    get_current_user_optional,
    hash_api_key,
    hash_password,
    require_tier,
    require_user,
    verify_password,
)


# =========================================================================
# Password Hashing Tests
# =========================================================================


class TestPasswordHashing:
    """Test password hashing and verification (bcrypt)."""

    def test_hash_password_returns_string(self):
        """hash_password() returns a bcrypt hash string."""
        password = "SecureP@ssw0rd123"
        hashed = hash_password(password)

        assert isinstance(hashed, str)
        assert hashed != password
        assert hashed.startswith("$2b$")  # bcrypt prefix

    def test_hash_password_different_each_time(self):
        """hash_password() generates different hashes for same password (salt)."""
        password = "SamePassword"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2  # Different salts

    def test_verify_password_correct(self):
        """verify_password() returns True for correct password."""
        password = "CorrectPassword123"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """verify_password() returns False for wrong password."""
        password = "CorrectPassword123"
        hashed = hash_password(password)

        assert verify_password("WrongPassword", hashed) is False

    def test_verify_password_empty_password(self):
        """verify_password() handles empty password."""
        hashed = hash_password("nonempty")

        assert verify_password("", hashed) is False

    def test_verify_password_invalid_hash(self):
        """verify_password() returns False for invalid hash."""
        assert verify_password("password", "not_a_valid_hash") is False

    def test_verify_password_unicode(self):
        """verify_password() handles Unicode characters."""
        password = "Pāsswørd123日本語"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True
        assert verify_password("WrongPassword", hashed) is False


# =========================================================================
# JWT Tests
# =========================================================================


class TestJWT:
    """Test JWT token creation and validation."""

    def test_create_access_token_includes_claims(self):
        """create_access_token() includes user_id, email, tier in claims."""
        settings = MagicMock()
        settings.auth.jwt_secret = "test_secret_key_123"
        settings.auth.jwt_expire_minutes = 1440  # 24h
        settings.auth.jwt_algorithm = "HS256"
        settings.web.secret_key = "fallback"

        token = create_access_token("user123", "user@example.com", "pro", settings)

        payload = jwt.decode(token, "test_secret_key_123", algorithms=["HS256"])
        assert payload["sub"] == "user123"
        assert payload["email"] == "user@example.com"
        assert payload["tier"] == "pro"
        assert "exp" in payload

    def test_create_access_token_expiry(self):
        """create_access_token() sets expiry based on jwt_expire_minutes."""
        settings = MagicMock()
        settings.auth.jwt_secret = "secret"
        settings.auth.jwt_expire_minutes = 60  # 1 hour
        settings.auth.jwt_algorithm = "HS256"
        settings.web.secret_key = "fallback"

        before = time.time()
        token = create_access_token("user1", "u@e.com", "free", settings)
        after = time.time()

        payload = jwt.decode(token, "secret", algorithms=["HS256"])
        exp = payload["exp"]

        # Should expire ~1 hour from now
        assert before + 3600 <= exp <= after + 3600 + 5  # 5s tolerance

    def test_create_access_token_falls_back_to_web_secret(self):
        """create_access_token() uses web.secret_key if jwt_secret is empty."""
        settings = MagicMock()
        settings.auth.jwt_secret = ""  # Empty
        settings.auth.jwt_expire_minutes = 1440
        settings.auth.jwt_algorithm = "HS256"
        settings.web.secret_key = "web_fallback_key"

        token = create_access_token("user1", "u@e.com", "free", settings)

        # Should decode with web.secret_key
        payload = jwt.decode(token, "web_fallback_key", algorithms=["HS256"])
        assert payload["sub"] == "user1"

    def test_create_access_token_invalid_signature(self):
        """JWT with invalid signature raises JWTError."""
        settings = MagicMock()
        settings.auth.jwt_secret = "correct_secret"
        settings.auth.jwt_expire_minutes = 1440
        settings.auth.jwt_algorithm = "HS256"
        settings.web.secret_key = "fallback"

        token = create_access_token("user1", "u@e.com", "free", settings)

        # Try to decode with wrong secret
        from jose import JWTError
        with pytest.raises(JWTError):
            jwt.decode(token, "wrong_secret", algorithms=["HS256"])

    def test_create_access_token_expired(self):
        """Expired JWT raises JWTError."""
        settings = MagicMock()
        settings.auth.jwt_secret = "secret"
        settings.auth.jwt_expire_minutes = -1  # Already expired
        settings.auth.jwt_algorithm = "HS256"
        settings.web.secret_key = "fallback"

        token = create_access_token("user1", "u@e.com", "free", settings)

        from jose import ExpiredSignatureError
        with pytest.raises(ExpiredSignatureError):
            jwt.decode(token, "secret", algorithms=["HS256"])

    def test_jwt_missing_claims(self):
        """JWT without required claims can still be decoded (app layer validates)."""
        settings = MagicMock()
        settings.auth.jwt_secret = "secret"
        settings.auth.jwt_algorithm = "HS256"

        # Manually create JWT without all claims
        payload = {"exp": time.time() + 3600}
        token = jwt.encode(payload, "secret", algorithm="HS256")

        decoded = jwt.decode(token, "secret", algorithms=["HS256"])
        assert decoded.get("sub") is None  # Missing claim


# =========================================================================
# API Key Tests
# =========================================================================


class TestAPIKey:
    """Test API key generation and hashing."""

    def test_generate_api_key_format(self):
        """generate_api_key() creates rot_ prefixed token."""
        api_key = generate_api_key()

        assert api_key.startswith("rot_")
        assert len(api_key) > 10  # rot_ + urlsafe token

    def test_generate_api_key_unique(self):
        """generate_api_key() creates unique keys each time."""
        key1 = generate_api_key()
        key2 = generate_api_key()

        assert key1 != key2

    def test_hash_api_key_sha256(self):
        """hash_api_key() creates SHA-256 hash."""
        api_key = "rot_test_key_12345"
        hashed = hash_api_key(api_key)

        assert isinstance(hashed, str)
        assert len(hashed) == 64  # SHA-256 hex digest
        assert hashed != api_key

    def test_hash_api_key_deterministic(self):
        """hash_api_key() produces same hash for same key."""
        api_key = "rot_same_key"
        hash1 = hash_api_key(api_key)
        hash2 = hash_api_key(api_key)

        assert hash1 == hash2

    def test_hash_api_key_different_for_different_keys(self):
        """hash_api_key() produces different hashes for different keys."""
        key1 = "rot_key1"
        key2 = "rot_key2"

        assert hash_api_key(key1) != hash_api_key(key2)


# =========================================================================
# Admin Elevation Tests
# =========================================================================


class TestAdminElevation:
    """Test _maybe_elevate_admin() function."""

    def test_maybe_elevate_admin_email_matches(self):
        """Admin email elevates tier to 'admin'."""
        from rot.web.auth import _maybe_elevate_admin

        settings = MagicMock()
        settings.auth.get_admin_emails.return_value = ["admin@rot.com", "owner@rot.com"]

        user = {"id": "1", "email": "admin@rot.com", "tier": "free"}
        elevated = _maybe_elevate_admin(user, settings)

        assert elevated["tier"] == "admin"
        assert elevated["email"] == "admin@rot.com"

    def test_maybe_elevate_admin_case_insensitive(self):
        """Admin email matching is case-insensitive."""
        from rot.web.auth import _maybe_elevate_admin

        settings = MagicMock()
        settings.auth.get_admin_emails.return_value = ["ADMIN@ROT.COM"]

        user = {"id": "1", "email": "admin@rot.com", "tier": "pro"}
        elevated = _maybe_elevate_admin(user, settings)

        assert elevated["tier"] == "admin"

    def test_maybe_elevate_admin_non_admin_unchanged(self):
        """Non-admin email keeps original tier."""
        from rot.web.auth import _maybe_elevate_admin

        settings = MagicMock()
        settings.auth.get_admin_emails.return_value = ["admin@rot.com"]

        user = {"id": "2", "email": "user@example.com", "tier": "premium"}
        elevated = _maybe_elevate_admin(user, settings)

        assert elevated["tier"] == "premium"  # Unchanged

    def test_maybe_elevate_admin_empty_list(self):
        """Empty admin emails list doesn't elevate anyone."""
        from rot.web.auth import _maybe_elevate_admin

        settings = MagicMock()
        settings.auth.get_admin_emails.return_value = []

        user = {"id": "1", "email": "user@rot.com", "tier": "ultra"}
        elevated = _maybe_elevate_admin(user, settings)

        assert elevated["tier"] == "ultra"

    def test_maybe_elevate_admin_none_list(self):
        """None admin emails list doesn't elevate."""
        from rot.web.auth import _maybe_elevate_admin

        settings = MagicMock()
        settings.auth.get_admin_emails.return_value = None

        user = {"id": "1", "email": "user@rot.com", "tier": "pro"}
        elevated = _maybe_elevate_admin(user, settings)

        assert elevated["tier"] == "pro"

    def test_maybe_elevate_admin_creates_copy(self):
        """_maybe_elevate_admin() creates copy, doesn't mutate original."""
        from rot.web.auth import _maybe_elevate_admin

        settings = MagicMock()
        settings.auth.get_admin_emails.return_value = ["admin@rot.com"]

        original = {"id": "1", "email": "admin@rot.com", "tier": "free"}
        elevated = _maybe_elevate_admin(original, settings)

        assert elevated["tier"] == "admin"
        assert original["tier"] == "free"  # Original unchanged
        assert elevated is not original


# =========================================================================
# get_current_user_optional Tests
# =========================================================================


class TestGetCurrentUserOptional:
    """Test get_current_user_optional() priority order."""

    @pytest.mark.asyncio
    async def test_bearer_token_priority_1(self):
        """Priority 1: Bearer token validated and returns user."""
        request = Mock(spec=Request)
        request.headers.get = lambda k, d="": "Bearer valid_token" if k == "authorization" else d
        request.cookies.get = lambda k: None

        settings = MagicMock()
        settings.auth.jwt_secret = "secret"
        settings.auth.jwt_algorithm = "HS256"
        settings.web.secret_key = "fallback"
        settings.auth.get_admin_emails.return_value = []

        db = AsyncMock()
        db.get_user_by_id = AsyncMock(return_value={"id": "user1", "email": "u@e.com", "tier": "pro"})

        request.app = MagicMock()
        request.app.state.settings = settings
        request.app.state.db = db

        # Create valid token
        payload = {"sub": "user1", "email": "u@e.com", "tier": "pro", "exp": time.time() + 3600}
        token = jwt.encode(payload, "secret", algorithm="HS256")
        request.headers.get = lambda k, d="": f"Bearer {token}" if k == "authorization" else d

        user = await get_current_user_optional(request)

        assert user is not None
        assert user["id"] == "user1"
        db.get_user_by_id.assert_called_once_with("user1")

    @pytest.mark.asyncio
    async def test_api_key_priority_2(self):
        """Priority 2: API key used if no bearer token."""
        request = Mock(spec=Request)
        request.headers.get = lambda k, d="": "rot_api_key_123" if k == "x-api-key" else d
        request.cookies.get = lambda k: None

        settings = MagicMock()
        settings.auth.jwt_secret = "secret"
        settings.auth.jwt_algorithm = "HS256"
        settings.auth.get_admin_emails.return_value = []

        db = AsyncMock()
        expected_hash = hash_api_key("rot_api_key_123")
        db.get_user_by_api_key_hash = AsyncMock(return_value={"id": "user2", "email": "api@e.com", "tier": "premium"})

        request.app = MagicMock()
        request.app.state.settings = settings
        request.app.state.db = db

        user = await get_current_user_optional(request)

        assert user is not None
        assert user["id"] == "user2"
        db.get_user_by_api_key_hash.assert_called_once_with(expected_hash)

    @pytest.mark.asyncio
    async def test_session_cookie_priority_3(self):
        """Priority 3: Session cookie used if no bearer/api key."""
        settings = MagicMock()
        settings.auth.jwt_secret = "secret"
        settings.auth.jwt_algorithm = "HS256"
        settings.web.secret_key = "fallback"
        settings.auth.get_admin_emails.return_value = []

        db = AsyncMock()
        db.get_user_by_id = AsyncMock(return_value={"id": "user3", "email": "cookie@e.com", "tier": "ultra"})

        # Create valid session token
        payload = {"sub": "user3", "email": "cookie@e.com", "tier": "ultra", "exp": time.time() + 3600}
        session_token = jwt.encode(payload, "secret", algorithm="HS256")

        request = Mock(spec=Request)
        request.headers.get = lambda k, d="": d  # No auth header, no api key
        request.cookies.get = lambda k: session_token if k == "rot_session" else None
        request.app = MagicMock()
        request.app.state.settings = settings
        request.app.state.db = db

        user = await get_current_user_optional(request)

        assert user is not None
        assert user["id"] == "user3"

    @pytest.mark.asyncio
    async def test_anonymous_priority_4(self):
        """Priority 4: Returns None if no auth (anonymous)."""
        request = Mock(spec=Request)
        request.headers.get = lambda k, d="": d
        request.cookies.get = lambda k: None

        settings = MagicMock()
        settings.auth.jwt_secret = "secret"
        settings.auth.jwt_algorithm = "HS256"

        request.app = MagicMock()
        request.app.state.settings = settings
        request.app.state.db = AsyncMock()

        user = await get_current_user_optional(request)

        assert user is None

    @pytest.mark.asyncio
    async def test_invalid_bearer_token_continues(self):
        """Invalid bearer token doesn't raise, continues to next priority."""
        request = Mock(spec=Request)
        request.headers.get = lambda k, d="": "Bearer invalid_token" if k == "authorization" else d
        request.cookies.get = lambda k: None

        settings = MagicMock()
        settings.auth.jwt_secret = "secret"
        settings.auth.jwt_algorithm = "HS256"

        request.app = MagicMock()
        request.app.state.settings = settings
        request.app.state.db = AsyncMock()

        user = await get_current_user_optional(request)

        assert user is None  # Falls through to anonymous

    @pytest.mark.asyncio
    async def test_bearer_token_user_not_found(self):
        """Valid bearer token but user not in DB returns None."""
        settings = MagicMock()
        settings.auth.jwt_secret = "secret"
        settings.auth.jwt_algorithm = "HS256"
        settings.web.secret_key = "fallback"

        db = AsyncMock()
        db.get_user_by_id = AsyncMock(return_value=None)  # User not found

        payload = {"sub": "nonexistent", "exp": time.time() + 3600}
        token = jwt.encode(payload, "secret", algorithm="HS256")

        request = Mock(spec=Request)
        request.headers.get = lambda k, d="": f"Bearer {token}" if k == "authorization" else d
        request.cookies.get = lambda k: None
        request.app = MagicMock()
        request.app.state.settings = settings
        request.app.state.db = db

        user = await get_current_user_optional(request)

        assert user is None


# =========================================================================
# require_user Tests
# =========================================================================


class TestRequireUser:
    """Test require_user() authentication check."""

    @pytest.mark.asyncio
    async def test_require_user_authenticated(self):
        """require_user() returns user if authenticated."""
        with patch("rot.web.auth.get_current_user_optional") as mock_get:
            mock_get.return_value = {"id": "user1", "tier": "pro"}

            request = Mock(spec=Request)
            user = await require_user(request)

            assert user["id"] == "user1"

    @pytest.mark.asyncio
    async def test_require_user_unauthenticated_raises_401(self):
        """require_user() raises 401 if not authenticated."""
        with patch("rot.web.auth.get_current_user_optional") as mock_get:
            mock_get.return_value = None  # Anonymous

            request = Mock(spec=Request)

            with pytest.raises(HTTPException) as exc_info:
                await require_user(request)

            assert exc_info.value.status_code == 401
            assert "Authentication required" in exc_info.value.detail


# =========================================================================
# require_tier Tests
# =========================================================================


class TestRequireTier:
    """Test require_tier() tier checking factory."""

    @pytest.mark.asyncio
    async def test_require_tier_allowed(self):
        """require_tier() passes if user has allowed tier."""
        with patch("rot.web.auth.require_user") as mock_require:
            mock_require.return_value = {"id": "user1", "tier": "premium"}

            check_tier = require_tier("premium", "ultra")
            request = Mock(spec=Request)

            user = await check_tier(request)

            assert user["tier"] == "premium"

    @pytest.mark.asyncio
    async def test_require_tier_multiple_allowed(self):
        """require_tier() accepts any tier in allowed list."""
        with patch("rot.web.auth.require_user") as mock_require:
            mock_require.return_value = {"id": "user1", "tier": "ultra"}

            check_tier = require_tier("pro", "premium", "ultra", "enterprise")
            request = Mock(spec=Request)

            user = await check_tier(request)

            assert user["tier"] == "ultra"

    @pytest.mark.asyncio
    async def test_require_tier_forbidden(self):
        """require_tier() raises 403 if tier not allowed."""
        with patch("rot.web.auth.require_user") as mock_require:
            mock_require.return_value = {"id": "user1", "tier": "free"}

            check_tier = require_tier("premium", "ultra")
            request = Mock(spec=Request)

            with pytest.raises(HTTPException) as exc_info:
                await check_tier(request)

            assert exc_info.value.status_code == 403
            assert "premium or ultra" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_tier_admin_always_passes(self):
        """Admin tier bypasses all tier checks."""
        with patch("rot.web.auth.require_user") as mock_require:
            mock_require.return_value = {"id": "admin1", "tier": "admin"}

            # Check tier that doesn't include admin
            check_tier = require_tier("enterprise")
            request = Mock(spec=Request)

            user = await check_tier(request)

            assert user["tier"] == "admin"  # Admin passes despite not in allowed

    @pytest.mark.asyncio
    async def test_require_tier_admin_bypasses_free_only(self):
        """Admin bypasses even if only 'free' is allowed."""
        with patch("rot.web.auth.require_user") as mock_require:
            mock_require.return_value = {"id": "admin1", "tier": "admin"}

            check_tier = require_tier("free")
            request = Mock(spec=Request)

            user = await check_tier(request)

            assert user["tier"] == "admin"
