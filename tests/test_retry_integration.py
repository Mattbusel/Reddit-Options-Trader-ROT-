"""Integration tests for retry logic across the pipeline.

Tests retry behavior with real components:
- Market data fetching with network failures
- LLM API calls with transient errors
- Social media ingestion with rate limits
- Database operations with connection issues
"""
from __future__ import annotations

import asyncio
from unittest.mock import Mock, patch, AsyncMock

import pytest
import httpx

from rot.market.enricher import MarketEnricher
from rot.reasoner.llm_client import LLMClient
from rot.ingest.stocktwits_ingestor import StockTwitsIngestor
from rot.ingest.rss_ingestor import RSSIngestor


class TestMarketDataRetry:
    """Test retry logic for market data fetching."""

    @pytest.mark.asyncio
    async def test_yfinance_retry_on_network_error(self):
        """Test that yfinance fetching retries on network errors."""
        enricher = MarketEnricher()

        # Mock yfinance to fail twice, then succeed
        call_count = 0

        def mock_download(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network unreachable")
            # Return minimal valid response
            import pandas as pd
            return pd.DataFrame({"Close": [100.0]}, index=[pd.Timestamp.now()])

        with patch("yfinance.download", side_effect=mock_download):
            result = enricher._fetch("AAPL")

            # Should succeed after retries
            assert result is not None
            assert call_count == 3  # Failed twice, succeeded on third

    @pytest.mark.asyncio
    async def test_yfinance_exhausts_retries(self):
        """Test that yfinance gives up after max retries."""
        enricher = MarketEnricher()

        # Mock yfinance to always fail
        def mock_download(*args, **kwargs):
            raise TimeoutError("Request timeout")

        with patch("yfinance.download", side_effect=mock_download):
            with pytest.raises(TimeoutError):
                enricher._fetch("AAPL")

    @pytest.mark.asyncio
    async def test_options_metrics_retry(self):
        """Test that options metrics fetching retries."""
        enricher = MarketEnricher()

        call_count = 0

        def mock_ticker(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_obj = Mock()
            if call_count < 2:
                mock_obj.options = property(lambda self: (_ for _ in ()).throw(OSError("Connection reset")))
            else:
                mock_obj.options = ["2024-12-20"]
                mock_obj.option_chain = Mock(
                    return_value=Mock(
                        calls=Mock(empty=True),
                        puts=Mock(empty=True),
                    )
                )
            return mock_obj

        with patch("yfinance.Ticker", side_effect=mock_ticker):
            result = enricher._fetch_options_metrics("AAPL")

            # Should succeed after retry
            assert call_count == 2


class TestLLMRetry:
    """Test retry logic for LLM API calls."""

    def test_openai_retry_on_connection_error(self):
        """Test that OpenAI calls retry on network errors."""
        client = LLMClient(provider="openai", api_key="sk-test", model="gpt-4")

        call_count = 0

        def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("API unreachable")

            # Return valid response
            mock_response = Mock()
            mock_choice = Mock()
            mock_message = Mock()
            mock_message.content = "Bullish sentiment detected"
            mock_choice.message = mock_message
            mock_response.choices = [mock_choice]
            return mock_response

        with patch.object(client._client.chat.completions, "create", side_effect=mock_create):
            result = client.complete(
                system="You are a financial analyst",
                user="Analyze this: TSLA to the moon!",
            )

            assert "Bullish" in result
            assert call_count == 3

    def test_anthropic_retry_on_timeout(self):
        """Test that Anthropic calls retry on timeouts."""
        client = LLMClient(provider="anthropic", api_key="sk-ant-test", model="claude-3-sonnet-20240229")

        call_count = 0

        def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("Request timeout")

            mock_response = Mock()
            mock_content = Mock()
            mock_content.text = "Analysis complete"
            mock_response.content = [mock_content]
            return mock_response

        with patch.object(client._client.messages, "create", side_effect=mock_create):
            result = client.complete(system="Analyze", user="NVDA rally")

            assert "Analysis" in result
            assert call_count == 2


class TestSocialIngestorRetry:
    """Test retry logic for social media ingestors."""

    def test_stocktwits_retry_on_http_error(self):
        """Test that StockTwits fetching retries on HTTP errors."""
        ingestor = StockTwitsIngestor(symbols=["AAPL"], track_trending=False)

        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_response = Mock()
            if call_count < 2:
                mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "503 Service Unavailable",
                    request=Mock(),
                    response=Mock(status_code=503),
                )
            else:
                mock_response.raise_for_status.return_value = None
                mock_response.json.return_value = {"messages": []}

            return mock_response

        with patch.object(ingestor._client, "get", side_effect=mock_get):
            result = ingestor._fetch_symbol("AAPL")

            assert result is not None
            assert call_count == 2

    def test_stocktwits_trending_retry(self):
        """Test that StockTwits trending fetching retries."""
        ingestor = StockTwitsIngestor(symbols=[], track_trending=True)

        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_response = Mock()
            if call_count < 3:
                # Simulate network timeout
                raise OSError("Network timeout")
            else:
                mock_response.raise_for_status.return_value = None
                mock_response.json.return_value = {"symbols": []}

            return mock_response

        with patch.object(ingestor._client, "get", side_effect=mock_get):
            result = ingestor._fetch_trending()

            assert result is not None
            assert call_count == 3

    def test_rss_feed_retry_on_connection_error(self):
        """Test that RSS feed fetching retries on connection errors."""
        ingestor = RSSIngestor(feed_urls=["https://example.com/rss"])

        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_response = Mock()
            if call_count < 2:
                raise ConnectionError("DNS resolution failed")
            else:
                mock_response.raise_for_status.return_value = None
                mock_response.text = """<?xml version="1.0"?>
                <rss version="2.0">
                    <channel>
                        <title>Test Feed</title>
                        <item><title>Test</title></item>
                    </channel>
                </rss>"""

            return mock_response

        with patch("httpx.get", side_effect=mock_get):
            result = ingestor._fetch_feed("https://example.com/rss")

            assert result is not None
            assert call_count == 2


class TestRetryBackoffTiming:
    """Test retry backoff timing behavior."""

    @pytest.mark.asyncio
    async def test_exponential_backoff_increases_delay(self):
        """Test that retry delays increase exponentially."""
        import time
        from rot.core.retry import retry_with_backoff

        call_times = []

        @retry_with_backoff(
            max_attempts=3,
            base_delay=0.1,
            exponential_base=2.0,
            jitter=False,
        )
        def failing_function():
            call_times.append(time.time())
            raise ConnectionError("Test error")

        with pytest.raises(ConnectionError):
            failing_function()

        # Calculate delays between calls
        delays = [call_times[i + 1] - call_times[i] for i in range(len(call_times) - 1)]

        # First delay ~0.1s, second delay ~0.2s
        assert len(delays) == 2
        assert 0.08 <= delays[0] <= 0.15
        assert 0.18 <= delays[1] <= 0.25

    @pytest.mark.asyncio
    async def test_jitter_adds_randomness(self):
        """Test that jitter adds randomness to delays."""
        import time
        from rot.core.retry import async_retry_with_backoff

        delays_run1 = []
        delays_run2 = []

        @async_retry_with_backoff(
            max_attempts=3,
            base_delay=0.1,
            jitter=True,
        )
        async def failing_function(delay_list):
            delay_list.append(time.time())
            raise TimeoutError("Test error")

        # Run twice to get different jitter values
        try:
            await failing_function(delays_run1)
        except TimeoutError:
            pass

        try:
            await failing_function(delays_run2)
        except TimeoutError:
            pass

        # Calculate actual delays
        actual_delays1 = [delays_run1[i + 1] - delays_run1[i] for i in range(len(delays_run1) - 1)]
        actual_delays2 = [delays_run2[i + 1] - delays_run2[i] for i in range(len(delays_run2) - 1)]

        # With jitter, delays should be different between runs
        # (very unlikely to be identical with random jitter)
        if len(actual_delays1) > 0 and len(actual_delays2) > 0:
            # Allow some tolerance, but they shouldn't be exactly the same
            assert not all(abs(actual_delays1[i] - actual_delays2[i]) < 0.001 for i in range(len(actual_delays1)))


class TestRetryIntegration:
    """Integration tests combining retry with real pipeline components."""

    @pytest.mark.asyncio
    async def test_market_enrichment_pipeline_resilience(self):
        """Test that market enrichment handles transient failures gracefully."""
        enricher = MarketEnricher()

        # Simulate flaky yfinance that works on retry
        call_count = 0

        def mock_download(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Temporary failure")

            import pandas as pd
            return pd.DataFrame(
                {"Close": [150.0], "Volume": [1000000]},
                index=[pd.Timestamp.now()],
            )

        with patch("yfinance.download", side_effect=mock_download):
            # Should succeed despite initial failure
            result = enricher._fetch("MSFT")
            assert result is not None

    @pytest.mark.asyncio
    async def test_llm_reasoning_resilience(self):
        """Test that LLM reasoning handles API failures gracefully."""
        client = LLMClient(provider="openai", api_key="sk-test", model="gpt-4")

        failures = 0

        def mock_create(*args, **kwargs):
            nonlocal failures
            failures += 1
            if failures <= 2:
                raise ConnectionError("Temporary API outage")

            mock_response = Mock()
            mock_choice = Mock()
            mock_message = Mock()
            mock_message.content = "BULLISH | High conviction signal"
            mock_choice.message = mock_message
            mock_response.choices = [mock_choice]
            return mock_response

        with patch.object(client._client.chat.completions, "create", side_effect=mock_create):
            result = client.complete(
                system="Analyze sentiment",
                user="Breaking: Company beats earnings by 50%",
            )

            assert "BULLISH" in result
            assert failures == 3  # Failed twice, succeeded on third
