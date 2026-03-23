"""
Butterfly spread options strategy implementation.

Supports both call and put butterfly spreads. Provides net premium, P&L
profile, breakevens, and Monte Carlo probability-of-profit.
"""

import math
import random
from typing import List


# ─── BSM HELPERS ─────────────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def bsm_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes-Merton call option price.

    Args:
        S: Current underlying price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free interest rate (annualised, continuous).
        sigma: Implied volatility (annualised).

    Returns:
        Call option price. Returns intrinsic value when T <= 0.
    """
    if T <= 0.0:
        return max(S - K, 0.0)
    if sigma <= 0.0:
        return max(S - K * math.exp(-r * T), 0.0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def bsm_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes-Merton put option price.

    Args:
        S: Current underlying price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free interest rate (annualised, continuous).
        sigma: Implied volatility (annualised).

    Returns:
        Put option price. Returns intrinsic value when T <= 0.
    """
    if T <= 0.0:
        return max(K - S, 0.0)
    if sigma <= 0.0:
        return max(K * math.exp(-r * T) - S, 0.0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


# ─── BUTTERFLY SPREAD ────────────────────────────────────────────────────────

class ButterflySpread:
    """
    A long butterfly spread.

    Structure (call butterfly):
      +1 call @ K_low
      -2 calls @ K_mid
      +1 call @ K_high

    The spread is symmetric when K_mid - K_low ≈ K_high - K_mid.
    """

    def __init__(
        self,
        S: float,
        K_low: float,
        K_mid: float,
        K_high: float,
        T: float,
        r: float,
        sigma: float,
        is_call: bool = True,
        shares: int = 1,
    ) -> None:
        """
        Args:
            S:       Current underlying price.
            K_low:   Lower strike (long wing).
            K_mid:   Middle strike (short body × 2).
            K_high:  Upper strike (long wing).
            T:       Time to expiry in years.
            r:       Risk-free rate.
            sigma:   Implied volatility.
            is_call: True for call butterfly; False for put butterfly.
            shares:  Contract multiplier (e.g. 100 for equity options).
        """
        lower_width = K_mid - K_low
        upper_width = K_high - K_mid
        if abs(lower_width - upper_width) > 1e-4 * K_mid:
            raise ValueError(
                f"Butterfly must be symmetric: K_mid-K_low={lower_width:.4f} "
                f"!= K_high-K_mid={upper_width:.4f}"
            )
        if K_low >= K_mid or K_mid >= K_high:
            raise ValueError("Strikes must satisfy K_low < K_mid < K_high")

        self.S = S
        self.K_low = K_low
        self.K_mid = K_mid
        self.K_high = K_high
        self.T = T
        self.r = r
        self.sigma = sigma
        self.is_call = is_call
        self.shares = shares

        self._pricer = bsm_call if is_call else bsm_put

    def net_premium(self) -> float:
        """Net premium paid (positive = debit spread).

        Debit = buy K_low + buy K_high − sell 2×K_mid.
        """
        low = self._pricer(self.S, self.K_low, self.T, self.r, self.sigma)
        mid = self._pricer(self.S, self.K_mid, self.T, self.r, self.sigma)
        high = self._pricer(self.S, self.K_high, self.T, self.r, self.sigma)
        return (low + high - 2.0 * mid) * self.shares

    def max_profit(self) -> float:
        """Maximum profit at expiry (achieved when S_T = K_mid).

        max_profit = (K_mid - K_low) - net_premium.
        """
        wing_width = self.K_mid - self.K_low
        return (wing_width - self.net_premium()) * self.shares / self.shares
        # simplified: (K_mid - K_low) * shares - net_premium
        # net_premium already incorporates shares so:

    def _max_profit_raw(self) -> float:
        wing_width = self.K_mid - self.K_low
        return wing_width * self.shares - self.net_premium()

    def max_loss(self) -> float:
        """Maximum loss = net premium paid (limited risk)."""
        return -self.net_premium()

    def breakeven_lower(self) -> float:
        """Lower breakeven price at expiry: K_low + net_premium / shares."""
        return self.K_low + self.net_premium() / self.shares

    def breakeven_upper(self) -> float:
        """Upper breakeven price at expiry: K_high - net_premium / shares."""
        return self.K_high - self.net_premium() / self.shares

    def pnl_at_expiry(self, S_T: float) -> float:
        """P&L at expiry for a given underlying price S_T."""
        if self.is_call:
            low_payoff = max(S_T - self.K_low, 0.0)
            mid_payoff = max(S_T - self.K_mid, 0.0)
            high_payoff = max(S_T - self.K_high, 0.0)
        else:
            low_payoff = max(self.K_low - S_T, 0.0)
            mid_payoff = max(self.K_mid - S_T, 0.0)
            high_payoff = max(self.K_high - S_T, 0.0)

        gross = (low_payoff - 2.0 * mid_payoff + high_payoff) * self.shares
        return gross - self.net_premium()

    def pnl_profile(self, prices: List[float]) -> List[float]:
        """P&L at expiry for each price in the list."""
        return [self.pnl_at_expiry(p) for p in prices]

    def probability_of_profit(self, n_sim: int = 10_000, seed: int = 42) -> float:
        """Monte Carlo estimate of the probability of profit at expiry.

        Simulates S_T = S * exp((r - 0.5 σ²) T + σ √T Z) where Z ~ N(0,1).
        """
        rng = random.Random(seed)
        drift = (self.r - 0.5 * self.sigma ** 2) * self.T
        vol_sqrt_t = self.sigma * math.sqrt(self.T)

        profitable = 0
        for _ in range(n_sim):
            z = rng.gauss(0.0, 1.0)
            s_t = self.S * math.exp(drift + vol_sqrt_t * z)
            if self.pnl_at_expiry(s_t) > 0.0:
                profitable += 1

        return profitable / n_sim

    def is_debit(self) -> bool:
        """Returns True if the spread is entered for a net debit (premium > 0)."""
        return self.net_premium() > 0.0


__all__ = ["bsm_call", "bsm_put", "ButterflySpread"]
