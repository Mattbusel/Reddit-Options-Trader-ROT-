"""Tests for rot.market.symbol_validator — SymbolValidator with caching,
normalization, alias resolution, yfinance lookups, cache pruning, and persistence.

Covers: normalize(), is_valid(), _prune_expired(), _save(), __post_init__(),
cache hits/misses, TTL expiry, max_cache_size cap, edge cases.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rot.market.enricher import ALIAS_MAP, NON_EQUITY_TOKENS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _noop_quiet():
    """No-op replacement for _quiet_yfinance in tests."""
    yield


def _make_validator(tmp_path: Path, **overrides):
    """Create a SymbolValidator with defaults pointing at tmp_path."""
    from rot.market.symbol_validator import SymbolValidator

    defaults = {
        "cache_path": str(tmp_path / "cache.json"),
        "ttl_s": 3600,
        "max_cache_size": 100,
    }
    defaults.update(overrides)
    return SymbolValidator(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def validator(tmp_path):
    """SymbolValidator with temp cache directory."""
    return _make_validator(tmp_path)


# ---------------------------------------------------------------------------
# normalize() tests
# ---------------------------------------------------------------------------

class TestNormalize:
    """Tests for SymbolValidator.normalize()."""

    def test_basic_uppercasing(self, validator):
        assert validator.normalize("aapl") == "AAPL"

    def test_strip_dollar_sign(self, validator):
        assert validator.normalize("$TSLA") == "TSLA"

    def test_strip_whitespace(self, validator):
        assert validator.normalize("  MSFT  ") == "MSFT"

    def test_combined_dollar_and_whitespace(self, validator):
        assert validator.normalize("  $goog  ") == "GOOG"

    def test_alias_resolution_spx(self, validator):
        assert validator.normalize("SPX") == ALIAS_MAP["SPX"]

    def test_alias_resolution_tsmc(self, validator):
        assert validator.normalize("tsmc") == "TSM"

    @pytest.mark.parametrize("raw,expected", [
        ("$SPX", ALIAS_MAP["SPX"]),
        ("  sp500  ", ALIAS_MAP["SP500"]),
        ("SPXW", ALIAS_MAP["SPXW"]),
    ])
    def test_alias_parametrized(self, validator, raw, expected):
        assert validator.normalize(raw) == expected

    def test_no_alias_passthrough(self, validator):
        assert validator.normalize("NVDA") == "NVDA"

    def test_empty_string(self, validator):
        assert validator.normalize("") == ""

    def test_only_dollar_sign(self, validator):
        assert validator.normalize("$") == ""


# ---------------------------------------------------------------------------
# is_valid() — hard filter tests (no yfinance needed)
# ---------------------------------------------------------------------------

class TestIsValidHardFilters:
    """Tests for is_valid() that hit hard filters before yfinance lookup."""

    def test_too_short_single_char(self, validator):
        assert validator.is_valid("A") is False

    def test_too_long_seven_chars(self, validator):
        assert validator.is_valid("ABCDEFG") is False

    def test_empty_string(self, validator):
        assert validator.is_valid("") is False

    def test_only_whitespace(self, validator):
        assert validator.is_valid("   ") is False

    @pytest.mark.parametrize("token", ["USD", "YOLO", "WSB", "CEO", "FDA", "ETF"])
    def test_non_equity_tokens_rejected(self, validator, token):
        assert token in NON_EQUITY_TOKENS
        assert validator.is_valid(token) is False

    def test_dollar_sign_only(self, validator):
        """'$' normalizes to '' which is empty → False."""
        assert validator.is_valid("$") is False

    def test_boundary_length_two(self, tmp_path):
        """Two-char symbol should pass hard filters and reach yfinance."""
        sv = _make_validator(tmp_path)
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {"lastPrice": 150.0}
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            assert sv.is_valid("GE") is True

    def test_boundary_length_six(self, tmp_path):
        """Six-char symbol should pass hard filters and reach yfinance."""
        sv = _make_validator(tmp_path)
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {"lastPrice": 42.0}
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            assert sv.is_valid("ABCDEF") is True


# ---------------------------------------------------------------------------
# is_valid() — yfinance interaction tests
# ---------------------------------------------------------------------------

class TestIsValidYfinance:
    """Tests for is_valid() yfinance lookup path."""

    def test_valid_symbol_fast_info_last_price(self, tmp_path):
        """Symbol is valid when fast_info has lastPrice."""
        sv = _make_validator(tmp_path)
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {"lastPrice": 150.0}
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            assert sv.is_valid("AAPL") is True

    def test_valid_symbol_fast_info_last_price_underscore(self, tmp_path):
        """Symbol is valid when fast_info has last_price (underscore variant)."""
        sv = _make_validator(tmp_path)
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {"last_price": 99.0}
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            assert sv.is_valid("MSFT") is True

    def test_valid_symbol_history_fallback(self, tmp_path):
        """Symbol is valid via history fallback when fast_info has no price."""
        sv = _make_validator(tmp_path)
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {}
        mock_hist = MagicMock()
        mock_hist.__len__ = lambda self: 5
        mock_hist.__bool__ = lambda self: True
        mock_ticker.history.return_value = mock_hist
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            assert sv.is_valid("GOOG") is True

    def test_invalid_symbol_no_fast_info_empty_history(self, tmp_path):
        """Symbol is invalid when fast_info has no price and history is empty."""
        sv = _make_validator(tmp_path)
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {}
        mock_hist = MagicMock()
        mock_hist.__len__ = lambda self: 0
        mock_hist.__bool__ = lambda self: False
        mock_ticker.history.return_value = mock_hist
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            assert sv.is_valid("ZZZZ") is False

    def test_yfinance_exception_returns_false(self, tmp_path):
        """Symbol is invalid when yfinance raises an exception."""
        sv = _make_validator(tmp_path)
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.side_effect = RuntimeError("network error")
            assert sv.is_valid("AAPL") is False

    def test_no_fast_info_attribute(self, tmp_path):
        """Symbol checked via history when fast_info attr is None."""
        sv = _make_validator(tmp_path)
        mock_ticker = MagicMock()
        mock_ticker.fast_info = None
        mock_hist = MagicMock()
        mock_hist.__len__ = lambda self: 3
        mock_hist.__bool__ = lambda self: True
        mock_ticker.history.return_value = mock_hist
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            assert sv.is_valid("TSLA") is True


# ---------------------------------------------------------------------------
# Cache behavior tests
# ---------------------------------------------------------------------------

class TestCacheBehavior:
    """Tests for cache hits, misses, TTL expiry, and persistence."""

    def test_cache_hit_avoids_yfinance(self, tmp_path):
        """Second call for same symbol uses cache, not yfinance."""
        sv = _make_validator(tmp_path)
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {"lastPrice": 100.0}
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            # First call — cache miss, hits yfinance
            assert sv.is_valid("AAPL") is True
            assert mock_yf.Ticker.call_count == 1
            # Second call — cache hit, no additional yfinance call
            assert sv.is_valid("AAPL") is True
            assert mock_yf.Ticker.call_count == 1

    def test_cache_stores_false_results(self, tmp_path):
        """Invalid symbols are cached too (negative caching)."""
        sv = _make_validator(tmp_path)
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {}
        mock_hist = MagicMock()
        mock_hist.__len__ = lambda self: 0
        mock_hist.__bool__ = lambda self: False
        mock_ticker.history.return_value = mock_hist
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            assert sv.is_valid("FAKE") is False
            assert mock_yf.Ticker.call_count == 1
            # Second call uses cache
            assert sv.is_valid("FAKE") is False
            assert mock_yf.Ticker.call_count == 1

    def test_cache_persisted_to_disk(self, tmp_path):
        """After is_valid(), cache is written to JSON file."""
        cache_file = tmp_path / "cache.json"
        sv = _make_validator(tmp_path)
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {"lastPrice": 200.0}
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            sv.is_valid("NVDA")
        assert cache_file.exists()
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "NVDA" in data
        assert data["NVDA"]["ok"] is True

    def test_cache_loaded_from_disk_on_init(self, tmp_path):
        """New SymbolValidator loads existing cache from disk."""
        cache_file = tmp_path / "cache.json"
        now = int(time.time())
        cache_data = {"AAPL": {"ok": True, "ts": now}}
        cache_file.write_text(json.dumps(cache_data), encoding="utf-8")
        sv = _make_validator(tmp_path)
        # Should not need yfinance — uses loaded cache
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            assert sv.is_valid("AAPL") is True
            mock_yf.Ticker.assert_not_called()

    def test_expired_cache_entry_triggers_yfinance(self, tmp_path):
        """Expired TTL entry is ignored, yfinance is called again."""
        cache_file = tmp_path / "cache.json"
        old_ts = int(time.time()) - 7200  # 2 hours ago
        cache_data = {"AAPL": {"ok": True, "ts": old_ts}}
        cache_file.write_text(json.dumps(cache_data), encoding="utf-8")
        sv = _make_validator(tmp_path, ttl_s=3600)  # 1 hour TTL
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {"lastPrice": 155.0}
        with patch("rot.market.symbol_validator.yf") as mock_yf, \
             patch("rot.market.symbol_validator._quiet_yfinance", _noop_quiet):
            mock_yf.Ticker.return_value = mock_ticker
            assert sv.is_valid("AAPL") is True
            assert mock_yf.Ticker.call_count == 1

    def test_corrupt_cache_file_handled(self, tmp_path):
        """Corrupt JSON cache file does not crash __post_init__."""
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("NOT VALID JSON {{{", encoding="utf-8")
        sv = _make_validator(tmp_path)
        assert sv._cache == {}


# ---------------------------------------------------------------------------
# _prune_expired() tests
# ---------------------------------------------------------------------------

class TestPruneExpired:
    """Tests for _prune_expired() TTL removal and max_cache_size cap."""

    def test_removes_expired_entries(self, tmp_path):
        """Entries older than ttl_s are pruned."""
        sv = _make_validator(tmp_path, ttl_s=100)
        now = int(time.time())
        sv._cache = {
            "AAPL": {"ok": True, "ts": now},
            "OLD": {"ok": True, "ts": now - 200},  # expired
        }
        sv._prune_expired()
        assert "AAPL" in sv._cache
        assert "OLD" not in sv._cache

    def test_respects_max_cache_size(self, tmp_path):
        """Prune caps cache at max_cache_size, evicting oldest first."""
        sv = _make_validator(tmp_path, ttl_s=10000, max_cache_size=3)
        now = int(time.time())
        sv._cache = {
            "A1": {"ok": True, "ts": now - 500},
            "B2": {"ok": True, "ts": now - 400},
            "C3": {"ok": True, "ts": now - 300},
            "D4": {"ok": True, "ts": now - 200},
            "E5": {"ok": True, "ts": now - 100},
        }
        sv._prune_expired()
        assert len(sv._cache) == 3
        # Oldest (A1, B2) should be evicted; newest kept
        assert "A1" not in sv._cache
        assert "B2" not in sv._cache
        assert "E5" in sv._cache

    def test_removes_malformed_entries(self, tmp_path):
        """Entries without proper dict structure or ts field are pruned."""
        sv = _make_validator(tmp_path, ttl_s=10000)
        now = int(time.time())
        sv._cache = {
            "GOOD": {"ok": True, "ts": now},
            "NO_TS": {"ok": True},
            "STRING_VAL": "not_a_dict",
            "BAD_TS": {"ok": True, "ts": "not_a_number"},
        }
        sv._prune_expired()
        assert "GOOD" in sv._cache
        assert "NO_TS" not in sv._cache
        assert "STRING_VAL" not in sv._cache
        assert "BAD_TS" not in sv._cache

    def test_empty_cache_no_error(self, tmp_path):
        """Pruning an empty cache does not raise."""
        sv = _make_validator(tmp_path)
        sv._cache = {}
        sv._prune_expired()
        assert sv._cache == {}


# ---------------------------------------------------------------------------
# _save() tests
# ---------------------------------------------------------------------------

class TestSave:
    """Tests for _save() disk persistence."""

    def test_save_writes_json(self, tmp_path):
        """_save() writes current cache to disk as JSON."""
        sv = _make_validator(tmp_path)
        now = int(time.time())
        sv._cache = {"AAPL": {"ok": True, "ts": now}}
        sv._save()
        cache_file = tmp_path / "cache.json"
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert data["AAPL"]["ok"] is True

    def test_save_prunes_before_writing(self, tmp_path):
        """_save() calls _prune_expired(), so expired entries are not persisted."""
        sv = _make_validator(tmp_path, ttl_s=100)
        now = int(time.time())
        sv._cache = {
            "FRESH": {"ok": True, "ts": now},
            "STALE": {"ok": True, "ts": now - 500},
        }
        sv._save()
        cache_file = tmp_path / "cache.json"
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "FRESH" in data
        assert "STALE" not in data
