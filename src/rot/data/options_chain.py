"""Options chain data structure and analytics."""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional


@dataclass
class OptionQuote:
    symbol: str
    strike: float
    expiry: str
    option_type: str  # "call" or "put"
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    implied_vol: float


class OptionsChain:
    def __init__(self, underlying: str, spot_price: float, quotes: List[OptionQuote]):
        self.underlying = underlying
        self.spot_price = spot_price
        self.quotes = quotes

    def calls(self) -> List[OptionQuote]:
        return [q for q in self.quotes if q.option_type.lower() == "call"]

    def puts(self) -> List[OptionQuote]:
        return [q for q in self.quotes if q.option_type.lower() == "put"]

    def strikes(self) -> List[float]:
        return sorted(set(q.strike for q in self.quotes))

    def expiries(self) -> List[str]:
        return sorted(set(q.expiry for q in self.quotes))

    def atm_strike(self) -> float:
        """Nearest strike to spot price."""
        all_strikes = self.strikes()
        if not all_strikes:
            return self.spot_price
        return min(all_strikes, key=lambda s: abs(s - self.spot_price))

    def atm_iv(self) -> float:
        """IV of the ATM call or put (prefer call)."""
        atm = self.atm_strike()
        for q in self.calls():
            if q.strike == atm:
                return q.implied_vol
        for q in self.puts():
            if q.strike == atm:
                return q.implied_vol
        return 0.0

    def iv_skew(self) -> Dict[float, float]:
        """{strike: iv} for puts."""
        return {q.strike: q.implied_vol for q in self.puts()}

    def put_call_ratio(self) -> float:
        """Total put volume / total call volume."""
        put_vol = sum(q.volume for q in self.puts())
        call_vol = sum(q.volume for q in self.calls())
        if call_vol == 0:
            return float("inf") if put_vol > 0 else 0.0
        return put_vol / call_vol

    def max_pain(self) -> float:
        """Strike where total option value (at expiry) for writers is minimised.

        For each candidate strike, computes sum of intrinsic values of all
        calls and puts if spot = that strike. The max-pain strike minimises
        this sum.
        """
        all_strikes = self.strikes()
        if not all_strikes:
            return self.spot_price

        def total_writer_pain(spot_at_expiry: float) -> float:
            pain = 0.0
            for q in self.calls():
                pain += max(0.0, spot_at_expiry - q.strike) * q.open_interest
            for q in self.puts():
                pain += max(0.0, q.strike - spot_at_expiry) * q.open_interest
            return pain

        return min(all_strikes, key=total_writer_pain)

    def term_structure(self) -> List[Tuple[str, float]]:
        """[(expiry, avg_iv)] sorted by expiry."""
        expiry_ivs: Dict[str, List[float]] = {}
        for q in self.quotes:
            expiry_ivs.setdefault(q.expiry, []).append(q.implied_vol)
        result = [
            (exp, sum(ivs) / len(ivs))
            for exp, ivs in expiry_ivs.items()
            if ivs
        ]
        return sorted(result, key=lambda x: x[0])
