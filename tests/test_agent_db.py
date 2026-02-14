from __future__ import annotations

import pytest
import time
from rot.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    """Create a test database with schema initialized."""
    database = Database(db_path=str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def test_user(db):
    """Create a test user for agent tests."""
    user_id = "test_user_123"
    await db.db.execute(
        """INSERT INTO users (id, email, password_hash, tier, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, "test@example.com", "hashed_pw", "pro", time.time()),
    )
    await db.db.commit()
    return user_id


@pytest.fixture
async def test_signal(db):
    """Create a test signal for agent trades."""
    signal_id = await db.insert_signal({
        "run_id": "run_test",
        "event": {
            "entities": ["TSLA"],
            "stance": "bullish",
            "confidence": 0.7,
            "evidence": [{"subreddit": "wsb", "excerpt": "TSLA calls"}],
            "meta": {},
        },
        "trade_idea": {"strategy": "debit_spread"},
    })
    return signal_id


# ── Agent CRUD Tests ──


async def test_create_agent_and_get(db, test_user):
    """Test creating an agent and retrieving it."""
    agent_id = await db.create_agent(
        user_id=test_user,
        name="My First Bot",
        agent_type="momentum",
        min_confidence=0.5,
        max_daily_trades=10,
    )
    assert agent_id

    agent = await db.get_agent(agent_id)
    assert agent is not None
    assert agent["id"] == agent_id
    assert agent["user_id"] == test_user
    assert agent["name"] == "My First Bot"
    assert agent["agent_type"] == "momentum"
    assert agent["status"] == "active"
    assert agent["min_confidence"] == 0.5
    assert agent["max_daily_trades"] == 10


async def test_get_agents_for_user(db, test_user):
    """Test getting all agents for a user."""
    # Create 3 agents
    agent1 = await db.create_agent(test_user, "Bot 1", "momentum")
    agent2 = await db.create_agent(test_user, "Bot 2", "reversal")
    agent3 = await db.create_agent(test_user, "Bot 3", "mean_reversion")

    agents = await db.get_agents_for_user(test_user)
    assert len(agents) == 3
    agent_ids = [a["id"] for a in agents]
    assert agent1 in agent_ids
    assert agent2 in agent_ids
    assert agent3 in agent_ids


async def test_get_active_agents_filters_correctly(db, test_user):
    """Test that get_active_agents only returns active agents."""
    agent1 = await db.create_agent(test_user, "Active Bot", "momentum")
    agent2 = await db.create_agent(test_user, "Paused Bot", "reversal")

    # Pause one agent
    await db.update_agent_status(agent2, "paused")

    active = await db.get_active_agents()
    assert len(active) == 1
    assert active[0]["id"] == agent1
    assert active[0]["status"] == "active"


async def test_update_agent_fields(db, test_user):
    """Test updating multiple agent fields."""
    agent_id = await db.create_agent(
        test_user, "Test Bot", "momentum",
        min_confidence=0.4, max_daily_trades=5
    )

    # Update multiple fields
    success = await db.update_agent(
        agent_id,
        name="Updated Bot Name",
        min_confidence=0.6,
        max_position_dollars=3000.0,
    )
    assert success is True

    agent = await db.get_agent(agent_id)
    assert agent["name"] == "Updated Bot Name"
    assert agent["min_confidence"] == 0.6
    assert agent["max_position_dollars"] == 3000.0
    assert agent["max_daily_trades"] == 5  # unchanged


async def test_update_agent_status(db, test_user):
    """Test updating agent status (pause/resume)."""
    agent_id = await db.create_agent(test_user, "Test Bot", "momentum")

    # Pause
    await db.update_agent_status(agent_id, "paused")
    agent = await db.get_agent(agent_id)
    assert agent["status"] == "paused"

    # Resume
    await db.update_agent_status(agent_id, "active")
    agent = await db.get_agent(agent_id)
    assert agent["status"] == "active"


async def test_delete_agent(db, test_user):
    """Test deleting an agent removes it from database."""
    agent_id = await db.create_agent(test_user, "Doomed Bot", "momentum")

    # Verify it exists
    agent = await db.get_agent(agent_id)
    assert agent is not None

    # Delete
    success = await db.delete_agent(agent_id)
    assert success is True

    # Verify it's gone
    agent = await db.get_agent(agent_id)
    assert agent is None


async def test_delete_agent_with_trades_cascades(db, test_user, test_signal):
    """Test that deleting an agent also deletes its trades."""
    agent_id = await db.create_agent(test_user, "Trading Bot", "momentum")

    # Create some trades
    trade1 = await db.insert_agent_trade(
        agent_id, test_user, test_signal, "TSLA", "bullish", 250.0, 10, 2500.0
    )
    trade2 = await db.insert_agent_trade(
        agent_id, test_user, test_signal, "AAPL", "bearish", 180.0, 5, 900.0
    )

    # Verify trades exist
    trades = await db.get_agent_trades(agent_id)
    assert len(trades) == 2

    # Delete agent
    await db.delete_agent(agent_id)

    # Verify trades are gone
    trades = await db.get_agent_trades(agent_id)
    assert len(trades) == 0


async def test_count_user_agents(db, test_user):
    """Test counting agents for a user."""
    assert await db.count_user_agents(test_user) == 0

    await db.create_agent(test_user, "Bot 1", "momentum")
    assert await db.count_user_agents(test_user) == 1

    await db.create_agent(test_user, "Bot 2", "reversal")
    assert await db.count_user_agents(test_user) == 2


async def test_create_multiple_agents_for_same_user(db, test_user):
    """Test that one user can have multiple agents."""
    agent1 = await db.create_agent(test_user, "Conservative", "mean_reversion",
                                     min_confidence=0.7, max_daily_trades=3)
    agent2 = await db.create_agent(test_user, "Aggressive", "momentum",
                                     min_confidence=0.4, max_daily_trades=15)

    agents = await db.get_agents_for_user(test_user)
    assert len(agents) == 2

    # Verify they have different configs
    a1 = [a for a in agents if a["id"] == agent1][0]
    a2 = [a for a in agents if a["id"] == agent2][0]

    assert a1["min_confidence"] == 0.7
    assert a2["min_confidence"] == 0.4
    assert a1["max_daily_trades"] == 3
    assert a2["max_daily_trades"] == 15


# ── Agent Trade Tests ──


async def test_insert_agent_trade_and_retrieve(db, test_user, test_signal):
    """Test inserting an agent trade and retrieving it."""
    agent_id = await db.create_agent(test_user, "Test Bot", "momentum")

    trade_id = await db.insert_agent_trade(
        agent_id=agent_id,
        user_id=test_user,
        signal_id=test_signal,
        ticker="TSLA",
        stance="bullish",
        entry_price=250.0,
        quantity=10,
        dollars=2500.0,
    )
    assert trade_id

    trades = await db.get_agent_trades(agent_id)
    assert len(trades) == 1

    trade = trades[0]
    assert trade["id"] == trade_id
    assert trade["agent_id"] == agent_id
    assert trade["user_id"] == test_user
    assert trade["signal_id"] == test_signal
    assert trade["ticker"] == "TSLA"
    assert trade["stance"] == "bullish"
    assert trade["entry_price"] == 250.0
    assert trade["quantity"] == 10
    assert trade["dollars"] == 2500.0
    assert trade["status"] == "open"


async def test_close_agent_trade_with_pnl(db, test_user, test_signal):
    """Test closing an open trade with P&L."""
    agent_id = await db.create_agent(test_user, "Test Bot", "momentum")

    trade_id = await db.insert_agent_trade(
        agent_id, test_user, test_signal, "TSLA", "bullish", 250.0, 10, 2500.0
    )

    # Close with profit
    success = await db.close_agent_trade(
        trade_id, exit_price=270.0, pnl_dollars=200.0, pnl_pct=8.0
    )
    assert success is True

    trades = await db.get_agent_trades(agent_id)
    trade = trades[0]

    assert trade["status"] == "closed"
    assert trade["exit_price"] == 270.0
    assert trade["pnl_dollars"] == 200.0
    assert trade["pnl_pct"] == 8.0
    assert trade["closed_at"] is not None


async def test_get_agent_trades_respects_limit(db, test_user, test_signal):
    """Test that get_agent_trades respects limit parameter."""
    agent_id = await db.create_agent(test_user, "Test Bot", "momentum")

    # Create 10 trades
    for i in range(10):
        await db.insert_agent_trade(
            agent_id, test_user, test_signal, "TSLA", "bullish",
            250.0 + i, 10, 2500.0
        )

    # Get only 5
    trades = await db.get_agent_trades(agent_id, limit=5)
    assert len(trades) == 5

    # Get all
    trades = await db.get_agent_trades(agent_id, limit=50)
    assert len(trades) == 10


async def test_get_agent_trades_today_counts_correctly(db, test_user, test_signal):
    """Test that get_agent_trades_today counts only recent trades."""
    agent_id = await db.create_agent(test_user, "Test Bot", "momentum")

    # Create 3 trades now
    for i in range(3):
        await db.insert_agent_trade(
            agent_id, test_user, test_signal, "TSLA", "bullish",
            250.0, 10, 2500.0
        )

    count = await db.get_agent_trades_today(agent_id)
    assert count == 3

    # Manually insert an old trade (> 24h ago)
    old_timestamp = time.time() - 90000  # ~25 hours ago
    await db.db.execute(
        """INSERT INTO agent_trades
           (id, agent_id, user_id, signal_id, ticker, stance, entry_price,
            quantity, dollars, created_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("old_trade", agent_id, test_user, test_signal, "AAPL", "bearish",
         180.0, 5, 900.0, old_timestamp, "open"),
    )
    await db.db.commit()

    # Should still count only 3 recent trades
    count = await db.get_agent_trades_today(agent_id)
    assert count == 3


async def test_get_agent_performance_computes_wins_losses(db, test_user, test_signal):
    """Test that get_agent_performance computes correct metrics."""
    agent_id = await db.create_agent(test_user, "Test Bot", "momentum")

    # Create and close 3 winning trades
    for i in range(3):
        trade_id = await db.insert_agent_trade(
            agent_id, test_user, test_signal, "TSLA", "bullish",
            250.0, 10, 2500.0
        )
        await db.close_agent_trade(trade_id, 270.0, 200.0, 8.0)

    # Create and close 2 losing trades
    for i in range(2):
        trade_id = await db.insert_agent_trade(
            agent_id, test_user, test_signal, "AAPL", "bearish",
            180.0, 5, 900.0
        )
        await db.close_agent_trade(trade_id, 185.0, -25.0, -2.8)

    perf = await db.get_agent_performance(agent_id)

    assert perf["total_trades"] == 5
    assert perf["winning_trades"] == 3
    assert perf["win_rate"] == 0.6  # 3/5
    assert abs(perf["total_pnl"] - 550.0) < 0.01  # 3*200 - 2*25
    assert abs(perf["avg_trade_pnl"] - 110.0) < 0.01  # 550/5


async def test_get_agent_performance_with_no_trades(db, test_user):
    """Test agent performance with no trades returns zero metrics."""
    agent_id = await db.create_agent(test_user, "New Bot", "momentum")

    perf = await db.get_agent_performance(agent_id)

    assert perf["total_trades"] == 0
    assert perf["winning_trades"] == 0
    assert perf["win_rate"] == 0.0
    assert perf["total_pnl"] == 0.0
    assert perf["avg_trade_pnl"] == 0.0
    assert perf["trades_today"] == 0


async def test_get_open_agent_trades(db, test_user, test_signal):
    """Test getting only open trades for an agent."""
    agent_id = await db.create_agent(test_user, "Test Bot", "momentum")

    # Create 3 trades
    trade1 = await db.insert_agent_trade(
        agent_id, test_user, test_signal, "TSLA", "bullish", 250.0, 10, 2500.0
    )
    trade2 = await db.insert_agent_trade(
        agent_id, test_user, test_signal, "AAPL", "bearish", 180.0, 5, 900.0
    )
    trade3 = await db.insert_agent_trade(
        agent_id, test_user, test_signal, "NVDA", "bullish", 450.0, 2, 900.0
    )

    # Close one
    await db.close_agent_trade(trade2, 175.0, 25.0, 2.8)

    # Get open trades
    open_trades = await db.get_open_agent_trades(agent_id)
    assert len(open_trades) == 2

    trade_ids = [t["id"] for t in open_trades]
    assert trade1 in trade_ids
    assert trade3 in trade_ids
    assert trade2 not in trade_ids


async def test_get_agent_total_exposure(db, test_user, test_signal):
    """Test calculating total dollar exposure for open trades."""
    agent_id = await db.create_agent(test_user, "Test Bot", "momentum")

    # Create 3 trades with different dollar amounts
    trade1 = await db.insert_agent_trade(
        agent_id, test_user, test_signal, "TSLA", "bullish", 250.0, 10, 2500.0
    )
    trade2 = await db.insert_agent_trade(
        agent_id, test_user, test_signal, "AAPL", "bearish", 180.0, 5, 900.0
    )
    trade3 = await db.insert_agent_trade(
        agent_id, test_user, test_signal, "NVDA", "bullish", 450.0, 4, 1800.0
    )

    # Total exposure should be sum of all open trades
    exposure = await db.get_agent_total_exposure(agent_id)
    assert abs(exposure - 5200.0) < 0.01  # 2500 + 900 + 1800

    # Close one trade
    await db.close_agent_trade(trade1, 270.0, 200.0, 8.0)

    # Exposure should decrease
    exposure = await db.get_agent_total_exposure(agent_id)
    assert abs(exposure - 2700.0) < 0.01  # 900 + 1800


async def test_check_agent_signal_dedup_no_dup(db, test_user, test_signal):
    """Test signal dedup check when no duplicate exists."""
    agent_id = await db.create_agent(test_user, "Test Bot", "momentum")

    # No trade yet
    has_dup = await db.check_agent_signal_dedup(agent_id, test_signal)
    assert has_dup is False


async def test_check_agent_signal_dedup_yes_dup(db, test_user, test_signal):
    """Test signal dedup check when duplicate exists."""
    agent_id = await db.create_agent(test_user, "Test Bot", "momentum")

    # Create a trade with this signal
    await db.insert_agent_trade(
        agent_id, test_user, test_signal, "TSLA", "bullish", 250.0, 10, 2500.0
    )

    # Should detect duplicate
    has_dup = await db.check_agent_signal_dedup(agent_id, test_signal)
    assert has_dup is True


async def test_agent_signal_dedup_per_agent(db, test_user, test_signal):
    """Test that signal dedup is per-agent (different agents can trade same signal)."""
    agent1 = await db.create_agent(test_user, "Bot 1", "momentum")
    agent2 = await db.create_agent(test_user, "Bot 2", "reversal")

    # Agent 1 trades the signal
    await db.insert_agent_trade(
        agent1, test_user, test_signal, "TSLA", "bullish", 250.0, 10, 2500.0
    )

    # Agent 1 has dup
    assert await db.check_agent_signal_dedup(agent1, test_signal) is True

    # Agent 2 does not have dup (hasn't traded it yet)
    assert await db.check_agent_signal_dedup(agent2, test_signal) is False

    # Agent 2 can trade it
    await db.insert_agent_trade(
        agent2, test_user, test_signal, "TSLA", "bearish", 260.0, 5, 1300.0
    )

    # Now agent 2 also has dup
    assert await db.check_agent_signal_dedup(agent2, test_signal) is True
