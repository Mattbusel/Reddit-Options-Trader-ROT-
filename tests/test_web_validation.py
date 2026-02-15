"""
Comprehensive tests for web validation models.

Modules tested:
- rot.web.validation

Coverage:
- CreateStrategyRequest (name length, description, rules, config)
- DiscoverStrategiesRequest (range validation for all fields)
- MLOptimizeRequest (days, max_signals, min_signals)
- GeneticEvolveRequest (population_size, generations, max_rules)
- PublishToMarketplaceRequest (strategy_id, price validation)
- BacktestCompareRequest (run_ids min/max length)
- ExportScheduleCreateRequest (format, frequency, filters)
- Pydantic validation errors (min/max violations)
- Default values
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from rot.web.validation import (
    BacktestCompareRequest,
    CreateStrategyRequest,
    DiscoverStrategiesRequest,
    ExportScheduleCreateRequest,
    GeneticEvolveRequest,
    MLOptimizeRequest,
    PublishToMarketplaceRequest,
)


class TestCreateStrategyRequest:
    def test_create_strategy_valid(self):
        """CreateStrategyRequest accepts valid inputs."""
        req = CreateStrategyRequest(
            name="My Strategy",
            description="A test strategy",
            rules=[{"field": "ticker", "op": "equals", "value": "AAPL"}],
            config={"max_trades": 10},
        )

        assert req.name == "My Strategy"
        assert req.description == "A test strategy"
        assert len(req.rules) == 1
        assert req.config["max_trades"] == 10

    def test_create_strategy_defaults(self):
        """CreateStrategyRequest has default values."""
        req = CreateStrategyRequest(name="Test")

        assert req.name == "Test"
        assert req.description == ""
        assert req.rules == []
        assert req.config == {}

    def test_create_strategy_name_too_short(self):
        """CreateStrategyRequest rejects empty name."""
        with pytest.raises(ValidationError):
            CreateStrategyRequest(name="")

    def test_create_strategy_name_too_long(self):
        """CreateStrategyRequest rejects name > 100 chars."""
        with pytest.raises(ValidationError):
            CreateStrategyRequest(name="A" * 101)

    def test_create_strategy_description_too_long(self):
        """CreateStrategyRequest rejects description > 500 chars."""
        with pytest.raises(ValidationError):
            CreateStrategyRequest(
                name="Test",
                description="X" * 501,
            )


class TestDiscoverStrategiesRequest:
    def test_discover_strategies_defaults(self):
        """DiscoverStrategiesRequest has sensible defaults."""
        req = DiscoverStrategiesRequest()

        assert req.days == 90
        assert req.max_signals == 1000
        assert req.max_rules == 3
        assert req.max_candidates == 500
        assert req.min_trades == 10
        assert req.min_win_rate == 0.5
        assert req.min_sharpe == 0.0
        assert req.search_mode == "random"
        assert req.walk_forward is False

    def test_discover_strategies_custom_values(self):
        """DiscoverStrategiesRequest accepts custom values."""
        req = DiscoverStrategiesRequest(
            days=180,
            max_signals=2000,
            max_rules=5,
            min_win_rate=0.6,
        )

        assert req.days == 180
        assert req.max_signals == 2000
        assert req.max_rules == 5
        assert req.min_win_rate == 0.6

    def test_discover_strategies_days_range(self):
        """DiscoverStrategiesRequest validates days range."""
        # Valid range
        req1 = DiscoverStrategiesRequest(days=1)
        assert req1.days == 1

        req2 = DiscoverStrategiesRequest(days=365)
        assert req2.days == 365

        # Invalid: too low
        with pytest.raises(ValidationError):
            DiscoverStrategiesRequest(days=0)

        # Invalid: too high
        with pytest.raises(ValidationError):
            DiscoverStrategiesRequest(days=366)

    def test_discover_strategies_max_signals_range(self):
        """DiscoverStrategiesRequest validates max_signals range."""
        req1 = DiscoverStrategiesRequest(max_signals=10)
        assert req1.max_signals == 10

        req2 = DiscoverStrategiesRequest(max_signals=10000)
        assert req2.max_signals == 10000

        with pytest.raises(ValidationError):
            DiscoverStrategiesRequest(max_signals=9)

        with pytest.raises(ValidationError):
            DiscoverStrategiesRequest(max_signals=10001)

    def test_discover_strategies_win_rate_range(self):
        """DiscoverStrategiesRequest validates win_rate 0-1."""
        req1 = DiscoverStrategiesRequest(min_win_rate=0.0)
        assert req1.min_win_rate == 0.0

        req2 = DiscoverStrategiesRequest(min_win_rate=1.0)
        assert req2.min_win_rate == 1.0

        with pytest.raises(ValidationError):
            DiscoverStrategiesRequest(min_win_rate=-0.1)

        with pytest.raises(ValidationError):
            DiscoverStrategiesRequest(min_win_rate=1.1)


class TestMLOptimizeRequest:
    def test_ml_optimize_defaults(self):
        """MLOptimizeRequest has defaults."""
        req = MLOptimizeRequest()

        assert req.days == 90
        assert req.max_signals == 1000
        assert req.min_signals == 200

    def test_ml_optimize_custom_values(self):
        """MLOptimizeRequest accepts custom values."""
        req = MLOptimizeRequest(
            days=180,
            max_signals=2000,
            min_signals=500,
        )

        assert req.days == 180
        assert req.max_signals == 2000
        assert req.min_signals == 500

    def test_ml_optimize_range_validation(self):
        """MLOptimizeRequest validates ranges."""
        # Valid
        req = MLOptimizeRequest(min_signals=10)
        assert req.min_signals == 10

        # Invalid: min_signals > 5000
        with pytest.raises(ValidationError):
            MLOptimizeRequest(min_signals=5001)


class TestGeneticEvolveRequest:
    def test_genetic_evolve_defaults(self):
        """GeneticEvolveRequest has defaults."""
        req = GeneticEvolveRequest()

        assert req.days == 90
        assert req.max_signals == 1000
        assert req.population_size == 50
        assert req.generations == 30
        assert req.max_rules == 5

    def test_genetic_evolve_custom_values(self):
        """GeneticEvolveRequest accepts custom values."""
        req = GeneticEvolveRequest(
            population_size=80,
            generations=40,
            max_rules=8,
        )

        assert req.population_size == 80
        assert req.generations == 40
        assert req.max_rules == 8

    def test_genetic_evolve_population_range(self):
        """GeneticEvolveRequest validates population_size 10-100."""
        req1 = GeneticEvolveRequest(population_size=10)
        assert req1.population_size == 10

        req2 = GeneticEvolveRequest(population_size=100)
        assert req2.population_size == 100

        with pytest.raises(ValidationError):
            GeneticEvolveRequest(population_size=9)

        with pytest.raises(ValidationError):
            GeneticEvolveRequest(population_size=101)

    def test_genetic_evolve_generations_range(self):
        """GeneticEvolveRequest validates generations 1-50."""
        req1 = GeneticEvolveRequest(generations=1)
        assert req1.generations == 1

        req2 = GeneticEvolveRequest(generations=50)
        assert req2.generations == 50

        with pytest.raises(ValidationError):
            GeneticEvolveRequest(generations=0)

        with pytest.raises(ValidationError):
            GeneticEvolveRequest(generations=51)


class TestPublishToMarketplaceRequest:
    def test_publish_to_marketplace_valid(self):
        """PublishToMarketplaceRequest accepts valid inputs."""
        req = PublishToMarketplaceRequest(
            strategy_id="strat123",
            name="Premium Strategy",
            description="A profitable strategy",
            price=99.99,
            tags=["momentum", "tech"],
        )

        assert req.strategy_id == "strat123"
        assert req.name == "Premium Strategy"
        assert req.price == 99.99
        assert len(req.tags) == 2

    def test_publish_to_marketplace_defaults(self):
        """PublishToMarketplaceRequest has defaults."""
        req = PublishToMarketplaceRequest(strategy_id="strat123")

        assert req.strategy_id == "strat123"
        assert req.name == ""
        assert req.description == ""
        assert req.price == 0.0
        assert req.tags == []

    def test_publish_to_marketplace_strategy_id_required(self):
        """PublishToMarketplaceRequest requires strategy_id."""
        with pytest.raises(ValidationError):
            PublishToMarketplaceRequest()

    def test_publish_to_marketplace_price_non_negative(self):
        """PublishToMarketplaceRequest rejects negative price."""
        with pytest.raises(ValidationError):
            PublishToMarketplaceRequest(
                strategy_id="strat123",
                price=-1.0,
            )

    def test_publish_to_marketplace_name_max_length(self):
        """PublishToMarketplaceRequest validates name max length."""
        with pytest.raises(ValidationError):
            PublishToMarketplaceRequest(
                strategy_id="strat123",
                name="X" * 101,
            )

    def test_publish_to_marketplace_description_max_length(self):
        """PublishToMarketplaceRequest validates description max length."""
        with pytest.raises(ValidationError):
            PublishToMarketplaceRequest(
                strategy_id="strat123",
                description="X" * 1001,
            )


class TestBacktestCompareRequest:
    def test_backtest_compare_valid(self):
        """BacktestCompareRequest accepts 2-5 run_ids."""
        req = BacktestCompareRequest(run_ids=["run1", "run2"])
        assert len(req.run_ids) == 2

        req2 = BacktestCompareRequest(run_ids=["r1", "r2", "r3", "r4", "r5"])
        assert len(req2.run_ids) == 5

    def test_backtest_compare_min_length(self):
        """BacktestCompareRequest requires at least 2 run_ids."""
        with pytest.raises(ValidationError):
            BacktestCompareRequest(run_ids=["run1"])

        with pytest.raises(ValidationError):
            BacktestCompareRequest(run_ids=[])

    def test_backtest_compare_max_length(self):
        """BacktestCompareRequest allows max 5 run_ids."""
        with pytest.raises(ValidationError):
            BacktestCompareRequest(run_ids=["r1", "r2", "r3", "r4", "r5", "r6"])


class TestExportScheduleCreateRequest:
    def test_export_schedule_defaults(self):
        """ExportScheduleCreateRequest has defaults."""
        req = ExportScheduleCreateRequest()

        assert req.format == "csv"
        assert req.frequency == "daily"
        assert req.filters == {}

    def test_export_schedule_custom_values(self):
        """ExportScheduleCreateRequest accepts custom values."""
        req = ExportScheduleCreateRequest(
            format="json",
            frequency="weekly",
            filters={"ticker": "AAPL"},
        )

        assert req.format == "json"
        assert req.frequency == "weekly"
        assert req.filters["ticker"] == "AAPL"
