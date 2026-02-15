"""Tests for rot.market.price_checker — PriceChecker with yfinance retry,
batch price fetching, initial price recording, and time-gated performance updates.

Covers:
1. _get_current_price: success, retry on failure, all retries exhausted
2. _get_prices_batch: single ticker, multiple tickers, batch failure fallback, empty list
3. record_initial_price: success, UNKNOWN ticker, None price, db error
4. check_pending_prices: no pending, time-gated updates, stance-aware gain, batch integration
5. Edge cases: empty ticker list, zero price_at_signal
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rot.market.price_checker import PriceChecker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_quiet():
    """No-op replacement for _quiet_yfinance context manager."""
    @contextmanager
    def _cm():
        yield
    return _cm()


def _make_hist(close_value):
    """Create a mock yfinance history DataFrame with a single close value."""
    hist = MagicMock()
    hist.__len__ = MagicMock(return_value=1)
    hist.__bool__ = MagicMock(return_value=True)
    close_col = MagicMock()
    close_col.iloc.__getitem__ = MagicMock(return_value=close_value)
    hist.__getitem__ = MagicMock(return_value=close_col)
    return hist


def _make_empty_hist():
    """Create a mock yfinance history DataFrame with no rows."""
    hist = MagicMock()
    hist.__len__ = MagicMock(return_value=0)
    hist.__bool__ = MagicMock(return_value=False)
    return hist


def _make_perf(
    perf_id="perf-1",
    ticker="AAPL",
    price_at_signal=100.0,
    created_at=None,
    signal_stance="bullish",
    price_1h=None,
    price_4h=None,
    price_1d=None,
    price_1w=None,
):
    """Build a performance dict matching the DB row format."""
    if created_at is None:
        created_at = time.time() - 7200  # 2h ago by default
    return {
        "id": perf_id,
        "ticker": ticker,
        "price_at_signal": price_at_signal,
        "created_at": created_at,
        "checked_at": None,
        "signal_stance": signal_stance,
        "price_1h": price_1h,
        "price_4h": price_4h,
        "price_1d": price_1d,
        "price_1w": price_1w,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """AsyncMock database with default empty returns."""
    db = AsyncMock()
    db.insert_signal_performance = AsyncMock()
    db.get_unchecked_performances = AsyncMock(return_value=[])
    db.update_performance_prices = AsyncMock()
    return db


@pytest.fixture
def checker(mock_db):
    """PriceChecker with mocked database."""
    return PriceChecker(mock_db, batch_size=50)


# ---------------------------------------------------------------------------
# 1. _get_current_price — success, retry, exhausted
# ---------------------------------------------------------------------------


class TestGetCurrentPrice:
    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_success_returns_float(self, mock_yf, mock_quiet, checker):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_hist(155.50)
        mock_yf.Ticker.return_value = mock_ticker

        result = checker._get_current_price("AAPL")
        assert result == 155.50
        mock_yf.Ticker.assert_called_once_with("AAPL")

    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_empty_history_returns_none(self, mock_yf, mock_quiet, checker):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_empty_hist()
        mock_yf.Ticker.return_value = mock_ticker

        result = checker._get_current_price("AAPL")
        assert result is None

    @patch("rot.market.price_checker.time.sleep")
    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_retry_on_failure_then_success(self, mock_yf, mock_quiet, mock_sleep, checker):
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = [
            RuntimeError("network error"),
            _make_hist(200.0),
        ]
        mock_yf.Ticker.return_value = mock_ticker

        result = checker._get_current_price("TSLA", retries=2)
        assert result == 200.0
        mock_sleep.assert_called_once_with(1)  # 2^0 = 1

    @patch("rot.market.price_checker.time.sleep")
    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_all_retries_exhausted_returns_none(self, mock_yf, mock_quiet, mock_sleep, checker):
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = RuntimeError("always fails")
        mock_yf.Ticker.return_value = mock_ticker

        result = checker._get_current_price("BAD", retries=3)
        assert result is None
        assert mock_sleep.call_count == 2  # retries - 1 sleeps

    @patch("rot.market.price_checker.time.sleep")
    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_retry_backoff_timing(self, mock_yf, mock_quiet, mock_sleep, checker):
        """Verify exponential backoff: 1s, 2s for 3 retries."""
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = RuntimeError("timeout")
        mock_yf.Ticker.return_value = mock_ticker

        checker._get_current_price("FAIL", retries=3)
        calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert calls == [1, 2]  # 2^0, 2^1

    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_none_history_returns_none(self, mock_yf, mock_quiet, checker):
        """History that is None (not empty) also returns None."""
        mock_ticker = MagicMock()
        none_hist = MagicMock()
        none_hist.__len__ = MagicMock(return_value=0)
        none_hist.__bool__ = MagicMock(return_value=False)
        mock_ticker.history.return_value = none_hist
        mock_yf.Ticker.return_value = mock_ticker

        result = checker._get_current_price("XYZ")
        assert result is None

    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_single_retry_no_sleep_on_success(self, mock_yf, mock_quiet, checker):
        """With retries=1, success on first try means no sleep at all."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_hist(42.0)
        mock_yf.Ticker.return_value = mock_ticker

        with patch("rot.market.price_checker.time.sleep") as mock_sleep:
            result = checker._get_current_price("OK", retries=1)
        assert result == 42.0
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# 2. _get_prices_batch — single, multi, fallback, empty
# ---------------------------------------------------------------------------


class TestGetPricesBatch:
    def test_empty_tickers_returns_empty_dict(self, checker):
        result = checker._get_prices_batch([])
        assert result == {}

    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_single_ticker_uses_direct_close(self, mock_yf, mock_quiet, checker):
        """Single ticker: data['Close'] not data[ticker]['Close']."""
        mock_data = MagicMock()
        close_col = MagicMock()
        close_col.iloc.__getitem__ = MagicMock(return_value=150.0)
        mock_data.__getitem__ = MagicMock(return_value=close_col)
        mock_yf.download.return_value = mock_data

        result = checker._get_prices_batch(["AAPL"])
        assert result["AAPL"] == 150.0

    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_multiple_tickers_uses_grouped_access(self, mock_yf, mock_quiet, checker):
        """Multiple tickers: data[ticker]['Close']."""
        mock_data = MagicMock()

        def get_ticker_data(key):
            if key == "AAPL":
                sub = MagicMock()
                close_col = MagicMock()
                close_col.iloc.__getitem__ = MagicMock(return_value=150.0)
                sub.__getitem__ = MagicMock(return_value=close_col)
                return sub
            if key == "TSLA":
                sub = MagicMock()
                close_col = MagicMock()
                close_col.iloc.__getitem__ = MagicMock(return_value=250.0)
                sub.__getitem__ = MagicMock(return_value=close_col)
                return sub
            raise KeyError(key)

        mock_data.__getitem__ = MagicMock(side_effect=get_ticker_data)
        mock_yf.download.return_value = mock_data

        result = checker._get_prices_batch(["AAPL", "TSLA"])
        assert result["AAPL"] == 150.0
        assert result["TSLA"] == 250.0

    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_batch_failure_falls_back_to_individual(self, mock_yf, mock_quiet, checker):
        """When yf.download raises, falls back to _get_current_price per ticker."""
        mock_yf.download.side_effect = RuntimeError("batch API down")

        with patch.object(checker, "_get_current_price", return_value=100.0) as mock_indiv:
            result = checker._get_prices_batch(["AAPL", "MSFT"])

        assert result["AAPL"] == 100.0
        assert result["MSFT"] == 100.0
        assert mock_indiv.call_count == 2

    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    @patch("rot.market.price_checker.pd")
    def test_nan_close_becomes_none(self, mock_pd, mock_yf, mock_quiet, checker):
        """When close value is NaN, result should be None."""
        mock_pd.isna.return_value = True

        mock_data = MagicMock()
        close_col = MagicMock()
        close_col.iloc.__getitem__ = MagicMock(return_value=float("nan"))
        mock_data.__getitem__ = MagicMock(return_value=close_col)
        mock_yf.download.return_value = mock_data

        result = checker._get_prices_batch(["AAPL"])
        assert result["AAPL"] is None

    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    def test_key_error_for_ticker_in_batch(self, mock_yf, mock_quiet, checker):
        """Missing ticker in grouped data returns None for that ticker."""
        mock_data = MagicMock()
        mock_data.__getitem__ = MagicMock(side_effect=KeyError("MISSING"))
        mock_yf.download.return_value = mock_data

        result = checker._get_prices_batch(["MISSING", "ALSO_MISSING"])
        assert result["MISSING"] is None
        assert result["ALSO_MISSING"] is None


# ---------------------------------------------------------------------------
# 3. record_initial_price — success, UNKNOWN, None price, db error
# ---------------------------------------------------------------------------


class TestRecordInitialPrice:
    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    async def test_success_inserts_to_db(self, mock_yf, mock_quiet, checker, mock_db):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_hist(155.0)
        mock_yf.Ticker.return_value = mock_ticker

        await checker.record_initial_price("sig-1", "AAPL")
        mock_db.insert_signal_performance.assert_awaited_once_with("sig-1", "AAPL", 155.0)

    async def test_unknown_ticker_skipped(self, checker, mock_db):
        await checker.record_initial_price("sig-1", "UNKNOWN")
        mock_db.insert_signal_performance.assert_not_awaited()

    async def test_empty_ticker_skipped(self, checker, mock_db):
        await checker.record_initial_price("sig-1", "")
        mock_db.insert_signal_performance.assert_not_awaited()

    async def test_none_ticker_skipped(self, checker, mock_db):
        await checker.record_initial_price("sig-1", None)
        mock_db.insert_signal_performance.assert_not_awaited()

    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    async def test_price_none_skipped(self, mock_yf, mock_quiet, checker, mock_db):
        """When _get_current_price returns None, no DB insert happens."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_empty_hist()
        mock_yf.Ticker.return_value = mock_ticker

        await checker.record_initial_price("sig-1", "AAPL")
        mock_db.insert_signal_performance.assert_not_awaited()

    @patch("rot.market.price_checker._quiet_yfinance", side_effect=_noop_quiet)
    @patch("rot.market.price_checker.yf")
    async def test_db_error_handled_gracefully(self, mock_yf, mock_quiet, checker, mock_db):
        """Database insert failure is caught and logged, not raised."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_hist(100.0)
        mock_yf.Ticker.return_value = mock_ticker
        mock_db.insert_signal_performance.side_effect = RuntimeError("DB write error")

        # Should not raise
        await checker.record_initial_price("sig-1", "AAPL")
        mock_db.insert_signal_performance.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. check_pending_prices — no pending, time gates, stance, batch
# ---------------------------------------------------------------------------


class TestCheckPendingPrices:
    async def test_no_pending_returns_zero(self, checker, mock_db):
        mock_db.get_unchecked_performances.return_value = []
        result = await checker.check_pending_prices()
        assert result == 0

    async def test_skips_records_missing_ticker(self, checker, mock_db):
        perf = _make_perf(ticker="")
        mock_db.get_unchecked_performances.return_value = [perf]
        result = await checker.check_pending_prices()
        assert result == 0

    async def test_skips_records_missing_price_at_signal(self, checker, mock_db):
        perf = _make_perf(price_at_signal=None)
        mock_db.get_unchecked_performances.return_value = [perf]
        result = await checker.check_pending_prices()
        assert result == 0

    async def test_skips_records_missing_id(self, checker, mock_db):
        perf = _make_perf(perf_id=None)
        mock_db.get_unchecked_performances.return_value = [perf]
        result = await checker.check_pending_prices()
        assert result == 0

    async def test_1h_gate_triggers_at_3600s(self, checker, mock_db):
        """Record aged 2h (>3600s) should get price_1h set."""
        now = time.time()
        perf = _make_perf(created_at=now - 7200)  # 2h ago
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 110.0}):
            result = await checker.check_pending_prices()

        assert result == 1
        update_call = mock_db.update_performance_prices.call_args
        updates = update_call.args[1]
        assert updates["price_1h"] == 110.0

    async def test_4h_gate_triggers_at_14400s(self, checker, mock_db):
        """Record aged 5h (>14400s) should get price_4h set."""
        now = time.time()
        perf = _make_perf(created_at=now - 18000)  # 5h ago
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 115.0}):
            result = await checker.check_pending_prices()

        assert result == 1
        updates = mock_db.update_performance_prices.call_args.args[1]
        assert updates["price_1h"] == 115.0
        assert updates["price_4h"] == 115.0

    async def test_1d_gate_triggers_at_86400s(self, checker, mock_db):
        """Record aged 2d (>86400s) should get price_1d set."""
        now = time.time()
        perf = _make_perf(created_at=now - 172800)  # 2d ago
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 120.0}):
            result = await checker.check_pending_prices()

        updates = mock_db.update_performance_prices.call_args.args[1]
        assert updates["price_1d"] == 120.0

    async def test_1w_gate_triggers_at_604800s(self, checker, mock_db):
        """Record aged 8d (>604800s) should get price_1w set."""
        now = time.time()
        perf = _make_perf(created_at=now - 691200)  # 8d ago
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 130.0}):
            result = await checker.check_pending_prices()

        updates = mock_db.update_performance_prices.call_args.args[1]
        assert updates["price_1w"] == 130.0

    async def test_already_filled_slot_not_overwritten(self, checker, mock_db):
        """If price_1h already set, it should not be overwritten."""
        now = time.time()
        perf = _make_perf(created_at=now - 7200, price_1h=105.0)
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 110.0}):
            result = await checker.check_pending_prices()

        # With 1h already filled and age only 2h, no 4h/1d/1w gates triggered
        assert result == 0

    async def test_bullish_gain_calc_price_up(self, checker, mock_db):
        """Bullish signal: price goes up = positive gain."""
        now = time.time()
        perf = _make_perf(
            created_at=now - 7200,
            price_at_signal=100.0,
            signal_stance="bullish",
        )
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 110.0}):
            await checker.check_pending_prices()

        updates = mock_db.update_performance_prices.call_args.args[1]
        # (110/100 - 1) * 100 = 10%
        assert updates["max_gain_pct"] == pytest.approx(10.0)
        assert updates["max_loss_pct"] == pytest.approx(10.0)  # only one price point

    async def test_bullish_gain_calc_price_down(self, checker, mock_db):
        """Bullish signal: price goes down = negative gain."""
        now = time.time()
        perf = _make_perf(
            created_at=now - 7200,
            price_at_signal=100.0,
            signal_stance="bullish",
        )
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 90.0}):
            await checker.check_pending_prices()

        updates = mock_db.update_performance_prices.call_args.args[1]
        # (90/100 - 1) * 100 = -10%
        assert updates["max_gain_pct"] == pytest.approx(-10.0)
        assert updates["max_loss_pct"] == pytest.approx(-10.0)

    async def test_bearish_gain_calc_price_down(self, checker, mock_db):
        """Bearish signal: price goes down = positive gain (inverted)."""
        now = time.time()
        perf = _make_perf(
            created_at=now - 7200,
            price_at_signal=100.0,
            signal_stance="bearish",
        )
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 90.0}):
            await checker.check_pending_prices()

        updates = mock_db.update_performance_prices.call_args.args[1]
        # raw: (90/100 - 1) * 100 = -10%, inverted for bearish: +10%
        assert updates["max_gain_pct"] == pytest.approx(10.0)
        assert updates["max_loss_pct"] == pytest.approx(10.0)

    async def test_bearish_gain_calc_price_up(self, checker, mock_db):
        """Bearish signal: price goes up = negative gain (inverted)."""
        now = time.time()
        perf = _make_perf(
            created_at=now - 7200,
            price_at_signal=100.0,
            signal_stance="bearish",
        )
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 115.0}):
            await checker.check_pending_prices()

        updates = mock_db.update_performance_prices.call_args.args[1]
        # raw: (115/100 - 1) * 100 = 15%, inverted: -15%
        assert updates["max_gain_pct"] == pytest.approx(-15.0)
        assert updates["max_loss_pct"] == pytest.approx(-15.0)

    async def test_batch_deduplicates_tickers(self, checker, mock_db):
        """Multiple perf records for same ticker should produce one batch call."""
        now = time.time()
        perf1 = _make_perf(perf_id="p1", ticker="AAPL", created_at=now - 7200)
        perf2 = _make_perf(perf_id="p2", ticker="AAPL", created_at=now - 7200)
        mock_db.get_unchecked_performances.return_value = [perf1, perf2]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 110.0}) as mock_batch:
            await checker.check_pending_prices()

        # Should call batch with deduplicated list (1 ticker, not 2)
        batch_tickers = mock_batch.call_args.args[0]
        assert len(batch_tickers) == 1
        assert batch_tickers[0] == "AAPL"

    async def test_price_not_found_in_batch_skips_record(self, checker, mock_db):
        """If batch fetch returns None for a ticker, that record is skipped."""
        now = time.time()
        perf = _make_perf(created_at=now - 7200)
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": None}):
            result = await checker.check_pending_prices()

        assert result == 0
        mock_db.update_performance_prices.assert_not_awaited()

    async def test_db_update_error_handled_gracefully(self, checker, mock_db):
        """Database update failure is caught, does not crash the loop."""
        now = time.time()
        perf = _make_perf(created_at=now - 7200)
        mock_db.get_unchecked_performances.return_value = [perf]
        mock_db.update_performance_prices.side_effect = RuntimeError("DB error")

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 110.0}):
            result = await checker.check_pending_prices()

        # Error handled, count is 0 because the update raised
        assert result == 0

    async def test_checked_at_set_on_update(self, checker, mock_db):
        """Updates should include checked_at timestamp."""
        now = time.time()
        perf = _make_perf(created_at=now - 7200)
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 110.0}):
            await checker.check_pending_prices()

        updates = mock_db.update_performance_prices.call_args.args[1]
        assert "checked_at" in updates
        assert isinstance(updates["checked_at"], float)

    async def test_too_young_record_not_updated(self, checker, mock_db):
        """Record < 1h old should not trigger any price gate."""
        now = time.time()
        perf = _make_perf(created_at=now - 1800)  # 30min ago
        mock_db.get_unchecked_performances.return_value = [perf]

        result = await checker.check_pending_prices()
        assert result == 0
        mock_db.update_performance_prices.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_init_stores_batch_size(self):
        db = AsyncMock()
        pc = PriceChecker(db, batch_size=25)
        assert pc.batch_size == 25

    def test_init_default_batch_size(self):
        db = AsyncMock()
        pc = PriceChecker(db)
        assert pc.batch_size == 50

    async def test_zero_price_at_signal_skips_gain_calc(self, checker, mock_db):
        """price_at_signal == 0 should skip gain/loss computation (division by zero guard)."""
        now = time.time()
        perf = _make_perf(created_at=now - 7200, price_at_signal=0)
        # price_at_signal=0 is falsy, so the first-pass filter skips it
        mock_db.get_unchecked_performances.return_value = [perf]

        result = await checker.check_pending_prices()
        assert result == 0

    async def test_uses_checked_at_fallback_for_age(self, checker, mock_db):
        """When created_at is 0/None, falls back to checked_at for age calc."""
        now = time.time()
        perf = _make_perf(created_at=0)
        perf["checked_at"] = now - 7200  # 2h ago via fallback
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 110.0}):
            result = await checker.check_pending_prices()

        assert result == 1

    async def test_mixed_stance_defaults_to_bullish(self, checker, mock_db):
        """Unknown/mixed stance should use bullish (positive) gain direction."""
        now = time.time()
        perf = _make_perf(
            created_at=now - 7200,
            price_at_signal=100.0,
            signal_stance="mixed",
        )
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 110.0}):
            await checker.check_pending_prices()

        updates = mock_db.update_performance_prices.call_args.args[1]
        # mixed/unknown uses bullish direction: price up = positive
        assert updates["max_gain_pct"] == pytest.approx(10.0)

    async def test_multiple_time_gates_same_record(self, checker, mock_db):
        """A very old record (10 days) should fill all 4 time slots at once."""
        now = time.time()
        perf = _make_perf(created_at=now - 864000)  # 10 days ago
        mock_db.get_unchecked_performances.return_value = [perf]

        with patch.object(checker, "_get_prices_batch", return_value={"AAPL": 120.0}):
            result = await checker.check_pending_prices()

        assert result == 1
        updates = mock_db.update_performance_prices.call_args.args[1]
        assert updates["price_1h"] == 120.0
        assert updates["price_4h"] == 120.0
        assert updates["price_1d"] == 120.0
        assert updates["price_1w"] == 120.0

    async def test_returns_count_of_updated_records(self, checker, mock_db):
        """Return value is the number of successfully updated records."""
        now = time.time()
        perfs = [
            _make_perf(perf_id="p1", ticker="AAPL", created_at=now - 7200),
            _make_perf(perf_id="p2", ticker="TSLA", created_at=now - 7200),
        ]
        mock_db.get_unchecked_performances.return_value = perfs

        with patch.object(
            checker, "_get_prices_batch",
            return_value={"AAPL": 110.0, "TSLA": 250.0},
        ):
            result = await checker.check_pending_prices()

        assert result == 2
        assert mock_db.update_performance_prices.await_count == 2
