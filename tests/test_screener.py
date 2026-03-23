"""Unit tests for rot.screener — StrategyScreener (Round 3)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from rot.analytics.iv_rank import IVData, IVRegime, IVRankCalculator
from rot.screener import (
    ScreenCriteria,
    ScreenResult,
    Strategy,
    StrategyScreener,
    _estimate_edge,
    _log_normalise,
    _meets_criteria,
    _score_covered_call,
    _score_iron_condor,
    _weighted,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_iv_data(
    symbol: str = "AAPL",
    iv_rank: float = 60.0,
    current_iv: float = 0.35,
    iv_52w_high: float = 0.50,
    iv_52w_low: float = 0.20,
    iv_mean_30d: float = 0.30,
    iv_percentile: float = 65.0,
    classification: IVRegime = IVRegime.NORMAL,
) -> IVData:
    return IVData(
        symbol=symbol,
        current_iv=current_iv,
        iv_52w_high=iv_52w_high,
        iv_52w_low=iv_52w_low,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        iv_mean_30d=iv_mean_30d,
        classification=classification,
        timestamp=time.time(),
    )


def _make_chain_stats(
    call_vol: float = 5_000.0,
    put_vol: float = 4_000.0,
    call_oi: float = 20_000.0,
    put_oi: float = 18_000.0,
) -> dict:
    return {
        "call_volume": call_vol,
        "put_volume": put_vol,
        "call_oi": call_oi,
        "put_oi": put_oi,
    }


@pytest.fixture()
def mock_screener() -> StrategyScreener:
    iv_data = _make_iv_data()
    calc = MagicMock(spec=IVRankCalculator)
    calc.analyze.return_value = iv_data
    screener = StrategyScreener(iv_calculator=calc)
    return screener


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def test_log_normalise_zero_input() -> None:
    assert _log_normalise(0.0, 1_000.0) == pytest.approx(0.0)


def test_log_normalise_at_scale() -> None:
    val = _log_normalise(1_000.0, 1_000.0)
    assert val == pytest.approx(1.0)


def test_log_normalise_above_scale_capped() -> None:
    val = _log_normalise(1_000_000.0, 1_000.0)
    assert val == pytest.approx(1.0)


def test_log_normalise_negative_scale() -> None:
    assert _log_normalise(100.0, -1.0) == pytest.approx(0.0)


def test_weighted_all_ones() -> None:
    result = _weighted(1.0, 1.0, 1.0, 1.0)
    assert result == pytest.approx(1.0, abs=0.01)


def test_weighted_all_zeros() -> None:
    result = _weighted(0.0, 0.0, 0.0, 0.0)
    assert result == pytest.approx(0.0, abs=0.01)


def test_estimate_edge_above_mean() -> None:
    iv_data = _make_iv_data(current_iv=0.40, iv_mean_30d=0.30)
    edge = _estimate_edge(iv_data)
    assert edge > 0.5


def test_estimate_edge_below_mean() -> None:
    iv_data = _make_iv_data(current_iv=0.20, iv_mean_30d=0.30)
    edge = _estimate_edge(iv_data)
    assert edge < 0.5


def test_estimate_edge_clamped_to_unit_interval() -> None:
    iv_data = _make_iv_data(current_iv=5.0, iv_mean_30d=0.01)
    edge = _estimate_edge(iv_data)
    assert 0.0 <= edge <= 1.0


def test_estimate_edge_zero_mean_returns_half() -> None:
    iv_data = _make_iv_data(current_iv=0.30, iv_mean_30d=0.0)
    edge = _estimate_edge(iv_data)
    assert edge == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# meets_criteria
# ---------------------------------------------------------------------------

def test_meets_criteria_all_pass() -> None:
    stats = _make_chain_stats()
    criteria = ScreenCriteria(min_volume=100, min_open_interest=500, min_iv_rank=20.0)
    assert _meets_criteria(stats, criteria, iv_rank=60.0) is True


def test_meets_criteria_volume_fail() -> None:
    stats = _make_chain_stats(call_vol=10.0, put_vol=10.0)
    criteria = ScreenCriteria(min_volume=1_000)
    assert _meets_criteria(stats, criteria, iv_rank=60.0) is False


def test_meets_criteria_oi_fail() -> None:
    stats = _make_chain_stats(call_oi=100.0, put_oi=100.0)
    criteria = ScreenCriteria(min_open_interest=10_000)
    assert _meets_criteria(stats, criteria, iv_rank=60.0) is False


def test_meets_criteria_iv_rank_below_min_fail() -> None:
    stats = _make_chain_stats()
    criteria = ScreenCriteria(min_iv_rank=70.0)
    assert _meets_criteria(stats, criteria, iv_rank=50.0) is False


def test_meets_criteria_iv_rank_above_max_fail() -> None:
    stats = _make_chain_stats()
    criteria = ScreenCriteria(max_iv_rank=50.0)
    assert _meets_criteria(stats, criteria, iv_rank=60.0) is False


# ---------------------------------------------------------------------------
# Individual scorers
# ---------------------------------------------------------------------------

def test_score_covered_call_in_range() -> None:
    iv_data = _make_iv_data(iv_rank=70.0)
    score = _score_covered_call(iv_data, _make_chain_stats())
    assert 0.0 <= score <= 100.0


def test_score_iron_condor_high_iv_higher_than_low_iv() -> None:
    high_iv = _make_iv_data(iv_rank=85.0)
    low_iv = _make_iv_data(iv_rank=15.0)
    stats = _make_chain_stats()
    assert _score_iron_condor(high_iv, stats) > _score_iron_condor(low_iv, stats)


def test_score_covered_call_high_iv_higher_score() -> None:
    high = _make_iv_data(iv_rank=90.0)
    low = _make_iv_data(iv_rank=10.0)
    stats = _make_chain_stats()
    assert _score_covered_call(high, stats) > _score_covered_call(low, stats)


# ---------------------------------------------------------------------------
# StrategyScreener.scan
# ---------------------------------------------------------------------------

def test_scan_returns_list(mock_screener: StrategyScreener) -> None:
    with patch("rot.screener._fetch_chain_stats", return_value=_make_chain_stats()):
        results = mock_screener.scan(["AAPL"], ScreenCriteria())
    assert isinstance(results, list)


def test_scan_sorted_by_score_descending(mock_screener: StrategyScreener) -> None:
    with patch("rot.screener._fetch_chain_stats", return_value=_make_chain_stats()):
        results = mock_screener.scan(["AAPL"], ScreenCriteria())
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_scan_five_strategies_per_symbol(mock_screener: StrategyScreener) -> None:
    with patch("rot.screener._fetch_chain_stats", return_value=_make_chain_stats()):
        results = mock_screener.scan(["AAPL"], ScreenCriteria())
    strategies = {r.strategy for r in results}
    assert len(strategies) == 5


def test_scan_result_has_details(mock_screener: StrategyScreener) -> None:
    with patch("rot.screener._fetch_chain_stats", return_value=_make_chain_stats()):
        results = mock_screener.scan(["AAPL"], ScreenCriteria())
    assert results
    assert "iv_rank" in results[0].details


def test_scan_top_limits_results(mock_screener: StrategyScreener) -> None:
    with patch("rot.screener._fetch_chain_stats", return_value=_make_chain_stats()):
        results = mock_screener.scan_top(["AAPL", "TSLA"], ScreenCriteria(), top_n=3)
    assert len(results) <= 3


def test_scan_filters_by_iv_rank_min(mock_screener: StrategyScreener) -> None:
    """Symbols with IV rank below min should be excluded."""
    low_iv_data = _make_iv_data(iv_rank=10.0)
    mock_screener._iv_calc.analyze.return_value = low_iv_data
    criteria = ScreenCriteria(min_iv_rank=50.0)
    with patch("rot.screener._fetch_chain_stats", return_value=_make_chain_stats()):
        results = mock_screener.scan(["LOW_IV"], criteria)
    assert results == []


def test_scan_symbol_in_result(mock_screener: StrategyScreener) -> None:
    with patch("rot.screener._fetch_chain_stats", return_value=_make_chain_stats()):
        results = mock_screener.scan(["AAPL"], ScreenCriteria())
    assert all(r.symbol == "AAPL" for r in results)


def test_scan_empty_watchlist(mock_screener: StrategyScreener) -> None:
    results = mock_screener.scan([], ScreenCriteria())
    assert results == []


def test_scan_screen_result_fields() -> None:
    r = ScreenResult(
        symbol="AAPL",
        strategy=Strategy.COVERED_CALL,
        score=72.5,
        details={"iv_rank": 65.0},
    )
    assert r.symbol == "AAPL"
    assert r.strategy is Strategy.COVERED_CALL
    assert r.score == pytest.approx(72.5)
    assert r.details["iv_rank"] == pytest.approx(65.0)


# ---------------------------------------------------------------------------
# Strategy enum
# ---------------------------------------------------------------------------

def test_all_strategies_present() -> None:
    strategies = {s for s in Strategy}
    assert Strategy.COVERED_CALL in strategies
    assert Strategy.CASH_SECURED_PUT in strategies
    assert Strategy.IRON_CONDOR in strategies
    assert Strategy.BULL_PUT_SPREAD in strategies
    assert Strategy.BEAR_CALL_SPREAD in strategies


# Patch needed for import
from unittest.mock import patch
