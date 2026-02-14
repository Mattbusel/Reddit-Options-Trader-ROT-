"""Tests for rot.alerts.dispatcher module.

Covers multi-channel routing, confidence filtering, strategy filtering,
stance filtering, watchlist matching, and error handling.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from rot.alerts.dispatcher import AlertDispatcher, _to_dict


# ============================================================================
# Test Utilities
# ============================================================================


def _make_signal_data(
    ticker: str = "TSLA",
    stance: str = "bullish",
    confidence: float = 0.75,
    strategy: str = "debit_spread",
    event_type: str = "earnings_rumor",
    **kwargs
) -> dict:
    """Create a mock signal_data dict."""
    return {
        "event": {
            "entities": [ticker],
            "stance": stance,
            "confidence": confidence,
            "event_type": event_type,
            "evidence": [{"permalink": "https://reddit.com/r/wallstreetbets/123"}],
        },
        "trade_idea": {
            "strategy": strategy,
            "legs": [
                {"side": "buy", "kind": "call", "strike": 200, "expiry": "2025-01-17", "qty": 1}
            ],
            "max_loss": 500.0,
        },
        "reasoning": {
            "thesis": "Earnings beat expected, positive momentum",
            "catalyst_window": "earnings next week",
            "risk_notes": ["IV crush risk", "Market volatility"],
        },
        **kwargs
    }


# ============================================================================
# Test AlertDispatcher Initialization
# ============================================================================


class TestAlertDispatcherInit:
    """Test AlertDispatcher initialization."""

    def test_init_no_channels(self):
        """Should initialize with empty channels when no webhook URL provided."""
        dispatcher = AlertDispatcher(discord_webhook_url=None, min_confidence=0.6)
        assert dispatcher.min_confidence == 0.6
        assert len(dispatcher._channels) == 0
        assert dispatcher.has_channels is False

    def test_init_with_discord(self):
        """Should add Discord channel when webhook URL provided."""
        url = "https://discord.com/api/webhooks/123/abc"
        dispatcher = AlertDispatcher(discord_webhook_url=url, min_confidence=0.6)
        assert len(dispatcher._channels) == 1
        assert dispatcher.has_channels is True

    def test_init_with_db(self):
        """Should mark has_channels=True when DB provided."""
        db = MagicMock()
        dispatcher = AlertDispatcher(db=db)
        assert dispatcher.has_channels is True

    def test_init_with_email_alerter(self):
        """Should store email alerter reference."""
        email = MagicMock()
        dispatcher = AlertDispatcher(email_alerter=email)
        assert dispatcher._email_alerter == email

    def test_init_sets_dashboard_url(self):
        """Should store dashboard URL for link generation."""
        dispatcher = AlertDispatcher(dashboard_url="https://rot.example.com")
        assert dispatcher.dashboard_url == "https://rot.example.com"


# ============================================================================
# Test _to_dict Helper
# ============================================================================


class TestToDictHelper:
    """Test _to_dict dataclass conversion helper."""

    def test_to_dict_with_dict(self):
        """Should return dict unchanged."""
        d = {"a": 1, "b": 2}
        assert _to_dict(d) == d

    def test_to_dict_with_dataclass(self):
        """Should convert dataclass to dict."""
        from dataclasses import dataclass

        @dataclass
        class Sample:
            x: int
            y: str

        obj = Sample(x=10, y="test")
        result = _to_dict(obj)
        assert result == {"x": 10, "y": "test"}

    def test_to_dict_with_none(self):
        """Should return empty dict for None."""
        assert _to_dict(None) == {}

    def test_to_dict_with_string(self):
        """Should return empty dict for non-dict/non-dataclass."""
        assert _to_dict("not a dict") == {}


# ============================================================================
# Test Confidence Filtering
# ============================================================================


class TestConfidenceFiltering:
    """Test min_confidence threshold filtering."""

    @pytest.mark.asyncio
    async def test_below_threshold_skipped(self):
        """Signals below min_confidence should not be dispatched."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            min_confidence=0.7
        )

        signal = _make_signal_data(confidence=0.6)  # Below 0.7

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_exact_threshold_dispatched(self):
        """Signals at exactly min_confidence should be dispatched."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            min_confidence=0.7
        )

        signal = _make_signal_data(confidence=0.7)  # Exactly 0.7

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_above_threshold_dispatched(self):
        """Signals above min_confidence should be dispatched."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            min_confidence=0.6
        )

        signal = _make_signal_data(confidence=0.85)

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_confidence_defaults_to_zero(self):
        """Missing confidence should default to 0 and be filtered."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            min_confidence=0.6
        )

        signal = _make_signal_data(confidence=0.8)
        signal["event"].pop("confidence")  # Remove confidence field

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            mock_send.assert_not_called()


# ============================================================================
# Test Strategy Filtering
# ============================================================================


class TestStrategyFiltering:
    """Test strategy != 'none' validation."""

    @pytest.mark.asyncio
    async def test_strategy_none_skipped(self):
        """Signals with strategy='none' should not be dispatched."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            min_confidence=0.6
        )

        signal = _make_signal_data(confidence=0.8, strategy="none")

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_strategy_dispatched(self):
        """Signals with valid strategies should be dispatched."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            min_confidence=0.6
        )

        strategies = ["debit_spread", "credit_spread", "iron_condor", "straddle", "strangle"]

        for strategy in strategies:
            signal = _make_signal_data(confidence=0.8, strategy=strategy)
            with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
                await dispatcher.dispatch(signal)
                mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_strategy_defaults_to_none(self):
        """Missing strategy field should default to 'none' and be filtered."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            min_confidence=0.6
        )

        signal = _make_signal_data(confidence=0.8)
        signal["trade_idea"].pop("strategy")

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_high_confidence_none_strategy_still_filtered(self):
        """Even high-confidence signals with no strategy should be filtered."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            min_confidence=0.6
        )

        signal = _make_signal_data(confidence=0.95, strategy="none")

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            mock_send.assert_not_called()


# ============================================================================
# Test Multi-Channel Routing
# ============================================================================


class TestMultiChannelRouting:
    """Test routing to Discord + Email + Webhook channels."""

    @pytest.mark.asyncio
    async def test_discord_channel_called(self):
        """Should call Discord channel send_signal."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            min_confidence=0.6,
            dashboard_url="https://rot.app"
        )

        signal = _make_signal_data(confidence=0.8)

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            mock_send.assert_called_once_with(signal, dashboard_url="https://rot.app")

    @pytest.mark.asyncio
    async def test_multiple_discord_channels(self):
        """Should send to all registered Discord channels."""
        dispatcher = AlertDispatcher(min_confidence=0.6)

        # Manually add multiple channels
        from rot.alerts.discord import DiscordAlerter
        dispatcher._channels.append(DiscordAlerter("https://discord.com/webhook1"))
        dispatcher._channels.append(DiscordAlerter("https://discord.com/webhook2"))

        signal = _make_signal_data(confidence=0.8)

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock1, \
             patch.object(dispatcher._channels[1], 'send_signal', new_callable=AsyncMock) as mock2:
            await dispatcher.dispatch(signal)
            assert mock1.call_count == 1
            assert mock2.call_count == 1

    @pytest.mark.asyncio
    async def test_webhook_dispatch_called(self):
        """Should call _dispatch_webhooks when DB is configured."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[])

        dispatcher = AlertDispatcher(db=db, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="AAPL", stance="bullish")

        with patch.object(dispatcher, '_dispatch_webhooks', new_callable=AsyncMock) as mock_webhooks:
            await dispatcher.dispatch(signal)
            mock_webhooks.assert_called_once_with(
                signal, "AAPL", "bullish", 0.8, "earnings_rumor"
            )

    @pytest.mark.asyncio
    async def test_watchlist_dispatch_called(self):
        """Should call _dispatch_watchlist_alerts when DB and email are configured."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[])
        email = MagicMock()

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="NVDA", stance="bearish")

        with patch.object(dispatcher, '_dispatch_watchlist_alerts', new_callable=AsyncMock) as mock_watch:
            await dispatcher.dispatch(signal)
            mock_watch.assert_called_once_with(signal, "NVDA", "bearish", 0.8)

    @pytest.mark.asyncio
    async def test_all_channels_called_together(self):
        """Should dispatch to Discord + webhooks + watchlist simultaneously."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[])
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[])
        email = MagicMock()

        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/webhook",
            db=db,
            email_alerter=email,
            min_confidence=0.6
        )

        signal = _make_signal_data(confidence=0.8)

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_discord, \
             patch.object(dispatcher, '_dispatch_webhooks', new_callable=AsyncMock) as mock_webhooks, \
             patch.object(dispatcher, '_dispatch_watchlist_alerts', new_callable=AsyncMock) as mock_watch:
            await dispatcher.dispatch(signal)
            mock_discord.assert_called_once()
            mock_webhooks.assert_called_once()
            mock_watch.assert_called_once()


# ============================================================================
# Test Channel Error Handling
# ============================================================================


class TestChannelErrorHandling:
    """Test that one channel failure doesn't break others."""

    @pytest.mark.asyncio
    async def test_discord_error_doesnt_break_webhooks(self):
        """Discord failure should not prevent webhook dispatch."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[])

        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/webhook",
            db=db,
            min_confidence=0.6
        )

        signal = _make_signal_data(confidence=0.8)

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_discord, \
             patch.object(dispatcher, '_dispatch_webhooks', new_callable=AsyncMock) as mock_webhooks:
            mock_discord.side_effect = Exception("Discord API down")

            await dispatcher.dispatch(signal)

            # Discord should have been attempted
            mock_discord.assert_called_once()
            # Webhooks should still have been called
            mock_webhooks.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_error_doesnt_break_watchlist(self):
        """Webhook failure should not prevent watchlist dispatch."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(side_effect=Exception("DB error"))
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[])
        email = MagicMock()

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8)

        with patch.object(dispatcher, '_dispatch_watchlist_alerts', new_callable=AsyncMock) as mock_watch:
            await dispatcher.dispatch(signal)
            # Watchlist should still be called even if webhooks failed
            mock_watch.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_channels_fail_gracefully(self):
        """Multiple channel failures should not raise exceptions."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(side_effect=Exception("DB error"))
        db.get_users_with_watchlist_ticker = AsyncMock(side_effect=Exception("DB error 2"))
        email = MagicMock()

        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/webhook",
            db=db,
            email_alerter=email,
            min_confidence=0.6
        )

        signal = _make_signal_data(confidence=0.8)

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_discord:
            mock_discord.side_effect = Exception("Discord error")

            # Should not raise exception
            await dispatcher.dispatch(signal)


# ============================================================================
# Test Watchlist Matching
# ============================================================================


class TestWatchlistMatching:
    """Test watchlist ticker matching and email dispatch."""

    @pytest.mark.asyncio
    async def test_watchlist_no_users_no_emails(self):
        """Should not send emails when no users match watchlist."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[])
        email = MagicMock()

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="AAPL")

        await dispatcher.dispatch(signal)

        db.get_users_with_watchlist_ticker.assert_called_once_with("AAPL")
        email._send_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_watchlist_paid_user_gets_email(self):
        """Paid tier users should receive watchlist alerts."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[
            {"email": "user@example.com", "tier": "pro"}
        ])
        email = MagicMock()

        dispatcher = AlertDispatcher(
            db=db,
            email_alerter=email,
            min_confidence=0.6,
            dashboard_url="https://rot.app"
        )
        signal = _make_signal_data(confidence=0.8, ticker="TSLA", stance="bullish", strategy="debit_spread")

        await dispatcher.dispatch(signal)

        email._send_email.assert_called_once()
        args = email._send_email.call_args[0]
        assert args[0] == "user@example.com"
        assert "TSLA" in args[1]
        assert "BULLISH" in args[1]
        assert "80%" in args[1]
        assert "bullish" in args[2]
        assert "debit_spread" in args[2]
        assert "https://rot.app/dashboard" in args[2]

    @pytest.mark.asyncio
    async def test_watchlist_free_user_no_email(self):
        """Free tier users should not receive watchlist alerts."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[
            {"email": "free@example.com", "tier": "free"}
        ])
        email = MagicMock()

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="AAPL")

        await dispatcher.dispatch(signal)

        email._send_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_watchlist_premium_user_gets_email(self):
        """Premium tier users should receive watchlist alerts."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[
            {"email": "premium@example.com", "tier": "premium"}
        ])
        email = MagicMock()

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.75, ticker="NVDA")

        await dispatcher.dispatch(signal)

        email._send_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_watchlist_ultra_user_gets_email(self):
        """Ultra tier users should receive watchlist alerts."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[
            {"email": "ultra@example.com", "tier": "ultra"}
        ])
        email = MagicMock()

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.7, ticker="AMD")

        await dispatcher.dispatch(signal)

        email._send_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_watchlist_enterprise_user_gets_email(self):
        """Enterprise tier users should receive watchlist alerts."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[
            {"email": "enterprise@example.com", "tier": "enterprise"}
        ])
        email = MagicMock()

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="SPY")

        await dispatcher.dispatch(signal)

        email._send_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_watchlist_user_no_email_address(self):
        """Users without email address should be skipped."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[
            {"email": "", "tier": "pro"}
        ])
        email = MagicMock()

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="AAPL")

        await dispatcher.dispatch(signal)

        email._send_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_watchlist_multiple_users(self):
        """Should send emails to all matching paid users."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[
            {"email": "user1@example.com", "tier": "pro"},
            {"email": "user2@example.com", "tier": "premium"},
            {"email": "free@example.com", "tier": "free"},  # Should be skipped
            {"email": "user3@example.com", "tier": "ultra"},
        ])
        email = MagicMock()

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="MSFT")

        await dispatcher.dispatch(signal)

        assert email._send_email.call_count == 3  # 3 paid users
        emails_sent = [call[0][0] for call in email._send_email.call_args_list]
        assert "user1@example.com" in emails_sent
        assert "user2@example.com" in emails_sent
        assert "user3@example.com" in emails_sent
        assert "free@example.com" not in emails_sent

    @pytest.mark.asyncio
    async def test_watchlist_email_error_doesnt_break_others(self):
        """One email failure should not prevent other emails."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[
            {"email": "user1@example.com", "tier": "pro"},
            {"email": "user2@example.com", "tier": "premium"},
        ])
        email = MagicMock()

        # First call fails, second succeeds
        email._send_email.side_effect = [Exception("SMTP error"), None]

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="TSLA")

        await dispatcher.dispatch(signal)

        # Both should have been attempted
        assert email._send_email.call_count == 2

    @pytest.mark.asyncio
    async def test_watchlist_db_error_silent_fail(self):
        """DB error in watchlist query should fail silently."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(side_effect=Exception("DB connection lost"))
        email = MagicMock()

        dispatcher = AlertDispatcher(db=db, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="AAPL")

        # Should not raise exception
        await dispatcher.dispatch(signal)

        email._send_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_watchlist_no_db_configured(self):
        """Should not attempt watchlist alerts when DB not configured."""
        email = MagicMock()
        dispatcher = AlertDispatcher(db=None, email_alerter=email, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="AAPL")

        await dispatcher.dispatch(signal)

        email._send_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_watchlist_no_email_alerter_configured(self):
        """Should not attempt watchlist alerts when email alerter not configured."""
        db = MagicMock()
        db.get_users_with_watchlist_ticker = AsyncMock(return_value=[
            {"email": "user@example.com", "tier": "pro"}
        ])

        dispatcher = AlertDispatcher(db=db, email_alerter=None, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="AAPL")

        await dispatcher.dispatch(signal)

        # get_users_with_watchlist_ticker should not be called
        db.get_users_with_watchlist_ticker.assert_not_called()


# ============================================================================
# Test Webhook Dispatch
# ============================================================================


class TestWebhookDispatch:
    """Test custom webhook dispatch for Ultra users."""

    @pytest.mark.asyncio
    async def test_webhook_dispatch_no_users(self):
        """Should not send webhooks when no users match criteria."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[])

        dispatcher = AlertDispatcher(db=db, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8)

        with patch('rot.alerts.dispatcher.WebhookAlerter.send_webhook', new_callable=AsyncMock) as mock_webhook:
            await dispatcher.dispatch(signal)
            mock_webhook.assert_not_called()

    @pytest.mark.asyncio
    async def test_webhook_dispatch_with_user(self):
        """Should send webhook to users with configured webhook URLs."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[
            {"webhook_url": "https://example.com/webhook"}
        ])

        dispatcher = AlertDispatcher(db=db, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8, ticker="AAPL", stance="bullish")

        with patch('rot.alerts.dispatcher.WebhookAlerter.send_webhook', new_callable=AsyncMock) as mock_webhook:
            await dispatcher.dispatch(signal)

            db.get_users_for_realtime_alert.assert_called_once_with(
                "AAPL", "bullish", 0.8, "earnings_rumor"
            )
            mock_webhook.assert_called_once_with(
                "https://example.com/webhook", signal
            )

    @pytest.mark.asyncio
    async def test_webhook_dispatch_multiple_users(self):
        """Should send webhooks to all matching users."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[
            {"webhook_url": "https://example.com/webhook1"},
            {"webhook_url": "https://example.com/webhook2"},
            {"webhook_url": ""},  # Should be skipped
        ])

        dispatcher = AlertDispatcher(db=db, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.75, ticker="TSLA")

        with patch('rot.alerts.dispatcher.WebhookAlerter.send_webhook', new_callable=AsyncMock) as mock_webhook:
            await dispatcher.dispatch(signal)

            assert mock_webhook.call_count == 2
            urls_called = [call[0][0] for call in mock_webhook.call_args_list]
            assert "https://example.com/webhook1" in urls_called
            assert "https://example.com/webhook2" in urls_called

    @pytest.mark.asyncio
    async def test_webhook_dispatch_user_no_url(self):
        """Should skip users without webhook URL."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[
            {"webhook_url": ""}
        ])

        dispatcher = AlertDispatcher(db=db, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8)

        with patch('rot.alerts.dispatcher.WebhookAlerter.send_webhook', new_callable=AsyncMock) as mock_webhook:
            await dispatcher.dispatch(signal)
            mock_webhook.assert_not_called()

    @pytest.mark.asyncio
    async def test_webhook_dispatch_error_doesnt_break_others(self):
        """One webhook failure should not prevent others."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[
            {"webhook_url": "https://example.com/webhook1"},
            {"webhook_url": "https://example.com/webhook2"},
        ])

        dispatcher = AlertDispatcher(db=db, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8)

        with patch('rot.alerts.dispatcher.WebhookAlerter.send_webhook', new_callable=AsyncMock) as mock_webhook:
            mock_webhook.side_effect = [Exception("Webhook 1 error"), None]

            await dispatcher.dispatch(signal)

            assert mock_webhook.call_count == 2

    @pytest.mark.asyncio
    async def test_webhook_dispatch_db_error_silent_fail(self):
        """DB error in webhook query should fail silently."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(side_effect=Exception("DB error"))

        dispatcher = AlertDispatcher(db=db, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8)

        # Should not raise exception
        await dispatcher.dispatch(signal)

    @pytest.mark.asyncio
    async def test_webhook_dispatch_no_db_configured(self):
        """Should not attempt webhooks when DB not configured."""
        dispatcher = AlertDispatcher(db=None, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8)

        with patch('rot.alerts.dispatcher.WebhookAlerter.send_webhook', new_callable=AsyncMock) as mock_webhook:
            await dispatcher.dispatch(signal)
            mock_webhook.assert_not_called()


# ============================================================================
# Test Ticker Extraction
# ============================================================================


class TestTickerExtraction:
    """Test ticker extraction from signal data."""

    @pytest.mark.asyncio
    async def test_ticker_from_entities(self):
        """Should extract ticker from entities list."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[])

        dispatcher = AlertDispatcher(db=db, min_confidence=0.6)
        signal = _make_signal_data(ticker="AAPL", confidence=0.8)

        await dispatcher.dispatch(signal)

        db.get_users_for_realtime_alert.assert_called_once()
        args = db.get_users_for_realtime_alert.call_args[0]
        assert args[0] == "AAPL"

    @pytest.mark.asyncio
    async def test_ticker_defaults_to_unknown(self):
        """Should default to UNKNOWN when entities list is empty."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[])

        dispatcher = AlertDispatcher(db=db, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8)
        signal["event"]["entities"] = []

        await dispatcher.dispatch(signal)

        db.get_users_for_realtime_alert.assert_called_once()
        args = db.get_users_for_realtime_alert.call_args[0]
        assert args[0] == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_ticker_first_entity_used(self):
        """Should use first entity when multiple tickers present."""
        db = MagicMock()
        db.get_users_for_realtime_alert = AsyncMock(return_value=[])

        dispatcher = AlertDispatcher(db=db, min_confidence=0.6)
        signal = _make_signal_data(confidence=0.8)
        signal["event"]["entities"] = ["TSLA", "AAPL", "NVDA"]

        await dispatcher.dispatch(signal)

        db.get_users_for_realtime_alert.assert_called_once()
        args = db.get_users_for_realtime_alert.call_args[0]
        assert args[0] == "TSLA"


# ============================================================================
# Test Signal Data Parsing
# ============================================================================


class TestSignalDataParsing:
    """Test parsing of signal_data dict."""

    @pytest.mark.asyncio
    async def test_missing_event_key(self):
        """Should handle missing 'event' key gracefully."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/webhook",
            min_confidence=0.6
        )

        signal = {"trade_idea": {"strategy": "debit_spread"}}

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            # Should be filtered due to missing confidence
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_trade_idea_key(self):
        """Should handle missing 'trade_idea' key gracefully."""
        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/webhook",
            min_confidence=0.6
        )

        signal = {"event": {"confidence": 0.8, "entities": ["AAPL"]}}

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            # Should be filtered due to missing/default strategy='none'
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_as_dataclass(self):
        """Should convert event dataclass to dict."""
        from dataclasses import dataclass

        @dataclass
        class MockEvent:
            confidence: float
            entities: list
            stance: str
            event_type: str

        dispatcher = AlertDispatcher(
            discord_webhook_url="https://discord.com/webhook",
            min_confidence=0.6
        )

        signal = {
            "event": MockEvent(
                confidence=0.8,
                entities=["TSLA"],
                stance="bullish",
                event_type="earnings_rumor"
            ),
            "trade_idea": {"strategy": "debit_spread"}
        }

        with patch.object(dispatcher._channels[0], 'send_signal', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch(signal)
            mock_send.assert_called_once()
