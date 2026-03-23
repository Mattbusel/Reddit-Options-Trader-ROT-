"""Discord webhook notification system for ROT trade signal alerts.

Sends structured, richly-formatted trade signal embeds to a Discord channel
via an Incoming Webhook URL.  Configuration is driven entirely by the
``DISCORD_WEBHOOK_URL`` environment variable (no hardcoded credentials).

Key features:
- Signal confidence, ticker, strategy type, entry/exit targets in each embed
- Colour-coded by stance (bullish = green, bearish = red, mixed = yellow)
- Async-safe: uses ``httpx.AsyncClient``
- Falls back to the lower-level ``rot.alerts.discord.DiscordAlerter`` for
  full signal objects; this module exposes a higher-level interface focused
  on explicit trade-notification payloads.

Environment variables::

    DISCORD_WEBHOOK_URL   Required.  Full Incoming Webhook URL from Discord.

Typical usage::

    import asyncio
    from rot.notifications.discord import DiscordNotifier

    notifier = DiscordNotifier()
    asyncio.run(notifier.send_trade_alert(
        ticker="AAPL",
        strategy="bull_call_spread",
        stance="bullish",
        confidence=0.82,
        entry_target=172.50,
        exit_target=185.00,
        stop_loss=168.00,
        notes="Strong earnings beat + positive guidance.",
    ))
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger(__name__)

# Stance -> Discord embed colour (decimal)
_COLOUR = {
    "bullish": 0x22C55E,   # green
    "bearish": 0xEF4444,   # red
    "mixed": 0xEAB308,     # yellow
    "neutral": 0x3B82F6,   # blue
    "unknown": 0x6B7280,   # grey
}

_ENV_VAR = "DISCORD_WEBHOOK_URL"


class DiscordNotifier:
    """Sends trade-signal notifications to a Discord channel via a webhook.

    Args:
        webhook_url: Full Discord Incoming Webhook URL.  When omitted the
            value of the ``DISCORD_WEBHOOK_URL`` environment variable is used.
        timeout: HTTP request timeout in seconds (default 10).

    Raises:
        ValueError: If no webhook URL is available from either the argument or
            the environment variable.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        url = webhook_url or os.environ.get(_ENV_VAR, "")
        if not url:
            raise ValueError(
                f"Discord webhook URL is not configured.  "
                f"Set the {_ENV_VAR!r} environment variable or pass webhook_url= explicitly."
            )
        self._url = url
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_trade_alert(
        self,
        ticker: str,
        strategy: str,
        stance: str,
        confidence: float,
        entry_target: Optional[float] = None,
        exit_target: Optional[float] = None,
        stop_loss: Optional[float] = None,
        notes: str = "",
        source_url: str = "",
        timeframe: str = "",
    ) -> bool:
        """Send a trade-signal alert embed to Discord.

        Args:
            ticker: Equity ticker symbol, e.g. ``"AAPL"``.
            strategy: Options strategy name, e.g. ``"bull_call_spread"``.
            stance: Signal direction — ``"bullish"``, ``"bearish"``, ``"mixed"``, or ``"neutral"``.
            confidence: Signal confidence in [0.0, 1.0].
            entry_target: Suggested entry price or premium (USD).
            exit_target: Profit-taking target price (USD).
            stop_loss: Maximum acceptable loss price (USD).
            notes: Free-text analyst notes or thesis (≤500 chars displayed).
            source_url: Hyperlink to the originating Reddit post or source.
            timeframe: Optional analysis timeframe label, e.g. ``"1h/4h/1d aligned"``.

        Returns:
            ``True`` if the webhook returned HTTP 200 or 204, else ``False``.
        """
        stance_lower = stance.lower()
        colour = _COLOUR.get(stance_lower, _COLOUR["unknown"])

        # Build stance indicator prefix
        prefix = {"bullish": "🟢", "bearish": "🔴", "mixed": "🟡", "neutral": "🔵"}.get(stance_lower, "⚪")
        strategy_display = strategy.replace("_", " ").title()

        fields = [
            {"name": "Stance", "value": stance.upper(), "inline": True},
            {"name": "Confidence", "value": f"{confidence:.0%}", "inline": True},
            {"name": "Strategy", "value": strategy_display, "inline": True},
        ]

        if entry_target is not None:
            fields.append({"name": "Entry Target", "value": f"${entry_target:,.2f}", "inline": True})
        if exit_target is not None:
            fields.append({"name": "Exit / Take Profit", "value": f"${exit_target:,.2f}", "inline": True})
        if stop_loss is not None:
            fields.append({"name": "Stop Loss", "value": f"${stop_loss:,.2f}", "inline": True})
        if timeframe:
            fields.append({"name": "Timeframe Alignment", "value": timeframe, "inline": True})
        if notes:
            fields.append({
                "name": "Thesis / Notes",
                "value": notes[:500],
                "inline": False,
            })

        embed: Dict[str, Any] = {
            "title": f"{prefix} {ticker} — {strategy_display}",
            "color": colour,
            "fields": fields,
            "footer": {"text": "ROT — Reddit Options Trader | Not financial advice"},
        }
        if source_url:
            embed["url"] = source_url

        return await self._post({"embeds": [embed]})

    async def send_raw_signal(
        self,
        signal_data: Dict[str, Any],
        dashboard_url: str = "",
    ) -> bool:
        """Forward a raw ROT signal dict to Discord (delegates to DiscordAlerter).

        This is a convenience wrapper that allows passing the native signal
        dict produced by the ROT pipeline directly without reformatting.

        Args:
            signal_data: Signal dictionary as produced by the ROT pipeline
                (must contain ``event``, ``reasoning``, and ``trade_idea`` keys).
            dashboard_url: Optional URL to the ROT dashboard.

        Returns:
            ``True`` on success.
        """
        from rot.alerts.discord import DiscordAlerter

        alerter = DiscordAlerter(webhook_url=self._url)
        return await alerter.send_signal(signal_data, dashboard_url=dashboard_url)

    async def send_system_message(self, message: str, title: str = "ROT System Notice") -> bool:
        """Send a plain informational message to the Discord channel.

        Args:
            message: Body text (≤2000 chars).
            title: Embed title.

        Returns:
            ``True`` on success.
        """
        embed = {
            "title": title,
            "description": message[:2000],
            "color": 0x6B7280,
            "footer": {"text": "ROT — Reddit Options Trader"},
        }
        return await self._post({"embeds": [embed]})

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _post(self, payload: Dict[str, Any]) -> bool:
        """POST *payload* as JSON to the configured Discord webhook URL.

        Args:
            payload: JSON-serialisable dict accepted by the Discord webhooks API.

        Returns:
            ``True`` if the server responded with 200 or 204.
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=self._timeout,
                )
            if resp.status_code in (200, 204):
                log.info("discord.notification_sent status=%d", resp.status_code)
                return True
            log.warning(
                "discord.webhook_error status=%d body=%s",
                resp.status_code,
                resp.text[:200],
            )
            return False
        except httpx.TimeoutException:
            log.error("discord.timeout url=%s", self._url[:60])
            return False
        except Exception as exc:
            log.error("discord.send_failed error=%s", exc)
            return False


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def get_notifier(webhook_url: Optional[str] = None) -> Optional[DiscordNotifier]:
    """Return a :class:`DiscordNotifier` if a webhook URL is configured.

    Returns ``None`` (instead of raising) when the URL is absent, making it
    safe to call in contexts where Discord alerts are optional.

    Args:
        webhook_url: Explicit URL; falls back to ``DISCORD_WEBHOOK_URL`` env var.

    Returns:
        Configured :class:`DiscordNotifier` or ``None``.
    """
    url = webhook_url or os.environ.get(_ENV_VAR, "")
    if not url:
        log.debug("discord.notifier_disabled reason=no_webhook_url")
        return None
    return DiscordNotifier(webhook_url=url)
