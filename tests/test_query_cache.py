"""Tests for the dashboard query cache engine."""

from __future__ import annotations

import asyncio
import time

import pytest

from rot.web.query_cache import QueryCache


@pytest.fixture
def cache():
    return QueryCache(default_ttl=5)


class TestQueryCacheBasics:
    @pytest.mark.asyncio
    async def test_first_call_fetches(self, cache):
        """First call should invoke the fetcher and return the result."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return {"data": 42}

        result = await cache.get_or_fetch("test_key", fetcher)
        assert result == {"data": 42}
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_second_call_returns_cached(self, cache):
        """Second call within TTL should return cached value, not re-fetch."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return [1, 2, 3]

        r1 = await cache.get_or_fetch("key", fetcher)
        r2 = await cache.get_or_fetch("key", fetcher)
        assert r1 == r2
        assert call_count == 1  # Only fetched once

    @pytest.mark.asyncio
    async def test_ttl_expiry_refetches(self, cache):
        """After TTL expires, the fetcher should be called again."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return call_count

        r1 = await cache.get_or_fetch("key", fetcher, ttl=0)  # Expires immediately
        # Entry is created with expires_at = now + 0 = already expired
        r2 = await cache.get_or_fetch("key", fetcher, ttl=0)
        assert call_count == 2  # Fetched twice

    @pytest.mark.asyncio
    async def test_per_key_ttl_overrides_default(self, cache):
        """Per-key TTL should override the default TTL."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return "val"

        # TTL=100 → should not expire during this test
        await cache.get_or_fetch("long_ttl", fetcher, ttl=100)
        await cache.get_or_fetch("long_ttl", fetcher, ttl=100)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_different_keys_independent(self, cache):
        """Different keys should be cached independently."""
        async def fetcher_a():
            return "A"

        async def fetcher_b():
            return "B"

        a = await cache.get_or_fetch("key_a", fetcher_a)
        b = await cache.get_or_fetch("key_b", fetcher_b)
        assert a == "A"
        assert b == "B"
        assert len(cache) == 2


class TestQueryCacheInvalidation:
    @pytest.mark.asyncio
    async def test_invalidate_single_key(self, cache):
        """Invalidating a specific key should cause re-fetch on next call."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return call_count

        await cache.get_or_fetch("key", fetcher, ttl=300)
        assert call_count == 1

        cache.invalidate("key")
        r2 = await cache.get_or_fetch("key", fetcher, ttl=300)
        assert call_count == 2
        assert r2 == 2

    @pytest.mark.asyncio
    async def test_invalidate_by_prefix(self, cache):
        """Invalidating by prefix should clear all matching keys."""
        async def fetcher():
            return "v"

        await cache.get_or_fetch("trending_24_10", fetcher, ttl=300)
        await cache.get_or_fetch("trending_48_20", fetcher, ttl=300)
        await cache.get_or_fetch("accuracy_30", fetcher, ttl=300)
        assert len(cache) == 3

        count = cache.invalidate("trending_")
        assert count == 2
        assert len(cache) == 1  # Only accuracy remains

    @pytest.mark.asyncio
    async def test_invalidate_all(self, cache):
        """Invalidating with no prefix should clear everything."""
        async def fetcher():
            return "v"

        await cache.get_or_fetch("a", fetcher, ttl=300)
        await cache.get_or_fetch("b", fetcher, ttl=300)
        await cache.get_or_fetch("c", fetcher, ttl=300)

        count = cache.invalidate()
        assert count == 3
        assert len(cache) == 0

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_prefix(self, cache):
        """Invalidating a non-matching prefix should not affect anything."""
        async def fetcher():
            return "v"

        await cache.get_or_fetch("key", fetcher, ttl=300)
        count = cache.invalidate("nonexistent_")
        assert count == 0
        assert len(cache) == 1


class TestQueryCacheThunderingHerd:
    @pytest.mark.asyncio
    async def test_concurrent_calls_only_one_fetch(self, cache):
        """Multiple concurrent get_or_fetch calls should only trigger one fetch."""
        call_count = 0

        async def slow_fetcher():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)  # Simulate slow DB query
            return {"result": call_count}

        # Launch 10 concurrent requests for the same key
        tasks = [cache.get_or_fetch("key", slow_fetcher, ttl=300) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # All should get the same result, and fetcher called only once
        assert call_count == 1
        for r in results:
            assert r == {"result": 1}


class TestQueryCacheEdgeCases:
    @pytest.mark.asyncio
    async def test_none_result_is_cached(self, cache):
        """None return values should be cached (not treated as miss)."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return None

        r1 = await cache.get_or_fetch("key", fetcher)
        r2 = await cache.get_or_fetch("key", fetcher)
        assert r1 is None
        assert r2 is None
        assert call_count == 1  # Only one fetch

    @pytest.mark.asyncio
    async def test_empty_list_is_cached(self, cache):
        """Empty list return values should be cached."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return []

        await cache.get_or_fetch("key", fetcher)
        await cache.get_or_fetch("key", fetcher)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exception_not_cached(self, cache):
        """If fetcher raises, the error should propagate and nothing cached."""
        call_count = 0

        async def failing_fetcher():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("DB error")
            return "recovered"

        # First call raises
        with pytest.raises(ValueError, match="DB error"):
            await cache.get_or_fetch("key", failing_fetcher)

        # Second call should retry (not return cached error)
        result = await cache.get_or_fetch("key", failing_fetcher)
        assert result == "recovered"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_confidence_floor(self, cache):
        """Cache should not grow unbounded — entries are evicted by TTL."""
        async def fetcher():
            return "v"

        for i in range(100):
            await cache.get_or_fetch(f"key_{i}", fetcher, ttl=300)
        assert len(cache) == 100

        cache.invalidate()
        assert len(cache) == 0


class TestQueryCacheStats:
    @pytest.mark.asyncio
    async def test_stats_tracking(self, cache):
        """Stats should correctly track hits, misses, and refreshes."""
        async def fetcher():
            return "v"

        await cache.get_or_fetch("key", fetcher, ttl=300)
        await cache.get_or_fetch("key", fetcher, ttl=300)
        await cache.get_or_fetch("key", fetcher, ttl=300)
        await cache.get_or_fetch("other", fetcher, ttl=300)

        stats = cache.stats()
        assert stats["misses"] == 2   # key (first) + other (first)
        assert stats["hits"] == 2     # key (second) + key (third)
        assert stats["refreshes"] == 2
        assert stats["entries"] == 2
        assert set(stats["keys"]) == {"key", "other"}
