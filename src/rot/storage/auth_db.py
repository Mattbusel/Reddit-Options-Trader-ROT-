"""
Auth rate limiting database operations.

This module provides database-backed auth rate limiting for brute-force protection.
Replaces in-memory storage to support multi-instance deployments (Railway).

Methods:
    - record_auth_attempt: Record an auth attempt
    - get_auth_attempts: Get attempts for an IP+endpoint within a time window
    - cleanup_old_auth_attempts: Clean up attempts older than 1 hour
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


class AuthMixin:
    """Database operations for auth rate limiting."""

    async def record_auth_attempt(
        self,
        ip_address: str,
        endpoint: str,
    ) -> None:
        """Record an auth attempt for rate limiting.

        Args:
            ip_address: Client IP address
            endpoint: Auth endpoint (login, register, api-key)
        """
        if not self._db:
            raise RuntimeError("Database not connected")

        now = time.time()

        await self._db.execute(
            """
            INSERT INTO auth_attempts (ip_address, endpoint, attempted_at)
            VALUES (?, ?, ?)
            """,
            (ip_address, endpoint, now),
        )
        await self._db.commit()

        log.debug(f"Recorded auth attempt: ip={ip_address}, endpoint={endpoint}")

    async def get_auth_attempts(
        self,
        ip_address: str,
        endpoint: str,
        since: float,
    ) -> int:
        """Get count of auth attempts for an IP+endpoint within a time window.

        Args:
            ip_address: Client IP address
            endpoint: Auth endpoint (login, register, api-key)
            since: Unix timestamp to count attempts since

        Returns:
            Number of attempts within the time window
        """
        if not self._db:
            raise RuntimeError("Database not connected")

        cursor = await self._db.execute(
            """
            SELECT COUNT(*) as count
            FROM auth_attempts
            WHERE ip_address = ? AND endpoint = ? AND attempted_at >= ?
            """,
            (ip_address, endpoint, since),
        )
        row = await cursor.fetchone()
        return row["count"] if row else 0

    async def cleanup_old_auth_attempts(self, older_than_seconds: int = 3600) -> int:
        """Clean up auth attempts older than specified time.

        Args:
            older_than_seconds: Remove attempts older than this (default: 1 hour)

        Returns:
            Number of rows deleted
        """
        if not self._db:
            raise RuntimeError("Database not connected")

        cutoff = time.time() - older_than_seconds

        cursor = await self._db.execute(
            """
            DELETE FROM auth_attempts
            WHERE attempted_at < ?
            """,
            (cutoff,),
        )
        await self._db.commit()

        deleted = cursor.rowcount
        if deleted > 0:
            log.info(f"Cleaned up {deleted} old auth attempts (older than {older_than_seconds}s)")

        return deleted
