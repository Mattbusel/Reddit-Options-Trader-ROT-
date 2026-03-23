"""Unit tests for rot.analytics.iv_rank — IVRankCalculator (Round 3)."""

from __future__ import annotations

import math
import time
from unittest.mock import MagicMock, patch

import pytest

from rot.analytics.iv_rank import (
    IVData,
    IVRegime,
    IVRankCalculator,
    _bsm_call_price,
    _bsm_vega,
    _implied_vol_newton,
    _norm_cdf,
    _norm_pdf,
)


# ---------------------------------------------------------------------------
# BSM math helpers
# ---------------------------------------------------------------------------

def test_norm_cdf_at_zero() -> None:
    assert _norm_cdf(0.0) == pytest.approx(0.5, abs=1e-9)


def test_norm_cdf_large_positive() -> None:
    assert _norm_cdf(10.0) == pytest.approx(1.0, abs=1e-6)


def test_norm_cdf_large_negative() -> None:
    assert _norm_cdf(-10.0) == pytest.approx(0.0, abs=1e-6)


def test_norm_pdf_at_zero() -> None:
    assert _norm_pdf(0.0) == pytest.approx(1.0 / math.sqrt(2 * math.pi), rel=1e-9)


def test_bsm_call_price_otm_low() -> None:
    """Deep OTM call should have very low price."""
    price = _bsm_call_price(S=100.0, K=200.0, T=0.25, r=0.05, sigma=0.20)
    assert price < 0.01


def test_bsm_call_price_itm_positive() -> None:
    """Deep ITM call should have positive price."""
    price = _bsm_call_price(S=100.0, K=50.0, T=0.25, r=0.05, sigma=0.20)
    assert price > 49.0


def test_bsm_call_price_zero_time_is_intrinsic() -> None:
    price = _bsm_call_price(S=100.0, K=90.0, T=0.0, r=0.05, sigma=0.20)
    assert price == pytest.approx(max(0.0, 100.0 - 90.0), abs=0.01)


def test_bsm_vega_positive() -> None:
    vega = _bsm_vega(S=100.0, K=100.0, T=0.25, r=0.05, sigma=0.20)
    assert vega > 0.0


def test_bsm_vega_zero_time() -> None:
    vega = _bsm_vega(S=100.0, K=100.0, T=0.0, r=0.05, sigma=0.20)
    assert vega < 1e-10


# ---------------------------------------------------------------------------
# Newton-Raphson implied vol inversion
# ---------------------------------------------------------------------------

def test_implied_vol_round_trip() -> None:
    """IV → price → IV should recover the original vol."""
    true_iv = 0.30
    price = _bsm_call_price(S=100.0, K=100.0, T=0.25, r=0.05, sigma=true_iv)
    recovered = _implied_vol_newton(price, S=100.0, K=100.0, T=0.25, r=0.05)
    assert recovered == pytest.approx(true_iv, abs=1e-4)


def test_implied_vol_high_vol_round_trip() -> None:
    true_iv = 0.80
    price = _bsm_call_price(S=100.0, K=100.0, T=0.5, r=0.05, sigma=true_iv)
    recovered = _implied_vol_newton(price, S=100.0, K=100.0, T=0.5, r=0.05)
    assert recovered == pytest.approx(true_iv, abs=1e-3)


def test_implied_vol_zero_price_returns_none() -> None:
    result = _implied_vol_newton(0.0, S=100.0, K=100.0, T=0.25, r=0.05)
    assert result is None


def test_implied_vol_negative_spot_returns_none() -> None:
    result = _implied_vol_newton(5.0, S=-100.0, K=100.0, T=0.25, r=0.05)
    assert result is None


def test_implied_vol_zero_tte_returns_none() -> None:
    result = _implied_vol_newton(5.0, S=100.0, K=100.0, T=0.0, r=0.05)
    assert result is None


# ---------------------------------------------------------------------------
# IVRankCalculator static helpers
# ---------------------------------------------------------------------------

def test_iv_rank_formula_mid_range() -> None:
    rank = IVRankCalculator._iv_rank(0.30, 0.20, 0.40)
    assert rank == pytest.approx(50.0, abs=0.01)


def test_iv_rank_at_high() -> None:
    rank = IVRankCalculator._iv_rank(0.40, 0.20, 0.40)
    assert rank == pytest.approx(100.0, abs=0.01)


def test_iv_rank_at_low() -> None:
    rank = IVRankCalculator._iv_rank(0.20, 0.20, 0.40)
    assert rank == pytest.approx(0.0, abs=0.01)


def test_iv_rank_degenerate_range_returns_50() -> None:
    rank = IVRankCalculator._iv_rank(0.30, 0.30, 0.30)
    assert rank == pytest.approx(50.0, abs=0.01)


def test_iv_percentile_all_below() -> None:
    pct = IVRankCalculator._iv_percentile(0.50, [0.10, 0.20, 0.30])
    assert pct == pytest.approx(100.0, abs=0.01)


def test_iv_percentile_none_below() -> None:
    pct = IVRankCalculator._iv_percentile(0.05, [0.10, 0.20, 0.30])
    assert pct == pytest.approx(0.0, abs=0.01)


def test_iv_percentile_half_below() -> None:
    pct = IVRankCalculator._iv_percentile(0.25, [0.10, 0.20, 0.30, 0.40])
    assert pct == pytest.approx(50.0, abs=0.01)


def test_iv_percentile_empty_history_returns_50() -> None:
    pct = IVRankCalculator._iv_percentile(0.30, [])
    assert pct == pytest.approx(50.0, abs=0.01)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_classify_crush_zone() -> None:
    assert IVRankCalculator._classify(85.0) is IVRegime.IV_CRUSH_ZONE


def test_classify_normal() -> None:
    assert IVRankCalculator._classify(50.0) is IVRegime.NORMAL


def test_classify_expansion_zone() -> None:
    assert IVRankCalculator._classify(15.0) is IVRegime.IV_EXPANSION_ZONE


def test_classify_boundary_80() -> None:
    # 80 is NOT > 80, so it is NORMAL
    assert IVRankCalculator._classify(80.0) is IVRegime.NORMAL


def test_classify_boundary_20() -> None:
    # 20 is NOT < 20, so it is NORMAL
    assert IVRankCalculator._classify(20.0) is IVRegime.NORMAL


# ---------------------------------------------------------------------------
# IVRankCalculator.analyze — mocked
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_calc() -> IVRankCalculator:
    calc = IVRankCalculator()
    # Provide synthetic IV history
    history = [0.20 + i * 0.001 for i in range(252)]
    calc._fetch_iv_history = MagicMock(return_value=history)  # type: ignore[method-assign]
    calc._fetch_atm_iv = MagicMock(return_value=0.35)  # type: ignore[method-assign]
    return calc


def test_analyze_returns_ivdata(mock_calc: IVRankCalculator) -> None:
    data = mock_calc.analyze("AAPL")
    assert isinstance(data, IVData)


def test_analyze_symbol_preserved(mock_calc: IVRankCalculator) -> None:
    data = mock_calc.analyze("AAPL")
    assert data.symbol == "AAPL"


def test_analyze_iv_rank_in_range(mock_calc: IVRankCalculator) -> None:
    data = mock_calc.analyze("AAPL")
    assert 0.0 <= data.iv_rank <= 100.0


def test_analyze_classification_is_ivregime(mock_calc: IVRankCalculator) -> None:
    data = mock_calc.analyze("AAPL")
    assert isinstance(data.classification, IVRegime)


def test_analyze_timestamp_recent(mock_calc: IVRankCalculator) -> None:
    data = mock_calc.analyze("AAPL")
    assert data.timestamp == pytest.approx(time.time(), abs=5.0)


def test_analyze_fallback_when_atm_iv_none() -> None:
    calc = IVRankCalculator()
    history = [0.25 + i * 0.001 for i in range(100)]
    calc._fetch_iv_history = MagicMock(return_value=history)  # type: ignore[method-assign]
    calc._fetch_atm_iv = MagicMock(return_value=None)  # type: ignore[method-assign]
    data = calc.analyze("FAKE")
    assert data.current_iv > 0.0


def test_analyze_batch_returns_list(mock_calc: IVRankCalculator) -> None:
    results = mock_calc.analyze_batch(["AAPL", "TSLA"])
    assert isinstance(results, list)
    assert len(results) == 2
