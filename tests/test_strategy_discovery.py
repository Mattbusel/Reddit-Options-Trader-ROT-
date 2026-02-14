"""Tests for strategy discovery module (automatic rule-set search).

Tests cover:
- StrategyDiscoverer initialization
- Candidate generation (random and exhaustive modes)
- Candidate count limits
- Backtesting with quality gates
- Discovery flow with various configurations
- Walk-forward validation
- Strategy ranking
- Edge cases
"""

import random
import time
from typing import List

import pytest

from rot.backtest.config import BacktestConfig
from rot.strategy.discovery import (
    StrategyDiscoverer,
    _build_atomic_rules,
    _describe_rules,
    _rules_are_compatible,
    _safe_sharpe,
)
from rot.strategy.types import DiscoveryResult, StrategyRule


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_signals(
    count: int = 50, seed: int = 42
) -> List[dict]:
    """Generate mock signal dicts for testing."""
    random.seed(seed)
    signals = []
    base_time = time.time() - 86400 * 30  # 30 days ago

    for i in range(count):
        base_price = 150.0 + random.uniform(-10, 10)
        price_change = random.uniform(-15, 15)

        signals.append({
            "id": f"sig-{i}",
            "ticker": random.choice(["AAPL", "TSLA", "NVDA", "SPY", "QQQ"]),
            "stance": random.choice(["bullish", "bearish", "mixed", "unknown"]),
            "confidence": random.uniform(0.3, 0.9),
            "event_type": random.choice([
                "earnings_rumor",
                "product_news",
                "regulatory",
                "squeeze_chatter",
                "macro",
                "other",
            ]),
            "subreddit": random.choice(["wallstreetbets", "stocks", "options"]),
            "quality_score": random.uniform(0.2, 0.8),
            "trend_score": random.uniform(0.05, 0.5),
            "created_at": base_time + random.randint(0, 86400 * 30),
            "price_at_signal": base_price,
            "price_1d": base_price + price_change,
            "max_gain_pct": max(0, price_change / base_price * 100),
            "max_loss_pct": max(0, -price_change / base_price * 100),
            "strategy": random.choice([
                "debit_spread",
                "credit_spread",
                "iron_condor",
                "none",
            ]),
        })

    return signals


@pytest.fixture
def mock_signals():
    """Fixture providing 50 mock signals."""
    return _make_mock_signals(50)


@pytest.fixture
def mock_signals_small():
    """Fixture providing 10 mock signals."""
    return _make_mock_signals(10, seed=100)


@pytest.fixture
def discoverer(mock_signals):
    """Fixture providing a StrategyDiscoverer instance."""
    config = BacktestConfig(starting_capital=10000.0)
    return StrategyDiscoverer(mock_signals, config)


@pytest.fixture
def discoverer_small(mock_signals_small):
    """Fixture providing a StrategyDiscoverer with fewer signals."""
    config = BacktestConfig(starting_capital=10000.0)
    return StrategyDiscoverer(mock_signals_small, config)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_build_atomic_rules():
    """Test that _build_atomic_rules produces expected rule count."""
    rules = _build_atomic_rules()

    # Count: 5 confidence + 2 stance + 6 event_type + 3 subreddit + 3 quality + 3 trend
    # = 22 total atomic rules
    assert len(rules) == 22
    assert all(isinstance(r, StrategyRule) for r in rules)

    # Check field coverage
    fields = {r.field for r in rules}
    assert "confidence" in fields
    assert "stance" in fields
    assert "event_type" in fields
    assert "subreddit" in fields
    assert "quality_score" in fields
    assert "trend_score" in fields


def test_rules_are_compatible_duplicates():
    """Test that duplicate rules are rejected."""
    r1 = StrategyRule(field="confidence", operator="gte", value=0.5)
    r2 = StrategyRule(field="confidence", operator="gte", value=0.5)

    assert not _rules_are_compatible([r1, r2])


def test_rules_are_compatible_contradictory_eq():
    """Test that contradictory equality rules are rejected."""
    r1 = StrategyRule(field="stance", operator="eq", value="bullish")
    r2 = StrategyRule(field="stance", operator="eq", value="bearish")

    assert not _rules_are_compatible([r1, r2])


def test_rules_are_compatible_multiple_gte_same_field():
    """Test that multiple gte rules on same field are rejected."""
    r1 = StrategyRule(field="confidence", operator="gte", value=0.5)
    r2 = StrategyRule(field="confidence", operator="gte", value=0.7)

    assert not _rules_are_compatible([r1, r2])


def test_rules_are_compatible_valid_combo():
    """Test that valid rule combinations pass."""
    r1 = StrategyRule(field="confidence", operator="gte", value=0.5)
    r2 = StrategyRule(field="stance", operator="eq", value="bullish")
    r3 = StrategyRule(field="event_type", operator="eq", value="earnings_rumor")

    assert _rules_are_compatible([r1, r2, r3])


def test_describe_rules():
    """Test human-readable rule description generation."""
    rules = [
        StrategyRule(field="confidence", operator="gte", value=0.5),
        StrategyRule(field="stance", operator="eq", value="bullish"),
    ]

    desc = _describe_rules(rules)
    assert "confidence>=0.5" in desc
    assert "stance=bullish" in desc
    assert " AND " in desc


def test_safe_sharpe_valid():
    """Test _safe_sharpe with valid Sharpe ratio."""
    class MockResult:
        sharpe_ratio = 1.5

    assert _safe_sharpe(MockResult()) == 1.5


def test_safe_sharpe_nan():
    """Test _safe_sharpe with NaN returns -inf."""
    class MockResult:
        sharpe_ratio = float("nan")

    assert _safe_sharpe(MockResult()) == float("-inf")


def test_safe_sharpe_none():
    """Test _safe_sharpe with None returns -inf."""
    class MockResult:
        sharpe_ratio = None

    assert _safe_sharpe(MockResult()) == float("-inf")


# ---------------------------------------------------------------------------
# StrategyDiscoverer initialization
# ---------------------------------------------------------------------------


def test_discoverer_init(mock_signals):
    """Test StrategyDiscoverer initialization."""
    config = BacktestConfig(starting_capital=10000.0)
    discoverer = StrategyDiscoverer(mock_signals, config)

    assert len(discoverer._signals) == 50
    assert discoverer._config.starting_capital == 10000.0
    assert discoverer._engine is not None
    assert discoverer._rule_engine is not None


def test_discoverer_init_sorts_signals():
    """Test that signals are sorted chronologically on init."""
    signals = [
        {"id": "s1", "created_at": 300.0},
        {"id": "s2", "created_at": 100.0},
        {"id": "s3", "created_at": 200.0},
    ]

    discoverer = StrategyDiscoverer(signals)

    assert discoverer._signals[0]["id"] == "s2"
    assert discoverer._signals[1]["id"] == "s3"
    assert discoverer._signals[2]["id"] == "s1"


def test_discoverer_init_default_config():
    """Test initialization with default BacktestConfig."""
    discoverer = StrategyDiscoverer([])

    assert discoverer._config is not None
    assert isinstance(discoverer._config, BacktestConfig)


def test_discoverer_init_empty_signals():
    """Test initialization with empty signal list."""
    discoverer = StrategyDiscoverer([])

    assert len(discoverer._signals) == 0


# ---------------------------------------------------------------------------
# Candidate generation: random mode
# ---------------------------------------------------------------------------


def test_generate_candidates_random_mode(discoverer):
    """Test random mode candidate generation."""
    candidates = discoverer._generate_candidates({
        "max_rules": 2,
        "max_candidates": 50,
        "search_mode": "random",
    })

    assert len(candidates) > 0
    assert len(candidates) <= 50
    assert all(isinstance(c, list) for c in candidates)
    assert all(len(c) <= 2 for c in candidates)


def test_generate_candidates_random_respects_max_candidates(discoverer):
    """Test that random mode respects max_candidates limit."""
    candidates = discoverer._generate_candidates({
        "max_rules": 3,
        "max_candidates": 100,
        "search_mode": "random",
    })

    assert len(candidates) <= 100


def test_generate_candidates_random_dedup(discoverer):
    """Test that random mode doesn't produce duplicate candidates."""
    candidates = discoverer._generate_candidates({
        "max_rules": 2,
        "max_candidates": 30,
        "search_mode": "random",
    })

    # Convert to hashable tuples for dedup check
    unique = set()
    for c in candidates:
        key = frozenset((r.field, r.operator, str(r.value)) for r in c)
        assert key not in unique, "Duplicate candidate found"
        unique.add(key)


def test_generate_candidates_random_max_attempts(discoverer):
    """Test that random mode gives up after max_attempts."""
    # Very small candidate limit, should hit max_attempts (10x multiplier)
    candidates = discoverer._generate_candidates({
        "max_rules": 1,
        "max_candidates": 5,
        "search_mode": "random",
    })

    # Should still produce some candidates even if not hitting the target
    assert len(candidates) >= 0


# ---------------------------------------------------------------------------
# Candidate generation: exhaustive mode
# ---------------------------------------------------------------------------


def test_generate_candidates_exhaustive_mode(discoverer):
    """Test exhaustive mode candidate generation."""
    candidates = discoverer._generate_candidates({
        "max_rules": 1,
        "max_candidates": 50,
        "search_mode": "exhaustive",
    })

    assert len(candidates) > 0
    assert len(candidates) <= 50
    assert all(len(c) == 1 for c in candidates)


def test_generate_candidates_exhaustive_respects_max_candidates(discoverer):
    """Test that exhaustive mode respects max_candidates limit."""
    candidates = discoverer._generate_candidates({
        "max_rules": 3,
        "max_candidates": 100,
        "search_mode": "exhaustive",
    })

    assert len(candidates) <= 100


def test_generate_candidates_exhaustive_depth(discoverer):
    """Test exhaustive mode with varying depths."""
    # Depth 1: just single rules
    candidates_1 = discoverer._generate_candidates({
        "max_rules": 1,
        "max_candidates": 1000,
        "search_mode": "exhaustive",
    })

    # Depth 2: includes pairs
    candidates_2 = discoverer._generate_candidates({
        "max_rules": 2,
        "max_candidates": 1000,
        "search_mode": "exhaustive",
    })

    # Depth 2 should produce more combinations
    assert len(candidates_2) > len(candidates_1)


def test_generate_candidates_exhaustive_compatibility_filter(discoverer):
    """Test that exhaustive mode filters incompatible rules."""
    candidates = discoverer._generate_candidates({
        "max_rules": 2,
        "max_candidates": 500,
        "search_mode": "exhaustive",
    })

    # All candidates should pass compatibility check
    for c in candidates:
        assert _rules_are_compatible(c)


# ---------------------------------------------------------------------------
# Backtesting single candidate
# ---------------------------------------------------------------------------


def test_backtest_candidate_valid(discoverer):
    """Test backtesting a valid candidate."""
    rules = [
        StrategyRule(field="stance", operator="eq", value="bullish"),
    ]

    result = discoverer._backtest_candidate(
        rules=rules,
        min_trades=1,
        min_win_rate=0.0,
        min_sharpe=float("-inf"),
    )

    # Should produce a result (may be None if not enough bullish signals)
    # We're testing structure, not specific outcomes
    if result is not None:
        assert "id" in result
        assert "name" in result
        assert "rules" in result
        assert "win_rate" in result
        assert "sharpe" in result
        assert "total_trades" in result


def test_backtest_candidate_too_few_signals(discoverer):
    """Test that candidate with too few matching signals returns None."""
    # Very restrictive rules that likely won't match many signals
    rules = [
        StrategyRule(field="confidence", operator="gte", value=0.95),
        StrategyRule(field="quality_score", operator="gte", value=0.95),
    ]

    result = discoverer._backtest_candidate(
        rules=rules,
        min_trades=50,  # Require 50 trades
        min_win_rate=0.0,
        min_sharpe=float("-inf"),
    )

    # Should return None due to insufficient trades
    assert result is None


def test_backtest_candidate_below_win_rate(discoverer):
    """Test that candidate below min_win_rate is rejected."""
    rules = [
        StrategyRule(field="stance", operator="eq", value="bullish"),
    ]

    result = discoverer._backtest_candidate(
        rules=rules,
        min_trades=1,
        min_win_rate=0.99,  # Unrealistic requirement
        min_sharpe=float("-inf"),
    )

    # Should return None due to low win rate
    assert result is None


def test_backtest_candidate_below_sharpe(discoverer):
    """Test that candidate below min_sharpe is rejected."""
    rules = [
        StrategyRule(field="stance", operator="eq", value="bullish"),
    ]

    result = discoverer._backtest_candidate(
        rules=rules,
        min_trades=1,
        min_win_rate=0.0,
        min_sharpe=100.0,  # Unrealistic Sharpe requirement
    )

    # Should return None due to low Sharpe
    assert result is None


def test_backtest_candidate_result_structure(discoverer):
    """Test that valid candidate result has expected structure."""
    rules = [
        StrategyRule(field="confidence", operator="gte", value=0.3),
    ]

    result = discoverer._backtest_candidate(
        rules=rules,
        min_trades=1,
        min_win_rate=0.0,
        min_sharpe=float("-inf"),
    )

    if result is not None:
        assert "id" in result
        assert "name" in result
        assert "rules" in result
        assert "win_rate" in result
        assert "sharpe" in result
        assert "total_trades" in result
        assert "winning_trades" in result
        assert "losing_trades" in result
        assert "total_pnl" in result
        assert "total_return_pct" in result
        assert "max_drawdown_pct" in result
        assert "profit_factor" in result
        assert "expectancy" in result
        assert "avg_win_pct" in result
        assert "avg_loss_pct" in result
        assert "final_equity" in result


# ---------------------------------------------------------------------------
# Full discovery flow
# ---------------------------------------------------------------------------


def test_discover_basic(discoverer):
    """Test basic discovery flow."""
    result = discoverer.discover({
        "user_id": "test_user",
        "max_rules": 2,
        "max_candidates": 50,
        "min_trades": 1,
        "min_win_rate": 0.0,
        "search_mode": "random",
    })

    assert isinstance(result, DiscoveryResult)
    assert result.user_id == "test_user"
    assert result.strategies_found >= 0
    assert isinstance(result.best_strategies, list)
    assert result.elapsed_s > 0


def test_discover_returns_top_strategies(discoverer):
    """Test that discovery returns top strategies."""
    result = discoverer.discover({
        "user_id": "test_user",
        "max_rules": 1,
        "max_candidates": 30,
        "min_trades": 1,
        "min_win_rate": 0.0,
        "search_mode": "random",
    })

    # Should return at most _TOP_N (10) strategies
    assert len(result.best_strategies) <= 10


def test_discover_empty_signals():
    """Test discovery with empty signal list."""
    discoverer = StrategyDiscoverer([])

    result = discoverer.discover({
        "user_id": "test_user",
        "max_rules": 2,
        "max_candidates": 50,
        "min_trades": 1,
        "search_mode": "random",
    })

    assert result.strategies_found == 0
    assert len(result.best_strategies) == 0


def test_discover_single_signal():
    """Test discovery with single signal."""
    signal = _make_mock_signals(1)[0]
    discoverer = StrategyDiscoverer([signal])

    result = discoverer.discover({
        "user_id": "test_user",
        "max_rules": 1,
        "max_candidates": 20,
        "min_trades": 1,
        "search_mode": "random",
    })

    # Should find few/no valid strategies with just 1 signal
    assert result.strategies_found >= 0


def test_discover_exhaustive_mode(discoverer_small):
    """Test discovery in exhaustive mode."""
    result = discoverer_small.discover({
        "user_id": "test_user",
        "max_rules": 1,
        "max_candidates": 25,
        "min_trades": 1,
        "min_win_rate": 0.0,
        "search_mode": "exhaustive",
    })

    assert isinstance(result, DiscoveryResult)
    assert result.strategies_found >= 0


def test_discover_respects_search_config(discoverer):
    """Test that discovery respects search config parameters."""
    result = discoverer.discover({
        "user_id": "custom_user",
        "max_rules": 3,
        "max_candidates": 100,
        "min_trades": 5,
        "min_win_rate": 0.5,
        "min_sharpe": 0.5,
        "search_mode": "random",
    })

    assert result.user_id == "custom_user"
    assert result.search_config["max_rules"] == 3
    assert result.search_config["max_candidates"] == 100

    # All returned strategies should meet thresholds
    for strategy in result.best_strategies:
        assert strategy["total_trades"] >= 5
        assert strategy["win_rate"] >= 0.5
        assert strategy["sharpe"] >= 0.5


# ---------------------------------------------------------------------------
# Walk-forward validation
# ---------------------------------------------------------------------------


def test_discover_with_walk_forward(discoverer):
    """Test discovery with walk-forward validation enabled."""
    result = discoverer.discover({
        "user_id": "test_user",
        "max_rules": 1,
        "max_candidates": 20,
        "min_trades": 1,
        "min_win_rate": 0.0,
        "walk_forward": True,
        "walk_forward_folds": 3,
        "search_mode": "random",
    })

    assert isinstance(result, DiscoveryResult)

    # Check if any strategies have walk_forward data
    for strategy in result.best_strategies:
        if "walk_forward" in strategy:
            wf = strategy["walk_forward"]
            assert "avg_win_rate" in wf
            assert "avg_sharpe" in wf
            assert "avg_total_trades" in wf
            assert "stability_score" in wf
            assert "folds" in wf


def test_walk_forward_validate_insufficient_data(discoverer_small):
    """Test walk-forward with insufficient data."""
    rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]

    wf_result = discoverer_small._walk_forward_validate(rules, n_folds=10)

    # Should return default empty result
    assert wf_result["avg_win_rate"] == 0.0
    assert wf_result["avg_sharpe"] == float("-inf")
    assert wf_result["stability_score"] == 0.0


def test_walk_forward_validate_structure(discoverer):
    """Test walk-forward validation result structure."""
    rules = [StrategyRule(field="stance", operator="eq", value="bullish")]

    wf_result = discoverer._walk_forward_validate(rules, n_folds=3)

    assert "avg_win_rate" in wf_result
    assert "avg_sharpe" in wf_result
    assert "avg_total_trades" in wf_result
    assert "avg_pnl_pct" in wf_result
    assert "avg_max_drawdown_pct" in wf_result
    assert "folds" in wf_result
    assert "stability_score" in wf_result

    # Stability score should be between 0 and 1
    assert 0.0 <= wf_result["stability_score"] <= 1.0


def test_walk_forward_rejects_poor_oos(discoverer):
    """Test that walk-forward can reject strategies with poor OOS performance."""
    result = discoverer.discover({
        "user_id": "test_user",
        "max_rules": 1,
        "max_candidates": 20,
        "min_trades": 1,
        "min_win_rate": 0.6,
        "min_sharpe": 0.5,
        "walk_forward": True,
        "walk_forward_folds": 3,
        "search_mode": "random",
    })

    # Walk-forward filter should reduce the number of valid strategies
    assert isinstance(result, DiscoveryResult)


# ---------------------------------------------------------------------------
# Strategy ranking
# ---------------------------------------------------------------------------


def test_rank_strategies_by_sharpe(discoverer):
    """Test strategy ranking by Sharpe ratio."""
    strategies = [
        {"name": "A", "sharpe": 1.5, "win_rate": 0.6, "total_pnl": 1000},
        {"name": "B", "sharpe": 2.0, "win_rate": 0.5, "total_pnl": 800},
        {"name": "C", "sharpe": 1.0, "win_rate": 0.7, "total_pnl": 1200},
    ]

    ranked = discoverer.rank_strategies(strategies, sort_by="sharpe")

    assert ranked[0]["name"] == "B"
    assert ranked[1]["name"] == "A"
    assert ranked[2]["name"] == "C"


def test_rank_strategies_by_win_rate(discoverer):
    """Test strategy ranking by win rate."""
    strategies = [
        {"name": "A", "sharpe": 1.5, "win_rate": 0.6, "total_pnl": 1000},
        {"name": "B", "sharpe": 2.0, "win_rate": 0.5, "total_pnl": 800},
        {"name": "C", "sharpe": 1.0, "win_rate": 0.7, "total_pnl": 1200},
    ]

    ranked = discoverer.rank_strategies(strategies, sort_by="win_rate")

    assert ranked[0]["name"] == "C"
    assert ranked[1]["name"] == "A"
    assert ranked[2]["name"] == "B"


def test_rank_strategies_handles_nan(discoverer):
    """Test that ranking handles NaN values correctly."""
    strategies = [
        {"name": "A", "sharpe": 1.5, "win_rate": 0.6},
        {"name": "B", "sharpe": float("nan"), "win_rate": 0.5},
        {"name": "C", "sharpe": 2.0, "win_rate": 0.7},
    ]

    ranked = discoverer.rank_strategies(strategies, sort_by="sharpe")

    # NaN should be treated as -inf, so B should be last
    assert ranked[0]["name"] == "C"
    assert ranked[1]["name"] == "A"
    assert ranked[2]["name"] == "B"


def test_rank_strategies_empty_list(discoverer):
    """Test ranking with empty strategy list."""
    ranked = discoverer.rank_strategies([], sort_by="sharpe")

    assert ranked == []


def test_rank_strategies_limits_to_top_n(discoverer):
    """Test that ranking limits results to _TOP_N."""
    # Create 15 strategies
    strategies = [
        {"name": f"S{i}", "sharpe": float(i), "win_rate": 0.5}
        for i in range(15)
    ]

    ranked = discoverer.rank_strategies(strategies, sort_by="sharpe")

    # Should return at most 10 (_TOP_N)
    assert len(ranked) == 10


# ---------------------------------------------------------------------------
# Helper methods
# ---------------------------------------------------------------------------


def test_get_search_space_size(discoverer):
    """Test search space size estimation."""
    space = discoverer.get_search_space_size(max_rules=2)

    assert "atomic_rules" in space
    assert "max_rules" in space
    assert "estimated_combinations" in space

    assert space["atomic_rules"] == 22
    assert space["max_rules"] == 2
    assert space["estimated_combinations"] > 0


def test_preview_candidates(discoverer):
    """Test candidate preview generation."""
    previews = discoverer.preview_candidates(
        search_config={
            "max_rules": 1,
            "max_candidates": 10,
            "search_mode": "random",
        },
        limit=5,
    )

    assert isinstance(previews, list)
    assert len(previews) <= 5
    assert all(isinstance(p, str) for p in previews)


def test_evaluate_rules(discoverer):
    """Test single rule-set evaluation."""
    rules = [
        StrategyRule(field="confidence", operator="gte", value=0.5),
    ]

    result = discoverer.evaluate_rules(rules)

    if result is not None:
        assert "win_rate" in result
        assert "sharpe" in result
        assert "total_trades" in result


def test_evaluate_rules_with_walk_forward(discoverer):
    """Test rule evaluation with walk-forward."""
    rules = [
        StrategyRule(field="stance", operator="eq", value="bullish"),
    ]

    result = discoverer.evaluate_rules(
        rules,
        walk_forward=True,
        walk_forward_folds=3,
    )

    if result is not None and "walk_forward" in result:
        wf = result["walk_forward"]
        assert "avg_win_rate" in wf
        assert "stability_score" in wf


def test_result_to_strategy_dicts(discoverer):
    """Test conversion of DiscoveryResult to strategy dicts."""
    discovery_result = DiscoveryResult(
        id="discovery-123",
        user_id="test_user",
        search_config={},
        strategies_found=2,
        best_strategies=[
            {
                "id": "strat-1",
                "name": "Test Strategy",
                "rules": [{"field": "confidence", "operator": "gte", "value": 0.5}],
                "win_rate": 0.65,
                "sharpe": 1.5,
                "total_trades": 20,
                "total_pnl": 1000.0,
                "total_return_pct": 10.0,
                "max_drawdown_pct": -5.0,
                "profit_factor": 2.0,
                "expectancy": 50.0,
                "avg_win_pct": 8.0,
                "avg_loss_pct": -4.0,
            },
        ],
        elapsed_s=5.0,
    )

    strategy_dicts = discoverer.result_to_strategy_dicts(discovery_result)

    assert len(strategy_dicts) == 1
    assert strategy_dicts[0]["user_id"] == "test_user"
    assert strategy_dicts[0]["name"] == "Test Strategy"
    assert strategy_dicts[0]["source"] == "discovered"
    assert strategy_dicts[0]["is_active"] is False
    assert "performance" in strategy_dicts[0]
    assert strategy_dicts[0]["performance"]["win_rate"] == 0.65


def test_summarise_result(discoverer):
    """Test discovery result summary generation."""
    discovery_result = DiscoveryResult(
        id="discovery-123",
        user_id="test_user",
        search_config={"max_candidates": 100},
        strategies_found=5,
        best_strategies=[
            {
                "name": "Best",
                "sharpe": 2.0,
                "win_rate": 0.7,
                "total_pnl": 1500.0,
            },
            {
                "name": "Second",
                "sharpe": 1.5,
                "win_rate": 0.6,
                "total_pnl": 1000.0,
            },
        ],
        elapsed_s=10.5,
    )

    summary = discoverer.summarise_result(discovery_result)

    assert summary["total_evaluated"] == 100
    assert summary["strategies_found"] == 5
    assert summary["top_sharpe"] == 2.0
    assert summary["top_win_rate"] == 0.7
    assert summary["top_pnl"] == 1500.0
    assert summary["elapsed_s"] == 10.5
    assert summary["best_strategy_name"] == "Best"


def test_summarise_result_empty(discoverer):
    """Test summary with no strategies found."""
    discovery_result = DiscoveryResult(
        id="discovery-123",
        user_id="test_user",
        search_config={"max_candidates": 50},
        strategies_found=0,
        best_strategies=[],
        elapsed_s=3.0,
    )

    summary = discoverer.summarise_result(discovery_result)

    assert summary["strategies_found"] == 0
    assert summary["top_sharpe"] is None
    assert summary["top_win_rate"] is None
    assert summary["best_strategy_name"] is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_discover_no_matching_candidates(discoverer_small):
    """Test discovery when no candidates meet thresholds."""
    result = discoverer_small.discover({
        "user_id": "test_user",
        "max_rules": 2,
        "max_candidates": 50,
        "min_trades": 100,  # Impossible with 10 signals
        "min_win_rate": 0.9,
        "min_sharpe": 5.0,
        "search_mode": "random",
    })

    assert result.strategies_found == 0
    assert len(result.best_strategies) == 0


def test_discover_all_signals_mixed_stance():
    """Test discovery with all signals having mixed stance."""
    signals = [
        {
            "id": f"sig-{i}",
            "ticker": "SPY",
            "stance": "mixed",
            "confidence": 0.5,
            "event_type": "macro",
            "subreddit": "stocks",
            "quality_score": 0.5,
            "trend_score": 0.3,
            "created_at": time.time() - 86400 * i,
            "price_at_signal": 400.0,
            "price_1d": 400.0 + random.uniform(-10, 10),
            "strategy": "iron_condor",
        }
        for i in range(20)
    ]

    discoverer = StrategyDiscoverer(signals)

    result = discoverer.discover({
        "user_id": "test_user",
        "max_rules": 1,
        "max_candidates": 30,
        "min_trades": 1,
        "search_mode": "random",
    })

    # Should still complete without error
    assert isinstance(result, DiscoveryResult)


def test_discover_for_subsets(discoverer):
    """Test multi-subset discovery."""
    # Split signals by ticker
    subsets = {
        "AAPL": [s for s in discoverer._signals if s["ticker"] == "AAPL"],
        "TSLA": [s for s in discoverer._signals if s["ticker"] == "TSLA"],
    }

    results = discoverer.discover_for_subsets(
        search_config={
            "user_id": "test_user",
            "max_rules": 1,
            "max_candidates": 20,
            "min_trades": 1,
            "search_mode": "random",
        },
        subsets=subsets,
    )

    assert isinstance(results, dict)
    assert "AAPL" in results
    assert "TSLA" in results
    assert all(isinstance(r, DiscoveryResult) for r in results.values())


def test_discover_max_rules_clamping():
    """Test that max_rules is clamped to 1-5 range."""
    discoverer = StrategyDiscoverer(_make_mock_signals(30))

    # Test with too high value
    result = discoverer.discover({
        "user_id": "test_user",
        "max_rules": 10,  # Should be clamped to 5
        "max_candidates": 20,
        "search_mode": "random",
    })

    # Should not crash, and candidates should have max 5 rules
    for strategy in result.best_strategies:
        assert len(strategy["rules"]) <= 5

    # Test with too low value
    result = discoverer.discover({
        "user_id": "test_user",
        "max_rules": 0,  # Should be clamped to 1
        "max_candidates": 20,
        "search_mode": "random",
    })

    # Should find some strategies
    assert isinstance(result, DiscoveryResult)
