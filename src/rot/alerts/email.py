"""Email alert system for ROT signal notifications.

Sends daily digest emails and password reset emails.
Requires configuration via ROT_EMAIL_* environment variables.

Supports two sending backends:
  - Resend HTTP API (recommended for cloud): Set ROT_EMAIL_RESEND_API_KEY
    Uses HTTPS (port 443), works on Railway, Render, Fly, etc.
  - SMTP (for local dev or self-hosted): Set ROT_EMAIL_SMTP_HOST
    Supports STARTTLS (port 587) and SMTP_SSL (port 465)

The Resend backend is preferred when both are configured.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List

import httpx

from rot.alerts.email_templates import render_daily_digest

log = logging.getLogger(__name__)

# SMTP connection timeout in seconds
_SMTP_TIMEOUT = 15

# Resend API endpoint
_RESEND_API_URL = "https://api.resend.com/emails"


class EmailAlerter:
    """Sends signal alert emails via Resend HTTP API or SMTP fallback."""

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        from_address: str = "alerts@rot.app",
        use_ssl: bool = False,
        resend_api_key: str = "",
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address
        self.use_ssl = use_ssl
        self.resend_api_key = resend_api_key

    @property
    def is_configured(self) -> bool:
        return bool(self.resend_api_key or (self.smtp_host and self.smtp_user))

    @property
    def backend(self) -> str:
        if self.resend_api_key:
            return "resend"
        return "smtp"

    # ── Resend HTTP API backend ──

    def _send_via_resend_sync(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send email via Resend HTTP API (synchronous). Returns True on success."""
        try:
            resp = httpx.post(
                _RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {self.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self.from_address,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_body,
                },
                timeout=15.0,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                log.info("Email sent via Resend to %s: %s (id=%s)", to_email, subject, data.get("id", "?"))
                return True
            else:
                log.error(
                    "Resend API error %d for %s: %s",
                    resp.status_code, to_email, resp.text[:300],
                )
                return False
        except Exception as e:
            log.error("Resend send failed to %s: %s", to_email, e)
            return False

    # ── SMTP backend ──

    def _send_via_smtp_sync(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send an HTML email via SMTP (synchronous). Returns True on success."""
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_address
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(html_body, "html"))

            if self.use_ssl or self.smtp_port == 465:
                log.debug("Connecting to %s:%d via SMTP_SSL", self.smtp_host, self.smtp_port)
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=_SMTP_TIMEOUT) as server:
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_address, to_email, msg.as_string())
            else:
                log.debug("Connecting to %s:%d via STARTTLS", self.smtp_host, self.smtp_port)
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=_SMTP_TIMEOUT) as server:
                    server.starttls()
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_address, to_email, msg.as_string())

            log.info("Email sent via SMTP to %s: %s", to_email, subject)
            return True
        except Exception as e:
            log.error("SMTP send failed to %s: %s", to_email, e)
            return False

    # ── Unified send methods ──

    def _send_email_sync(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send email using the best available backend."""
        if self.resend_api_key:
            return self._send_via_resend_sync(to_email, subject, html_body)
        return self._send_via_smtp_sync(to_email, subject, html_body)

    def _send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        """Synchronous wrapper for backward compatibility."""
        return self._send_email_sync(to_email, subject, html_body)

    async def _send_email_async(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send email in a thread executor to avoid blocking the event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._send_email_sync, to_email, subject, html_body
        )

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
