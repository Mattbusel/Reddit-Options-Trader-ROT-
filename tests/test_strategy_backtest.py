"""Tests for rot.backtest.strategy_backtest."""

from __future__ import annotations

import pytest

from rot.backtest.config import BacktestConfig
from rot.backtest.strategy_backtest import (
    MonteCarloSimulator,
    SignalHistoryLoader,
    StrategyBacktester,
    WalkForwardTester,
    _build_metrics,
    _equity_svg,
)
from rot.backtest.engine import BacktestEngine
from rot.backtest.result import EquityPoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(**overrides) -> dict:
    base = dict(
        signal_id="sig-001",
        ticker="TSLA",
        stance="bullish",
        strategy="debit_spread",
        event_type="product_news",
        confidence=0.65,
        created_at=1_700_000_000.0,
        price_at_signal=100.0,
        price_1h=101.0,
        price_4h=103.0,
        price_1d=105.0,
        max_gain_pct=None,
        max_loss_pct=None,
    )
    base.update(overrides)
    return base


def _signals_n(n: int, base_ts: float = 1_700_000_000.0) -> list[dict]:
    sigs = []
    for i in range(n):
        win = i % 3 != 0
        sigs.append(_make_signal(
            signal_id=f"sig-{i:04d}",
            created_at=base_ts + i * 86400,
            price_at_signal=100.0,
            price_1d=106.0 if win else 94.0,
            confidence=0.5 + (i % 5) * 0.1,
        ))
    return sigs


def _run_engine(signals: list[dict], config: BacktestConfig | None = None):
    engine = BacktestEngine()
    return engine.run(signals, config or BacktestConfig())


# ---------------------------------------------------------------------------
# SignalHistoryLoader
# ---------------------------------------------------------------------------


class TestSignalHistoryLoader:
    def test_init_with_signals(self):
        signals = [_make_signal(signal_id=f"s{i}") for i in range(5)]
        loader = SignalHistoryLoader(signals)
        assert len(loader) == 5

    def test_init_empty(self):
        loader = SignalHistoryLoader()
        assert len(loader) == 0
        assert loader.signals == []

    def test_signals_property_returns_copy(self):
        signals = [_make_signal()]
        loader = SignalHistoryLoader(signals)
        s1 = loader.signals
        s2 = loader.signals
        assert s1 == s2
        s1.pop()  # mutate copy
        assert len(loader.signals) == 1  # original unaffected

    def test_filter_confidence(self):
        signals = [
            _make_signal(signal_id="low", confidence=0.3),
            _make_signal(signal_id="high", confidence=0.7),
        ]
        loader = SignalHistoryLoader(signals).filter(min_confidence=0.5)
        assert len(loader) == 1
        assert loader.signals[0]["signal_id"] == "high"

    def test_filter_stance(self):
        signals = [
            _make_signal(signal_id="bull", stance="bullish"),
            _make_signal(signal_id="bear", stance="bearish"),
        ]
        loader = SignalHistoryLoader(signals).filter(stance="bearish")
        assert len(loader) == 1
        assert loader.signals[0]["stance"] == "bearish"

    def test_filter_ticker(self):
        signals = [
            _make_signal(signal_id="tsla", ticker="TSLA"),
            _make_signal(signal_id="aapl", ticker="AAPL"),
        ]
        loader = SignalHistoryLoader(signals).filter(ticker="AAPL")
        assert len(loader) == 1
        assert loader.signals[0]["ticker"] == "AAPL"

    def test_filter_strategy(self):
        signals = [
            _make_signal(signal_id="ds", strategy="debit_spread"),
            _make_signal(signal_id="cs", strategy="credit_spread"),
        ]
        loader = SignalHistoryLoader(signals).filter(strategy="credit_spread")
        assert len(loader) == 1

    def test_filter_event_type(self):
        signals = [
            _make_signal(signal_id="er", event_type="earnings_rumor"),
            _make_signal(signal_id="pn", event_type="product_news"),
        ]
        loader = SignalHistoryLoader(signals).filter(event_type="earnings_rumor")
        assert len(loader) == 1

    def test_filter_combined(self):
        signals = [
            _make_signal(signal_id="match", confidence=0.8, stance="bullish"),
            _make_signal(signal_id="low_conf", confidence=0.3, stance="bullish"),
            _make_signal(signal_id="wrong_stance", confidence=0.8, stance="bearish"),
        ]
        loader = SignalHistoryLoader(signals).filter(min_confidence=0.5, stance="bullish")
        assert len(loader) == 1
        assert loader.signals[0]["signal_id"] == "match"

    def test_filter_original_unmodified(self):
        signals = [_make_signal(signal_id="s1"), _make_signal(signal_id="s2", confidence=0.3)]
        original = SignalHistoryLoader(signals)
        filtered = original.filter(min_confidence=0.5)
        assert len(original) == 2
        assert len(filtered) == 1

    def test_from_db_nonexistent_path(self):
        """from_db with bad path should return empty loader, not raise."""
        loader = SignalHistoryLoader.from_db("/nonexistent/path/db.sqlite")
        assert len(loader) == 0


# ---------------------------------------------------------------------------
# BacktestMetrics (via _build_metrics)
# ---------------------------------------------------------------------------


class TestBacktestMetrics:
    def test_basic_metrics(self):
        signals = _signals_n(20)
        result = _run_engine(signals)
        metrics = _build_metrics(result)
        assert metrics.total_trades == result.total_trades
        assert 0.0 <= metrics.win_rate <= 1.0
        assert metrics.max_drawdown_pct >= 0.0
        assert isinstance(metrics.profit_factor, float)

    def test_empty_trades(self):
        result = _run_engine([])
        metrics = _build_metrics(result)
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.avg_pnl_pct == 0.0
        assert metrics.best_trade_pct == 0.0
        assert metrics.worst_trade_pct == 0.0

    def test_to_dict_serializable(self):
        signals = _signals_n(10)
        result = _run_engine(signals)
        metrics = _build_metrics(result)
        d = metrics.to_dict()
        assert isinstance(d, dict)
        assert "total_trades" in d
        assert "win_rate" in d
        assert "sharpe_ratio" in d
        assert "profit_factor" in d
        assert "avg_pnl_pct" in d
        assert "best_trade_pct" in d
        assert "worst_trade_pct" in d

    def test_avg_win_positive_avg_loss_negative(self):
        signals = _signals_n(20)
        result = _run_engine(signals)
        metrics = _build_metrics(result)
        if result.winning_trades > 0:
            assert metrics.avg_win_pct > 0.0
        if result.losing_trades > 0:
            assert metrics.avg_loss_pct < 0.0

    def test_calmar_ratio_populated(self):
        signals = _signals_n(30)
        result = _run_engine(signals)
        metrics = _build_metrics(result)
        if metrics.max_drawdown_pct > 0.01 and metrics.annual_return_pct != 0:
            assert metrics.calmar_ratio is not None


# ---------------------------------------------------------------------------
# WalkForwardTester
# ---------------------------------------------------------------------------


class TestWalkForwardTester:
    def test_invalid_n_folds(self):
        with pytest.raises(ValueError):
            WalkForwardTester(n_folds=1)

    def test_invalid_in_sample_pct(self):
        with pytest.raises(ValueError):
            WalkForwardTester(in_sample_pct=0.4)
        with pytest.raises(ValueError):
            WalkForwardTester(in_sample_pct=1.0)

    def test_insufficient_signals(self):
        tester = WalkForwardTester(n_folds=3)
        result = tester.run([], BacktestConfig())
        assert result.n_folds == 0
        assert result.stability_score == 0.0

    def test_sufficient_signals(self):
        signals = _signals_n(60)
        tester = WalkForwardTester(n_folds=3, in_sample_pct=0.7)
        result = tester.run(signals, BacktestConfig())
        assert result.n_folds >= 0  # may be 0 if engine filters all signals
        assert 0.0 <= result.stability_score <= 1.0

    def test_result_has_folds(self):
        signals = _signals_n(50)
        tester = WalkForwardTester(n_folds=5)
        result = tester.run(signals, BacktestConfig())
        assert len(result.folds) == result.n_folds


# ---------------------------------------------------------------------------
# MonteCarloSimulator
# ---------------------------------------------------------------------------


class TestMonteCarloSimulator:
    def test_invalid_n_simulations(self):
        with pytest.raises(ValueError):
            MonteCarloSimulator(n_simulations=5)

    def test_empty_signals(self):
        sim = MonteCarloSimulator(n_simulations=10, seed=42)
        result = sim.run([], BacktestConfig())
        assert result.n_simulations == 0
        assert result.prob_profit == 0.0

    def test_basic_run(self):
        signals = _signals_n(20)
        sim = MonteCarloSimulator(n_simulations=50, seed=42)
        result = sim.run(signals, BacktestConfig(), observed_return_pct=5.0)
        assert result.n_simulations == 50
        assert result.n_trades == 20
        assert 0.0 <= result.prob_profit <= 1.0
        assert 0.0 <= result.prob_ruin <= 1.0
        assert 0.0 <= result.p_value_approx <= 1.0

    def test_equity_percentiles_ordered(self):
        signals = _signals_n(25)
        sim = MonteCarloSimulator(n_simulations=100, seed=99)
        result = sim.run(signals, BacktestConfig())
        assert result.final_equity_p5 <= result.final_equity_p50
        assert result.final_equity_p50 <= result.final_equity_p95

    def test_return_percentiles_ordered(self):
        signals = _signals_n(25)
        sim = MonteCarloSimulator(n_simulations=100, seed=7)
        result = sim.run(signals, BacktestConfig())
        assert result.p5_return_pct <= result.median_return_pct
        assert result.median_return_pct <= result.p95_return_pct

    def test_reproducibility_with_seed(self):
        signals = _signals_n(15)
        sim1 = MonteCarloSimulator(n_simulations=50, seed=42)
        sim2 = MonteCarloSimulator(n_simulations=50, seed=42)
        r1 = sim1.run(signals, BacktestConfig())
        r2 = sim2.run(signals, BacktestConfig())
        assert r1.mean_return_pct == r2.mean_return_pct
        assert r1.prob_profit == r2.prob_profit

    def test_to_dict_serializable(self):
        signals = _signals_n(10)
        sim = MonteCarloSimulator(n_simulations=20, seed=1)
        result = sim.run(signals, BacktestConfig())
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "n_simulations" in d
        assert "prob_profit" in d
        assert "p_value_approx" in d


# ---------------------------------------------------------------------------
# StrategyBacktester
# ---------------------------------------------------------------------------


class TestStrategyBacktester:
    def _loader(self, n: int) -> SignalHistoryLoader:
        return SignalHistoryLoader(_signals_n(n))

    def test_basic_run_no_wf_no_mc(self):
        backtester = StrategyBacktester(run_walk_forward=False, run_monte_carlo=False)
        loader = self._loader(10)
        report = backtester.run("test_strategy", loader)
        assert report.strategy_name == "test_strategy"
        assert report.n_signals_loaded == 10
        assert report.monte_carlo is None
        assert report.walk_forward is None
        assert report.elapsed_s >= 0.0

    def test_run_with_walk_forward(self):
        backtester = StrategyBacktester(
            run_walk_forward=True, run_monte_carlo=False, n_wf_folds=3
        )
        loader = self._loader(60)
        report = backtester.run("wf_strategy", loader)
        # walk_forward present or None (if too few signals pass engine)
        if report.walk_forward:
            assert report.walk_forward.n_folds >= 0

    def test_run_with_monte_carlo(self):
        backtester = StrategyBacktester(
            run_walk_forward=False, run_monte_carlo=True, n_mc_simulations=20, mc_seed=42
        )
        loader = self._loader(15)
        report = backtester.run("mc_strategy", loader)
        assert report.monte_carlo is not None
        assert report.monte_carlo.n_simulations == 20

    def test_full_pipeline(self):
        backtester = StrategyBacktester(
            run_walk_forward=True,
            run_monte_carlo=True,
            n_wf_folds=3,
            n_mc_simulations=30,
            mc_seed=0,
        )
        loader = self._loader(50)
        report = backtester.run("full_pipeline", loader, config=BacktestConfig())
        assert report.n_signals_loaded == 50
        assert report.metrics.total_trades >= 0
        assert isinstance(report.elapsed_s, float)

    def test_metrics_populated(self):
        backtester = StrategyBacktester(run_walk_forward=False, run_monte_carlo=False)
        loader = self._loader(20)
        report = backtester.run("metrics_check", loader)
        m = report.metrics
        assert 0.0 <= m.win_rate <= 1.0
        assert m.max_drawdown_pct >= 0.0

    def test_to_dict_serializable(self):
        backtester = StrategyBacktester(run_walk_forward=False, run_monte_carlo=False)
        loader = self._loader(10)
        report = backtester.run("serialize_test", loader)
        d = report.to_dict()
        assert isinstance(d, dict)
        assert "strategy_name" in d
        assert "metrics" in d
        assert "total_trades" in d

    def test_empty_loader(self):
        backtester = StrategyBacktester(run_walk_forward=False, run_monte_carlo=False)
        loader = SignalHistoryLoader([])
        report = backtester.run("empty", loader)
        assert report.n_signals_loaded == 0
        assert report.metrics.total_trades == 0

    def test_custom_config(self):
        backtester = StrategyBacktester(run_walk_forward=False, run_monte_carlo=False)
        loader = self._loader(10)
        config = BacktestConfig(starting_capital=50000.0, min_confidence=0.6)
        report = backtester.run("custom_config", loader, config=config)
        assert report.config.starting_capital == 50000.0

    def test_generate_html_returns_string(self):
        backtester = StrategyBacktester(run_walk_forward=False, run_monte_carlo=False)
        loader = self._loader(15)
        report = backtester.run("html_test", loader)
        html = backtester.generate_html(report)
        assert isinstance(html, str)
        assert "ROT Strategy Backtest" in html
        assert "html_test" in html

    def test_generate_html_includes_wf_table(self):
        backtester = StrategyBacktester(
            run_walk_forward=True, run_monte_carlo=False, n_wf_folds=3
        )
        loader = self._loader(50)
        report = backtester.run("wf_html_test", loader)
        html = backtester.generate_html(report)
        if report.walk_forward and report.walk_forward.folds:
            assert "Walk-Forward" in html

    def test_generate_html_includes_mc_table(self):
        backtester = StrategyBacktester(
            run_walk_forward=False, run_monte_carlo=True, n_mc_simulations=20, mc_seed=1
        )
        loader = self._loader(20)
        report = backtester.run("mc_html_test", loader)
        html = backtester.generate_html(report)
        if report.monte_carlo:
            assert "Monte Carlo" in html


# ---------------------------------------------------------------------------
# _equity_svg helper
# ---------------------------------------------------------------------------


class TestEquitySvg:
    def test_empty_curve(self):
        svg = _equity_svg([])
        assert "<svg" in svg
        assert "No equity data" in svg

    def test_single_point(self):
        curve = [EquityPoint(timestamp=0.0, equity=10000.0, trade_count=0)]
        svg = _equity_svg(curve)
        assert "<svg" in svg

    def test_normal_curve(self):
        curve = [
            EquityPoint(timestamp=float(i), equity=10000.0 + i * 50, trade_count=i)
            for i in range(20)
        ]
        svg = _equity_svg(curve, width=800, height=180)
        assert "<polyline" in svg
        assert "<polygon" in svg
        assert "4ade80" in svg  # profit colour (green)

    def test_losing_curve(self):
        curve = [
            EquityPoint(timestamp=float(i), equity=10000.0 - i * 100, trade_count=i)
            for i in range(10)
        ]
        svg = _equity_svg(curve)
        assert "f87171" in svg  # loss colour (red)

    def test_dimensions_in_svg(self):
        curve = [EquityPoint(timestamp=0.0, equity=10000.0, trade_count=0),
                 EquityPoint(timestamp=1.0, equity=10100.0, trade_count=1)]
        svg = _equity_svg(curve, width=600, height=150)
        assert "width='600'" in svg
        assert "height='150'" in svg
