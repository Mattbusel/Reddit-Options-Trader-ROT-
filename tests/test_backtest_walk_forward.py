"""Tests for walk-forward analysis."""

from __future__ import annotations

import pytest

from rot.backtest.config import BacktestConfig
from rot.backtest.walk_forward import WalkForwardFold, WalkForwardResult, run_walk_forward


# ── Helpers ──


def _make_signal(idx: int, is_win: bool = True) -> dict:
    entry = 100.0
    exit_1d = 105.0 if is_win else 95.0
    return dict(
        signal_id=f"sig-{idx:03d}",
        ticker="TSLA",
        stance="bullish",
        strategy="debit_spread",
        event_type="product_news",
        confidence=0.65,
        created_at=1700000000.0 + idx * 86400,
        price_at_signal=entry,
        price_1d=exit_1d,
        price_4h=exit_1d - 0.5,
        price_1h=entry + 0.3,
        max_gain_pct=None,
        max_loss_pct=None,
    )


def _make_signals(n: int, win_rate: float = 0.667) -> list[dict]:
    """Create N signals with approximate win_rate."""
    signals = []
    for i in range(n):
        is_win = (i % 3) != 0  # ~67% win rate
        signals.append(_make_signal(i, is_win))
    return signals


# ── Tests ──


class TestWalkForwardInsufficientData:
    def test_empty_signals(self):
        result = run_walk_forward([], BacktestConfig())
        assert result.n_folds == 0
        assert result.stability_score == 0.0

    def test_too_few_signals(self):
        """With < n_folds * 4 signals, returns empty result."""
        signals = _make_signals(10)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        assert result.n_folds == 0

    def test_minimal_signals(self):
        """Just enough signals for walk-forward."""
        signals = _make_signals(25)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        assert result.n_folds > 0


class TestWalkForwardFolds:
    def test_correct_number_of_folds(self):
        signals = _make_signals(50)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        assert result.n_folds == 5

    def test_three_folds(self):
        signals = _make_signals(30)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=3)
        assert result.n_folds == 3

    def test_fold_has_is_and_oos(self):
        signals = _make_signals(50)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        for f in result.folds:
            assert f.is_signals > 0
            assert f.oos_signals > 0


class TestWalkForwardInSamplePct:
    def test_default_70_30(self):
        signals = _make_signals(50)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5, in_sample_pct=0.7)
        assert result.in_sample_pct == 0.7
        # IS should generally be larger than OOS
        for f in result.folds:
            assert f.is_signals >= f.oos_signals

    def test_50_50_split(self):
        signals = _make_signals(50)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5, in_sample_pct=0.5)
        for f in result.folds:
            # Should be roughly equal with 50/50 split
            assert abs(f.is_signals - f.oos_signals) <= 2


class TestWalkForwardMetrics:
    def test_has_avg_oos_return(self):
        signals = _make_signals(50)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        # avg_oos_return should be a real number
        assert isinstance(result.avg_oos_return_pct, float)

    def test_has_avg_oos_win_rate(self):
        signals = _make_signals(50)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        assert 0.0 <= result.avg_oos_win_rate <= 1.0

    def test_total_signals(self):
        signals = _make_signals(50)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        assert result.total_is_signals > 0
        assert result.total_oos_signals > 0
        assert result.total_is_signals + result.total_oos_signals <= 50


class TestWalkForwardStability:
    def test_stability_score_range(self):
        signals = _make_signals(50)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        assert 0.0 <= result.stability_score <= 1.0

    def test_consistent_system_higher_stability(self):
        """A system with consistent returns should have higher stability."""
        # All winners → very consistent OOS performance
        signals = [_make_signal(i, is_win=True) for i in range(60)]
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        assert result.stability_score > 0.3  # should be reasonably stable


class TestWalkForwardDegradation:
    def test_degradation_computed(self):
        signals = _make_signals(50)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        for f in result.folds:
            assert isinstance(f.degradation_pct, float)

    def test_fold_index_sequential(self):
        signals = _make_signals(50)
        result = run_walk_forward(signals, BacktestConfig(), n_folds=5)
        indices = [f.fold_index for f in result.folds]
        assert indices == sorted(indices)
