"""Real-time alert system for the Reddit Options Trader.

Provides condition-based alert rules with cooldown enforcement, severity
classification, and a summary reporting interface.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Alert condition types
# ---------------------------------------------------------------------------

class AlertCondition:
    """Namespace for alert condition type constants."""

    PRICE_MOVE: str = "PRICE_MOVE"
    VOLUME_SPIKE: str = "VOLUME_SPIKE"
    SENTIMENT_SHIFT: str = "SENTIMENT_SHIFT"
    IV_CHANGE: str = "IV_CHANGE"
    OPTIONS_FLOW: str = "OPTIONS_FLOW"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    """A triggered alert instance."""

    id: str
    ticker: str
    condition_type: str
    threshold: float
    current_value: float
    triggered_at: datetime
    message: str
    severity: str  # "info" | "warning" | "critical"


@dataclass
class AlertRule:
    """A persistent rule that is evaluated against incoming market data."""

    id: str
    ticker: str
    condition_type: str
    threshold: float
    comparison: str  # "gt" | "lt" | "gte" | "lte"
    cooldown_seconds: float = 300.0
    enabled: bool = True


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

_COMPARATORS = {
    "gt":  lambda current, threshold: current > threshold,
    "lt":  lambda current, threshold: current < threshold,
    "gte": lambda current, threshold: current >= threshold,
    "lte": lambda current, threshold: current <= threshold,
}


def _severity_for(condition_type: str, ratio: float) -> str:
    """Derive a severity level from how far the value exceeds the threshold."""
    if ratio >= 2.0:
        return "critical"
    if ratio >= 1.2:
        return "warning"
    return "info"


# ---------------------------------------------------------------------------
# Alert manager
# ---------------------------------------------------------------------------

class AlertManager:
    """Evaluates alert rules against market data and tracks active alerts."""

    def __init__(self) -> None:
        self._rules: dict[str, AlertRule] = {}
        self._active_alerts: dict[str, Alert] = {}
        # Maps rule_id → last trigger timestamp (UTC).
        self._last_triggered: dict[str, datetime] = {}

    # ── Rule management ────────────────────────────────────────────────────

    def add_rule(self, rule: AlertRule) -> None:
        """Register a new alert rule."""
        self._rules[rule.id] = rule

    # ── Evaluation ────────────────────────────────────────────────────────

    def check_rules(
        self,
        market_data: dict[str, float],
        timestamp: Optional[datetime] = None,
    ) -> list[Alert]:
        """Evaluate all enabled rules against *market_data*.

        Parameters
        ----------
        market_data:
            Mapping of ``"<TICKER>.<condition_type>"`` → current value.
            E.g. ``{"AAPL.PRICE_MOVE": 5.2, "AAPL.VOLUME_SPIKE": 1.8}``.
        timestamp:
            Evaluation time; defaults to UTC now.

        Returns
        -------
        list[Alert]
            Newly triggered alerts (respecting cooldowns).
        """
        now = timestamp or datetime.now(tz=timezone.utc)
        triggered: list[Alert] = []

        for rule in self._rules.values():
            if not rule.enabled:
                continue

            # Build the market-data key.
            key = f"{rule.ticker}.{rule.condition_type}"
            if key not in market_data:
                continue

            current = market_data[key]
            comparator = _COMPARATORS.get(rule.comparison)
            if comparator is None:
                continue

            if not comparator(current, rule.threshold):
                continue

            # Enforce cooldown.
            last = self._last_triggered.get(rule.id)
            if last is not None:
                elapsed = (now - last).total_seconds()
                if elapsed < rule.cooldown_seconds:
                    continue

            # Determine severity.
            ratio = abs(current / rule.threshold) if rule.threshold != 0 else 2.0
            severity = _severity_for(rule.condition_type, ratio)

            alert = Alert(
                id=str(uuid.uuid4()),
                ticker=rule.ticker,
                condition_type=rule.condition_type,
                threshold=rule.threshold,
                current_value=current,
                triggered_at=now,
                message=(
                    f"{rule.ticker} {rule.condition_type}: "
                    f"current={current:.4g} {rule.comparison} "
                    f"threshold={rule.threshold:.4g}"
                ),
                severity=severity,
            )
            self._active_alerts[alert.id] = alert
            self._last_triggered[rule.id] = now
            triggered.append(alert)

        return triggered

    # ── Active alerts ──────────────────────────────────────────────────────

    def active_alerts(self) -> list[Alert]:
        """Return all currently active (non-dismissed) alerts."""
        return list(self._active_alerts.values())

    def dismiss(self, alert_id: str) -> None:
        """Remove an alert from the active set."""
        self._active_alerts.pop(alert_id, None)

    # ── Summary ────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return counts of active alerts grouped by severity and condition type.

        Example output::

            {
                "total": 3,
                "by_severity": {"info": 1, "warning": 1, "critical": 1},
                "by_condition": {"PRICE_MOVE": 2, "VOLUME_SPIKE": 1},
            }
        """
        by_severity: dict[str, int] = {}
        by_condition: dict[str, int] = {}

        for alert in self._active_alerts.values():
            by_severity[alert.severity] = by_severity.get(alert.severity, 0) + 1
            by_condition[alert.condition_type] = (
                by_condition.get(alert.condition_type, 0) + 1
            )

        return {
            "total": len(self._active_alerts),
            "by_severity": by_severity,
            "by_condition": by_condition,
        }


# ---------------------------------------------------------------------------
# Tests (run with pytest)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Quick smoke test.
    mgr = AlertManager()
    rule = AlertRule(
        id="r1",
        ticker="AAPL",
        condition_type=AlertCondition.PRICE_MOVE,
        threshold=5.0,
        comparison="gt",
        cooldown_seconds=60.0,
    )
    mgr.add_rule(rule)

    data = {"AAPL.PRICE_MOVE": 7.5}
    alerts = mgr.check_rules(data)
    assert len(alerts) == 1, f"Expected 1 alert, got {len(alerts)}"
    assert alerts[0].ticker == "AAPL"
    print("AlertManager smoke test passed.", file=sys.stderr)
