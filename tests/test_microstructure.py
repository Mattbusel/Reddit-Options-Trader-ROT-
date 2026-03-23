"""Tests for rot.market.microstructure."""

from __future__ import annotations

import pytest

from rot.market.microstructure import (
    BidAskSpreadAnalyzer,
    LiquidityScore,
    MarketImpactEstimator,
    OrderImbalanceDetector,
    PriceDiscoveryMetric,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trades(prices: list[float], sides: list[str] | None = None, sizes: list[float] | None = None) -> list[dict]:
    trades = []
    for i, p in enumerate(prices):
        t: dict = {"price": p}
        if sides:
            t["side"] = sides[i]
        if sizes:
            t["size"] = sizes[i]
        trades.append(t)
    return trades


# ---------------------------------------------------------------------------
# BidAskSpreadAnalyzer
# ---------------------------------------------------------------------------


class TestBidAskSpreadAnalyzer:
    def setup_method(self):
        self.analyzer = BidAskSpreadAnalyzer(min_trades=3)

    def test_estimate_with_quotes(self):
        trades = _trades([100.01, 99.99, 100.02])
        result = self.analyzer.estimate("TSLA", trades, best_bid=99.95, best_ask=100.05)
        assert result.symbol == "TSLA"
        assert result.quoted_spread is not None
        assert abs(result.quoted_spread - 0.10) < 0.01
        assert result.mid_price == 100.0
        assert result.effective_spread is not None
        assert result.half_spread == pytest.approx(result.effective_spread / 2, abs=1e-6)
        assert result.relative_spread_bps is not None
        assert result.n_trades == 3

    def test_estimate_no_quotes(self):
        trades = _trades([100.0, 100.1, 99.9, 100.0])
        result = self.analyzer.estimate("AAPL", trades)
        assert result.effective_spread is not None
        assert result.quoted_spread is not None  # approximated from effective
        assert result.n_trades == 4

    def test_empty_trades(self):
        result = self.analyzer.estimate("NVDA", [])
        assert result.effective_spread is None
        assert result.n_trades == 0

    def test_invalid_prices_skipped(self):
        trades = [{"price": 100.0}, {"price": 0}, {"price": None}, {"price": 100.2}]
        result = self.analyzer.estimate("AMD", trades)
        assert result.n_trades == 4  # all 4 passed in, 2 valid for deviations
        assert result.effective_spread is not None

    def test_relative_spread_bps_positive(self):
        trades = _trades([100.0, 100.5, 99.5])
        result = self.analyzer.estimate("GME", trades, best_bid=99.0, best_ask=101.0)
        assert result.relative_spread_bps is not None
        assert result.relative_spread_bps > 0

    def test_from_options_chain_with_data(self):
        options_data = {
            "last_close": 200.0,
            "options_chain": {"avg_bid_ask_spread_pct": 0.01},  # 1% = 100 bps
        }
        result = self.analyzer.from_options_chain("MSFT", options_data)
        assert result.symbol == "MSFT"
        assert result.mid_price == pytest.approx(200.0, abs=0.01)
        assert result.relative_spread_bps == pytest.approx(100.0, abs=1.0)

    def test_from_options_chain_no_data(self):
        result = self.analyzer.from_options_chain("SPY", {})
        assert result.effective_spread is None

    def test_half_spread_consistency(self):
        trades = _trades([50.0, 50.5, 49.5, 50.1])
        result = self.analyzer.estimate("XYZ", trades, best_bid=49.5, best_ask=50.5)
        if result.effective_spread:
            assert abs(result.half_spread - result.effective_spread / 2) < 1e-9


# ---------------------------------------------------------------------------
# OrderImbalanceDetector
# ---------------------------------------------------------------------------


class TestOrderImbalanceDetector:
    def setup_method(self):
        self.detector = OrderImbalanceDetector(threshold=0.25)

    def test_threshold_validation(self):
        with pytest.raises(ValueError):
            OrderImbalanceDetector(threshold=0.0)
        with pytest.raises(ValueError):
            OrderImbalanceDetector(threshold=1.0)

    def test_buy_heavy(self):
        trades = _trades(
            [100] * 8,
            sides=["buy"] * 7 + ["sell"],
            sizes=[100.0] * 8,
        )
        result = self.detector.detect("TSLA", trades)
        assert result.direction == "buy_heavy"
        assert result.threshold_breached is True
        assert result.buy_volume > result.sell_volume

    def test_sell_heavy(self):
        trades = _trades(
            [100] * 8,
            sides=["sell"] * 7 + ["buy"],
            sizes=[100.0] * 8,
        )
        result = self.detector.detect("TSLA", trades)
        assert result.direction == "sell_heavy"
        assert result.threshold_breached is True

    def test_balanced(self):
        trades = _trades(
            [100] * 4,
            sides=["buy", "sell", "buy", "sell"],
            sizes=[100.0] * 4,
        )
        result = self.detector.detect("TSLA", trades)
        assert result.direction == "balanced"
        assert result.threshold_breached is False
        assert abs(result.imbalance_ratio) < 0.01

    def test_empty_trades(self):
        result = self.detector.detect("TSLA", [])
        assert result.total_volume == 0.0
        assert result.direction == "balanced"
        assert result.threshold_breached is False

    def test_missing_side_skipped(self):
        trades = [
            {"size": 100.0},  # no side
            {"side": "buy", "size": 200.0},
            {"side": "sell"},  # no size
        ]
        result = self.detector.detect("AMD", trades)
        assert result.buy_volume == 200.0
        assert result.sell_volume == 0.0

    def test_imbalance_ratio_range(self):
        trades = _trades(
            [100] * 10,
            sides=["buy"] * 6 + ["sell"] * 4,
            sizes=[100.0] * 10,
        )
        result = self.detector.detect("SPY", trades)
        assert -1.0 <= result.imbalance_ratio <= 1.0
        assert 0.0 <= result.imbalance_pct <= 100.0


# ---------------------------------------------------------------------------
# PriceDiscoveryMetric
# ---------------------------------------------------------------------------


class TestPriceDiscoveryMetric:
    def setup_method(self):
        self.metric = PriceDiscoveryMetric(max_lag=5)

    def test_max_lag_validation(self):
        with pytest.raises(ValueError):
            PriceDiscoveryMetric(max_lag=0)

    def test_unequal_length_raises(self):
        with pytest.raises(ValueError):
            self.metric.compute("TSLA", [1.0, 2.0], [1.0])

    def test_insufficient_data_returns_neutral(self):
        s = [0.5] * 3
        r = [0.5] * 3
        result = self.metric.compute("TSLA", s, r)
        assert result.n_observations == 3
        assert result.max_correlation == 0.0

    def test_leading_sentiment(self):
        # Construct series where sentiment leads returns by 1 period
        n = 30
        import math as _math
        s = [_math.sin(i * 0.3) for i in range(n)]
        # Returns follow sentiment with a 1-period lag
        r = [0.0] + s[:-1]
        result = self.metric.compute("TSLA", s, r)
        assert result.n_observations == n
        assert result.optimal_lag >= 0  # sentiment leads or contemporaneous
        assert abs(result.max_correlation) > 0.0

    def test_lagging_sentiment(self):
        n = 30
        import math as _math
        r = [_math.sin(i * 0.3) for i in range(n)]
        # Sentiment follows returns with a 1-period lag
        s = [0.0] + r[:-1]
        result = self.metric.compute("TSLA", s, r)
        assert result.optimal_lag <= 0  # sentiment lags or contemporaneous

    def test_contemporaneous_fields(self):
        result = self.metric.compute("AAPL", [1.0] * 5, [1.0] * 5)
        # Degenerate case: should not raise
        assert isinstance(result.is_contemporaneous, bool)

    def test_perfect_correlation_at_zero_lag(self):
        # Use a non-monotone oscillating series so the max correlation
        # genuinely peaks at lag=0 (shifted copies are less correlated).
        import math as _math
        n = 30
        s = [_math.sin(i * 0.7) + _math.cos(i * 1.3) for i in range(n)]
        result = self.metric.compute("SPY", s, s)
        # At lag=0 the series is identical → correlation = 1.0;
        # for any non-zero lag the series differ, so lag=0 should win.
        assert result.optimal_lag == 0
        assert abs(result.max_correlation - 1.0) < 0.01


# ---------------------------------------------------------------------------
# MarketImpactEstimator
# ---------------------------------------------------------------------------


class TestMarketImpactEstimator:
    def setup_method(self):
        self.estimator = MarketImpactEstimator(low_threshold=0.01, high_threshold=0.10)

    def test_unequal_length_raises(self):
        with pytest.raises(ValueError):
            self.estimator.estimate("TSLA", [1.0, 2.0], [1.0])

    def test_insufficient_data(self):
        result = self.estimator.estimate("TSLA", [1.0], [0.01])
        assert result.lambda_value == 0.0
        assert result.r_squared == 0.0

    def test_perfect_linear_relationship(self):
        # price_change = 0.05 * flow  → lambda=0.05, R²=1.0
        # Use 10+ points so OLS is well-determined
        flows = [float(i * 100) for i in range(1, 11)]
        changes = [f * 0.05 for f in flows]
        result = self.estimator.estimate("AAPL", flows, changes)
        assert result.lambda_value == pytest.approx(0.05, rel=0.01)
        assert result.r_squared > 0.99
        # 0.01 < 0.05 < 0.10 → "medium" illiquidity
        assert result.interpretation == "medium"

    def test_high_lambda_interpretation(self):
        flows = [10.0, 20.0, 30.0, 40.0, 50.0]
        changes = [f * 0.5 for f in flows]  # lambda=0.5 > high_threshold=0.10
        result = self.estimator.estimate("MEME", flows, changes)
        assert result.interpretation == "high"

    def test_low_lambda_interpretation(self):
        flows = [100.0, 200.0, 300.0, 400.0, 500.0]
        changes = [f * 0.001 for f in flows]  # lambda=0.001 < low_threshold=0.01
        result = self.estimator.estimate("AAPL", flows, changes)
        assert result.interpretation == "low"

    def test_zero_variance_flows(self):
        flows = [100.0] * 5
        changes = [0.01, 0.02, 0.01, 0.03, 0.01]
        result = self.estimator.estimate("FLAT", flows, changes)
        assert result.lambda_value == 0.0  # no variance in x → slope = 0

    def test_negative_flows(self):
        # Lambda should be absolute value
        flows = [-100.0, -200.0, -300.0, -400.0, -500.0]
        changes = [f * 0.05 for f in flows]
        result = self.estimator.estimate("SELL", flows, changes)
        assert result.lambda_value >= 0.0


# ---------------------------------------------------------------------------
# LiquidityScore
# ---------------------------------------------------------------------------


class TestLiquidityScore:
    def setup_method(self):
        self.scorer = LiquidityScore()

    def test_weight_sum_validation(self):
        with pytest.raises(ValueError):
            LiquidityScore(spread_weight=0.5, depth_weight=0.5, turnover_weight=0.5)

    def test_high_liquidity(self):
        result = self.scorer.score(
            "AAPL",
            spread_bps=5.0,
            open_interest=80_000.0,
            daily_volume=5_000_000.0,
        )
        assert result.composite_score > 0.65
        assert result.classification == "high"
        assert result.symbol == "AAPL"

    def test_low_liquidity(self):
        result = self.scorer.score(
            "MEME",
            spread_bps=190.0,
            open_interest=100.0,
            daily_volume=10_000.0,
        )
        assert result.composite_score < 0.35
        assert result.classification == "low"

    def test_neutral_when_no_data(self):
        result = self.scorer.score("UNKNOWN")
        # All components neutral (0.5) → composite = 0.5
        assert abs(result.composite_score - 0.5) < 0.01
        assert result.classification == "medium"

    def test_partial_data(self):
        result = self.scorer.score("SPY", spread_bps=10.0)
        assert result.spread_score > 0.9  # good spread
        assert result.depth_score == pytest.approx(0.5, abs=0.01)  # neutral
        assert result.turnover_score == pytest.approx(0.5, abs=0.01)

    def test_scores_in_range(self):
        for spread in [0.0, 50.0, 200.0, 500.0]:
            result = self.scorer.score("X", spread_bps=spread, open_interest=50000, daily_volume=1e6)
            assert 0.0 <= result.composite_score <= 1.0
            assert 0.0 <= result.spread_score <= 1.0
            assert 0.0 <= result.depth_score <= 1.0
            assert 0.0 <= result.turnover_score <= 1.0

    def test_from_market_data(self):
        market_data = {
            "last_close": 150.0,
            "options_chain": {"avg_bid_ask_spread_pct": 0.005},  # 50bps
            "call_oi": 30000,
            "put_oi": 20000,
            "volume": 2_000_000,
        }
        result = self.scorer.from_market_data("AAPL", market_data)
        assert result.symbol == "AAPL"
        assert 0.0 <= result.composite_score <= 1.0

    def test_from_market_data_empty(self):
        result = self.scorer.from_market_data("EMPTY", {})
        assert result.composite_score == pytest.approx(0.5, abs=0.01)

    def test_classification_thresholds(self):
        high = self.scorer.score("H", spread_bps=0.0, open_interest=100_000, daily_volume=10_000_000)
        assert high.classification == "high"
        low = self.scorer.score("L", spread_bps=300.0, open_interest=0.0, daily_volume=0.0)
        assert low.classification in ("low", "medium")
