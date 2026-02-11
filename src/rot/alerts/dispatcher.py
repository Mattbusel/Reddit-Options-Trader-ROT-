from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional

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

        log.info(
            "Dispatching alert for %s (confidence=%.2f, strategy=%s)",
            ticker, confidence, strategy,
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
                await self._dispatch_webhooks(signal_data, ticker, confidence)
            except Exception as e:
                log.error("Webhook dispatch failed: %s", e)

        # Email alerts (real-time)
        if self._db and self._email_alerter and self._email_alerter.is_configured:
            try:
                await self._dispatch_realtime_emails(signal_data, ticker, confidence)
            except Exception as e:
                log.error("Email dispatch failed: %s", e)

    async def _dispatch_webhooks(
        self, signal_data: Dict[str, Any], ticker: str, confidence: float
    ) -> None:
        """Send signal to all configured webhook URLs for matching users."""
        if not self._db:
            return

        users = await self._db.get_users_for_realtime_alert(ticker, confidence)
        for u in users:
            webhook_url = u.get("webhook_url", "")
            if webhook_url:
                try:
                    await WebhookAlerter.send_webhook(webhook_url, signal_data)
                except Exception as e:
                    log.error("Webhook to %s failed: %s", webhook_url, e)

    async def _dispatch_realtime_emails(
        self, signal_data: Dict[str, Any], ticker: str, confidence: float
    ) -> None:
        """Send real-time email alerts to matching users."""
        if not self._db or not self._email_alerter:
            return

        users = await self._db.get_users_for_realtime_alert(ticker, confidence)
        event = _to_dict(signal_data.get("event"))
        idea = _to_dict(signal_data.get("trade_idea"))

        signal_for_email = {
            "ticker": ticker,
            "stance": event.get("stance", "unknown"),
            "confidence": confidence,
            "event_type": event.get("event_type", "other"),
            "strategy": idea.get("strategy", "none"),
            "reasoning": event.get("reasoning", {}),
            "created_at": event.get("created_at", 0),
        }

        for u in users:
            email = u.get("email", "")
            if email and u.get("realtime_enabled"):
                try:
                    await self._email_alerter.send_signal_alert(email, signal_for_email)
                except Exception as e:
                    log.error("Email to %s failed: %s", email, e)
