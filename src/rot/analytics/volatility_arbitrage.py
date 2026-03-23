"""Volatility arbitrage: realized vs implied vol trading, variance trading."""
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from collections import deque


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bsm_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    return S * math.sqrt(T) * math.exp(-0.5*d1**2) / math.sqrt(2*math.pi)


def bsm_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return S*norm_cdf(d1) - K*math.exp(-r*T)*norm_cdf(d2)


def realized_vol(returns: List[float], annualize: bool = True, periods_per_year: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r)**2 for r in returns) / (n - 1)
    vol = math.sqrt(variance)
    return vol * math.sqrt(periods_per_year) if annualize else vol


@dataclass
class VolArbitragePosition:
    """Track a vol arb position: long/short realized vol vs implied."""
    entry_implied_vol: float
    current_implied_vol: float
    notional_vega: float   # dollar vega at inception
    entry_price: float     # option price at entry
    is_long_vol: bool      # True = long realized, short implied

    @property
    def vega_pnl(self) -> float:
        """P&L from change in implied vol."""
        iv_change = self.current_implied_vol - self.entry_implied_vol
        sign = 1.0 if self.is_long_vol else -1.0
        return sign * self.notional_vega * iv_change * 100  # vega in cents per vol point

    def realized_vs_implied_edge(self, realized: float) -> float:
        """Edge from vol differential (annualized)."""
        edge = realized - self.entry_implied_vol
        return edge if self.is_long_vol else -edge


class VolSurfaceArbitrage:
    """Detect and exploit vol surface inconsistencies."""

    def __init__(self, S: float, r: float):
        self.S = S
        self.r = r

    def calendar_spread_arb(self, K: float, T1: float, T2: float,
                              iv1: float, iv2: float) -> Optional[str]:
        """Calendar arb: forward variance must be positive."""
        if T1 >= T2:
            return None
        var1 = iv1**2 * T1
        var2 = iv2**2 * T2
        fwd_var = var2 - var1
        if fwd_var <= 0:
            return f"Calendar arb at K={K}: forward variance {fwd_var:.4f} <= 0"
        return None

    def butterfly_arb(self, S: float, K1: float, K2: float, K3: float,
                       T: float, iv1: float, iv2: float, iv3: float) -> Optional[str]:
        """Butterfly arb: convexity of call prices in strike must be non-negative."""
        c1 = bsm_call(S, K1, T, self.r, iv1)
        c2 = bsm_call(S, K2, T, self.r, iv2)
        c3 = bsm_call(S, K3, T, self.r, iv3)
        # Convexity: c2 <= (K3-K2)/(K3-K1)*c1 + (K2-K1)/(K3-K1)*c3
        w1 = (K3 - K2) / (K3 - K1)
        w3 = (K2 - K1) / (K3 - K1)
        if c2 > w1 * c1 + w3 * c3 + 1e-6:
            return f"Butterfly arb at ({K1},{K2},{K3}): convexity violated"
        return None

    def vol_cone(self, historical_vols: List[float]) -> Tuple[float, float, float]:
        """(min, median, max) realized vol for comparison with implied."""
        if not historical_vols:
            return (0.0, 0.0, 0.0)
        s = sorted(historical_vols)
        n = len(s)
        median = s[n//2] if n % 2 else (s[n//2-1] + s[n//2]) / 2
        return (s[0], median, s[-1])


class GammaScalper:
    """Trade realized vol via delta-hedged option position."""

    def __init__(self, S: float, K: float, T: float, r: float, iv: float,
                 is_long_gamma: bool = True, hedge_threshold: float = 0.01):
        self.S = S
        self.K = K
        self.T = T
        self.r = r
        self.iv = iv
        self.is_long_gamma = is_long_gamma
        self.hedge_threshold = hedge_threshold
        self.cumulative_pnl = 0.0
        self.n_hedges = 0
        self.delta = self._compute_delta()

    def _compute_delta(self) -> float:
        if self.T <= 0:
            return 0.0
        d1 = (math.log(self.S/self.K) + (self.r + 0.5*self.iv**2)*self.T) / (self.iv*math.sqrt(self.T))
        return norm_cdf(d1)

    def update(self, new_price: float, dt: float) -> float:
        """Rebalance delta hedge, return step P&L."""
        old_delta = self.delta
        old_price = self.S
        self.S = new_price
        self.T = max(self.T - dt, 0.0)
        new_delta = self._compute_delta()

        delta_change = new_delta - old_delta
        price_change = new_price - old_price

        # Gamma P&L: long gamma profits when |price_change| is large
        # P&L ~ 0.5 * gamma * (dS)^2 - theta * dt
        gamma = bsm_vega(old_price, self.K, max(self.T + dt, 1e-6), self.r, self.iv) / (old_price * self.iv * math.sqrt(max(self.T + dt, 1e-6)))
        gamma_pnl = 0.5 * gamma * price_change**2
        theta_cost = self.iv**2 * old_price**2 * gamma / 2 * dt  # approximate theta

        step_pnl = (gamma_pnl - theta_cost) * (1 if self.is_long_gamma else -1)
        self.cumulative_pnl += step_pnl

        if abs(delta_change) > self.hedge_threshold:
            self.delta = new_delta
            self.n_hedges += 1

        return step_pnl

    def summary(self) -> dict:
        return {
            'cumulative_pnl': self.cumulative_pnl,
            'n_hedges': self.n_hedges,
            'current_delta': self.delta,
            'position_type': 'long_gamma' if self.is_long_gamma else 'short_gamma',
        }
