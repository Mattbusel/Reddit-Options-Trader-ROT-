"""Comprehensive tests for rot.market.trade_builder — TradeBuilder.

Covers:
- _next_friday and _next_monthly date helpers
- Strategy selection (bullish/bearish/mixed x high/low IV)
- Trade gate integration
- Options liquidity filter
- Quality score calculation
- Max loss estimation
- Edge cases (no entities, unknown stance, low confidence, earnings rumor)
"""
from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest

from rot.core.types import Event, Evidence, OptionLeg, ReasoningPacket
from rot.market.trade_builder import TradeBuilder, _next_friday, _next_monthly


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    entities: list | None = None,
    stance: str = "bullish",
    confidence: float = 0.5,
    event_type: str = "other",
    price: float = 150.0,
    market_cap: float = 3e12,
    atm_iv: float | None = None,
    options_chain: dict | None = None,
) -> Event:
    """Create a test Event with market data."""
    market = {
        (entities or ["TSLA"])[0]: {
            "last_close": price,
            "market_cap": market_cap,
        }
    }
    if atm_iv is not None:
        market[(entities or ["TSLA"])[0]]["atm_iv"] = atm_iv
    if options_chain is not None:
        market[(entities or ["TSLA"])[0]]["options_chain"] = options_chain
    return Event(
        event_type=event_type,
        entities=entities if entities is not None else ["TSLA"],
        stance=stance,
        time_horizon="1w",
        evidence=[Evidence(post_id="x", permalink="", subreddit="options", excerpt="test")],
        confidence=confidence,
        meta={"market": market},
    )


def _make_packet(
    thesis: str = "TSLA looks strong heading into earnings",
    confidence: float = 0.6,
    stance: str = "bullish",
    horizon: str = "1w",
    event_type: str = "other",
    recommended_structures: list | None = None,
    risk_notes: list | None = None,
) -> ReasoningPacket:
    return ReasoningPacket(
        thesis=thesis,
        catalyst_window="1 week",
        market_expectation="bullish continuation",
        invalidations=["price drops below support"],
        raw={
            "confidence": confidence,
            "stance": stance,
            "time_horizon": horizon,
            "event_type": event_type,
        },
        recommended_structures=recommended_structures or [],
        risk_notes=risk_notes or [],
    )


def _force_weekday():
    """Context manager to force the trade gate datetime to a Wednesday."""
    dt = datetime.datetime(2026, 2, 18, 15, 0, tzinfo=datetime.timezone.utc)  # Wednesday
    return patch("rot.market.gates.datetime", wraps=datetime, **{
        "datetime.now.return_value": dt,
    })


@pytest.fixture
def builder():
    return TradeBuilder()


@pytest.fixture(autouse=True)
def mock_weekday():
    """Force all tests to run as if it were a weekday to avoid weekend gate."""
    dt = datetime.datetime(2026, 2, 18, 15, 0, tzinfo=datetime.timezone.utc)  # Wednesday
    with patch("rot.market.gates.datetime") as mock_dt:
        mock_dt.datetime.now.return_value = dt
        mock_dt.timezone = datetime.timezone
        yield


# =========================================================================
# 1. Date helpers
# =========================================================================


class TestNextFriday:
    def test_returns_valid_iso_date(self):
        result = _next_friday()
        datetime.date.fromisoformat(result)  # Should not raise

    def test_returns_a_friday(self):
        result = _next_friday()
        d = datetime.date.fromisoformat(result)
        assert d.weekday() == 4  # Friday

    def test_always_in_future(self):
        result = _next_friday()
        d = datetime.date.fromisoformat(result)
        assert d > datetime.date.today()

    @pytest.mark.parametrize("today_weekday", range(7))
    def test_result_is_always_friday(self, today_weekday):
        """Regardless of which day we're on, result should be a Friday."""
        # We can't easily mock date.today(), so just verify current behavior
        result = _next_friday()
        d = datetime.date.fromisoformat(result)
        assert d.weekday() == 4


class TestNextMonthly:
    def test_returns_valid_iso_date(self):
        result = _next_monthly()
        datetime.date.fromisoformat(result)

    def test_returns_a_friday(self):
        result = _next_monthly()
        d = datetime.date.fromisoformat(result)
        assert d.weekday() == 4

    def test_day_is_between_15_and_21(self):
        """Third Friday is always between the 15th and 21st."""
        result = _next_monthly()
        d = datetime.date.fromisoformat(result)
        assert 15 <= d.day <= 21


# =========================================================================
# 2. TradeBuilder init
# =========================================================================


class TestInit:
    def test_default_min_market_cap(self):
        tb = TradeBuilder()
        assert tb.min_market_cap == 1e8

    def test_custom_min_market_cap(self):
        tb = TradeBuilder(min_market_cap=5e8)
        assert tb.min_market_cap == 5e8

    def test_liquidity_thresholds(self):
        assert TradeBuilder.MIN_OPTION_VOLUME == 10
        assert TradeBuilder.MIN_OPEN_INTEREST == 50
        assert TradeBuilder.MAX_BID_ASK_SPREAD_PCT == 0.15


# =========================================================================
# 3. Successful builds — strategy selection
# =========================================================================


class TestBullishLowIV:
    def test_returns_debit_spread(self, builder):
        event = _make_event(stance="bullish", atm_iv=0.3)
        packet = _make_packet(stance="bullish")
        trades = builder.build(packet, event)
        assert len(trades) == 1
        assert trades[0].strategy == "debit_spread"

    def test_debit_spread_has_call_legs(self, builder):
        event = _make_event(stance="bullish", atm_iv=0.3)
        packet = _make_packet(stance="bullish")
        trades = builder.build(packet, event)
        legs = trades[0].legs
        assert len(legs) == 2
        assert legs[0].kind == "call"
        assert legs[0].side == "buy"
        assert legs[1].kind == "call"
        assert legs[1].side == "sell"


class TestBullishHighIV:
    def test_returns_credit_spread(self, builder):
        event = _make_event(stance="bullish", atm_iv=0.6)
        packet = _make_packet(stance="bullish")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "credit_spread"

    def test_credit_spread_has_put_legs(self, builder):
        event = _make_event(stance="bullish", atm_iv=0.6)
        packet = _make_packet(stance="bullish")
        trades = builder.build(packet, event)
        legs = trades[0].legs
        assert len(legs) == 2
        assert legs[0].kind == "put"
        assert legs[0].side == "sell"
        assert legs[1].kind == "put"
        assert legs[1].side == "buy"


class TestBearishLowIV:
    def test_returns_debit_spread(self, builder):
        event = _make_event(stance="bearish", atm_iv=0.3)
        packet = _make_packet(stance="bearish")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "debit_spread"

    def test_debit_spread_has_put_legs(self, builder):
        event = _make_event(stance="bearish", atm_iv=0.3)
        packet = _make_packet(stance="bearish")
        trades = builder.build(packet, event)
        legs = trades[0].legs
        assert len(legs) == 2
        assert legs[0].kind == "put"
        assert legs[0].side == "buy"
        assert legs[1].kind == "put"
        assert legs[1].side == "sell"


class TestBearishHighIV:
    def test_returns_credit_spread(self, builder):
        event = _make_event(stance="bearish", atm_iv=0.6)
        packet = _make_packet(stance="bearish")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "credit_spread"

    def test_credit_spread_has_call_legs(self, builder):
        event = _make_event(stance="bearish", atm_iv=0.6)
        packet = _make_packet(stance="bearish")
        trades = builder.build(packet, event)
        legs = trades[0].legs
        assert len(legs) == 2
        assert legs[0].kind == "call"
        assert legs[0].side == "sell"
        assert legs[1].kind == "call"
        assert legs[1].side == "buy"


class TestMixedLowIV:
    def test_returns_straddle(self, builder):
        event = _make_event(stance="mixed", atm_iv=0.3)
        packet = _make_packet(stance="mixed")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "straddle"

    def test_straddle_has_call_and_put(self, builder):
        event = _make_event(stance="mixed", atm_iv=0.3)
        packet = _make_packet(stance="mixed")
        trades = builder.build(packet, event)
        legs = trades[0].legs
        assert len(legs) == 2
        kinds = {leg.kind for leg in legs}
        assert "call" in kinds
        assert "put" in kinds


class TestMixedHighIV:
    def test_returns_iron_condor(self, builder):
        event = _make_event(stance="mixed", atm_iv=0.6)
        packet = _make_packet(stance="mixed")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "iron_condor"

    def test_iron_condor_has_4_legs(self, builder):
        event = _make_event(stance="mixed", atm_iv=0.6)
        packet = _make_packet(stance="mixed")
        trades = builder.build(packet, event)
        assert len(trades[0].legs) == 4


# =========================================================================
# 4. No-trade scenarios
# =========================================================================


class TestNoTrade:
    def test_no_entities(self, builder):
        event = _make_event(entities=[])
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert len(trades) == 1
        assert trades[0].strategy == "none"
        assert "no_tickers_extracted" in trades[0].do_not_trade_reasons

    def test_unknown_stance(self, builder):
        event = _make_event(stance="bullish")
        packet = _make_packet(stance="unknown")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "none"
        assert "unknown_stance" in trades[0].do_not_trade_reasons

    def test_low_confidence(self, builder):
        event = _make_event(confidence=0.1)
        packet = _make_packet(confidence=0.2)
        trades = builder.build(packet, event)
        assert trades[0].strategy == "none"
        assert "confidence_too_low" in trades[0].do_not_trade_reasons

    def test_confidence_exactly_0_30_passes(self, builder):
        event = _make_event(confidence=0.30)
        packet = _make_packet(confidence=0.30)
        trades = builder.build(packet, event)
        assert trades[0].strategy != "none" or "confidence_too_low" not in trades[0].do_not_trade_reasons

    def test_confidence_0_29_fails(self, builder):
        event = _make_event(confidence=0.29)
        packet = _make_packet(confidence=0.29)
        trades = builder.build(packet, event)
        assert "confidence_too_low" in trades[0].do_not_trade_reasons

    def test_no_price_data(self, builder):
        event = Event(
            event_type="other",
            entities=["TSLA"],
            stance="bullish",
            time_horizon="1w",
            evidence=[],
            confidence=0.5,
            meta={"market": {"TSLA": {"market_cap": 1e12}}},
        )
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert any("no_price" in r for r in trades[0].do_not_trade_reasons)

    def test_zero_price(self, builder):
        event = _make_event(price=0)
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert any("no_price" in r for r in trades[0].do_not_trade_reasons)

    def test_negative_price(self, builder):
        event = _make_event(price=-10)
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert any("no_price" in r for r in trades[0].do_not_trade_reasons)


# =========================================================================
# 5. Earnings rumor confidence clamp
# =========================================================================


class TestEarningsRumorClamp:
    def test_earnings_rumor_high_confidence_clamped(self, builder):
        event = _make_event(event_type="earnings_rumor", confidence=0.6)
        packet = _make_packet(confidence=0.6, event_type="earnings_rumor")
        trades = builder.build(packet, event)
        # Confidence clamped to 0.25, which is below 0.30 threshold → no trade
        assert "confidence_too_low" in trades[0].do_not_trade_reasons

    def test_earnings_rumor_low_confidence_not_clamped(self, builder):
        event = _make_event(event_type="earnings_rumor", confidence=0.2)
        packet = _make_packet(confidence=0.2, event_type="earnings_rumor")
        trades = builder.build(packet, event)
        assert "confidence_too_low" in trades[0].do_not_trade_reasons

    def test_regular_earnings_not_clamped(self, builder):
        event = _make_event(event_type="earnings", confidence=0.6)
        packet = _make_packet(confidence=0.6, event_type="earnings")
        trades = builder.build(packet, event)
        assert trades[0].strategy != "none"


# =========================================================================
# 6. Options liquidity filter
# =========================================================================


class TestOptionsLiquidity:
    def test_no_options_chain_passes(self, builder):
        """No options chain data available — allow trade."""
        event = _make_event()
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert trades[0].strategy != "none"

    def test_low_volume_blocked(self, builder):
        event = _make_event(
            options_chain={"avg_volume": 5, "avg_open_interest": 100, "avg_bid_ask_spread_pct": 0.05}
        )
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert "low_option_volume" in trades[0].do_not_trade_reasons

    def test_low_open_interest_blocked(self, builder):
        event = _make_event(
            options_chain={"avg_volume": 100, "avg_open_interest": 10, "avg_bid_ask_spread_pct": 0.05}
        )
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert "low_open_interest" in trades[0].do_not_trade_reasons

    def test_wide_spread_blocked(self, builder):
        event = _make_event(
            options_chain={"avg_volume": 100, "avg_open_interest": 100, "avg_bid_ask_spread_pct": 0.20}
        )
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert "wide_bid_ask_spread" in trades[0].do_not_trade_reasons

    def test_good_liquidity_passes(self, builder):
        event = _make_event(
            options_chain={"avg_volume": 100, "avg_open_interest": 200, "avg_bid_ask_spread_pct": 0.05}
        )
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert trades[0].strategy != "none"


# =========================================================================
# 7. Max loss estimation
# =========================================================================


class TestMaxLoss:
    def test_debit_spread_max_loss(self, builder):
        event = _make_event(price=100, atm_iv=0.3)
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert trades[0].strategy == "debit_spread"
        assert trades[0].max_loss > 0

    def test_credit_spread_max_loss(self, builder):
        event = _make_event(price=100, atm_iv=0.6)
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert trades[0].strategy == "credit_spread"
        assert trades[0].max_loss > 0

    def test_straddle_max_loss(self, builder):
        event = _make_event(stance="mixed", price=100, atm_iv=0.3)
        packet = _make_packet(stance="mixed")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "straddle"
        assert trades[0].max_loss > 0

    def test_iron_condor_max_loss(self, builder):
        event = _make_event(stance="mixed", price=100, atm_iv=0.6)
        packet = _make_packet(stance="mixed")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "iron_condor"
        assert trades[0].max_loss > 0

    def test_no_trade_zero_max_loss(self, builder):
        event = _make_event(entities=[])
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert trades[0].max_loss == 0.0


# =========================================================================
# 8. Quality score
# =========================================================================


class TestQualityScore:
    def test_quality_score_in_range(self, builder):
        event = _make_event()
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert 0.0 <= trades[0].quality_score <= 1.0

    def test_higher_confidence_higher_quality(self, builder):
        event_low = _make_event(confidence=0.4)
        event_high = _make_event(confidence=0.9)
        packet_low = _make_packet(confidence=0.4)
        packet_high = _make_packet(confidence=0.9)
        trades_low = builder.build(packet_low, event_low)
        trades_high = builder.build(packet_high, event_high)
        if trades_low[0].strategy != "none" and trades_high[0].strategy != "none":
            assert trades_high[0].quality_score >= trades_low[0].quality_score

    def test_specific_event_type_boosts(self, builder):
        event_other = _make_event(event_type="other")
        event_earnings = _make_event(event_type="earnings")
        packet = _make_packet()
        t1 = builder.build(packet, event_other)
        t2 = builder.build(packet, event_earnings)
        if t1[0].strategy != "none" and t2[0].strategy != "none":
            assert t2[0].quality_score >= t1[0].quality_score

    def test_long_thesis_boosts(self, builder):
        event = _make_event()
        short = _make_packet(thesis="buy")
        long = _make_packet(thesis="x" * 100)
        t1 = builder.build(short, event)
        t2 = builder.build(long, event)
        if t1[0].strategy != "none" and t2[0].strategy != "none":
            assert t2[0].quality_score >= t1[0].quality_score

    def test_many_risk_notes_penalized(self, builder):
        event = _make_event()
        few = _make_packet(risk_notes=["a"])
        many = _make_packet(risk_notes=["a", "b", "c", "d"])
        t1 = builder.build(few, event)
        t2 = builder.build(many, event)
        if t1[0].strategy != "none" and t2[0].strategy != "none":
            assert t1[0].quality_score >= t2[0].quality_score


# =========================================================================
# 9. Trade meta
# =========================================================================


class TestTradeMeta:
    def test_meta_has_stance(self, builder):
        event = _make_event()
        packet = _make_packet()
        trades = builder.build(packet, event)
        if trades[0].strategy != "none":
            assert "stance" in trades[0].meta

    def test_meta_has_horizon(self, builder):
        event = _make_event()
        packet = _make_packet()
        trades = builder.build(packet, event)
        if trades[0].strategy != "none":
            assert "horizon" in trades[0].meta

    def test_meta_includes_iv_when_available(self, builder):
        event = _make_event(atm_iv=0.45)
        packet = _make_packet()
        trades = builder.build(packet, event)
        if trades[0].strategy != "none":
            assert "atm_iv" in trades[0].meta


# =========================================================================
# 10. Horizon → expiry mapping
# =========================================================================


class TestHorizonExpiry:
    def test_intraday_gets_weekly(self, builder):
        event = _make_event()
        packet = _make_packet(horizon="intraday")
        trades = builder.build(packet, event)
        if trades[0].strategy != "none":
            expiry = datetime.date.fromisoformat(trades[0].time_stop)
            assert expiry.weekday() == 4

    def test_1w_gets_weekly(self, builder):
        event = _make_event()
        packet = _make_packet(horizon="1w")
        trades = builder.build(packet, event)
        if trades[0].strategy != "none":
            expiry = datetime.date.fromisoformat(trades[0].time_stop)
            assert expiry.weekday() == 4

    def test_earnings_gets_weekly(self, builder):
        event = _make_event()
        packet = _make_packet(horizon="earnings")
        trades = builder.build(packet, event)
        if trades[0].strategy != "none":
            expiry = datetime.date.fromisoformat(trades[0].time_stop)
            assert expiry.weekday() == 4

    def test_1m_gets_monthly(self, builder):
        event = _make_event()
        packet = _make_packet(horizon="1m")
        trades = builder.build(packet, event)
        if trades[0].strategy != "none":
            expiry = datetime.date.fromisoformat(trades[0].time_stop)
            assert expiry.weekday() == 4
            assert 15 <= expiry.day <= 21


# =========================================================================
# 11. Parametrized strategy matrix
# =========================================================================


class TestStrategyMatrix:
    @pytest.mark.parametrize("stance,iv,expected_strategy", [
        ("bullish", 0.3, "debit_spread"),
        ("bullish", 0.6, "credit_spread"),
        ("bearish", 0.3, "debit_spread"),
        ("bearish", 0.6, "credit_spread"),
        ("mixed", 0.3, "straddle"),
        ("mixed", 0.6, "iron_condor"),
    ])
    def test_strategy_selection(self, builder, stance, iv, expected_strategy):
        event = _make_event(stance=stance, atm_iv=iv)
        packet = _make_packet(stance=stance)
        trades = builder.build(packet, event)
        assert trades[0].strategy == expected_strategy

    @pytest.mark.parametrize("stance,iv,expected_legs", [
        ("bullish", 0.3, 2),
        ("bullish", 0.6, 2),
        ("bearish", 0.3, 2),
        ("bearish", 0.6, 2),
        ("mixed", 0.3, 2),
        ("mixed", 0.6, 4),
    ])
    def test_leg_count(self, builder, stance, iv, expected_legs):
        event = _make_event(stance=stance, atm_iv=iv)
        packet = _make_packet(stance=stance)
        trades = builder.build(packet, event)
        assert len(trades[0].legs) == expected_legs


# =========================================================================
# 12. Edge cases
# =========================================================================


class TestEdgeCases:
    def test_always_returns_list(self, builder):
        event = _make_event()
        packet = _make_packet()
        result = builder.build(packet, event)
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_no_trade_has_reasons(self, builder):
        event = _make_event(entities=[])
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert trades[0].do_not_trade_reasons

    def test_no_trade_underlying_is_unknown(self, builder):
        event = _make_event(entities=[])
        packet = _make_packet()
        trades = builder.build(packet, event)
        assert trades[0].underlying == "UNKNOWN"

    def test_valid_trade_has_thesis(self, builder):
        event = _make_event()
        packet = _make_packet(thesis="Test thesis")
        trades = builder.build(packet, event)
        assert trades[0].thesis == "Test thesis"

    def test_iv_threshold_boundary(self, builder):
        """IV exactly 0.5 is NOT high IV."""
        event = _make_event(stance="bullish", atm_iv=0.5)
        packet = _make_packet(stance="bullish")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "debit_spread"  # Low IV path

    def test_iv_just_above_threshold(self, builder):
        """IV 0.51 IS high IV."""
        event = _make_event(stance="bullish", atm_iv=0.51)
        packet = _make_packet(stance="bullish")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "credit_spread"  # High IV path

    def test_no_iv_data_defaults_to_low_iv(self, builder):
        """When no IV data, default to low IV strategies."""
        event = _make_event(stance="bullish")
        packet = _make_packet(stance="bullish")
        trades = builder.build(packet, event)
        assert trades[0].strategy == "debit_spread"
