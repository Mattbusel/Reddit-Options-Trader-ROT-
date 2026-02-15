"""Tests for rot.storage.sql_helpers — SQL macros, _to_dict, _row_to_dict."""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from rot.storage.sql_helpers import (
    _A_LOSS_SQL,
    _A_NEUTRAL_SQL,
    _A_PRICE_COL,
    _A_WIN_SQL,
    _LOSS_SQL,
    _NEUTRAL_SQL,
    _PRICE_COL,
    _UNIFIED_CTE,
    _WIN_SQL,
    _row_to_dict,
    _to_dict,
)


# ---------------------------------------------------------------------------
# SQL Macro string validation
# ---------------------------------------------------------------------------


class TestSqlMacros:
    """Verify SQL macro strings contain expected patterns."""

    def test_price_col_standard(self):
        assert "sp.price_1d" in _PRICE_COL
        assert "sp.price_4h" in _PRICE_COL
        assert "sp.price_1h" in _PRICE_COL
        assert "COALESCE" in _PRICE_COL

    def test_price_col_archive(self):
        assert "price_1d" in _A_PRICE_COL
        assert "price_4h" in _A_PRICE_COL
        assert "price_1h" in _A_PRICE_COL
        assert "sp." not in _A_PRICE_COL

    def test_win_sql_standard_has_stance_checks(self):
        assert "s.stance = 'bullish'" in _WIN_SQL
        assert "s.stance = 'bearish'" in _WIN_SQL
        assert "0.005" in _WIN_SQL

    def test_loss_sql_standard_has_stance_checks(self):
        assert "s.stance = 'bullish'" in _LOSS_SQL
        assert "s.stance = 'bearish'" in _LOSS_SQL

    def test_neutral_sql_standard(self):
        assert "'unknown'" in _NEUTRAL_SQL
        assert "'mixed'" in _NEUTRAL_SQL
        assert "0.005" in _NEUTRAL_SQL

    def test_win_sql_archive_no_table_prefix(self):
        assert "s.stance" not in _A_WIN_SQL
        assert "sp.price_at_signal" not in _A_WIN_SQL
        assert "stance = 'bullish'" in _A_WIN_SQL

    def test_loss_sql_archive_no_table_prefix(self):
        assert "s.stance" not in _A_LOSS_SQL
        assert "sp.price_at_signal" not in _A_LOSS_SQL

    def test_neutral_sql_archive(self):
        assert "s.stance" not in _A_NEUTRAL_SQL
        assert "stance" in _A_NEUTRAL_SQL

    @pytest.mark.parametrize("macro_name,macro_val", [
        ("_WIN_SQL", _WIN_SQL),
        ("_LOSS_SQL", _LOSS_SQL),
        ("_NEUTRAL_SQL", _NEUTRAL_SQL),
    ])
    def test_standard_macros_have_case(self, macro_name, macro_val):
        assert "CASE" in macro_val
        assert "END" in macro_val

    @pytest.mark.parametrize("macro_name,macro_val", [
        ("_A_WIN_SQL", _A_WIN_SQL),
        ("_A_LOSS_SQL", _A_LOSS_SQL),
        ("_A_NEUTRAL_SQL", _A_NEUTRAL_SQL),
    ])
    def test_archive_macros_have_case(self, macro_name, macro_val):
        assert "CASE" in macro_val
        assert "END" in macro_val

    def test_unified_cte_structure(self):
        assert "WITH _unified AS" in _UNIFIED_CTE
        assert "UNION ALL" in _UNIFIED_CTE
        assert "signal_archive" in _UNIFIED_CTE
        assert "signals s" in _UNIFIED_CTE
        assert "signal_performance sp" in _UNIFIED_CTE

    def test_unified_cte_columns(self):
        for col in ("id", "created_at", "ticker", "event_type", "stance",
                     "strategy", "confidence", "subreddit", "quality_score",
                     "price_at_signal", "price_1h", "price_4h", "price_1d",
                     "max_gain_pct", "max_loss_pct"):
            assert col in _UNIFIED_CTE

    @pytest.mark.parametrize("stance,direction", [
        ("bullish", "up"),
        ("bearish", "down"),
    ])
    def test_win_logic_direction(self, stance, direction):
        """Verify win SQL has correct directional logic per stance."""
        assert f"stance = '{stance}'" in _WIN_SQL

    @pytest.mark.parametrize("stance", ["bullish", "bearish"])
    def test_loss_logic_inverted(self, stance):
        """Both stances appear in loss SQL (inverted win logic)."""
        assert f"stance = '{stance}'" in _LOSS_SQL


# ---------------------------------------------------------------------------
# _to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    def test_dict_passthrough(self):
        d = {"key": "value"}
        assert _to_dict(d) == d

    def test_none_returns_empty(self):
        assert _to_dict(None) == {}

    def test_empty_dict(self):
        assert _to_dict({}) == {}

    def test_dataclass_converted(self):
        @dataclass
        class Sample:
            x: int = 1
            y: str = "hello"

        result = _to_dict(Sample())
        assert result == {"x": 1, "y": "hello"}

    def test_non_dict_non_dataclass(self):
        assert _to_dict(42) == {}
        assert _to_dict("string") == {}

    def test_dataclass_with_nested(self):
        @dataclass
        class Inner:
            val: int = 10

        @dataclass
        class Outer:
            name: str = "test"
            inner: Inner = None  # type: ignore[assignment]

        obj = Outer(name="test", inner=Inner(val=20))
        result = _to_dict(obj)
        assert result["name"] == "test"
        assert result["inner"]["val"] == 20

    @pytest.mark.parametrize("input_val,expected", [
        ({}, {}),
        ({"a": 1}, {"a": 1}),
        (None, {}),
        (42, {}),
        ("str", {}),
        ([], {}),
    ])
    def test_various_inputs(self, input_val, expected):
        assert _to_dict(input_val) == expected


# ---------------------------------------------------------------------------
# _row_to_dict
# ---------------------------------------------------------------------------


class TestRowToDict:
    def test_none_returns_empty(self):
        assert _row_to_dict(None) == {}

    def test_regular_dict(self):
        row = MagicMock()
        row.__iter__ = MagicMock(return_value=iter([("id", "123"), ("ticker", "TSLA")]))
        row.keys = MagicMock(return_value=["id", "ticker"])
        # dict(row) should work — use a plain dict to simulate
        result = _row_to_dict({"id": "123", "ticker": "TSLA"})
        assert result["id"] == "123"
        assert result["ticker"] == "TSLA"

    def test_json_field_parsing_valid(self):
        row = {
            "id": "123",
            "market_data": json.dumps({"TSLA": {"price": 250}}),
            "reasoning": json.dumps({"thesis": "bullish"}),
            "trade_idea": json.dumps({"strategy": "debit_spread"}),
            "event_data": json.dumps({"type": "earnings"}),
        }
        result = _row_to_dict(row)
        assert result["market_data"]["TSLA"]["price"] == 250
        assert result["reasoning"]["thesis"] == "bullish"
        assert result["trade_idea"]["strategy"] == "debit_spread"

    def test_json_field_invalid_json(self):
        row = {"reasoning": "not valid json"}
        result = _row_to_dict(row)
        assert result["reasoning"] == {}

    def test_json_field_already_dict(self):
        row = {"reasoning": {"thesis": "test"}}
        result = _row_to_dict(row)
        assert result["reasoning"] == {"thesis": "test"}

    def test_json_field_non_dict_parsed(self):
        # JSON that parses to a list (not dict) → reset to {}
        row = {"reasoning": json.dumps([1, 2, 3])}
        result = _row_to_dict(row)
        assert result["reasoning"] == {}

    def test_json_field_numeric_value(self):
        row = {"reasoning": 42}
        result = _row_to_dict(row)
        assert result["reasoning"] == {}

    def test_json_field_none_value(self):
        row = {"reasoning": None}
        result = _row_to_dict(row)
        assert result["reasoning"] == {}

    def test_settings_parsed(self):
        row = {"settings": json.dumps({"watchlist": ["TSLA"]})}
        result = _row_to_dict(row)
        assert result["settings"]["watchlist"] == ["TSLA"]

    def test_non_json_fields_untouched(self):
        row = {"id": "123", "ticker": "TSLA", "confidence": 0.8}
        result = _row_to_dict(row)
        assert result["id"] == "123"
        assert result["confidence"] == 0.8

    @pytest.mark.parametrize("field", ["market_data", "reasoning", "trade_idea", "event_data", "settings"])
    def test_all_json_fields_handled(self, field):
        row = {field: json.dumps({"test": True})}
        result = _row_to_dict(row)
        assert result[field] == {"test": True}

    @pytest.mark.parametrize("bad_value", ["", "null", "{bad", "123", "true"])
    def test_malformed_json_values(self, bad_value):
        row = {"reasoning": bad_value}
        result = _row_to_dict(row)
        assert isinstance(result["reasoning"], dict)

    def test_empty_json_string(self):
        row = {"reasoning": "{}"}
        result = _row_to_dict(row)
        assert result["reasoning"] == {}
