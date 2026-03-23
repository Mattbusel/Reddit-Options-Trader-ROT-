"""Dynamic delta hedging simulation and P&L analysis."""
import math
import random
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bsm_delta(S: float, K: float, T: float, r: float, sigma: float, is_call: bool = True) -> float:
    if T <= 0 or sigma <= 0:
        return 1.0 if (is_call and S > K) else 0.0
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    return norm_cdf(d1) if is_call else norm_cdf(d1) - 1


def bsm_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    return math.exp(-0.5*d1**2) / (math.sqrt(2*math.pi) * S * sigma * math.sqrt(T))


def bsm_price(S: float, K: float, T: float, r: float, sigma: float, is_call: bool = True) -> float:
    if T <= 0 or sigma <= 0:
        return max(S-K, 0.0) if is_call else max(K-S, 0.0)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    if is_call:
        return S*norm_cdf(d1) - K*math.exp(-r*T)*norm_cdf(d2)
    return K*math.exp(-r*T)*norm_cdf(-d2) - S*norm_cdf(-d1)


@dataclass
class DeltaHedgeSimulation:
    """Simulate delta hedging of a short call position."""
    S0: float
    K: float
    T: float
    r: float
    sigma_actual: float   # actual realized volatility
    sigma_hedge: float    # vol used for hedging (may differ from actual)
    hedge_freq: int = 252  # rehedging frequency per year

    def simulate(self, seed: int = 42) -> 'HedgeResult':
        rng = random.Random(seed)
        dt = self.T / self.hedge_freq
        sqrt_dt = math.sqrt(dt)

        S = self.S0
        option_value_0 = bsm_price(S, self.K, self.T, self.r, self.sigma_hedge)

        # Short call: receive premium
        cash = option_value_0
        delta = bsm_delta(S, self.K, self.T, self.r, self.sigma_hedge)
        shares = delta  # long delta shares to hedge
        cash -= delta * S  # pay for shares

        pnl_path = [0.0]
        gamma_pnl = 0.0

        for step in range(1, self.hedge_freq + 1):
            t_remaining = self.T - step * dt
            dW = rng.gauss(0, 1) * sqrt_dt
            dS = S * ((self.r - 0.5*self.sigma_actual**2)*dt + self.sigma_actual*dW)
            S_new = S + dS

            # Mark-to-market P&L
            port_value = shares * S_new + cash * math.exp(self.r * dt)
            option_value = bsm_price(S_new, self.K, max(t_remaining, 0), self.r, self.sigma_hedge)
            hedge_pnl = port_value - option_value

            # Rehedge
            cash = cash * math.exp(self.r * dt)
            new_delta = bsm_delta(S_new, self.K, max(t_remaining, 1e-6), self.r, self.sigma_hedge)
            delta_change = new_delta - shares
            cash -= delta_change * S_new
            shares = new_delta

            # Gamma P&L contribution
            gamma = bsm_gamma(S, self.K, max(self.T - (step-1)*dt, 1e-6), self.r, self.sigma_hedge)
            gamma_pnl += 0.5 * gamma * dS**2

            pnl_path.append(hedge_pnl)
            S = S_new

        # Final settlement
        final_payoff = max(S - self.K, 0.0)
        total_pnl = shares * S + cash - final_payoff

        return HedgeResult(
            total_pnl=total_pnl,
            pnl_path=pnl_path,
            final_stock=S,
            gamma_pnl=gamma_pnl,
            vega_pnl=total_pnl - gamma_pnl,
        )


@dataclass
class HedgeResult:
    total_pnl: float
    pnl_path: List[float]
    final_stock: float
    gamma_pnl: float
    vega_pnl: float

    def annualized_sharpe(self) -> float:
        if len(self.pnl_path) < 2:
            return 0.0
        m = sum(self.pnl_path) / len(self.pnl_path)
        v = sum((p-m)**2 for p in self.pnl_path) / len(self.pnl_path)
        std = math.sqrt(v) + 1e-10
        return m / std * math.sqrt(252)
