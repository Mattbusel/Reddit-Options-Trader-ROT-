"""User service — encapsulates registration, authentication, and profile logic.

Extracts business logic from auth_routes.py into a testable service
class with custom exception types.
"""
from __future__ import annotations

import logging
import re

from rot.web.auth import hash_password, verify_password

log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class UserAlreadyExistsError(Exception):
    """Raised when registering with an email that already exists."""


class InvalidCredentialsError(Exception):
    """Raised when login credentials are incorrect."""


class InvalidEmailError(Exception):
    """Raised when email format is invalid."""


class WeakPasswordError(Exception):
    """Raised when password does not meet minimum requirements."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class UserService:
    """Business logic for user management."""

    def __init__(self, db) -> None:
        self._db = db

    async def register(self, email: str, password: str) -> dict:
        """Create a new user account.

        Returns:
            The created user dict.

        Raises:
            InvalidEmailError: Email format is invalid.
            WeakPasswordError: Password is too short.
            UserAlreadyExistsError: Email already registered.
        """
        email = email.lower().strip()

        if not _EMAIL_RE.match(email):
            raise InvalidEmailError("Invalid email format")
        if len(password) < 8:
            raise WeakPasswordError(
                "Password must be at least 8 characters"
            )

        existing = await self._db.get_user_by_email(email)
        if existing:
            raise UserAlreadyExistsError("Email already registered")

        pw_hash = hash_password(password)
        user = await self._db.create_user(email, pw_hash)
        return user

    async def authenticate(self, email: str, password: str) -> dict:
        """Verify credentials and return the user.

        Returns:
            The user dict on success.

        Raises:
            InvalidCredentialsError: Email not found or password wrong.
        """
        email = email.lower().strip()
        user = await self._db.get_user_by_email(email)

        if not user or not user.get("password_hash"):
            raise InvalidCredentialsError("Invalid email or password")
        if not verify_password(password, user["password_hash"]):
            raise InvalidCredentialsError("Invalid email or password")

        return user

    async def get_user_by_id(self, user_id: str) -> dict | None:
        """Fetch a user by ID."""
        return await self._db.get_user_by_id(user_id)

    async def get_subscription(self, user_id: str) -> dict | None:
        """Fetch a user's subscription data."""
        return await self._db.get_subscription(user_id)

    async def update_password(self, user_id: str, new_password: str) -> None:
        """Hash and update a user's password.

        Raises:
            WeakPasswordError: New password is too short.
        """
        if len(new_password) < 8:
            raise WeakPasswordError(
                "Password must be at least 8 characters"
            )
        pw_hash = hash_password(new_password)
        await self._db.update_user_password(user_id, pw_hash)
