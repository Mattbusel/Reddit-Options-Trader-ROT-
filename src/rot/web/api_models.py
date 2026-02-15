"""Pydantic models for API responses.

Provides comprehensive response models for OpenAPI documentation:
- Standard response wrappers
- Error responses with consistent format
- Signal and trade idea models
- Analytics and metrics responses
- Pagination support
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Generic, TypeVar
from datetime import datetime

from pydantic import BaseModel, Field


# Generic type for data responses
T = TypeVar('T')


class APIResponse(BaseModel, Generic[T]):
    """Standard API response wrapper.

    All API responses follow this format for consistency.
    """
    success: bool = Field(
        description="Whether the request was successful",
        example=True
    )
    data: Optional[T] = Field(
        default=None,
        description="Response data (null on error)"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message (null on success)",
        example=None
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Unique request ID for tracing",
        example="req_abc123-def4-5678-90ab-cdef12345678"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "data": {"example": "data"},
                "error": None,
                "request_id": "req_abc123-def4-5678-90ab-cdef12345678"
            }
        }


class ErrorResponse(BaseModel):
    """Standard error response format."""
    success: bool = Field(default=False, description="Always false for errors")
    error: str = Field(description="Error message", example="Invalid API key")
    error_code: Optional[str] = Field(
        default=None,
        description="Machine-readable error code",
        example="INVALID_API_KEY"
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional error details"
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Request ID for support",
        example="req_abc123"
    )


class SignalResponse(BaseModel):
    """Trading signal response model."""
    id: int = Field(description="Signal ID", example=12345)
    ticker: str = Field(description="Stock ticker symbol", example="AAPL")
    stance: str = Field(
        description="Trading stance (bullish/bearish/mixed/unknown)",
        example="bullish"
    )
    confidence: float = Field(
        description="Signal confidence (0.0-1.0)",
        example=0.85,
        ge=0.0,
        le=1.0
    )
    event_type: str = Field(
        description="Type of event detected",
        example="earnings_beat"
    )
    reasoning: str = Field(
        description="AI-generated reasoning for the signal",
        example="Strong earnings beat with positive guidance"
    )
    strategy: Optional[str] = Field(
        default=None,
        description="Recommended options strategy",
        example="call_debit_spread"
    )
    created_at: int = Field(
        description="Unix timestamp when signal was created",
        example=1708041600
    )
    post_title: str = Field(
        description="Original Reddit post title",
        example="AAPL crushing it - earnings beat by 20%"
    )
    subreddit: str = Field(description="Source subreddit", example="wallstreetbets")
    credibility_score: Optional[float] = Field(
        default=None,
        description="ML credibility score (0.0-1.0)",
        example=0.78
    )


class TradeIdeaResponse(BaseModel):
    """Options trade idea response model."""
    ticker: str = Field(description="Stock ticker", example="TSLA")
    strategy: str = Field(
        description="Options strategy name",
        example="call_debit_spread"
    )
    stance: str = Field(description="Bullish/bearish/neutral", example="bullish")
    entry_price: Optional[float] = Field(
        default=None,
        description="Recommended entry price",
        example=250.50
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="Stop loss price",
        example=240.00
    )
    target: Optional[float] = Field(
        default=None,
        description="Target price",
        example=270.00
    )
    contracts: Optional[int] = Field(
        default=None,
        description="Number of contracts",
        example=10
    )
    max_loss: Optional[float] = Field(
        default=None,
        description="Maximum potential loss",
        example=500.00
    )
    max_gain: Optional[float] = Field(
        default=None,
        description="Maximum potential gain",
        example=1500.00
    )
    iv_percentile: Optional[float] = Field(
        default=None,
        description="Implied volatility percentile",
        example=65.0
    )


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""
    items: List[T] = Field(description="List of items in current page")
    total: int = Field(description="Total number of items", example=1000)
    page: int = Field(description="Current page number (1-indexed)", example=1)
    page_size: int = Field(description="Number of items per page", example=50)
    total_pages: int = Field(description="Total number of pages", example=20)
    has_next: bool = Field(description="Whether there is a next page", example=True)
    has_prev: bool = Field(description="Whether there is a previous page", example=False)


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str = Field(description="Health status", example="healthy")
    version: str = Field(description="API version", example="0.1.0")
    uptime_seconds: int = Field(description="Server uptime in seconds", example=3600)
    database: Dict[str, Any] = Field(
        description="Database health information",
        example={
            "status": "connected",
            "signals_stored": 50000,
            "size_mb": 150.5
        }
    )
    system: Dict[str, Any] = Field(
        description="System metrics",
        example={
            "memory_rss_mb": 250.5,
            "cpu_percent": 15.2,
            "num_threads": 8
        }
    )


class AnalyticsResponse(BaseModel):
    """Analytics metrics response."""
    win_rate: float = Field(
        description="Win rate percentage",
        example=65.5,
        ge=0.0,
        le=100.0
    )
    total_signals: int = Field(description="Total number of signals", example=1000)
    total_trades: int = Field(description="Total number of trades", example=850)
    avg_confidence: float = Field(
        description="Average confidence score",
        example=0.75,
        ge=0.0,
        le=1.0
    )
    top_tickers: List[Dict[str, Any]] = Field(
        description="Top performing tickers",
        example=[
            {"ticker": "AAPL", "signals": 50, "win_rate": 70.0},
            {"ticker": "TSLA", "signals": 45, "win_rate": 65.5}
        ]
    )
    performance_by_category: Dict[str, Dict[str, float]] = Field(
        description="Performance metrics by event category",
        example={
            "earnings_beat": {"win_rate": 72.0, "count": 100},
            "product_launch": {"win_rate": 65.0, "count": 50}
        }
    )


class TierLimitsResponse(BaseModel):
    """User tier limits response."""
    tier: str = Field(description="User tier", example="pro")
    daily_api_limit: int = Field(description="Daily API call limit", example=1000)
    daily_api_used: int = Field(description="API calls used today", example=150)
    daily_api_remaining: int = Field(description="Remaining API calls", example=850)
    real_time_access: bool = Field(description="Real-time data access", example=True)
    advanced_features: bool = Field(description="Advanced features enabled", example=True)
    signal_delay_minutes: int = Field(description="Signal delay in minutes", example=0)


class BacktestRequest(BaseModel):
    """Backtest configuration request."""
    ticker: Optional[str] = Field(
        default=None,
        description="Specific ticker to backtest (null for all)",
        example="AAPL"
    )
    start_date: str = Field(
        description="Start date (YYYY-MM-DD)",
        example="2024-01-01"
    )
    end_date: str = Field(
        description="End date (YYYY-MM-DD)",
        example="2024-12-31"
    )
    initial_capital: float = Field(
        description="Initial capital amount",
        example=10000.0,
        gt=0
    )
    strategy: Optional[str] = Field(
        default=None,
        description="Specific strategy to test",
        example="call_debit_spread"
    )
    min_confidence: float = Field(
        default=0.7,
        description="Minimum confidence threshold",
        example=0.7,
        ge=0.0,
        le=1.0
    )


class BacktestResponse(BaseModel):
    """Backtest results response."""
    total_return: float = Field(description="Total return percentage", example=25.5)
    sharpe_ratio: float = Field(description="Sharpe ratio", example=1.8)
    max_drawdown: float = Field(description="Maximum drawdown percentage", example=-15.2)
    win_rate: float = Field(description="Win rate percentage", example=65.0)
    total_trades: int = Field(description="Total number of trades", example=150)
    avg_return_per_trade: float = Field(
        description="Average return per trade",
        example=2.5
    )
    best_trade: float = Field(description="Best single trade return", example=45.0)
    worst_trade: float = Field(description="Worst single trade return", example=-12.0)


# OpenAPI examples for common responses
SIGNAL_LIST_EXAMPLE = {
    "success": True,
    "data": {
        "items": [
            {
                "id": 12345,
                "ticker": "AAPL",
                "stance": "bullish",
                "confidence": 0.85,
                "event_type": "earnings_beat",
                "reasoning": "Strong earnings beat with positive guidance",
                "created_at": 1708041600,
                "subreddit": "wallstreetbets"
            }
        ],
        "total": 1000,
        "page": 1,
        "page_size": 50,
        "has_next": True
    },
    "error": None,
    "request_id": "req_abc123"
}

ERROR_401_EXAMPLE = {
    "success": False,
    "error": "Authentication required. Please provide a valid API key.",
    "error_code": "UNAUTHORIZED",
    "request_id": "req_abc123"
}

ERROR_429_EXAMPLE = {
    "success": False,
    "error": "Rate limit exceeded. Your tier allows 1000 calls/day. Upgrade at /pricing.",
    "error_code": "RATE_LIMIT_EXCEEDED",
    "details": {
        "tier": "pro",
        "daily_limit": 1000,
        "daily_used": 1000,
        "reset_in_hours": 8
    },
    "request_id": "req_abc123"
}
