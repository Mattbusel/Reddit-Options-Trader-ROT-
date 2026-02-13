"""Tests for unusual activity history/baseline tracking."""

from __future__ import annotations

import pytest

from rot.unusual.history import UnusualHistory, TickerStats


# ── TickerStats ──


class TestTickerStats:
    """TickerStats data container tests."""

    def test_default_empty(self):
        stats = TickerStats()
        assert len(stats.iv_history) == 0
        assert len(stats.volume_history) == 0
        assert len(stats.oi_history) == 0
        assert len(stats.pc_ratio_history) == 0
        assert stats.last_oi is None

    def test_deque_bounded(self):
        stats = TickerStats()
        for i in range(200):
            stats.iv_history.append(float(i))
        assert len(stats.iv_history) == 100  # maxlen=100


# ── UnusualHistory ──


class TestUnusualHistory:
    """UnusualHistory rolling stats tests."""

    def test_empty_state(self):
        h = UnusualHistory()
        assert h.ticker_count == 0

    def test_update_creates_ticker(self):
        h = UnusualHistory()
        h.update("AAPL", iv=0.35, volume=1000.0)
        assert h.ticker_count == 1

    def test_update_multiple_tickers(self):
        h = UnusualHistory()
        h.update("AAPL", iv=0.35)
        h.update("TSLA", iv=0.55)
        h.update("NVDA", iv=0.40)
        assert h.ticker_count == 3

    def test_update_ignores_none(self):
        h = UnusualHistory()
        h.update("AAPL", iv=None, volume=None, oi=None, pc_ratio=None)
        snap = h.get_stats_snapshot("AAPL")
        assert snap["iv_samples"] == 0
        assert snap["volume_samples"] == 0

    def test_update_ignores_zero_negative(self):
        h = UnusualHistory()
        h.update("AAPL", iv=0.0, volume=-1.0, oi=0.0, pc_ratio=-0.5)
        snap = h.get_stats_snapshot("AAPL")
        assert snap["iv_samples"] == 0
        assert snap["volume_samples"] == 0

    def test_update_records_positive(self):
        h = UnusualHistory()
        h.update("AAPL", iv=0.35, volume=1000.0, oi=5000.0, pc_ratio=0.8)
        snap = h.get_stats_snapshot("AAPL")
        assert snap["iv_samples"] == 1
        assert snap["volume_samples"] == 1
        assert snap["oi_samples"] == 1
        assert snap["pc_ratio_samples"] == 1

    def test_custom_window_size(self):
        h = UnusualHistory(max_window=5)
        for i in range(10):
            h.update("SPY", iv=float(i + 1) * 0.1)
        snap = h.get_stats_snapshot("SPY")
        assert snap["iv_samples"] == 5

    # ── IV Rank ──

    def test_iv_rank_insufficient_history(self):
        h = UnusualHistory()
        for i in range(4):
            h.update("SPY", iv=0.2 + i * 0.01)
        assert h.get_iv_rank("SPY", 0.25) is None  # needs 5

    def test_iv_rank_sufficient_history(self):
        h = UnusualHistory()
        for i in range(10):
            h.update("SPY", iv=0.20 + i * 0.01)  # 0.20 to 0.29
        rank = h.get_iv_rank("SPY", 0.30)  # higher than all
        assert rank is not None
        assert rank == 100.0  # higher than all 10 samples

    def test_iv_rank_lowest(self):
        h = UnusualHistory()
        for i in range(10):
            h.update("SPY", iv=0.30 + i * 0.01)  # 0.30 to 0.39
        rank = h.get_iv_rank("SPY", 0.10)  # lower than all
        assert rank == 0.0

    def test_iv_rank_median(self):
        h = UnusualHistory()
        for i in range(10):
            h.update("SPY", iv=float(i + 1))  # 1.0 to 10.0
        rank = h.get_iv_rank("SPY", 5.5)
        # 5 values below 5.5 out of 10 → 50%
        assert rank == 50.0

    def test_iv_rank_unknown_ticker(self):
        h = UnusualHistory()
        assert h.get_iv_rank("UNKNOWN", 0.5) is None

    # ── Volume Ratio ──

    def test_volume_ratio_insufficient(self):
        h = UnusualHistory()
        h.update("SPY", volume=100.0)
        h.update("SPY", volume=200.0)
        assert h.get_volume_ratio("SPY", 300.0) is None  # needs 3

    def test_volume_ratio_basic(self):
        h = UnusualHistory()
        for _ in range(5):
            h.update("SPY", volume=100.0)
        ratio = h.get_volume_ratio("SPY", 300.0)
        assert ratio is not None
        assert ratio == pytest.approx(3.0)

    def test_volume_ratio_low_mean(self):
        h = UnusualHistory()
        for _ in range(5):
            h.update("SPY", volume=0.5)
        assert h.get_volume_ratio("SPY", 1.0) is None  # mean < 1.0

    # ── Volume Zscore ──

    def test_volume_zscore_insufficient(self):
        h = UnusualHistory()
        for _ in range(4):
            h.update("SPY", volume=100.0)
        assert h.get_volume_zscore("SPY", 200.0) is None

    def test_volume_zscore_normal(self):
        h = UnusualHistory()
        # Add varied volumes so std > 1
        volumes = [100, 110, 90, 105, 95, 120, 80, 115, 85, 100]
        for v in volumes:
            h.update("SPY", volume=float(v))
        z = h.get_volume_zscore("SPY", 200.0)
        assert z is not None
        assert z > 2.0  # well above mean

    def test_volume_zscore_low_variance(self):
        h = UnusualHistory()
        for _ in range(10):
            h.update("SPY", volume=100.0)  # zero variance → std < 1
        z = h.get_volume_zscore("SPY", 200.0)
        assert z is not None
        # Falls back to ratio-based: (200/100) - 1 = 1.0
        assert z == pytest.approx(1.0)

    # ── OI Change Pct ──

    def test_oi_change_no_prior(self):
        h = UnusualHistory()
        h.update("SPY", oi=5000.0)
        # First update: last_oi is None
        assert h.get_oi_change_pct("SPY", 6000.0) is None

    def test_oi_change_basic(self):
        h = UnusualHistory()
        h.update("SPY", oi=5000.0)   # oi_history=[], last_oi stays None, appends 5000
        h.update("SPY", oi=6000.0)   # oi_history=[5000], sets last_oi=5000, appends 6000
        pct = h.get_oi_change_pct("SPY", 7000.0)
        assert pct is not None
        # uses last_oi=5000: (7000 - 5000) / 5000 * 100 = 40.0
        assert pct == pytest.approx(40.0)

    def test_oi_change_decrease(self):
        h = UnusualHistory()
        h.update("SPY", oi=10000.0)  # last_oi stays None, appends 10000
        h.update("SPY", oi=8000.0)   # sets last_oi=10000, appends 8000
        pct = h.get_oi_change_pct("SPY", 6000.0)
        # uses last_oi=10000: (6000 - 10000) / 10000 * 100 = -40.0
        assert pct == pytest.approx(-40.0)

    # ── PC Ratio Zscore ──

    def test_pc_ratio_zscore_insufficient(self):
        h = UnusualHistory()
        for _ in range(4):
            h.update("SPY", pc_ratio=0.8)
        assert h.get_pc_ratio_zscore("SPY", 2.0) is None

    def test_pc_ratio_zscore_normal(self):
        h = UnusualHistory()
        ratios = [0.7, 0.8, 0.9, 0.75, 0.85, 0.70, 0.80, 0.90, 0.75, 0.85]
        for r in ratios:
            h.update("SPY", pc_ratio=r)
        z = h.get_pc_ratio_zscore("SPY", 2.0)
        assert z is not None
        assert z > 3.0  # very high vs typical ~0.8

    def test_pc_ratio_zscore_zero_std(self):
        h = UnusualHistory()
        for _ in range(10):
            h.update("SPY", pc_ratio=0.8)  # zero variance
        z = h.get_pc_ratio_zscore("SPY", 2.0)
        assert z == 0.0  # returns 0 when std < 0.01

    # ── Stats Snapshot ──

    def test_snapshot_unknown_ticker(self):
        h = UnusualHistory()
        snap = h.get_stats_snapshot("UNKNOWN")
        assert snap["has_data"] is False

    def test_snapshot_populated(self):
        h = UnusualHistory()
        h.update("SPY", iv=0.3, volume=100.0, oi=5000.0, pc_ratio=0.8)
        snap = h.get_stats_snapshot("SPY")
        assert snap["has_data"] is True
        assert snap["iv_samples"] == 1
        assert snap["volume_samples"] == 1

    # ── Clear ──

    def test_clear_all(self):
        h = UnusualHistory()
        h.update("SPY", iv=0.3)
        h.update("AAPL", iv=0.25)
        assert h.ticker_count == 2
        h.clear()
        assert h.ticker_count == 0

    def test_clear_ticker(self):
        h = UnusualHistory()
        h.update("SPY", iv=0.3)
        h.update("AAPL", iv=0.25)
        h.clear_ticker("SPY")
        assert h.ticker_count == 1
        assert h.get_stats_snapshot("SPY")["has_data"] is False
        assert h.get_stats_snapshot("AAPL")["has_data"] is True

    def test_clear_nonexistent_ticker(self):
        h = UnusualHistory()
        h.clear_ticker("MISSING")  # should not raise
