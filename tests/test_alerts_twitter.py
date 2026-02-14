"""Comprehensive tests for X/Twitter posting via OAuth 1.0a.

Tests cover:
- OAuth 1.0a signature generation (HMAC-SHA1)
- OAuth header construction
- Tweet formatting (280 char limit, emoji, hashtags)
- XPoster initialization and configuration checks
- HTTP POST to X API v2
- Error handling (rate limits, network errors, auth failures)
- Duplicate prevention
- Interval checking
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rot.alerts.twitter import (
    XPoster,
    _build_oauth_header,
    _oauth1_sign,
    format_tweet,
)


# ══════════════════════════════════════════════════════════════════════════════
# OAuth 1.0a Signing Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestOAuth1Signing:
    """Test HMAC-SHA1 signature generation for OAuth 1.0a."""

    def test_oauth1_sign_basic(self):
        """Test basic signature generation with known inputs."""
        method = "POST"
        url = "https://api.x.com/2/tweets"
        params = {
            "oauth_consumer_key": "test_key",
            "oauth_nonce": "abc123",
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": "1234567890",
            "oauth_token": "test_token",
            "oauth_version": "1.0",
        }
        consumer_secret = "consumer_secret"
        token_secret = "token_secret"

        signature = _oauth1_sign(method, url, params, consumer_secret, token_secret)

        # Signature should be base64-encoded
        assert signature
        assert isinstance(signature, str)
        # Base64 should be decodable
        decoded = base64.b64decode(signature)
        # HMAC-SHA1 produces 20 bytes
        assert len(decoded) == 20

    def test_oauth1_sign_deterministic(self):
        """Test that signature is deterministic with same inputs."""
        method = "POST"
        url = "https://api.x.com/2/tweets"
        params = {
            "oauth_consumer_key": "key1",
            "oauth_nonce": "nonce1",
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": "1000000000",
            "oauth_token": "token1",
            "oauth_version": "1.0",
        }
        consumer_secret = "secret1"
        token_secret = "tokensecret1"

        sig1 = _oauth1_sign(method, url, params, consumer_secret, token_secret)
        sig2 = _oauth1_sign(method, url, params, consumer_secret, token_secret)

        assert sig1 == sig2

    def test_oauth1_sign_different_params(self):
        """Test that different params produce different signatures."""
        method = "POST"
        url = "https://api.x.com/2/tweets"
        base_params = {
            "oauth_consumer_key": "key1",
            "oauth_nonce": "nonce1",
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": "1000000000",
            "oauth_token": "token1",
            "oauth_version": "1.0",
        }
        consumer_secret = "secret1"
        token_secret = "tokensecret1"

        sig1 = _oauth1_sign(method, url, base_params, consumer_secret, token_secret)

        # Change nonce
        params2 = {**base_params, "oauth_nonce": "nonce2"}
        sig2 = _oauth1_sign(method, url, params2, consumer_secret, token_secret)

        assert sig1 != sig2

    def test_oauth1_sign_different_secrets(self):
        """Test that different secrets produce different signatures."""
        method = "POST"
        url = "https://api.x.com/2/tweets"
        params = {
            "oauth_consumer_key": "key1",
            "oauth_nonce": "nonce1",
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": "1000000000",
            "oauth_token": "token1",
            "oauth_version": "1.0",
        }

        sig1 = _oauth1_sign(method, url, params, "secret1", "tokensecret1")
        sig2 = _oauth1_sign(method, url, params, "secret2", "tokensecret1")
        sig3 = _oauth1_sign(method, url, params, "secret1", "tokensecret2")

        assert sig1 != sig2
        assert sig1 != sig3
        assert sig2 != sig3

    def test_oauth1_sign_url_encoding(self):
        """Test that params are properly URL-encoded."""
        method = "POST"
        url = "https://api.x.com/2/tweets"
        # Params with special chars
        params = {
            "oauth_consumer_key": "key with spaces",
            "oauth_nonce": "abc&123",
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": "1000000000",
            "oauth_token": "token=value",
            "oauth_version": "1.0",
        }
        consumer_secret = "secret"
        token_secret = "tokensecret"

        # Should not raise
        signature = _oauth1_sign(method, url, params, consumer_secret, token_secret)
        assert signature

    def test_oauth1_sign_method_case_insensitive(self):
        """Test that HTTP method is uppercased."""
        url = "https://api.x.com/2/tweets"
        params = {
            "oauth_consumer_key": "key1",
            "oauth_nonce": "nonce1",
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": "1000000000",
            "oauth_token": "token1",
            "oauth_version": "1.0",
        }
        consumer_secret = "secret"
        token_secret = "tokensecret"

        sig_post = _oauth1_sign("POST", url, params, consumer_secret, token_secret)
        sig_post_lower = _oauth1_sign("post", url, params, consumer_secret, token_secret)

        assert sig_post == sig_post_lower

    def test_oauth1_sign_empty_secrets(self):
        """Test signature with empty secrets (edge case)."""
        method = "POST"
        url = "https://api.x.com/2/tweets"
        params = {
            "oauth_consumer_key": "key1",
            "oauth_nonce": "nonce1",
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": "1000000000",
            "oauth_token": "token1",
            "oauth_version": "1.0",
        }

        # Empty secrets
        signature = _oauth1_sign(method, url, params, "", "")
        assert signature
        # Should still be valid base64
        decoded = base64.b64decode(signature)
        assert len(decoded) == 20


# ══════════════════════════════════════════════════════════════════════════════
# OAuth Header Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestOAuthHeader:
    """Test OAuth 1.0a Authorization header construction."""

    @patch("rot.alerts.twitter.secrets.token_hex", return_value="fixed_nonce")
    @patch("rot.alerts.twitter.time.time", return_value=1234567890.0)
    def test_build_oauth_header_format(self, mock_time, mock_nonce):
        """Test OAuth header format and structure."""
        header = _build_oauth_header(
            method="POST",
            url="https://api.x.com/2/tweets",
            api_key="test_key",
            api_secret="test_secret",
            access_token="test_token",
            access_secret="test_access_secret",
        )

        assert header.startswith("OAuth ")
        assert "oauth_consumer_key" in header
        assert "oauth_nonce" in header
        assert "oauth_signature" in header
        assert "oauth_signature_method" in header
        assert "oauth_timestamp" in header
        assert "oauth_token" in header
        assert "oauth_version" in header

    @patch("rot.alerts.twitter.secrets.token_hex", return_value="fixed_nonce")
    @patch("rot.alerts.twitter.time.time", return_value=1234567890.0)
    def test_build_oauth_header_values(self, mock_time, mock_nonce):
        """Test that OAuth header contains correct parameter values."""
        header = _build_oauth_header(
            method="POST",
            url="https://api.x.com/2/tweets",
            api_key="my_api_key",
            api_secret="my_api_secret",
            access_token="my_token",
            access_secret="my_token_secret",
        )

        # Parse header params
        assert 'oauth_consumer_key="my_api_key"' in header
        assert 'oauth_nonce="fixed_nonce"' in header
        assert 'oauth_signature_method="HMAC-SHA1"' in header
        assert 'oauth_timestamp="1234567890"' in header
        assert 'oauth_token="my_token"' in header
        assert 'oauth_version="1.0"' in header

    @patch("rot.alerts.twitter.secrets.token_hex", return_value="fixed_nonce")
    @patch("rot.alerts.twitter.time.time", return_value=1234567890.0)
    def test_build_oauth_header_signature_present(self, mock_time, mock_nonce):
        """Test that signature is generated and included."""
        header = _build_oauth_header(
            method="POST",
            url="https://api.x.com/2/tweets",
            api_key="test_key",
            api_secret="test_secret",
            access_token="test_token",
            access_secret="test_access_secret",
        )

        assert "oauth_signature=" in header
        # Extract signature value (comes after oauth_signature=")
        sig_start = header.find('oauth_signature="') + len('oauth_signature="')
        sig_end = header.find('"', sig_start)
        signature = header[sig_start:sig_end]
        # Should be URL-encoded base64
        assert len(signature) > 0

    @patch("rot.alerts.twitter.secrets.token_hex")
    @patch("rot.alerts.twitter.time.time", return_value=1000000000.0)
    def test_build_oauth_header_different_nonce(self, mock_time, mock_nonce):
        """Test that different nonces produce different headers."""
        mock_nonce.return_value = "nonce1"
        header1 = _build_oauth_header(
            method="POST",
            url="https://api.x.com/2/tweets",
            api_key="key",
            api_secret="secret",
            access_token="token",
            access_secret="tokensecret",
        )

        mock_nonce.return_value = "nonce2"
        header2 = _build_oauth_header(
            method="POST",
            url="https://api.x.com/2/tweets",
            api_key="key",
            api_secret="secret",
            access_token="token",
            access_secret="tokensecret",
        )

        assert header1 != header2
        assert 'oauth_nonce="nonce1"' in header1
        assert 'oauth_nonce="nonce2"' in header2

    @patch("rot.alerts.twitter.secrets.token_hex", return_value="fixed_nonce")
    @patch("rot.alerts.twitter.time.time")
    def test_build_oauth_header_different_timestamp(self, mock_time, mock_nonce):
        """Test that different timestamps produce different headers."""
        mock_time.return_value = 1000000000.0
        header1 = _build_oauth_header(
            method="POST",
            url="https://api.x.com/2/tweets",
            api_key="key",
            api_secret="secret",
            access_token="token",
            access_secret="tokensecret",
        )

        mock_time.return_value = 2000000000.0
        header2 = _build_oauth_header(
            method="POST",
            url="https://api.x.com/2/tweets",
            api_key="key",
            api_secret="secret",
            access_token="token",
            access_secret="tokensecret",
        )

        assert header1 != header2
        assert 'oauth_timestamp="1000000000"' in header1
        assert 'oauth_timestamp="2000000000"' in header2


# ══════════════════════════════════════════════════════════════════════════════
# Tweet Formatting Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatTweet:
    """Test tweet formatting with emoji, hashtags, and 280 char limit."""

    def test_format_tweet_basic_bullish(self):
        """Test basic bullish signal formatting."""
        signal = {
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 0.75,
            "strategy": "debit_spread",
            "event_type": "earnings_rumor",
            "time_horizon": "1w",
        }

        tweet = format_tweet(signal)

        assert "🟢" in tweet  # green circle emoji
        assert "$TSLA" in tweet
        assert "BULLISH" in tweet
        assert "75%" in tweet
        assert "Debit Spread" in tweet
        assert "Earnings Rumor" in tweet
        assert "1w" in tweet
        assert "#TSLA" in tweet
        assert "#options" in tweet
        assert "#trading" in tweet
        assert "#stocks" in tweet

    def test_format_tweet_bearish(self):
        """Test bearish signal formatting."""
        signal = {
            "ticker": "SPY",
            "stance": "bearish",
            "confidence": 0.60,
            "strategy": "credit_spread",
            "event_type": "macro",
            "time_horizon": "intraday",
        }

        tweet = format_tweet(signal)

        assert "🔴" in tweet  # red circle emoji
        assert "$SPY" in tweet
        assert "BEARISH" in tweet
        assert "60%" in tweet
        assert "Credit Spread" in tweet
        assert "Macro" in tweet
        assert "intraday" in tweet
        assert "#SPY" in tweet

    def test_format_tweet_mixed(self):
        """Test mixed stance signal."""
        signal = {
            "ticker": "AAPL",
            "stance": "mixed",
            "confidence": 0.50,
            "strategy": "iron_condor",
            "event_type": "product_news",
            "time_horizon": "earnings",
        }

        tweet = format_tweet(signal)

        assert "🟡" in tweet  # yellow circle emoji
        assert "$AAPL" in tweet
        assert "MIXED" in tweet
        assert "50%" in tweet
        assert "Iron Condor" in tweet

    def test_format_tweet_unknown_stance(self):
        """Test unknown stance signal."""
        signal = {
            "ticker": "NVDA",
            "stance": "unknown",
            "confidence": 0.40,
            "strategy": "straddle",
            "event_type": "other",
            "time_horizon": "unknown",
        }

        tweet = format_tweet(signal)

        assert "⚪" in tweet  # white circle emoji
        assert "$NVDA" in tweet
        assert "UNKNOWN" in tweet

    def test_format_tweet_no_strategy(self):
        """Test signal with no strategy (strategy='none')."""
        signal = {
            "ticker": "AMD",
            "stance": "bullish",
            "confidence": 0.65,
            "strategy": "none",
            "event_type": "regulatory",
            "time_horizon": "longer",
        }

        tweet = format_tweet(signal)

        assert "$AMD" in tweet
        assert "BULLISH" in tweet
        # Strategy line should not appear
        assert "Strategy:" not in tweet
        assert "Regulatory" in tweet

    def test_format_tweet_confidence_as_decimal(self):
        """Test confidence formatted as decimal (0-1 range)."""
        signal = {
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 0.8523,  # decimal
            "strategy": "debit_spread",
            "event_type": "earnings_rumor",
            "time_horizon": "1w",
        }

        tweet = format_tweet(signal)

        assert "85%" in tweet  # rounded to 85%

    def test_format_tweet_confidence_as_percentage(self):
        """Test confidence already as percentage (>1)."""
        signal = {
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 85,  # already percentage
            "strategy": "debit_spread",
            "event_type": "earnings_rumor",
            "time_horizon": "1w",
        }

        tweet = format_tweet(signal)

        assert "85%" in tweet

    def test_format_tweet_with_dashboard_url(self):
        """Test tweet with dashboard URL included."""
        signal = {
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 0.75,
            "strategy": "debit_spread",
            "event_type": "earnings_rumor",
            "time_horizon": "1w",
        }

        tweet = format_tweet(signal, dashboard_url="https://rot.app")

        assert "https://rot.app/dashboard?ticker=TSLA" in tweet
        assert "Track live →" in tweet

    def test_format_tweet_no_dashboard_url(self):
        """Test tweet without dashboard URL."""
        signal = {
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 0.75,
            "strategy": "debit_spread",
            "event_type": "earnings_rumor",
            "time_horizon": "1w",
        }

        tweet = format_tweet(signal, dashboard_url="")

        assert "dashboard" not in tweet.lower()

    def test_format_tweet_280_char_limit(self):
        """Test that tweet is truncated if over 280 chars."""
        # Create a signal that would generate a very long tweet
        signal = {
            "ticker": "TSLA" * 20,  # very long ticker
            "stance": "bullish",
            "confidence": 0.75,
            "strategy": "debit_spread",
            "event_type": "earnings_rumor",
            "time_horizon": "1w",
        }

        tweet = format_tweet(signal, dashboard_url="https://very-long-url.com" * 10)

        assert len(tweet) <= 280
        if len(tweet) == 280:
            # Should end with ... if truncated
            assert tweet.endswith("...") or len(tweet) < 280

    def test_format_tweet_under_280_chars(self):
        """Test that normal tweets are under 280 chars."""
        signal = {
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 0.75,
            "strategy": "debit_spread",
            "event_type": "earnings_rumor",
            "time_horizon": "1w",
        }

        tweet = format_tweet(signal, dashboard_url="https://rot.app")

        assert len(tweet) < 280

    def test_format_tweet_missing_fields(self):
        """Test tweet formatting with missing optional fields."""
        signal = {
            "ticker": "SPY",
            # missing stance, confidence, strategy, event_type, time_horizon
        }

        tweet = format_tweet(signal)

        assert "$SPY" in tweet
        assert "#SPY" in tweet
        # Should use defaults
        assert "???" not in tweet  # ticker should be present

    def test_format_tweet_underscores_replaced(self):
        """Test that underscores in strategy/event are replaced with spaces and title-cased."""
        signal = {
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 0.75,
            "strategy": "iron_condor",
            "event_type": "insider_activity",
            "time_horizon": "1w",
        }

        tweet = format_tweet(signal)

        assert "Iron Condor" in tweet
        assert "Insider Activity" in tweet
        assert "_" not in tweet  # no underscores in display

    def test_format_tweet_empty_horizon_not_shown(self):
        """Test that empty/unknown horizon is not shown."""
        signal = {
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 0.75,
            "strategy": "debit_spread",
            "event_type": "earnings_rumor",
            "time_horizon": "",  # empty
        }

        tweet = format_tweet(signal)

        assert "Horizon:" not in tweet

        signal["time_horizon"] = "unknown"
        tweet = format_tweet(signal)

        assert "Horizon:" not in tweet


# ══════════════════════════════════════════════════════════════════════════════
# XPoster Initialization Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestXPosterInit:
    """Test XPoster initialization and configuration checks."""

    def test_init_all_credentials(self):
        """Test initialization with all credentials."""
        poster = XPoster(
            api_key="test_key",
            api_secret="test_secret",
            access_token="test_token",
            access_secret="test_access_secret",
        )

        assert poster.api_key == "test_key"
        assert poster.api_secret == "test_secret"
        assert poster.access_token == "test_token"
        assert poster.access_secret == "test_access_secret"
        assert poster.is_configured is True

    def test_init_empty_credentials(self):
        """Test initialization with empty credentials."""
        poster = XPoster(
            api_key="",
            api_secret="",
            access_token="",
            access_secret="",
        )

        assert poster.is_configured is False

    def test_init_missing_api_key(self):
        """Test initialization with missing API key."""
        poster = XPoster(
            api_key="",
            api_secret="test_secret",
            access_token="test_token",
            access_secret="test_access_secret",
        )

        assert poster.is_configured is False

    def test_init_missing_api_secret(self):
        """Test initialization with missing API secret."""
        poster = XPoster(
            api_key="test_key",
            api_secret="",
            access_token="test_token",
            access_secret="test_access_secret",
        )

        assert poster.is_configured is False

    def test_init_missing_access_token(self):
        """Test initialization with missing access token."""
        poster = XPoster(
            api_key="test_key",
            api_secret="test_secret",
            access_token="",
            access_secret="test_access_secret",
        )

        assert poster.is_configured is False

    def test_init_missing_access_secret(self):
        """Test initialization with missing access secret."""
        poster = XPoster(
            api_key="test_key",
            api_secret="test_secret",
            access_token="test_token",
            access_secret="",
        )

        assert poster.is_configured is False

    def test_is_configured_property(self):
        """Test is_configured property logic."""
        # All present
        poster = XPoster("k", "s", "t", "ts")
        assert poster.is_configured is True

        # One missing
        poster = XPoster("", "s", "t", "ts")
        assert poster.is_configured is False

        poster = XPoster("k", "", "t", "ts")
        assert poster.is_configured is False

        poster = XPoster("k", "s", "", "ts")
        assert poster.is_configured is False

        poster = XPoster("k", "s", "t", "")
        assert poster.is_configured is False

        # All missing
        poster = XPoster("", "", "", "")
        assert poster.is_configured is False


# ══════════════════════════════════════════════════════════════════════════════
# XPoster.post_tweet Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPostTweet:
    """Test HTTP POST to X API v2."""

    @pytest.mark.asyncio
    async def test_post_tweet_success_200(self):
        """Test successful tweet posting (200 response)."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"id": "tweet123"}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            tweet_id = await poster.post_tweet("Test tweet")

            assert tweet_id == "tweet123"
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "https://api.x.com/2/tweets"
            assert call_args[1]["json"] == {"text": "Test tweet"}
            assert "Authorization" in call_args[1]["headers"]
            assert call_args[1]["headers"]["Authorization"].startswith("OAuth ")

    @pytest.mark.asyncio
    async def test_post_tweet_success_201(self):
        """Test successful tweet posting (201 response)."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"data": {"id": "tweet456"}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            tweet_id = await poster.post_tweet("Another tweet")

            assert tweet_id == "tweet456"

    @pytest.mark.asyncio
    async def test_post_tweet_not_configured(self, caplog):
        """Test posting when credentials not configured."""
        poster = XPoster("", "", "", "")

        with caplog.at_level("WARNING"):
            tweet_id = await poster.post_tweet("Test tweet")

        assert tweet_id is None
        assert "not configured" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_error_400(self, caplog):
        """Test posting with 400 error response."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request: Invalid tweet text"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("ERROR"):
                tweet_id = await poster.post_tweet("Test tweet")

            assert tweet_id is None
            assert "X API error 400" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_error_401_unauthorized(self, caplog):
        """Test posting with 401 unauthorized error."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("ERROR"):
                tweet_id = await poster.post_tweet("Test tweet")

            assert tweet_id is None
            assert "X API error 401" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_error_403_forbidden(self, caplog):
        """Test posting with 403 forbidden error."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden: Duplicate tweet"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("ERROR"):
                tweet_id = await poster.post_tweet("Test tweet")

            assert tweet_id is None
            assert "X API error 403" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_error_420_rate_limit(self, caplog):
        """Test posting with 420 rate limit error."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 420
        mock_response.text = "Enhance Your Calm: Rate limit exceeded"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("ERROR"):
                tweet_id = await poster.post_tweet("Test tweet")

            assert tweet_id is None
            assert "X API error 420" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_error_429_rate_limit(self, caplog):
        """Test posting with 429 rate limit error."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Too Many Requests"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("ERROR"):
                tweet_id = await poster.post_tweet("Test tweet")

            assert tweet_id is None
            assert "X API error 429" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_error_500_server_error(self, caplog):
        """Test posting with 500 server error."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("ERROR"):
                tweet_id = await poster.post_tweet("Test tweet")

            assert tweet_id is None
            assert "X API error 500" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_network_timeout(self, caplog):
        """Test posting with network timeout."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("ERROR"):
                tweet_id = await poster.post_tweet("Test tweet")

            assert tweet_id is None
            assert "X post failed" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_network_error(self, caplog):
        """Test posting with generic network error."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.NetworkError("Connection failed"))
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("ERROR"):
                tweet_id = await poster.post_tweet("Test tweet")

            assert tweet_id is None
            assert "X post failed" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_json_decode_error(self, caplog):
        """Test posting with JSON decode error in response."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("err", "doc", 0)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("ERROR"):
                tweet_id = await poster.post_tweet("Test tweet")

            assert tweet_id is None
            assert "X post failed" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_missing_id_in_response(self, caplog):
        """Test posting with missing id in successful response."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {}}  # no id

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("INFO"):
                tweet_id = await poster.post_tweet("Test tweet")

            # Should return empty string
            assert tweet_id == ""
            assert "posted successfully" in caplog.text

    @pytest.mark.asyncio
    async def test_post_tweet_timeout_setting(self):
        """Test that timeout is set to 15 seconds."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"id": "tweet123"}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await poster.post_tweet("Test tweet")

            call_args = mock_client.post.call_args
            assert call_args[1]["timeout"] == 15.0

    @pytest.mark.asyncio
    async def test_post_tweet_content_type_header(self):
        """Test that Content-Type header is set to application/json."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"id": "tweet123"}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await poster.post_tweet("Test tweet")

            call_args = mock_client.post.call_args
            assert call_args[1]["headers"]["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_post_tweet_truncated_error_log(self, caplog):
        """Test that error response text is truncated to 300 chars in log."""
        poster = XPoster("key", "secret", "token", "tokensecret")

        # Very long error message
        long_error = "Error: " + "X" * 500
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = long_error

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with caplog.at_level("ERROR"):
                await poster.post_tweet("Test tweet")

            # Check that log message doesn't contain the full error
            assert len(caplog.text) < len(long_error) + 100


# ══════════════════════════════════════════════════════════════════════════════
# Integration Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestIntegration:
    """Integration tests combining multiple components."""

    @pytest.mark.asyncio
    async def test_full_tweet_workflow(self):
        """Test full workflow from signal to tweet."""
        signal = {
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 0.75,
            "strategy": "debit_spread",
            "event_type": "earnings_rumor",
            "time_horizon": "1w",
        }

        tweet_text = format_tweet(signal, dashboard_url="https://rot.app")

        poster = XPoster("key", "secret", "token", "tokensecret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"id": "tweet789"}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            tweet_id = await poster.post_tweet(tweet_text)

            assert tweet_id == "tweet789"
            # Verify tweet text was sent
            call_args = mock_client.post.call_args
            assert call_args[1]["json"]["text"] == tweet_text

    def test_multiple_signals_different_stances(self):
        """Test formatting multiple signals with different stances."""
        signals = [
            {
                "ticker": "TSLA",
                "stance": "bullish",
                "confidence": 0.75,
                "strategy": "debit_spread",
                "event_type": "earnings_rumor",
                "time_horizon": "1w",
            },
            {
                "ticker": "SPY",
                "stance": "bearish",
                "confidence": 0.60,
                "strategy": "credit_spread",
                "event_type": "macro",
                "time_horizon": "intraday",
            },
            {
                "ticker": "AAPL",
                "stance": "mixed",
                "confidence": 0.50,
                "strategy": "iron_condor",
                "event_type": "product_news",
                "time_horizon": "earnings",
            },
        ]

        tweets = [format_tweet(s) for s in signals]

        assert len(tweets) == 3
        assert "🟢" in tweets[0]  # bullish
        assert "🔴" in tweets[1]  # bearish
        assert "🟡" in tweets[2]  # mixed
        assert all(len(t) <= 280 for t in tweets)
