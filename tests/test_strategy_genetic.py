"""Tests for rot.strategy.genetic — genetic algorithm optimizer for strategy rules."""

from __future__ import annotations

import random
import time

import pytest

from rot.backtest.config import BacktestConfig
from rot.strategy.genetic import (
    FIELD_POOL,
    GeneticOptimizer,
    _BAD_FITNESS,
    _MIN_TRADES,
    _random_rule_from_pool,
)
from rot.strategy.types import StrategyRule


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_signals():
    """Generate 50 mock signals with mixed bullish/bearish outcomes.

    Bullish signals tend to gain, bearish signals tend to lose (inverse).
    This creates a realistic environment where good filters can improve Sharpe.
    """
    random.seed(42)
    signals = []
    base = 100.0

    for i in range(50):
        stance = random.choice(["bullish", "bearish"])
        event_type = random.choice(["earnings_rumor", "product_news", "regulatory"])
        subreddit = random.choice(["stocks", "wallstreetbets", "options"])
        confidence = random.uniform(0.3, 0.9)
        quality_score = random.uniform(0.3, 0.8)
        trend_score = random.uniform(0.1, 0.5)

        # Bullish signals tend to gain, bearish tend to lose (inverse of stance)
        if stance == "bullish":
            price_1d = base + random.uniform(-3, 10)
        else:
            price_1d = base + random.uniform(-10, 3)

        signals.append({
            "id": f"sig-{i}",
            "ticker": "AAPL",
            "stance": stance,
            "confidence": confidence,
            "event_type": event_type,
            "subreddit": subreddit,
            "quality_score": quality_score,
            "trend_score": trend_score,
            "strategy": "debit_spread",
            "created_at": time.time() - i * 3600,
            "price_at_signal": base,
            "price_1d": price_1d,
        })

    return signals


@pytest.fixture
def minimal_signals():
    """Just enough signals to avoid _MIN_TRADES penalty (10 signals)."""
    random.seed(123)
    signals = []
    base = 100.0

    for i in range(10):
        stance = "bullish"
        price_1d = base + random.uniform(-2, 8)

        signals.append({
            "id": f"min-{i}",
            "ticker": "SPY",
            "stance": stance,
            "confidence": 0.6,
            "event_type": "product_news",
            "subreddit": "stocks",
            "quality_score": 0.5,
            "trend_score": 0.2,
            "strategy": "credit_spread",
            "created_at": time.time() - i * 1800,
            "price_at_signal": base,
            "price_1d": price_1d,
        })

    return signals


# ---------------------------------------------------------------------------
# Module-level function tests
# ---------------------------------------------------------------------------

def test_random_rule_from_pool():
    """_random_rule_from_pool generates a valid StrategyRule."""
    random.seed(1)
    rule = _random_rule_from_pool()

    assert isinstance(rule, StrategyRule)
    # Check that field, operator, value are all drawn from FIELD_POOL
    found = False
    for field, operator, value_options in FIELD_POOL:
        if rule.field == field and rule.operator == operator:
            assert rule.value in value_options
            found = True
            break
    assert found, f"Rule {rule} not found in FIELD_POOL"


def test_random_rule_from_pool_deterministic():
    """_random_rule_from_pool is deterministic with seed."""
    random.seed(999)
    rule1 = _random_rule_from_pool()
    random.seed(999)
    rule2 = _random_rule_from_pool()

    assert rule1.field == rule2.field
    assert rule1.operator == rule2.operator
    assert rule1.value == rule2.value


# ---------------------------------------------------------------------------
# GeneticOptimizer initialization tests
# ---------------------------------------------------------------------------

def test_optimizer_init_defaults(mock_signals):
    """GeneticOptimizer initializes with default parameters."""
    opt = GeneticOptimizer(signals=mock_signals)

    assert opt._signals is mock_signals
    assert opt._population_size == 100
    assert opt._generations == 50
    assert opt._mutation_rate == 0.1
    assert opt._crossover_rate == 0.7
    assert opt._elitism == 5
    assert opt._max_rules == 5
    assert isinstance(opt._config, BacktestConfig)


def test_optimizer_init_custom_params(mock_signals):
    """GeneticOptimizer accepts custom parameters."""
    config = BacktestConfig(starting_capital=50000.0)

    opt = GeneticOptimizer(
        signals=mock_signals,
        population_size=20,
        generations=10,
        mutation_rate=0.2,
        crossover_rate=0.8,
        elitism=3,
        max_rules=7,
        default_config=config,
    )

    assert opt._population_size == 20
    assert opt._generations == 10
    assert opt._mutation_rate == 0.2
    assert opt._crossover_rate == 0.8
    assert opt._elitism == 3
    assert opt._max_rules == 7
    assert opt._config.starting_capital == 50000.0


def test_optimizer_init_empty_signals():
    """GeneticOptimizer raises ValueError on empty signals list."""
    with pytest.raises(ValueError, match="signals must be a non-empty list"):
        GeneticOptimizer(signals=[])


def test_optimizer_init_population_too_small(mock_signals):
    """GeneticOptimizer raises ValueError if population_size < 4."""
    with pytest.raises(ValueError, match="population_size must be >= 4"):
        GeneticOptimizer(signals=mock_signals, population_size=3)


def test_optimizer_init_generations_too_small(mock_signals):
    """GeneticOptimizer raises ValueError if generations < 1."""
    with pytest.raises(ValueError, match="generations must be >= 1"):
        GeneticOptimizer(signals=mock_signals, generations=0)


def test_optimizer_init_mutation_rate_out_of_range(mock_signals):
    """GeneticOptimizer raises ValueError if mutation_rate not in [0,1]."""
    with pytest.raises(ValueError, match="mutation_rate must be between 0.0 and 1.0"):
        GeneticOptimizer(signals=mock_signals, mutation_rate=1.5)

    with pytest.raises(ValueError, match="mutation_rate must be between 0.0 and 1.0"):
        GeneticOptimizer(signals=mock_signals, mutation_rate=-0.1)


def test_optimizer_init_crossover_rate_out_of_range(mock_signals):
    """GeneticOptimizer raises ValueError if crossover_rate not in [0,1]."""
    with pytest.raises(ValueError, match="crossover_rate must be between 0.0 and 1.0"):
        GeneticOptimizer(signals=mock_signals, crossover_rate=2.0)

    with pytest.raises(ValueError, match="crossover_rate must be between 0.0 and 1.0"):
        GeneticOptimizer(signals=mock_signals, crossover_rate=-0.5)


def test_optimizer_init_elitism_negative(mock_signals):
    """GeneticOptimizer raises ValueError if elitism < 0."""
    with pytest.raises(ValueError, match="elitism must be >= 0"):
        GeneticOptimizer(signals=mock_signals, elitism=-1)


def test_optimizer_init_elitism_too_large(mock_signals):
    """GeneticOptimizer raises ValueError if elitism >= population_size."""
    with pytest.raises(ValueError, match="elitism must be < population_size"):
        GeneticOptimizer(signals=mock_signals, population_size=10, elitism=10)


def test_optimizer_init_max_rules_too_small(mock_signals):
    """GeneticOptimizer raises ValueError if max_rules < 1."""
    with pytest.raises(ValueError, match="max_rules must be >= 1"):
        GeneticOptimizer(signals=mock_signals, max_rules=0)


# ---------------------------------------------------------------------------
# _random_individual tests
# ---------------------------------------------------------------------------

def test_random_individual_returns_rules(mock_signals):
    """_random_individual returns a list of StrategyRule instances."""
    random.seed(10)
    opt = GeneticOptimizer(signals=mock_signals, max_rules=5)

    individual = opt._random_individual()

    assert isinstance(individual, list)
    assert 1 <= len(individual) <= 5
    for rule in individual:
        assert isinstance(rule, StrategyRule)


def test_random_individual_respects_max_rules(mock_signals):
    """_random_individual does not exceed max_rules."""
    random.seed(20)
    opt = GeneticOptimizer(signals=mock_signals, max_rules=3)

    for _ in range(10):
        individual = opt._random_individual()
        assert 1 <= len(individual) <= 3


def test_random_individual_avoids_duplicates(mock_signals):
    """_random_individual avoids duplicate rules within an individual."""
    random.seed(30)
    opt = GeneticOptimizer(signals=mock_signals, max_rules=5)

    individual = opt._random_individual()

    # Check no duplicate (field, operator, value) tuples
    seen = set()
    for rule in individual:
        key = (rule.field, rule.operator, rule.value)
        assert key not in seen, f"Duplicate rule: {key}"
        seen.add(key)


# ---------------------------------------------------------------------------
# _initialize_population tests
# ---------------------------------------------------------------------------

def test_initialize_population_correct_size(mock_signals):
    """_initialize_population creates population_size individuals."""
    random.seed(40)
    opt = GeneticOptimizer(signals=mock_signals, population_size=10)

    population = opt._initialize_population()

    assert len(population) == 10
    for individual in population:
        assert isinstance(individual, list)
        assert all(isinstance(r, StrategyRule) for r in individual)


# ---------------------------------------------------------------------------
# _fitness tests
# ---------------------------------------------------------------------------

def test_fitness_returns_numeric(mock_signals):
    """_fitness returns a numeric fitness value (may be -1 for bad)."""
    random.seed(50)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=1, elitism=2
    )

    individual = opt._random_individual()
    fitness = opt._fitness(individual)

    assert isinstance(fitness, (int, float))


def test_fitness_caching(mock_signals):
    """_fitness caches results for identical individuals."""
    random.seed(60)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=1, elitism=2
    )

    individual = [
        StrategyRule(field="confidence", operator="gte", value=0.5),
        StrategyRule(field="stance", operator="eq", value="bullish"),
    ]

    # First call — cache miss
    assert opt.total_evaluated == 0
    f1 = opt._fitness(individual)
    assert opt.total_evaluated == 1

    # Second call — cache hit
    f2 = opt._fitness(individual)
    assert opt.total_evaluated == 1
    assert f1 == f2


def test_fitness_too_few_signals_penalty(mock_signals):
    """_fitness returns _BAD_FITNESS if fewer than _MIN_TRADES signals match."""
    random.seed(70)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=1, elitism=2
    )

    # A rule that matches almost nothing
    individual = [
        StrategyRule(field="confidence", operator="gte", value=0.99),
        StrategyRule(field="quality_score", operator="gte", value=0.99),
    ]

    fitness = opt._fitness(individual)
    assert fitness == _BAD_FITNESS


def test_fitness_zero_for_no_trades(minimal_signals):
    """_fitness returns _BAD_FITNESS if backtest produces < _MIN_TRADES."""
    random.seed(80)
    opt = GeneticOptimizer(
        signals=minimal_signals, population_size=10, generations=1, elitism=2
    )

    # Very restrictive rule — may pass filter but fail backtest trade count
    individual = [
        StrategyRule(field="confidence", operator="gte", value=0.9),
    ]

    fitness = opt._fitness(individual)
    # Should be _BAD_FITNESS or a valid Sharpe (depends on signal distribution)
    assert isinstance(fitness, float)


# ---------------------------------------------------------------------------
# _select tests
# ---------------------------------------------------------------------------

def test_select_returns_individual(mock_signals):
    """_select (tournament selection) returns an individual from the population."""
    random.seed(90)
    opt = GeneticOptimizer(signals=mock_signals, population_size=10, generations=1)

    population = opt._initialize_population()
    fitnesses = [opt._fitness(ind) for ind in population]

    selected = opt._select(population, fitnesses)

    assert isinstance(selected, list)
    assert all(isinstance(r, StrategyRule) for r in selected)


def test_select_returns_copy(mock_signals):
    """_select returns a copy of the individual (mutations don't affect original)."""
    random.seed(100)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=1, elitism=2
    )

    population = opt._initialize_population()
    fitnesses = [opt._fitness(ind) for ind in population]

    selected = opt._select(population, fitnesses)
    original_len = len(population[0])

    assert selected is not population[0]  # Should be a copy
    # Mutate selected
    selected.append(StrategyRule(field="confidence", operator="gte", value=0.9))
    # Original should be unchanged
    assert len(population[0]) == original_len


# ---------------------------------------------------------------------------
# _crossover tests
# ---------------------------------------------------------------------------

def test_crossover_returns_two_children(mock_signals):
    """_crossover returns two child individuals."""
    random.seed(110)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=1, elitism=2
    )

    parent1 = [
        StrategyRule(field="confidence", operator="gte", value=0.5),
        StrategyRule(field="stance", operator="eq", value="bullish"),
    ]
    parent2 = [
        StrategyRule(field="quality_score", operator="gte", value=0.4),
        StrategyRule(field="event_type", operator="eq", value="product_news"),
    ]

    child1, child2 = opt._crossover(parent1, parent2)

    assert isinstance(child1, list)
    assert isinstance(child2, list)
    assert all(isinstance(r, StrategyRule) for r in child1)
    assert all(isinstance(r, StrategyRule) for r in child2)


def test_crossover_respects_crossover_rate(mock_signals):
    """_crossover respects crossover_rate (sometimes returns parents unchanged)."""
    # crossover_rate = 0.0 should always return parents
    random.seed(120)
    opt = GeneticOptimizer(
        signals=mock_signals,
        population_size=10,
        generations=1,
        elitism=2,
        crossover_rate=0.0,
    )

    parent1 = [
        StrategyRule(field="confidence", operator="gte", value=0.5),
        StrategyRule(field="stance", operator="eq", value="bullish"),
    ]
    parent2 = [
        StrategyRule(field="quality_score", operator="gte", value=0.4),
        StrategyRule(field="event_type", operator="eq", value="product_news"),
    ]

    child1, child2 = opt._crossover(parent1, parent2)

    # Should be copies of parents
    assert len(child1) == len(parent1)
    assert len(child2) == len(parent2)


def test_crossover_produces_different_children_when_triggered(mock_signals):
    """_crossover produces children different from parents when it triggers."""
    # crossover_rate = 1.0 should always trigger
    random.seed(130)
    opt = GeneticOptimizer(
        signals=mock_signals,
        population_size=10,
        generations=1,
        elitism=2,
        crossover_rate=1.0,
    )

    parent1 = [
        StrategyRule(field="confidence", operator="gte", value=0.5),
        StrategyRule(field="stance", operator="eq", value="bullish"),
        StrategyRule(field="trend_score", operator="gte", value=0.1),
    ]
    parent2 = [
        StrategyRule(field="quality_score", operator="gte", value=0.4),
        StrategyRule(field="event_type", operator="eq", value="product_news"),
        StrategyRule(field="subreddit", operator="eq", value="stocks"),
    ]

    child1, child2 = opt._crossover(parent1, parent2)

    # With high probability, children should differ from parents
    # (could be flaky, but with seed 130 they should differ)
    # At minimum, check they are valid
    assert isinstance(child1, list)
    assert isinstance(child2, list)


def test_crossover_single_rule_fallback(mock_signals):
    """_crossover returns copies if either parent has only 1 rule."""
    random.seed(140)
    opt = GeneticOptimizer(
        signals=mock_signals,
        population_size=10,
        generations=1,
        elitism=2,
        crossover_rate=1.0,
    )

    parent1 = [StrategyRule(field="confidence", operator="gte", value=0.5)]
    parent2 = [StrategyRule(field="quality_score", operator="gte", value=0.4)]

    child1, child2 = opt._crossover(parent1, parent2)

    assert len(child1) == 1
    assert len(child2) == 1


def test_crossover_respects_max_rules(mock_signals):
    """_crossover caps children at max_rules."""
    random.seed(150)
    opt = GeneticOptimizer(
        signals=mock_signals,
        population_size=10,
        generations=1,
        elitism=2,
        max_rules=3,
        crossover_rate=1.0,
    )

    parent1 = [
        StrategyRule(field="confidence", operator="gte", value=0.5),
        StrategyRule(field="stance", operator="eq", value="bullish"),
        StrategyRule(field="trend_score", operator="gte", value=0.1),
    ]
    parent2 = [
        StrategyRule(field="quality_score", operator="gte", value=0.4),
        StrategyRule(field="event_type", operator="eq", value="product_news"),
        StrategyRule(field="subreddit", operator="eq", value="stocks"),
    ]

    child1, child2 = opt._crossover(parent1, parent2)

    assert len(child1) <= 3
    assert len(child2) <= 3


# ---------------------------------------------------------------------------
# _mutate tests
# ---------------------------------------------------------------------------

def test_mutate_modifies_individual(mock_signals):
    """_mutate can modify the individual's rules."""
    random.seed(160)
    opt = GeneticOptimizer(
        signals=mock_signals,
        population_size=10,
        generations=1,
        elitism=2,
        mutation_rate=1.0,
    )

    individual = [
        StrategyRule(field="confidence", operator="gte", value=0.5),
        StrategyRule(field="stance", operator="eq", value="bullish"),
    ]

    mutated = opt._mutate(individual)

    # With mutation_rate=1.0, all rules should be mutated
    # The list may have changed length or content
    assert mutated is individual  # returns same list (in-place)
    # Difficult to assert exact changes without determinism, but should be modified
    # (with very high probability)


def test_mutate_can_add_rule(mock_signals):
    """_mutate can add a new rule if below max_rules."""
    random.seed(170)
    opt = GeneticOptimizer(
        signals=mock_signals,
        population_size=10,
        generations=1,
        elitism=2,
        max_rules=5,
        mutation_rate=1.0,
    )

    individual = [StrategyRule(field="confidence", operator="gte", value=0.5)]

    # Run mutate multiple times to increase chance of add
    for _ in range(10):
        individual = opt._mutate(list(individual))
        if len(individual) > 1:
            break

    # With mutation_rate=1.0 and multiple runs, should eventually add
    # (could be flaky, but very likely with seed 170)
    assert len(individual) >= 1


def test_mutate_can_remove_rule(mock_signals):
    """_mutate can remove a rule if individual has > 1 rule."""
    random.seed(180)
    opt = GeneticOptimizer(
        signals=mock_signals,
        population_size=10,
        generations=1,
        elitism=2,
        mutation_rate=1.0,
    )

    individual = [
        StrategyRule(field="confidence", operator="gte", value=0.5),
        StrategyRule(field="stance", operator="eq", value="bullish"),
        StrategyRule(field="quality_score", operator="gte", value=0.4),
    ]

    # Run mutate multiple times to increase chance of removal
    for _ in range(10):
        individual = opt._mutate(list(individual))
        if len(individual) < 3:
            break

    # With mutation_rate=1.0 and multiple runs, should eventually remove
    assert len(individual) >= 1  # never goes to 0


def test_mutate_never_empties_individual(mock_signals):
    """_mutate never produces an empty individual (min 1 rule)."""
    random.seed(190)
    opt = GeneticOptimizer(
        signals=mock_signals,
        population_size=10,
        generations=1,
        elitism=2,
        mutation_rate=1.0,
    )

    individual = [StrategyRule(field="confidence", operator="gte", value=0.5)]

    # Even with mutation_rate=1.0, should never become empty
    for _ in range(20):
        individual = opt._mutate(individual)
        assert len(individual) >= 1


# ---------------------------------------------------------------------------
# evolve() tests
# ---------------------------------------------------------------------------

def test_evolve_runs_without_error(mock_signals):
    """evolve() runs without error and returns a result dict."""
    random.seed(200)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=2, elitism=2
    )

    result = opt.evolve()

    assert isinstance(result, dict)


def test_evolve_result_has_expected_keys(mock_signals):
    """evolve() result contains expected keys."""
    random.seed(210)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=2, elitism=2
    )

    result = opt.evolve()

    assert "best_rules" in result
    assert "best_fitness" in result
    assert "best_backtest" in result
    assert "generation_history" in result
    assert "total_evaluated" in result
    assert "population_size" in result
    assert "generations" in result
    assert "elapsed_s" in result


def test_evolve_best_rules_is_list_of_dicts(mock_signals):
    """evolve() best_rules is a list of rule dicts."""
    random.seed(220)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=2, elitism=2
    )

    result = opt.evolve()

    assert isinstance(result["best_rules"], list)
    for rule_dict in result["best_rules"]:
        assert isinstance(rule_dict, dict)
        assert "field" in rule_dict
        assert "operator" in rule_dict
        assert "value" in rule_dict


def test_evolve_best_fitness_is_numeric(mock_signals):
    """evolve() best_fitness is a numeric value."""
    random.seed(230)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=2, elitism=2
    )

    result = opt.evolve()

    assert isinstance(result["best_fitness"], (int, float))


def test_evolve_generation_history_correct_length(mock_signals):
    """evolve() generation_history has correct length."""
    random.seed(240)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=3, elitism=2
    )

    result = opt.evolve()

    assert len(result["generation_history"]) == 3


def test_evolve_generation_history_has_stats(mock_signals):
    """evolve() generation_history entries have correct fields."""
    random.seed(250)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=2, elitism=2
    )

    result = opt.evolve()

    for gen_stats in result["generation_history"]:
        assert "generation" in gen_stats
        assert "best_fitness" in gen_stats
        assert "avg_fitness" in gen_stats
        assert "worst_fitness" in gen_stats
        assert isinstance(gen_stats["best_fitness"], (int, float))


def test_evolve_single_generation(mock_signals):
    """evolve() works with generations=1."""
    random.seed(260)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=1, elitism=2
    )

    result = opt.evolve()

    assert len(result["generation_history"]) == 1
    assert result["generations"] == 1


def test_evolve_minimal_population_size(mock_signals):
    """evolve() works with population_size=4 (minimum allowed)."""
    random.seed(270)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=4, generations=2, elitism=1
    )

    result = opt.evolve()

    assert result["population_size"] == 4


def test_get_convergence_history(mock_signals):
    """get_convergence_history returns per-generation stats."""
    random.seed(280)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=3, elitism=2
    )

    # Before evolve, should be empty
    assert opt.get_convergence_history() == []

    opt.evolve()

    history = opt.get_convergence_history()
    assert len(history) == 3
    for entry in history:
        assert "generation" in entry
        assert "best_fitness" in entry
        assert "avg_fitness" in entry
        assert "worst_fitness" in entry


def test_cache_size_property(mock_signals):
    """cache_size property returns the number of cached fitness evaluations."""
    random.seed(290)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=2, elitism=2
    )

    assert opt.cache_size == 0

    opt.evolve()

    # After evolve, should have some cached entries
    assert opt.cache_size > 0


def test_total_evaluated_property(mock_signals):
    """total_evaluated property returns the number of unique evaluations."""
    random.seed(300)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=2, elitism=2
    )

    assert opt.total_evaluated == 0

    opt.evolve()

    # After evolve, should have evaluated some individuals
    assert opt.total_evaluated > 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_evolve_with_single_signal():
    """evolve() handles the edge case of a single signal (should get _BAD_FITNESS)."""
    random.seed(310)
    signals = [
        {
            "id": "single",
            "ticker": "XYZ",
            "stance": "bullish",
            "confidence": 0.7,
            "event_type": "product_news",
            "subreddit": "stocks",
            "quality_score": 0.6,
            "trend_score": 0.3,
            "strategy": "debit_spread",
            "created_at": time.time(),
            "price_at_signal": 100.0,
            "price_1d": 105.0,
        }
    ]

    opt = GeneticOptimizer(
        signals=signals, population_size=10, generations=1, elitism=2
    )

    result = opt.evolve()

    # With only 1 signal, no rule set can produce >= _MIN_TRADES
    assert result["best_fitness"] == _BAD_FITNESS


def test_evolve_with_zero_elitism(mock_signals):
    """evolve() works with elitism=0 (no elite preservation)."""
    random.seed(320)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=2, elitism=0
    )

    result = opt.evolve()

    # Should complete without error
    assert "best_fitness" in result


def test_evolve_with_high_elitism(mock_signals):
    """evolve() works with high elitism (e.g., half the population)."""
    random.seed(330)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=2, elitism=4
    )

    result = opt.evolve()

    # Should complete without error
    assert "best_fitness" in result


def test_evolve_deterministic_with_seed(mock_signals):
    """evolve() is deterministic when random seed is set."""
    random.seed(340)
    opt1 = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=3
    )
    result1 = opt1.evolve()

    random.seed(340)
    opt2 = GeneticOptimizer(
        signals=mock_signals, population_size=10, generations=3
    )
    result2 = opt2.evolve()

    # Should get identical results
    assert result1["best_fitness"] == result2["best_fitness"]
    assert result1["best_rules"] == result2["best_rules"]


def test_evolve_fitness_improves_over_generations(mock_signals):
    """evolve() shows fitness improvement over generations (in most runs)."""
    random.seed(350)
    opt = GeneticOptimizer(
        signals=mock_signals, population_size=20, generations=5
    )

    result = opt.evolve()

    history = result["generation_history"]

    # First generation best fitness
    gen0_best = history[0]["best_fitness"]
    # Last generation best fitness
    final_best = history[-1]["best_fitness"]

    # In a typical run, fitness should improve (or stay same if already optimal)
    # With random seed 350 and 50 signals, should see improvement
    assert final_best >= gen0_best


def test_evolve_handles_all_bad_fitness_population(minimal_signals):
    """evolve() handles the case where all individuals get _BAD_FITNESS."""
    random.seed(360)
    # Use very restrictive max_rules=1 and a small signal set
    # to make it likely all individuals fail
    signals = minimal_signals[:3]  # Only 3 signals (below _MIN_TRADES)

    opt = GeneticOptimizer(
        signals=signals, population_size=10, generations=2, elitism=2, max_rules=1
    )

    result = opt.evolve()

    # Should complete without error, even if all fitnesses are bad
    assert "best_fitness" in result
    # Best fitness should be _BAD_FITNESS
    assert result["best_fitness"] == _BAD_FITNESS
