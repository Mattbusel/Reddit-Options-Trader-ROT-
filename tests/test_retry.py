"""Tests for retry logic with exponential backoff.

Tests both synchronous and asynchronous retry decorators with:
- Successful operations
- Transient failures with eventual success
- Permanent failures that exhaust retries
- Exponential backoff timing
- Custom retry configuration
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import Mock, AsyncMock

import pytest

from rot.core.retry import retry_with_backoff, async_retry_with_backoff


class TestSyncRetry:
    """Tests for synchronous retry_with_backoff decorator."""

    def test_successful_first_attempt(self):
        """Test that successful operations don't retry."""
        mock_func = Mock(return_value="success")
        decorated = retry_with_backoff(max_attempts=3)(mock_func)

        result = decorated("arg1", kwarg1="value1")

        assert result == "success"
        assert mock_func.call_count == 1
        mock_func.assert_called_once_with("arg1", kwarg1="value1")

    def test_transient_failure_then_success(self):
        """Test that transient failures trigger retry and eventually succeed."""
        mock_func = Mock(side_effect=[
            ConnectionError("Network error"),
            ConnectionError("Network error"),
            "success"
        ])
        decorated = retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,  # Fast for testing
            jitter=False,  # Disable jitter for predictable timing
        )(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 3

    def test_permanent_failure_exhausts_retries(self):
        """Test that permanent failures exhaust all retries and raise."""
        mock_func = Mock(side_effect=ConnectionError("Permanent network error"))
        decorated = retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
        )(mock_func)

        with pytest.raises(ConnectionError, match="Permanent network error"):
            decorated()

        assert mock_func.call_count == 3

    def test_non_retryable_exception_not_retried(self):
        """Test that non-retryable exceptions fail immediately."""
        mock_func = Mock(side_effect=ValueError("Invalid input"))
        decorated = retry_with_backoff(
            max_attempts=3,
            retryable_exceptions=(ConnectionError, TimeoutError),
        )(mock_func)

        with pytest.raises(ValueError, match="Invalid input"):
            decorated()

        # Should not retry on ValueError
        assert mock_func.call_count == 1

    def test_exponential_backoff_timing(self):
        """Test that exponential backoff delays increase correctly."""
        call_times = []

        def failing_func():
            call_times.append(time.time())
            raise ConnectionError("Network error")

        decorated = retry_with_backoff(
            max_attempts=3,
            base_delay=0.1,
            exponential_base=2.0,
            jitter=False,  # Disable jitter for predictable timing
        )(failing_func)

        with pytest.raises(ConnectionError):
            decorated()

        # Calculate delays between calls
        delays = [call_times[i+1] - call_times[i] for i in range(len(call_times) - 1)]

        # First delay: 0.1s, Second delay: 0.2s
        # Allow 50ms tolerance for timing precision
        assert 0.08 <= delays[0] <= 0.15, f"First delay: {delays[0]}"
        assert 0.18 <= delays[1] <= 0.25, f"Second delay: {delays[1]}"

    def test_max_delay_cap(self):
        """Test that delays are capped at max_delay."""
        call_times = []

        def failing_func():
            call_times.append(time.time())
            raise TimeoutError("Timeout")

        decorated = retry_with_backoff(
            max_attempts=4,
            base_delay=1.0,
            max_delay=0.2,  # Cap at 0.2s
            exponential_base=2.0,
            jitter=False,
        )(failing_func)

        with pytest.raises(TimeoutError):
            decorated()

        # All delays should be capped at max_delay (0.2s)
        delays = [call_times[i+1] - call_times[i] for i in range(len(call_times) - 1)]
        for delay in delays:
            assert delay <= 0.25, f"Delay exceeded max: {delay}"

    def test_custom_retryable_exceptions(self):
        """Test custom exception list for retries."""
        class CustomError(Exception):
            pass

        mock_func = Mock(side_effect=[CustomError("Custom"), "success"])
        decorated = retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
            retryable_exceptions=(CustomError,),
        )(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 2


class TestAsyncRetry:
    """Tests for asynchronous async_retry_with_backoff decorator."""

    @pytest.mark.asyncio
    async def test_successful_first_attempt(self):
        """Test that successful async operations don't retry."""
        mock_func = AsyncMock(return_value="async_success")
        decorated = async_retry_with_backoff(max_attempts=3)(mock_func)

        result = await decorated("arg1", kwarg1="value1")

        assert result == "async_success"
        assert mock_func.call_count == 1
        mock_func.assert_called_once_with("arg1", kwarg1="value1")

    @pytest.mark.asyncio
    async def test_transient_failure_then_success(self):
        """Test that async transient failures trigger retry."""
        mock_func = AsyncMock(side_effect=[
            ConnectionError("Network error"),
            ConnectionError("Network error"),
            "async_success"
        ])
        decorated = async_retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
            jitter=False,
        )(mock_func)

        result = await decorated()

        assert result == "async_success"
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_permanent_failure_exhausts_retries(self):
        """Test that async permanent failures exhaust retries."""
        mock_func = AsyncMock(side_effect=TimeoutError("Timeout"))
        decorated = async_retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
        )(mock_func)

        with pytest.raises(TimeoutError, match="Timeout"):
            await decorated()

        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing(self):
        """Test that async exponential backoff delays increase correctly."""
        call_times = []

        async def failing_func():
            call_times.append(time.time())
            raise ConnectionError("Network error")

        decorated = async_retry_with_backoff(
            max_attempts=3,
            base_delay=0.1,
            exponential_base=2.0,
            jitter=False,
        )(failing_func)

        with pytest.raises(ConnectionError):
            await decorated()

        delays = [call_times[i+1] - call_times[i] for i in range(len(call_times) - 1)]

        # Allow 50ms tolerance
        assert 0.08 <= delays[0] <= 0.15, f"First delay: {delays[0]}"
        assert 0.18 <= delays[1] <= 0.25, f"Second delay: {delays[1]}"

    @pytest.mark.asyncio
    async def test_jitter_adds_randomness(self):
        """Test that jitter adds randomness to delay times."""
        call_times = []

        async def failing_func():
            call_times.append(time.time())
            raise OSError("OS error")

        decorated = async_retry_with_backoff(
            max_attempts=3,
            base_delay=0.1,
            exponential_base=2.0,
            jitter=True,  # Enable jitter
        )(failing_func)

        with pytest.raises(OSError):
            await decorated()

        delays = [call_times[i+1] - call_times[i] for i in range(len(call_times) - 1)]

        # With jitter, delays should be 50%-150% of base
        # First delay: 0.1 * [0.5-1.5] = 0.05-0.15
        # Second delay: 0.2 * [0.5-1.5] = 0.10-0.30
        assert 0.04 <= delays[0] <= 0.16, f"First jittered delay: {delays[0]}"
        assert 0.08 <= delays[1] <= 0.32, f"Second jittered delay: {delays[1]}"

    @pytest.mark.asyncio
    async def test_concurrent_async_retries(self):
        """Test that multiple async retries can run concurrently."""
        call_counts = {"func1": 0, "func2": 0}

        async def func1():
            call_counts["func1"] += 1
            if call_counts["func1"] < 2:
                raise ConnectionError("Func1 error")
            return "func1_success"

        async def func2():
            call_counts["func2"] += 1
            if call_counts["func2"] < 2:
                raise ConnectionError("Func2 error")
            return "func2_success"

        decorated1 = async_retry_with_backoff(max_attempts=3, base_delay=0.01)(func1)
        decorated2 = async_retry_with_backoff(max_attempts=3, base_delay=0.01)(func2)

        # Run concurrently
        results = await asyncio.gather(decorated1(), decorated2())

        assert results == ["func1_success", "func2_success"]
        assert call_counts["func1"] == 2
        assert call_counts["func2"] == 2


class TestRetryIntegration:
    """Integration tests for retry decorators with realistic scenarios."""

    def test_api_call_simulation(self):
        """Simulate retrying a failing API call."""
        attempt_count = 0

        def flaky_api_call():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ConnectionError(f"API unreachable (attempt {attempt_count})")
            return {"status": "success", "data": "response"}

        decorated = retry_with_backoff(
            max_attempts=5,
            base_delay=0.01,
        )(flaky_api_call)

        result = decorated()

        assert result == {"status": "success", "data": "response"}
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_database_connection_retry(self):
        """Simulate retrying a database connection."""
        connection_attempts = 0

        async def connect_to_db():
            nonlocal connection_attempts
            connection_attempts += 1
            if connection_attempts < 2:
                raise OSError("Database connection refused")
            return "connected"

        decorated = async_retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
            retryable_exceptions=(OSError, ConnectionError),
        )(connect_to_db)

        result = await decorated()

        assert result == "connected"
        assert connection_attempts == 2

    def test_preserves_function_metadata(self):
        """Test that decorator preserves original function metadata."""
        def original_func(x: int, y: int) -> int:
            """Add two numbers."""
            return x + y

        decorated = retry_with_backoff(max_attempts=3)(original_func)

        assert decorated.__name__ == "original_func"
        assert "Add two numbers" in decorated.__doc__

    @pytest.mark.asyncio
    async def test_preserves_async_function_metadata(self):
        """Test that async decorator preserves function metadata."""
        async def original_async_func(x: int) -> int:
            """Async square function."""
            return x * x

        decorated = async_retry_with_backoff(max_attempts=3)(original_async_func)

        assert decorated.__name__ == "original_async_func"
        assert "Async square" in decorated.__doc__
