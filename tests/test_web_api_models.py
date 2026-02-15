"""
Comprehensive tests for web API response models.

Modules tested:
- rot.web.api_models

Coverage:
- APIResponse generic wrapper
- ErrorResponse standard format
- SignalResponse model
- TradeIdeaResponse model
- PaginatedResponse generic wrapper
- HealthResponse model
- AnalyticsResponse model
- TierLimitsResponse model
- BacktestRequest validation
- BacktestResponse model
- Field validation (confidence, win_rate ranges)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from rot.web.api_models import (
    AnalyticsResponse,
    APIResponse,
    BacktestRequest,
    BacktestResponse,
    ErrorResponse,
    HealthResponse,
    PaginatedResponse,
    SignalResponse,
    TierLimitsResponse,
    TradeIdeaResponse,
)


class TestAPIResponse:
    def test_api_response_success(self):
        """APIResponse with success=True and data."""
        response = APIResponse[dict](
            success=True,
            data={"test": "value"},
            error=None,
            request_id="req_123",
        )

        assert response.success is True
        assert response.data == {"test": "value"}
        assert response.error is None
        assert response.request_id == "req_123"

    def test_api_response_error(self):
        """APIResponse with success=False and error message."""
        response = APIResponse[None](
            success=False,
            data=None,
            error="Something went wrong",
            request_id="req_456",
        )

        assert response.success is False
        assert response.data is None
        assert response.error == "Something went wrong"
        assert response.request_id == "req_456"

    def test_api_response_defaults(self):
        """APIResponse has None defaults for optional fields."""
        response = APIResponse[str](success=True)

        assert response.success is True
        assert response.data is None
        assert response.error is None
        assert response.request_id is None

    def test_api_response_serialization(self):
        """APIResponse can be serialized to dict/JSON."""
        response = APIResponse[dict](
            success=True,
            data={"key": "value"},
            request_id="req_789",
        )

        data = response.model_dump()
        assert data["success"] is True
        assert data["data"] == {"key": "value"}
        assert data["request_id"] == "req_789"


class TestErrorResponse:
    def test_error_response_minimal(self):
        """ErrorResponse with required fields only."""
        response = ErrorResponse(error="Invalid input")

        assert response.success is False
        assert response.error == "Invalid input"
        assert response.error_code is None
        assert response.details is None
        assert response.request_id is None

    def test_error_response_full(self):
        """ErrorResponse with all fields populated."""
        response = ErrorResponse(
            error="Rate limit exceeded",
            error_code="RATE_LIMIT_EXCEEDED",
            details={"limit": 1000, "used": 1000},
            request_id="req_abc",
        )

        assert response.success is False
        assert response.error == "Rate limit exceeded"
        assert response.error_code == "RATE_LIMIT_EXCEEDED"
        assert response.details["limit"] == 1000
        assert response.request_id == "req_abc"


class TestSignalResponse:
    def test_signal_response_valid(self):
        """SignalResponse with valid data."""
        response = SignalResponse(
            id=12345,
            ticker="AAPL",
            stance="bullish",
            confidence=0.85,
            event_type="earnings_beat",
            reasoning="Strong earnings",
            created_at=1708041600,
            post_title="AAPL earnings beat!",
            subreddit="wallstreetbets",
        )

        assert response.id == 12345
        assert response.ticker == "AAPL"
        assert response.stance == "bullish"
        assert response.confidence == 0.85
        assert response.event_type == "earnings_beat"

    def test_signal_response_confidence_validation(self):
        """SignalResponse validates confidence range 0.0-1.0."""
        # Valid: 0.0
        response1 = SignalResponse(
            id=1,
            ticker="AAPL",
            stance="bullish",
            confidence=0.0,
            event_type="test",
            reasoning="test",
            created_at=123,
            post_title="test",
            subreddit="test",
        )
        assert response1.confidence == 0.0

        # Valid: 1.0
        response2 = SignalResponse(
            id=2,
            ticker="AAPL",
            stance="bullish",
            confidence=1.0,
            event_type="test",
            reasoning="test",
            created_at=123,
            post_title="test",
            subreddit="test",
        )
        assert response2.confidence == 1.0

        # Invalid: > 1.0
        with pytest.raises(ValidationError):
            SignalResponse(
                id=3,
                ticker="AAPL",
                stance="bullish",
                confidence=1.5,
                event_type="test",
                reasoning="test",
                created_at=123,
                post_title="test",
                subreddit="test",
            )

        # Invalid: < 0.0
        with pytest.raises(ValidationError):
            SignalResponse(
                id=4,
                ticker="AAPL",
                stance="bullish",
                confidence=-0.1,
                event_type="test",
                reasoning="test",
                created_at=123,
                post_title="test",
                subreddit="test",
            )

    def test_signal_response_optional_fields(self):
        """SignalResponse handles optional fields."""
        response = SignalResponse(
            id=123,
            ticker="TSLA",
            stance="bearish",
            confidence=0.7,
            event_type="product_delay",
            reasoning="Delayed product launch",
            created_at=1708041600,
            post_title="TSLA delays product",
            subreddit="investing",
            strategy="put_debit_spread",
            credibility_score=0.78,
        )

        assert response.strategy == "put_debit_spread"
        assert response.credibility_score == 0.78


class TestTradeIdeaResponse:
    def test_trade_idea_response_minimal(self):
        """TradeIdeaResponse with required fields only."""
        response = TradeIdeaResponse(
            ticker="TSLA",
            strategy="call_debit_spread",
            stance="bullish",
        )

        assert response.ticker == "TSLA"
        assert response.strategy == "call_debit_spread"
        assert response.stance == "bullish"
        assert response.entry_price is None
        assert response.stop_loss is None

    def test_trade_idea_response_full(self):
        """TradeIdeaResponse with all fields populated."""
        response = TradeIdeaResponse(
            ticker="AAPL",
            strategy="iron_condor",
            stance="neutral",
            entry_price=250.50,
            stop_loss=240.00,
            target=270.00,
            contracts=10,
            max_loss=500.00,
            max_gain=1500.00,
            iv_percentile=65.0,
        )

        assert response.ticker == "AAPL"
        assert response.entry_price == 250.50
        assert response.contracts == 10
        assert response.max_loss == 500.00
        assert response.iv_percentile == 65.0


class TestPaginatedResponse:
    def test_paginated_response_first_page(self):
        """PaginatedResponse for first page."""
        items = [{"id": i, "name": f"Item {i}"} for i in range(1, 51)]
        response = PaginatedResponse[dict](
            items=items,
            total=1000,
            page=1,
            page_size=50,
            total_pages=20,
            has_next=True,
            has_prev=False,
        )

        assert len(response.items) == 50
        assert response.total == 1000
        assert response.page == 1
        assert response.has_next is True
        assert response.has_prev is False

    def test_paginated_response_middle_page(self):
        """PaginatedResponse for middle page."""
        items = [{"id": i} for i in range(101, 151)]
        response = PaginatedResponse[dict](
            items=items,
            total=1000,
            page=3,
            page_size=50,
            total_pages=20,
            has_next=True,
            has_prev=True,
        )

        assert response.page == 3
        assert response.has_next is True
        assert response.has_prev is True

    def test_paginated_response_last_page(self):
        """PaginatedResponse for last page."""
        items = [{"id": i} for i in range(951, 1001)]
        response = PaginatedResponse[dict](
            items=items,
            total=1000,
            page=20,
            page_size=50,
            total_pages=20,
            has_next=False,
            has_prev=True,
        )

        assert response.page == 20
        assert response.has_next is False
        assert response.has_prev is True

    def test_paginated_response_empty(self):
        """PaginatedResponse with no items."""
        response = PaginatedResponse[dict](
            items=[],
            total=0,
            page=1,
            page_size=50,
            total_pages=0,
            has_next=False,
            has_prev=False,
        )

        assert len(response.items) == 0
        assert response.total == 0
        assert response.has_next is False


class TestHealthResponse:
    def test_health_response(self):
        """HealthResponse with all fields."""
        response = HealthResponse(
            status="healthy",
            version="0.1.0",
            uptime_seconds=3600,
            database={
                "status": "connected",
                "signals_stored": 50000,
                "size_mb": 150.5,
            },
            system={
                "memory_rss_mb": 250.5,
                "cpu_percent": 15.2,
                "num_threads": 8,
            },
        )

        assert response.status == "healthy"
        assert response.version == "0.1.0"
        assert response.uptime_seconds == 3600
        assert response.database["signals_stored"] == 50000
        assert response.system["cpu_percent"] == 15.2


class TestAnalyticsResponse:
    def test_analytics_response_valid(self):
        """AnalyticsResponse with valid data."""
        response = AnalyticsResponse(
            win_rate=65.5,
            total_signals=1000,
            total_trades=850,
            avg_confidence=0.75,
            top_tickers=[
                {"ticker": "AAPL", "signals": 50, "win_rate": 70.0},
                {"ticker": "TSLA", "signals": 45, "win_rate": 65.5},
            ],
            performance_by_category={
                "earnings_beat": {"win_rate": 72.0, "count": 100},
                "product_launch": {"win_rate": 65.0, "count": 50},
            },
        )

        assert response.win_rate == 65.5
        assert response.total_signals == 1000
        assert len(response.top_tickers) == 2
        assert "earnings_beat" in response.performance_by_category

    def test_analytics_response_win_rate_validation(self):
        """AnalyticsResponse validates win_rate 0-100."""
        # Valid: 0.0
        response1 = AnalyticsResponse(
            win_rate=0.0,
            total_signals=100,
            total_trades=50,
            avg_confidence=0.5,
            top_tickers=[],
            performance_by_category={},
        )
        assert response1.win_rate == 0.0

        # Valid: 100.0
        response2 = AnalyticsResponse(
            win_rate=100.0,
            total_signals=100,
            total_trades=50,
            avg_confidence=0.5,
            top_tickers=[],
            performance_by_category={},
        )
        assert response2.win_rate == 100.0

        # Invalid: > 100
        with pytest.raises(ValidationError):
            AnalyticsResponse(
                win_rate=105.0,
                total_signals=100,
                total_trades=50,
                avg_confidence=0.5,
                top_tickers=[],
                performance_by_category={},
            )

        # Invalid: < 0
        with pytest.raises(ValidationError):
            AnalyticsResponse(
                win_rate=-5.0,
                total_signals=100,
                total_trades=50,
                avg_confidence=0.5,
                top_tickers=[],
                performance_by_category={},
            )

    def test_analytics_response_avg_confidence_validation(self):
        """AnalyticsResponse validates avg_confidence 0.0-1.0."""
        # Valid
        response = AnalyticsResponse(
            win_rate=50.0,
            total_signals=100,
            total_trades=50,
            avg_confidence=0.75,
            top_tickers=[],
            performance_by_category={},
        )
        assert response.avg_confidence == 0.75

        # Invalid: > 1.0
        with pytest.raises(ValidationError):
            AnalyticsResponse(
                win_rate=50.0,
                total_signals=100,
                total_trades=50,
                avg_confidence=1.5,
                top_tickers=[],
                performance_by_category={},
            )


class TestTierLimitsResponse:
    def test_tier_limits_response(self):
        """TierLimitsResponse with all fields."""
        response = TierLimitsResponse(
            tier="pro",
            daily_api_limit=1000,
            daily_api_used=150,
            daily_api_remaining=850,
            real_time_access=True,
            advanced_features=True,
            signal_delay_minutes=0,
        )

        assert response.tier == "pro"
        assert response.daily_api_limit == 1000
        assert response.daily_api_used == 150
        assert response.daily_api_remaining == 850
        assert response.real_time_access is True
        assert response.signal_delay_minutes == 0


class TestBacktestRequest:
    def test_backtest_request_minimal(self):
        """BacktestRequest with required fields only."""
        request = BacktestRequest(
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_capital=10000.0,
        )

        assert request.ticker is None
        assert request.start_date == "2024-01-01"
        assert request.end_date == "2024-12-31"
        assert request.initial_capital == 10000.0
        assert request.strategy is None
        assert request.min_confidence == 0.7  # Default

    def test_backtest_request_full(self):
        """BacktestRequest with all fields populated."""
        request = BacktestRequest(
            ticker="AAPL",
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_capital=50000.0,
            strategy="call_debit_spread",
            min_confidence=0.8,
        )

        assert request.ticker == "AAPL"
        assert request.strategy == "call_debit_spread"
        assert request.min_confidence == 0.8

    def test_backtest_request_initial_capital_validation(self):
        """BacktestRequest validates initial_capital > 0."""
        # Valid
        request = BacktestRequest(
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_capital=1.0,
        )
        assert request.initial_capital == 1.0

        # Invalid: 0
        with pytest.raises(ValidationError):
            BacktestRequest(
                start_date="2024-01-01",
                end_date="2024-12-31",
                initial_capital=0.0,
            )

        # Invalid: negative
        with pytest.raises(ValidationError):
            BacktestRequest(
                start_date="2024-01-01",
                end_date="2024-12-31",
                initial_capital=-1000.0,
            )

    def test_backtest_request_min_confidence_validation(self):
        """BacktestRequest validates min_confidence 0.0-1.0."""
        # Valid: 0.0
        request1 = BacktestRequest(
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_capital=10000.0,
            min_confidence=0.0,
        )
        assert request1.min_confidence == 0.0

        # Valid: 1.0
        request2 = BacktestRequest(
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_capital=10000.0,
            min_confidence=1.0,
        )
        assert request2.min_confidence == 1.0

        # Invalid: > 1.0
        with pytest.raises(ValidationError):
            BacktestRequest(
                start_date="2024-01-01",
                end_date="2024-12-31",
                initial_capital=10000.0,
                min_confidence=1.5,
            )

        # Invalid: < 0.0
        with pytest.raises(ValidationError):
            BacktestRequest(
                start_date="2024-01-01",
                end_date="2024-12-31",
                initial_capital=10000.0,
                min_confidence=-0.1,
            )


class TestBacktestResponse:
    def test_backtest_response(self):
        """BacktestResponse with all fields."""
        response = BacktestResponse(
            total_return=25.5,
            sharpe_ratio=1.8,
            max_drawdown=-15.2,
            win_rate=65.0,
            total_trades=150,
            avg_return_per_trade=2.5,
            best_trade=45.0,
            worst_trade=-12.0,
        )

        assert response.total_return == 25.5
        assert response.sharpe_ratio == 1.8
        assert response.max_drawdown == -15.2
        assert response.win_rate == 65.0
        assert response.total_trades == 150
        assert response.best_trade == 45.0
        assert response.worst_trade == -12.0


class TestSerialization:
    def test_all_models_serializable(self):
        """All models can be serialized to dict/JSON."""
        models = [
            APIResponse[dict](success=True, data={"test": "value"}),
            ErrorResponse(error="Test error"),
            SignalResponse(
                id=1,
                ticker="AAPL",
                stance="bullish",
                confidence=0.8,
                event_type="test",
                reasoning="test",
                created_at=123,
                post_title="test",
                subreddit="test",
            ),
            TradeIdeaResponse(ticker="TSLA", strategy="calls", stance="bullish"),
            PaginatedResponse[dict](
                items=[],
                total=0,
                page=1,
                page_size=50,
                total_pages=0,
                has_next=False,
                has_prev=False,
            ),
            HealthResponse(
                status="healthy",
                version="0.1.0",
                uptime_seconds=100,
                database={},
                system={},
            ),
            AnalyticsResponse(
                win_rate=50.0,
                total_signals=100,
                total_trades=50,
                avg_confidence=0.5,
                top_tickers=[],
                performance_by_category={},
            ),
            TierLimitsResponse(
                tier="free",
                daily_api_limit=100,
                daily_api_used=10,
                daily_api_remaining=90,
                real_time_access=False,
                advanced_features=False,
                signal_delay_minutes=15,
            ),
            BacktestRequest(
                start_date="2024-01-01",
                end_date="2024-12-31",
                initial_capital=10000.0,
            ),
            BacktestResponse(
                total_return=10.0,
                sharpe_ratio=1.0,
                max_drawdown=-10.0,
                win_rate=50.0,
                total_trades=100,
                avg_return_per_trade=1.0,
                best_trade=20.0,
                worst_trade=-15.0,
            ),
        ]

        for model in models:
            data = model.model_dump()
            assert isinstance(data, dict)
