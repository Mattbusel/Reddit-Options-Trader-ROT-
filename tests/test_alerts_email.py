"""Tests for rot.alerts.email - Email alert system with Resend/SMTP backends.

Comprehensive test coverage for email sending:
- Backend selection (Resend API → SMTP fallback)
- Resend HTTP API path (JSON payload, headers, error handling)
- SMTP backend (SMTP_SSL, STARTTLS, authentication)
- Daily digest rendering (signal grouping, template rendering)
- Empty recipient handling
- Async execution (run_in_executor)
- Backend fallback on error
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call
import smtplib
from email.mime.multipart import MIMEMultipart

from rot.alerts.email import EmailAlerter, _RESEND_API_URL


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def resend_alerter():
    """EmailAlerter configured with Resend API key."""
    return EmailAlerter(
        resend_api_key="re_test_key_abc123",
        from_address="alerts@rot.app",
    )


@pytest.fixture
def smtp_alerter():
    """EmailAlerter configured with SMTP (no Resend key)."""
    return EmailAlerter(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="alerts@rot.app",
        smtp_password="smtp_password_123",
        from_address="alerts@rot.app",
        use_ssl=False,
    )


@pytest.fixture
def smtp_ssl_alerter():
    """EmailAlerter configured with SMTP_SSL (port 465)."""
    return EmailAlerter(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="alerts@rot.app",
        smtp_password="smtp_password_123",
        from_address="alerts@rot.app",
        use_ssl=True,
    )


@pytest.fixture
def unconfigured_alerter():
    """EmailAlerter with no backend configured."""
    return EmailAlerter(from_address="alerts@rot.app")


@pytest.fixture
def sample_signals():
    """Sample signals for daily digest."""
    return [
        {
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 0.85,
            "event_type": "product_news",
            "strategy": "debit_spread",
            "subreddit": "wallstreetbets",
            "post_title": "Tesla FSD approval imminent - calls printing",
            "time_horizon": "1w",
            "created_at": 1707955200.0,
            "price_at_signal": 200.50,
            "price_1h": 202.75,
            "price_4h": 205.00,
            "price_1d": 210.25,
        },
        {
            "ticker": "AAPL",
            "stance": "bearish",
            "confidence": 0.72,
            "event_type": "earnings_rumor",
            "strategy": "credit_spread",
            "subreddit": "options",
            "post_title": "AAPL Q4 earnings looking weak",
            "time_horizon": "earnings",
            "created_at": 1707955100.0,
            "price_at_signal": 180.00,
            "price_1d": 178.50,
        },
        {
            "ticker": "NVDA",
            "stance": "bullish",
            "confidence": 0.91,
            "event_type": "technical_breakout",
            "strategy": "none",
            "subreddit": "stocks",
            "post_title": "NVDA breaking out - massive volume",
            "time_horizon": "intraday",
            "created_at": 1707955000.0,
        },
    ]


@pytest.fixture
def sample_summary():
    """Sample summary stats for daily digest."""
    return {
        "total_signals": 15,
        "bullish_count": 9,
        "bearish_count": 6,
        "unique_tickers": 12,
        "avg_confidence": 0.78,
    }


# ══════════════════════════════════════════════════════════════════════════════
# EmailAlerter.__init__ and properties
# ══════════════════════════════════════════════════════════════════════════════


class TestEmailAlerterInit:
    """Test initialization and property methods."""

    def test_init_with_resend(self, resend_alerter):
        """Resend API key is stored correctly."""
        assert resend_alerter.resend_api_key == "re_test_key_abc123"
        assert resend_alerter.from_address == "alerts@rot.app"

    def test_init_with_smtp(self, smtp_alerter):
        """SMTP credentials are stored correctly."""
        assert smtp_alerter.smtp_host == "smtp.example.com"
        assert smtp_alerter.smtp_port == 587
        assert smtp_alerter.smtp_user == "alerts@rot.app"
        assert smtp_alerter.smtp_password == "smtp_password_123"
        assert smtp_alerter.use_ssl is False

    def test_init_with_smtp_ssl(self, smtp_ssl_alerter):
        """SMTP_SSL (port 465) is stored correctly."""
        assert smtp_ssl_alerter.smtp_port == 465
        assert smtp_ssl_alerter.use_ssl is True

    def test_is_configured_with_resend(self, resend_alerter):
        """is_configured returns True when Resend API key is set."""
        assert resend_alerter.is_configured is True

    def test_is_configured_with_smtp(self, smtp_alerter):
        """is_configured returns True when SMTP host and user are set."""
        assert smtp_alerter.is_configured is True

    def test_is_configured_unconfigured(self, unconfigured_alerter):
        """is_configured returns False when no backend is configured."""
        assert unconfigured_alerter.is_configured is False

    def test_backend_property_resend(self, resend_alerter):
        """backend property returns 'resend' when API key is set."""
        assert resend_alerter.backend == "resend"

    def test_backend_property_smtp(self, smtp_alerter):
        """backend property returns 'smtp' when only SMTP is configured."""
        assert smtp_alerter.backend == "smtp"

    def test_backend_property_prefers_resend(self):
        """backend property prefers Resend over SMTP when both are configured."""
        alerter = EmailAlerter(
            resend_api_key="re_key",
            smtp_host="smtp.example.com",
            smtp_user="user@example.com",
        )
        assert alerter.backend == "resend"


# ══════════════════════════════════════════════════════════════════════════════
# Resend HTTP API backend
# ══════════════════════════════════════════════════════════════════════════════


class TestResendBackend:
    """Test Resend HTTP API email sending path."""

    @patch("rot.alerts.email.httpx.post")
    def test_send_via_resend_success(self, mock_post, resend_alerter):
        """Resend API success (200) returns True."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "resend_email_123"},
        )

        result = resend_alerter._send_via_resend_sync(
            "user@example.com",
            "Test Subject",
            "<p>HTML body</p>",
        )

        assert result is True
        mock_post.assert_called_once()

    @patch("rot.alerts.email.httpx.post")
    def test_send_via_resend_201_success(self, mock_post, resend_alerter):
        """Resend API success (201) returns True."""
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: {"id": "resend_email_456"},
        )

        result = resend_alerter._send_via_resend_sync(
            "user@example.com",
            "Test",
            "<p>Body</p>",
        )

        assert result is True

    @patch("rot.alerts.email.httpx.post")
    def test_send_via_resend_headers(self, mock_post, resend_alerter):
        """Resend request includes correct Authorization header."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        resend_alerter._send_via_resend_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        call_args = mock_post.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer re_test_key_abc123"
        assert call_args[1]["headers"]["Content-Type"] == "application/json"

    @patch("rot.alerts.email.httpx.post")
    def test_send_via_resend_payload(self, mock_post, resend_alerter):
        """Resend request includes correct JSON payload."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        resend_alerter._send_via_resend_sync(
            "user@example.com",
            "Daily Digest",
            "<html><body>Test</body></html>",
        )

        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["from"] == "alerts@rot.app"
        assert payload["to"] == ["user@example.com"]
        assert payload["subject"] == "Daily Digest"
        assert payload["html"] == "<html><body>Test</body></html>"

    @patch("rot.alerts.email.httpx.post")
    def test_send_via_resend_endpoint(self, mock_post, resend_alerter):
        """Resend request hits correct API endpoint."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        resend_alerter._send_via_resend_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        call_args = mock_post.call_args
        assert call_args[0][0] == _RESEND_API_URL
        assert call_args[1]["timeout"] == 15.0

    @patch("rot.alerts.email.httpx.post")
    def test_send_via_resend_400_error(self, mock_post, resend_alerter):
        """Resend API 400 error returns False and logs error."""
        mock_post.return_value = MagicMock(
            status_code=400,
            text='{"error": "invalid_email"}',
        )

        result = resend_alerter._send_via_resend_sync(
            "invalid-email",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    @patch("rot.alerts.email.httpx.post")
    def test_send_via_resend_500_error(self, mock_post, resend_alerter):
        """Resend API 500 error returns False."""
        mock_post.return_value = MagicMock(
            status_code=500,
            text="Internal Server Error",
        )

        result = resend_alerter._send_via_resend_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    @patch("rot.alerts.email.httpx.post")
    def test_send_via_resend_network_exception(self, mock_post, resend_alerter):
        """Resend network exception returns False."""
        mock_post.side_effect = Exception("Connection timeout")

        result = resend_alerter._send_via_resend_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    @patch("rot.alerts.email.httpx.post")
    def test_send_via_resend_malformed_response(self, mock_post, resend_alerter):
        """Resend malformed JSON response is handled gracefully."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {},  # No "id" field
        )

        result = resend_alerter._send_via_resend_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        # Still returns True on 200, even if "id" is missing
        assert result is True


# ══════════════════════════════════════════════════════════════════════════════
# SMTP backend
# ══════════════════════════════════════════════════════════════════════════════


class TestSMTPBackend:
    """Test SMTP email sending path."""

    @patch("rot.alerts.email.smtplib.SMTP")
    def test_send_via_smtp_starttls_success(self, mock_smtp_class, smtp_alerter):
        """SMTP STARTTLS success returns True."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        result = smtp_alerter._send_via_smtp_sync(
            "user@example.com",
            "Test Subject",
            "<p>HTML body</p>",
        )

        assert result is True
        mock_smtp_class.assert_called_once_with(
            "smtp.example.com", 587, timeout=15
        )
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with(
            "alerts@rot.app", "smtp_password_123"
        )
        mock_server.sendmail.assert_called_once()

    @patch("rot.alerts.email.smtplib.SMTP_SSL")
    def test_send_via_smtp_ssl_success(self, mock_smtp_ssl_class, smtp_ssl_alerter):
        """SMTP_SSL success returns True."""
        mock_server = MagicMock()
        mock_smtp_ssl_class.return_value.__enter__.return_value = mock_server

        result = smtp_ssl_alerter._send_via_smtp_sync(
            "user@example.com",
            "Test Subject",
            "<p>HTML body</p>",
        )

        assert result is True
        mock_smtp_ssl_class.assert_called_once_with(
            "smtp.gmail.com", 465, timeout=15
        )
        # SMTP_SSL should not call starttls()
        mock_server.starttls.assert_not_called()
        mock_server.login.assert_called_once()
        mock_server.sendmail.assert_called_once()

    @patch("rot.alerts.email.smtplib.SMTP_SSL")
    def test_send_via_smtp_port_465_uses_ssl(self, mock_smtp_ssl_class):
        """Port 465 forces SMTP_SSL even if use_ssl=False."""
        alerter = EmailAlerter(
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_user="user@example.com",
            smtp_password="password",
            use_ssl=False,  # Explicit False
        )
        mock_server = MagicMock()
        mock_smtp_ssl_class.return_value.__enter__.return_value = mock_server

        alerter._send_via_smtp_sync("to@example.com", "Subject", "<p>Body</p>")

        mock_smtp_ssl_class.assert_called_once()

    @patch("rot.alerts.email.smtplib.SMTP")
    def test_send_via_smtp_message_construction(self, mock_smtp_class, smtp_alerter):
        """SMTP message is constructed correctly with MIME multipart."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        smtp_alerter._send_via_smtp_sync(
            "user@example.com",
            "Test Subject",
            "<html><body>Test Body</body></html>",
        )

        sendmail_args = mock_server.sendmail.call_args
        from_addr = sendmail_args[0][0]
        to_addr = sendmail_args[0][1]
        msg_str = sendmail_args[0][2]

        assert from_addr == "alerts@rot.app"
        assert to_addr == "user@example.com"
        assert "Test Subject" in msg_str
        assert "<html><body>Test Body</body></html>" in msg_str
        assert "Content-Type: text/html" in msg_str

    @patch("rot.alerts.email.smtplib.SMTP")
    def test_send_via_smtp_no_auth(self, mock_smtp_class):
        """SMTP without credentials skips login()."""
        alerter = EmailAlerter(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="",
            smtp_password="",
        )
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        alerter._send_via_smtp_sync("to@example.com", "Subject", "<p>Body</p>")

        mock_server.login.assert_not_called()
        mock_server.sendmail.assert_called_once()

    @patch("rot.alerts.email.smtplib.SMTP_SSL")
    def test_send_via_smtp_ssl_no_auth(self, mock_smtp_ssl_class, smtp_ssl_alerter):
        """SMTP_SSL without credentials skips login()."""
        smtp_ssl_alerter.smtp_user = ""
        smtp_ssl_alerter.smtp_password = ""
        mock_server = MagicMock()
        mock_smtp_ssl_class.return_value.__enter__.return_value = mock_server

        smtp_ssl_alerter._send_via_smtp_sync("to@example.com", "Subject", "<p>Body</p>")

        mock_server.login.assert_not_called()
        mock_server.sendmail.assert_called_once()

    @patch("rot.alerts.email.smtplib.SMTP")
    def test_send_via_smtp_auth_failure(self, mock_smtp_class, smtp_alerter):
        """SMTP authentication failure returns False."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"Authentication failed"
        )

        result = smtp_alerter._send_via_smtp_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    @patch("rot.alerts.email.smtplib.SMTP")
    def test_send_via_smtp_connection_failure(self, mock_smtp_class, smtp_alerter):
        """SMTP connection failure returns False."""
        mock_smtp_class.side_effect = smtplib.SMTPConnectError(
            421, b"Service not available"
        )

        result = smtp_alerter._send_via_smtp_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    @patch("rot.alerts.email.smtplib.SMTP")
    def test_send_via_smtp_timeout(self, mock_smtp_class, smtp_alerter):
        """SMTP timeout is passed to smtplib.SMTP()."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        smtp_alerter._send_via_smtp_sync("to@example.com", "Subject", "<p>Body</p>")

        call_args = mock_smtp_class.call_args
        assert call_args[1]["timeout"] == 15


# ══════════════════════════════════════════════════════════════════════════════
# Unified send methods
# ══════════════════════════════════════════════════════════════════════════════


class TestUnifiedSendMethods:
    """Test backend selection and unified send interface."""

    @patch("rot.alerts.email.httpx.post")
    def test_send_email_sync_prefers_resend(self, mock_post, resend_alerter):
        """_send_email_sync uses Resend when API key is present."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        result = resend_alerter._send_email_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is True
        mock_post.assert_called_once()

    @patch("rot.alerts.email.smtplib.SMTP")
    def test_send_email_sync_uses_smtp_fallback(self, mock_smtp_class, smtp_alerter):
        """_send_email_sync uses SMTP when no Resend key."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        result = smtp_alerter._send_email_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is True
        mock_smtp_class.assert_called_once()

    @patch("rot.alerts.email.httpx.post")
    def test_send_email_wrapper_calls_sync(self, mock_post, resend_alerter):
        """_send_email() is a synchronous wrapper for _send_email_sync()."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        result = resend_alerter._send_email(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is True
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_send_email_async_runs_in_executor(self, mock_post, resend_alerter):
        """_send_email_async runs sync send in thread executor."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        result = await resend_alerter._send_email_async(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is True
        mock_post.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# Daily digest
# ══════════════════════════════════════════════════════════════════════════════


class TestDailyDigest:
    """Test daily digest email generation and sending."""

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_send_daily_digest_success(
        self, mock_post, resend_alerter, sample_signals, sample_summary
    ):
        """Daily digest sends successfully via Resend."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "digest_123"},
        )

        result = await resend_alerter.send_daily_digest(
            "user@example.com",
            sample_signals,
            sample_summary,
        )

        assert result is True
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_send_daily_digest_subject_line(
        self, mock_post, resend_alerter, sample_signals, sample_summary
    ):
        """Daily digest subject line includes signal count."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        await resend_alerter.send_daily_digest(
            "user@example.com",
            sample_signals,
            sample_summary,
        )

        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["subject"] == "ROT Daily Digest: 3 signals"

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_send_daily_digest_subject_singular(
        self, mock_post, resend_alerter, sample_summary
    ):
        """Daily digest subject uses singular 'signal' for count=1."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        await resend_alerter.send_daily_digest(
            "user@example.com",
            [sample_summary],  # 1 signal
            sample_summary,
        )

        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["subject"] == "ROT Daily Digest: 1 signal"

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_send_daily_digest_html_contains_signals(
        self, mock_post, resend_alerter, sample_signals, sample_summary
    ):
        """Daily digest HTML body includes signal tickers."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        await resend_alerter.send_daily_digest(
            "user@example.com",
            sample_signals,
            sample_summary,
        )

        call_args = mock_post.call_args
        html = call_args[1]["json"]["html"]
        assert "TSLA" in html
        assert "AAPL" in html
        assert "NVDA" in html

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_send_daily_digest_html_contains_summary_stats(
        self, mock_post, resend_alerter, sample_signals, sample_summary
    ):
        """Daily digest HTML includes summary stats."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        await resend_alerter.send_daily_digest(
            "user@example.com",
            sample_signals,
            sample_summary,
        )

        call_args = mock_post.call_args
        html = call_args[1]["json"]["html"]
        # Summary has total_signals=15, bullish=9, bearish=6, unique=12
        assert "15" in html  # total signals
        assert "9" in html  # bullish
        assert "6" in html  # bearish
        assert "12" in html  # unique tickers

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_send_daily_digest_empty_signals(
        self, mock_post, resend_alerter, sample_summary
    ):
        """Daily digest with empty signals shows 'no signals' message."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        await resend_alerter.send_daily_digest(
            "user@example.com",
            [],
            sample_summary,
        )

        call_args = mock_post.call_args
        html = call_args[1]["json"]["html"]
        assert "No signals generated in the last 24 hours" in html

    @pytest.mark.asyncio
    @patch("rot.alerts.email.smtplib.SMTP")
    async def test_send_daily_digest_via_smtp(
        self, mock_smtp_class, smtp_alerter, sample_signals, sample_summary
    ):
        """Daily digest can be sent via SMTP backend."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        result = await smtp_alerter.send_daily_digest(
            "user@example.com",
            sample_signals,
            sample_summary,
        )

        assert result is True
        mock_smtp_class.assert_called_once()
        sendmail_args = mock_server.sendmail.call_args[0]
        msg_str = sendmail_args[2]
        assert "TSLA" in msg_str
        assert "AAPL" in msg_str


# ══════════════════════════════════════════════════════════════════════════════
# Backend fallback and edge cases
# ══════════════════════════════════════════════════════════════════════════════


class TestBackendFallback:
    """Test backend fallback behavior when primary backend fails."""

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_resend_failure_does_not_auto_fallback_to_smtp(
        self, mock_post, resend_alerter
    ):
        """Resend failure does NOT automatically fall back to SMTP.

        The alerter uses either Resend OR SMTP, not both in sequence.
        If Resend is configured and fails, it returns False.
        """
        mock_post.return_value = MagicMock(
            status_code=500,
            text="Server error",
        )

        result = await resend_alerter._send_email_async(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    @pytest.mark.asyncio
    @patch("rot.alerts.email.smtplib.SMTP")
    async def test_smtp_failure_returns_false(self, mock_smtp_class, smtp_alerter):
        """SMTP failure returns False."""
        mock_smtp_class.side_effect = Exception("SMTP connection failed")

        result = await smtp_alerter._send_email_async(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    def test_unconfigured_alerter_returns_false(self, unconfigured_alerter):
        """Unconfigured alerter (no Resend, no SMTP) returns False."""
        result = unconfigured_alerter._send_email_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_empty_recipient_email(self, mock_post, resend_alerter):
        """Empty recipient email still attempts send (backend will reject)."""
        mock_post.return_value = MagicMock(
            status_code=400,
            text="Invalid recipient",
        )

        result = await resend_alerter._send_email_async("", "Subject", "<p>Body</p>")

        assert result is False

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_malformed_email_address(self, mock_post, resend_alerter):
        """Malformed email address (backend will reject)."""
        mock_post.return_value = MagicMock(
            status_code=400,
            text="Invalid email format",
        )

        result = await resend_alerter._send_email_async(
            "not-an-email",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_empty_subject(self, mock_post, resend_alerter):
        """Empty subject is allowed (backend may accept or reject)."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        result = await resend_alerter._send_email_async(
            "user@example.com",
            "",
            "<p>Body</p>",
        )

        assert result is True

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_empty_html_body(self, mock_post, resend_alerter):
        """Empty HTML body is allowed."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        result = await resend_alerter._send_email_async(
            "user@example.com",
            "Subject",
            "",
        )

        assert result is True

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_large_html_body(self, mock_post, resend_alerter):
        """Large HTML body (10KB+) is sent successfully."""
        large_html = "<html><body>" + "x" * 50000 + "</body></html>"
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        result = await resend_alerter._send_email_async(
            "user@example.com",
            "Subject",
            large_html,
        )

        assert result is True

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_unicode_in_subject(self, mock_post, resend_alerter):
        """Unicode characters in subject are handled correctly."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        result = await resend_alerter._send_email_async(
            "user@example.com",
            "🚀 TSLA to the moon 📈",
            "<p>Body</p>",
        )

        assert result is True

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_unicode_in_html_body(self, mock_post, resend_alerter):
        """Unicode characters in HTML body are handled correctly."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        result = await resend_alerter._send_email_async(
            "user@example.com",
            "Subject",
            "<p>TSLA 🚀 bullish 📈</p>",
        )

        assert result is True

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_html_with_special_chars(self, mock_post, resend_alerter):
        """HTML with special characters (<, >, &) is sent correctly."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "123"},
        )

        result = await resend_alerter._send_email_async(
            "user@example.com",
            "Subject",
            "<p>Price > $100 &amp; < $200</p>",
        )

        assert result is True

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_resend_rate_limit_429(self, mock_post, resend_alerter):
        """Resend API rate limit (429) returns False."""
        mock_post.return_value = MagicMock(
            status_code=429,
            text="Too many requests",
        )

        result = await resend_alerter._send_email_async(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    @pytest.mark.asyncio
    @patch("rot.alerts.email.httpx.post")
    async def test_resend_unauthorized_401(self, mock_post, resend_alerter):
        """Resend API unauthorized (401) returns False."""
        mock_post.return_value = MagicMock(
            status_code=401,
            text="Unauthorized - invalid API key",
        )

        result = await resend_alerter._send_email_async(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    @patch("rot.alerts.email.smtplib.SMTP")
    def test_smtp_recipient_refused(self, mock_smtp_class, smtp_alerter):
        """SMTP recipient refused returns False."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server
        mock_server.sendmail.side_effect = smtplib.SMTPRecipientsRefused(
            {"user@example.com": (550, b"User unknown")}
        )

        result = smtp_alerter._send_via_smtp_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False

    @patch("rot.alerts.email.smtplib.SMTP")
    def test_smtp_sender_refused(self, mock_smtp_class, smtp_alerter):
        """SMTP sender refused returns False."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server
        mock_server.sendmail.side_effect = smtplib.SMTPSenderRefused(
            550, b"Sender address rejected", "alerts@rot.app"
        )

        result = smtp_alerter._send_via_smtp_sync(
            "user@example.com",
            "Subject",
            "<p>Body</p>",
        )

        assert result is False
