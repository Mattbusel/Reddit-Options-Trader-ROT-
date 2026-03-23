"""Unit tests for Round 4 additions to rot.notifications.discord.

Tests AlertLevel, token-bucket rate limiting, send_signal_alert,
send_position_alert, and send_daily_summary using mocked HTTP.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rot.notifications.discord import AlertLevel, DiscordNotifier, _TokenBucket
from rot.portfolio.positions import (
    LegSide,
    OptionLeg,
    OptionsPosition,
    PortfolioGreeks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_URL = "https://discord.com/api/webhooks/fake/token"


def _make_notifier(**kwargs) -> DiscordNotifier:
    return DiscordNotifier(webhook_url=_FAKE_URL, **kwargs)


def _in_days(n: int) -> date:
    return datetime.now(timezone.utc).date() + timedelta(days=n)


def _simple_position(symbol: str = "AAPL", days: int = 30) -> OptionsPosition:
    leg = OptionLeg(
        contract="OPT1",
        side=LegSide.LONG,
        strike=180.0,
        expiry=_in_days(days),
        premium=5.0,
        quantity=1,
        delta=0.50,
    )
    pos = OptionsPosition(
        symbol=symbol,
        strategy="long_call",
        legs=[leg],
        entry_date=datetime.now(timezone.utc).date(),
        expiry=_in_days(days),
        entry_cost=500.0,
    )
    pos.current_value = 550.0
    return pos


def _mock_response(status_code: int = 204) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# AlertLevel
# ---------------------------------------------------------------------------

class TestAlertLevel:
    def test_info_colour_blue(self):
        assert AlertLevel.INFO.colour == 0x3498DB

    def test_warning_colour_yellow(self):
        assert AlertLevel.WARNING.colour == 0xF1C40F

    def test_critical_colour_red(self):
        assert AlertLevel.CRITICAL.colour == 0xE74C3C

    def test_label_info(self):
        assert AlertLevel.INFO.label == "INFO"

    def test_label_warning(self):
        assert AlertLevel.WARNING.label == "WARNING"

    def test_label_critical(self):
        assert AlertLevel.CRITICAL.label == "CRITICAL"

    def test_all_levels_have_colour(self):
        for level in AlertLevel:
            assert isinstance(level.colour, int)


# ---------------------------------------------------------------------------
# No-op when env var unset
# ---------------------------------------------------------------------------

class TestNoOp:
    def test_missing_url_raises(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        with pytest.raises(ValueError, match="webhook URL"):
            DiscordNotifier()

    def test_explicit_url_works(self):
        n = _make_notifier()
        assert n is not None


# ---------------------------------------------------------------------------
# Rate limiting (_TokenBucket)
# ---------------------------------------------------------------------------

class TestTokenBucket:
    def test_allows_within_capacity(self):
        bucket = _TokenBucket(capacity=3, refill_period_s=60.0)

        async def _run():
            results = []
            for _ in range(3):
                results.append(await bucket.acquire())
            return results

        results = asyncio.get_event_loop().run_until_complete(_run())
        assert all(results)

    def test_blocks_when_exhausted(self):
        bucket = _TokenBucket(capacity=2, refill_period_s=60.0)

        async def _run():
            await bucket.acquire()
            await bucket.acquire()
            return await bucket.acquire()  # 3rd should fail

        blocked = asyncio.get_event_loop().run_until_complete(_run())
        assert blocked is False

    def test_rate_limiter_on_notifier(self):
        """Notifier should drop message when bucket exhausted."""
        notifier = _make_notifier(rate_limit_capacity=1, rate_limit_period_s=60.0)

        async def _run():
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__.return_value = mock_client
                mock_client.post.return_value = _mock_response(204)

                r1 = await notifier.send_signal_alert("sig", "AAPL", 0.8)
                r2 = await notifier.send_signal_alert("sig", "AAPL", 0.8)
            return r1, r2

        r1, r2 = asyncio.get_event_loop().run_until_complete(_run())
        assert r1 is True
        assert r2 is False  # rate-limited


# ---------------------------------------------------------------------------
# send_signal_alert
# ---------------------------------------------------------------------------

class TestSendSignalAlert:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_returns_true_on_204(self):
        notifier = _make_notifier()

        async def _go():
            with patch("httpx.AsyncClient") as mock_cls:
                mc = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mc
                mc.post.return_value = _mock_response(204)
                return await notifier.send_signal_alert("bull_call detected", "AAPL", 0.82)

        assert self._run(_go()) is True

    def test_embed_contains_ticker(self):
        notifier = _make_notifier()
        captured = {}

        async def _go():
            with patch("httpx.AsyncClient") as mock_cls:
                mc = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mc
                mc.post.return_value = _mock_response(204)

                async def capture(url, json=None, headers=None, timeout=None):
                    captured["payload"] = json
                    return _mock_response(204)

                mc.post.side_effect = capture
                await notifier.send_signal_alert("sig", "TSLA", 0.75, AlertLevel.WARNING)

        self._run(_go())
        title = captured["payload"]["embeds"][0]["title"]
        assert "TSLA" in title

    def test_critical_level_uses_red(self):
        notifier = _make_notifier()
        captured = {}

        async def _go():
            with patch("httpx.AsyncClient") as mock_cls:
                mc = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mc

                async def capture(url, json=None, **kw):
                    captured["payload"] = json
                    return _mock_response(204)

                mc.post.side_effect = capture
                await notifier.send_signal_alert("sig", "NVDA", 0.9, AlertLevel.CRITICAL)

        self._run(_go())
        color = captured["payload"]["embeds"][0]["color"]
        assert color == AlertLevel.CRITICAL.colour

    def test_returns_false_on_server_error(self):
        notifier = _make_notifier()

        async def _go():
            with patch("httpx.AsyncClient") as mock_cls:
                mc = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mc
                mc.post.return_value = _mock_response(500)
                return await notifier.send_signal_alert("sig", "AAPL", 0.5)

        assert self._run(_go()) is False


# ---------------------------------------------------------------------------
# send_position_alert
# ---------------------------------------------------------------------------

class TestSendPositionAlert:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_sends_position_details(self):
        notifier = _make_notifier()
        pos = _simple_position("AAPL", days=5)
        captured = {}

        async def _go():
            with patch("httpx.AsyncClient") as mock_cls:
                mc = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mc

                async def capture(url, json=None, **kw):
                    captured["payload"] = json
                    return _mock_response(204)

                mc.post.side_effect = capture
                return await notifier.send_position_alert(pos, "expiry_warning", AlertLevel.WARNING)

        result = self._run(_go())
        assert result is True
        title = captured["payload"]["embeds"][0]["title"]
        assert "AAPL" in title

    def test_embed_colour_matches_level(self):
        notifier = _make_notifier()
        pos = _simple_position("MSFT")
        captured = {}

        async def _go():
            with patch("httpx.AsyncClient") as mock_cls:
                mc = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mc

                async def capture(url, json=None, **kw):
                    captured["payload"] = json
                    return _mock_response(204)

                mc.post.side_effect = capture
                await notifier.send_position_alert(pos, "loss_alert", AlertLevel.CRITICAL)

        self._run(_go())
        assert captured["payload"]["embeds"][0]["color"] == AlertLevel.CRITICAL.colour


# ---------------------------------------------------------------------------
# send_daily_summary
# ---------------------------------------------------------------------------

class TestSendDailySummary:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_positive_pnl_info_level(self):
        notifier = _make_notifier()
        greeks = PortfolioGreeks(total_delta=50.0, total_gamma=2.0, total_theta=-10.0, total_vega=5.0)
        captured = {}

        async def _go():
            with patch("httpx.AsyncClient") as mock_cls:
                mc = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mc

                async def capture(url, json=None, **kw):
                    captured["payload"] = json
                    return _mock_response(204)

                mc.post.side_effect = capture
                return await notifier.send_daily_summary(greeks, daily_pnl=1200.0, open_positions=3)

        result = self._run(_go())
        assert result is True
        color = captured["payload"]["embeds"][0]["color"]
        assert color == AlertLevel.INFO.colour

    def test_negative_pnl_warning_level(self):
        notifier = _make_notifier()
        greeks = PortfolioGreeks()
        captured = {}

        async def _go():
            with patch("httpx.AsyncClient") as mock_cls:
                mc = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mc

                async def capture(url, json=None, **kw):
                    captured["payload"] = json
                    return _mock_response(204)

                mc.post.side_effect = capture
                return await notifier.send_daily_summary(greeks, daily_pnl=-500.0)

        self._run(_go())
        assert captured["payload"]["embeds"][0]["color"] == AlertLevel.WARNING.colour

    def test_greeks_in_fields(self):
        notifier = _make_notifier()
        greeks = PortfolioGreeks(total_delta=42.5, total_gamma=1.5, total_theta=-8.0, total_vega=3.0)
        captured = {}

        async def _go():
            with patch("httpx.AsyncClient") as mock_cls:
                mc = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mc

                async def capture(url, json=None, **kw):
                    captured["payload"] = json
                    return _mock_response(204)

                mc.post.side_effect = capture
                await notifier.send_daily_summary(greeks, daily_pnl=0.0)

        self._run(_go())
        field_names = {f["name"] for f in captured["payload"]["embeds"][0]["fields"]}
        assert "Net Delta" in field_names
        assert "Net Theta" in field_names

    def test_notes_included_when_provided(self):
        notifier = _make_notifier()
        greeks = PortfolioGreeks()
        captured = {}

        async def _go():
            with patch("httpx.AsyncClient") as mock_cls:
                mc = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mc

                async def capture(url, json=None, **kw):
                    captured["payload"] = json
                    return _mock_response(204)

                mc.post.side_effect = capture
                await notifier.send_daily_summary(greeks, daily_pnl=100.0, notes="Good day trading.")

        self._run(_go())
        field_names = [f["name"] for f in captured["payload"]["embeds"][0]["fields"]]
        assert "Commentary" in field_names
