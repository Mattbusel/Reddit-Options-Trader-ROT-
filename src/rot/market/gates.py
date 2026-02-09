from __future__ import annotations

import datetime
from typing import Any, Dict, List


def check_trade_gates(
    event_meta: Dict[str, Any],
    min_market_cap: float = 1e8,
) -> List[str]:
    """Return list of reasons NOT to trade. Empty list = all gates passed."""
    reasons: List[str] = []

    # Gate 1: Market hours check
    now = datetime.datetime.now(datetime.timezone.utc)
    weekday = now.weekday()
    hour = now.hour

    if weekday >= 5:  # Saturday/Sunday
        reasons.append("market_closed_weekend")
    elif hour < 13 or hour >= 21:  # Rough UTC window for US market (9:30-4 ET)
        pass  # Don't block on hours - signals can be queued for next open

    # Gate 2: Market data available
    market_data = event_meta.get("market", {})
    if not market_data:
        reasons.append("no_market_data")
        return reasons

    # Gate 3: Check each ticker has valid price data
    for sym, data in market_data.items():
        if not isinstance(data, dict):
            continue
        if "price_error" in data:
            reasons.append(f"price_error_{sym}")
        if "last_close" not in data:
            reasons.append(f"no_price_{sym}")

        # Gate 4: Market cap minimum
        market_cap = data.get("market_cap")
        if market_cap is not None and market_cap < min_market_cap:
            reasons.append(f"low_market_cap_{sym}")

    return reasons
