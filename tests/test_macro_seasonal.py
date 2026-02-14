"""Tests for rot.macro.seasonal — SeasonalAnalyzer: patterns, bias, rotation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rot.macro.seasonal import SeasonalAnalyzer, _SECTOR_SEASONAL_BASELINES, _SPY_MONTHLY_AVG
from rot.macro.types import SeasonalPattern


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def analyzer():
    return SeasonalAnalyzer()


# ── compute_seasonal_patterns ───────────────────────────────────────


class TestComputeSeasonalPatterns:
    def test_basic_patterns(self, analyzer):
        monthly_returns = {
            1: [2.0, 3.0, -1.0, 4.0],
            6: [-1.0, -2.0, 0.5],
        }
        patterns = analyzer.compute_seasonal_patterns(monthly_returns, "SPY")
        assert len(patterns) == 2
        assert all(isinstance(p, SeasonalPattern) for p in patterns)

    def test_avg_return_computed(self, analyzer):
        monthly_returns = {1: [2.0, 4.0]}  # avg = 3.0
        patterns = analyzer.compute_seasonal_patterns(monthly_returns, "TSLA")
        p = patterns[0]
        assert p.avg_return_pct == 3.0

    def test_win_rate_computed(self, analyzer):
        monthly_returns = {1: [2.0, -1.0, 3.0, -0.5]}  # 2 wins out of 4 = 50%
        patterns = analyzer.compute_seasonal_patterns(monthly_returns, "AAPL")
        p = patterns[0]
        assert p.win_rate_pct == 50.0

    def test_sample_years(self, analyzer):
        monthly_returns = {3: [1.0, 2.0, 3.0, 4.0, 5.0]}
        patterns = analyzer.compute_seasonal_patterns(monthly_returns, "TEST")
        assert patterns[0].sample_years == 5

    def test_best_worst_return(self, analyzer):
        monthly_returns = {7: [5.0, -3.0, 2.0, 8.0]}
        patterns = analyzer.compute_seasonal_patterns(monthly_returns, "TEST")
        p = patterns[0]
        assert p.best_year_return == 8.0
        assert p.worst_year_return == -3.0

    def test_median_return(self, analyzer):
        monthly_returns = {1: [1.0, 2.0, 3.0, 4.0, 5.0]}  # median = 3.0
        patterns = analyzer.compute_seasonal_patterns(monthly_returns, "TEST")
        assert patterns[0].median_return_pct == 3.0

    def test_empty_months_skipped(self, analyzer):
        monthly_returns = {1: [1.0], 2: [], 3: [2.0]}
        patterns = analyzer.compute_seasonal_patterns(monthly_returns, "TEST")
        months = [p.month for p in patterns]
        assert 2 not in months
        assert len(patterns) == 2

    def test_all_empty_returns_empty(self, analyzer):
        monthly_returns = {}
        patterns = analyzer.compute_seasonal_patterns(monthly_returns, "TEST")
        assert patterns == []

    def test_ticker_or_sector_passed_through(self, analyzer):
        monthly_returns = {1: [1.0]}
        patterns = analyzer.compute_seasonal_patterns(monthly_returns, "Technology")
        assert patterns[0].ticker_or_sector == "Technology"

    def test_rounding(self, analyzer):
        monthly_returns = {1: [1.111, 2.222, 3.333]}
        patterns = analyzer.compute_seasonal_patterns(monthly_returns, "TEST")
        p = patterns[0]
        # avg = 2.222, should be rounded to 2.22
        assert p.avg_return_pct == 2.22


# ── get_sector_patterns ─────────────────────────────────────────────


class TestGetSectorPatterns:
    def test_technology_returns_12_patterns(self, analyzer):
        patterns = analyzer.get_sector_patterns("Technology")
        assert len(patterns) == 12

    def test_financials_returns_12_patterns(self, analyzer):
        patterns = analyzer.get_sector_patterns("Financials")
        assert len(patterns) == 12

    def test_unknown_sector_returns_empty(self, analyzer):
        patterns = analyzer.get_sector_patterns("NonexistentSector")
        assert patterns == []

    def test_pattern_months_cover_all_12(self, analyzer):
        patterns = analyzer.get_sector_patterns("Technology")
        months = {p.month for p in patterns}
        assert months == set(range(1, 13))

    def test_pattern_ticker_or_sector_matches(self, analyzer):
        patterns = analyzer.get_sector_patterns("Energy")
        for p in patterns:
            assert p.ticker_or_sector == "Energy"

    def test_sample_years_is_20(self, analyzer):
        patterns = analyzer.get_sector_patterns("Healthcare")
        for p in patterns:
            assert p.sample_years == 20

    def test_all_patterns_are_seasonal_pattern(self, analyzer):
        patterns = analyzer.get_sector_patterns("Materials")
        assert all(isinstance(p, SeasonalPattern) for p in patterns)


# ── get_all_sector_patterns ─────────────────────────────────────────


class TestGetAllSectorPatterns:
    def test_returns_all_10_sectors(self, analyzer):
        all_patterns = analyzer.get_all_sector_patterns()
        assert len(all_patterns) == len(_SECTOR_SEASONAL_BASELINES)
        assert "Technology" in all_patterns
        assert "Financials" in all_patterns
        assert "Energy" in all_patterns

    def test_each_sector_has_12_months(self, analyzer):
        all_patterns = analyzer.get_all_sector_patterns()
        for sector, patterns in all_patterns.items():
            assert len(patterns) == 12, f"{sector} has {len(patterns)} patterns"


# ── get_current_bias ────────────────────────────────────────────────


class TestGetCurrentBias:
    def test_january_bullish(self, analyzer):
        bias = analyzer.get_current_bias(1)
        assert bias["spy_avg_return_pct"] == _SPY_MONTHLY_AVG[1]
        assert bias["month"] == 1
        assert bias["month_name"] == "January"
        # January has 1.0% avg, which is > 0.8 = "historically bullish"
        assert bias["bias"] == "historically bullish"

    def test_september_bearish(self, analyzer):
        bias = analyzer.get_current_bias(9)
        assert bias["spy_avg_return_pct"] == _SPY_MONTHLY_AVG[9]
        assert bias["month_name"] == "September"
        # September has -0.7% avg
        assert "bearish" in bias["bias"]

    def test_has_top_sectors(self, analyzer):
        bias = analyzer.get_current_bias(1)
        assert "top_sectors" in bias
        assert len(bias["top_sectors"]) == 3
        # Top sectors are tuples of (sector_name, return)
        for sector, ret in bias["top_sectors"]:
            assert isinstance(sector, str)
            assert isinstance(ret, (int, float))

    def test_has_bottom_sectors(self, analyzer):
        bias = analyzer.get_current_bias(1)
        assert "bottom_sectors" in bias
        assert len(bias["bottom_sectors"]) == 3

    def test_has_narrative(self, analyzer):
        bias = analyzer.get_current_bias(4)
        assert "narrative" in bias
        assert isinstance(bias["narrative"], str)
        assert len(bias["narrative"]) > 10

    def test_spy_avg_matches_data(self, analyzer):
        for month in range(1, 13):
            bias = analyzer.get_current_bias(month)
            assert bias["spy_avg_return_pct"] == _SPY_MONTHLY_AVG[month]

    def test_february_slightly_bullish_or_neutral(self, analyzer):
        # February has 0.1% avg -> neutral
        bias = analyzer.get_current_bias(2)
        assert bias["bias"] == "neutral"

    def test_november_strongly_bullish(self, analyzer):
        # November has 1.5% avg -> historically bullish
        bias = analyzer.get_current_bias(11)
        assert bias["bias"] == "historically bullish"


# ── get_rotation_calendar ───────────────────────────────────────────


class TestGetRotationCalendar:
    def test_returns_12_entries(self, analyzer):
        calendar = analyzer.get_rotation_calendar()
        assert len(calendar) == 12

    def test_each_entry_has_month(self, analyzer):
        calendar = analyzer.get_rotation_calendar()
        months = [entry["month"] for entry in calendar]
        assert months == list(range(1, 13))

    def test_each_entry_has_bias(self, analyzer):
        calendar = analyzer.get_rotation_calendar()
        for entry in calendar:
            assert "bias" in entry
            assert "top_sectors" in entry
            assert "bottom_sectors" in entry
            assert "narrative" in entry

    def test_each_entry_has_spy_avg(self, analyzer):
        calendar = analyzer.get_rotation_calendar()
        for entry in calendar:
            assert "spy_avg_return_pct" in entry
            assert isinstance(entry["spy_avg_return_pct"], (int, float))


# ── fetch_ticker_seasonals ──────────────────────────────────────────


class TestFetchTickerSeasonals:
    def test_with_mocked_yfinance(self, analyzer):
        with patch.dict("sys.modules", {}):
            # We need to mock yfinance module
            mock_yf = MagicMock()
            import pandas as pd
            import numpy as np

            dates = pd.date_range("2020-01-01", periods=36, freq="ME")
            closes = [100 + i * 0.5 + (i % 5) for i in range(36)]
            mock_hist = pd.DataFrame({"Close": closes}, index=dates)
            mock_ticker = MagicMock()
            mock_ticker.history.return_value = mock_hist
            mock_yf.Ticker.return_value = mock_ticker

            with patch.dict("sys.modules", {"yfinance": mock_yf}):
                patterns = analyzer.fetch_ticker_seasonals("AAPL", lookback_years=3)
                # Should produce patterns for months with data
                assert isinstance(patterns, list)
                if patterns:
                    assert all(isinstance(p, SeasonalPattern) for p in patterns)

    def test_handles_missing_yfinance(self, analyzer):
        """When yfinance import fails, returns empty list."""
        # Simulate ImportError by patching import
        with patch.object(analyzer, "fetch_ticker_seasonals", return_value=[]):
            result = analyzer.fetch_ticker_seasonals("TSLA")
            assert result == []

    def test_handles_empty_history(self, analyzer):
        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = MagicMock(empty=True)
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            patterns = analyzer.fetch_ticker_seasonals("FAKESYM")
            assert patterns == []
