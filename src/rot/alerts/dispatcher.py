from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List

from rot.alerts.discord import DiscordAlerter
from rot.alerts.webhook import WebhookAlerter

log = logging.getLogger(__name__)


def _to_dict(obj: Any) -> Dict[str, Any]:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return obj
    return {}


class AlertDispatcher:
    """Routes high-confidence signals to configured alert channels."""

    def __init__(
        self,
        discord_webhook_url: str | None = None,
        min_confidence: float = 0.6,
        dashboard_url: str = "",
        db=None,
        email_alerter=None,
    ) -> None:
        self.min_confidence = min_confidence
        self.dashboard_url = dashboard_url
        self._channels: List[DiscordAlerter] = []
        self._db = db
        self._email_alerter = email_alerter

        if discord_webhook_url:
            self._channels.append(DiscordAlerter(discord_webhook_url))

    @property
    def has_channels(self) -> bool:
        """``True`` if at least one delivery channel (Discord, webhook, or database) is configured."""
        return len(self._channels) > 0 or self._db is not None

    async def dispatch(self, signal_data: Dict[str, Any]) -> None:
        """Dispatch a signal to all configured channels if it meets confidence threshold."""
        event = _to_dict(signal_data.get("event"))
        confidence = event.get("confidence", 0)

        if confidence < self.min_confidence:
            return

        idea = _to_dict(signal_data.get("trade_idea"))
        # Skip signals with no tradeable strategy
        strategy = idea.get("strategy", "none")
        if strategy == "none":
            return

        entities = event.get("entities", [])
        ticker = entities[0] if entities else "UNKNOWN"
        stance = event.get("stance", "unknown")
        event_type = event.get("event_type", "other")

        log.info(
            "Dispatching alert for %s (confidence=%.2f, strategy=%s, stance=%s)",
            ticker, confidence, strategy, stance,
        )

        # Discord alerts
        for channel in self._channels:
            try:
                await channel.send_signal(signal_data, dashboard_url=self.dashboard_url)
            except Exception as e:
                log.error("Alert dispatch failed: %s", e)

        # Webhook alerts (ultra users)
        if self._db:
            try:
                await self._dispatch_webhooks(signal_data, ticker, stance, confidence, event_type)
            except Exception as e:
                log.error("Webhook dispatch failed: %s", e)

        # Watchlist alerts: email users when a signal matches their watchlist tickers
        if self._db and self._email_alerter:
            try:
                await self._dispatch_watchlist_alerts(signal_data, ticker, stance, confidence)
            except Exception as e:
                log.error("Watchlist alert dispatch failed: %s", e)

        # Note: Real-time email alerts removed to conserve email quota.
        # Users receive signals via daily digest instead.

    async def _dispatch_watchlist_alerts(
        self, signal_data: Dict[str, Any], ticker: str, stance: str,
        confidence: float
    ) -> None:
        """Send email alerts to users who have this ticker on their watchlist."""
        if not self._db or not self._email_alerter:
            return

        try:
            users = await self._db.get_users_with_watchlist_ticker(ticker)
        except Exception:
            return

        if not users:
            return

        idea = _to_dict(signal_data.get("trade_idea"))
        strategy = idea.get("strategy", "none")

        for u in users:
            email = u.get("email", "")
            tier = u.get("tier", "free")
            # Only paid users get watchlist alerts
            if tier not in ("pro", "premium", "ultra", "enterprise"):
                continue
            if not email:
                continue
            try:
                subject = f"ROT Watchlist Alert: {ticker} ({stance.upper()}, {confidence*100:.0f}%)"
                body = (
                    f"<h2>Watchlist Alert: {ticker}</h2>"
                    f"<p><strong>Stance:</strong> {stance} | "
                    f"<strong>Confidence:</strong> {confidence*100:.0f}% | "
                    f"<strong>Strategy:</strong> {strategy}</p>"
                    f"<p>A new signal matching your watchlist was detected.</p>"
                    f"<p><a href='{self.dashboard_url}/dashboard'>View on Dashboard</a></p>"
                )
                self._email_alerter._send_email(email, subject, body)
            except Exception as e:
                log.error("Watchlist email to %s failed: %s", email, e)

    async def _dispatch_webhooks(
        self, signal_data: Dict[str, Any], ticker: str, stance: str,
        confidence: float, event_type: str
    ) -> None:
        """Send signal to all configured webhook URLs for matching users."""
        if not self._db:
            return

        users = await self._db.get_users_for_realtime_alert(ticker, stance, confidence, event_type)
        for u in users:
            webhook_url = u.get("webhook_url", "")
            if webhook_url:
                try:
                    await WebhookAlerter.send_webhook(webhook_url, signal_data)
                except Exception as e:
                    log.error("Webhook to %s failed: %s", webhook_url, e)

