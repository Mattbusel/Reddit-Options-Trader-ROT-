"""Covered call position management."""
import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CoveredCallPosition:
    symbol: str
    shares: int
    purchase_price: float
    call_strike: float
    call_expiry_days: int
    call_premium: float
    r: float        # risk-free rate
    sigma: float    # implied volatility


def _norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Probability density function for standard normal."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


class CoveredCallManager:
    def __init__(self, position: CoveredCallPosition):
        self.position = position

    def bsm_call(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Black-Scholes-Merton call price."""
        if T <= 0.0 or S <= 0.0 or K <= 0.0 or sigma <= 0.0:
            return max(S - K, 0.0)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)

    def delta(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Call delta (dC/dS)."""
        if T <= 0.0 or S <= 0.0 or K <= 0.0 or sigma <= 0.0:
            return 1.0 if S > K else 0.0
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        return _norm_cdf(d1)

    def net_cost_basis(self) -> float:
        """Effective cost basis after receiving the call premium."""
        return self.position.purchase_price - self.position.call_premium

    def max_profit(self) -> float:
        """Maximum profit per share at expiry (if stock finishes at or above strike)."""
        return (self.position.call_strike - self.net_cost_basis()) * self.position.shares

    def breakeven(self) -> float:
        """Breakeven price per share at expiry."""
        return self.net_cost_basis()

    def pnl_at_expiry(self, S_T: float) -> float:
        """Total position P&L at expiry given terminal stock price S_T."""
        stock_pnl = (S_T - self.position.purchase_price) * self.position.shares
        # Short call P&L
        intrinsic = max(S_T - self.position.call_strike, 0.0)
        call_pnl = (self.position.call_premium - intrinsic) * self.position.shares
        return stock_pnl + call_pnl

    def should_roll(self, current_S: float, days_remaining: int, roll_delta_threshold: float = 0.80) -> bool:
        """Return True if the short call should be rolled (deeply ITM or near expiry)."""
        T = days_remaining / 365.0
        d = self.delta(current_S, self.position.call_strike, T, self.position.r, self.position.sigma)
        return d >= roll_delta_threshold or days_remaining <= 5

    def roll_up(self, new_strike: float, new_expiry_days: int, new_premium: float) -> CoveredCallPosition:
        """Roll the short call up to a higher strike."""
        return CoveredCallPosition(
            symbol=self.position.symbol,
            shares=self.position.shares,
            purchase_price=self.position.purchase_price,
            call_strike=new_strike,
            call_expiry_days=new_expiry_days,
            call_premium=new_premium,
            r=self.position.r,
            sigma=self.position.sigma,
        )

    def roll_out(self, same_strike: float, new_expiry_days: int, new_premium: float) -> CoveredCallPosition:
        """Roll the short call out to a further expiry at the same strike."""
        return CoveredCallPosition(
            symbol=self.position.symbol,
            shares=self.position.shares,
            purchase_price=self.position.purchase_price,
            call_strike=same_strike,
            call_expiry_days=new_expiry_days,
            call_premium=new_premium,
            r=self.position.r,
            sigma=self.position.sigma,
        )

    @staticmethod
    def optimal_strike(S: float, sigma: float, T: float, r: float, target_delta: float = 0.30) -> float:
        """Find the call strike corresponding to a target delta via bisection."""
        if T <= 0.0 or sigma <= 0.0:
            return S
        # d1 = (ln(S/K) + (r + 0.5*sigma^2)*T) / (sigma*sqrt(T)) => N(d1) = target_delta
        # Invert: K = S * exp((r + 0.5*sigma^2)*T - d1*sigma*sqrt(T))
        from math import erfinv
        # N(d1) = target_delta => d1 = sqrt(2) * erfinv(2*target_delta - 1)
        d1 = math.sqrt(2.0) * math.erfinv(2.0 * target_delta - 1.0)
        K = S * math.exp((r + 0.5 * sigma**2) * T - d1 * sigma * math.sqrt(T))
        return K

    def annualized_return(self, current_S: float, days_to_expiry: int) -> float:
        """Annualized return from premium relative to cost basis."""
        cost = self.net_cost_basis()
        if cost <= 0.0 or days_to_expiry <= 0:
            return 0.0
        return (self.position.call_premium / cost) * (365.0 / days_to_expiry)
