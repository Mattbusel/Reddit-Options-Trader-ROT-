"""
tests/test_strategy_db.py

Tests for strategy-related database methods in Database class.

Tests all strategy builder DB methods: strategies, strategy_trades,
strategy_portfolios, strategy_marketplace, market_regimes, strategy_discoveries.

All tests are async (pytest-asyncio).
"""

import pytest
import tempfile
import os
import time
import json
from rot.storage.database import Database


@pytest.fixture
async def db():
    """Create a temporary database for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = Database(db_path=tmp.name)
    await d.connect()
    yield d
    await d.close()
    os.unlink(tmp.name)


# ── Strategy CRUD ──


@pytest.mark.asyncio
async def test_save_and_get_strategy(db: Database):
    """save_strategy + get_strategy round-trip with JSON parsing."""
    strategy = {
        "id": "strat-001",
        "user_id": "user-001",
        "name": "Test Strategy",
        "description": "A test strategy",
        "rules": [
            {"type": "confidence", "operator": ">", "value": 0.7},
            {"type": "stance", "operator": "=", "value": "bullish"},
        ],
        "config": {"max_positions": 5, "stop_loss": 0.05},
        "performance": {"win_rate": 0.65, "total_trades": 100},
        "health_score": 0.85,
        "is_active": True,
        "source": "discovery",
        "created_at": time.time(),
        "updated_at": time.time(),
    }

    await db.save_strategy(strategy)

    # Retrieve and verify
    result = await db.get_strategy("strat-001")
    assert result is not None
    assert result["id"] == "strat-001"
    assert result["user_id"] == "user-001"
    assert result["name"] == "Test Strategy"
    assert result["description"] == "A test strategy"
    assert isinstance(result["rules"], list)
    assert len(result["rules"]) == 2
    assert result["rules"][0]["type"] == "confidence"
    assert isinstance(result["config"], dict)
    assert result["config"]["max_positions"] == 5
    assert isinstance(result["performance"], dict)
    assert result["performance"]["win_rate"] == 0.65
    assert result["health_score"] == 0.85
    assert result["is_active"] is True
    assert result["source"] == "discovery"


@pytest.mark.asyncio
async def test_save_strategy_defaults(db: Database):
    """save_strategy with minimal fields uses defaults."""
    strategy = {
        "id": "strat-002",
        "user_id": "user-002",
        "name": "Minimal Strategy",
    }

    await db.save_strategy(strategy)

    result = await db.get_strategy("strat-002")
    assert result is not None
    assert result["description"] == ""
    assert result["rules"] == []
    assert result["config"] == {}
    assert result["performance"] == {}
    assert result["health_score"] == 1.0
    assert result["is_active"] is False
    assert result["source"] == "manual"
    assert result["created_at"] > 0
    assert result["updated_at"] > 0


@pytest.mark.asyncio
async def test_get_strategy_nonexistent(db: Database):
    """get_strategy returns None for nonexistent ID."""
    result = await db.get_strategy("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_user_strategies(db: Database):
    """get_user_strategies returns all strategies for a user."""
    # Create 3 strategies for user-001
    for i in range(3):
        await db.save_strategy(
            {
                "id": f"strat-{i}",
                "user_id": "user-001",
                "name": f"Strategy {i}",
                "is_active": i == 0,  # Only first is active
            }
        )

    # Create 1 strategy for user-002
    await db.save_strategy(
        {
            "id": "strat-other",
            "user_id": "user-002",
            "name": "Other User Strategy",
        }
    )

    # Get all for user-001
    results = await db.get_user_strategies("user-001")
    assert len(results) == 3
    ids = {r["id"] for r in results}
    assert "strat-0" in ids
    assert "strat-1" in ids
    assert "strat-2" in ids
    assert "strat-other" not in ids


@pytest.mark.asyncio
async def test_get_user_strategies_active_only(db: Database):
    """get_user_strategies with active_only=True filters correctly."""
    await db.save_strategy(
        {
            "id": "strat-active",
            "user_id": "user-001",
            "name": "Active",
            "is_active": True,
        }
    )
    await db.save_strategy(
        {
            "id": "strat-inactive",
            "user_id": "user-001",
            "name": "Inactive",
            "is_active": False,
        }
    )

    results = await db.get_user_strategies("user-001", active_only=True)
    assert len(results) == 1
    assert results[0]["id"] == "strat-active"


@pytest.mark.asyncio
async def test_delete_strategy(db: Database):
    """delete_strategy deletes strategy + related trades + portfolios."""
    # Create strategy
    await db.save_strategy(
        {
            "id": "strat-del",
            "user_id": "user-001",
            "name": "Delete Me",
        }
    )

    # Create related trade
    await db.save_strategy_trade(
        {
            "id": "trade-del",
            "strategy_id": "strat-del",
            "ticker": "AAPL",
            "stance": "bullish",
            "entry_price": 150.0,
        }
    )

    # Create related portfolio
    await db.save_strategy_portfolio(
        {
            "strategy_id": "strat-del",
            "user_id": "user-001",
            "balance": 10000.0,
        }
    )

    # Delete
    deleted = await db.delete_strategy("strat-del", "user-001")
    assert deleted is True

    # Verify strategy deleted
    assert await db.get_strategy("strat-del") is None

    # Verify trades deleted
    trades = await db.get_strategy_trades("strat-del")
    assert len(trades) == 0

    # Verify portfolio deleted
    portfolio = await db.get_strategy_portfolio("strat-del", "user-001")
    assert portfolio is None


@pytest.mark.asyncio
async def test_delete_strategy_wrong_user(db: Database):
    """delete_strategy returns False if wrong user."""
    await db.save_strategy(
        {
            "id": "strat-protected",
            "user_id": "user-001",
            "name": "Protected",
        }
    )

    # Try to delete with wrong user
    deleted = await db.delete_strategy("strat-protected", "user-002")
    assert deleted is False

    # Verify still exists
    result = await db.get_strategy("strat-protected")
    assert result is not None


@pytest.mark.asyncio
async def test_delete_strategy_nonexistent(db: Database):
    """delete_strategy returns False for nonexistent strategy."""
    deleted = await db.delete_strategy("nonexistent", "user-001")
    assert deleted is False


@pytest.mark.asyncio
async def test_update_strategy_health(db: Database):
    """update_strategy_health updates health_score and is_active."""
    await db.save_strategy(
        {
            "id": "strat-health",
            "user_id": "user-001",
            "name": "Health Test",
            "health_score": 1.0,
            "is_active": True,
        }
    )

    # Update health
    await db.update_strategy_health("strat-health", health_score=0.3, is_active=False)

    result = await db.get_strategy("strat-health")
    assert result["health_score"] == 0.3
    assert result["is_active"] is False


@pytest.mark.asyncio
async def test_update_strategy_performance(db: Database):
    """update_strategy_performance updates performance JSON."""
    await db.save_strategy(
        {
            "id": "strat-perf",
            "user_id": "user-001",
            "name": "Perf Test",
            "performance": {"win_rate": 0.5},
        }
    )

    # Update performance
    new_perf = {
        "win_rate": 0.75,
        "total_trades": 200,
        "sharpe_ratio": 1.5,
    }
    await db.update_strategy_performance("strat-perf", new_perf)

    result = await db.get_strategy("strat-perf")
    assert result["performance"]["win_rate"] == 0.75
    assert result["performance"]["total_trades"] == 200
    assert result["performance"]["sharpe_ratio"] == 1.5


# ── Strategy Trades ──


@pytest.mark.asyncio
async def test_save_and_get_strategy_trade(db: Database):
    """save_strategy_trade + get_strategy_trades round-trip."""
    trade = {
        "id": "trade-001",
        "strategy_id": "strat-001",
        "signal_id": "sig-001",
        "ticker": "TSLA",
        "stance": "bullish",
        "entry_price": 200.0,
        "exit_price": 220.0,
        "pnl_pct": 10.0,
        "created_at": time.time(),
        "resolved_at": time.time(),
    }

    await db.save_strategy_trade(trade)

    trades = await db.get_strategy_trades("strat-001")
    assert len(trades) == 1
    assert trades[0]["id"] == "trade-001"
    assert trades[0]["ticker"] == "TSLA"
    assert trades[0]["stance"] == "bullish"
    assert trades[0]["entry_price"] == 200.0
    assert trades[0]["exit_price"] == 220.0
    assert trades[0]["pnl_pct"] == 10.0


@pytest.mark.asyncio
async def test_get_strategy_trades_open(db: Database):
    """get_strategy_trades with status='open' filters correctly."""
    await db.save_strategy_trade(
        {
            "id": "trade-open",
            "strategy_id": "strat-001",
            "ticker": "AAPL",
            "stance": "bullish",
            "entry_price": 150.0,
            "exit_price": None,
        }
    )
    await db.save_strategy_trade(
        {
            "id": "trade-closed",
            "strategy_id": "strat-001",
            "ticker": "MSFT",
            "stance": "bearish",
            "entry_price": 300.0,
            "exit_price": 290.0,
        }
    )

    open_trades = await db.get_strategy_trades("strat-001", status="open")
    assert len(open_trades) == 1
    assert open_trades[0]["id"] == "trade-open"


@pytest.mark.asyncio
async def test_get_strategy_trades_closed(db: Database):
    """get_strategy_trades with status='closed' filters correctly."""
    await db.save_strategy_trade(
        {
            "id": "trade-open",
            "strategy_id": "strat-001",
            "ticker": "AAPL",
            "stance": "bullish",
            "entry_price": 150.0,
            "exit_price": None,
        }
    )
    await db.save_strategy_trade(
        {
            "id": "trade-closed",
            "strategy_id": "strat-001",
            "ticker": "MSFT",
            "stance": "bearish",
            "entry_price": 300.0,
            "exit_price": 290.0,
        }
    )

    closed_trades = await db.get_strategy_trades("strat-001", status="closed")
    assert len(closed_trades) == 1
    assert closed_trades[0]["id"] == "trade-closed"


@pytest.mark.asyncio
async def test_get_strategy_trades_all(db: Database):
    """get_strategy_trades with status=None returns all trades."""
    await db.save_strategy_trade(
        {
            "id": "trade-open",
            "strategy_id": "strat-001",
            "ticker": "AAPL",
            "stance": "bullish",
            "entry_price": 150.0,
            "exit_price": None,
        }
    )
    await db.save_strategy_trade(
        {
            "id": "trade-closed",
            "strategy_id": "strat-001",
            "ticker": "MSFT",
            "stance": "bearish",
            "entry_price": 300.0,
            "exit_price": 290.0,
        }
    )

    all_trades = await db.get_strategy_trades("strat-001", status=None)
    assert len(all_trades) == 2


@pytest.mark.asyncio
async def test_get_strategy_trades_limit(db: Database):
    """get_strategy_trades respects limit parameter."""
    for i in range(5):
        await db.save_strategy_trade(
            {
                "id": f"trade-{i}",
                "strategy_id": "strat-001",
                "ticker": "AAPL",
                "stance": "bullish",
                "entry_price": 150.0,
            }
        )

    trades = await db.get_strategy_trades("strat-001", limit=3)
    assert len(trades) == 3


@pytest.mark.asyncio
async def test_resolve_strategy_trade(db: Database):
    """resolve_strategy_trade sets exit_price, pnl_pct, resolved_at."""
    await db.save_strategy_trade(
        {
            "id": "trade-resolve",
            "strategy_id": "strat-001",
            "ticker": "NVDA",
            "stance": "bullish",
            "entry_price": 400.0,
            "exit_price": None,
            "pnl_pct": None,
            "resolved_at": None,
        }
    )

    # Resolve trade
    await db.resolve_strategy_trade("trade-resolve", exit_price=440.0, pnl_pct=10.0)

    trades = await db.get_strategy_trades("strat-001")
    assert len(trades) == 1
    assert trades[0]["exit_price"] == 440.0
    assert trades[0]["pnl_pct"] == 10.0
    assert trades[0]["resolved_at"] is not None
    assert trades[0]["resolved_at"] > 0


# ── Strategy Portfolios ──


@pytest.mark.asyncio
async def test_save_and_get_strategy_portfolio(db: Database):
    """save_strategy_portfolio + get_strategy_portfolio round-trip."""
    portfolio = {
        "strategy_id": "strat-001",
        "user_id": "user-001",
        "balance": 12500.0,
        "total_trades": 50,
        "winning_trades": 35,
        "total_pnl": 2500.0,
    }

    await db.save_strategy_portfolio(portfolio)

    result = await db.get_strategy_portfolio("strat-001", "user-001")
    assert result is not None
    assert result["balance"] == 12500.0
    assert result["total_trades"] == 50
    assert result["winning_trades"] == 35
    assert result["total_pnl"] == 2500.0


@pytest.mark.asyncio
async def test_save_strategy_portfolio_defaults(db: Database):
    """save_strategy_portfolio with minimal fields uses defaults."""
    portfolio = {
        "strategy_id": "strat-002",
        "user_id": "user-002",
    }

    await db.save_strategy_portfolio(portfolio)

    result = await db.get_strategy_portfolio("strat-002", "user-002")
    assert result is not None
    assert result["balance"] == 10000.0
    assert result["total_trades"] == 0
    assert result["winning_trades"] == 0
    assert result["total_pnl"] == 0.0


@pytest.mark.asyncio
async def test_get_strategy_portfolio_nonexistent(db: Database):
    """get_strategy_portfolio returns None for nonexistent portfolio."""
    result = await db.get_strategy_portfolio("nonexistent", "user-001")
    assert result is None


# ── Marketplace ──


@pytest.mark.asyncio
async def test_save_and_get_marketplace_entry(db: Database):
    """save_marketplace_entry + get_marketplace_entry round-trip."""
    entry = {
        "id": "market-001",
        "strategy_id": "strat-001",
        "author_id": "user-001",
        "name": "Momentum Strategy",
        "description": "A high-performance momentum strategy",
        "performance": {
            "win_rate": 0.72,
            "sharpe_ratio": 1.8,
            "total_return": 0.45,
        },
        "subscriber_count": 150,
        "rating": 4.5,
        "created_at": time.time(),
    }

    await db.save_marketplace_entry(entry)

    result = await db.get_marketplace_entry("market-001")
    assert result is not None
    assert result["id"] == "market-001"
    assert result["strategy_id"] == "strat-001"
    assert result["author_id"] == "user-001"
    assert result["name"] == "Momentum Strategy"
    assert result["description"] == "A high-performance momentum strategy"
    assert isinstance(result["performance"], dict)
    assert result["performance"]["win_rate"] == 0.72
    assert result["subscriber_count"] == 150
    assert result["rating"] == 4.5


@pytest.mark.asyncio
async def test_get_marketplace_entries_by_rating(db: Database):
    """get_marketplace_entries with sort_by='rating' orders correctly."""
    # Create entries with different ratings
    for i, rating in enumerate([4.5, 3.2, 4.9, 3.8]):
        await db.save_marketplace_entry(
            {
                "id": f"market-{i}",
                "strategy_id": f"strat-{i}",
                "author_id": "user-001",
                "name": f"Strategy {i}",
                "rating": rating,
            }
        )

    results = await db.get_marketplace_entries(sort_by="rating", limit=10)
    assert len(results) == 4
    # Should be sorted by rating DESC
    assert results[0]["rating"] == 4.9
    assert results[1]["rating"] == 4.5
    assert results[2]["rating"] == 3.8
    assert results[3]["rating"] == 3.2


@pytest.mark.asyncio
async def test_get_marketplace_entries_by_subscribers(db: Database):
    """get_marketplace_entries with sort_by='subscribers' orders correctly."""
    for i, subs in enumerate([100, 500, 250, 1000]):
        await db.save_marketplace_entry(
            {
                "id": f"market-{i}",
                "strategy_id": f"strat-{i}",
                "author_id": "user-001",
                "name": f"Strategy {i}",
                "subscriber_count": subs,
            }
        )

    results = await db.get_marketplace_entries(sort_by="subscribers", limit=10)
    assert len(results) == 4
    # Should be sorted by subscriber_count DESC
    assert results[0]["subscriber_count"] == 1000
    assert results[1]["subscriber_count"] == 500
    assert results[2]["subscriber_count"] == 250
    assert results[3]["subscriber_count"] == 100


@pytest.mark.asyncio
async def test_get_marketplace_entries_by_newest(db: Database):
    """get_marketplace_entries with sort_by='newest' orders correctly."""
    base_time = time.time()
    for i in range(4):
        await db.save_marketplace_entry(
            {
                "id": f"market-{i}",
                "strategy_id": f"strat-{i}",
                "author_id": "user-001",
                "name": f"Strategy {i}",
                "created_at": base_time + i,
            }
        )

    results = await db.get_marketplace_entries(sort_by="newest", limit=10)
    assert len(results) == 4
    # Should be sorted by created_at DESC (newest first)
    assert results[0]["id"] == "market-3"
    assert results[1]["id"] == "market-2"
    assert results[2]["id"] == "market-1"
    assert results[3]["id"] == "market-0"


@pytest.mark.asyncio
async def test_get_marketplace_entries_pagination(db: Database):
    """get_marketplace_entries respects limit and offset."""
    for i in range(10):
        await db.save_marketplace_entry(
            {
                "id": f"market-{i}",
                "strategy_id": f"strat-{i}",
                "author_id": "user-001",
                "name": f"Strategy {i}",
                "rating": float(i),
            }
        )

    # Get first page
    page1 = await db.get_marketplace_entries(sort_by="rating", limit=3, offset=0)
    assert len(page1) == 3
    assert page1[0]["rating"] == 9.0

    # Get second page
    page2 = await db.get_marketplace_entries(sort_by="rating", limit=3, offset=3)
    assert len(page2) == 3
    assert page2[0]["rating"] == 6.0


@pytest.mark.asyncio
async def test_delete_marketplace_entry(db: Database):
    """delete_marketplace_entry deletes entry if author matches."""
    await db.save_marketplace_entry(
        {
            "id": "market-del",
            "strategy_id": "strat-001",
            "author_id": "user-001",
            "name": "Delete Me",
        }
    )

    # Delete as author
    deleted = await db.delete_marketplace_entry("market-del", "user-001")
    assert deleted is True

    # Verify deleted
    result = await db.get_marketplace_entry("market-del")
    assert result is None


@pytest.mark.asyncio
async def test_delete_marketplace_entry_wrong_author(db: Database):
    """delete_marketplace_entry returns False if wrong author."""
    await db.save_marketplace_entry(
        {
            "id": "market-protected",
            "strategy_id": "strat-001",
            "author_id": "user-001",
            "name": "Protected",
        }
    )

    # Try to delete with wrong author
    deleted = await db.delete_marketplace_entry("market-protected", "user-002")
    assert deleted is False

    # Verify still exists
    result = await db.get_marketplace_entry("market-protected")
    assert result is not None


@pytest.mark.asyncio
async def test_delete_marketplace_entry_nonexistent(db: Database):
    """delete_marketplace_entry returns False for nonexistent entry."""
    deleted = await db.delete_marketplace_entry("nonexistent", "user-001")
    assert deleted is False


# ── Market Regimes ──


@pytest.mark.asyncio
async def test_save_and_get_market_regime(db: Database):
    """save_market_regime + get_market_regimes round-trip."""
    regime = {
        "id": "regime-001",
        "regime_type": "bull_run",
        "start_ts": time.time() - 86400,  # 1 day ago
        "end_ts": None,
        "indicators": {
            "vix": 15.2,
            "spy_sma_50": 450.0,
            "spy_sma_200": 430.0,
        },
        "confidence": 0.85,
        "detected_at": time.time(),
    }

    await db.save_market_regime(regime)

    results = await db.get_market_regimes(days=7)
    assert len(results) >= 1
    found = next((r for r in results if r["id"] == "regime-001"), None)
    assert found is not None
    assert found["regime_type"] == "bull_run"
    assert found["end_ts"] is None
    assert isinstance(found["indicators"], dict)
    assert found["indicators"]["vix"] == 15.2
    assert found["confidence"] == 0.85


@pytest.mark.asyncio
async def test_get_market_regimes_days_filter(db: Database):
    """get_market_regimes filters by days parameter."""
    now = time.time()

    # Create regime 5 days ago
    await db.save_market_regime(
        {
            "id": "regime-old",
            "regime_type": "bear_market",
            "start_ts": now - (5 * 86400),
            "detected_at": now - (5 * 86400),
        }
    )

    # Create regime 1 day ago
    await db.save_market_regime(
        {
            "id": "regime-recent",
            "regime_type": "bull_run",
            "start_ts": now - 86400,
            "detected_at": now - 86400,
        }
    )

    # Query last 2 days
    results = await db.get_market_regimes(days=2)
    ids = {r["id"] for r in results}
    assert "regime-recent" in ids
    assert "regime-old" not in ids


@pytest.mark.asyncio
async def test_get_market_regimes_type_filter(db: Database):
    """get_market_regimes filters by regime_type."""
    now = time.time()

    await db.save_market_regime(
        {
            "id": "regime-bull",
            "regime_type": "bull_run",
            "start_ts": now - 86400,
            "detected_at": now,
        }
    )
    await db.save_market_regime(
        {
            "id": "regime-bear",
            "regime_type": "bear_market",
            "start_ts": now - 86400,
            "detected_at": now,
        }
    )

    results = await db.get_market_regimes(days=7, regime_type="bull_run")
    assert len(results) == 1
    assert results[0]["id"] == "regime-bull"


# ── Strategy Discoveries ──


@pytest.mark.asyncio
async def test_save_and_get_discovery_result(db: Database):
    """save_discovery_result + get_discovery_results round-trip."""
    discovery = {
        "id": "disc-001",
        "user_id": "user-001",
        "search_config": {
            "population_size": 100,
            "generations": 50,
            "min_win_rate": 0.6,
        },
        "best_strategies": [
            {"rules": [{"type": "confidence", "operator": ">", "value": 0.7}]},
            {"rules": [{"type": "stance", "operator": "=", "value": "bullish"}]},
        ],
        "strategies_found": 2,
        "elapsed_s": 45.3,
        "created_at": time.time(),
    }

    await db.save_discovery_result(discovery)

    results = await db.get_discovery_results("user-001", limit=10)
    assert len(results) >= 1
    found = next((r for r in results if r["id"] == "disc-001"), None)
    assert found is not None
    assert isinstance(found["search_config"], dict)
    assert found["search_config"]["population_size"] == 100
    assert isinstance(found["best_strategies"], list)
    assert len(found["best_strategies"]) == 2
    assert found["strategies_found"] == 2
    assert found["elapsed_s"] == 45.3


@pytest.mark.asyncio
async def test_get_discovery_results_limit(db: Database):
    """get_discovery_results respects limit parameter."""
    for i in range(5):
        await db.save_discovery_result(
            {
                "id": f"disc-{i}",
                "user_id": "user-001",
                "search_config": {},
                "best_strategies": [],
                "created_at": time.time() + i,
            }
        )

    results = await db.get_discovery_results("user-001", limit=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_get_discovery_results_user_filter(db: Database):
    """get_discovery_results filters by user_id."""
    await db.save_discovery_result(
        {
            "id": "disc-user1",
            "user_id": "user-001",
            "search_config": {},
            "best_strategies": [],
        }
    )
    await db.save_discovery_result(
        {
            "id": "disc-user2",
            "user_id": "user-002",
            "search_config": {},
            "best_strategies": [],
        }
    )

    results = await db.get_discovery_results("user-001", limit=10)
    ids = {r["id"] for r in results}
    assert "disc-user1" in ids
    assert "disc-user2" not in ids


# ── Purge ──


@pytest.mark.asyncio
async def test_purge_old_strategy_data_trades(db: Database):
    """purge_old_strategy_data removes old resolved trades."""
    now = time.time()

    # Create old resolved trade (100 days ago)
    await db.save_strategy_trade(
        {
            "id": "trade-old",
            "strategy_id": "strat-001",
            "ticker": "AAPL",
            "stance": "bullish",
            "entry_price": 150.0,
            "exit_price": 160.0,
            "resolved_at": now - (100 * 86400),
        }
    )

    # Create recent resolved trade (10 days ago)
    await db.save_strategy_trade(
        {
            "id": "trade-recent",
            "strategy_id": "strat-001",
            "ticker": "MSFT",
            "stance": "bearish",
            "entry_price": 300.0,
            "exit_price": 290.0,
            "resolved_at": now - (10 * 86400),
        }
    )

    # Create open trade (no resolved_at)
    await db.save_strategy_trade(
        {
            "id": "trade-open",
            "strategy_id": "strat-001",
            "ticker": "NVDA",
            "stance": "bullish",
            "entry_price": 400.0,
            "resolved_at": None,
        }
    )

    # Purge data older than 30 days
    deleted = await db.purge_old_strategy_data(keep_days=30)
    assert deleted >= 1  # At least the old trade

    # Verify old trade deleted
    trades = await db.get_strategy_trades("strat-001", limit=100)
    ids = {t["id"] for t in trades}
    assert "trade-old" not in ids
    assert "trade-recent" in ids
    assert "trade-open" in ids


@pytest.mark.asyncio
async def test_purge_old_strategy_data_discoveries(db: Database):
    """purge_old_strategy_data removes old discovery runs."""
    now = time.time()

    # Create old discovery (100 days ago)
    await db.save_discovery_result(
        {
            "id": "disc-old",
            "user_id": "user-001",
            "search_config": {},
            "best_strategies": [],
            "created_at": now - (100 * 86400),
        }
    )

    # Create recent discovery (10 days ago)
    await db.save_discovery_result(
        {
            "id": "disc-recent",
            "user_id": "user-001",
            "search_config": {},
            "best_strategies": [],
            "created_at": now - (10 * 86400),
        }
    )

    # Purge data older than 30 days
    deleted = await db.purge_old_strategy_data(keep_days=30)
    assert deleted >= 1

    # Verify old discovery deleted
    results = await db.get_discovery_results("user-001", limit=100)
    ids = {r["id"] for r in results}
    assert "disc-old" not in ids
    assert "disc-recent" in ids


@pytest.mark.asyncio
async def test_purge_old_strategy_data_regimes(db: Database):
    """purge_old_strategy_data removes old market regimes."""
    now = time.time()

    # Create old regime (100 days ago)
    await db.save_market_regime(
        {
            "id": "regime-old",
            "regime_type": "bear_market",
            "start_ts": now - (100 * 86400),
            "detected_at": now - (100 * 86400),
        }
    )

    # Create recent regime (10 days ago)
    await db.save_market_regime(
        {
            "id": "regime-recent",
            "regime_type": "bull_run",
            "start_ts": now - (10 * 86400),
            "detected_at": now - (10 * 86400),
        }
    )

    # Purge data older than 30 days
    deleted = await db.purge_old_strategy_data(keep_days=30)
    assert deleted >= 1

    # Verify old regime deleted
    results = await db.get_market_regimes(days=365)
    ids = {r["id"] for r in results}
    assert "regime-old" not in ids
    assert "regime-recent" in ids


@pytest.mark.asyncio
async def test_purge_old_strategy_data_returns_total(db: Database):
    """purge_old_strategy_data returns total count of deleted rows."""
    now = time.time()
    cutoff = now - (100 * 86400)

    # Create 2 old trades
    await db.save_strategy_trade(
        {
            "id": "trade-1",
            "strategy_id": "strat-001",
            "ticker": "AAPL",
            "stance": "bullish",
            "entry_price": 150.0,
            "exit_price": 160.0,
            "resolved_at": cutoff,
        }
    )
    await db.save_strategy_trade(
        {
            "id": "trade-2",
            "strategy_id": "strat-001",
            "ticker": "MSFT",
            "stance": "bearish",
            "entry_price": 300.0,
            "exit_price": 290.0,
            "resolved_at": cutoff,
        }
    )

    # Create 1 old discovery
    await db.save_discovery_result(
        {
            "id": "disc-old",
            "user_id": "user-001",
            "search_config": {},
            "best_strategies": [],
            "created_at": cutoff,
        }
    )

    # Create 1 old regime
    await db.save_market_regime(
        {
            "id": "regime-old",
            "regime_type": "bear_market",
            "start_ts": cutoff,
            "detected_at": cutoff,
        }
    )

    # Purge all old data
    deleted = await db.purge_old_strategy_data(keep_days=30)
    assert deleted == 4  # 2 trades + 1 discovery + 1 regime


# ── Schema ──


@pytest.mark.asyncio
async def test_schema_tables_exist(db: Database):
    """All strategy-related tables are created."""
    # Query sqlite_master for table names
    async with db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) as cur:
        rows = await cur.fetchall()
        table_names = {row[0] for row in rows}

    # Verify all strategy tables exist
    assert "strategies" in table_names
    assert "strategy_trades" in table_names
    assert "strategy_portfolios" in table_names
    assert "strategy_marketplace" in table_names
    assert "market_regimes" in table_names
    assert "strategy_discoveries" in table_names
