"""Async-aware in-memory TTL cache for dashboard queries.

Designed for aggregate/statistical queries that change slowly (trending
tickers, accuracy stats, leaderboards, heatmaps).  NOT for user-specific
or filtered queries.

Features:
- Per-key TTL with configurable defaults
- Thundering-herd prevention via per-key asyncio.Lock
- Prefix-based invalidation (e.g. invalidate("trending_") clears all trending keys)
- Signal-triggered invalidation for fast-changing data
- Hit/miss/refresh stats for monitoring
- Exception-safe: failed fetches are not cached
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Union

log = logging.getLogger(__name__)

# Type alias for async fetcher callables
Fetcher = Callable[[], Awaitable[Any]]


@dataclass
class CacheEntry:
    """Single cached value with TTL metadata."""

    value: Any
    expires_at: float  # time.time() + ttl
    created_at: float


class QueryCache:
    """Async-aware in-memory TTL cache for dashboard queries.

    Usage::

        cache = QueryCache(default_ttl=60)
        result = await cache.get_or_fetch(
            "trending_24_10",
            lambda: db.get_trending_tickers(hours=24, limit=10),
            ttl=30,
        )
    """

    def __init__(self, default_ttl: int = 60) -> None:
        self._store: Dict[str, CacheEntry] = {}
        self._default_ttl = default_ttl
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._stats = {"hits": 0, "misses": 0, "refreshes": 0}

    async def _get_lock(self, key: str) -> asyncio.Lock:
        """Get or create a per-key lock (prevents thundering herd)."""
        if key not in self._locks:
            async with self._global_lock:
                # Double-check after acquiring global lock
                if key not in self._locks:
                    self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Fetcher,
        ttl: Optional[int] = None,
    ) -> Any:
        """Return cached value if fresh, otherwise call fetcher and cache result.

        Args:
            key: Cache key string.
            fetcher: Async callable that returns the value to cache.
            ttl: Time-to-live in seconds. Defaults to instance default_ttl.

        Returns:
            The cached or freshly-fetched value.

        If the fetcher raises an exception, the error propagates and nothing
        is cached — the next call will retry.
        """
        now = time.time()
        entry = self._store.get(key)

        # Cache hit: return immediately
        if entry is not None and entry.expires_at > now:
            self._stats["hits"] += 1
            return entry.value

        # Cache miss or stale — acquire per-key lock to prevent thundering herd
        lock = await self._get_lock(key)
        async with lock:
            # Double-check: another coroutine may have refreshed while we waited
            entry = self._store.get(key)
            if entry is not None and entry.expires_at > now:
                self._stats["hits"] += 1
                return entry.value

            # Fetch fresh data
            self._stats["misses"] += 1
            try:
                value = await fetcher()
            except Exception:
                # Don't cache failures — let the next call retry
                log.warning("QueryCache fetch failed for key=%s", key, exc_info=True)
                raise

            ttl_s = ttl if ttl is not None else self._default_ttl
            self._store[key] = CacheEntry(
                value=value,
                expires_at=now + ttl_s,
                created_at=now,
            )
            self._stats["refreshes"] += 1
            return value

    def invalidate(self, prefix: Optional[str] = None) -> int:
        """Invalidate cache entries.

        Args:
            prefix: If given, invalidate all keys starting with this prefix.
                    If None, invalidate ALL entries.

        Returns:
            Number of entries invalidated.
        """
        if prefix is None:
            count = len(self._store)
            self._store.clear()
            return count

        to_remove = [k for k in self._store if k.startswith(prefix)]
        for k in to_remove:
            del self._store[k]
        return len(to_remove)

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics for monitoring."""
        return {
            **self._stats,
            "entries": len(self._store),
            "keys": list(self._store.keys()),
        }

    def __len__(self) -> int:
        return len(self._store)
