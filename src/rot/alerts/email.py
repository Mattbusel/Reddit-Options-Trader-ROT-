"""Email alert system for ROT signal notifications.

Sends real-time signal alerts and daily digest emails.
Requires SMTP configuration via ROT_EMAIL_* environment variables.

Supports two connection modes:
  - STARTTLS (port 587, default): Connects plaintext, upgrades to TLS
  - SMTP_SSL (port 465, use_ssl=True): Connects with SSL from the start

Many cloud providers (Railway, Render, etc.) block outbound port 587.
Set ROT_EMAIL_SMTP_PORT=465 and ROT_EMAIL_USE_SSL=true to use SSL mode.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from rot.alerts.email_templates import render_signal_alert, render_daily_digest

log = logging.getLogger(__name__)

# SMTP connection timeout in seconds
_SMTP_TIMEOUT = 15


class EmailAlerter:
    """Sends signal alert emails via SMTP."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        from_address: str = "alerts@rot.app",
        use_ssl: bool = False,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address
        self.use_ssl = use_ssl

    @property
    def is_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user)

    def _send_email_sync(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send an HTML email via SMTP (synchronous). Returns True on success."""
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_address
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(html_body, "html"))

            if self.use_ssl or self.smtp_port == 465:
                # SMTP_SSL: direct SSL connection (port 465)
                log.debug("Connecting to %s:%d via SMTP_SSL", self.smtp_host, self.smtp_port)
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=_SMTP_TIMEOUT) as server:
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_address, to_email, msg.as_string())
            else:
                # STARTTLS: connect plaintext then upgrade (port 587)
                log.debug("Connecting to %s:%d via STARTTLS", self.smtp_host, self.smtp_port)
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=_SMTP_TIMEOUT) as server:
                    server.starttls()
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_address, to_email, msg.as_string())

            log.info("Email sent to %s: %s", to_email, subject)
            return True
        except Exception as e:
            log.error("Email send failed to %s: %s", to_email, e)
            return False

    def _send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        """Synchronous wrapper for backward compatibility."""
        return self._send_email_sync(to_email, subject, html_body)

    async def _send_email_async(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send email in a thread executor to avoid blocking the event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._send_email_sync, to_email, subject, html_body
        )

    async def send_signal_alert(
        self, to_email: str, signal_data: Dict[str, Any]
    ) -> bool:
        """Send a real-time signal alert email."""
        html = render_signal_alert(signal_data)
        ticker = signal_data.get("ticker", "UNKNOWN")
        stance = signal_data.get("stance", "unknown")
        subject = f"ROT Signal: {ticker} ({stance.upper()})"
        return await self._send_email_async(to_email, subject, html)

    async def send_daily_digest(
        self,
        to_email: str,
        signals: List[Dict[str, Any]],
        summary: Dict[str, Any],
    ) -> bool:
        """Send a daily digest email with recent signal summary."""
        html = render_daily_digest(signals, summary)
        count = len(signals)
        subject = f"ROT Daily Digest: {count} signal{'s' if count != 1 else ''}"
        return await self._send_email_async(to_email, subject, html)
