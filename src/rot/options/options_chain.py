"""Options chain analysis module for the ROT platform.

Provides data structures and analytics for options chains including Greeks,
put/call ratio, max pain, gamma exposure, unusual activity detection,
implied move estimation, term structure, vol skew, and risk reversal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class OptionContract:
    """A single options contract with full Greeks and market data."""

    strike: float
    expiry: datetime
    option_type: str  # "call" or "put"
    bid: float
    ask: float
    last: float
    iv: float
    delta: float
    gamma: float
    theta: float
    volume: int
    open_interest: int

    @property
    def mid_price(self) -> float:
        """Mid-point of bid/ask spread."""
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float:
        """Bid-ask spread as a percentage of mid price."""
        mid = self.mid_price
        if mid == 0.0:
            return float("inf")
        return (self.ask - self.bid) / mid

    def moneyness(self, spot_price: float) -> float:
        """Strike / spot price ratio. 1.0 = ATM, >1 = OTM call / ITM put."""
        if spot_price == 0.0:
            return float("inf")
        return self.strike / spot_price


class OptionsChain:
    """Complete options chain for a single underlying + expiry combination."""

    def __init__(self, symbol: str, expiry: datetime, contracts: list[OptionContract]):
        self.symbol = symbol
        self.expiry = expiry
        self.contracts = contracts

    @property
    def calls(self) -> list[OptionContract]:
        """All call contracts in the chain."""
        return [c for c in self.contracts if c.option_type == "call"]

    @property
    def puts(self) -> list[OptionContract]:
        """All put contracts in the chain."""
        return [c for c in self.contracts if c.option_type == "put"]

    def atm_strike(self, spot: float) -> float:
        """Return the strike nearest to the current spot price."""
        strikes = sorted({c.strike for c in self.contracts})
        if not strikes:
            return spot
        return min(strikes, key=lambda k: abs(k - spot))

    def atm_options(self, spot: float) -> dict[str, Optional[OptionContract]]:
        """Return the ATM call and put as a dict with keys 'call' and 'put'."""
        atm = self.atm_strike(spot)
        call = next((c for c in self.calls if c.strike == atm), None)
        put = next((c for c in self.puts if c.strike == atm), None)
        return {"call": call, "put": put}

    @property
    def put_call_ratio(self) -> float:
        """Total put open interest divided by total call open interest."""
        call_oi = sum(c.open_interest for c in self.calls)
        put_oi = sum(c.open_interest for c in self.puts)
        if call_oi == 0:
            return float("inf")
        return put_oi / call_oi

    def max_pain(self, spot: float) -> float:
        """Strike that minimises total ITM option pain across all strikes.

        Pain at each strike K is defined as the sum over all option contracts
        of their ITM intrinsic value weighted by open interest.
        """
        strikes = sorted({c.strike for c in self.contracts})
        if not strikes:
            return spot

        min_pain = float("inf")
        max_pain_strike = strikes[0]

        for candidate_k in strikes:
            pain = 0.0
            for c in self.contracts:
                if c.option_type == "call":
                    intrinsic = max(0.0, candidate_k - c.strike)
                else:
                    intrinsic = max(0.0, c.strike - candidate_k)
                pain += intrinsic * c.open_interest
            if pain < min_pain:
                min_pain = pain
                max_pain_strike = candidate_k

        return max_pain_strike

    def gamma_exposure(self, spot: float) -> float:
        """Net gamma exposure (GEX) in dollar terms.

        GEX = Σ (gamma × OI × spot² × 100) for calls
            − Σ (gamma × OI × spot² × 100) for puts
        """
        call_gex = sum(
            c.gamma * c.open_interest * spot * spot * 100.0 for c in self.calls
        )
        put_gex = sum(
            c.gamma * c.open_interest * spot * spot * 100.0 for c in self.puts
        )
        return call_gex - put_gex

    def unusual_activity(self, volume_oi_threshold: float = 5.0) -> list[OptionContract]:
        """Return contracts where volume / open_interest exceeds the threshold."""
        result = []
        for c in self.contracts:
            if c.open_interest > 0:
                ratio = c.volume / c.open_interest
                if ratio > volume_oi_threshold:
                    result.append(c)
        return result

    def implied_move(self, spot: float) -> float:
        """Approximate 1σ expected move as ATM straddle price / spot.

        Uses mid prices of the ATM call and put.
        """
        atm = self.atm_options(spot)
        call = atm.get("call")
        put = atm.get("put")
        if call is None or put is None:
            return 0.0
        straddle_price = call.mid_price + put.mid_price
        if spot == 0.0:
            return 0.0
        return straddle_price / spot


class OptionsChainAnalyzer:
    """Cross-chain analytics for term structure, vol skew, and risk reversal."""

    @staticmethod
    def term_structure(chains: list[OptionsChain], spot: float) -> list[tuple[datetime, float]]:
        """Return (expiry, atm_iv) pairs sorted by expiry for term structure analysis."""
        result = []
        for chain in chains:
            atm = chain.atm_options(spot)
            call = atm.get("call")
            put = atm.get("put")
            # Use call IV if available, then put, then 0.
            if call is not None:
                iv = call.iv
            elif put is not None:
                iv = put.iv
            else:
                iv = 0.0
            result.append((chain.expiry, iv))
        result.sort(key=lambda x: x[0])
        return result

    @staticmethod
    def vol_skew(chain: OptionsChain, spot: float) -> dict[float, float]:
        """Map moneyness → IV for all contracts in the chain.

        Returns a dict keyed by moneyness (strike/spot) mapped to IV.
        When both a call and put exist at a strike, their IVs are averaged.
        """
        skew: dict[float, list[float]] = {}
        for c in chain.contracts:
            m = c.moneyness(spot)
            skew.setdefault(m, []).append(c.iv)
        return {m: sum(ivs) / len(ivs) for m, ivs in sorted(skew.items())}

    @staticmethod
    def risk_reversal(
        chain: OptionsChain,
        spot: float,
        delta: float = 0.25,
    ) -> float:
        """25Δ (or specified Δ) call IV minus 25Δ put IV.

        Finds the call with delta nearest to +`delta` and the put with delta
        nearest to −`delta` (i.e. abs(delta) nearest to `delta`).
        """
        calls = chain.calls
        puts = chain.puts

        if not calls or not puts:
            return 0.0

        target_call_delta = abs(delta)
        target_put_delta = abs(delta)

        best_call = min(calls, key=lambda c: abs(c.delta - target_call_delta))
        best_put = min(puts, key=lambda c: abs(abs(c.delta) - target_put_delta))

        return best_call.iv - best_put.iv
