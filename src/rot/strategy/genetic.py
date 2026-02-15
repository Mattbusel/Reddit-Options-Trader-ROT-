"""Genetic algorithm optimizer for strategy rule sets.

Evolves populations of ``StrategyRule`` lists through selection, crossover,
and mutation.  Fitness is measured by running each individual's rule set
through the :class:`~rot.strategy.rules.RuleEngine` to filter signals, then
backtesting the filtered signals via :class:`~rot.backtest.engine.BacktestEngine`
and using the resulting Sharpe ratio as the fitness score.

Typical usage::

    from rot.strategy.genetic import GeneticOptimizer

    optimizer = GeneticOptimizer(signals=my_signals, generations=30)
    result = optimizer.evolve()
    print(result["best_rules"])       # list of StrategyRule dicts
    print(result["best_fitness"])     # best Sharpe ratio found
    print(result["best_backtest"])    # BacktestResult.to_dict()

The optimizer is fully deterministic when a random seed is provided via
``random.seed()`` before calling :meth:`evolve`.
"""

from __future__ import annotations

import copy
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

from rot.backtest.config import BacktestConfig
from rot.backtest.engine import BacktestEngine
from rot.backtest.result import BacktestResult
from rot.strategy.rules import RuleEngine
from rot.strategy.types import StrategyRule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gene pool — the search space of possible rules
# ---------------------------------------------------------------------------

# Each entry is (field_name, operator, list_of_possible_values).
# During individual creation / mutation, one value is sampled uniformly
# from the value list to produce a concrete StrategyRule.

FIELD_POOL: list[tuple[str, str, list[Any]]] = [
    # Confidence thresholds
    ("confidence", "gte", [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
    ("confidence", "lte", [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
    # Stance filters
    ("stance", "eq", ["bullish", "bearish"]),
    # Event type filters
    (
        "event_type",
        "eq",
        [
            "earnings_rumor",
            "product_news",
            "regulatory",
            "squeeze_chatter",
            "macro",
            "other",
        ],
    ),
    # Quality score thresholds
    ("quality_score", "gte", [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]),
    # Trend score thresholds
    ("trend_score", "gte", [0.05, 0.1, 0.2, 0.3, 0.5]),
    # Subreddit filters
    (
        "subreddit",
        "eq",
        ["wallstreetbets", "stocks", "options", "thetagang", "investing"],
    ),
]

# Minimum number of trades required for a valid fitness evaluation.
# Strategies that produce fewer trades are penalised.
_MIN_TRADES = 5

# Fitness penalty for strategies with too few trades or errors.
_BAD_FITNESS = -1.0

# Default tournament size for selection.
_TOURNAMENT_SIZE = 3


# ---------------------------------------------------------------------------
# Helper: sample a random rule from the gene pool
# ---------------------------------------------------------------------------

def _random_rule_from_pool() -> StrategyRule:
    """Sample a single random rule from :data:`FIELD_POOL`.

    Picks a random gene spec (field, operator, value_options) and then
    picks a random value from the value_options list.

    Returns:
        A new ``StrategyRule`` instance.
    """
    field, operator, value_options = random.choice(FIELD_POOL)
    value = random.choice(value_options)
    return StrategyRule(field=field, operator=operator, value=value)


# ---------------------------------------------------------------------------
# Per-generation stats
# ---------------------------------------------------------------------------

@dataclass
class _GenerationStats:
    """Internal bookkeeping for a single generation."""

    generation: int
    best_fitness: float
    avg_fitness: float
    worst_fitness: float
    best_individual: list[StrategyRule]


# ---------------------------------------------------------------------------
# GeneticOptimizer
# ---------------------------------------------------------------------------

class GeneticOptimizer:
    """Evolves strategy rule sets using a genetic algorithm.

    The workflow follows the canonical GA loop:

    1. **Initialise** a population of random individuals (rule sets).
    2. **Evaluate** each individual's fitness (Sharpe ratio from backtest).
    3. **Select** parents via tournament selection.
    4. **Crossover** parent pairs to produce offspring.
    5. **Mutate** offspring with a per-rule probability.
    6. **Replace** the population, preserving elite individuals.
    7. Repeat from step 2 for ``generations`` iterations.

    Parameters
    ----------
    signals:
        List of signal dicts (rows from ``get_backtest_signals()``).
        These are the universe of signals that each individual's rule set
        will filter.
    population_size:
        Number of individuals per generation.
    generations:
        Number of evolution iterations.
    mutation_rate:
        Probability (0-1) of mutating each rule in an individual.
    crossover_rate:
        Probability (0-1) of performing crossover on a parent pair.
    elitism:
        Number of top individuals carried unchanged to the next generation.
    max_rules:
        Maximum number of rules per individual.
    default_config:
        ``BacktestConfig`` to use when running backtests.  If ``None``,
        a sensible default is used.
    """

    def __init__(
        self,
        signals: list[dict],
        population_size: int = 100,
        generations: int = 50,
        mutation_rate: float = 0.1,
        crossover_rate: float = 0.7,
        elitism: int = 5,
        max_rules: int = 5,
        default_config: BacktestConfig | None = None,
    ) -> None:
        if not signals:
            raise ValueError("signals must be a non-empty list")
        if population_size < 4:
            raise ValueError("population_size must be >= 4")
        if generations < 1:
            raise ValueError("generations must be >= 1")
        if not (0.0 <= mutation_rate <= 1.0):
            raise ValueError("mutation_rate must be between 0.0 and 1.0")
        if not (0.0 <= crossover_rate <= 1.0):
            raise ValueError("crossover_rate must be between 0.0 and 1.0")
        if elitism < 0:
            raise ValueError("elitism must be >= 0")
        if elitism >= population_size:
            raise ValueError("elitism must be < population_size")
        if max_rules < 1:
            raise ValueError("max_rules must be >= 1")

        self._signals = signals
        self._population_size = population_size
        self._generations = generations
        self._mutation_rate = mutation_rate
        self._crossover_rate = crossover_rate
        self._elitism = elitism
        self._max_rules = max_rules
        self._config = default_config or BacktestConfig()

        # Engines (stateless, created once)
        self._rule_engine = RuleEngine()
        self._backtest_engine = BacktestEngine()

        # Convergence / diagnostic state (populated by evolve())
        self._generation_history: list[_GenerationStats] = []
        self._total_evaluated: int = 0

        # Cache: tuple(sorted rule dicts) -> fitness
        # Avoids re-evaluating identical individuals across generations.
        self._fitness_cache: dict[tuple[tuple[str, str, Any], ...], float] = {}

    # ------------------------------------------------------------------
    # Individual creation
    # ------------------------------------------------------------------

    def _random_individual(self) -> list[StrategyRule]:
        """Generate a random individual (a list of 1 to ``max_rules`` rules).

        Duplicate rules (same field + operator + value) within an
        individual are avoided where possible to reduce wasted search
        space.

        Returns:
            A list of ``StrategyRule`` instances.
        """
        num_rules = random.randint(1, self._max_rules)
        individual: list[StrategyRule] = []
        seen: set[tuple[str, str, Any]] = set()

        attempts = 0
        max_attempts = num_rules * 10  # avoid infinite loop on small pools

        while len(individual) < num_rules and attempts < max_attempts:
            rule = _random_rule_from_pool()
            key = (rule.field, rule.operator, _hashable_value(rule.value))
            if key not in seen:
                individual.append(rule)
                seen.add(key)
            attempts += 1

        return individual

    # ------------------------------------------------------------------
    # Population initialisation
    # ------------------------------------------------------------------

    def _initialize_population(self) -> list[list[StrategyRule]]:
        """Create the initial population of random individuals.

        Returns:
            A list of ``population_size`` individuals, where each
            individual is a list of ``StrategyRule``.
        """
        population: list[list[StrategyRule]] = []
        for _ in range(self._population_size):
            population.append(self._random_individual())
        logger.debug(
            "Initialized population of %d individuals", self._population_size
        )
        return population

    # ------------------------------------------------------------------
    # Fitness evaluation
    # ------------------------------------------------------------------

    def _individual_key(
        self, individual: list[StrategyRule]
    ) -> tuple[tuple[str, str, Any], ...]:
        """Create a hashable cache key for an individual.

        Rules are sorted to ensure that different orderings of the same
        rule set produce the same key.
        """
        items = sorted(
            (r.field, r.operator, _hashable_value(r.value)) for r in individual
        )
        return tuple(items)

    def _fitness(self, individual: list[StrategyRule]) -> float:
        """Evaluate the fitness of a single individual.

        Workflow:
          1. Filter ``self._signals`` using :meth:`RuleEngine.batch_evaluate`.
          2. Run :meth:`BacktestEngine.run` on the filtered signals.
          3. Return the Sharpe ratio as fitness.

        Edge cases:
          - If fewer than :data:`_MIN_TRADES` pass the filter, return
            :data:`_BAD_FITNESS`.
          - If the backtest produces a ``None`` Sharpe ratio (not enough
            data points), return ``0.0``.
          - If the Sharpe ratio is negative, return the raw negative value
            (not clamped to -1) so that the GA can still distinguish
            "slightly bad" from "very bad".

        Returns:
            Fitness score (Sharpe ratio, or penalty value).
        """
        # Check cache first.
        key = self._individual_key(individual)
        if key in self._fitness_cache:
            return self._fitness_cache[key]

        self._total_evaluated += 1

        # 1. Filter signals through the rule set.
        filtered = self._rule_engine.batch_evaluate(self._signals, individual)

        # Too few matching signals → strategy is too restrictive.
        if len(filtered) < _MIN_TRADES:
            self._fitness_cache[key] = _BAD_FITNESS
            return _BAD_FITNESS

        # 2. Run backtest on filtered signals.
        try:
            result = self._backtest_engine.run(filtered, self._config)
        except Exception:
            logger.debug(
                "Backtest raised an exception for individual %s",
                _summarise_individual(individual),
                exc_info=True,
            )
            self._fitness_cache[key] = _BAD_FITNESS
            return _BAD_FITNESS

        # 3. Extract Sharpe ratio.
        sharpe = result.sharpe_ratio
        if sharpe is None:
            fitness = 0.0
        else:
            fitness = float(sharpe)

        # Penalise strategies with very few actual trades executed
        # (backtest may filter further, e.g. no exit price).
        if result.total_trades < _MIN_TRADES:
            fitness = _BAD_FITNESS

        self._fitness_cache[key] = fitness
        return fitness

    def _fitness_with_result(
        self, individual: list[StrategyRule]
    ) -> tuple[float, BacktestResult | None]:
        """Evaluate fitness and also return the backtest result.

        Used for the final best individual to capture full diagnostics.
        """
        filtered = self._rule_engine.batch_evaluate(self._signals, individual)
        if len(filtered) < _MIN_TRADES:
            return _BAD_FITNESS, None

        try:
            result = self._backtest_engine.run(filtered, self._config)
        except Exception:
            logger.debug(
                "Backtest exception during fitness_with_result",
                exc_info=True,
            )
            return _BAD_FITNESS, None

        sharpe = result.sharpe_ratio
        if sharpe is None:
            fitness = 0.0
        else:
            fitness = float(sharpe)

        if result.total_trades < _MIN_TRADES:
            fitness = _BAD_FITNESS

        return fitness, result

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _select(
        self,
        population: list[list[StrategyRule]],
        fitnesses: list[float],
    ) -> list[StrategyRule]:
        """Select one individual via tournament selection.

        Randomly samples ``_TOURNAMENT_SIZE`` individuals from the
        population and returns the one with the highest fitness.

        Args:
            population: Current generation of individuals.
            fitnesses: Fitness scores aligned with *population*.

        Returns:
            A **copy** of the winning individual's rule list.
        """
        tournament_size = min(_TOURNAMENT_SIZE, len(population))
        indices = random.sample(range(len(population)), tournament_size)
        best_idx = max(indices, key=lambda i: fitnesses[i])
        # Return a copy so mutations don't affect the original.
        return list(population[best_idx])

    # ------------------------------------------------------------------
    # Crossover
    # ------------------------------------------------------------------

    def _crossover(
        self,
        parent1: list[StrategyRule],
        parent2: list[StrategyRule],
    ) -> tuple[list[StrategyRule], list[StrategyRule]]:
        """Single-point crossover on two parent rule lists.

        If the crossover rate check fails (random roll > crossover_rate),
        the parents are returned as-is (deep copies).

        For crossover to be meaningful both parents must have at least 2
        rules.  If either parent has only 1 rule, we fall back to
        returning copies.

        The crossover point is chosen randomly within the shorter parent.
        Child rule lists are capped at ``max_rules``.

        Args:
            parent1: First parent's rule list.
            parent2: Second parent's rule list.

        Returns:
            A tuple of two offspring rule lists.
        """
        # Roll for crossover probability.
        if random.random() > self._crossover_rate:
            return list(parent1), list(parent2)

        # Need at least 2 rules in each parent for a meaningful split.
        if len(parent1) < 2 or len(parent2) < 2:
            return list(parent1), list(parent2)

        # Crossover point: pick within the range of the shorter parent
        # so both halves are non-empty.
        min_len = min(len(parent1), len(parent2))
        point = random.randint(1, min_len - 1)

        child1 = parent1[:point] + parent2[point:]
        child2 = parent2[:point] + parent1[point:]

        # Enforce max_rules cap by trimming excess from the tail.
        child1 = child1[: self._max_rules]
        child2 = child2[: self._max_rules]

        return child1, child2

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def _mutate(self, individual: list[StrategyRule]) -> list[StrategyRule]:
        """Mutate an individual's rule list in-place (returns the list).

        For each rule position, with probability ``mutation_rate``:
          - **Replace** the rule with a random rule from the gene pool
            (60% chance).
          - **Add** a new random rule if the individual is below
            ``max_rules`` (20% chance).
          - **Remove** the rule if the individual has more than 1 rule
            (20% chance).

        Args:
            individual: The rule list to mutate.

        Returns:
            The (possibly modified) rule list.
        """
        # Iterate over a snapshot of indices because the list may change
        # in length during mutation.
        i = 0
        while i < len(individual):
            if random.random() < self._mutation_rate:
                action = random.random()

                if action < 0.6:
                    # Replace this rule with a new random one.
                    individual[i] = _random_rule_from_pool()
                    i += 1
                elif action < 0.8 and len(individual) < self._max_rules:
                    # Add a new rule at a random position.
                    individual.insert(
                        random.randint(0, len(individual)),
                        _random_rule_from_pool(),
                    )
                    # Skip ahead past the inserted rule to avoid
                    # mutating it again immediately.
                    i += 2
                elif len(individual) > 1:
                    # Remove this rule.
                    individual.pop(i)
                    # Don't increment i — the next rule slides into this
                    # position.
                else:
                    # Can't remove the only rule and can't add; replace
                    # instead.
                    individual[i] = _random_rule_from_pool()
                    i += 1
            else:
                i += 1

        return individual

    # ------------------------------------------------------------------
    # Main evolution loop
    # ------------------------------------------------------------------

    def evolve(self) -> dict:
        """Run the full genetic algorithm.

        Returns:
            A dict containing:

            - ``best_rules``: List of ``StrategyRule.to_dict()`` for the
              best individual found.
            - ``best_fitness``: Best Sharpe ratio achieved.
            - ``best_backtest``: ``BacktestResult.to_dict()`` for the
              best individual (or ``None``).
            - ``generation_history``: List of dicts with per-generation
              stats (``generation``, ``best_fitness``, ``avg_fitness``,
              ``worst_fitness``).
            - ``total_evaluated``: Total number of unique fitness
              evaluations performed (cache misses).
            - ``population_size``: Population size used.
            - ``generations``: Number of generations run.
            - ``elapsed_s``: Wall-clock seconds for the full run.
        """
        start_time = time.monotonic()

        self._generation_history = []
        self._total_evaluated = 0
        self._fitness_cache.clear()

        population = self._initialize_population()

        # Track overall best across all generations.
        overall_best_fitness = _BAD_FITNESS
        overall_best_individual: list[StrategyRule] = []

        for gen in range(self._generations):
            # --- Evaluate fitness for the whole population ---------------
            fitnesses = [self._fitness(ind) for ind in population]

            # --- Track per-generation statistics -------------------------
            valid_fitnesses = [f for f in fitnesses if f > _BAD_FITNESS]
            if valid_fitnesses:
                gen_best = max(valid_fitnesses)
                gen_avg = sum(valid_fitnesses) / len(valid_fitnesses)
                gen_worst = min(valid_fitnesses)
            else:
                gen_best = _BAD_FITNESS
                gen_avg = _BAD_FITNESS
                gen_worst = _BAD_FITNESS

            # Find the best individual this generation.
            best_idx = max(range(len(fitnesses)), key=lambda i: fitnesses[i])
            gen_best_individual = list(population[best_idx])

            stats = _GenerationStats(
                generation=gen,
                best_fitness=gen_best,
                avg_fitness=gen_avg,
                worst_fitness=gen_worst,
                best_individual=gen_best_individual,
            )
            self._generation_history.append(stats)

            if fitnesses[best_idx] > overall_best_fitness:
                overall_best_fitness = fitnesses[best_idx]
                overall_best_individual = list(population[best_idx])

            logger.debug(
                "Generation %d/%d: best=%.4f  avg=%.4f  worst=%.4f  "
                "cache_size=%d",
                gen + 1,
                self._generations,
                gen_best,
                gen_avg,
                gen_worst,
                len(self._fitness_cache),
            )

            # Early stopping: last generation — don't breed.
            if gen == self._generations - 1:
                break

            # --- Build next generation -----------------------------------
            next_population: list[list[StrategyRule]] = []

            # Elitism: carry the top N individuals unchanged.
            if self._elitism > 0:
                elite_indices = sorted(
                    range(len(fitnesses)),
                    key=lambda i: fitnesses[i],
                    reverse=True,
                )[: self._elitism]
                for ei in elite_indices:
                    next_population.append(list(population[ei]))

            # Fill the rest via selection + crossover + mutation.
            while len(next_population) < self._population_size:
                p1 = self._select(population, fitnesses)
                p2 = self._select(population, fitnesses)

                child1, child2 = self._crossover(p1, p2)

                child1 = self._mutate(child1)
                child2 = self._mutate(child2)

                next_population.append(child1)
                if len(next_population) < self._population_size:
                    next_population.append(child2)

            population = next_population

        # --- Evaluate the overall best with full backtest result ----------
        if overall_best_individual:
            best_fitness, best_result = self._fitness_with_result(
                overall_best_individual
            )
            # Use the cached fitness if re-evaluation changed nothing.
            if best_fitness > overall_best_fitness:
                overall_best_fitness = best_fitness
        else:
            best_result = None

        elapsed = time.monotonic() - start_time

        logger.info(
            "Genetic optimization complete: best_fitness=%.4f  "
            "generations=%d  evaluated=%d  elapsed=%.1fs",
            overall_best_fitness,
            self._generations,
            self._total_evaluated,
            elapsed,
        )

        return {
            "best_rules": [r.to_dict() for r in overall_best_individual],
            "best_fitness": round(overall_best_fitness, 6),
            "best_backtest": best_result.to_dict() if best_result else None,
            "generation_history": [
                {
                    "generation": gs.generation,
                    "best_fitness": round(gs.best_fitness, 6),
                    "avg_fitness": round(gs.avg_fitness, 6),
                    "worst_fitness": round(gs.worst_fitness, 6),
                }
                for gs in self._generation_history
            ],
            "total_evaluated": self._total_evaluated,
            "population_size": self._population_size,
            "generations": self._generations,
            "elapsed_s": round(elapsed, 3),
        }

    # ------------------------------------------------------------------
    # Convergence history (public accessor)
    # ------------------------------------------------------------------

    def get_convergence_history(self) -> list[dict]:
        """Return per-generation statistics from the last :meth:`evolve` run.

        Each dict contains:

        - ``generation``: Zero-based generation index.
        - ``best_fitness``: Best fitness in this generation.
        - ``avg_fitness``: Average fitness of *valid* individuals (those
          with fitness > -1).
        - ``worst_fitness``: Worst fitness among valid individuals.

        Returns:
            A list of dicts ordered by generation.  Empty if
            :meth:`evolve` has not been called yet.
        """
        return [
            {
                "generation": gs.generation,
                "best_fitness": round(gs.best_fitness, 6),
                "avg_fitness": round(gs.avg_fitness, 6),
                "worst_fitness": round(gs.worst_fitness, 6),
            }
            for gs in self._generation_history
        ]

    # ------------------------------------------------------------------
    # Diagnostic helpers
    # ------------------------------------------------------------------

    @property
    def cache_size(self) -> int:
        """Number of entries in the fitness cache."""
        return len(self._fitness_cache)

    @property
    def total_evaluated(self) -> int:
        """Total unique fitness evaluations (cache misses) so far."""
        return self._total_evaluated


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _hashable_value(value: Any) -> Any:
    """Convert a rule value to a hashable form for caching / dedup.

    Lists are converted to tuples.  Everything else is returned as-is
    (primitive types are already hashable).
    """
    if isinstance(value, list):
        return tuple(value)
    return value


def _summarise_individual(individual: list[StrategyRule]) -> str:
    """Return a compact human-readable summary of an individual's rules.

    Used for debug logging.
    """
    parts: list[str] = []
    for r in individual:
        parts.append(f"{r.field} {r.operator} {r.value!r}")
    return " AND ".join(parts) if parts else "(empty)"
