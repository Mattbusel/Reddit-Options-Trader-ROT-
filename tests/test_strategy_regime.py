"""Tests for market regime detection and strategy-regime performance mapping.

Tests the RegimeDetector class in src/rot/strategy/regime.py, covering:
- Regime classification (bull, bear, sideways, volatile, crisis)
- Indicator computation
- Historical regime detection
- Regime-strategy performance matrix
- Edge cases and boundary conditions
"""

from __future__ import annotations

import time

import pytest

from rot.strategy.regime import (
    RegimeDetector,
    _stance_to_numeric,
    _safe_stdev,
    _safe_mean,
    _compute_sharpe,
)
from rot.strategy.types import MarketRegime, RegimeStrategy, REGIME_TYPES


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_signal(
    stance: str,
    confidence: float = 0.5,
    trend_score: float = 0.5,
    sector: str = "tech",
    created_at: float | None = None,
) -> dict:
    """Create a minimal signal dict for testing."""
    if created_at is None:
        created_at = time.time()
    return {
        "stance": stance,
        "confidence": confidence,
        "trend_score": trend_score,
        "sector": sector,
        "created_at": created_at,
    }


def _make_trade(
    strategy_id: str,
    pnl_pct: float,
    created_at: float | None = None,
) -> dict:
    """Create a minimal trade dict for testing."""
    if created_at is None:
        created_at = time.time()
    return {
        "strategy_id": strategy_id,
        "pnl_pct": pnl_pct,
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# Test: Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    """Test low-level helper functions."""

    def test_stance_to_numeric_bullish(self):
        assert _stance_to_numeric("bullish") == 1.0

    def test_stance_to_numeric_bearish(self):
        assert _stance_to_numeric("bearish") == -1.0

    def test_stance_to_numeric_mixed(self):
        assert _stance_to_numeric("mixed") == 0.0

    def test_stance_to_numeric_unknown(self):
        assert _stance_to_numeric("unknown") == 0.0

    def test_safe_stdev_empty(self):
        assert _safe_stdev([]) == 0.0

    def test_safe_stdev_single(self):
        assert _safe_stdev([1.0]) == 0.0

    def test_safe_stdev_normal(self):
        # Known values: mean=3, stdev=1 for [2,3,4]
        result = _safe_stdev([2.0, 3.0, 4.0])
        assert abs(result - 1.0) < 0.01

    def test_safe_mean_empty(self):
        assert _safe_mean([]) == 0.0

    def test_safe_mean_normal(self):
        assert _safe_mean([1.0, 2.0, 3.0]) == 2.0

    def test_compute_sharpe_empty(self):
        assert _compute_sharpe([]) == 0.0

    def test_compute_sharpe_single(self):
        assert _compute_sharpe([1.0]) == 0.0

    def test_compute_sharpe_zero_stdev(self):
        # All returns the same -> zero stdev -> sharpe=0
        assert _compute_sharpe([1.0, 1.0, 1.0]) == 0.0

    def test_compute_sharpe_positive(self):
        # Mean=1.0, stdev=0.8165, sharpe=1.225 * sqrt(252) ~= 19.4
        sharpe = _compute_sharpe([0.0, 1.0, 2.0])
        assert sharpe > 0


# ---------------------------------------------------------------------------
# Test: RegimeDetector initialization
# ---------------------------------------------------------------------------

class TestRegimeDetectorInit:
    """Test RegimeDetector __init__ validation."""

    def test_default_window(self):
        detector = RegimeDetector()
        assert detector.window_days == 30

    def test_custom_window(self):
        detector = RegimeDetector(window_days=7)
        assert detector.window_days == 7

    def test_invalid_window(self):
        with pytest.raises(ValueError, match="window_days must be >= 1"):
            RegimeDetector(window_days=0)


# ---------------------------------------------------------------------------
# Test: detect_regime classification logic
# ---------------------------------------------------------------------------

class TestDetectRegime:
    """Test detect_regime regime classification."""

    def test_detect_bull_regime(self):
        """Mostly bullish signals -> 'bull'."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        # 30 bullish signals
        signals = [
            _make_signal("bullish", confidence=0.7, trend_score=0.3, created_at=now - i * 100)
            for i in range(30)
        ]

        regime = detector.detect_regime(signals)

        assert regime.regime_type == "bull"
        assert regime.confidence > 0.3
        assert regime.indicators["bullish_ratio"] > 0.65
        assert regime.indicators["signal_count"] == 30

    def test_detect_bear_regime(self):
        """Mostly bearish signals -> 'bear'."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        # 30 bearish signals
        signals = [
            _make_signal("bearish", confidence=0.6, created_at=now - i * 100)
            for i in range(30)
        ]

        regime = detector.detect_regime(signals)

        assert regime.regime_type == "bear"
        assert regime.confidence > 0.3
        assert regime.indicators["bullish_ratio"] < 0.35
        assert regime.indicators["signal_count"] == 30

    def test_detect_sideways_regime(self):
        """Mixed/neutral signals with low volatility -> 'sideways'."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        # Mostly mixed stances (low stance_volatility) with a few directional
        # to keep bullish_ratio near 0.5
        signals = [
            _make_signal("mixed", created_at=now - i * 100)
            for i in range(20)
        ] + [
            _make_signal("bullish", created_at=now - (i + 20) * 100)
            for i in range(5)
        ] + [
            _make_signal("bearish", created_at=now - (i + 25) * 100)
            for i in range(5)
        ]

        regime = detector.detect_regime(signals)

        assert regime.regime_type == "sideways"
        assert 0.35 <= regime.indicators["bullish_ratio"] <= 0.65

    def test_detect_volatile_regime(self):
        """High stance volatility -> 'volatile'."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        # Rapidly alternating bullish/bearish -> high stance stdev
        signals = []
        for i in range(30):
            stance = "bullish" if i % 2 == 0 else "bearish"
            signals.append(_make_signal(stance, created_at=now - i * 100))

        regime = detector.detect_regime(signals)

        # Should be volatile (stance_volatility > 0.6)
        # Alternating [1, -1, 1, -1, ...] has stdev = 1.0
        assert regime.regime_type == "volatile"
        assert regime.indicators["stance_volatility"] > 0.6

    def test_detect_crisis_regime(self):
        """Very high velocity + volatility -> 'crisis'."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        # Need historical baseline to be low so velocity ratio > 3x.
        # Add 10 old signals over 10 days (1/day baseline), then
        # burst of 100 in the recent window (100/day >> 3x normal).
        signals = []

        # Old history: 10 signals over 10 days = 1/day normal
        for i in range(10):
            signals.append(_make_signal("bullish", created_at=now - 86400 * (i + 2)))

        # Recent burst: 100 signals in last day with alternating stances
        for i in range(100):
            stance = "bullish" if i % 2 == 0 else "bearish"
            signals.append(_make_signal(stance, created_at=now - i * 60))

        regime = detector.detect_regime(signals)

        # velocity in window >> normal baseline, and volatility > 0.8
        assert regime.regime_type == "crisis"
        assert regime.indicators["stance_volatility"] > 0.8

    def test_detect_regime_insufficient_signals(self):
        """Fewer than MIN_SIGNALS -> 'sideways' with low confidence."""
        detector = RegimeDetector(window_days=1)

        # Only 2 signals (below MIN_SIGNALS_FOR_DETECTION = 5)
        signals = [
            _make_signal("bullish", created_at=time.time() - 100),
            _make_signal("bearish", created_at=time.time() - 200),
        ]

        regime = detector.detect_regime(signals)

        assert regime.regime_type == "sideways"
        assert regime.confidence == 0.1  # Low confidence
        assert regime.indicators["signal_count"] == 2

    def test_detect_regime_returns_market_regime(self):
        """Verify detect_regime returns valid MarketRegime."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        signals = [
            _make_signal("bullish", created_at=now - i * 100)
            for i in range(10)
        ]

        regime = detector.detect_regime(signals)

        assert isinstance(regime, MarketRegime)
        assert regime.id is not None
        assert regime.regime_type in REGIME_TYPES
        assert 0.0 <= regime.confidence <= 1.0
        assert regime.start_ts > 0
        assert regime.end_ts is None  # Current regime has no end
        assert isinstance(regime.indicators, dict)

    def test_detect_regime_indicators_complete(self):
        """Verify all six indicators are computed."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        signals = [
            _make_signal(
                "bullish",
                confidence=0.7,
                trend_score=0.4,
                sector="tech" if i % 2 == 0 else "finance",
                created_at=now - i * 100,
            )
            for i in range(20)
        ]

        regime = detector.detect_regime(signals)

        assert "bullish_ratio" in regime.indicators
        assert "avg_confidence" in regime.indicators
        assert "signal_velocity" in regime.indicators
        assert "avg_trend_score" in regime.indicators
        assert "stance_volatility" in regime.indicators
        assert "sector_diversity" in regime.indicators
        assert "signal_count" in regime.indicators

        # Check reasonable values
        assert regime.indicators["avg_confidence"] > 0.5
        assert regime.indicators["sector_diversity"] == 2  # tech, finance

    def test_detect_regime_with_mixed_unknown_stances(self):
        """Mixed/unknown stances count as neutral (0.0) for stance_volatility."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        signals = [
            _make_signal("bullish", created_at=now - i * 100) for i in range(5)
        ] + [
            _make_signal("mixed", created_at=now - (i + 5) * 100) for i in range(5)
        ] + [
            _make_signal("unknown", created_at=now - (i + 10) * 100) for i in range(5)
        ]

        regime = detector.detect_regime(signals)

        # Bullish ratio only counts directional signals (5 bullish, 0 bearish)
        assert regime.indicators["bullish_ratio"] == 1.0
        assert regime.regime_type == "bull"


# ---------------------------------------------------------------------------
# Test: detect_regime_history
# ---------------------------------------------------------------------------

class TestDetectRegimeHistory:
    """Test historical regime detection."""

    def test_detect_regime_history_empty(self):
        """Empty signals -> empty history."""
        detector = RegimeDetector(window_days=7)
        history = detector.detect_regime_history([])
        assert history == []

    def test_detect_regime_history_single_regime(self):
        """Insufficient span -> single regime."""
        now = time.time()
        detector = RegimeDetector(window_days=7)

        # Only 2 days of data (< 7 day window)
        signals = [
            _make_signal("bullish", created_at=now - i * 3600)
            for i in range(48)  # 48 hours = 2 days
        ]

        history = detector.detect_regime_history(signals)

        assert len(history) == 1
        assert history[0].regime_type == "bull"
        assert history[0].end_ts is None  # Ongoing

    def test_detect_regime_history_merges_adjacent(self):
        """Adjacent windows with same regime -> merged into one period."""
        now = time.time()
        detector = RegimeDetector(window_days=7)

        # 30 days of consistently bullish signals
        signals = []
        for day in range(30):
            for hour in range(10):  # 10 signals per day
                signals.append(
                    _make_signal(
                        "bullish",
                        created_at=now - (day * 86400 + hour * 3600),
                    )
                )

        history = detector.detect_regime_history(signals, window_days=7)

        # Should merge into a single bull regime
        assert len(history) == 1
        assert history[0].regime_type == "bull"

    def test_detect_regime_history_detects_transitions(self):
        """Market transitions -> multiple regimes in history."""
        now = time.time()
        detector = RegimeDetector(window_days=7)

        signals = []

        # Days 0-15: bullish
        for day in range(15):
            for hour in range(5):
                signals.append(
                    _make_signal(
                        "bullish",
                        created_at=now - (day * 86400 + hour * 3600),
                    )
                )

        # Days 16-30: bearish
        for day in range(16, 31):
            for hour in range(5):
                signals.append(
                    _make_signal(
                        "bearish",
                        created_at=now - (day * 86400 + hour * 3600),
                    )
                )

        history = detector.detect_regime_history(signals, window_days=7)

        # Should detect transition from bear to bull (reverse chronological)
        assert len(history) >= 2
        regime_types = [r.regime_type for r in history]
        assert "bear" in regime_types
        assert "bull" in regime_types

    def test_detect_regime_history_has_timestamps(self):
        """Each regime has start_ts and end_ts (except last)."""
        now = time.time()
        detector = RegimeDetector(window_days=7)

        # 30 days with regime shift
        signals = []
        for day in range(15):
            signals.append(_make_signal("bullish", created_at=now - day * 86400))
        for day in range(16, 31):
            signals.append(_make_signal("bearish", created_at=now - day * 86400))

        history = detector.detect_regime_history(signals, window_days=7)

        for i, regime in enumerate(history):
            assert regime.start_ts > 0
            if i < len(history) - 1:
                # All but last should have end_ts
                assert regime.end_ts is not None
            else:
                # Last regime is ongoing
                assert regime.end_ts is None


# ---------------------------------------------------------------------------
# Test: build_regime_matrix
# ---------------------------------------------------------------------------

class TestBuildRegimeMatrix:
    """Test regime-strategy performance matrix."""

    def test_build_regime_matrix_empty_inputs(self):
        """Empty strategies/trades/regimes -> empty matrix."""
        detector = RegimeDetector()

        assert detector.build_regime_matrix([], [], []) == []

        fake_regime = MarketRegime(
            id="r1",
            regime_type="bull",
            start_ts=0.0,
            end_ts=100.0,
            indicators={},
            confidence=0.5,
        )
        assert detector.build_regime_matrix([], [], [fake_regime]) == []

    def test_build_regime_matrix_no_trades(self):
        """Strategy with no trades -> empty matrix (early return)."""
        detector = RegimeDetector()

        strategies = [{"id": "strat_a"}]
        regimes = [
            MarketRegime(
                id="r1",
                regime_type="bull",
                start_ts=0.0,
                end_ts=100.0,
                indicators={},
                confidence=0.5,
            ),
            MarketRegime(
                id="r2",
                regime_type="bear",
                start_ts=100.0,
                end_ts=200.0,
                indicators={},
                confidence=0.5,
            ),
        ]

        matrix = detector.build_regime_matrix(strategies, [], regimes)

        # No trades -> early return with empty list
        assert len(matrix) == 0

    def test_build_regime_matrix_computes_win_rate(self):
        """Matrix computes correct win_rate per (strategy, regime)."""
        now = time.time()
        detector = RegimeDetector()

        strategies = [{"id": "strat_a"}]
        regimes = [
            MarketRegime(
                id="r1",
                regime_type="bull",
                start_ts=now - 1000,
                end_ts=now,
                indicators={},
                confidence=0.5,
            ),
        ]

        # 3 wins, 2 losses -> win_rate = 0.6
        trades = [
            _make_trade("strat_a", pnl_pct=5.0, created_at=now - 900),
            _make_trade("strat_a", pnl_pct=3.0, created_at=now - 800),
            _make_trade("strat_a", pnl_pct=-2.0, created_at=now - 700),
            _make_trade("strat_a", pnl_pct=4.0, created_at=now - 600),
            _make_trade("strat_a", pnl_pct=-1.0, created_at=now - 500),
        ]

        matrix = detector.build_regime_matrix(strategies, trades, regimes)

        assert len(matrix) == 1
        entry = matrix[0]
        assert entry.win_rate == 0.6  # 3 wins / 5 trades
        assert entry.total_trades == 5

    def test_build_regime_matrix_computes_sharpe(self):
        """Matrix computes Sharpe ratio."""
        now = time.time()
        detector = RegimeDetector()

        strategies = [{"id": "strat_a"}]
        regimes = [
            MarketRegime(
                id="r1",
                regime_type="bull",
                start_ts=now - 1000,
                end_ts=now,
                indicators={},
                confidence=0.5,
            ),
        ]

        trades = [
            _make_trade("strat_a", pnl_pct=1.0, created_at=now - 900),
            _make_trade("strat_a", pnl_pct=2.0, created_at=now - 800),
            _make_trade("strat_a", pnl_pct=3.0, created_at=now - 700),
        ]

        matrix = detector.build_regime_matrix(strategies, trades, regimes)

        entry = matrix[0]
        assert entry.sharpe > 0  # Should be positive
        assert entry.avg_pnl_pct == 2.0  # mean of [1, 2, 3]

    def test_build_regime_matrix_marks_recommended(self):
        """Entries with win_rate > 0.55 and trades >= 5 -> recommended."""
        now = time.time()
        detector = RegimeDetector()

        strategies = [{"id": "strat_a"}]
        regimes = [
            MarketRegime(
                id="r1",
                regime_type="bull",
                start_ts=now - 1000,
                end_ts=now,
                indicators={},
                confidence=0.5,
            ),
        ]

        # 6 wins, 4 losses -> win_rate = 0.6 > 0.55, trades = 10 >= 5
        trades = []
        for i in range(6):
            trades.append(_make_trade("strat_a", pnl_pct=2.0, created_at=now - (i + 1) * 50))
        for i in range(4):
            trades.append(_make_trade("strat_a", pnl_pct=-1.0, created_at=now - (i + 7) * 50))

        matrix = detector.build_regime_matrix(strategies, trades, regimes)

        entry = matrix[0]
        assert entry.recommended is True

    def test_build_regime_matrix_not_recommended_low_win_rate(self):
        """win_rate < 0.55 -> not recommended."""
        now = time.time()
        detector = RegimeDetector()

        strategies = [{"id": "strat_a"}]
        regimes = [
            MarketRegime(
                id="r1",
                regime_type="bull",
                start_ts=now - 1000,
                end_ts=now,
                indicators={},
                confidence=0.5,
            ),
        ]

        # 2 wins, 8 losses -> win_rate = 0.2
        trades = []
        for i in range(2):
            trades.append(_make_trade("strat_a", pnl_pct=2.0, created_at=now - (i + 1) * 50))
        for i in range(8):
            trades.append(_make_trade("strat_a", pnl_pct=-1.0, created_at=now - (i + 3) * 50))

        matrix = detector.build_regime_matrix(strategies, trades, regimes)

        entry = matrix[0]
        assert entry.recommended is False

    def test_build_regime_matrix_not_recommended_insufficient_trades(self):
        """trades < 5 -> not recommended even with high win rate."""
        now = time.time()
        detector = RegimeDetector()

        strategies = [{"id": "strat_a"}]
        regimes = [
            MarketRegime(
                id="r1",
                regime_type="bull",
                start_ts=now - 1000,
                end_ts=now,
                indicators={},
                confidence=0.5,
            ),
        ]

        # 3 wins, 0 losses -> win_rate = 1.0, but only 3 trades
        trades = [
            _make_trade("strat_a", pnl_pct=2.0, created_at=now - 900),
            _make_trade("strat_a", pnl_pct=3.0, created_at=now - 800),
            _make_trade("strat_a", pnl_pct=1.0, created_at=now - 700),
        ]

        matrix = detector.build_regime_matrix(strategies, trades, regimes)

        entry = matrix[0]
        assert entry.recommended is False

    def test_build_regime_matrix_filters_by_regime_period(self):
        """Only trades within regime period are counted."""
        now = time.time()
        detector = RegimeDetector()

        strategies = [{"id": "strat_a"}]
        regimes = [
            MarketRegime(
                id="r1",
                regime_type="bull",
                start_ts=now - 1000,
                end_ts=now - 500,
                indicators={},
                confidence=0.5,
            ),
        ]

        trades = [
            # Inside regime
            _make_trade("strat_a", pnl_pct=5.0, created_at=now - 900),
            _make_trade("strat_a", pnl_pct=3.0, created_at=now - 700),
            # Outside regime (after end_ts)
            _make_trade("strat_a", pnl_pct=-10.0, created_at=now - 400),
            _make_trade("strat_a", pnl_pct=-10.0, created_at=now - 200),
        ]

        matrix = detector.build_regime_matrix(strategies, trades, regimes)

        entry = matrix[0]
        assert entry.total_trades == 2  # Only 2 trades inside regime
        assert entry.win_rate == 1.0  # Both were winners

    def test_build_regime_matrix_multiple_strategies(self):
        """Matrix has entries for all (strategy, regime) combinations."""
        now = time.time()
        detector = RegimeDetector()

        strategies = [{"id": "strat_a"}, {"id": "strat_b"}]
        regimes = [
            MarketRegime(
                id="r1",
                regime_type="bull",
                start_ts=now - 1000,
                end_ts=now,
                indicators={},
                confidence=0.5,
            ),
            MarketRegime(
                id="r2",
                regime_type="bear",
                start_ts=now - 2000,
                end_ts=now - 1000,
                indicators={},
                confidence=0.5,
            ),
        ]

        trades = [
            _make_trade("strat_a", pnl_pct=1.0, created_at=now - 900),
            _make_trade("strat_b", pnl_pct=2.0, created_at=now - 1500),
        ]

        matrix = detector.build_regime_matrix(strategies, trades, regimes)

        # Should have 4 entries (2 strategies x 2 regimes)
        assert len(matrix) == 4

        strategy_ids = {entry.strategy_id for entry in matrix}
        assert strategy_ids == {"strat_a", "strat_b"}

        regime_types = {entry.regime_type for entry in matrix}
        assert regime_types == {"bull", "bear"}


# ---------------------------------------------------------------------------
# Test: get_regime_recommendation
# ---------------------------------------------------------------------------

class TestGetRegimeRecommendation:
    """Test strategy recommendations for current regime."""

    def test_get_regime_recommendation_empty_matrix(self):
        """Empty matrix -> empty recommendations."""
        detector = RegimeDetector()

        current_regime = MarketRegime(
            id="r1",
            regime_type="bull",
            start_ts=0.0,
            end_ts=None,
            indicators={},
            confidence=0.5,
        )

        recommendations = detector.get_regime_recommendation(current_regime, [])
        assert recommendations == []

    def test_get_regime_recommendation_no_recommended(self):
        """No recommended strategies for regime -> empty list."""
        detector = RegimeDetector()

        current_regime = MarketRegime(
            id="r1",
            regime_type="bull",
            start_ts=0.0,
            end_ts=None,
            indicators={},
            confidence=0.5,
        )

        matrix = [
            RegimeStrategy(
                strategy_id="strat_a",
                regime_type="bull",
                win_rate=0.4,  # Low win rate
                sharpe=0.5,
                total_trades=10,
                avg_pnl_pct=0.5,
                recommended=False,
            ),
        ]

        recommendations = detector.get_regime_recommendation(current_regime, matrix)
        assert recommendations == []

    def test_get_regime_recommendation_sorted_by_sharpe(self):
        """Recommended strategies sorted by Sharpe (descending)."""
        detector = RegimeDetector()

        current_regime = MarketRegime(
            id="r1",
            regime_type="bull",
            start_ts=0.0,
            end_ts=None,
            indicators={},
            confidence=0.5,
        )

        matrix = [
            RegimeStrategy(
                strategy_id="strat_a",
                regime_type="bull",
                win_rate=0.6,
                sharpe=1.5,
                total_trades=10,
                avg_pnl_pct=2.0,
                recommended=True,
            ),
            RegimeStrategy(
                strategy_id="strat_b",
                regime_type="bull",
                win_rate=0.7,
                sharpe=2.5,  # Higher Sharpe
                total_trades=15,
                avg_pnl_pct=3.0,
                recommended=True,
            ),
            RegimeStrategy(
                strategy_id="strat_c",
                regime_type="bull",
                win_rate=0.6,
                sharpe=0.8,  # Lower Sharpe
                total_trades=8,
                avg_pnl_pct=1.0,
                recommended=True,
            ),
        ]

        recommendations = detector.get_regime_recommendation(current_regime, matrix)

        # Should be sorted by Sharpe: strat_b (2.5), strat_a (1.5), strat_c (0.8)
        assert recommendations == ["strat_b", "strat_a", "strat_c"]

    def test_get_regime_recommendation_filters_by_regime(self):
        """Only returns strategies for the current regime type."""
        detector = RegimeDetector()

        current_regime = MarketRegime(
            id="r1",
            regime_type="bull",
            start_ts=0.0,
            end_ts=None,
            indicators={},
            confidence=0.5,
        )

        matrix = [
            RegimeStrategy(
                strategy_id="strat_a",
                regime_type="bull",
                win_rate=0.6,
                sharpe=1.5,
                total_trades=10,
                avg_pnl_pct=2.0,
                recommended=True,
            ),
            RegimeStrategy(
                strategy_id="strat_b",
                regime_type="bear",  # Wrong regime
                win_rate=0.7,
                sharpe=2.5,
                total_trades=15,
                avg_pnl_pct=3.0,
                recommended=True,
            ),
        ]

        recommendations = detector.get_regime_recommendation(current_regime, matrix)

        # Only strat_a matches "bull" regime
        assert recommendations == ["strat_a"]


# ---------------------------------------------------------------------------
# Test: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_detect_regime_single_signal(self):
        """Single signal -> sideways with low confidence."""
        detector = RegimeDetector(window_days=1)

        signals = [_make_signal("bullish", created_at=time.time())]

        regime = detector.detect_regime(signals)

        assert regime.regime_type == "sideways"
        assert regime.confidence == 0.1

    def test_detect_regime_all_same_stance(self):
        """All signals same stance -> strong directional regime."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        signals = [
            _make_signal("bullish", created_at=now - i * 100)
            for i in range(50)
        ]

        regime = detector.detect_regime(signals)

        assert regime.regime_type == "bull"
        assert regime.indicators["bullish_ratio"] == 1.0
        assert regime.confidence > 0.5

    def test_detect_regime_missing_optional_fields(self):
        """Signals missing optional fields -> use defaults."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        # Minimal signals with only stance + created_at
        signals = [
            {"stance": "bullish", "created_at": now - i * 100}
            for i in range(10)
        ]

        regime = detector.detect_regime(signals)

        # Should still classify (uses defaults for missing fields)
        assert regime.regime_type == "bull"
        assert regime.indicators["avg_confidence"] == 0.0  # No confidence data
        assert regime.indicators["avg_trend_score"] == 0.0
        assert regime.indicators["sector_diversity"] == 0

    def test_detect_regime_invalid_timestamps(self):
        """Non-numeric timestamps are ignored."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        signals = [
            {"stance": "bullish", "created_at": "invalid"},
            {"stance": "bullish", "created_at": now - 100},
            {"stance": "bearish", "created_at": now - 200},
        ]

        regime = detector.detect_regime(signals)

        # Should only use the 2 valid signals
        assert regime.indicators["signal_count"] == 2

    def test_build_regime_matrix_ongoing_regime(self):
        """Regime with end_ts=None includes all trades after start_ts."""
        now = time.time()
        detector = RegimeDetector()

        strategies = [{"id": "strat_a"}]
        regimes = [
            MarketRegime(
                id="r1",
                regime_type="bull",
                start_ts=now - 1000,
                end_ts=None,  # Ongoing
                indicators={},
                confidence=0.5,
            ),
        ]

        trades = [
            _make_trade("strat_a", pnl_pct=1.0, created_at=now - 900),
            _make_trade("strat_a", pnl_pct=2.0, created_at=now - 500),
            _make_trade("strat_a", pnl_pct=3.0, created_at=now - 100),
        ]

        matrix = detector.build_regime_matrix(strategies, trades, regimes)

        entry = matrix[0]
        assert entry.total_trades == 3  # All trades after start_ts

    def test_detect_regime_old_signals_filtered(self):
        """Signals outside window_days are not counted."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        signals = [
            # Recent (within 1 day) — need >= 5 for detection
            _make_signal("bullish", created_at=now - 1000),
            _make_signal("bullish", created_at=now - 2000),
            _make_signal("bullish", created_at=now - 3000),
            _make_signal("bullish", created_at=now - 4000),
            _make_signal("bullish", created_at=now - 5000),
            _make_signal("bullish", created_at=now - 6000),
            # Old (outside 1 day window)
            _make_signal("bearish", created_at=now - 90000),
            _make_signal("bearish", created_at=now - 180000),
        ]

        regime = detector.detect_regime(signals)

        # Should only count the 6 recent signals (all bullish)
        assert regime.indicators["signal_count"] == 6
        assert regime.regime_type == "bull"

    def test_detect_regime_confidence_scales_with_signal_count(self):
        """More signals -> higher base confidence."""
        now = time.time()
        detector = RegimeDetector(window_days=1)

        # 10 signals
        signals_10 = [
            _make_signal("bullish", created_at=now - i * 100)
            for i in range(10)
        ]
        regime_10 = detector.detect_regime(signals_10)

        # 50 signals (same ratio)
        signals_50 = [
            _make_signal("bullish", created_at=now - i * 10)
            for i in range(50)
        ]
        regime_50 = detector.detect_regime(signals_50)

        # 50-signal regime should have higher or equal confidence
        assert regime_50.confidence >= regime_10.confidence
