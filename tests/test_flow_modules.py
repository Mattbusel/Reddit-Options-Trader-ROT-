"""Tests for rot.flow — GreeksEngine, FlowDetector, and flow helpers.

Covers GreeksEngine: price (call/put), delta, gamma, theta, vega, rho,
compute_greeks, implied_volatility, portfolio_greeks, edge cases.
Covers FlowDetector: detect_from_market_data, scan_batch, compute_score,
block trade / sweep / dark pool / accumulation / distribution detection.
Covers helpers: _safe_float, _safe_int, _parse_market_data, _extract_ticker_data.
"""
from __future__ import annotations

import math
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from rot.flow.detector import (
    FlowDetector,
    FlowDetectorConfig,
    _extract_ticker_data,
    _parse_market_data,
    _safe_float,
    _safe_int,
)
from rot.flow.greeks import (
    DEFAULT_RISK_FREE_RATE,
    GreeksEngine,
    _norm_cdf,
    _norm_pdf,
    black_scholes_price,
    compute_iv,
)
from rot.flow.history import FlowHistory
from rot.flow.types import FlowEvent, FlowScore, GreeksSnapshot


# =========================================================================
# Part 1: Normal distribution helpers
# =========================================================================


class TestNormCdf:
    def test_at_zero(self):
        assert _norm_cdf(0.0) == pytest.approx(0.5)

    def test_large_positive(self):
        assert _norm_cdf(10.0) == pytest.approx(1.0, abs=1e-10)

    def test_large_negative(self):
        assert _norm_cdf(-10.0) == pytest.approx(0.0, abs=1e-10)

    def test_symmetry(self):
        for x in [0.5, 1.0, 1.5, 2.0, 3.0]:
            assert _norm_cdf(x) + _norm_cdf(-x) == pytest.approx(1.0)

    @pytest.mark.parametrize("x,expected", [
        (0.0, 0.5),
        (1.0, 0.8413),
        (2.0, 0.9772),
        (-1.0, 0.1587),
        (-2.0, 0.0228),
    ])
    def test_known_values(self, x, expected):
        assert _norm_cdf(x) == pytest.approx(expected, abs=0.001)


class TestNormPdf:
    def test_at_zero(self):
        expected = 1.0 / math.sqrt(2.0 * math.pi)
        assert _norm_pdf(0.0) == pytest.approx(expected)

    def test_symmetry(self):
        assert _norm_pdf(1.0) == pytest.approx(_norm_pdf(-1.0))

    def test_positive(self):
        for x in [-3, -1, 0, 1, 3]:
            assert _norm_pdf(x) > 0


# =========================================================================
# Part 2: GreeksEngine — Pricing
# =========================================================================


@pytest.fixture
def engine():
    return GreeksEngine(risk_free_rate=0.05)


class TestPricing:
    def test_call_price_positive(self, engine):
        price = engine.price(S=150, K=155, T=0.1, sigma=0.25, option_type="call")
        assert price > 0

    def test_put_price_positive(self, engine):
        price = engine.price(S=150, K=155, T=0.1, sigma=0.25, option_type="put")
        assert price > 0

    def test_call_higher_for_lower_strike(self, engine):
        c1 = engine.price(S=150, K=140, T=0.1, sigma=0.25, option_type="call")
        c2 = engine.price(S=150, K=160, T=0.1, sigma=0.25, option_type="call")
        assert c1 > c2

    def test_put_higher_for_higher_strike(self, engine):
        p1 = engine.price(S=150, K=160, T=0.1, sigma=0.25, option_type="put")
        p2 = engine.price(S=150, K=140, T=0.1, sigma=0.25, option_type="put")
        assert p1 > p2

    def test_put_call_parity(self, engine):
        """C - P = S - K*e^(-rT) (approximately)."""
        S, K, T, sigma, r = 150.0, 155.0, 0.25, 0.30, 0.05
        call = engine.price(S, K, T, sigma, "call", r)
        put = engine.price(S, K, T, sigma, "put", r)
        parity = call - put
        expected = S - K * math.exp(-r * T)
        assert parity == pytest.approx(expected, abs=0.01)

    def test_deep_itm_call_near_intrinsic(self, engine):
        price = engine.price(S=200, K=100, T=0.01, sigma=0.25, option_type="call")
        intrinsic = 200 - 100
        assert price >= intrinsic - 1  # Near intrinsic value

    def test_deep_otm_call_near_zero(self, engine):
        price = engine.price(S=100, K=200, T=0.01, sigma=0.25, option_type="call")
        assert price < 1.0

    def test_higher_vol_higher_price(self, engine):
        c_low = engine.price(S=150, K=155, T=0.1, sigma=0.15)
        c_high = engine.price(S=150, K=155, T=0.1, sigma=0.45)
        assert c_high > c_low

    def test_longer_time_higher_price(self, engine):
        c_short = engine.price(S=150, K=155, T=0.05, sigma=0.25)
        c_long = engine.price(S=150, K=155, T=0.5, sigma=0.25)
        assert c_long > c_short

    @pytest.mark.parametrize("S,K,T,sigma,opt", [
        (100, 100, 0.25, 0.20, "call"),
        (100, 100, 0.25, 0.20, "put"),
        (200, 150, 0.5, 0.30, "call"),
        (150, 200, 0.5, 0.30, "put"),
        (50, 50, 1.0, 0.50, "call"),
    ])
    def test_price_non_negative(self, engine, S, K, T, sigma, opt):
        assert engine.price(S, K, T, sigma, opt) >= 0


class TestPricingEdgeCases:
    def test_zero_underlying(self, engine):
        assert engine.price(S=0, K=100, T=0.1, sigma=0.25) == 0.0

    def test_zero_strike(self, engine):
        assert engine.price(S=100, K=0, T=0.1, sigma=0.25) == 0.0

    def test_at_expiry_call_itm(self, engine):
        price = engine.price(S=110, K=100, T=0, sigma=0.25, option_type="call")
        assert price == pytest.approx(10.0)

    def test_at_expiry_call_otm(self, engine):
        price = engine.price(S=90, K=100, T=0, sigma=0.25, option_type="call")
        assert price == 0.0

    def test_at_expiry_put_itm(self, engine):
        price = engine.price(S=90, K=100, T=0, sigma=0.25, option_type="put")
        assert price == pytest.approx(10.0)

    def test_zero_vol_call(self, engine):
        price = engine.price(S=150, K=100, T=0.25, sigma=0, option_type="call")
        pv_k = 100 * math.exp(-0.05 * 0.25)
        expected = max(150 - pv_k, 0.0)
        assert price == pytest.approx(expected, abs=0.01)

    def test_custom_risk_free_rate(self, engine):
        p1 = engine.price(S=150, K=155, T=0.25, sigma=0.25, r=0.01)
        p2 = engine.price(S=150, K=155, T=0.25, sigma=0.25, r=0.10)
        # Higher rate = higher call price (slightly)
        assert p2 > p1


# =========================================================================
# Part 3: Greeks
# =========================================================================


class TestDelta:
    def test_call_delta_between_0_and_1(self, engine):
        d = engine.delta(S=150, K=155, T=0.1, sigma=0.25, option_type="call")
        assert 0 < d < 1

    def test_put_delta_between_neg1_and_0(self, engine):
        d = engine.delta(S=150, K=155, T=0.1, sigma=0.25, option_type="put")
        assert -1 < d < 0

    def test_atm_call_delta_near_0_5(self, engine):
        d = engine.delta(S=100, K=100, T=0.25, sigma=0.25, option_type="call")
        assert d == pytest.approx(0.5, abs=0.1)

    def test_deep_itm_call_delta_near_1(self, engine):
        d = engine.delta(S=200, K=100, T=0.1, sigma=0.25, option_type="call")
        assert d > 0.9

    def test_deep_otm_call_delta_near_0(self, engine):
        d = engine.delta(S=50, K=100, T=0.1, sigma=0.25, option_type="call")
        assert d < 0.1

    def test_delta_at_expiry_itm(self, engine):
        d = engine.delta(S=110, K=100, T=0, sigma=0.25, option_type="call")
        assert d == 1.0

    def test_delta_at_expiry_otm(self, engine):
        d = engine.delta(S=90, K=100, T=0, sigma=0.25, option_type="call")
        assert d == 0.0

    def test_put_call_delta_relationship(self, engine):
        """Call delta - Put delta = 1 (approximately)."""
        cd = engine.delta(S=150, K=155, T=0.25, sigma=0.25, option_type="call")
        pd = engine.delta(S=150, K=155, T=0.25, sigma=0.25, option_type="put")
        assert (cd - pd) == pytest.approx(1.0, abs=0.01)


class TestGamma:
    def test_gamma_positive(self, engine):
        g = engine.gamma(S=150, K=155, T=0.1, sigma=0.25)
        assert g > 0

    def test_gamma_highest_atm(self, engine):
        g_atm = engine.gamma(S=100, K=100, T=0.1, sigma=0.25)
        g_itm = engine.gamma(S=120, K=100, T=0.1, sigma=0.25)
        g_otm = engine.gamma(S=80, K=100, T=0.1, sigma=0.25)
        assert g_atm > g_itm
        assert g_atm > g_otm

    def test_gamma_zero_at_edge(self, engine):
        assert engine.gamma(S=0, K=100, T=0.1, sigma=0.25) == 0.0
        assert engine.gamma(S=100, K=100, T=0, sigma=0.25) == 0.0


class TestTheta:
    def test_theta_negative_for_long_call(self, engine):
        t = engine.theta(S=150, K=155, T=0.1, sigma=0.25, option_type="call")
        assert t < 0  # Time decay

    def test_theta_negative_for_long_put(self, engine):
        t = engine.theta(S=150, K=155, T=0.1, sigma=0.25, option_type="put")
        assert t < 0

    def test_theta_near_expiry_larger(self, engine):
        t_far = engine.theta(S=100, K=100, T=1.0, sigma=0.25)
        t_near = engine.theta(S=100, K=100, T=0.01, sigma=0.25)
        assert abs(t_near) > abs(t_far)  # More time decay near expiry


class TestVega:
    def test_vega_positive(self, engine):
        v = engine.vega(S=150, K=155, T=0.1, sigma=0.25)
        assert v > 0

    def test_vega_highest_atm(self, engine):
        v_atm = engine.vega(S=100, K=100, T=0.25, sigma=0.25)
        v_otm = engine.vega(S=80, K=100, T=0.25, sigma=0.25)
        assert v_atm > v_otm


class TestRho:
    def test_call_rho_positive(self, engine):
        r = engine.rho(S=150, K=155, T=0.25, sigma=0.25, option_type="call")
        assert r > 0

    def test_put_rho_negative(self, engine):
        r = engine.rho(S=150, K=155, T=0.25, sigma=0.25, option_type="put")
        assert r < 0


class TestComputeGreeks:
    def test_returns_snapshot(self, engine):
        gs = engine.compute_greeks(S=150, K=155, T=0.1, sigma=0.25)
        assert isinstance(gs, GreeksSnapshot)
        assert gs.delta > 0
        assert gs.gamma > 0
        assert gs.theta < 0
        assert gs.vega > 0
        assert gs.iv == 0.25
        assert gs.underlying_price == 150
        assert gs.strike == 155

    def test_dte_computed(self, engine):
        gs = engine.compute_greeks(S=100, K=100, T=30 / 365, sigma=0.25)
        assert gs.dte == pytest.approx(30.0, abs=0.1)


# =========================================================================
# Part 4: Implied Volatility
# =========================================================================


class TestImpliedVolatility:
    def test_round_trip(self, engine):
        """Price at known vol, then recover vol from that price."""
        sigma = 0.30
        S, K, T = 150.0, 155.0, 0.25
        price = engine.price(S, K, T, sigma, "call")
        iv = engine.implied_volatility(price, S, K, T, "call")
        assert iv is not None
        assert iv == pytest.approx(sigma, abs=0.001)

    def test_round_trip_put(self, engine):
        sigma = 0.25
        S, K, T = 100.0, 105.0, 0.5
        price = engine.price(S, K, T, sigma, "put")
        iv = engine.implied_volatility(price, S, K, T, "put")
        assert iv is not None
        assert iv == pytest.approx(sigma, abs=0.001)

    def test_returns_none_for_zero_price(self, engine):
        assert engine.implied_volatility(0, 100, 100, 0.25) is None

    def test_returns_none_for_negative_price(self, engine):
        assert engine.implied_volatility(-5, 100, 100, 0.25) is None

    def test_returns_none_for_zero_time(self, engine):
        assert engine.implied_volatility(5, 100, 100, 0) is None

    @pytest.mark.parametrize("sigma", [0.10, 0.20, 0.30, 0.50, 0.80, 1.00])
    def test_round_trip_various_vols(self, engine, sigma):
        S, K, T = 100.0, 100.0, 0.25
        price = engine.price(S, K, T, sigma, "call")
        iv = engine.implied_volatility(price, S, K, T, "call")
        assert iv is not None
        assert iv == pytest.approx(sigma, abs=0.01)


class TestConvenienceFunctions:
    def test_black_scholes_price(self):
        price = black_scholes_price(S=100, K=100, T=0.25, sigma=0.25)
        assert price > 0

    def test_compute_iv(self):
        price = black_scholes_price(S=100, K=100, T=0.25, sigma=0.30)
        iv = compute_iv(price, S=100, K=100, T=0.25)
        assert iv is not None
        assert iv == pytest.approx(0.30, abs=0.01)


# =========================================================================
# Part 5: Portfolio Greeks
# =========================================================================


class TestPortfolioGreeks:
    def test_single_position(self, engine):
        positions = [
            {"S": 150, "K": 155, "T": 0.25, "sigma": 0.25, "qty": 1, "option_type": "call"},
        ]
        pg = engine.portfolio_greeks(positions)
        assert isinstance(pg, GreeksSnapshot)
        assert pg.delta > 0  # Long call = positive delta

    def test_straddle_near_zero_delta(self, engine):
        positions = [
            {"S": 100, "K": 100, "T": 0.25, "sigma": 0.25, "qty": 1, "option_type": "call"},
            {"S": 100, "K": 100, "T": 0.25, "sigma": 0.25, "qty": 1, "option_type": "put"},
        ]
        pg = engine.portfolio_greeks(positions)
        # ATM straddle has near-zero delta
        assert abs(pg.delta) < 20  # In share-equivalent terms

    def test_short_position_negative_delta(self, engine):
        positions = [
            {"S": 100, "K": 100, "T": 0.25, "sigma": 0.25, "qty": -1, "option_type": "call"},
        ]
        pg = engine.portfolio_greeks(positions)
        assert pg.delta < 0

    def test_empty_portfolio(self, engine):
        pg = engine.portfolio_greeks([])
        assert pg.delta == 0
        assert pg.gamma == 0

    def test_skips_invalid_positions(self, engine):
        positions = [
            {"S": 0, "K": 100, "T": 0.25, "sigma": 0.25, "qty": 1, "option_type": "call"},
            {"S": 100, "K": 100, "T": 0.25, "sigma": 0.25, "qty": 0, "option_type": "call"},
        ]
        pg = engine.portfolio_greeks(positions)
        assert pg.delta == 0


# =========================================================================
# Part 6: Flow detector helpers
# =========================================================================


class TestSafeFloat:
    @pytest.mark.parametrize("val,expected", [
        (None, 0.0),
        ("", 0.0),
        ("abc", 0.0),
        (42, 42.0),
        (3.14, 3.14),
        ("3.14", 3.14),
        (float("nan"), 0.0),
        (float("inf"), 0.0),
        (float("-inf"), 0.0),
    ])
    def test_safe_float(self, val, expected):
        assert _safe_float(val) == expected

    def test_custom_default(self):
        assert _safe_float(None, default=99.9) == 99.9


class TestSafeInt:
    @pytest.mark.parametrize("val,expected", [
        (None, 0),
        ("", 0),
        ("abc", 0),
        (42, 42),
        (3.7, 3),
        ("100", 100),
        ("3.14", 3),
    ])
    def test_safe_int(self, val, expected):
        assert _safe_int(val) == expected


class TestParseMarketData:
    def test_dict_passthrough(self):
        d = {"TSLA": {"last_close": 250.0}}
        assert _parse_market_data(d) == d

    def test_json_string(self):
        import json
        d = {"TSLA": {"last_close": 250.0}}
        assert _parse_market_data(json.dumps(d)) == d

    def test_invalid_json(self):
        assert _parse_market_data("bad json{") == {}

    def test_none(self):
        assert _parse_market_data(None) == {}

    def test_int(self):
        assert _parse_market_data(42) == {}


class TestExtractTickerData:
    def test_nested_by_ticker(self):
        md = {"TSLA": {"last_close": 250.0}}
        assert _extract_ticker_data(md, "TSLA") == {"last_close": 250.0}

    def test_flat_structure(self):
        md = {"atm_iv": 0.35, "call_oi": 1000}
        assert _extract_ticker_data(md, "TSLA") == md

    def test_missing_ticker(self):
        md = {"AAPL": {"last_close": 150.0}}
        assert _extract_ticker_data(md, "TSLA") == {}


# =========================================================================
# Part 7: FlowDetectorConfig
# =========================================================================


class TestFlowDetectorConfig:
    def test_defaults(self):
        cfg = FlowDetectorConfig()
        assert cfg.block_premium_threshold == 100_000.0
        assert cfg.sweep_volume_threshold == 500
        assert cfg.composite_min_score == 25.0

    def test_custom(self):
        cfg = FlowDetectorConfig(block_premium_threshold=50_000)
        assert cfg.block_premium_threshold == 50_000


# =========================================================================
# Part 8: FlowDetector
# =========================================================================


class TestFlowDetectorInit:
    def test_default_config(self):
        d = FlowDetector()
        assert isinstance(d.config, FlowDetectorConfig)
        assert isinstance(d.history, FlowHistory)

    def test_custom_config(self):
        cfg = FlowDetectorConfig(block_premium_threshold=50_000)
        d = FlowDetector(config=cfg)
        assert d.config.block_premium_threshold == 50_000


class TestDetectFromMarketData:
    def test_empty_ticker_returns_empty(self):
        d = FlowDetector()
        assert d.detect_from_market_data("", {}) == []

    def test_empty_data_returns_empty(self):
        d = FlowDetector()
        assert d.detect_from_market_data("TSLA", {}) == []

    def test_no_matching_data_returns_empty(self):
        d = FlowDetector()
        result = d.detect_from_market_data("TSLA", {"AAPL": {"last_close": 150}})
        assert result == []

    def test_detects_block_trade(self):
        d = FlowDetector(config=FlowDetectorConfig(
            block_premium_threshold=1000,
            composite_min_score=0,
        ))
        md = {"TSLA": {
            "call_oi": 5000, "put_oi": 2000, "volume": 1000,
            "last_close": 250.0, "atm_iv": 0.40,
        }}
        events = d.detect_from_market_data("TSLA", md)
        types = [e.flow_type for e in events]
        assert "block_trade" in types


class TestComputeScore:
    def test_empty_events(self):
        d = FlowDetector()
        score = d.compute_score([], "TSLA")
        assert isinstance(score, FlowScore)
        assert score.score == 0.0
        assert score.event_count == 0

    def test_single_event_score(self):
        d = FlowDetector()
        event = FlowEvent(
            id="e1", ticker="TSLA", flow_type="block_trade",
            direction="bullish", premium=200_000, volume=500,
            oi_change=0, score=50.0, timestamp=1.0,
        )
        score = d.compute_score([event], "TSLA")
        assert score.score > 0
        assert score.bullish_flow == 200_000
        assert score.bearish_flow == 0
        assert score.event_count == 1

    def test_net_premium_calculation(self):
        d = FlowDetector()
        events = [
            FlowEvent(id="e1", ticker="TSLA", flow_type="block_trade",
                       direction="bullish", premium=100_000, volume=100,
                       oi_change=0, score=50.0, timestamp=1.0),
            FlowEvent(id="e2", ticker="TSLA", flow_type="sweep",
                       direction="bearish", premium=40_000, volume=200,
                       oi_change=0, score=40.0, timestamp=1.0),
        ]
        score = d.compute_score(events, "TSLA")
        assert score.net_premium == pytest.approx(60_000)
        assert score.event_count == 2

    def test_score_capped_at_100(self):
        d = FlowDetector()
        events = [
            FlowEvent(id=f"e{i}", ticker="TSLA", flow_type="block_trade",
                       direction="bullish", premium=1_000_000, volume=10000,
                       oi_change=0, score=99.0, timestamp=1.0)
            for i in range(10)
        ]
        score = d.compute_score(events, "TSLA")
        assert score.score <= 100.0


class TestScanBatch:
    def test_empty_signals(self):
        d = FlowDetector()
        assert d.scan_batch([]) == []

    def test_skips_empty_ticker(self):
        d = FlowDetector()
        signals = [{"ticker": "", "market_data": {}}]
        assert d.scan_batch(signals) == []

    def test_handles_json_market_data(self):
        import json
        d = FlowDetector(config=FlowDetectorConfig(
            block_premium_threshold=100,
            composite_min_score=0,
        ))
        md = {"TSLA": {
            "call_oi": 5000, "put_oi": 2000, "volume": 1000,
            "last_close": 250.0, "atm_iv": 0.40,
        }}
        signals = [{"ticker": "TSLA", "market_data": json.dumps(md), "id": "s1"}]
        events = d.scan_batch(signals)
        assert len(events) > 0

    def test_handles_detection_error_gracefully(self):
        d = FlowDetector()
        signals = [{"ticker": "TSLA", "market_data": "invalid", "id": "s1"}]
        # Should not raise
        events = d.scan_batch(signals)
        assert isinstance(events, list)


class TestInferDirection:
    def test_high_put_call_ratio_bearish(self):
        d = FlowDetector()
        direction = d._infer_direction_from_oi(1000, 2000, {})
        assert direction == "bearish"

    def test_low_put_call_ratio_bullish(self):
        d = FlowDetector()
        direction = d._infer_direction_from_oi(2000, 500, {})
        assert direction == "bullish"

    def test_balanced_ratio_neutral(self):
        d = FlowDetector()
        direction = d._infer_direction_from_oi(1000, 1000, {})
        assert direction == "neutral"

    def test_zero_call_oi(self):
        d = FlowDetector()
        direction = d._infer_direction_from_oi(0, 100, {})
        assert direction == "bearish"

    def test_zero_both_neutral(self):
        d = FlowDetector()
        direction = d._infer_direction_from_oi(0, 0, {})
        assert direction == "neutral"

    def test_positive_change_overrides_neutral(self):
        d = FlowDetector()
        direction = d._infer_direction_from_oi(1000, 1000, {"change_1d": 3.0})
        assert direction == "bullish"

    def test_negative_change_overrides_neutral(self):
        d = FlowDetector()
        direction = d._infer_direction_from_oi(1000, 1000, {"change_1d": -3.0})
        assert direction == "bearish"


class TestGetBaselineFactor:
    def test_new_ticker_gets_default(self):
        d = FlowDetector()
        factor = d._get_baseline_factor("NEWTICKER", 100_000)
        assert factor == 5.0  # Default for unknown


# =========================================================================
# Part 9: Flow types
# =========================================================================


class TestFlowTypes:
    def test_flow_event_creation(self):
        e = FlowEvent(
            id="e1", ticker="TSLA", flow_type="block_trade",
            direction="bullish", premium=100_000, volume=500,
            oi_change=1000, score=75.0, timestamp=1.0,
        )
        assert e.ticker == "TSLA"
        assert e.flow_type == "block_trade"
        assert e.score == 75.0

    def test_flow_score_creation(self):
        s = FlowScore(
            ticker="TSLA", score=65.0, bullish_flow=200_000,
            bearish_flow=50_000, net_premium=150_000,
            event_count=3, detected_at=1.0,
        )
        assert s.ticker == "TSLA"
        assert s.net_premium == 150_000

    def test_greeks_snapshot_creation(self):
        gs = GreeksSnapshot(
            delta=0.5, gamma=0.02, theta=-5.0, vega=15.0,
            rho=2.0, iv=0.25, underlying_price=150,
            strike=155, dte=30.0, option_type="call",
        )
        assert gs.delta == 0.5
        assert gs.dte == 30.0


# =========================================================================
# Part 10: Stress tests
# =========================================================================


class TestStress:
    @pytest.mark.parametrize("S", [10, 50, 100, 500, 1000, 5000])
    def test_pricing_various_underlyings(self, engine, S):
        price = engine.price(S=S, K=S, T=0.25, sigma=0.25)
        assert price > 0

    @pytest.mark.parametrize("T", [0.001, 0.01, 0.1, 0.25, 0.5, 1.0, 2.0])
    def test_pricing_various_expiries(self, engine, T):
        price = engine.price(S=100, K=100, T=T, sigma=0.25)
        assert price > 0

    @pytest.mark.parametrize("sigma", [0.01, 0.05, 0.10, 0.25, 0.50, 1.0, 2.0])
    def test_pricing_various_vols(self, engine, sigma):
        price = engine.price(S=100, K=100, T=0.25, sigma=sigma)
        assert price > 0
