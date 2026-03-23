"""Ratio spreads: 1x2 and 1x3 call/put ratio strategies."""
import math
from dataclasses import dataclass
from typing import List, Tuple, Optional


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bsm_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return S*norm_cdf(d1) - K*math.exp(-r*T)*norm_cdf(d2)


def bsm_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return bsm_call(S, K, T, r, sigma) - S + K*math.exp(-r*T)


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


@dataclass
class CallRatioSpread:
    """Long 1 lower call, short N upper calls. Net credit or debit."""
    S: float
    K_long: float    # lower strike (buy 1)
    K_short: float   # upper strike (sell ratio)
    T: float
    r: float
    sigma: float
    ratio: int = 2   # 1x2 default

    def net_premium(self) -> float:
        """Positive = credit received."""
        long_leg = bsm_call(self.S, self.K_long, self.T, self.r, self.sigma)
        short_leg = self.ratio * bsm_call(self.S, self.K_short, self.T, self.r, self.sigma)
        return short_leg - long_leg  # credit is positive

    def pnl_at_expiry(self, S_T: float) -> float:
        long_pnl = max(S_T - self.K_long, 0.0)
        short_pnl = -self.ratio * max(S_T - self.K_short, 0.0)
        return long_pnl + short_pnl + self.net_premium()

    def max_profit(self) -> float:
        return self.pnl_at_expiry(self.K_short)

    def upper_breakeven(self) -> float:
        """Stock price above which trade loses money."""
        # Profit zone: K_short < S_T < upper_BE
        # At upper_BE: K_short pnl from long - ratio*(S-K_short) + premium = 0
        spread = self.K_short - self.K_long
        premium = self.net_premium()
        # pnl = spread - (ratio-1)*(S - K_short) + premium = 0
        # S = K_short + (spread + premium) / (ratio - 1)
        if self.ratio == 1:
            return float('inf')
        return self.K_short + (spread + premium) / (self.ratio - 1)

    def lower_breakeven(self) -> float:
        """Stock price below which the credit trade loses premium."""
        premium = self.net_premium()
        if premium <= 0:
            return self.K_long - premium  # debit spread BE
        return self.K_long  # credit: profitable if above K_long (simplification)

    def net_delta(self) -> float:
        d_long = bsm_delta(self.S, self.K_long, self.T, self.r, self.sigma)
        d_short = self.ratio * bsm_delta(self.S, self.K_short, self.T, self.r, self.sigma)
        return d_long - d_short

    def net_gamma(self) -> float:
        g_long = bsm_gamma(self.S, self.K_long, self.T, self.r, self.sigma)
        g_short = self.ratio * bsm_gamma(self.S, self.K_short, self.T, self.r, self.sigma)
        return g_long - g_short


@dataclass
class PutRatioSpread:
    """Short N lower puts, long 1 upper put."""
    S: float
    K_long: float    # upper strike (buy 1)
    K_short: float   # lower strike (sell ratio)
    T: float
    r: float
    sigma: float
    ratio: int = 2

    def net_premium(self) -> float:
        """Positive = credit received."""
        long_leg = bsm_put(self.S, self.K_long, self.T, self.r, self.sigma)
        short_leg = self.ratio * bsm_put(self.S, self.K_short, self.T, self.r, self.sigma)
        return short_leg - long_leg

    def pnl_at_expiry(self, S_T: float) -> float:
        long_pnl = max(self.K_long - S_T, 0.0)
        short_pnl = -self.ratio * max(self.K_short - S_T, 0.0)
        return long_pnl + short_pnl + self.net_premium()

    def max_profit(self) -> float:
        return self.pnl_at_expiry(self.K_short)

    def lower_breakeven(self) -> float:
        spread = self.K_long - self.K_short
        premium = self.net_premium()
        if self.ratio == 1:
            return 0.0
        return self.K_short - (spread + premium) / (self.ratio - 1)

    def probability_of_profit(self, n_sims: int = 30000, seed: int = 42) -> float:
        import random
        rng = random.Random(seed)
        wins = sum(
            1 for _ in range(n_sims)
            if self.pnl_at_expiry(
                self.S * math.exp((self.r - 0.5*self.sigma**2)*self.T
                                  + self.sigma*math.sqrt(self.T)*rng.gauss(0,1))
            ) > 0
        )
        return wins / n_sims
