"""Tests for autonomous trading agent execution engine."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import math

from rot.agents.engine import AgentEngine
from rot.agents.types import AgentRule, AgentPerformance


# ============================================================================
# _flatten_signal tests
# ============================================================================

def test_flatten_signal_with_dataclass_event():
    """Test _flatten_signal converts dataclass Event to flat dict."""
    engine = AgentEngine(db=AsyncMock())

    # Mock Event and TradeIdea as objects with attributes
    event = MagicMock()
    event.entities = ["TSLA", "AAPL"]
    event.event_type = "product_news"
    event.stance = "bullish"
    event.confidence = 0.75
    event.time_horizon = "1w"
    event.meta = {"sector": "Technology"}
    event.evidence = [MagicMock(subreddit="wallstreetbets")]

    trade = MagicMock()
    trade.strategy = "debit_spread"
    trade.quality_score = 0.85

    signal_data = {
        "id": "sig123",
        "event": event,
        "trade_idea": trade,
        "market_data": {"last_close": 250.0, "market_cap": 800e9},
    }

    result = engine._flatten_signal(signal_data)

    assert result["ticker"] == "TSLA"
    assert result["event_type"] == "product_news"
    assert result["stance"] == "bullish"
    assert result["confidence"] == 0.75
    assert result["time_horizon"] == "1w"
    assert result["sector"] == "Technology"
    assert result["subreddit"] == "wallstreetbets"
    assert result["strategy"] == "debit_spread"
    assert result["quality_score"] == 0.85
    assert result["id"] == "sig123"
    assert result["price"] == 250.0
    assert result["market_cap"] == 800e9


def test_flatten_signal_with_dict_event():
    """Test _flatten_signal converts dict-based event to flat dict."""
    engine = AgentEngine(db=AsyncMock())

    signal_data = {
        "signal_id": "sig456",
        "event": {
            "entities": ["NVDA"],
            "event_type": "earnings_rumor",
            "stance": "bearish",
            "confidence": 0.6,
            "time_horizon": "intraday",
            "meta": {"sector": "Semiconductors"},
            "evidence": [{"subreddit": "stocks"}],
        },
        "trade_idea": {
            "strategy": "credit_spread",
            "quality_score": 0.7,
        },
        "market_data": {"last_close": 480.0, "market_cap": 1.2e12},
    }

    result = engine._flatten_signal(signal_data)

    assert result["ticker"] == "NVDA"
    assert result["event_type"] == "earnings_rumor"
    assert result["stance"] == "bearish"
    assert result["confidence"] == 0.6
    assert result["time_horizon"] == "intraday"
    assert result["sector"] == "Semiconductors"
    assert result["subreddit"] == "stocks"
    assert result["strategy"] == "credit_spread"
    assert result["quality_score"] == 0.7
    assert result["id"] == "sig456"
    assert result["price"] == 480.0
    assert result["market_cap"] == 1.2e12


def test_flatten_signal_missing_fields():
    """Test _flatten_signal handles missing fields gracefully."""
    engine = AgentEngine(db=AsyncMock())

    signal_data = {
        "event": {
            "entities": [],  # Empty entities
            "stance": "unknown",
        },
        "trade_idea": {},
        "market_data": {},
    }

    result = engine._flatten_signal(signal_data)

    assert result["ticker"] == "UNKNOWN"
    assert result["event_type"] == "other"
    assert result["stance"] == "unknown"
    assert result["confidence"] == 0
    assert result["strategy"] == "none"
    assert result["quality_score"] == 0
    assert result["price"] == 0
    assert result["market_cap"] == 0


# ============================================================================
# Metric computation tests
# ============================================================================

def test_compute_sharpe_with_positive_returns():
    """Test Sharpe ratio computation with positive returns."""
    returns = [0.02, 0.03, -0.01, 0.04, 0.02]
    sharpe = AgentEngine._compute_sharpe(returns)

    # Expected: mean ~0.02, std ~0.018, sharpe ~(0.02/0.018)*sqrt(252) ~17.7
    assert sharpe > 0
    assert 10 < sharpe < 25


def test_compute_sharpe_with_empty_returns():
    """Test Sharpe ratio returns 0 for empty returns."""
    assert AgentEngine._compute_sharpe([]) == 0.0
    assert AgentEngine._compute_sharpe([0.05]) == 0.0


def test_compute_sharpe_with_zero_std():
    """Test Sharpe ratio returns 0 when std is zero (all identical returns)."""
    returns = [0.05, 0.05, 0.05, 0.05]
    sharpe = AgentEngine._compute_sharpe(returns)
    assert sharpe == 0.0


def test_compute_max_drawdown_with_losses():
    """Test max drawdown computation with losing streak."""
    returns = [0.05, 0.02, -0.10, -0.05, 0.03, -0.02]
    # Cumulative: 0.05, 0.07, -0.03, -0.08, -0.05, -0.07
    # Peak: 0.07, drawdown = 0.07 - (-0.08) = 0.15
    dd = AgentEngine._compute_max_drawdown(returns)
    assert dd == pytest.approx(0.15, abs=0.01)


def test_compute_max_drawdown_all_positive():
    """Test max drawdown is 0 when all returns are positive."""
    returns = [0.02, 0.03, 0.01, 0.04]
    dd = AgentEngine._compute_max_drawdown(returns)
    assert dd == 0.0


def test_compute_max_drawdown_empty():
    """Test max drawdown returns 0 for empty returns."""
    dd = AgentEngine._compute_max_drawdown([])
    assert dd == 0.0


# ============================================================================
# evaluate_signal tests
# ============================================================================

@pytest.mark.asyncio
async def test_evaluate_signal_no_active_agents():
    """Test evaluate_signal returns empty list when no agents active."""
    db = AsyncMock()
    db.get_active_agents.return_value = []

    engine = AgentEngine(db)

    signal_data = {
        "event": {"entities": ["TSLA"], "stance": "bullish", "confidence": 0.7},
        "trade_idea": {},
    }

    result = await engine.evaluate_signal(signal_data)
    assert result == []


@pytest.mark.asyncio
async def test_evaluate_signal_non_tradeable_stance():
    """Test evaluate_signal skips signals with non-tradeable stance (mixed/unknown)."""
    db = AsyncMock()
    db.get_active_agents.return_value = [
        {"id": "agent1", "user_id": "user1", "min_confidence": 0.4}
    ]

    engine = AgentEngine(db)

    signal_data = {
        "event": {"entities": ["TSLA"], "stance": "mixed", "confidence": 0.7},
        "trade_idea": {},
    }

    result = await engine.evaluate_signal(signal_data)
    assert result == []


@pytest.mark.asyncio
async def test_evaluate_signal_executes_trade():
    """Test evaluate_signal executes trade for matching agent."""
    db = AsyncMock()
    db.get_active_agents.return_value = [
        {
            "id": "agent1",
            "user_id": "user1",
            "agent_type": "signal_follower",
            "min_confidence": 0.5,
            "rules_json": "[]",
            "config_json": "{}",
            "max_position_dollars": 1000.0,
            "max_daily_trades": 5,
            "max_portfolio_exposure_pct": 50.0,
            "stop_loss_pct": 10.0,
        }
    ]
    db.get_agent_trade_by_signal.return_value = None
    db.get_agent_daily_trade_count.return_value = 2
    db.get_paper_portfolio.return_value = {"balance": 10000}
    db.get_agent_trades.return_value = []
    db.get_agent_daily_pnl.return_value = 0.0
    db.create_agent_trade.return_value = None

    engine = AgentEngine(db)

    signal_data = {
        "id": "sig123",
        "event": {
            "entities": ["TSLA"],
            "stance": "bullish",
            "confidence": 0.75,
        },
        "trade_idea": {},
        "market_data": {"last_close": 250.0},
    }

    result = await engine.evaluate_signal(signal_data)

    assert len(result) == 1
    trade = result[0]
    assert trade["agent_id"] == "agent1"
    assert trade["ticker"] == "TSLA"
    assert trade["stance"] == "bullish"
    assert trade["entry_price"] == 250.0
    assert trade["dollars"] == 1000.0
    assert trade["quantity"] == 4.0  # 1000 / 250


# ============================================================================
# execute_trade tests
# ============================================================================

@pytest.mark.asyncio
async def test_execute_trade_creates_record():
    """Test execute_trade creates a trade record with correct fields."""
    db = AsyncMock()
    db.create_agent_trade.return_value = None

    engine = AgentEngine(db)

    agent = {
        "id": "agent1",
        "user_id": "user1",
        "max_position_dollars": 2000.0,
    }

    signal = {
        "id": "sig456",
        "ticker": "NVDA",
        "stance": "bearish",
        "price": 480.0,
    }

    trade = await engine.execute_trade(agent, signal)

    assert trade is not None
    assert trade["agent_id"] == "agent1"
    assert trade["user_id"] == "user1"
    assert trade["signal_id"] == "sig456"
    assert trade["ticker"] == "NVDA"
    assert trade["stance"] == "bearish"
    assert trade["entry_price"] == 480.0
    assert trade["dollars"] == 2000.0
    assert trade["quantity"] == pytest.approx(4.1667, abs=0.01)
    assert trade["status"] == "open"

    db.create_agent_trade.assert_called_once()


@pytest.mark.asyncio
async def test_execute_trade_no_price():
    """Test execute_trade returns None when price is missing or invalid."""
    db = AsyncMock()
    engine = AgentEngine(db)

    agent = {"id": "agent1", "user_id": "user1", "max_position_dollars": 1000.0}
    signal = {"id": "sig123", "ticker": "TSLA", "stance": "bullish", "price": 0}

    trade = await engine.execute_trade(agent, signal)
    assert trade is None

    signal["price"] = None
    trade = await engine.execute_trade(agent, signal)
    assert trade is None


# ============================================================================
# check_safety_rails tests
# ============================================================================

@pytest.mark.asyncio
async def test_safety_rails_daily_trade_cap_hit():
    """Test safety rails block trade when daily trade cap is hit."""
    db = AsyncMock()
    db.get_agent_daily_trade_count.return_value = 5

    engine = AgentEngine(db)

    agent = {"id": "agent1", "user_id": "user1", "max_daily_trades": 5}

    safe, reason = await engine.check_safety_rails(agent)

    assert safe is False
    assert "daily trade limit" in reason
    assert "5/5" in reason


@pytest.mark.asyncio
async def test_safety_rails_portfolio_exposure_exceeded():
    """Test safety rails block trade when portfolio exposure exceeded."""
    db = AsyncMock()
    db.get_agent_daily_trade_count.return_value = 2
    db.get_paper_portfolio.return_value = {"balance": 10000}
    db.get_agent_trades.return_value = [
        {"dollars": 3000},
        {"dollars": 2500},
    ]
    db.get_agent_daily_pnl.return_value = 0.0

    engine = AgentEngine(db)

    agent = {
        "id": "agent1",
        "user_id": "user1",
        "max_daily_trades": 5,
        "max_portfolio_exposure_pct": 50.0,
        "stop_loss_pct": 10.0,
    }

    safe, reason = await engine.check_safety_rails(agent)

    # Open exposure: 5500 / 10000 = 55% > 50%
    assert safe is False
    assert "exposure limit" in reason
    assert "55.0%" in reason


@pytest.mark.asyncio
async def test_safety_rails_stop_loss_triggered():
    """Test safety rails auto-pause agent when stop loss triggered."""
    db = AsyncMock()
    db.get_agent_daily_trade_count.return_value = 3
    db.get_paper_portfolio.return_value = {"balance": 10000}
    db.get_agent_trades.return_value = []
    db.get_agent_daily_pnl.return_value = -1200.0  # -12% loss
    db.update_agent_status.return_value = True

    engine = AgentEngine(db)

    agent = {
        "id": "agent1",
        "user_id": "user1",
        "max_daily_trades": 5,
        "max_portfolio_exposure_pct": 50.0,
        "stop_loss_pct": 10.0,
    }

    safe, reason = await engine.check_safety_rails(agent)

    assert safe is False
    assert "stop loss triggered" in reason
    assert "12.0%" in reason
    db.update_agent_status.assert_called_once_with("agent1", "paused")


@pytest.mark.asyncio
async def test_safety_rails_all_clear():
    """Test safety rails pass when all checks clear."""
    db = AsyncMock()
    db.get_agent_daily_trade_count.return_value = 2
    db.get_paper_portfolio.return_value = {"balance": 10000}
    db.get_agent_trades.return_value = [{"dollars": 1000}]
    db.get_agent_daily_pnl.return_value = 150.0  # Positive P&L

    engine = AgentEngine(db)

    agent = {
        "id": "agent1",
        "user_id": "user1",
        "max_daily_trades": 5,
        "max_portfolio_exposure_pct": 50.0,
        "stop_loss_pct": 10.0,
    }

    safe, reason = await engine.check_safety_rails(agent)

    assert safe is True
    assert reason == ""


# ============================================================================
# get_agent_performance tests
# ============================================================================

@pytest.mark.asyncio
async def test_get_agent_performance_computes_metrics():
    """Test get_agent_performance computes all metrics correctly."""
    db = AsyncMock()
    db.get_agent_performance_stats.return_value = {
        "total_trades": 20,
        "winning_trades": 14,
        "total_pnl": 1250.0,
        "returns": [0.05, 0.03, -0.02, 0.04, 0.02, -0.01],
    }
    db.get_agent_daily_trade_count.return_value = 3

    engine = AgentEngine(db)

    perf = await engine.get_agent_performance("agent1")

    assert isinstance(perf, AgentPerformance)
    assert perf.agent_id == "agent1"
    assert perf.total_trades == 20
    assert perf.winning_trades == 14
    assert perf.total_pnl == 1250.0
    assert perf.win_rate == 0.7  # 14/20
    assert perf.avg_trade_pnl == 62.5  # 1250/20
    assert perf.sharpe_ratio > 0
    assert perf.max_drawdown_pct >= 0
    assert perf.trades_today == 3


@pytest.mark.asyncio
async def test_get_agent_performance_no_trades():
    """Test get_agent_performance handles agent with no trades."""
    db = AsyncMock()
    db.get_agent_performance_stats.return_value = {
        "total_trades": 0,
        "winning_trades": 0,
        "total_pnl": 0.0,
        "returns": [],
    }
    db.get_agent_daily_trade_count.return_value = 0

    engine = AgentEngine(db)

    perf = await engine.get_agent_performance("agent2")

    assert perf.total_trades == 0
    assert perf.win_rate == 0.0
    assert perf.avg_trade_pnl == 0.0
    assert perf.sharpe_ratio == 0.0
    assert perf.max_drawdown_pct == 0.0


# ============================================================================
# Edge cases and integration tests
# ============================================================================

@pytest.mark.asyncio
async def test_evaluate_agent_below_confidence_gate():
    """Test _evaluate_agent skips signal below min confidence."""
    db = AsyncMock()
    engine = AgentEngine(db)

    agent = {
        "id": "agent1",
        "user_id": "user1",
        "agent_type": "signal_follower",
        "min_confidence": 0.7,
        "rules_json": "[]",
    }

    signal = {
        "ticker": "AAPL",
        "stance": "bullish",
        "confidence": 0.5,  # Below threshold
    }

    trade = await engine._evaluate_agent(agent, signal)
    assert trade is None


@pytest.mark.asyncio
async def test_evaluate_agent_custom_rule_or_logic():
    """Test _evaluate_agent uses OR logic for custom_rule agent type."""
    db = AsyncMock()
    db.get_agent_trade_by_signal.return_value = None
    db.get_agent_daily_trade_count.return_value = 0
    db.get_paper_portfolio.return_value = {"balance": 10000}
    db.get_agent_trades.return_value = []
    db.get_agent_daily_pnl.return_value = 0.0
    db.create_agent_trade.return_value = None

    engine = AgentEngine(db)

    agent = {
        "id": "agent1",
        "user_id": "user1",
        "agent_type": "custom_rule",
        "min_confidence": 0.5,
        "rules_json": '[{"field": "ticker", "operator": "eq", "value": "TSLA"}, {"field": "confidence", "operator": "gte", "value": 0.8}]',
        "config_json": '{"rule_logic": "or"}',
        "max_position_dollars": 1000.0,
        "max_daily_trades": 5,
        "max_portfolio_exposure_pct": 50.0,
        "stop_loss_pct": 10.0,
    }

    signal = {
        "id": "sig789",
        "ticker": "AAPL",  # Doesn't match first rule
        "stance": "bullish",
        "confidence": 0.85,  # Matches second rule (OR logic)
        "price": 180.0,
    }

    trade = await engine._evaluate_agent(agent, signal)
    assert trade is not None
    assert trade["ticker"] == "AAPL"


@pytest.mark.asyncio
async def test_evaluate_agent_contrarian_flips_stance():
    """Test _evaluate_agent flips stance for contrarian agent."""
    db = AsyncMock()
    db.get_agent_trade_by_signal.return_value = None
    db.get_agent_daily_trade_count.return_value = 0
    db.get_paper_portfolio.return_value = {"balance": 10000}
    db.get_agent_trades.return_value = []
    db.get_agent_daily_pnl.return_value = 0.0
    db.create_agent_trade.return_value = None

    engine = AgentEngine(db)

    agent = {
        "id": "agent2",
        "user_id": "user1",
        "agent_type": "contrarian",
        "min_confidence": 0.5,
        "rules_json": "[]",
        "config_json": "{}",
        "max_position_dollars": 1000.0,
        "max_daily_trades": 5,
        "max_portfolio_exposure_pct": 50.0,
        "stop_loss_pct": 10.0,
    }

    signal = {
        "id": "sig999",
        "ticker": "NVDA",
        "stance": "bullish",  # Original stance
        "confidence": 0.7,
        "price": 480.0,
    }

    trade = await engine._evaluate_agent(agent, signal)
    assert trade is not None
    assert trade["stance"] == "bearish"  # Flipped by contrarian logic


@pytest.mark.asyncio
async def test_evaluate_agent_duplicate_signal():
    """Test _evaluate_agent skips duplicate signal."""
    db = AsyncMock()
    db.get_agent_trade_by_signal.return_value = {"id": "existing_trade"}
    db.get_agent_daily_trade_count.return_value = 0
    db.get_paper_portfolio.return_value = {"balance": 10000}
    db.get_agent_trades.return_value = []
    db.get_agent_daily_pnl.return_value = 0.0

    engine = AgentEngine(db)

    agent = {
        "id": "agent1",
        "user_id": "user1",
        "agent_type": "signal_follower",
        "min_confidence": 0.5,
        "rules_json": "[]",
        "config_json": "{}",
        "max_daily_trades": 5,
        "max_portfolio_exposure_pct": 50.0,
        "stop_loss_pct": 10.0,
    }

    signal = {
        "id": "sig_duplicate",
        "ticker": "TSLA",
        "stance": "bullish",
        "confidence": 0.7,
        "price": 250.0,
    }

    trade = await engine._evaluate_agent(agent, signal)
    assert trade is None
