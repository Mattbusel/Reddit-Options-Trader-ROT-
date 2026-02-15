"""Unit tests for UserService.

Tests registration, authentication, and password management with mock DB.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-user-service-tests!!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.services.user_service import (
    InvalidCredentialsError,
    InvalidEmailError,
    UserAlreadyExistsError,
    UserService,
    WeakPasswordError,
)
from rot.web.auth import hash_password


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_user_by_email = AsyncMock(return_value=None)
    db.create_user = AsyncMock(return_value={
        "id": "u1", "email": "test@example.com", "tier": "free"
    })
    db.get_user_by_id = AsyncMock(return_value=None)
    db.get_subscription = AsyncMock(return_value=None)
    db.update_user_password = AsyncMock()
    return db


@pytest.fixture
def svc(mock_db):
    return UserService(db=mock_db)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

class TestRegister:
    @pytest.mark.asyncio
    async def test_success(self, svc, mock_db):
        """Registers a new user with valid email and password."""
        mock_db.get_user_by_email = AsyncMock(return_value=None)
        mock_db.create_user = AsyncMock(return_value={
            "id": "u1", "email": "new@example.com", "tier": "free"
        })
        result = await svc.register("New@Example.com", "StrongPass123!")
        assert result["email"] == "new@example.com"
        mock_db.create_user.assert_called_once()
        # Verify email was lowercased
        call_args = mock_db.create_user.call_args
        assert call_args[0][0] == "new@example.com"

    @pytest.mark.asyncio
    async def test_invalid_email_no_at(self, svc):
        """Raises InvalidEmailError for emails missing @."""
        with pytest.raises(InvalidEmailError):
            await svc.register("notanemail", "StrongPass123!")

    @pytest.mark.asyncio
    async def test_invalid_email_no_domain(self, svc):
        """Raises InvalidEmailError for emails missing domain."""
        with pytest.raises(InvalidEmailError):
            await svc.register("user@", "StrongPass123!")

    @pytest.mark.asyncio
    async def test_invalid_email_empty(self, svc):
        """Raises InvalidEmailError for empty string."""
        with pytest.raises(InvalidEmailError):
            await svc.register("", "StrongPass123!")

    @pytest.mark.asyncio
    async def test_weak_password_short(self, svc):
        """Raises WeakPasswordError for passwords under 8 chars."""
        with pytest.raises(WeakPasswordError):
            await svc.register("valid@example.com", "short")

    @pytest.mark.asyncio
    async def test_weak_password_seven_chars(self, svc):
        """Raises WeakPasswordError for exactly 7 characters."""
        with pytest.raises(WeakPasswordError):
            await svc.register("valid@example.com", "1234567")

    @pytest.mark.asyncio
    async def test_password_exactly_eight_chars_ok(self, svc, mock_db):
        """Accepts password with exactly 8 characters."""
        mock_db.get_user_by_email = AsyncMock(return_value=None)
        mock_db.create_user = AsyncMock(return_value={
            "id": "u1", "email": "x@y.com", "tier": "free"
        })
        result = await svc.register("x@y.com", "12345678")
        assert result["id"] == "u1"

    @pytest.mark.asyncio
    async def test_duplicate_email(self, svc, mock_db):
        """Raises UserAlreadyExistsError for existing email."""
        mock_db.get_user_by_email = AsyncMock(return_value={
            "id": "existing", "email": "taken@example.com"
        })
        with pytest.raises(UserAlreadyExistsError):
            await svc.register("taken@example.com", "StrongPass123!")

    @pytest.mark.asyncio
    async def test_email_normalized_to_lowercase(self, svc, mock_db):
        """Email is lowercased before lookup and creation."""
        mock_db.get_user_by_email = AsyncMock(return_value=None)
        mock_db.create_user = AsyncMock(return_value={
            "id": "u1", "email": "upper@test.com", "tier": "free"
        })
        await svc.register("UPPER@TEST.COM", "ValidPass123!")
        mock_db.get_user_by_email.assert_called_once_with("upper@test.com")

    @pytest.mark.asyncio
    async def test_email_stripped_of_whitespace(self, svc, mock_db):
        """Email is stripped of whitespace."""
        mock_db.get_user_by_email = AsyncMock(return_value=None)
        mock_db.create_user = AsyncMock(return_value={
            "id": "u1", "email": "trimmed@test.com", "tier": "free"
        })
        await svc.register("  trimmed@test.com  ", "ValidPass123!")
        mock_db.get_user_by_email.assert_called_once_with("trimmed@test.com")


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------

class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_success(self, svc, mock_db):
        """Authenticates with correct credentials."""
        pw_hash = hash_password("CorrectPass123!")
        mock_db.get_user_by_email = AsyncMock(return_value={
            "id": "u1", "email": "user@test.com", "password_hash": pw_hash,
        })
        result = await svc.authenticate("user@test.com", "CorrectPass123!")
        assert result["id"] == "u1"

    @pytest.mark.asyncio
    async def test_wrong_password(self, svc, mock_db):
        """Raises InvalidCredentialsError for wrong password."""
        pw_hash = hash_password("CorrectPass123!")
        mock_db.get_user_by_email = AsyncMock(return_value={
            "id": "u1", "email": "user@test.com", "password_hash": pw_hash,
        })
        with pytest.raises(InvalidCredentialsError):
            await svc.authenticate("user@test.com", "WrongPass!")

    @pytest.mark.asyncio
    async def test_user_not_found(self, svc, mock_db):
        """Raises InvalidCredentialsError when user doesn't exist."""
        mock_db.get_user_by_email = AsyncMock(return_value=None)
        with pytest.raises(InvalidCredentialsError):
            await svc.authenticate("nobody@test.com", "SomePass123!")

    @pytest.mark.asyncio
    async def test_user_no_password_hash(self, svc, mock_db):
        """Raises InvalidCredentialsError when user has no password_hash."""
        mock_db.get_user_by_email = AsyncMock(return_value={
            "id": "u1", "email": "user@test.com", "password_hash": None,
        })
        with pytest.raises(InvalidCredentialsError):
            await svc.authenticate("user@test.com", "SomePass123!")

    @pytest.mark.asyncio
    async def test_email_normalized(self, svc, mock_db):
        """Email is lowercased before lookup."""
        pw_hash = hash_password("Pass123!")
        mock_db.get_user_by_email = AsyncMock(return_value={
            "id": "u1", "email": "user@test.com", "password_hash": pw_hash,
        })
        await svc.authenticate("USER@TEST.COM", "Pass123!")
        mock_db.get_user_by_email.assert_called_once_with("user@test.com")


# ---------------------------------------------------------------------------
# get_user_by_id
# ---------------------------------------------------------------------------

class TestGetUserById:
    @pytest.mark.asyncio
    async def test_returns_user(self, svc, mock_db):
        """Returns user dict by ID."""
        mock_db.get_user_by_id = AsyncMock(return_value={"id": "u1"})
        result = await svc.get_user_by_id("u1")
        assert result["id"] == "u1"

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, svc, mock_db):
        """Returns None when user not found."""
        mock_db.get_user_by_id = AsyncMock(return_value=None)
        result = await svc.get_user_by_id("missing")
        assert result is None


# ---------------------------------------------------------------------------
# get_subscription
# ---------------------------------------------------------------------------

class TestGetSubscription:
    @pytest.mark.asyncio
    async def test_returns_subscription(self, svc, mock_db):
        """Returns subscription dict."""
        mock_db.get_subscription = AsyncMock(return_value={"status": "active"})
        result = await svc.get_subscription("u1")
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_subscription(self, svc, mock_db):
        """Returns None when no subscription."""
        mock_db.get_subscription = AsyncMock(return_value=None)
        result = await svc.get_subscription("u1")
        assert result is None


# ---------------------------------------------------------------------------
# update_password
# ---------------------------------------------------------------------------

class TestUpdatePassword:
    @pytest.mark.asyncio
    async def test_success(self, svc, mock_db):
        """Updates password hash in DB."""
        await svc.update_password("u1", "NewStrongPass123!")
        mock_db.update_user_password.assert_called_once()
        # Verify the hash was passed (not plaintext)
        call_args = mock_db.update_user_password.call_args
        assert call_args[0][0] == "u1"
        assert call_args[0][1] != "NewStrongPass123!"  # should be hashed

    @pytest.mark.asyncio
    async def test_weak_password(self, svc):
        """Raises WeakPasswordError for short passwords."""
        with pytest.raises(WeakPasswordError):
            await svc.update_password("u1", "short")

    @pytest.mark.asyncio
    async def test_exactly_eight_chars_ok(self, svc, mock_db):
        """Accepts password with exactly 8 characters."""
        await svc.update_password("u1", "12345678")
        mock_db.update_user_password.assert_called_once()
