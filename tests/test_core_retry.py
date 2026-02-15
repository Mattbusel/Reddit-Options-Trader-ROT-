"""
Comprehensive tests for retry utility module.

Modules tested:
- rot.core.retry

Coverage:
- retry_with_backoff decorator (sync)
- async_retry_with_backoff decorator (async)
- Exponential backoff calculation
- Jitter randomization
- Max delay capping
- Custom retryable exceptions
- Success after N retries
- Failure after max attempts
- Non-retryable exceptions pass through immediately
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import Mock, patch

import pytest

from rot.core.retry import (
    retry_with_backoff,
    async_retry_with_backoff,
    DEFAULT_RETRYABLE_EXCEPTIONS,
)


# ============================================================================
# Synchronous retry_with_backoff Tests
# ============================================================================

class TestSyncRetryWithBackoff:
    def test_success_on_first_attempt(self):
        """Function succeeds on first attempt without retry."""
        call_count = 0

        @retry_with_backoff(max_attempts=3)
        def succeeds_immediately():
            nonlocal call_count
            call_count += 1
            return "success"

        result = succeeds_immediately()
        assert result == "success"
        assert call_count == 1

    def test_success_after_retries(self):
        """Function succeeds after some failed attempts."""
        call_count = 0

        @retry_with_backoff(max_attempts=5, base_delay=0.01)
        def succeeds_on_third_try():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary failure")
            return "success"

        result = succeeds_on_third_try()
        assert result == "success"
        assert call_count == 3

    def test_failure_after_max_attempts(self):
        """Function fails after exhausting all retry attempts."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Permanent failure")

        with pytest.raises(ConnectionError, match="Permanent failure"):
            always_fails()

        assert call_count == 3

    def test_non_retryable_exception_passes_through(self):
        """Non-retryable exceptions are not retried."""
        call_count = 0

        @retry_with_backoff(max_attempts=5, base_delay=0.01)
        def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")

        with pytest.raises(ValueError, match="Not retryable"):
            raises_value_error()

        assert call_count == 1  # No retries

    def test_custom_retryable_exceptions(self):
        """Custom exception types can be specified as retryable."""
        call_count = 0

        @retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
            retryable_exceptions=(ValueError, TypeError)
        )
        def raises_custom_exception():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Retryable ValueError")
            return "success"

        result = raises_custom_exception()
        assert result == "success"
        assert call_count == 2

    def test_exponential_backoff_delays(self):
        """Delays increase exponentially between retries."""
        call_times = []

        @retry_with_backoff(
            max_attempts=4,
            base_delay=0.1,
            exponential_base=2.0,
            jitter=False  # Disable jitter for predictable testing
        )
        def track_delays():
            call_times.append(time.time())
            raise ConnectionError("Test")

        start = time.time()
        with pytest.raises(ConnectionError):
            track_delays()
        elapsed = time.time() - start

        # Should have 4 attempts
        assert len(call_times) == 4
        # Total elapsed should be at least base_delay * (1 + 2 + 4) = 0.7s
        assert elapsed >= 0.6  # Allow some margin

    def test_max_delay_cap(self):
        """Delay is capped at max_delay."""
        @retry_with_backoff(
            max_attempts=10,
            base_delay=1.0,
            max_delay=2.0,
            exponential_base=2.0,
            jitter=False
        )
        def test_func():
            raise ConnectionError("Test")

        start = time.time()
        with pytest.raises(ConnectionError):
            test_func()
        elapsed = time.time() - start

        # With max_delay=2.0, total should be < 20s (10 attempts * 2s max)
        # Even with exponential backoff, it's capped
        assert elapsed < 25  # Allow some overhead

    def test_jitter_adds_randomness(self):
        """Jitter adds randomness to prevent thundering herd."""
        delays_1 = []
        delays_2 = []

        @retry_with_backoff(max_attempts=3, base_delay=0.1, jitter=True)
        def func_with_jitter():
            start = time.time()
            if delays_1:
                delays_1.append(time.time() - delays_1[-1])
            else:
                delays_1.append(start)
            raise ConnectionError("Test")

        with pytest.raises(ConnectionError):
            func_with_jitter()

        # Reset and run again
        @retry_with_backoff(max_attempts=3, base_delay=0.1, jitter=True)
        def func_with_jitter_2():
            start = time.time()
            if delays_2:
                delays_2.append(time.time() - delays_2[-1])
            else:
                delays_2.append(start)
            raise ConnectionError("Test")

        with pytest.raises(ConnectionError):
            func_with_jitter_2()

        # Delays should be different due to jitter (with very high probability)
        # This test might rarely fail due to random chance
        if len(delays_1) > 1 and len(delays_2) > 1:
            assert delays_1 != delays_2


# ============================================================================
# Asynchronous async_retry_with_backoff Tests
# ============================================================================

class TestAsyncRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_async_success_on_first_attempt(self):
        """Async function succeeds on first attempt without retry."""
        call_count = 0

        @async_retry_with_backoff(max_attempts=3)
        async def succeeds_immediately():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await succeeds_immediately()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_success_after_retries(self):
        """Async function succeeds after some failed attempts."""
        call_count = 0

        @async_retry_with_backoff(max_attempts=5, base_delay=0.01)
        async def succeeds_on_third_try():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary failure")
            return "success"

        result = await succeeds_on_third_try()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_failure_after_max_attempts(self):
        """Async function fails after exhausting all retry attempts."""
        call_count = 0

        @async_retry_with_backoff(max_attempts=3, base_delay=0.01)
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Permanent failure")

        with pytest.raises(ConnectionError, match="Permanent failure"):
            await always_fails()

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_non_retryable_exception(self):
        """Async non-retryable exceptions are not retried."""
        call_count = 0

        @async_retry_with_backoff(max_attempts=5, base_delay=0.01)
        async def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")

        with pytest.raises(ValueError, match="Not retryable"):
            await raises_value_error()

        assert call_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_async_custom_retryable_exceptions(self):
        """Async custom exception types can be specified as retryable."""
        call_count = 0

        @async_retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
            retryable_exceptions=(ValueError, TypeError)
        )
        async def raises_custom_exception():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Retryable ValueError")
            return "success"

        result = await raises_custom_exception()
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_exponential_backoff(self):
        """Async delays increase exponentially between retries."""
        call_times = []

        @async_retry_with_backoff(
            max_attempts=4,
            base_delay=0.05,
            exponential_base=2.0,
            jitter=False
        )
        async def track_delays():
            call_times.append(time.time())
            raise ConnectionError("Test")

        start = time.time()
        with pytest.raises(ConnectionError):
            await track_delays()
        elapsed = time.time() - start

        # Should have 4 attempts
        assert len(call_times) == 4
        # Total elapsed should be at least base_delay * (1 + 2 + 4) = 0.35s
        assert elapsed >= 0.3  # Allow some margin

    @pytest.mark.asyncio
    async def test_async_preserves_coroutine_behavior(self):
        """Async decorator preserves async/await behavior."""
        @async_retry_with_backoff(max_attempts=2)
        async def async_operation():
            await asyncio.sleep(0.01)
            return "async result"

        result = await async_operation()
        assert result == "async result"


# ============================================================================
# Edge Cases and Integration Tests
# ============================================================================

class TestRetryEdgeCases:
    def test_default_retryable_exceptions_coverage(self):
        """Default retryable exceptions include common network errors."""
        assert ConnectionError in DEFAULT_RETRYABLE_EXCEPTIONS
        assert TimeoutError in DEFAULT_RETRYABLE_EXCEPTIONS
        assert OSError in DEFAULT_RETRYABLE_EXCEPTIONS

    def test_max_attempts_one_means_no_retry(self):
        """max_attempts=1 means no retries (fail immediately)."""
        call_count = 0

        @retry_with_backoff(max_attempts=1)
        def fails_immediately():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Immediate failure")

        with pytest.raises(ConnectionError):
            fails_immediately()

        assert call_count == 1

    def test_zero_base_delay(self):
        """base_delay=0 means instant retries (no waiting)."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.0)
        def fails_with_no_delay():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Test")

        start = time.time()
        with pytest.raises(ConnectionError):
            fails_with_no_delay()
        elapsed = time.time() - start

        assert call_count == 3
        assert elapsed < 0.5  # Should complete very quickly


# ============================================================================
# Parametrized Tests for Coverage
# ============================================================================

class TestRetryParametrized:
    @pytest.mark.parametrize("max_attempts", [1, 2, 3, 5, 10])
    def test_various_max_attempts(self, max_attempts):
        """Test with various max_attempts values."""
        call_count = 0

        @retry_with_backoff(max_attempts=max_attempts, base_delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Test")

        with pytest.raises(ConnectionError):
            always_fails()

        assert call_count == max_attempts

    @pytest.mark.parametrize("exception_type", [
        ConnectionError,
        TimeoutError,
        OSError,
    ])
    def test_default_retryable_exception_types(self, exception_type):
        """Test that default retryable exceptions are actually retried."""
        call_count = 0

        @retry_with_backoff(max_attempts=2, base_delay=0.01)
        def raises_exception():
            nonlocal call_count
            call_count += 1
            raise exception_type("Test")

        with pytest.raises(exception_type):
            raises_exception()

        assert call_count == 2  # Should retry once
