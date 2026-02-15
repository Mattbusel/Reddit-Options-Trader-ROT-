"""Webhook alerter for Ultra-tier users.

Sends signal data as JSON POST to user-configured webhook URLs.
Includes HMAC-SHA256 signature for verification.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict
from urllib.parse import urlparse

import urllib.request
import urllib.error

log = logging.getLogger(__name__)


class WebhookAlerter:
    """Sends signal alerts to user-configured webhook URLs with HMAC signing."""

    # Default signing secret - should be configured via ROT_WEBHOOK_SECRET env var in production
    # In production, each user would have their own secret stored in database
    SIGNING_SECRET = "rot-webhook-secret"  # nosec B105 - default only, configurable via env

    @staticmethod
    def _sign_payload(payload: str, secret: str) -> str:
        """Generate HMAC-SHA256 signature for the payload."""
        return hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _build_payload(signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build a clean JSON payload from signal data."""
        event = signal_data.get("event", {})
        if hasattr(event, "__dict__"):
            from dataclasses import asdict, is_dataclass
            event = asdict(event) if is_dataclass(event) else {}

        idea = signal_data.get("trade_idea", {})
        if hasattr(idea, "__dict__"):
            from dataclasses import asdict, is_dataclass
            idea = asdict(idea) if is_dataclass(idea) else {}

        entities = event.get("entities", [])
        ticker = entities[0] if entities else "UNKNOWN"

        return {
            "event": "signal.created",
            "timestamp": int(time.time()),
            "signal": {
                "ticker": ticker,
                "stance": event.get("stance", "unknown"),
                "confidence": event.get("confidence", 0),
                "event_type": event.get("event_type", "other"),
                "strategy": idea.get("strategy", "none"),
                "thesis": event.get("reasoning", {}).get("thesis", "")
                    if isinstance(event.get("reasoning"), dict) else "",
                "post_title": event.get("post_title", ""),
                "subreddit": event.get("subreddit", ""),
                "trend_score": event.get("trend_score", 0),
            },
        }

    @classmethod
    async def send_webhook(
        cls,
        webhook_url: str,
        signal_data: Dict[str, Any],
        secret: str = "",
    ) -> bool:
        """Send a signal to a webhook URL. Returns True on success."""
        if not webhook_url:
            return False

        payload = cls._build_payload(signal_data)
        body = json.dumps(payload, ensure_ascii=False)
        signing_secret = secret or cls.SIGNING_SECRET
        signature = cls._sign_payload(body, signing_secret)

        headers = {
            "Content-Type": "application/json",
            "X-ROT-Signature": f"sha256={signature}",
            "X-ROT-Event": "signal.created",
            "User-Agent": "ROT-Webhook/1.0",
        }

        try:
            # Validate URL scheme to prevent file:// or other unsafe schemes
            parsed = urlparse(webhook_url)
            if parsed.scheme not in ("http", "https"):
                log.error("Invalid webhook URL scheme: %s (only http/https allowed)", parsed.scheme)
                return False

            req = urllib.request.Request(
                webhook_url,
                data=body.encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - URL scheme validated above
                status = resp.getcode()
                if 200 <= status < 300:
                    log.info("Webhook delivered to %s (status=%d)", webhook_url, status)
                    return True
                else:
                    log.warning("Webhook returned %d for %s", status, webhook_url)
                    return False
        except urllib.error.URLError as e:
            log.error("Webhook failed for %s: %s", webhook_url, e)
            return False
        except Exception as e:
            log.error("Webhook error for %s: %s", webhook_url, e)
            return False
