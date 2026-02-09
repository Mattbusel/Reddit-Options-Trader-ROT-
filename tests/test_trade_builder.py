from __future__ import annotations

from rot.market.trade_builder import TradeBuilder
from rot.core.types import Event, Evidence, ReasoningPacket


_SENTINEL = object()


def _make_event(
    entities=_SENTINEL, confidence=0.5, stance="bullish", horizon="1w", market_data=_SENTINEL
) -> Event:
    if market_data is _SENTINEL:
        market_data = {
            "TSLA": {
                "symbol": "TSLA",
                "last_close": 250.0,
                "pct_1d": 0.02,
                "market_cap": 800_000_000_000,
            }
        }
    meta = {
        "trend_score": 0.5,
        "features": {},
        "market": market_data,
    }
    if entities is _SENTINEL:
        entities = ["TSLA"]
    return Event(
        event_type="other",
        entities=entities,
        stance=stance,
        time_horizon=horizon,
        evidence=[Evidence(post_id="x", permalink="", subreddit="test", excerpt="test")],
        confidence=confidence,
        meta=meta,
    )


def _make_reasoning(confidence=0.65, stance="bullish", horizon="1w") -> ReasoningPacket:
    return ReasoningPacket(
        thesis="Test thesis for trade builder",
        catalyst_window="1 week",
        market_expectation="unclear",
        invalidations=["test"],
        recommended_structures=["debit spread"],
        risk_notes=["test risk"],
        raw={
            "event_type": "other",
            "stance": stance,
            "time_horizon": horizon,
            "confidence": confidence,
        },
    )


class TestTradeBuilder:
    def setup_method(self):
        self.builder = TradeBuilder()

    def test_bullish_generates_call_spread(self):
        event = _make_event(stance="bullish")
        reasoning = _make_reasoning(stance="bullish")
        ideas = self.builder.build(reasoning, event)

        assert len(ideas) == 1
        idea = ideas[0]
        assert idea.strategy == "debit_spread"
        assert len(idea.legs) == 2
        assert idea.legs[0].kind == "call"
        assert idea.legs[0].side == "buy"
        assert idea.legs[1].side == "sell"
        assert idea.max_loss > 0

    def test_bearish_generates_put_spread(self):
        event = _make_event(stance="bearish")
        reasoning = _make_reasoning(stance="bearish")
        ideas = self.builder.build(reasoning, event)

        assert len(ideas) == 1
        idea = ideas[0]
        assert idea.strategy == "debit_spread"
        assert idea.legs[0].kind == "put"

    def test_mixed_generates_straddle(self):
        event = _make_event(stance="mixed")
        reasoning = _make_reasoning(stance="mixed")
        ideas = self.builder.build(reasoning, event)

        idea = ideas[0]
        assert idea.strategy == "straddle"
        assert len(idea.legs) == 2
        assert {l.kind for l in idea.legs} == {"call", "put"}

    def test_low_confidence_no_trade(self):
        event = _make_event(confidence=0.2)
        reasoning = _make_reasoning(confidence=0.2)
        ideas = self.builder.build(reasoning, event)

        assert ideas[0].strategy == "none"
        assert "confidence_too_low" in ideas[0].do_not_trade_reasons

    def test_no_market_data_no_trade(self):
        event = _make_event(market_data={})
        reasoning = _make_reasoning()
        ideas = self.builder.build(reasoning, event)

        assert ideas[0].strategy == "none"
        assert "no_market_data" in ideas[0].do_not_trade_reasons

    def test_no_entities_no_trade(self):
        event = _make_event(entities=[])
        reasoning = _make_reasoning()
        ideas = self.builder.build(reasoning, event)

        assert ideas[0].strategy == "none"
        assert "no_tickers_extracted" in ideas[0].do_not_trade_reasons

    def test_quality_score_calculated(self):
        event = _make_event()
        reasoning = _make_reasoning(confidence=0.7)
        ideas = self.builder.build(reasoning, event)

        assert ideas[0].quality_score > 0

    def test_strike_prices_around_current(self):
        event = _make_event()
        reasoning = _make_reasoning(stance="bullish")
        ideas = self.builder.build(reasoning, event)

        buy_strike = ideas[0].legs[0].strike
        sell_strike = ideas[0].legs[1].strike
        # ATM should be near 250
        assert 245 <= buy_strike <= 255
        # OTM should be ~5% above
        assert 260 <= sell_strike <= 265
