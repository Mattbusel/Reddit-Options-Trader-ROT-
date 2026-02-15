"""Unit tests for PaperTradingService.

Tests business logic with a mock database — no SQLite needed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from rot.services.paper_trading_service import (
    InsufficientBalanceError,
    NoPriceDataError,
    NotOwnerError,
    PaperTradingService,
    SignalNotFoundError,
    TradeAlreadyClosedError,
    TradeNotFoundError,
)


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_paper_portfolio = AsyncMock(return_value=None)
    db.init_paper_portfolio = AsyncMock()
    db.get_signal = AsyncMock(return_value=None)
    db.get_performance_for_signal = AsyncMock(return_value=None)
    db.create_paper_trade = AsyncMock(return_value={"id": "t1"})
    db.get_paper_trade = AsyncMock(return_value=None)
    db.close_paper_trade = AsyncMock(return_value={"id": "t1", "status": "closed"})
    db.get_paper_trades = AsyncMock(return_value=[])
    return db


@pytest.fixture
def svc(mock_db):
    return PaperTradingService(db=mock_db)


# ---------------------------------------------------------------------------
# get_or_create_portfolio
# ---------------------------------------------------------------------------

class TestGetOrCreatePortfolio:
    @pytest.mark.asyncio
    async def test_returns_existing_portfolio(self, svc, mock_db):
        """Returns existing portfolio without creating a new one."""
        mock_db.get_paper_portfolio = AsyncMock(return_value={"balance": 10000})
        result = await svc.get_or_create_portfolio("u1")
        assert result["balance"] == 10000
        mock_db.init_paper_portfolio.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_portfolio_if_missing(self, svc, mock_db):
        """Creates a new portfolio when none exists."""
        mock_db.get_paper_portfolio = AsyncMock(
            side_effect=[None, {"balance": 100000}]
        )
        result = await svc.get_or_create_portfolio("u1")
        assert result["balance"] == 100000
        mock_db.init_paper_portfolio.assert_called_once_with("u1")


# ---------------------------------------------------------------------------
# execute_trade
# ---------------------------------------------------------------------------

class TestExecuteTrade:
    @pytest.mark.asyncio
    async def test_success(self, svc, mock_db):
        """Successful trade returns trade dict."""
        mock_db.get_paper_portfolio = AsyncMock(return_value={"balance": 10000})
        mock_db.get_signal = AsyncMock(return_value={
            "ticker": "AAPL",
            "stance": "bullish",
            "market_data": {},
        })
        mock_db.get_performance_for_signal = AsyncMock(
            return_value={"price_at_signal": 150.0}
        )
        mock_db.create_paper_trade = AsyncMock(return_value={"id": "t1", "ticker": "AAPL"})

        result = await svc.execute_trade("u1", "s1", 1000.0)
        assert result["id"] == "t1"
        mock_db.create_paper_trade.assert_called_once()

    @pytest.mark.asyncio
    async def test_insufficient_balance(self, svc, mock_db):
        """Raises InsufficientBalanceError when balance too low."""
        mock_db.get_paper_portfolio = AsyncMock(return_value={"balance": 5.0})
        with pytest.raises(InsufficientBalanceError):
            await svc.execute_trade("u1", "s1", 100.0)

    @pytest.mark.asyncio
    async def test_signal_not_found(self, svc, mock_db):
        """Raises SignalNotFoundError when signal missing."""
        mock_db.get_paper_portfolio = AsyncMock(return_value={"balance": 10000})
        mock_db.get_signal = AsyncMock(return_value=None)
        with pytest.raises(SignalNotFoundError):
            await svc.execute_trade("u1", "s1", 1000.0)

    @pytest.mark.asyncio
    async def test_no_price_data(self, svc, mock_db):
        """Raises NoPriceDataError when no entry price available."""
        mock_db.get_paper_portfolio = AsyncMock(return_value={"balance": 10000})
        mock_db.get_signal = AsyncMock(return_value={
            "ticker": "AAPL",
            "stance": "bullish",
            "market_data": {},
        })
        mock_db.get_performance_for_signal = AsyncMock(return_value=None)
        with pytest.raises(NoPriceDataError):
            await svc.execute_trade("u1", "s1", 1000.0)

    @pytest.mark.asyncio
    async def test_uses_market_data_price_fallback(self, svc, mock_db):
        """Falls back to market_data for entry price."""
        mock_db.get_paper_portfolio = AsyncMock(return_value={"balance": 10000})
        mock_db.get_signal = AsyncMock(return_value={
            "ticker": "TSLA",
            "stance": "bearish",
            "market_data": {"TSLA": {"price": 200.0}},
        })
        mock_db.get_performance_for_signal = AsyncMock(return_value={})
        mock_db.create_paper_trade = AsyncMock(return_value={"id": "t2"})

        result = await svc.execute_trade("u1", "s1", 500.0)
        assert result["id"] == "t2"
        # Verify quantity calculation: 500 / 200 = 2.5
        call_kwargs = mock_db.create_paper_trade.call_args.kwargs
        assert call_kwargs["entry_price"] == 200.0
        assert call_kwargs["quantity"] == 2.5

    @pytest.mark.asyncio
    async def test_clamps_dollars_to_balance(self, svc, mock_db):
        """Allocation is clamped to portfolio balance."""
        mock_db.get_paper_portfolio = AsyncMock(return_value={"balance": 100.0})
        mock_db.get_signal = AsyncMock(return_value={
            "ticker": "AAPL",
            "stance": "bullish",
            "market_data": {},
        })
        mock_db.get_performance_for_signal = AsyncMock(
            return_value={"price_at_signal": 50.0}
        )
        mock_db.create_paper_trade = AsyncMock(return_value={"id": "t3"})

        await svc.execute_trade("u1", "s1", 5000.0)
        call_kwargs = mock_db.create_paper_trade.call_args.kwargs
        assert call_kwargs["dollars"] == 100.0  # clamped to balance


# ---------------------------------------------------------------------------
# close_trade
# ---------------------------------------------------------------------------

class TestCloseTrade:
    @pytest.mark.asyncio
    async def test_success(self, svc, mock_db):
        """Closes an open trade."""
        mock_db.get_paper_trade = AsyncMock(return_value={
            "id": "t1", "user_id": "u1", "status": "open", "signal_id": "s1"
        })
        mock_db.get_performance_for_signal = AsyncMock(
            return_value={"price_1w": 160.0}
        )
        mock_db.close_paper_trade = AsyncMock(
            return_value={"id": "t1", "status": "closed"}
        )
        result = await svc.close_trade("u1", "t1")
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_trade_not_found(self, svc, mock_db):
        """Raises TradeNotFoundError when trade missing."""
        mock_db.get_paper_trade = AsyncMock(return_value=None)
        with pytest.raises(TradeNotFoundError):
            await svc.close_trade("u1", "t1")

    @pytest.mark.asyncio
    async def test_not_owner(self, svc, mock_db):
        """Raises NotOwnerError when trade belongs to another user."""
        mock_db.get_paper_trade = AsyncMock(return_value={
            "id": "t1", "user_id": "u2", "status": "open", "signal_id": "s1"
        })
        with pytest.raises(NotOwnerError):
            await svc.close_trade("u1", "t1")

    @pytest.mark.asyncio
    async def test_already_closed(self, svc, mock_db):
        """Raises TradeAlreadyClosedError for closed trades."""
        mock_db.get_paper_trade = AsyncMock(return_value={
            "id": "t1", "user_id": "u1", "status": "closed", "signal_id": "s1"
        })
        with pytest.raises(TradeAlreadyClosedError):
            await svc.close_trade("u1", "t1")

    @pytest.mark.asyncio
    async def test_no_exit_price(self, svc, mock_db):
        """Raises NoPriceDataError when no exit price available."""
        mock_db.get_paper_trade = AsyncMock(return_value={
            "id": "t1", "user_id": "u1", "status": "open", "signal_id": "s1"
        })
        mock_db.get_performance_for_signal = AsyncMock(return_value=None)
        with pytest.raises(NoPriceDataError):
            await svc.close_trade("u1", "t1")

    @pytest.mark.asyncio
    async def test_exit_price_priority(self, svc, mock_db):
        """Uses price_1w as first priority for exit price."""
        mock_db.get_paper_trade = AsyncMock(return_value={
            "id": "t1", "user_id": "u1", "status": "open", "signal_id": "s1"
        })
        mock_db.get_performance_for_signal = AsyncMock(return_value={
            "price_1w": 170.0,
            "price_1d": 165.0,
            "price_at_signal": 150.0,
        })
        mock_db.close_paper_trade = AsyncMock(
            return_value={"id": "t1", "status": "closed"}
        )
        await svc.close_trade("u1", "t1")
        mock_db.close_paper_trade.assert_called_once_with("t1", 170.0)


# ---------------------------------------------------------------------------
# get_portfolio_summary
# ---------------------------------------------------------------------------

class TestGetPortfolioSummary:
    @pytest.mark.asyncio
    async def test_returns_portfolio_and_count(self, svc, mock_db):
        """Returns portfolio and open trade count."""
        mock_db.get_paper_portfolio = AsyncMock(return_value={"balance": 10000})
        mock_db.get_paper_trades = AsyncMock(return_value=[
            {"id": "t1"}, {"id": "t2"}
        ])
        result = await svc.get_portfolio_summary("u1")
        assert result["portfolio"]["balance"] == 10000
        assert result["open_positions"] == 2


# ---------------------------------------------------------------------------
# get_trades
# ---------------------------------------------------------------------------

class TestGetTrades:
    @pytest.mark.asyncio
    async def test_delegates_to_db(self, svc, mock_db):
        """Delegates to db.get_paper_trades."""
        mock_db.get_paper_trades = AsyncMock(return_value=[{"id": "t1"}])
        result = await svc.get_trades("u1", status="open", limit=10)
        assert len(result) == 1
        mock_db.get_paper_trades.assert_called_once_with("u1", status="open", limit=10)
