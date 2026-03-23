"""Option screener based on Greeks and IV rank.

Screens a list of OptionSnapshot objects against configurable
ScreeningCriteria and provides ranking utilities for expected value and
high-IV plays.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# OptionSnapshot
# ---------------------------------------------------------------------------

@dataclass
class OptionSnapshot:
    """Point-in-time snapshot of a single option contract."""

    symbol: str
    expiry: date
    strike: float
    option_type: str  # 'call' or 'put'
    bid: float
    ask: float
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float          # Implied volatility as a decimal (e.g. 0.35 = 35%)
    iv_rank: float     # 0.0 – 1.0
    open_interest: int
    volume: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def days_to_expiry(self) -> int:
        return (self.expiry - date.today()).days


# ---------------------------------------------------------------------------
# ScreeningCriteria
# ---------------------------------------------------------------------------

@dataclass
class ScreeningCriteria:
    """Criteria used to filter option snapshots."""

    min_iv_rank: float = 0.0
    max_iv_rank: float = 1.0
    min_delta: float = -1.0
    max_delta: float = 1.0
    min_open_interest: int = 0
    min_volume: int = 0
    option_types: List[str] = field(default_factory=lambda: ["call", "put"])
    min_days_to_expiry: int = 0
    max_days_to_expiry: int = 365 * 10


# ---------------------------------------------------------------------------
# OptionScreener
# ---------------------------------------------------------------------------

class OptionScreener:
    """Screen and rank option contracts."""

    # ------------------------------------------------------------------
    # Core screening
    # ------------------------------------------------------------------

    def screen(
        self,
        options: List[OptionSnapshot],
        criteria: ScreeningCriteria,
    ) -> List[OptionSnapshot]:
        """Return options that satisfy all criteria."""
        result: List[OptionSnapshot] = []
        for opt in options:
            if not (criteria.min_iv_rank <= opt.iv_rank <= criteria.max_iv_rank):
                continue
            if not (criteria.min_delta <= opt.delta <= criteria.max_delta):
                continue
            if opt.open_interest < criteria.min_open_interest:
                continue
            if opt.volume < criteria.min_volume:
                continue
            if opt.option_type not in criteria.option_types:
                continue
            dte = opt.days_to_expiry
            if not (criteria.min_days_to_expiry <= dte <= criteria.max_days_to_expiry):
                continue
            result.append(opt)
        return result

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def rank_by_expected_value(
        self,
        options: List[OptionSnapshot],
    ) -> List[Tuple[OptionSnapshot, float]]:
        """Rank options by EV proxy: iv_rank * open_interest / (spread + 0.01).

        Higher values indicate better risk-adjusted opportunity.
        """
        scored: List[Tuple[OptionSnapshot, float]] = []
        for opt in options:
            spread = max(opt.ask - opt.bid, 0.0)
            ev = opt.iv_rank * opt.open_interest / (spread + 0.01)
            scored.append((opt, ev))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def find_high_iv_rank(
        self,
        options: List[OptionSnapshot],
        threshold: float = 0.7,
    ) -> List[OptionSnapshot]:
        """Filter options by IV rank threshold and sort descending."""
        filtered = [opt for opt in options if opt.iv_rank >= threshold]
        filtered.sort(key=lambda o: o.iv_rank, reverse=True)
        return filtered

    def find_earnings_plays(
        self,
        options: List[OptionSnapshot],
        days_threshold: int = 5,
    ) -> List[OptionSnapshot]:
        """Near-expiry (≤ days_threshold DTE) high-IV options for earnings plays.

        Returns options sorted by IV rank descending.
        """
        plays = [
            opt for opt in options
            if 0 <= opt.days_to_expiry <= days_threshold
        ]
        plays.sort(key=lambda o: o.iv_rank, reverse=True)
        return plays


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestOptionScreener(unittest.TestCase):
    """Unit tests for OptionScreener."""

    def _make_snapshot(
        self,
        symbol: str = "AAPL",
        expiry_days: int = 30,
        strike: float = 150.0,
        option_type: str = "call",
        bid: float = 1.50,
        ask: float = 1.60,
        delta: float = 0.45,
        gamma: float = 0.02,
        theta: float = -0.05,
        vega: float = 0.10,
        iv: float = 0.35,
        iv_rank: float = 0.65,
        open_interest: int = 500,
        volume: int = 200,
    ) -> OptionSnapshot:
        from datetime import timedelta
        expiry = date.today() + timedelta(days=expiry_days)
        return OptionSnapshot(
            symbol=symbol,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
            bid=bid,
            ask=ask,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            iv=iv,
            iv_rank=iv_rank,
            open_interest=open_interest,
            volume=volume,
        )

    def setUp(self) -> None:
        self.screener = OptionScreener()
        self.options = [
            self._make_snapshot("AAPL", iv_rank=0.80, open_interest=1000, volume=300),
            self._make_snapshot("TSLA", iv_rank=0.40, open_interest=500,  volume=100),
            self._make_snapshot("SPY",  iv_rank=0.20, open_interest=5000, volume=2000),
            self._make_snapshot("NVDA", iv_rank=0.90, option_type="put", delta=-0.40,
                                open_interest=800, volume=400),
        ]

    def test_screen_passes_all_with_default_criteria(self) -> None:
        criteria = ScreeningCriteria()
        result = self.screener.screen(self.options, criteria)
        self.assertEqual(len(result), len(self.options))

    def test_screen_filters_by_iv_rank(self) -> None:
        criteria = ScreeningCriteria(min_iv_rank=0.70)
        result = self.screener.screen(self.options, criteria)
        self.assertTrue(all(o.iv_rank >= 0.70 for o in result))
        self.assertEqual(len(result), 2)  # AAPL (0.80) and NVDA (0.90)

    def test_screen_filters_by_option_type(self) -> None:
        criteria = ScreeningCriteria(option_types=["put"])
        result = self.screener.screen(self.options, criteria)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].symbol, "NVDA")

    def test_screen_filters_by_open_interest(self) -> None:
        criteria = ScreeningCriteria(min_open_interest=1000)
        result = self.screener.screen(self.options, criteria)
        symbols = [o.symbol for o in result]
        self.assertIn("AAPL", symbols)
        self.assertIn("SPY", symbols)

    def test_screen_filters_by_dte(self) -> None:
        criteria = ScreeningCriteria(max_days_to_expiry=29)
        result = self.screener.screen(self.options, criteria)
        # All default snapshots have expiry_days=30, so all should be filtered out.
        self.assertEqual(len(result), 0)

    def test_screen_filters_by_delta_range(self) -> None:
        criteria = ScreeningCriteria(min_delta=-1.0, max_delta=0.0)
        result = self.screener.screen(self.options, criteria)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].symbol, "NVDA")

    def test_rank_by_expected_value_order(self) -> None:
        ranked = self.screener.rank_by_expected_value(self.options)
        # First element should have highest EV.
        self.assertGreaterEqual(ranked[0][1], ranked[-1][1])

    def test_rank_by_ev_returns_all_options(self) -> None:
        ranked = self.screener.rank_by_expected_value(self.options)
        self.assertEqual(len(ranked), len(self.options))

    def test_find_high_iv_rank_threshold(self) -> None:
        result = self.screener.find_high_iv_rank(self.options, threshold=0.75)
        self.assertTrue(all(o.iv_rank >= 0.75 for o in result))

    def test_find_high_iv_rank_sorted_descending(self) -> None:
        result = self.screener.find_high_iv_rank(self.options, threshold=0.0)
        for i in range(len(result) - 1):
            self.assertGreaterEqual(result[i].iv_rank, result[i + 1].iv_rank)

    def test_find_earnings_plays_filters_by_dte(self) -> None:
        from datetime import timedelta
        close = date.today() + timedelta(days=3)
        snap = OptionSnapshot("EARNINGS", close, 100.0, "call",
                              1.0, 1.2, 0.5, 0.03, -0.1, 0.2,
                              0.8, 0.95, 2000, 1000)
        plays = self.screener.find_earnings_plays(self.options + [snap], days_threshold=5)
        symbols = [o.symbol for o in plays]
        self.assertIn("EARNINGS", symbols)
        self.assertNotIn("AAPL", symbols)

    def test_option_snapshot_mid(self) -> None:
        snap = self._make_snapshot(bid=1.0, ask=1.4)
        self.assertAlmostEqual(snap.mid, 1.2)

    def test_option_snapshot_spread(self) -> None:
        snap = self._make_snapshot(bid=1.0, ask=1.4)
        self.assertAlmostEqual(snap.spread, 0.4)


if __name__ == "__main__":
    unittest.main()
