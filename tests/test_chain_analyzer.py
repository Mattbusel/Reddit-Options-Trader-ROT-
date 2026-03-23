"""Unit tests for rot.analytics.chain_analyzer — 15+ test cases."""

from __future__ import annotations

import math
import sys
import os
from datetime import date
from typing import List
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rot.analytics.chain_analyzer import (
    ChainAnalyzer,
    ChainSnapshot,
    OptionQuote,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_quote(
    strike: float,
    bid: float = 1.0,
    ask: float = 2.0,
    iv: float = 0.30,
    delta: float = 0.50,
    gamma: float = 0.05,
    theta: float = -0.02,
    open_interest: int = 100,
    volume: int = 50,
) -> OptionQuote:
    return OptionQuote(
        strike=strike,
        bid=bid,
        ask=ask,
        mid=(bid + ask) / 2,
        iv=iv,
        delta=delta,
        gamma=gamma,
        theta=theta,
        open_interest=open_interest,
        volume=volume,
    )


def make_snapshot(
    spot: float = 100.0,
    call_strikes: List[float] | None = None,
    put_strikes: List[float] | None = None,
) -> ChainSnapshot:
    call_strikes = call_strikes or [90.0, 100.0, 110.0]
    put_strikes = put_strikes or [90.0, 100.0, 110.0]

    calls = [
        make_quote(k, delta=0.6 if k < spot else 0.4, open_interest=200)
        for k in call_strikes
    ]
    puts = [
        make_quote(k, delta=-0.4 if k < spot else -0.6, open_interest=150)
        for k in put_strikes
    ]

    return ChainSnapshot(
        ticker="TEST",
        spot_price=spot,
        expiry=date(2025, 6, 20),
        calls=calls,
        puts=puts,
    )


ANALYZER = ChainAnalyzer()


# ---------------------------------------------------------------------------
# OptionQuote tests
# ---------------------------------------------------------------------------

class TestOptionQuote:
    def test_mid_is_average_of_bid_ask(self):
        q = make_quote(100.0, bid=1.0, ask=3.0)
        assert q.mid == pytest.approx(2.0)

    def test_fields_stored_correctly(self):
        q = make_quote(150.0, iv=0.45, delta=0.30, open_interest=500)
        assert q.strike == 150.0
        assert q.iv == pytest.approx(0.45)
        assert q.delta == pytest.approx(0.30)
        assert q.open_interest == 500


# ---------------------------------------------------------------------------
# ChainSnapshot tests
# ---------------------------------------------------------------------------

class TestChainSnapshot:
    def test_snapshot_fields(self):
        snap = make_snapshot(spot=200.0)
        assert snap.ticker == "TEST"
        assert snap.spot_price == 200.0
        assert len(snap.calls) == 3
        assert len(snap.puts) == 3

    def test_timestamp_set(self):
        snap = make_snapshot()
        assert snap.timestamp > 0


# ---------------------------------------------------------------------------
# max_pain tests
# ---------------------------------------------------------------------------

class TestMaxPain:
    def test_max_pain_returns_float(self):
        snap = make_snapshot()
        mp = ANALYZER.max_pain(snap)
        assert isinstance(mp, float)

    def test_max_pain_within_strike_range(self):
        snap = make_snapshot(call_strikes=[90.0, 100.0, 110.0],
                             put_strikes=[90.0, 100.0, 110.0])
        mp = ANALYZER.max_pain(snap)
        all_strikes = [90.0, 100.0, 110.0]
        assert mp in all_strikes

    def test_max_pain_empty_raises(self):
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=[], puts=[]
        )
        with pytest.raises(ValueError, match="no option contracts"):
            ANALYZER.max_pain(snap)

    def test_max_pain_known_answer(self):
        # Single call at strike 100 OI=100, single put at strike 100 OI=100
        # Only one strike => pain at 100 is 0 for both => trivially 100
        calls = [make_quote(100.0, open_interest=100)]
        puts = [make_quote(100.0, open_interest=100)]
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=calls, puts=puts
        )
        mp = ANALYZER.max_pain(snap)
        assert mp == pytest.approx(100.0)

    def test_max_pain_with_asymmetric_oi(self):
        # Calls: strike 90 OI=1000, 110 OI=1
        # Puts:  strike 90 OI=1, 110 OI=1000
        # Put sellers want price at 110, call sellers want price at 90.
        # Max pain at 90 (minimises total losses from call holders ATM, puts OTM)
        calls = [make_quote(90.0, open_interest=1000), make_quote(110.0, open_interest=1)]
        puts = [make_quote(90.0, open_interest=1), make_quote(110.0, open_interest=1000)]
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=calls, puts=puts
        )
        mp = ANALYZER.max_pain(snap)
        assert mp in [90.0, 110.0]


# ---------------------------------------------------------------------------
# put_call_ratio tests
# ---------------------------------------------------------------------------

class TestPutCallRatio:
    def test_pcr_equal_oi(self):
        calls = [make_quote(100.0, open_interest=100)]
        puts = [make_quote(100.0, open_interest=100)]
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=calls, puts=puts
        )
        assert ANALYZER.put_call_ratio(snap) == pytest.approx(1.0)

    def test_pcr_more_puts(self):
        calls = [make_quote(100.0, open_interest=100)]
        puts = [make_quote(100.0, open_interest=200)]
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=calls, puts=puts
        )
        assert ANALYZER.put_call_ratio(snap) == pytest.approx(2.0)

    def test_pcr_zero_call_oi_returns_inf(self):
        calls = [make_quote(100.0, open_interest=0)]
        puts = [make_quote(100.0, open_interest=50)]
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=calls, puts=puts
        )
        assert ANALYZER.put_call_ratio(snap) == float("inf")

    def test_pcr_both_zero_raises(self):
        calls = [make_quote(100.0, open_interest=0)]
        puts = [make_quote(100.0, open_interest=0)]
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=calls, puts=puts
        )
        with pytest.raises(ValueError, match="zero"):
            ANALYZER.put_call_ratio(snap)

    def test_pcr_aggregates_multiple_strikes(self):
        calls = [make_quote(90.0, open_interest=50),
                 make_quote(110.0, open_interest=50)]
        puts = [make_quote(90.0, open_interest=150),
                make_quote(110.0, open_interest=50)]
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=calls, puts=puts
        )
        assert ANALYZER.put_call_ratio(snap) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# skew tests
# ---------------------------------------------------------------------------

class TestSkew:
    def test_skew_returns_float(self):
        snap = make_snapshot()
        sk = ANALYZER.skew(snap)
        assert isinstance(sk, float)

    def test_skew_no_calls_raises(self):
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=[], puts=[make_quote(100.0)]
        )
        with pytest.raises(ValueError, match="No calls"):
            ANALYZER.skew(snap)

    def test_skew_no_puts_raises(self):
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=[make_quote(100.0)], puts=[]
        )
        with pytest.raises(ValueError, match="No puts"):
            ANALYZER.skew(snap)

    def test_skew_known_value(self):
        # Put 25D: delta=-0.25, iv=0.40; Call 25D: delta=0.25, iv=0.30
        # skew = 0.40 - 0.30 = 0.10
        calls = [make_quote(110.0, delta=0.25, iv=0.30)]
        puts = [make_quote(90.0, delta=-0.25, iv=0.40)]
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=calls, puts=puts
        )
        assert ANALYZER.skew(snap) == pytest.approx(0.10, rel=1e-9)

    def test_skew_picks_closest_to_25_delta(self):
        # Two calls: delta 0.22 and 0.27; closest to 0.25 is 0.27
        calls = [
            make_quote(105.0, delta=0.27, iv=0.25),
            make_quote(115.0, delta=0.22, iv=0.35),
        ]
        puts = [make_quote(95.0, delta=-0.25, iv=0.30)]
        snap = ChainSnapshot(
            ticker="X", spot_price=100.0, expiry=date(2025, 6, 20),
            calls=calls, puts=puts
        )
        sk = ANALYZER.skew(snap)
        # 25D call is strike=105 iv=0.25 => skew = 0.30 - 0.25 = 0.05
        assert sk == pytest.approx(0.05, rel=1e-9)
