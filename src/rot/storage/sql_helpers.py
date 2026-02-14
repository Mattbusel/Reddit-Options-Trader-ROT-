"""
SQL Helper Constants and Utility Functions for ROT Database

This module contains shared SQL constants and utility functions used across
multiple database mixins.

SQL Macros:
These macros handle win/loss/neutral classification logic for both live signals
(joined from signals + signal_performance tables) and archived signals (from
the signal_archive table).

Win/Loss Logic:
- Bullish signals win when price moves up >0.5%, lose when price moves down >0.5%
- Bearish signals win when price moves down >0.5%, lose when price moves up >0.5%
- Mixed/unknown stances are always neutral (no directional bet)
- Moves within ±0.5% are considered neutral (noise)

Two variants of each macro:
1. Standard (s.*/sp.* prefixed) - for queries joining signals + signal_performance tables
2. Archive-compatible (_A_* prefixed) - for queries using _UNIFIED_CTE where columns are unqualified

Utility Functions:
- _to_dict: Convert dataclass or dict to plain dict
- _row_to_dict: Convert sqlite Row to dict, parsing JSON fields
"""

import json
from typing import Any, Dict

# ── Standard macros (for signals JOIN signal_performance queries) ──

_WIN_CASE_SQL = """
    CASE
        /* bullish: price went up >0.5% */
        WHEN s.stance = 'bullish'
             AND ({price_col} - sp.price_at_signal) / sp.price_at_signal > 0.005
        THEN 1
        /* bearish: price went down >0.5% */
        WHEN s.stance = 'bearish'
             AND (sp.price_at_signal - {price_col}) / sp.price_at_signal > 0.005
        THEN 1
        /* mixed/unknown: always 0 (no directional bet) */
        ELSE 0
    END"""

_LOSS_CASE_SQL = """
    CASE
        /* bullish: price went down >0.5% */
        WHEN s.stance = 'bullish'
             AND (sp.price_at_signal - {price_col}) / sp.price_at_signal > 0.005
        THEN 1
        /* bearish: price went up >0.5% */
        WHEN s.stance = 'bearish'
             AND ({price_col} - sp.price_at_signal) / sp.price_at_signal > 0.005
        THEN 1
        /* mixed/unknown: always 0 (no directional bet) */
        ELSE 0
    END"""

_NEUTRAL_CASE_SQL = """
    CASE
        /* unknown/mixed stance: always neutral */
        WHEN COALESCE(s.stance, 'unknown') IN ('unknown', 'mixed') THEN 1
        /* directional: price within 0.5% = noise */
        WHEN s.stance IN ('bullish', 'bearish')
             AND ABS({price_col} - sp.price_at_signal) / sp.price_at_signal <= 0.005
        THEN 1
        ELSE 0
    END"""

# Pre-formatted with the standard COALESCE price column
_PRICE_COL = "COALESCE(sp.price_1d, sp.price_4h, sp.price_1h)"
_WIN_SQL = _WIN_CASE_SQL.format(price_col=_PRICE_COL)
_LOSS_SQL = _LOSS_CASE_SQL.format(price_col=_PRICE_COL)
_NEUTRAL_SQL = _NEUTRAL_CASE_SQL.format(price_col=_PRICE_COL)

# ── Archive-compatible macros (unqualified column names) ──
# Used with _UNIFIED_CTE where columns come from a single CTE, not s.*/sp.* tables
_A_PRICE_COL = "COALESCE(price_1d, price_4h, price_1h)"
_A_WIN_SQL = _WIN_CASE_SQL.format(price_col=_A_PRICE_COL).replace("s.stance", "stance").replace("sp.price_at_signal", "price_at_signal")
_A_LOSS_SQL = _LOSS_CASE_SQL.format(price_col=_A_PRICE_COL).replace("s.stance", "stance").replace("sp.price_at_signal", "price_at_signal")
_A_NEUTRAL_SQL = _NEUTRAL_CASE_SQL.format(price_col=_A_PRICE_COL).replace("s.stance", "stance").replace("sp.price_at_signal", "price_at_signal")

# ── Unified CTE (live + archived signals) ──
# CTE that unions live signals+performance with archived signals
_UNIFIED_CTE = """
WITH _unified AS (
    SELECT
        s.id, s.created_at, s.ticker, s.event_type, s.stance,
        s.strategy, s.confidence, s.subreddit, s.quality_score,
        s.sector, s.post_title,
        sp.price_at_signal, sp.price_1h, sp.price_4h, sp.price_1d,
        sp.max_gain_pct, sp.max_loss_pct
    FROM signals s
    JOIN signal_performance sp ON sp.signal_id = s.id

    UNION ALL

    SELECT
        id, created_at, ticker, event_type, stance,
        strategy, confidence, subreddit, quality_score,
        sector, post_title,
        price_at_signal, price_1h, price_4h, price_1d,
        max_gain_pct, max_loss_pct
    FROM signal_archive
)
"""


# ── Utility Functions ──


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert dataclass or dict to plain dict."""
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(obj)
    if isinstance(obj, dict):
        return obj
    return {}


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert sqlite Row to dict, parsing JSON fields."""
    if row is None:
        return {}
    d = dict(row)
    for key in ("market_data", "reasoning", "trade_idea", "event_data", "settings"):
        if key in d:
            val = d[key]
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    d[key] = parsed if isinstance(parsed, dict) else {}
                except (json.JSONDecodeError, TypeError):
                    d[key] = {}
            elif not isinstance(val, dict):
                # Raw non-string, non-dict value (e.g. float, int, None) — reset to empty dict
                d[key] = {}
    return d
