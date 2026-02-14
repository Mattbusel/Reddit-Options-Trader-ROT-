"""Comprehensive tests for webhook alerter.

Tests cover:
- HMAC-SHA256 signature generation and verification
- JSON payload construction from Event/TradeIdea dataclasses
- HTTP POST mechanics (headers, body, method)
- Success status codes (200-299)
- Error handling (4xx client errors, 5xx server errors, network errors)
- Connection errors (DNS, refused, timeout)
- URL validation
- Timestamp inclusion
- Secret key handling
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from urllib.error import HTTPError, URLError

import pytest

from rot.alerts.webhook import WebhookAlerter
from rot.core.types import Event, Evidence, TradeIdea, OptionLeg


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_event():
    """Sample Event dataclass for testing.

    Note: The webhook builder expects certain fields directly in the Event dict
    (after dataclass conversion), not in meta. When the Event dataclass is converted
    to dict via asdict(), the meta dict is preserved as-is.
    """
    return Event(
        event_type="earnings_rumor",
        entities=["TSLA", "AAPL"],
        stance="bullish",
        time_horizon="earnings",
        evidence=[
            Evidence(
                post_id="abc123",
                permalink="/r/wallstreetbets/abc123",
                subreddit="wallstreetbets",
                excerpt="TSLA calls looking good",
            )
        ],
        confidence=0.75,
        meta={
            "trend_score": 1.5,
            "post_title": "TSLA earnings play",
            "subreddit": "wallstreetbets",
            # Reasoning should be at event level for webhook, not in meta
            "reasoning": {"thesis": "Strong earnings expected"},
        },
    )


@pytest.fixture
def sample_trade_idea():
    """Sample TradeIdea dataclass for testing."""
    return TradeIdea(
        underlying="TSLA",
        strategy="debit_spread",
        legs=[
            OptionLeg(side="buy", kind="call", strike=250.0, expiry="2025-03-21", qty=1),
            OptionLeg(side="sell", kind="call", strike=260.0, expiry="2025-03-21", qty=1),
        ],
        max_loss=1000.0,
        thesis="Bullish on earnings",
        time_stop="before earnings",
        quality_score=0.8,
        do_not_trade_reasons=[],
        meta={},
    )


@pytest.fixture
def signal_data_with_dataclasses(sample_event, sample_trade_idea):
    """Signal data dict with Event and TradeIdea as dataclasses."""
    return {
        "event": sample_event,
        "trade_idea": sample_trade_idea,
    }


@pytest.fixture
def signal_data_with_dicts(sample_event, sample_trade_idea):
    """Signal data dict with Event and TradeIdea as dicts.

    Also add 'reasoning' at the event dict level (not in meta) since
    the webhook builder looks for event.get("reasoning").
    """
    event_dict = asdict(sample_event)
    # Add reasoning at event level (webhook builder expects it here)
    event_dict["reasoning"] = {"thesis": "Strong earnings expected"}
    event_dict["post_title"] = "TSLA earnings play"
    event_dict["subreddit"] = "wallstreetbets"
    event_dict["trend_score"] = 1.5

    return {
        "event": event_dict,
        "trade_idea": asdict(sample_trade_idea),
    }


@pytest.fixture
def signal_data_minimal():
    """Minimal signal data (empty dicts)."""
    return {
        "event": {},
        "trade_idea": {},
    }


# ─── Signature Generation Tests ─────────────────────────────────────────────


class TestSignatureGeneration:
    """Test HMAC-SHA256 signature generation."""

    def test_sign_payload_basic(self):
        """Test basic signature generation."""
        payload = '{"test": "data"}'
        secret = "my-secret-key"

        signature = WebhookAlerter._sign_payload(payload, secret)

        # Signature should be 64 hex characters (SHA256 = 32 bytes = 64 hex)
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)

    def test_sign_payload_deterministic(self):
        """Test that signature is deterministic (same input = same output)."""
        payload = '{"ticker": "TSLA", "confidence": 0.75}'
        secret = "test-secret"

        sig1 = WebhookAlerter._sign_payload(payload, secret)
        sig2 = WebhookAlerter._sign_payload(payload, secret)

        assert sig1 == sig2

    def test_sign_payload_different_payload_different_signature(self):
        """Test that different payloads produce different signatures."""
        secret = "test-secret"

        sig1 = WebhookAlerter._sign_payload('{"test": "data1"}', secret)
        sig2 = WebhookAlerter._sign_payload('{"test": "data2"}', secret)

        assert sig1 != sig2

    def test_sign_payload_different_secret_different_signature(self):
        """Test that different secrets produce different signatures."""
        payload = '{"test": "data"}'

        sig1 = WebhookAlerter._sign_payload(payload, "secret1")
        sig2 = WebhookAlerter._sign_payload(payload, "secret2")

        assert sig1 != sig2

    def test_sign_payload_empty_string(self):
        """Test signing an empty string."""
        signature = WebhookAlerter._sign_payload("", "secret")

        # Should still produce a valid signature
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)

    def test_sign_payload_unicode(self):
        """Test signing Unicode characters."""
        payload = '{"message": "Hello 世界 🚀"}'
        secret = "test-secret"

        signature = WebhookAlerter._sign_payload(payload, secret)

        assert len(signature) == 64
        # Verify we can reproduce the signature
        expected = hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        assert signature == expected

    def test_sign_payload_matches_standard_hmac(self):
        """Test that our signature matches standard HMAC-SHA256."""
        payload = '{"ticker": "AAPL", "stance": "bullish"}'
        secret = "webhook-secret"

        our_signature = WebhookAlerter._sign_payload(payload, secret)

        # Compute signature using standard library
        expected = hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        assert our_signature == expected


# ─── Payload Builder Tests ───────────────────────────────────────────────────


class TestPayloadBuilder:
    """Test JSON payload construction."""

    def test_build_payload_from_dataclasses(self, signal_data_with_dataclasses):
        """Test building payload from Event/TradeIdea dataclasses.

        Note: When the Event dataclass is passed, _build_payload converts it to a dict
        via asdict(). At that point, meta data is nested in event['meta'], not at the
        event level. The builder looks for reasoning/post_title/etc at event level,
        so these won't be found when using pure dataclasses. This test verifies the
        dataclass conversion path works without errors (using default values).
        """
        payload = WebhookAlerter._build_payload(signal_data_with_dataclasses)

        assert payload["event"] == "signal.created"
        assert "timestamp" in payload
        assert isinstance(payload["timestamp"], int)
        assert payload["timestamp"] > 0

        signal = payload["signal"]
        assert signal["ticker"] == "TSLA"  # First entity
        assert signal["stance"] == "bullish"
        assert signal["confidence"] == 0.75
        assert signal["event_type"] == "earnings_rumor"
        assert signal["strategy"] == "debit_spread"
        # When using pure dataclasses, these fields aren't at event level (they're in meta)
        # so they use default values
        assert signal["thesis"] == ""  # Not found at event level
        assert signal["post_title"] == ""
        assert signal["subreddit"] == ""
        assert signal["trend_score"] == 0

    def test_build_payload_from_dicts(self, signal_data_with_dicts):
        """Test building payload from dicts (already serialized)."""
        payload = WebhookAlerter._build_payload(signal_data_with_dicts)

        signal = payload["signal"]
        assert signal["ticker"] == "TSLA"
        assert signal["stance"] == "bullish"
        assert signal["confidence"] == 0.75
        assert signal["event_type"] == "earnings_rumor"
        assert signal["strategy"] == "debit_spread"

    def test_build_payload_minimal_data(self, signal_data_minimal):
        """Test building payload with minimal/missing data."""
        payload = WebhookAlerter._build_payload(signal_data_minimal)

        signal = payload["signal"]
        assert signal["ticker"] == "UNKNOWN"  # No entities
        assert signal["stance"] == "unknown"
        assert signal["confidence"] == 0
        assert signal["event_type"] == "other"
        assert signal["strategy"] == "none"
        assert signal["thesis"] == ""
        assert signal["post_title"] == ""
        assert signal["subreddit"] == ""
        assert signal["trend_score"] == 0

    def test_build_payload_missing_event_key(self):
        """Test building payload when 'event' key is missing."""
        signal_data = {"trade_idea": {}}

        payload = WebhookAlerter._build_payload(signal_data)

        signal = payload["signal"]
        assert signal["ticker"] == "UNKNOWN"
        assert signal["stance"] == "unknown"

    def test_build_payload_missing_trade_idea_key(self):
        """Test building payload when 'trade_idea' key is missing."""
        signal_data = {"event": {"entities": ["AAPL"], "stance": "bearish"}}

        payload = WebhookAlerter._build_payload(signal_data)

        signal = payload["signal"]
        assert signal["ticker"] == "AAPL"
        assert signal["stance"] == "bearish"
        assert signal["strategy"] == "none"

    def test_build_payload_empty_entities_list(self):
        """Test building payload with empty entities list."""
        signal_data = {
            "event": {"entities": [], "stance": "bullish"},
            "trade_idea": {},
        }

        payload = WebhookAlerter._build_payload(signal_data)

        assert payload["signal"]["ticker"] == "UNKNOWN"

    def test_build_payload_multiple_entities(self):
        """Test that payload uses first entity as ticker."""
        signal_data = {
            "event": {"entities": ["TSLA", "AAPL", "NVDA"], "stance": "bullish"},
            "trade_idea": {},
        }

        payload = WebhookAlerter._build_payload(signal_data)

        assert payload["signal"]["ticker"] == "TSLA"

    def test_build_payload_timestamp_recent(self):
        """Test that timestamp is recent (within last few seconds)."""
        before = int(time.time())
        payload = WebhookAlerter._build_payload({"event": {}, "trade_idea": {}})
        after = int(time.time())

        timestamp = payload["timestamp"]
        assert before <= timestamp <= after + 1  # Allow 1 second margin

    def test_build_payload_reasoning_as_dict(self):
        """Test thesis extraction when reasoning is a dict."""
        signal_data = {
            "event": {
                "reasoning": {"thesis": "This is the thesis"},
            },
            "trade_idea": {},
        }

        payload = WebhookAlerter._build_payload(signal_data)

        assert payload["signal"]["thesis"] == "This is the thesis"

    def test_build_payload_reasoning_not_dict(self):
        """Test thesis extraction when reasoning is not a dict."""
        signal_data = {
            "event": {
                "reasoning": "invalid reasoning format",
            },
            "trade_idea": {},
        }

        payload = WebhookAlerter._build_payload(signal_data)

        assert payload["signal"]["thesis"] == ""

    def test_build_payload_structure(self):
        """Test overall payload structure."""
        payload = WebhookAlerter._build_payload({"event": {}, "trade_idea": {}})

        # Top-level keys
        assert set(payload.keys()) == {"event", "timestamp", "signal"}

        # Signal keys
        expected_signal_keys = {
            "ticker", "stance", "confidence", "event_type",
            "strategy", "thesis", "post_title", "subreddit", "trend_score"
        }
        assert set(payload["signal"].keys()) == expected_signal_keys


# ─── Webhook POST Tests ──────────────────────────────────────────────────────


class TestWebhookPost:
    """Test HTTP POST mechanics."""

    @pytest.mark.asyncio
    async def test_send_webhook_success_200(self, signal_data_with_dicts):
        """Test successful webhook delivery (200 OK)."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is True
        mock_urlopen.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_webhook_success_201(self, signal_data_with_dicts):
        """Test successful webhook delivery (201 Created)."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 201
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_send_webhook_success_204(self, signal_data_with_dicts):
        """Test successful webhook delivery (204 No Content)."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 204
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_send_webhook_headers(self, signal_data_with_dicts):
        """Test that correct headers are sent."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        # Get the Request object that was passed to urlopen
        request = mock_urlopen.call_args[0][0]
        headers = request.headers

        assert headers["Content-type"] == "application/json"
        assert headers["User-agent"] == "ROT-Webhook/1.0"
        assert headers["X-rot-event"] == "signal.created"
        assert headers["X-rot-signature"].startswith("sha256=")

    @pytest.mark.asyncio
    async def test_send_webhook_signature_header_format(self, signal_data_with_dicts):
        """Test that signature header has correct format."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        request = mock_urlopen.call_args[0][0]
        signature_header = request.headers["X-rot-signature"]

        # Format: "sha256=<64 hex chars>"
        assert signature_header.startswith("sha256=")
        hex_part = signature_header.split("=", 1)[1]
        assert len(hex_part) == 64
        assert all(c in "0123456789abcdef" for c in hex_part)

    @pytest.mark.asyncio
    async def test_send_webhook_body_is_json(self, signal_data_with_dicts):
        """Test that request body is valid JSON."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        request = mock_urlopen.call_args[0][0]
        body = request.data.decode("utf-8")

        # Should be valid JSON
        parsed = json.loads(body)
        assert "event" in parsed
        assert "timestamp" in parsed
        assert "signal" in parsed

    @pytest.mark.asyncio
    async def test_send_webhook_method_is_post(self, signal_data_with_dicts):
        """Test that HTTP method is POST."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        request = mock_urlopen.call_args[0][0]
        assert request.get_method() == "POST"

    @pytest.mark.asyncio
    async def test_send_webhook_timeout(self, signal_data_with_dicts):
        """Test that request includes timeout."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        # Timeout should be 10 seconds
        assert mock_urlopen.call_args[1]["timeout"] == 10

    @pytest.mark.asyncio
    async def test_send_webhook_empty_url_returns_false(self, signal_data_with_dicts):
        """Test that empty URL returns False without making request."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = await WebhookAlerter.send_webhook(
                "",
                signal_data_with_dicts,
            )

        assert result is False
        mock_urlopen.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_webhook_custom_secret(self, signal_data_with_dicts):
        """Test using custom secret instead of default."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        custom_secret = "custom-user-secret-123"

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
                secret=custom_secret,
            )

        request = mock_urlopen.call_args[0][0]
        signature_header = request.headers["X-rot-signature"]
        hex_signature = signature_header.split("=", 1)[1]

        # Verify signature was computed with custom secret
        body = request.data.decode("utf-8")
        expected_signature = hmac.new(
            custom_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        assert hex_signature == expected_signature

    @pytest.mark.asyncio
    async def test_send_webhook_uses_default_secret_when_not_provided(self, signal_data_with_dicts):
        """Test that default secret is used when custom secret is not provided."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        request = mock_urlopen.call_args[0][0]
        signature_header = request.headers["X-rot-signature"]
        hex_signature = signature_header.split("=", 1)[1]

        # Verify signature was computed with default secret
        body = request.data.decode("utf-8")
        expected_signature = hmac.new(
            WebhookAlerter.SIGNING_SECRET.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        assert hex_signature == expected_signature


# ─── Error Handling Tests ────────────────────────────────────────────────────


class TestErrorHandling:
    """Test error handling for various failure scenarios."""

    @pytest.mark.asyncio
    async def test_send_webhook_http_error_400(self, signal_data_with_dicts):
        """Test handling of 400 Bad Request."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                "https://example.com/webhook",
                400,
                "Bad Request",
                {},
                None,
            )

            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_http_error_401(self, signal_data_with_dicts):
        """Test handling of 401 Unauthorized."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                "https://example.com/webhook",
                401,
                "Unauthorized",
                {},
                None,
            )

            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_http_error_404(self, signal_data_with_dicts):
        """Test handling of 404 Not Found."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                "https://example.com/webhook",
                404,
                "Not Found",
                {},
                None,
            )

            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_http_error_500(self, signal_data_with_dicts):
        """Test handling of 500 Internal Server Error."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                "https://example.com/webhook",
                500,
                "Internal Server Error",
                {},
                None,
            )

            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_http_error_503(self, signal_data_with_dicts):
        """Test handling of 503 Service Unavailable."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                "https://example.com/webhook",
                503,
                "Service Unavailable",
                {},
                None,
            )

            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_url_error_dns(self, signal_data_with_dicts):
        """Test handling of DNS resolution failure."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("Name or service not known")

            result = await WebhookAlerter.send_webhook(
                "https://nonexistent.example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_url_error_connection_refused(self, signal_data_with_dicts):
        """Test handling of connection refused."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("Connection refused")

            result = await WebhookAlerter.send_webhook(
                "https://localhost:99999/webhook",
                signal_data_with_dicts,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_timeout_error(self, signal_data_with_dicts):
        """Test handling of timeout."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("timed out")

            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_generic_exception(self, signal_data_with_dicts):
        """Test handling of unexpected exception."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Unexpected error")

            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_non_2xx_status_in_response(self, signal_data_with_dicts):
        """Test handling of non-2xx status code returned in response (not exception)."""
        # Note: urllib.request.urlopen raises HTTPError for non-2xx by default,
        # but we test the getcode() check path for completeness
        mock_response = MagicMock()
        mock_response.getcode.return_value = 301  # Redirect
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data_with_dicts,
            )

        # Non-2xx should return False
        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_logs_success(self, signal_data_with_dicts, caplog):
        """Test that successful delivery is logged."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            with caplog.at_level("INFO"):
                await WebhookAlerter.send_webhook(
                    "https://example.com/webhook",
                    signal_data_with_dicts,
                )

        assert any("Webhook delivered" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_send_webhook_logs_url_error(self, signal_data_with_dicts, caplog):
        """Test that URLError is logged."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("Connection refused")

            with caplog.at_level("ERROR"):
                await WebhookAlerter.send_webhook(
                    "https://example.com/webhook",
                    signal_data_with_dicts,
                )

        assert any("Webhook failed" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_send_webhook_logs_generic_error(self, signal_data_with_dicts, caplog):
        """Test that generic Exception is logged."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Unexpected")

            with caplog.at_level("ERROR"):
                await WebhookAlerter.send_webhook(
                    "https://example.com/webhook",
                    signal_data_with_dicts,
                )

        assert any("Webhook error" in record.message for record in caplog.records)


# ─── Signature Verification Tests ───────────────────────────────────────────


class TestSignatureVerification:
    """Test signature verification patterns (for webhook receivers)."""

    def test_verify_signature_valid(self):
        """Test verifying a valid signature."""
        payload = '{"event": "signal.created", "signal": {"ticker": "TSLA"}}'
        secret = "my-webhook-secret"

        # Generate signature
        signature = WebhookAlerter._sign_payload(payload, secret)

        # Verify signature (what receiver would do)
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        assert signature == expected_signature

    def test_verify_signature_invalid_payload_modified(self):
        """Test that signature fails if payload is modified."""
        original_payload = '{"event": "signal.created"}'
        secret = "webhook-secret"

        signature = WebhookAlerter._sign_payload(original_payload, secret)

        # Attacker modifies payload
        modified_payload = '{"event": "signal.modified"}'

        # Recompute signature with modified payload
        recomputed_signature = hmac.new(
            secret.encode("utf-8"),
            modified_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Signatures should not match
        assert signature != recomputed_signature

    def test_verify_signature_invalid_secret(self):
        """Test that signature fails if wrong secret is used."""
        payload = '{"event": "signal.created"}'
        correct_secret = "correct-secret"
        wrong_secret = "wrong-secret"

        signature = WebhookAlerter._sign_payload(payload, correct_secret)

        # Try to verify with wrong secret
        recomputed_signature = hmac.new(
            wrong_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Signatures should not match
        assert signature != recomputed_signature

    def test_signature_header_format_parsing(self):
        """Test parsing signature from X-ROT-Signature header."""
        header_value = "sha256=abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"

        # Receiver parses header
        assert header_value.startswith("sha256=")
        algorithm, signature = header_value.split("=", 1)

        assert algorithm == "sha256"
        assert len(signature) == 64


# ─── Integration Tests ───────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests with realistic scenarios."""

    @pytest.mark.asyncio
    async def test_end_to_end_webhook_delivery(self, sample_event, sample_trade_idea):
        """Test complete webhook delivery flow."""
        signal_data = {
            "event": sample_event,
            "trade_idea": sample_trade_idea,
        }

        webhook_url = "https://example.com/api/webhooks/rot-signals"
        custom_secret = "user-webhook-secret-xyz"

        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = await WebhookAlerter.send_webhook(
                webhook_url,
                signal_data,
                secret=custom_secret,
            )

        assert result is True

        # Verify request
        request = mock_urlopen.call_args[0][0]
        assert request.full_url == webhook_url
        assert request.get_method() == "POST"

        # Verify headers
        assert request.headers["Content-type"] == "application/json"
        assert request.headers["X-rot-event"] == "signal.created"
        assert request.headers["X-rot-signature"].startswith("sha256=")

        # Verify body
        body = request.data.decode("utf-8")
        payload = json.loads(body)
        assert payload["event"] == "signal.created"
        assert payload["signal"]["ticker"] == "TSLA"
        assert payload["signal"]["stance"] == "bullish"
        assert payload["signal"]["confidence"] == 0.75

        # Verify signature
        signature_header = request.headers["X-rot-signature"]
        hex_signature = signature_header.split("=", 1)[1]
        expected_signature = hmac.new(
            custom_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        assert hex_signature == expected_signature

    @pytest.mark.asyncio
    async def test_multiple_webhooks_different_secrets(self, signal_data_with_dicts):
        """Test sending to multiple webhooks with different secrets."""
        urls_and_secrets = [
            ("https://webhook1.example.com/endpoint", "secret1"),
            ("https://webhook2.example.com/endpoint", "secret2"),
            ("https://webhook3.example.com/endpoint", "secret3"),
        ]

        results = []

        for url, secret in urls_and_secrets:
            mock_response = MagicMock()
            mock_response.getcode.return_value = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)

            with patch("urllib.request.urlopen", return_value=mock_response):
                result = await WebhookAlerter.send_webhook(url, signal_data_with_dicts, secret=secret)
                results.append(result)

        assert all(results)

    @pytest.mark.asyncio
    async def test_payload_json_serializable(self, signal_data_with_dataclasses):
        """Test that generated payload is fully JSON serializable."""
        payload = WebhookAlerter._build_payload(signal_data_with_dataclasses)

        # Should not raise
        json_str = json.dumps(payload, ensure_ascii=False)

        # Should be able to parse back
        parsed = json.loads(json_str)
        assert parsed == payload

    @pytest.mark.asyncio
    async def test_unicode_in_payload(self):
        """Test handling of Unicode characters in signal data."""
        signal_data = {
            "event": {
                "entities": ["TSLA"],
                "stance": "bullish",
                "post_title": "TSLA 🚀 to the moon 月亮",
                "subreddit": "wallstreetbets",
            },
            "trade_idea": {"strategy": "debit_spread"},
        }

        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = await WebhookAlerter.send_webhook(
                "https://example.com/webhook",
                signal_data,
            )

        assert result is True

        # Verify Unicode in body
        request = mock_urlopen.call_args[0][0]
        body = request.data.decode("utf-8")
        assert "🚀" in body
        assert "月亮" in body
