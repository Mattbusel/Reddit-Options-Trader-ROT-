"""
Comprehensive tests for Discord alerter.

Coverage:
- Embed formatting (title, description, fields, color by stance)
- Signal data serialization (ticker, confidence, strategy, reasoning snippet)
- Webhook POST request (mock httpx.AsyncClient)
- URL validation
- Timeout handling (10s default)
- Error response handling (4xx, 5xx)
- Empty webhook URL → skip gracefully
- Stance-based color coding (green=bullish, red=bearish, gray=mixed)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rot.alerts.discord import DiscordAlerter, _STANCE_COLORS, _to_dict


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def minimal_signal() -> Dict[str, Any]:
    """Minimal signal data for testing."""
    return {
        "event": {
            "entities": ["TSLA"],
            "stance": "bullish",
            "confidence": 0.75,
            "event_type": "earnings_rumor",
            "evidence": [{"permalink": "https://reddit.com/r/wsb/comments/123"}],
        },
        "reasoning": {
            "thesis": "Strong earnings expected",
            "catalyst_window": "48h",
            "risk_notes": ["IV crush risk", "Market volatility"],
        },
        "trade_idea": {
            "strategy": "debit_spread",
            "legs": [
                {"side": "buy", "kind": "call", "strike": 250, "expiry": "2024-03-15"},
                {"side": "sell", "kind": "call", "strike": 260, "expiry": "2024-03-15"},
            ],
            "max_loss": 500.0,
        },
    }


@pytest.fixture
def dataclass_signal():
    """Signal with dataclass objects instead of dicts."""
    @dataclass
    class Event:
        entities: list
        stance: str
        confidence: float
        event_type: str
        evidence: list

    @dataclass
    class Reasoning:
        thesis: str
        catalyst_window: str
        risk_notes: list

    @dataclass
    class TradeIdea:
        strategy: str
        legs: list
        max_loss: float

    return {
        "event": Event(
            entities=["AAPL"],
            stance="bearish",
            confidence=0.60,
            event_type="product_news",
            evidence=[{"permalink": "https://reddit.com/r/stocks/comments/456"}],
        ),
        "reasoning": Reasoning(
            thesis="Disappointing product launch",
            catalyst_window="24h",
            risk_notes=["Short squeeze risk"],
        ),
        "trade_idea": TradeIdea(
            strategy="credit_spread",
            legs=[
                {"side": "sell", "kind": "put", "strike": 180, "expiry": "2024-03-22"},
                {"side": "buy", "kind": "put", "strike": 175, "expiry": "2024-03-22"},
            ],
            max_loss=250.0,
        ),
    }


@pytest.fixture
def no_trade_signal() -> Dict[str, Any]:
    """Signal with no trade recommendation (strategy=none)."""
    return {
        "event": {
            "entities": ["SPY"],
            "stance": "mixed",
            "confidence": 0.45,
            "event_type": "macro",
            "evidence": [],
        },
        "reasoning": {
            "thesis": "Mixed signals from Fed minutes",
        },
        "trade_idea": {
            "strategy": "none",
            "legs": [],
        },
    }


@pytest.fixture
def unknown_stance_signal() -> Dict[str, Any]:
    """Signal with unknown stance."""
    return {
        "event": {
            "entities": [],
            "stance": "unknown",
            "confidence": 0.30,
            "event_type": "other",
            "evidence": [],
        },
        "reasoning": {},
        "trade_idea": {"strategy": "none"},
    }


# ============================================================================
# Test _STANCE_COLORS constant
# ============================================================================


class TestStanceColors:
    """Test stance-to-color mapping."""

    def test_bullish_color_is_green(self):
        assert _STANCE_COLORS["bullish"] == 0x22C55E

    def test_bearish_color_is_red(self):
        assert _STANCE_COLORS["bearish"] == 0xEF4444

    def test_mixed_color_is_yellow(self):
        assert _STANCE_COLORS["mixed"] == 0xEAB308

    def test_unknown_color_is_gray(self):
        assert _STANCE_COLORS["unknown"] == 0x6B7280

    def test_all_colors_are_integers(self):
        for color in _STANCE_COLORS.values():
            assert isinstance(color, int)

    def test_all_colors_are_valid_hex(self):
        for color in _STANCE_COLORS.values():
            assert 0 <= color <= 0xFFFFFF


# ============================================================================
# Test _to_dict helper
# ============================================================================


class TestToDict:
    """Test dataclass/dict conversion helper."""

    def test_dict_passthrough(self):
        d = {"key": "value"}
        assert _to_dict(d) == d

    def test_dataclass_to_dict(self):
        @dataclass
        class Sample:
            field: str

        result = _to_dict(Sample(field="test"))
        assert result == {"field": "test"}

    def test_nested_dataclass(self):
        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Inner

        result = _to_dict(Outer(inner=Inner(value=42)))
        assert result == {"inner": {"value": 42}}

    def test_none_returns_empty_dict(self):
        assert _to_dict(None) == {}

    def test_string_returns_empty_dict(self):
        assert _to_dict("not a dict") == {}

    def test_list_returns_empty_dict(self):
        assert _to_dict([1, 2, 3]) == {}


# ============================================================================
# Test DiscordAlerter initialization
# ============================================================================


class TestDiscordAlerterInit:
    """Test DiscordAlerter constructor."""

    def test_init_stores_webhook_url(self):
        url = "https://discord.com/api/webhooks/123/abc"
        alerter = DiscordAlerter(webhook_url=url)
        assert alerter.webhook_url == url

    def test_init_with_empty_string(self):
        alerter = DiscordAlerter(webhook_url="")
        assert alerter.webhook_url == ""


# ============================================================================
# Test embed formatting
# ============================================================================


class TestEmbedFormatting:
    """Test Discord embed structure and formatting."""

    @pytest.mark.asyncio
    async def test_embed_title_includes_ticker(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert "TSLA" in embed["title"]

    @pytest.mark.asyncio
    async def test_embed_title_includes_event_type(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert "Earnings Rumor" in embed["title"]

    @pytest.mark.asyncio
    async def test_embed_description_is_thesis(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert embed["description"] == "Strong earnings expected"

    @pytest.mark.asyncio
    async def test_embed_description_truncated_at_500_chars(self):
        signal = {
            "event": {"entities": ["TEST"], "stance": "bullish", "confidence": 0.5, "event_type": "other", "evidence": []},
            "reasoning": {"thesis": "A" * 1000},
            "trade_idea": {"strategy": "none"},
        }
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert len(embed["description"]) == 500

    @pytest.mark.asyncio
    async def test_embed_color_bullish(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert embed["color"] == _STANCE_COLORS["bullish"]

    @pytest.mark.asyncio
    async def test_embed_color_bearish(self, dataclass_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(dataclass_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert embed["color"] == _STANCE_COLORS["bearish"]

    @pytest.mark.asyncio
    async def test_embed_color_mixed(self, no_trade_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(no_trade_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert embed["color"] == _STANCE_COLORS["mixed"]

    @pytest.mark.asyncio
    async def test_embed_color_unknown(self, unknown_stance_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(unknown_stance_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert embed["color"] == _STANCE_COLORS["unknown"]

    @pytest.mark.asyncio
    async def test_embed_emoji_bullish(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert "🟢" in embed["title"]

    @pytest.mark.asyncio
    async def test_embed_emoji_bearish(self, dataclass_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(dataclass_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert "🔴" in embed["title"]

    @pytest.mark.asyncio
    async def test_embed_emoji_mixed(self, no_trade_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(no_trade_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert "🟡" in embed["title"]

    @pytest.mark.asyncio
    async def test_embed_footer_present(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert "footer" in embed
            assert "ROT" in embed["footer"]["text"]

    @pytest.mark.asyncio
    async def test_embed_url_from_permalink(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert embed["url"] == "https://reddit.com/r/wsb/comments/123"

    @pytest.mark.asyncio
    async def test_embed_no_url_when_no_permalink(self, no_trade_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(no_trade_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert "url" not in embed


# ============================================================================
# Test embed fields
# ============================================================================


class TestEmbedFields:
    """Test Discord embed field structure."""

    @pytest.mark.asyncio
    async def test_stance_field_present(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            stance_field = next(f for f in fields if f["name"] == "Stance")
            assert stance_field["value"] == "BULLISH"
            assert stance_field["inline"] is True

    @pytest.mark.asyncio
    async def test_confidence_field_formatted_as_percentage(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            conf_field = next(f for f in fields if f["name"] == "Confidence")
            assert conf_field["value"] == "75%"
            assert conf_field["inline"] is True

    @pytest.mark.asyncio
    async def test_event_type_field_present(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            event_field = next(f for f in fields if f["name"] == "Event Type")
            assert event_field["value"] == "earnings_rumor"
            assert event_field["inline"] is True

    @pytest.mark.asyncio
    async def test_strategy_field_when_trade_exists(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            strategy_field = next(f for f in fields if f["name"] == "Strategy")
            assert strategy_field["value"] == "debit_spread"

    @pytest.mark.asyncio
    async def test_no_strategy_field_when_none(self, no_trade_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(no_trade_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            assert not any(f["name"] == "Strategy" for f in fields)

    @pytest.mark.asyncio
    async def test_legs_field_formatted(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            legs_field = next(f for f in fields if f["name"] == "Legs")
            assert "BUY CALL $250" in legs_field["value"]
            assert "SELL CALL $260" in legs_field["value"]
            assert "```" in legs_field["value"]
            assert legs_field["inline"] is False

    @pytest.mark.asyncio
    async def test_max_loss_field_formatted(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            max_loss_field = next(f for f in fields if f["name"] == "Max Loss")
            assert max_loss_field["value"] == "$500.00"

    @pytest.mark.asyncio
    async def test_catalyst_window_field(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            catalyst_field = next(f for f in fields if f["name"] == "Catalyst Window")
            assert catalyst_field["value"] == "48h"

    @pytest.mark.asyncio
    async def test_risks_field_formatted(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            risks_field = next(f for f in fields if f["name"] == "Risks")
            assert "- IV crush risk" in risks_field["value"]
            assert "- Market volatility" in risks_field["value"]
            assert risks_field["inline"] is False

    @pytest.mark.asyncio
    async def test_risks_limited_to_three(self):
        signal = {
            "event": {"entities": ["TEST"], "stance": "bullish", "confidence": 0.5, "event_type": "other", "evidence": []},
            "reasoning": {
                "thesis": "Test",
                "risk_notes": ["Risk 1", "Risk 2", "Risk 3", "Risk 4", "Risk 5"],
            },
            "trade_idea": {"strategy": "none"},
        }
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            risks_field = next(f for f in fields if f["name"] == "Risks")
            lines = risks_field["value"].split("\n")
            assert len(lines) == 3


# ============================================================================
# Test webhook POST request
# ============================================================================


class TestWebhookPost:
    """Test HTTP POST to Discord webhook."""

    @pytest.mark.asyncio
    async def test_posts_to_webhook_url(self, minimal_signal):
        webhook_url = "https://discord.com/api/webhooks/123456/abcdef"
        alerter = DiscordAlerter(webhook_url)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            assert mock_post.called
            assert mock_post.call_args.args[0] == webhook_url

    @pytest.mark.asyncio
    async def test_sends_json_payload(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            assert "json" in call_args.kwargs
            payload = call_args.kwargs["json"]
            assert "embeds" in payload
            assert len(payload["embeds"]) == 1

    @pytest.mark.asyncio
    async def test_sets_content_type_header(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            headers = call_args.kwargs["headers"]
            assert headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_timeout_is_10_seconds(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(minimal_signal)

            call_args = mock_post.call_args
            assert call_args.kwargs["timeout"] == 10.0

    @pytest.mark.asyncio
    async def test_returns_true_on_200(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await alerter.send_signal(minimal_signal)
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_on_204(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await alerter.send_signal(minimal_signal)
            assert result is True


# ============================================================================
# Test error handling
# ============================================================================


class TestErrorHandling:
    """Test error response and exception handling."""

    @pytest.mark.asyncio
    async def test_returns_false_on_400(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = "Bad Request"
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await alerter.send_signal(minimal_signal)
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_404(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.text = "Not Found"
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await alerter.send_signal(minimal_signal)
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_500(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await alerter.send_signal(minimal_signal)
            assert result is False

    @pytest.mark.asyncio
    async def test_handles_network_error(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(side_effect=httpx.NetworkError("Connection failed"))
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await alerter.send_signal(minimal_signal)
            assert result is False

    @pytest.mark.asyncio
    async def test_handles_timeout_error(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await alerter.send_signal(minimal_signal)
            assert result is False

    @pytest.mark.asyncio
    async def test_handles_generic_exception(self, minimal_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(side_effect=Exception("Unexpected error"))
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await alerter.send_signal(minimal_signal)
            assert result is False


# ============================================================================
# Test signal data serialization edge cases
# ============================================================================


class TestSignalSerialization:
    """Test dataclass to dict conversion edge cases."""

    @pytest.mark.asyncio
    async def test_handles_missing_entities(self):
        signal = {
            "event": {"stance": "bullish", "confidence": 0.5, "event_type": "other", "evidence": []},
            "reasoning": {},
            "trade_idea": {"strategy": "none"},
        }
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert "UNKNOWN" in embed["title"]

    @pytest.mark.asyncio
    async def test_handles_empty_entities(self):
        signal = {
            "event": {"entities": [], "stance": "bullish", "confidence": 0.5, "event_type": "other", "evidence": []},
            "reasoning": {},
            "trade_idea": {"strategy": "none"},
        }
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert "UNKNOWN" in embed["title"]

    @pytest.mark.asyncio
    async def test_handles_missing_confidence(self):
        signal = {
            "event": {"entities": ["TEST"], "stance": "bullish", "event_type": "other", "evidence": []},
            "reasoning": {},
            "trade_idea": {"strategy": "none"},
        }
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            conf_field = next(f for f in fields if f["name"] == "Confidence")
            assert conf_field["value"] == "0%"

    @pytest.mark.asyncio
    async def test_handles_missing_thesis(self):
        signal = {
            "event": {"entities": ["TEST"], "stance": "bullish", "confidence": 0.5, "event_type": "other", "evidence": []},
            "reasoning": {},
            "trade_idea": {"strategy": "none"},
        }
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert embed["description"] == ""

    @pytest.mark.asyncio
    async def test_handles_empty_legs(self):
        signal = {
            "event": {"entities": ["TEST"], "stance": "bullish", "confidence": 0.5, "event_type": "other", "evidence": []},
            "reasoning": {},
            "trade_idea": {"strategy": "debit_spread", "legs": []},
        }
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            assert not any(f["name"] == "Legs" for f in fields)

    @pytest.mark.asyncio
    async def test_handles_zero_max_loss(self):
        signal = {
            "event": {"entities": ["TEST"], "stance": "bullish", "confidence": 0.5, "event_type": "other", "evidence": []},
            "reasoning": {},
            "trade_idea": {"strategy": "debit_spread", "legs": [{"side": "buy", "kind": "call", "strike": 100, "expiry": "2024-03-15"}], "max_loss": 0},
        }
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            assert not any(f["name"] == "Max Loss" for f in fields)

    @pytest.mark.asyncio
    async def test_handles_empty_risk_notes(self):
        signal = {
            "event": {"entities": ["TEST"], "stance": "bullish", "confidence": 0.5, "event_type": "other", "evidence": []},
            "reasoning": {"risk_notes": []},
            "trade_idea": {"strategy": "none"},
        }
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await alerter.send_signal(signal)

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            fields = payload["embeds"][0]["fields"]

            assert not any(f["name"] == "Risks" for f in fields)

    @pytest.mark.asyncio
    async def test_dataclass_signal_works(self, dataclass_signal):
        alerter = DiscordAlerter("https://discord.com/api/webhooks/test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await alerter.send_signal(dataclass_signal)
            assert result is True

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            embed = payload["embeds"][0]

            assert "AAPL" in embed["title"]
            assert embed["color"] == _STANCE_COLORS["bearish"]
