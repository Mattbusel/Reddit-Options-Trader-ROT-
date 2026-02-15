"""Structured security logging for ROT.

Provides structured logging for security-relevant events:
- Authentication attempts (success/failure)
- Rate limit violations
- API key generation/revocation
- Admin tier elevation
- Suspicious activity detection
- Secret key validation failures

All logs are JSON-formatted with consistent fields for easy parsing and alerting.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

# Security logger separate from main application logger
security_logger = logging.getLogger("rot.security")


def log_auth_attempt(
    event: str,
    email: str,
    ip: str,
    success: bool,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Log an authentication attempt.

    Args:
        event: Type of auth event (login, register, api_key, etc.)
        email: User email address
        ip: IP address of request
        success: Whether the attempt succeeded
        reason: Optional reason for failure (invalid_password, rate_limited, etc.)
        metadata: Additional context (user_agent, tier, etc.)
    """
    log_data = {
        "event_type": "auth_attempt",
        "auth_event": event,
        "timestamp": datetime.utcnow().isoformat(),
        "email": email,
        "ip_address": ip,
        "success": success,
        "reason": reason,
        "metadata": metadata or {},
    }

    if success:
        security_logger.info(json.dumps(log_data))
    else:
        security_logger.warning(json.dumps(log_data))


def log_rate_limit_violation(
    endpoint: str,
    ip: str,
    attempt_count: int,
    limit: int,
    window_seconds: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Log a rate limit violation.

    Args:
        endpoint: The rate-limited endpoint (login, register, etc.)
        ip: IP address that exceeded limit
        attempt_count: Number of attempts made
        limit: Maximum allowed attempts
        window_seconds: Time window for the limit
        metadata: Additional context
    """
    log_data = {
        "event_type": "rate_limit_violation",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoint": endpoint,
        "ip_address": ip,
        "attempt_count": attempt_count,
        "limit": limit,
        "window_seconds": window_seconds,
        "metadata": metadata or {},
    }

    security_logger.warning(json.dumps(log_data))


def log_api_key_event(
    event: str,
    user_id: int,
    email: str,
    ip: str,
    key_prefix: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Log API key lifecycle events.

    Args:
        event: Event type (created, revoked, rotated, validated)
        user_id: User ID
        email: User email
        ip: IP address of request
        key_prefix: First 8 chars of API key (for identification)
        metadata: Additional context (tier, scopes, etc.)
    """
    log_data = {
        "event_type": "api_key_event",
        "api_key_event": event,
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": user_id,
        "email": email,
        "ip_address": ip,
        "key_prefix": key_prefix,
        "metadata": metadata or {},
    }

    security_logger.info(json.dumps(log_data))


def log_admin_elevation(
    user_id: int,
    email: str,
    ip: str,
    granted_by: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Log admin tier elevation events.

    Args:
        user_id: User ID being elevated
        email: User email
        ip: IP address of request
        granted_by: Who granted admin access (email or "system")
        reason: Reason for elevation
        metadata: Additional context
    """
    log_data = {
        "event_type": "admin_elevation",
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": user_id,
        "email": email,
        "ip_address": ip,
        "granted_by": granted_by,
        "reason": reason,
        "metadata": metadata or {},
    }

    security_logger.warning(json.dumps(log_data))


def log_suspicious_activity(
    activity_type: str,
    ip: str,
    description: str,
    severity: str = "medium",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Log suspicious activity detection.

    Args:
        activity_type: Type of suspicious activity (credential_stuffing, token_theft, etc.)
        ip: IP address associated with activity
        description: Human-readable description
        severity: Severity level (low, medium, high, critical)
        metadata: Additional context
    """
    log_data = {
        "event_type": "suspicious_activity",
        "activity_type": activity_type,
        "timestamp": datetime.utcnow().isoformat(),
        "ip_address": ip,
        "description": description,
        "severity": severity,
        "metadata": metadata or {},
    }

    if severity in ("high", "critical"):
        security_logger.error(json.dumps(log_data))
    else:
        security_logger.warning(json.dumps(log_data))


def log_secret_validation_failure(
    environment: str,
    secret_length: int,
    is_default: bool,
    reason: str,
) -> None:
    """Log secret key validation failures.

    Args:
        environment: Environment where validation failed (production, staging, etc.)
        secret_length: Length of the invalid secret
        is_default: Whether the default secret was used
        reason: Reason for failure
    """
    log_data = {
        "event_type": "secret_validation_failure",
        "timestamp": datetime.utcnow().isoformat(),
        "environment": environment,
        "secret_length": secret_length,
        "is_default_secret": is_default,
        "reason": reason,
    }

    security_logger.error(json.dumps(log_data))


def log_backup_event(
    event: str,
    success: bool,
    backup_file: Optional[str] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Log database backup events.

    Args:
        event: Event type (created, restored, cleanup, failed)
        success: Whether the operation succeeded
        backup_file: Backup filename
        error: Error message if failed
        metadata: Additional context (size, duration, etc.)
    """
    log_data = {
        "event_type": "backup_event",
        "backup_event": event,
        "timestamp": datetime.utcnow().isoformat(),
        "success": success,
        "backup_file": backup_file,
        "error": error,
        "metadata": metadata or {},
    }

    if success:
        security_logger.info(json.dumps(log_data))
    else:
        security_logger.error(json.dumps(log_data))


def log_tier_gate_block(
    user_id: int,
    email: str,
    endpoint: str,
    required_tier: str,
    user_tier: str,
    feature: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Log tier gate access blocks.

    Args:
        user_id: User ID blocked
        email: User email
        endpoint: Endpoint that was blocked
        required_tier: Minimum tier required
        user_tier: User's actual tier
        feature: Feature being gated
        metadata: Additional context
    """
    log_data = {
        "event_type": "tier_gate_block",
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": user_id,
        "email": email,
        "endpoint": endpoint,
        "required_tier": required_tier,
        "user_tier": user_tier,
        "feature": feature,
        "metadata": metadata or {},
    }

    security_logger.info(json.dumps(log_data))


def log_data_export(
    user_id: int,
    email: str,
    export_type: str,
    record_count: int,
    format: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Log enterprise data export events.

    Args:
        user_id: User requesting export
        email: User email
        export_type: Type of export (signals, analytics, etc.)
        record_count: Number of records exported
        format: Export format (csv, json, parquet)
        metadata: Additional context
    """
    log_data = {
        "event_type": "data_export",
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": user_id,
        "email": email,
        "export_type": export_type,
        "record_count": record_count,
        "format": format,
        "metadata": metadata or {},
    }

    security_logger.info(json.dumps(log_data))


def configure_security_logger(
    log_file: Optional[str] = None,
    console_output: bool = True,
    json_format: bool = True,
) -> None:
    """Configure the security logger.

    Args:
        log_file: Path to log file (if None, no file logging)
        console_output: Whether to also log to console
        json_format: Whether to use JSON formatting (recommended)
    """
    security_logger.setLevel(logging.INFO)
    security_logger.propagate = False  # Don't propagate to root logger

    # Remove existing handlers
    security_logger.handlers.clear()

    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        if json_format:
            # Already JSON-formatted by log functions
            file_handler.setFormatter(logging.Formatter("%(message)s"))
        else:
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
        security_logger.addHandler(file_handler)

    # Console handler
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)  # Only warnings and above to console
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        security_logger.addHandler(console_handler)
