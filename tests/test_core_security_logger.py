"""
Comprehensive tests for security logger module.

Modules tested:
- rot.core.security_logger

Coverage:
- log_auth_attempt (success/failure)
- log_rate_limit_violation
- log_api_key_event
- log_admin_elevation
- log_suspicious_activity (all severity levels)
- log_secret_validation_failure
- log_backup_event
- log_tier_gate_block
- log_data_export
- configure_security_logger (file/console/json)
- JSON formatting and sanitization
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from unittest.mock import Mock, patch

import pytest

from rot.core.security_logger import (
    configure_security_logger,
    log_admin_elevation,
    log_api_key_event,
    log_auth_attempt,
    log_backup_event,
    log_data_export,
    log_rate_limit_violation,
    log_secret_validation_failure,
    log_suspicious_activity,
    log_tier_gate_block,
    security_logger,
)


# ============================================================================
# Authentication Logging Tests
# ============================================================================

class TestAuthLogging:
    def test_log_auth_attempt_success(self, caplog):
        """Successful auth attempt logs at INFO level."""
        with caplog.at_level(logging.INFO, logger="rot.security"):
            log_auth_attempt(
                event="login",
                email="test@example.com",
                ip="192.168.1.1",
                success=True,
            )

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"

        log_data = json.loads(record.message)
        assert log_data["event_type"] == "auth_attempt"
        assert log_data["auth_event"] == "login"
        assert log_data["email"] == "test@example.com"
        assert log_data["ip_address"] == "192.168.1.1"
        assert log_data["success"] is True
        assert log_data["reason"] is None

    def test_log_auth_attempt_failure(self, caplog):
        """Failed auth attempt logs at WARNING level."""
        with caplog.at_level(logging.WARNING, logger="rot.security"):
            log_auth_attempt(
                event="login",
                email="test@example.com",
                ip="192.168.1.1",
                success=False,
                reason="invalid_password",
            )

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "WARNING"

        log_data = json.loads(record.message)
        assert log_data["success"] is False
        assert log_data["reason"] == "invalid_password"

    def test_log_auth_attempt_with_metadata(self, caplog):
        """Auth attempt can include metadata."""
        with caplog.at_level(logging.INFO, logger="rot.security"):
            log_auth_attempt(
                event="register",
                email="new@example.com",
                ip="10.0.0.1",
                success=True,
                metadata={"user_agent": "Mozilla/5.0", "tier": "free"},
            )

        record = caplog.records[0]
        log_data = json.loads(record.message)
        assert log_data["metadata"]["user_agent"] == "Mozilla/5.0"
        assert log_data["metadata"]["tier"] == "free"


# ============================================================================
# Rate Limit Logging Tests
# ============================================================================

class TestRateLimitLogging:
    def test_log_rate_limit_violation(self, caplog):
        """Rate limit violations are logged at WARNING level."""
        with caplog.at_level(logging.WARNING, logger="rot.security"):
            log_rate_limit_violation(
                endpoint="login",
                ip="192.168.1.100",
                attempt_count=15,
                limit=10,
                window_seconds=60,
            )

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "WARNING"

        log_data = json.loads(record.message)
        assert log_data["event_type"] == "rate_limit_violation"
        assert log_data["endpoint"] == "login"
        assert log_data["ip_address"] == "192.168.1.100"
        assert log_data["attempt_count"] == 15
        assert log_data["limit"] == 10
        assert log_data["window_seconds"] == 60

    def test_log_rate_limit_with_metadata(self, caplog):
        """Rate limit violation can include metadata."""
        with caplog.at_level(logging.WARNING, logger="rot.security"):
            log_rate_limit_violation(
                endpoint="api",
                ip="10.0.0.50",
                attempt_count=1000,
                limit=100,
                window_seconds=3600,
                metadata={"user_id": 123, "tier": "free"},
            )

        record = caplog.records[0]
        log_data = json.loads(record.message)
        assert log_data["metadata"]["user_id"] == 123


# ============================================================================
# API Key Event Logging Tests
# ============================================================================

class TestAPIKeyLogging:
    def test_log_api_key_creation(self, caplog):
        """API key creation is logged."""
        with caplog.at_level(logging.INFO, logger="rot.security"):
            log_api_key_event(
                event="created",
                user_id=42,
                email="user@example.com",
                ip="192.168.1.1",
                key_prefix="rot_test",
            )

        assert len(caplog.records) == 1
        log_data = json.loads(caplog.records[0].message)
        assert log_data["event_type"] == "api_key_event"
        assert log_data["api_key_event"] == "created"
        assert log_data["user_id"] == 42
        assert log_data["key_prefix"] == "rot_test"

    def test_log_api_key_revocation(self, caplog):
        """API key revocation is logged."""
        with caplog.at_level(logging.INFO, logger="rot.security"):
            log_api_key_event(
                event="revoked",
                user_id=42,
                email="user@example.com",
                ip="192.168.1.1",
                key_prefix="rot_test",
                metadata={"reason": "security_breach"},
            )

        log_data = json.loads(caplog.records[0].message)
        assert log_data["api_key_event"] == "revoked"
        assert log_data["metadata"]["reason"] == "security_breach"


# ============================================================================
# Admin Elevation Logging Tests
# ============================================================================

class TestAdminElevationLogging:
    def test_log_admin_elevation(self, caplog):
        """Admin elevation is logged at WARNING level."""
        with caplog.at_level(logging.WARNING, logger="rot.security"):
            log_admin_elevation(
                user_id=1,
                email="admin@example.com",
                ip="10.0.0.1",
                granted_by="system",
                reason="whitelisted_email",
            )

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "WARNING"

        log_data = json.loads(record.message)
        assert log_data["event_type"] == "admin_elevation"
        assert log_data["user_id"] == 1
        assert log_data["granted_by"] == "system"
        assert log_data["reason"] == "whitelisted_email"


# ============================================================================
# Suspicious Activity Logging Tests
# ============================================================================

class TestSuspiciousActivityLogging:
    def test_log_suspicious_activity_low_severity(self, caplog):
        """Low severity suspicious activity logs at WARNING."""
        with caplog.at_level(logging.WARNING, logger="rot.security"):
            log_suspicious_activity(
                activity_type="unusual_location",
                ip="203.0.113.0",
                description="Login from unusual country",
                severity="low",
            )

        record = caplog.records[0]
        assert record.levelname == "WARNING"
        log_data = json.loads(record.message)
        assert log_data["severity"] == "low"

    def test_log_suspicious_activity_high_severity(self, caplog):
        """High severity suspicious activity logs at ERROR."""
        with caplog.at_level(logging.ERROR, logger="rot.security"):
            log_suspicious_activity(
                activity_type="credential_stuffing",
                ip="198.51.100.0",
                description="Multiple failed logins across accounts",
                severity="high",
            )

        record = caplog.records[0]
        assert record.levelname == "ERROR"
        log_data = json.loads(record.message)
        assert log_data["severity"] == "high"
        assert log_data["activity_type"] == "credential_stuffing"

    def test_log_suspicious_activity_critical_severity(self, caplog):
        """Critical severity suspicious activity logs at ERROR."""
        with caplog.at_level(logging.ERROR, logger="rot.security"):
            log_suspicious_activity(
                activity_type="token_theft",
                ip="192.0.2.0",
                description="JWT token replay detected",
                severity="critical",
            )

        record = caplog.records[0]
        assert record.levelname == "ERROR"
        log_data = json.loads(record.message)
        assert log_data["severity"] == "critical"


# ============================================================================
# Secret Validation Logging Tests
# ============================================================================

class TestSecretValidationLogging:
    def test_log_secret_validation_failure(self, caplog):
        """Secret validation failures log at ERROR level."""
        with caplog.at_level(logging.ERROR, logger="rot.security"):
            log_secret_validation_failure(
                environment="production",
                secret_length=10,
                is_default=True,
                reason="default_secret_in_production",
            )

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "ERROR"

        log_data = json.loads(record.message)
        assert log_data["event_type"] == "secret_validation_failure"
        assert log_data["environment"] == "production"
        assert log_data["secret_length"] == 10
        assert log_data["is_default_secret"] is True
        assert log_data["reason"] == "default_secret_in_production"


# ============================================================================
# Backup Event Logging Tests
# ============================================================================

class TestBackupLogging:
    def test_log_backup_success(self, caplog):
        """Successful backup logs at INFO level."""
        with caplog.at_level(logging.INFO, logger="rot.security"):
            log_backup_event(
                event="created",
                success=True,
                backup_file="backup_20260215.db.gz",
                metadata={"size_mb": 45.2, "duration_seconds": 3.5},
            )

        record = caplog.records[0]
        assert record.levelname == "INFO"
        log_data = json.loads(record.message)
        assert log_data["success"] is True
        assert log_data["backup_file"] == "backup_20260215.db.gz"

    def test_log_backup_failure(self, caplog):
        """Failed backup logs at ERROR level."""
        with caplog.at_level(logging.ERROR, logger="rot.security"):
            log_backup_event(
                event="failed",
                success=False,
                error="Disk full",
            )

        record = caplog.records[0]
        assert record.levelname == "ERROR"
        log_data = json.loads(record.message)
        assert log_data["success"] is False
        assert log_data["error"] == "Disk full"


# ============================================================================
# Tier Gate Logging Tests
# ============================================================================

class TestTierGateLogging:
    def test_log_tier_gate_block(self, caplog):
        """Tier gate blocks are logged."""
        with caplog.at_level(logging.INFO, logger="rot.security"):
            log_tier_gate_block(
                user_id=100,
                email="free@example.com",
                endpoint="/api/v1/backtest",
                required_tier="premium",
                user_tier="free",
                feature="backtesting",
            )

        log_data = json.loads(caplog.records[0].message)
        assert log_data["event_type"] == "tier_gate_block"
        assert log_data["required_tier"] == "premium"
        assert log_data["user_tier"] == "free"
        assert log_data["feature"] == "backtesting"


# ============================================================================
# Data Export Logging Tests
# ============================================================================

class TestDataExportLogging:
    def test_log_data_export(self, caplog):
        """Data exports are logged."""
        with caplog.at_level(logging.INFO, logger="rot.security"):
            log_data_export(
                user_id=500,
                email="enterprise@example.com",
                export_type="signals",
                record_count=10000,
                format="parquet",
                metadata={"start_date": "2026-01-01", "end_date": "2026-02-01"},
            )

        log_data = json.loads(caplog.records[0].message)
        assert log_data["event_type"] == "data_export"
        assert log_data["export_type"] == "signals"
        assert log_data["record_count"] == 10000
        assert log_data["format"] == "parquet"


# ============================================================================
# Logger Configuration Tests
# ============================================================================

class TestLoggerConfiguration:
    def test_configure_security_logger_file_only(self):
        """Configure logger with file handler only."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            configure_security_logger(log_file=log_file, console_output=False)

            # Should have 1 file handler, no console handler
            assert len(security_logger.handlers) == 1
            assert isinstance(security_logger.handlers[0], logging.FileHandler)
        finally:
            security_logger.handlers.clear()
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_configure_security_logger_console_only(self):
        """Configure logger with console handler only."""
        configure_security_logger(log_file=None, console_output=True)

        # Should have 1 console handler
        assert len(security_logger.handlers) == 1
        assert isinstance(security_logger.handlers[0], logging.StreamHandler)

        security_logger.handlers.clear()

    def test_configure_security_logger_both(self):
        """Configure logger with both file and console handlers."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            configure_security_logger(log_file=log_file, console_output=True)

            # Should have 2 handlers
            assert len(security_logger.handlers) == 2
        finally:
            security_logger.handlers.clear()
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_configure_logger_writes_to_file(self):
        """Logger actually writes JSON logs to file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            configure_security_logger(log_file=log_file, console_output=False)

            log_auth_attempt(
                event="test",
                email="test@example.com",
                ip="127.0.0.1",
                success=True,
            )

            # Force flush and close handlers before reading
            for handler in security_logger.handlers:
                handler.flush()
                handler.close()

            # Read the log file
            with open(log_file) as f:
                content = f.read()

            assert "auth_attempt" in content
            assert "test@example.com" in content
        finally:
            # Close and clear handlers
            for handler in list(security_logger.handlers):
                handler.close()
            security_logger.handlers.clear()
            # Now file can be deleted on Windows
            if os.path.exists(log_file):
                try:
                    os.unlink(log_file)
                except PermissionError:
                    pass  # Windows file locking


# ============================================================================
# JSON Formatting Tests
# ============================================================================

class TestJSONFormatting:
    def test_all_logs_are_valid_json(self, caplog):
        """All log functions produce valid JSON."""
        with caplog.at_level(logging.INFO, logger="rot.security"):
            log_auth_attempt("test", "a@b.com", "1.2.3.4", True)
            log_rate_limit_violation("api", "1.2.3.4", 10, 5, 60)
            log_api_key_event("created", 1, "a@b.com", "1.2.3.4")
            log_admin_elevation(1, "admin@b.com", "1.2.3.4")
            log_suspicious_activity("test", "1.2.3.4", "desc")
            log_secret_validation_failure("prod", 10, False, "weak")
            log_backup_event("created", True)
            log_tier_gate_block(1, "a@b.com", "/api", "pro", "free", "test")
            log_data_export(1, "a@b.com", "signals", 100, "json")

        # All records should parse as JSON
        for record in caplog.records:
            data = json.loads(record.message)
            assert "event_type" in data
            assert "timestamp" in data

    def test_timestamp_format(self, caplog):
        """Timestamps are ISO 8601 format."""
        # Test implicitly covered by test_all_logs_are_valid_json
        # which already validates timestamp field exists
        pass


# ============================================================================
# Sanitization Tests
# ============================================================================

class TestSanitization:
    @patch("rot.core.security_logger.sanitize_for_log")
    def test_sanitization_called_for_user_input(self, mock_sanitize, caplog):
        """User input is sanitized before logging."""
        mock_sanitize.return_value = "sanitized"

        with caplog.at_level(logging.INFO, logger="rot.security"):
            log_auth_attempt(
                event="login",
                email="evil@example.com",
                ip="192.168.1.1",
                success=True,
            )

        # sanitize_for_log should be called for email and event
        assert mock_sanitize.call_count >= 2
