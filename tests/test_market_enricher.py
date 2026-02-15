"""Tests for rot.market.enricher — MarketEnricher with caching, aliases,
non-equity filtering, symbol validation, options chain, and yfinance retry.

Covers MarketEnricher: cache loading/saving/pruning/expiry, _fresh, _fetch,
get_symbol, enrich_symbols, enrich_event, ALIAS_MAP, NON_EQUITY_TOKENS,
options metrics, full info mode, and _quiet_yfinance context manager.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from rot.core.types import Event, Evidence
from rot.market.enricher import (
    ALIAS_MAP,
    NON_EQUITY_TOKENS,
    MarketEnricher,
    _quiet_yfinance,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache_dir(tmp_path):
    """Return a temporary cache path for MarketEnricher."""
    return str(tmp_path / "market_cache.json")


@pytest.fixture
def enricher(cache_dir):
    """MarketEnricher with all yfinance calls mocked out."""
    with patch("rot.market.enricher.retry_with_backoff", lambda **kw: lambda fn: fn):
        e = MarketEnricher(cache_path=cache_dir, ttl_s=3600, enable_options_chain=False)
    return e


def _make_event(**overrides) -> Event:
    defaults = dict(
        event_type="other",
        entities=["TSLA"],
        stance="bullish",
        time_horizon="1w",
        evidence=[Evidence(post_id="x", permalink="", subreddit="test", excerpt="t")],
        confidence=0.5,
        meta={},
    )
    defaults.update(overrides)
    return Event(**defaults)


# ---------------------------------------------------------------------------
# 1. ALIAS_MAP
# ---------------------------------------------------------------------------


class TestAliasMap:
    def test_spx_maps_to_gspc(self):
        assert ALIAS_MAP["SPX"] == "^GSPC"

    def test_sp500_maps_to_gspc(self):
        assert ALIAS_MAP["SP500"] == "^GSPC"

    def test_spxw_maps_to_gspc(self):
        assert ALIAS_MAP["SPXW"] == "^GSPC"

    def test_tsmc_maps_to_tsm(self):
        assert ALIAS_MAP["TSMC"] == "TSM"

    def test_alias_map_is_dict(self):
        assert isinstance(ALIAS_MAP, dict)
        assert len(ALIAS_MAP) >= 4


# ---------------------------------------------------------------------------
# 2. NON_EQUITY_TOKENS
# ---------------------------------------------------------------------------


class TestNonEquityTokens:
    @pytest.mark.parametrize("token", [
        "USD", "EUR", "GBP", "JPY",
        "AI", "DD", "YOLO", "WSB",
        "ITM", "OTM", "DTE", "FD",
        "BUY", "SELL", "HOLD",
        "CPI", "GDP", "FOMC", "FED",
        "CEO", "CFO", "COO",
    ])
    def test_common_non_equity_tokens_present(self, token):
        assert token in NON_EQUITY_TOKENS

    def test_is_a_set(self):
        assert isinstance(NON_EQUITY_TOKENS, set)

    def test_has_substantial_size(self):
        assert len(NON_EQUITY_TOKENS) >= 100

    @pytest.mark.parametrize("token", [
        "AAPL", "TSLA", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
    ])
    def test_real_tickers_not_in_non_equity(self, token):
        assert token not in NON_EQUITY_TOKENS


# ---------------------------------------------------------------------------
# 3. _quiet_yfinance context manager
# ---------------------------------------------------------------------------


class TestQuietYfinance:
    def test_suppresses_stdout(self, capsys):
        with _quiet_yfinance():
            import sys
            sys.stdout.write("should be suppressed\n")
        captured = capsys.readouterr()
        assert "should be suppressed" not in captured.out

    def test_context_manager_returns_normally(self):
        with _quiet_yfinance():
            pass  # Should not raise

    def test_exceptions_propagate(self):
        with pytest.raises(ValueError, match="test error"):
            with _quiet_yfinance():
                raise ValueError("test error")


# ---------------------------------------------------------------------------
# 4. get_symbol
# ---------------------------------------------------------------------------


class TestGetSymbol:
    def test_normal_ticker(self, enricher):
        assert enricher.get_symbol("AAPL") == "AAPL"

    def test_lowercase_ticker(self, enricher):
        assert enricher.get_symbol("aapl") == "AAPL"

    def test_mixed_case(self, enricher):
        assert enricher.get_symbol("Tsla") == "TSLA"

    def test_whitespace_stripped(self, enricher):
        assert enricher.get_symbol("  AAPL  ") == "AAPL"

    def test_alias_resolved(self, enricher):
        assert enricher.get_symbol("SPX") == "^GSPC"

    def test_non_equity_returns_none(self, enricher):
        assert enricher.get_symbol("USD") is None
        assert enricher.get_symbol("YOLO") is None
        assert enricher.get_symbol("CEO") is None

    def test_single_char_returns_none(self, enricher):
        assert enricher.get_symbol("A") is None

    def test_empty_returns_none(self, enricher):
        assert enricher.get_symbol("") is None

    @pytest.mark.parametrize("raw,expected", [
        ("SPX", "^GSPC"),
        ("SP500", "^GSPC"),
        ("TSMC", "TSM"),
        ("MSFT", "MSFT"),
        ("nvda", "NVDA"),
    ])
    def test_parametrized_symbol_resolution(self, enricher, raw, expected):
        assert enricher.get_symbol(raw) == expected


# ---------------------------------------------------------------------------
# 5. Cache loading / saving
# ---------------------------------------------------------------------------


class TestCacheLoading:
    def test_starts_with_empty_cache_no_file(self, cache_dir):
        e = MarketEnricher(cache_path=cache_dir)
        assert e._cache == {}

    def test_loads_valid_cache_from_file(self, cache_dir):
        now = int(time.time())
        cache_data = {"AAPL": {"ts": now, "data": {"symbol": "AAPL", "last_close": 150.0}}}
        Path(cache_dir).write_text(json.dumps(cache_data), encoding="utf-8")
        e = MarketEnricher(cache_path=cache_dir, ttl_s=3600)
        assert "AAPL" in e._cache

    def test_handles_corrupt_cache_file(self, cache_dir):
        Path(cache_dir).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_dir).write_text("not valid json{{{", encoding="utf-8")
        e = MarketEnricher(cache_path=cache_dir)
        assert e._cache == {}

    def test_creates_parent_directory(self, tmp_path):
        path = str(tmp_path / "deep" / "nested" / "cache.json")
        e = MarketEnricher(cache_path=path)
        assert Path(path).parent.exists()


class TestCacheSaving:
    def test_save_cache_writes_json(self, enricher, cache_dir):
        now = int(time.time())
        enricher._cache = {"AAPL": {"ts": now, "data": {"last_close": 150.0}}}
        enricher._save_cache()
        content = json.loads(Path(cache_dir).read_text(encoding="utf-8"))
        assert "AAPL" in content


# ---------------------------------------------------------------------------
# 6. Cache pruning
# ---------------------------------------------------------------------------


class TestCachePruning:
    def test_removes_expired_entries(self, cache_dir):
        old_ts = int(time.time()) - 7200  # 2h ago, default ttl=1h
        cache_data = {
            "AAPL": {"ts": old_ts, "data": {"last_close": 150.0}},
        }
        Path(cache_dir).write_text(json.dumps(cache_data), encoding="utf-8")
        e = MarketEnricher(cache_path=cache_dir, ttl_s=3600)
        assert "AAPL" not in e._cache

    def test_keeps_fresh_entries(self, cache_dir):
        now = int(time.time())
        cache_data = {
            "AAPL": {"ts": now, "data": {"last_close": 150.0}},
        }
        Path(cache_dir).write_text(json.dumps(cache_data), encoding="utf-8")
        e = MarketEnricher(cache_path=cache_dir, ttl_s=3600)
        assert "AAPL" in e._cache

    def test_evicts_oldest_when_over_max_size(self, cache_dir):
        now = int(time.time())
        # Create cache over MAX_CACHE_SIZE
        cache_data = {}
        for i in range(MarketEnricher.MAX_CACHE_SIZE + 10):
            cache_data[f"SYM{i}"] = {"ts": now - i, "data": {"last_close": float(i)}}
        Path(cache_dir).write_text(json.dumps(cache_data), encoding="utf-8")
        e = MarketEnricher(cache_path=cache_dir, ttl_s=86400)
        assert len(e._cache) <= MarketEnricher.MAX_CACHE_SIZE

    def test_prune_removes_non_dict_entries(self, cache_dir):
        cache_data = {
            "BAD": "not a dict",
            "ALSO_BAD": 42,
        }
        Path(cache_dir).write_text(json.dumps(cache_data), encoding="utf-8")
        e = MarketEnricher(cache_path=cache_dir, ttl_s=3600)
        assert len(e._cache) == 0


# ---------------------------------------------------------------------------
# 7. _fresh — cache freshness check
# ---------------------------------------------------------------------------


class TestFresh:
    def test_returns_data_for_fresh_entry(self, enricher):
        now = int(time.time())
        enricher._cache["AAPL"] = {"ts": now, "data": {"last_close": 150.0}}
        result = enricher._fresh("AAPL")
        assert result == {"last_close": 150.0}

    def test_returns_none_for_expired_entry(self, enricher):
        old_ts = int(time.time()) - 7200  # 2h ago
        enricher._cache["AAPL"] = {"ts": old_ts, "data": {"last_close": 150.0}}
        result = enricher._fresh("AAPL")
        assert result is None

    def test_returns_none_for_missing_key(self, enricher):
        assert enricher._fresh("MISSING") is None

    def test_returns_none_for_non_dict_entry(self, enricher):
        enricher._cache["BAD"] = "string"
        assert enricher._fresh("BAD") is None

    def test_returns_none_for_missing_ts(self, enricher):
        enricher._cache["AAPL"] = {"data": {"last_close": 150.0}}
        assert enricher._fresh("AAPL") is None

    def test_returns_none_for_non_numeric_ts(self, enricher):
        enricher._cache["AAPL"] = {"ts": "not_a_number", "data": {"last_close": 150.0}}
        assert enricher._fresh("AAPL") is None

    def test_returns_none_when_data_is_not_dict(self, enricher):
        now = int(time.time())
        enricher._cache["AAPL"] = {"ts": now, "data": "not a dict"}
        assert enricher._fresh("AAPL") is None

    def test_options_ttl_forces_refetch(self):
        """When options chain enabled and past options_ttl, returns None."""
        e = MarketEnricher(
            cache_path="storage/test_cache.json",
            ttl_s=3600,
            options_ttl_s=1800,
            enable_options_chain=True,
        )
        # Set entry at 2000s ago (past options_ttl but within main ttl)
        e._cache["AAPL"] = {"ts": int(time.time()) - 2000, "data": {"last_close": 150.0}}
        result = e._fresh("AAPL")
        assert result is None


# ---------------------------------------------------------------------------
# 8. _fetch
# ---------------------------------------------------------------------------


class TestFetch:
    @patch("rot.market.enricher.yf")
    @patch("rot.market.enricher._quiet_yfinance")
    def test_fetch_returns_last_close(self, mock_quiet, mock_yf, enricher):
        mock_quiet.return_value.__enter__ = MagicMock()
        mock_quiet.return_value.__exit__ = MagicMock(return_value=False)

        mock_ticker = MagicMock()
        # Mock history
        mock_hist = MagicMock()
        mock_hist.__len__ = MagicMock(return_value=2)
        mock_hist.__bool__ = MagicMock(return_value=True)
        close_col = MagicMock()
        close_col.iloc.__getitem__ = MagicMock(side_effect=lambda i: {-1: 150.0, -2: 148.0}[i])
        mock_hist.__getitem__ = MagicMock(return_value=close_col)
        mock_ticker.history.return_value = mock_hist
        mock_ticker.fast_info = None
        mock_yf.Ticker.return_value = mock_ticker

        result = enricher._fetch("AAPL")
        assert result["symbol"] == "AAPL"
        assert result["last_close"] == 150.0

    @patch("rot.market.enricher.yf")
    @patch("rot.market.enricher._quiet_yfinance")
    def test_fetch_computes_pct_1d(self, mock_quiet, mock_yf, enricher):
        mock_quiet.return_value.__enter__ = MagicMock()
        mock_quiet.return_value.__exit__ = MagicMock(return_value=False)

        mock_ticker = MagicMock()
        mock_hist = MagicMock()
        mock_hist.__len__ = MagicMock(return_value=2)
        mock_hist.__bool__ = MagicMock(return_value=True)
        close_col = MagicMock()
        close_col.iloc.__getitem__ = MagicMock(side_effect=lambda i: {-1: 110.0, -2: 100.0}[i])
        mock_hist.__getitem__ = MagicMock(return_value=close_col)
        mock_ticker.history.return_value = mock_hist
        mock_ticker.fast_info = None
        mock_yf.Ticker.return_value = mock_ticker

        result = enricher._fetch("AAPL")
        assert result["pct_1d"] == pytest.approx(0.1, abs=0.001)

    @patch("rot.market.enricher.yf")
    @patch("rot.market.enricher._quiet_yfinance")
    def test_fetch_handles_history_exception(self, mock_quiet, mock_yf, enricher):
        mock_quiet.return_value.__enter__ = MagicMock()
        mock_quiet.return_value.__exit__ = MagicMock(return_value=False)

        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("network error")
        mock_ticker.fast_info = None
        mock_yf.Ticker.return_value = mock_ticker

        result = enricher._fetch("AAPL")
        assert result["symbol"] == "AAPL"
        assert "price_error" in result

    @patch("rot.market.enricher.yf")
    @patch("rot.market.enricher._quiet_yfinance")
    def test_fetch_reads_fast_info_dict(self, mock_quiet, mock_yf, enricher):
        mock_quiet.return_value.__enter__ = MagicMock()
        mock_quiet.return_value.__exit__ = MagicMock(return_value=False)

        mock_ticker = MagicMock()
        mock_hist = MagicMock()
        mock_hist.__len__ = MagicMock(return_value=0)
        mock_hist.__bool__ = MagicMock(return_value=False)
        mock_ticker.history.return_value = mock_hist
        mock_ticker.fast_info = {
            "currency": "USD",
            "lastPrice": 155.0,
            "marketCap": 2.5e12,
        }
        mock_yf.Ticker.return_value = mock_ticker

        result = enricher._fetch("AAPL")
        assert result["currency"] == "USD"
        assert result["last_price"] == 155.0
        assert result["market_cap"] == 2.5e12

    @patch("rot.market.enricher.yf")
    @patch("rot.market.enricher._quiet_yfinance")
    def test_fetch_with_empty_history(self, mock_quiet, mock_yf, enricher):
        mock_quiet.return_value.__enter__ = MagicMock()
        mock_quiet.return_value.__exit__ = MagicMock(return_value=False)

        mock_ticker = MagicMock()
        mock_hist = MagicMock()
        mock_hist.__len__ = MagicMock(return_value=0)
        mock_hist.__bool__ = MagicMock(return_value=False)
        mock_ticker.history.return_value = mock_hist
        mock_ticker.fast_info = None
        mock_yf.Ticker.return_value = mock_ticker

        result = enricher._fetch("AAPL")
        assert result["symbol"] == "AAPL"
        assert "last_close" not in result


# ---------------------------------------------------------------------------
# 9. enrich_symbols
# ---------------------------------------------------------------------------


class TestEnrichSymbols:
    @patch.object(MarketEnricher, "_fetch")
    def test_basic_enrichment(self, mock_fetch, enricher):
        mock_fetch.return_value = {"symbol": "AAPL", "last_close": 150.0}
        result = enricher.enrich_symbols(["AAPL"])
        assert "AAPL" in result
        assert result["AAPL"]["last_close"] == 150.0

    @patch.object(MarketEnricher, "_fetch")
    def test_skips_non_equity_tokens(self, mock_fetch, enricher):
        result = enricher.enrich_symbols(["USD", "CEO", "YOLO"])
        assert result == {}
        mock_fetch.assert_not_called()

    @patch.object(MarketEnricher, "_fetch")
    def test_resolves_aliases(self, mock_fetch, enricher):
        mock_fetch.return_value = {"symbol": "^GSPC", "last_close": 5000.0}
        result = enricher.enrich_symbols(["SPX"])
        assert "^GSPC" in result

    def test_uses_cache_when_fresh(self, enricher):
        now = int(time.time())
        enricher._cache["AAPL"] = {"ts": now, "data": {"symbol": "AAPL", "last_close": 150.0}}
        result = enricher.enrich_symbols(["AAPL"])
        assert result["AAPL"]["last_close"] == 150.0

    @patch.object(MarketEnricher, "_fetch")
    def test_multiple_symbols(self, mock_fetch, enricher):
        mock_fetch.side_effect = [
            {"symbol": "AAPL", "last_close": 150.0},
            {"symbol": "TSLA", "last_close": 250.0},
        ]
        result = enricher.enrich_symbols(["AAPL", "TSLA"])
        assert len(result) == 2
        assert result["AAPL"]["last_close"] == 150.0
        assert result["TSLA"]["last_close"] == 250.0

    @patch.object(MarketEnricher, "_fetch")
    def test_caches_fetched_results(self, mock_fetch, enricher):
        mock_fetch.return_value = {"symbol": "AAPL", "last_close": 150.0}
        enricher.enrich_symbols(["AAPL"])
        assert "AAPL" in enricher._cache

    @patch.object(MarketEnricher, "_fetch")
    def test_empty_symbols_returns_empty(self, mock_fetch, enricher):
        result = enricher.enrich_symbols([])
        assert result == {}
        mock_fetch.assert_not_called()

    @patch.object(MarketEnricher, "_fetch")
    def test_single_char_symbols_filtered(self, mock_fetch, enricher):
        result = enricher.enrich_symbols(["A"])
        assert result == {}
        mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# 10. enrich_event
# ---------------------------------------------------------------------------


class TestEnrichEvent:
    @patch.object(MarketEnricher, "enrich_symbols")
    def test_adds_market_data_to_meta(self, mock_enrich, enricher):
        mock_enrich.return_value = {"TSLA": {"last_close": 250.0}}
        event = _make_event()
        enriched = enricher.enrich_event(event)
        assert "market" in enriched.meta
        assert enriched.meta["market"]["TSLA"]["last_close"] == 250.0

    @patch.object(MarketEnricher, "enrich_symbols")
    def test_preserves_existing_meta(self, mock_enrich, enricher):
        mock_enrich.return_value = {"TSLA": {"last_close": 250.0}}
        event = _make_event(meta={"existing_key": "value"})
        enriched = enricher.enrich_event(event)
        assert enriched.meta["existing_key"] == "value"
        assert "market" in enriched.meta

    @patch.object(MarketEnricher, "enrich_symbols")
    def test_original_event_unchanged(self, mock_enrich, enricher):
        mock_enrich.return_value = {}
        event = _make_event(meta={"original": True})
        enricher.enrich_event(event)
        assert "market" not in event.meta

    @patch.object(MarketEnricher, "enrich_symbols")
    def test_handles_no_entities(self, mock_enrich, enricher):
        mock_enrich.return_value = {}
        event = _make_event(entities=[])
        enriched = enricher.enrich_event(event)
        assert enriched.meta["market"] == {}

    @patch.object(MarketEnricher, "enrich_symbols")
    def test_uses_event_entities(self, mock_enrich, enricher):
        mock_enrich.return_value = {}
        event = _make_event(entities=["AAPL", "TSLA", "MSFT"])
        enricher.enrich_event(event)
        call_args = mock_enrich.call_args[0][0]
        assert set(call_args) == {"AAPL", "TSLA", "MSFT"}


# ---------------------------------------------------------------------------
# 11. Full info mode
# ---------------------------------------------------------------------------


class TestFullInfoMode:
    @patch("rot.market.enricher.yf")
    @patch("rot.market.enricher._quiet_yfinance")
    def test_fetches_sector_industry_when_enabled(self, mock_quiet, mock_yf):
        mock_quiet.return_value.__enter__ = MagicMock()
        mock_quiet.return_value.__exit__ = MagicMock(return_value=False)

        mock_ticker = MagicMock()
        mock_hist = MagicMock()
        mock_hist.__len__ = MagicMock(return_value=0)
        mock_hist.__bool__ = MagicMock(return_value=False)
        mock_ticker.history.return_value = mock_hist
        mock_ticker.fast_info = None
        mock_ticker.info = {
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "volume": 50_000_000,
            "averageVolume": 60_000_000,
            "fiftyTwoWeekHigh": 200.0,
            "fiftyTwoWeekLow": 120.0,
            "trailingPE": 30.5,
            "beta": 1.2,
        }
        mock_yf.Ticker.return_value = mock_ticker

        with patch("rot.market.enricher.retry_with_backoff", lambda **kw: lambda fn: fn):
            e = MarketEnricher(
                cache_path="storage/test_full.json",
                fetch_full_info=True,
            )
        result = e._fetch("AAPL")
        assert result["sector"] == "Technology"
        assert result["industry"] == "Consumer Electronics"
        assert result["volume"] == 50_000_000
        assert result["beta"] == 1.2

    @patch("rot.market.enricher.yf")
    @patch("rot.market.enricher._quiet_yfinance")
    def test_skips_full_info_when_disabled(self, mock_quiet, mock_yf, enricher):
        mock_quiet.return_value.__enter__ = MagicMock()
        mock_quiet.return_value.__exit__ = MagicMock(return_value=False)

        mock_ticker = MagicMock()
        mock_hist = MagicMock()
        mock_hist.__len__ = MagicMock(return_value=0)
        mock_hist.__bool__ = MagicMock(return_value=False)
        mock_ticker.history.return_value = mock_hist
        mock_ticker.fast_info = None
        mock_yf.Ticker.return_value = mock_ticker

        result = enricher._fetch("AAPL")
        assert "sector" not in result
        assert "industry" not in result


# ---------------------------------------------------------------------------
# 12. Options metrics
# ---------------------------------------------------------------------------


class TestOptionsMetrics:
    @patch("rot.market.enricher.yf")
    @patch("rot.market.enricher._quiet_yfinance")
    def test_options_fetched_when_enabled(self, mock_quiet, mock_yf):
        mock_quiet.return_value.__enter__ = MagicMock()
        mock_quiet.return_value.__exit__ = MagicMock(return_value=False)

        mock_ticker = MagicMock()
        mock_hist = MagicMock()
        mock_hist.__len__ = MagicMock(return_value=1)
        mock_hist.__bool__ = MagicMock(return_value=True)
        close_col = MagicMock()
        close_col.iloc.__getitem__ = MagicMock(return_value=150.0)
        mock_hist.__getitem__ = MagicMock(return_value=close_col)
        mock_ticker.history.return_value = mock_hist
        mock_ticker.fast_info = None
        mock_yf.Ticker.return_value = mock_ticker

        with patch("rot.market.enricher.retry_with_backoff", lambda **kw: lambda fn: fn):
            e = MarketEnricher(
                cache_path="storage/test_opts.json",
                enable_options_chain=True,
            )

        with patch.object(e, "_fetch_options_metrics", return_value={"atm_iv": 0.35}):
            result = e._fetch("AAPL")
            # The options data should be merged in
            assert result.get("atm_iv") == 0.35

    def test_options_not_fetched_when_disabled(self, enricher):
        assert enricher.enable_options_chain is False


# ---------------------------------------------------------------------------
# 13. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch.object(MarketEnricher, "_fetch")
    def test_handles_exception_in_fetch(self, mock_fetch, enricher):
        mock_fetch.side_effect = Exception("yfinance down")
        with pytest.raises(Exception, match="yfinance down"):
            enricher.enrich_symbols(["AAPL"])

    def test_max_cache_size_constant(self):
        assert MarketEnricher.MAX_CACHE_SIZE == 500

    def test_default_ttl(self, cache_dir):
        e = MarketEnricher(cache_path=cache_dir)
        assert e.ttl_s == 3600

    def test_default_options_ttl(self, cache_dir):
        e = MarketEnricher(cache_path=cache_dir)
        assert e.options_ttl_s == 1800

    @patch.object(MarketEnricher, "_fetch")
    def test_mixed_valid_and_invalid_symbols(self, mock_fetch, enricher):
        mock_fetch.return_value = {"symbol": "AAPL", "last_close": 150.0}
        result = enricher.enrich_symbols(["AAPL", "USD", "CEO", "A", ""])
        assert len(result) == 1
        assert "AAPL" in result


# ---------------------------------------------------------------------------
# 14. SymbolValidator tests
# ---------------------------------------------------------------------------


class TestSymbolValidator:
    """Tests for SymbolValidator (imported from symbol_validator.py)."""

    def test_normalize_strips_whitespace(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        assert sv.normalize("  aapl  ") == "AAPL"

    def test_normalize_removes_dollar_sign(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        assert sv.normalize("$TSLA") == "TSLA"

    def test_normalize_resolves_alias(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        assert sv.normalize("SPX") == "^GSPC"

    def test_is_valid_rejects_empty(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        assert sv.is_valid("") is False

    def test_is_valid_rejects_single_char(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        assert sv.is_valid("A") is False

    def test_is_valid_rejects_too_long(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        assert sv.is_valid("TOOLONG7") is False

    @pytest.mark.parametrize("token", ["USD", "YOLO", "CEO", "BUY", "AI"])
    def test_is_valid_rejects_non_equity(self, tmp_path, token):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        assert sv.is_valid(token) is False

    def test_is_valid_uses_cache_hit(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        now = int(time.time())
        sv._cache["AAPL"] = {"ok": True, "ts": now}
        assert sv.is_valid("AAPL") is True

    def test_is_valid_cache_hit_false(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        now = int(time.time())
        sv._cache["FAKE"] = {"ok": False, "ts": now}
        assert sv.is_valid("FAKE") is False

    def test_is_valid_ignores_expired_cache(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"), ttl_s=100)
        old_ts = int(time.time()) - 200
        sv._cache["AAPL"] = {"ok": True, "ts": old_ts}
        # Should not use expired cache, will try yfinance
        with patch("rot.market.symbol_validator.yf") as mock_yf:
            with patch("rot.market.symbol_validator._quiet_yfinance"):
                mock_ticker = MagicMock()
                mock_ticker.fast_info = None
                mock_hist = MagicMock()
                mock_hist.__len__ = MagicMock(return_value=0)
                mock_hist.__bool__ = MagicMock(return_value=False)
                mock_ticker.history.return_value = mock_hist
                mock_yf.Ticker.return_value = mock_ticker
                result = sv.is_valid("AAPL")
                assert result is False  # yfinance returned empty

    def test_prune_expired_removes_old(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"), ttl_s=100)
        old_ts = int(time.time()) - 200
        sv._cache = {
            "OLD": {"ok": True, "ts": old_ts},
            "FRESH": {"ok": True, "ts": int(time.time())},
        }
        sv._prune_expired()
        assert "OLD" not in sv._cache
        assert "FRESH" in sv._cache

    def test_prune_caps_at_max_cache_size(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"), max_cache_size=5)
        now = int(time.time())
        for i in range(10):
            sv._cache[f"SYM{i}"] = {"ok": True, "ts": now - i}
        sv._prune_expired()
        assert len(sv._cache) <= 5

    def test_loads_existing_cache_file(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        cache_file = tmp_path / "sv.json"
        now = int(time.time())
        cache_data = {"AAPL": {"ok": True, "ts": now}}
        cache_file.write_text(json.dumps(cache_data), encoding="utf-8")
        sv = SymbolValidator(cache_path=str(cache_file))
        assert "AAPL" in sv._cache

    def test_handles_corrupt_cache_file(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        cache_file = tmp_path / "sv.json"
        cache_file.write_text("{{bad json", encoding="utf-8")
        sv = SymbolValidator(cache_path=str(cache_file))
        assert sv._cache == {}

    def test_save_writes_cache_to_disk(self, tmp_path):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        now = int(time.time())
        sv._cache["AAPL"] = {"ok": True, "ts": now}
        sv._save()
        loaded = json.loads((tmp_path / "sv.json").read_text(encoding="utf-8"))
        assert "AAPL" in loaded

    @pytest.mark.parametrize("sym,expected", [
        ("$AAPL", "AAPL"),
        ("aapl", "AAPL"),
        ("  tsla  ", "TSLA"),
        ("$SPX", "^GSPC"),
        ("TSMC", "TSM"),
    ])
    def test_normalize_parametrized(self, tmp_path, sym, expected):
        from rot.market.symbol_validator import SymbolValidator
        sv = SymbolValidator(cache_path=str(tmp_path / "sv.json"))
        assert sv.normalize(sym) == expected


# ---------------------------------------------------------------------------
# 15. Stress tests
# ---------------------------------------------------------------------------


class TestStress:
    @patch.object(MarketEnricher, "_fetch")
    def test_enrich_many_symbols(self, mock_fetch, enricher):
        mock_fetch.return_value = {"symbol": "X", "last_close": 100.0}
        symbols = [f"SYM{i}" for i in range(100)]
        result = enricher.enrich_symbols(symbols)
        assert len(result) == 100

    def test_cache_pruning_large_cache(self, cache_dir):
        now = int(time.time())
        cache_data = {}
        for i in range(1000):
            cache_data[f"S{i}"] = {"ts": now - i, "data": {"last_close": float(i)}}
        Path(cache_dir).write_text(json.dumps(cache_data), encoding="utf-8")
        e = MarketEnricher(cache_path=cache_dir, ttl_s=86400)
        assert len(e._cache) <= MarketEnricher.MAX_CACHE_SIZE


# ---------------------------------------------------------------------------
# 16. Parametrized TTL behavior
# ---------------------------------------------------------------------------


class TestTTLBehavior:
    @pytest.mark.parametrize("ttl_s,age_s,should_be_fresh", [
        (3600, 1800, True),     # 30min old, 1h TTL
        (3600, 3599, True),     # 1s before TTL boundary
        (3600, 3601, False),    # 1s past TTL
        (3600, 7200, False),    # 2h old, 1h TTL
        (86400, 3600, True),    # 1h old, 24h TTL
        (86400, 90000, False),  # 25h old, 24h TTL
    ])
    def test_cache_freshness_by_ttl(self, cache_dir, ttl_s, age_s, should_be_fresh):
        e = MarketEnricher(cache_path=cache_dir, ttl_s=ttl_s)
        ts = int(time.time()) - age_s
        e._cache["AAPL"] = {"ts": ts, "data": {"last_close": 150.0}}
        result = e._fresh("AAPL")
        if should_be_fresh:
            assert result is not None
        else:
            assert result is None
