from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List

from rot.alerts.discord import DiscordAlerter

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
    ) -> None:
        self.min_confidence = min_confidence
        self.dashboard_url = dashboard_url
        self._channels: List[DiscordAlerter] = []

        if discord_webhook_url:
            self._channels.append(DiscordAlerter(discord_webhook_url))

    @property
    def has_channels(self) -> bool:
        return len(self._channels) > 0

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

        for channel in self._channels:
            try:
                await channel.send_signal(signal_data, dashboard_url=self.dashboard_url)
            except Exception as e:
                log.error("Alert dispatch failed: %s", e)
