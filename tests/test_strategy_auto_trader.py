"""Tests for the AutoPaperTrader — automated paper-trading engine."""

from __future__ import annotations

import pytest

from rot.strategy.auto_trader import AutoPaperTrader
from rot.strategy.types import Strategy, StrategyResult, StrategyRule


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def strategy_bullish_high_conf() -> Strategy:
    """A bullish strategy that requires confidence >= 0.6."""
    return Strategy(
        id="strat-bullish-1",
        user_id="user-1",
        name="Bullish High Confidence",
        rules=[
            StrategyRule(field="stance", operator="eq", value="bullish"),
            StrategyRule(field="confidence", operator="gte", value=0.6),
        ],
        config={
            "stop_loss_pct": 10.0,
            "take_profit_pct": 20.0,
        },
        is_active=True,
    )


@pytest.fixture
def strategy_bearish_earnings() -> Strategy:
    """A bearish strategy that targets earnings_rumor events."""
    return Strategy(
        id="strat-bearish-1",
        user_id="user-1",
        name="Bearish Earnings",
        rules=[
            StrategyRule(field="stance", operator="eq", value="bearish"),
            StrategyRule(
                field="event_type",
                operator="in",
                value=["earnings_rumor", "product_news"],
            ),
        ],
        config={
            "stop_loss_pct": 8.0,
            "take_profit_pct": 15.0,
            "max_concurrent": 5,
        },
        is_active=True,
    )


@pytest.fixture
def strategy_inactive() -> Strategy:
    """An inactive strategy that should not be loaded."""
    return Strategy(
        id="strat-inactive-1",
        user_id="user-1",
        name="Inactive Strategy",
        rules=[
            StrategyRule(field="confidence", operator="gte", value=0.5),
        ],
        config={},
        is_active=False,
    )


@pytest.fixture
def signal_bullish_tsla() -> dict:
    """A bullish signal for TSLA with 0.7 confidence."""
    return {
        "id": "signal-1",
        "ticker": "TSLA",
        "stance": "bullish",
        "confidence": 0.7,
        "event_type": "squeeze_chatter",
        "price_at_signal": 250.0,
    }


@pytest.fixture
def signal_bearish_aapl() -> dict:
    """A bearish earnings signal for AAPL."""
    return {
        "id": "signal-2",
        "ticker": "AAPL",
        "stance": "bearish",
        "confidence": 0.5,
        "event_type": "earnings_rumor",
        "price_at_signal": 195.0,
    }


@pytest.fixture
def signal_mixed_nvda() -> dict:
    """A mixed stance signal (should be skipped)."""
    return {
        "id": "signal-3",
        "ticker": "NVDA",
        "stance": "mixed",
        "confidence": 0.8,
        "event_type": "product_news",
        "price_at_signal": 880.0,
    }


@pytest.fixture
def signal_unknown_stance() -> dict:
    """An unknown stance signal (should be skipped)."""
    return {
        "id": "signal-4",
        "ticker": "MSFT",
        "stance": "unknown",
        "confidence": 0.6,
        "event_type": "regulatory",
        "price_at_signal": 420.0,
    }


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


def test_init_defaults():
    """AutoPaperTrader initializes with default settings."""
    trader = AutoPaperTrader()
    assert trader._max_concurrent == 10
    assert trader._default_position_size == 1000.0
    assert trader._active_strategies == {}
    assert trader._open_trades == {}
    assert trader._closed_trades == []


def test_init_custom_params():
    """AutoPaperTrader accepts custom max_concurrent and position_size."""
    trader = AutoPaperTrader(max_concurrent_per_strategy=5, default_position_size=5000.0)
    assert trader._max_concurrent == 5
    assert trader._default_position_size == 5000.0


def test_init_invalid_max_concurrent():
    """AutoPaperTrader raises ValueError for max_concurrent < 1."""
    with pytest.raises(ValueError, match="max_concurrent_per_strategy must be >= 1"):
        AutoPaperTrader(max_concurrent_per_strategy=0)


def test_init_invalid_position_size():
    """AutoPaperTrader raises ValueError for non-positive position_size."""
    with pytest.raises(ValueError, match="default_position_size must be positive"):
        AutoPaperTrader(default_position_size=-100)


# ---------------------------------------------------------------------------
# Strategy loading tests
# ---------------------------------------------------------------------------


def test_load_strategies_empty():
    """load_strategies handles empty list."""
    trader = AutoPaperTrader()
    trader.load_strategies([])
    assert len(trader._active_strategies) == 0


def test_load_strategies_active_only(
    strategy_bullish_high_conf, strategy_inactive
):
    """load_strategies only loads active strategies."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf, strategy_inactive])
    assert len(trader._active_strategies) == 1
    assert "strat-bullish-1" in trader._active_strategies
    assert "strat-inactive-1" not in trader._active_strategies


def test_load_strategies_compiles_rules(strategy_bullish_high_conf):
    """load_strategies pre-compiles strategy rules."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])
    assert "strat-bullish-1" in trader._compiled_rules
    assert len(trader._compiled_rules["strat-bullish-1"]) == 2


def test_load_strategies_replaces_existing(
    strategy_bullish_high_conf, strategy_bearish_earnings
):
    """load_strategies replaces previously loaded strategies."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])
    assert len(trader._active_strategies) == 1

    trader.load_strategies([strategy_bearish_earnings])
    assert len(trader._active_strategies) == 1
    assert "strat-bearish-1" in trader._active_strategies
    assert "strat-bullish-1" not in trader._active_strategies


def test_load_strategies_preserves_open_trades(strategy_bullish_high_conf):
    """load_strategies preserves open trades for removed strategies."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    # Manually add an open trade
    trade = StrategyResult(
        id="trade-1",
        strategy_id="strat-bullish-1",
        signal_id="signal-1",
        ticker="TSLA",
        stance="bullish",
        entry_price=250.0,
    )
    trader._open_trades["strat-bullish-1"] = [trade]

    # Reload with empty list
    trader.load_strategies([])
    assert len(trader._active_strategies) == 0
    # Open trade still exists
    assert "strat-bullish-1" in trader._open_trades
    assert len(trader._open_trades["strat-bullish-1"]) == 1


# ---------------------------------------------------------------------------
# Signal evaluation tests
# ---------------------------------------------------------------------------


def test_evaluate_signal_no_strategies():
    """evaluate_signal returns empty list when no strategies loaded."""
    trader = AutoPaperTrader()
    signal = {"ticker": "TSLA", "stance": "bullish", "confidence": 0.7}
    result = trader.evaluate_signal(signal)
    assert result == []


def test_evaluate_signal_matching_bullish(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """evaluate_signal opens trade for matching bullish signal."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    result = trader.evaluate_signal(signal_bullish_tsla)
    assert len(result) == 1
    trade = result[0]
    assert trade.ticker == "TSLA"
    assert trade.stance == "bullish"
    assert trade.entry_price == 250.0
    assert trade.exit_price is None


def test_evaluate_signal_matching_bearish(
    strategy_bearish_earnings, signal_bearish_aapl
):
    """evaluate_signal opens trade for matching bearish signal."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bearish_earnings])

    result = trader.evaluate_signal(signal_bearish_aapl)
    assert len(result) == 1
    trade = result[0]
    assert trade.ticker == "AAPL"
    assert trade.stance == "bearish"


def test_evaluate_signal_no_match_low_confidence(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """evaluate_signal skips signal with insufficient confidence."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    # Lower confidence below threshold
    low_conf_signal = signal_bullish_tsla.copy()
    low_conf_signal["confidence"] = 0.4

    result = trader.evaluate_signal(low_conf_signal)
    assert len(result) == 0


def test_evaluate_signal_skips_mixed_stance(
    strategy_bullish_high_conf, signal_mixed_nvda
):
    """evaluate_signal skips signals with mixed stance."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    result = trader.evaluate_signal(signal_mixed_nvda)
    assert len(result) == 0


def test_evaluate_signal_skips_unknown_stance(
    strategy_bullish_high_conf, signal_unknown_stance
):
    """evaluate_signal skips signals with unknown stance."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    result = trader.evaluate_signal(signal_unknown_stance)
    assert len(result) == 0


def test_evaluate_signal_missing_ticker():
    """evaluate_signal skips signal without ticker."""
    trader = AutoPaperTrader()
    trader.load_strategies(
        [
            Strategy(
                id="strat-1",
                user_id="user-1",
                name="Test",
                rules=[StrategyRule(field="confidence", operator="gte", value=0.5)],
                is_active=True,
            )
        ]
    )

    signal = {"stance": "bullish", "confidence": 0.7}
    result = trader.evaluate_signal(signal)
    assert len(result) == 0


def test_evaluate_signal_missing_price():
    """evaluate_signal skips signal without valid entry price."""
    trader = AutoPaperTrader()
    trader.load_strategies(
        [
            Strategy(
                id="strat-1",
                user_id="user-1",
                name="Test",
                rules=[StrategyRule(field="stance", operator="eq", value="bullish")],
                is_active=True,
            )
        ]
    )

    signal = {"id": "sig-1", "ticker": "TSLA", "stance": "bullish", "confidence": 0.7}
    result = trader.evaluate_signal(signal)
    assert len(result) == 0


def test_evaluate_signal_respects_max_concurrent(strategy_bullish_high_conf):
    """evaluate_signal respects max_concurrent limit."""
    trader = AutoPaperTrader(max_concurrent_per_strategy=2)
    trader.load_strategies([strategy_bullish_high_conf])

    # Fill up to max concurrent
    for i in range(2):
        signal = {
            "id": f"signal-{i}",
            "ticker": "TSLA",
            "stance": "bullish",
            "confidence": 0.7,
            "price_at_signal": 250.0,
        }
        result = trader.evaluate_signal(signal)
        assert len(result) == 1

    # Next signal should be skipped
    signal_extra = {
        "id": "signal-extra",
        "ticker": "TSLA",
        "stance": "bullish",
        "confidence": 0.7,
        "price_at_signal": 250.0,
    }
    result = trader.evaluate_signal(signal_extra)
    assert len(result) == 0


def test_evaluate_signal_strategy_config_max_concurrent(strategy_bearish_earnings):
    """evaluate_signal uses strategy config max_concurrent if provided."""
    trader = AutoPaperTrader(max_concurrent_per_strategy=10)
    trader.load_strategies([strategy_bearish_earnings])

    # Strategy config has max_concurrent=5
    for i in range(5):
        signal = {
            "id": f"signal-{i}",
            "ticker": "AAPL",
            "stance": "bearish",
            "confidence": 0.6,
            "event_type": "earnings_rumor",
            "price_at_signal": 195.0,
        }
        result = trader.evaluate_signal(signal)
        assert len(result) == 1

    # 6th signal should be skipped
    signal_extra = {
        "id": "signal-6",
        "ticker": "AAPL",
        "stance": "bearish",
        "confidence": 0.6,
        "event_type": "earnings_rumor",
        "price_at_signal": 195.0,
    }
    result = trader.evaluate_signal(signal_extra)
    assert len(result) == 0


def test_evaluate_signal_multiple_strategies(
    strategy_bullish_high_conf, strategy_bearish_earnings, signal_bullish_tsla
):
    """evaluate_signal evaluates against all loaded strategies."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf, strategy_bearish_earnings])

    # Bullish signal should only match bullish strategy
    result = trader.evaluate_signal(signal_bullish_tsla)
    assert len(result) == 1
    assert result[0].strategy_id == "strat-bullish-1"


def test_evaluate_signal_extract_price_from_market_data():
    """evaluate_signal extracts price from nested market_data dict."""
    trader = AutoPaperTrader()
    trader.load_strategies(
        [
            Strategy(
                id="strat-1",
                user_id="user-1",
                name="Test",
                rules=[StrategyRule(field="stance", operator="eq", value="bullish")],
                is_active=True,
            )
        ]
    )

    signal = {
        "id": "sig-1",
        "ticker": "TSLA",
        "stance": "bullish",
        "market_data": {"last_close": 250.5},
    }
    result = trader.evaluate_signal(signal)
    assert len(result) == 1
    assert result[0].entry_price == 250.5


# ---------------------------------------------------------------------------
# Trade resolution tests
# ---------------------------------------------------------------------------


def test_resolve_trades_empty_price_data(strategy_bullish_high_conf):
    """resolve_trades returns empty list when no price data provided."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    result = trader.resolve_trades({})
    assert result == []


def test_resolve_trades_stop_loss_bullish(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """resolve_trades closes bullish trade at stop loss."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    # Open a trade
    trader.evaluate_signal(signal_bullish_tsla)
    assert len(trader._open_trades["strat-bullish-1"]) == 1

    # Price drops 12% (exceeds 10% stop loss)
    current_price = 250.0 * 0.88  # -12%
    resolved = trader.resolve_trades({"TSLA": current_price})

    assert len(resolved) == 1
    trade = resolved[0]
    assert trade.exit_price == current_price
    assert trade.pnl_pct < -10.0
    assert trade.resolved_at is not None
    assert len(trader._open_trades["strat-bullish-1"]) == 0
    assert len(trader._closed_trades) == 1


def test_resolve_trades_take_profit_bullish(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """resolve_trades closes bullish trade at take profit."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    # Open a trade
    trader.evaluate_signal(signal_bullish_tsla)

    # Price rises 22% (exceeds 20% take profit)
    current_price = 250.0 * 1.22
    resolved = trader.resolve_trades({"TSLA": current_price})

    assert len(resolved) == 1
    trade = resolved[0]
    assert trade.pnl_pct > 20.0
    assert len(trader._closed_trades) == 1


def test_resolve_trades_stop_loss_bearish(
    strategy_bearish_earnings, signal_bearish_aapl
):
    """resolve_trades closes bearish trade at stop loss (price rises)."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bearish_earnings])

    # Open bearish trade
    trader.evaluate_signal(signal_bearish_aapl)

    # Price rises 10% (loss for bearish = stop loss at 8%)
    current_price = 195.0 * 1.10
    resolved = trader.resolve_trades({"AAPL": current_price})

    assert len(resolved) == 1
    trade = resolved[0]
    assert trade.pnl_pct < -8.0


def test_resolve_trades_take_profit_bearish(
    strategy_bearish_earnings, signal_bearish_aapl
):
    """resolve_trades closes bearish trade at take profit (price drops)."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bearish_earnings])

    # Open bearish trade
    trader.evaluate_signal(signal_bearish_aapl)

    # Price drops 17% (profit for bearish = take profit at 15%)
    current_price = 195.0 * 0.83
    resolved = trader.resolve_trades({"AAPL": current_price})

    assert len(resolved) == 1
    trade = resolved[0]
    assert trade.pnl_pct > 15.0


def test_resolve_trades_pnl_calculation_bullish():
    """resolve_trades computes correct P&L for bullish trades."""
    trader = AutoPaperTrader()
    # (current - entry) / entry * 100 for bullish
    entry = 100.0
    current = 110.0
    pnl = trader._compute_pnl_pct("bullish", entry, current)
    assert pnl == pytest.approx(10.0)


def test_resolve_trades_pnl_calculation_bearish():
    """resolve_trades computes correct P&L for bearish trades."""
    trader = AutoPaperTrader()
    # (entry - current) / entry * 100 for bearish
    entry = 100.0
    current = 90.0
    pnl = trader._compute_pnl_pct("bearish", entry, current)
    assert pnl == pytest.approx(10.0)


def test_resolve_trades_no_price_for_ticker(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """resolve_trades keeps trade open if no price data for ticker."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    trader.evaluate_signal(signal_bullish_tsla)
    resolved = trader.resolve_trades({"AAPL": 200.0})  # Different ticker

    assert len(resolved) == 0
    assert len(trader._open_trades["strat-bullish-1"]) == 1


def test_resolve_trades_multiple_tickers(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """resolve_trades handles multiple open trades across tickers."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    # Open two trades
    trader.evaluate_signal(signal_bullish_tsla)
    signal_aapl = {
        "id": "signal-aapl",
        "ticker": "AAPL",
        "stance": "bullish",
        "confidence": 0.7,
        "price_at_signal": 195.0,
    }
    trader.evaluate_signal(signal_aapl)

    # Resolve only TSLA
    resolved = trader.resolve_trades({"TSLA": 250.0 * 1.25})

    assert len(resolved) == 1
    assert resolved[0].ticker == "TSLA"
    assert len(trader._open_trades["strat-bullish-1"]) == 1


# ---------------------------------------------------------------------------
# Performance analytics tests
# ---------------------------------------------------------------------------


def test_get_strategy_performance_no_trades():
    """get_strategy_performance returns zeros when no trades exist."""
    trader = AutoPaperTrader()
    perf = trader.get_strategy_performance("strat-1")

    assert perf["total_trades"] == 0
    assert perf["winning_trades"] == 0
    assert perf["win_rate"] == 0.0
    assert perf["sharpe_ratio"] is None


def test_get_strategy_performance_with_trades(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """get_strategy_performance computes correct stats from closed trades."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    # Open and close trades one at a time with different outcomes
    # Trade 1: win (+25%)
    signal1 = signal_bullish_tsla.copy()
    signal1["id"] = "signal-0"
    trader.evaluate_signal(signal1)
    trader.resolve_trades({"TSLA": 250.0 * 1.25})

    # Trade 2: loss (-15%)
    signal2 = signal_bullish_tsla.copy()
    signal2["id"] = "signal-1"
    trader.evaluate_signal(signal2)
    trader.resolve_trades({"TSLA": 250.0 * 0.85})

    # Trade 3: win (+30%)
    signal3 = signal_bullish_tsla.copy()
    signal3["id"] = "signal-2"
    trader.evaluate_signal(signal3)
    trader.resolve_trades({"TSLA": 250.0 * 1.30})

    perf = trader.get_strategy_performance("strat-bullish-1")
    assert perf["total_trades"] == 3
    assert perf["winning_trades"] == 2
    assert perf["losing_trades"] == 1
    assert perf["win_rate"] == pytest.approx(2 / 3)
    assert perf["total_pnl_pct"] > 0


def test_get_strategy_performance_sharpe_calculation(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """get_strategy_performance computes Sharpe when >= 5 trades."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    # Open and close 5 trades one at a time (need to hit stop/take thresholds)
    outcomes = [1.25, 0.85, 1.22, 1.30, 0.88]  # 3 wins, 2 losses
    for i, mult in enumerate(outcomes):
        signal = signal_bullish_tsla.copy()
        signal["id"] = f"signal-{i}"
        trader.evaluate_signal(signal)
        trader.resolve_trades({"TSLA": 250.0 * mult})

    perf = trader.get_strategy_performance("strat-bullish-1")
    assert perf["sharpe_ratio"] is not None
    assert isinstance(perf["sharpe_ratio"], float)


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------


def test_health_check_insufficient_data():
    """health_check returns healthy with insufficient trade history."""
    trader = AutoPaperTrader()
    health = trader.health_check("strat-1")

    assert health["health_score"] == 1.0
    assert health["auto_disable"] is False
    assert "Insufficient" in health["reason"]


def test_health_check_healthy_strategy(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """health_check returns high score for performing strategy."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    # Create 5 winning trades
    for i in range(5):
        signal = signal_bullish_tsla.copy()
        signal["id"] = f"signal-{i}"
        trader.evaluate_signal(signal)
        trader.resolve_trades({"TSLA": 250.0 * 1.25})  # +25% each (hits 20% take_profit)

    health = trader.health_check("strat-bullish-1", lookback_trades=5)

    assert health["health_score"] > 0.8
    assert health["auto_disable"] is False
    assert health["rolling_win_rate"] == 1.0


def test_health_check_unhealthy_strategy(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """health_check returns low score and auto_disable for losing strategy."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    # Create 5 losing trades with varied losses (so Sharpe is computed & negative)
    loss_multipliers = [0.85, 0.80, 0.88, 0.75, 0.82]
    for i, mult in enumerate(loss_multipliers):
        signal = signal_bullish_tsla.copy()
        signal["id"] = f"signal-{i}"
        trader.evaluate_signal(signal)
        trader.resolve_trades({"TSLA": 250.0 * mult})

    health = trader.health_check("strat-bullish-1", lookback_trades=5)

    assert health["health_score"] < 0.3
    assert health["auto_disable"] is True
    assert "underperforming" in health["reason"].lower()


def test_health_check_all(
    strategy_bullish_high_conf, strategy_bearish_earnings
):
    """health_check_all runs health check for all active strategies."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf, strategy_bearish_earnings])

    results = trader.health_check_all()
    assert len(results) == 2
    assert "strat-bullish-1" in results
    assert "strat-bearish-1" in results
    assert all(isinstance(r, dict) for r in results.values())


# ---------------------------------------------------------------------------
# Trade accessor tests
# ---------------------------------------------------------------------------


def test_get_open_trades_all(
    strategy_bullish_high_conf, strategy_bearish_earnings
):
    """get_open_trades returns all open trades across strategies."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf, strategy_bearish_earnings])

    # Open trades for both strategies
    signal_bull = {
        "id": "sig-1",
        "ticker": "TSLA",
        "stance": "bullish",
        "confidence": 0.7,
        "price_at_signal": 250.0,
    }
    signal_bear = {
        "id": "sig-2",
        "ticker": "AAPL",
        "stance": "bearish",
        "confidence": 0.6,
        "event_type": "earnings_rumor",
        "price_at_signal": 195.0,
    }

    trader.evaluate_signal(signal_bull)
    trader.evaluate_signal(signal_bear)

    all_open = trader.get_open_trades()
    assert len(all_open) == 2


def test_get_open_trades_by_strategy(strategy_bullish_high_conf):
    """get_open_trades filters by strategy_id."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    signal = {
        "id": "sig-1",
        "ticker": "TSLA",
        "stance": "bullish",
        "confidence": 0.7,
        "price_at_signal": 250.0,
    }
    trader.evaluate_signal(signal)

    strat_trades = trader.get_open_trades("strat-bullish-1")
    assert len(strat_trades) == 1
    assert strat_trades[0].strategy_id == "strat-bullish-1"

    other_trades = trader.get_open_trades("strat-other")
    assert len(other_trades) == 0


def test_get_closed_trades_all(
    strategy_bullish_high_conf, signal_bullish_tsla
):
    """get_closed_trades returns all closed trades."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf])

    trader.evaluate_signal(signal_bullish_tsla)
    trader.resolve_trades({"TSLA": 250.0 * 1.25})

    closed = trader.get_closed_trades()
    assert len(closed) == 1
    assert closed[0].exit_price is not None


def test_get_closed_trades_by_strategy(
    strategy_bullish_high_conf, strategy_bearish_earnings
):
    """get_closed_trades filters by strategy_id."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf, strategy_bearish_earnings])

    # Open and close for both strategies
    sig_bull = {
        "id": "sig-1",
        "ticker": "TSLA",
        "stance": "bullish",
        "confidence": 0.7,
        "price_at_signal": 250.0,
    }
    sig_bear = {
        "id": "sig-2",
        "ticker": "AAPL",
        "stance": "bearish",
        "confidence": 0.6,
        "event_type": "earnings_rumor",
        "price_at_signal": 195.0,
    }

    trader.evaluate_signal(sig_bull)
    trader.evaluate_signal(sig_bear)
    trader.resolve_trades({"TSLA": 250.0 * 1.25, "AAPL": 195.0 * 0.80})

    bullish_closed = trader.get_closed_trades("strat-bullish-1")
    assert len(bullish_closed) == 1
    assert bullish_closed[0].ticker == "TSLA"

    bearish_closed = trader.get_closed_trades("strat-bearish-1")
    assert len(bearish_closed) == 1
    assert bearish_closed[0].ticker == "AAPL"


# ---------------------------------------------------------------------------
# Summary / stats tests
# ---------------------------------------------------------------------------


def test_get_summary_empty():
    """get_summary returns zeros when no strategies or trades."""
    trader = AutoPaperTrader()
    summary = trader.get_summary()

    assert summary["active_strategies"] == 0
    assert summary["total_open_trades"] == 0
    assert summary["total_closed_trades"] == 0


def test_get_summary_with_data(
    strategy_bullish_high_conf, strategy_bearish_earnings
):
    """get_summary returns accurate counts."""
    trader = AutoPaperTrader()
    trader.load_strategies([strategy_bullish_high_conf, strategy_bearish_earnings])

    # Open 2 bullish, 1 bearish
    sig_bull = {
        "id": "sig-1",
        "ticker": "TSLA",
        "stance": "bullish",
        "confidence": 0.7,
        "price_at_signal": 250.0,
    }
    sig_bear = {
        "id": "sig-2",
        "ticker": "AAPL",
        "stance": "bearish",
        "confidence": 0.6,
        "event_type": "earnings_rumor",
        "price_at_signal": 195.0,
    }

    trader.evaluate_signal(sig_bull)

    # Open second bullish with different id, then close it
    sig_bull2 = sig_bull.copy()
    sig_bull2["id"] = "sig-1b"
    trader.evaluate_signal(sig_bull2)
    trader.resolve_trades({"TSLA": 250.0 * 1.25})  # Closes BOTH bullish TSLA trades

    trader.evaluate_signal(sig_bear)

    # Now: 0 bullish open (both closed), 1 bearish open
    summary = trader.get_summary()
    assert summary["active_strategies"] == 2
    assert summary["total_open_trades"] == 1
    assert summary["total_closed_trades"] == 2
    assert summary["open_per_strategy"].get("strat-bullish-1", 0) == 0
    assert summary["open_per_strategy"]["strat-bearish-1"] == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_evaluate_signal_no_signal_id():
    """evaluate_signal skips signal without id field."""
    trader = AutoPaperTrader()
    trader.load_strategies(
        [
            Strategy(
                id="strat-1",
                user_id="user-1",
                name="Test",
                rules=[StrategyRule(field="stance", operator="eq", value="bullish")],
                is_active=True,
            )
        ]
    )

    signal = {"ticker": "TSLA", "stance": "bullish", "price_at_signal": 250.0}
    result = trader.evaluate_signal(signal)
    assert len(result) == 0


def test_resolve_trades_invalid_price():
    """resolve_trades ignores zero/negative prices."""
    trader = AutoPaperTrader()
    trader.load_strategies(
        [
            Strategy(
                id="strat-1",
                user_id="user-1",
                name="Test",
                rules=[StrategyRule(field="stance", operator="eq", value="bullish")],
                is_active=True,
            )
        ]
    )

    signal = {
        "id": "sig-1",
        "ticker": "TSLA",
        "stance": "bullish",
        "price_at_signal": 250.0,
    }
    trader.evaluate_signal(signal)

    resolved = trader.resolve_trades({"TSLA": 0.0})
    assert len(resolved) == 0

    resolved = trader.resolve_trades({"TSLA": -10.0})
    assert len(resolved) == 0


def test_compute_sharpe_zero_std_dev():
    """_compute_sharpe returns None when standard deviation is zero."""
    trader = AutoPaperTrader()
    # All identical returns
    pnls = [5.0, 5.0, 5.0, 5.0, 5.0]
    sharpe = trader._compute_sharpe(pnls)
    assert sharpe is None


def test_compute_sharpe_insufficient_trades():
    """_compute_sharpe returns None when < 5 trades."""
    trader = AutoPaperTrader()
    pnls = [5.0, -3.0, 7.0, 2.0]
    sharpe = trader._compute_sharpe(pnls)
    assert sharpe is None
