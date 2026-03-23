"""Straddle and strangle options strategies with gamma scalping."""

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Black-Scholes-Merton pricing functions
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def bsm_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes-Merton call price."""
    if T <= 0:
        return max(S - K, 0.0)
    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def bsm_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes-Merton put price."""
    if T <= 0:
        return max(K - S, 0.0)
    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def delta_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Delta of a call option."""
    if T <= 0:
        return 1.0 if S > K else 0.0
    return _norm_cdf(_d1(S, K, T, r, sigma))


def gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Gamma — same for calls and puts under BSM."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    phi = math.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi)
    return phi / (S * sigma * math.sqrt(T))


# ---------------------------------------------------------------------------
# Position dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StraddlePosition:
    """Long straddle: long ATM call + long ATM put."""
    symbol: str
    S: float          # Spot at entry
    K: float          # Strike (typically ATM)
    T: float          # Time to expiry in years
    r: float          # Risk-free rate
    sigma: float      # Implied volatility
    premium_paid: float  # Total premium paid per share
    shares: int          # Number of share-equivalents


@dataclass
class StranglePosition:
    """Long strangle: long OTM put + long OTM call."""
    symbol: str
    S: float
    K_put: float
    K_call: float
    T: float
    r: float
    sigma: float
    premium_paid: float
    shares: int


# ---------------------------------------------------------------------------
# Straddle Manager
# ---------------------------------------------------------------------------


class StraddleManager:
    """Manage long straddle positions with Greeks and gamma scalping."""

    def enter_straddle(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        shares: int,
    ) -> StraddlePosition:
        """Create a new straddle position at entry."""
        call_px = bsm_call(S, K, T, r, sigma)
        put_px = bsm_put(S, K, T, r, sigma)
        premium = call_px + put_px
        return StraddlePosition(
            symbol="",
            S=S,
            K=K,
            T=T,
            r=r,
            sigma=sigma,
            premium_paid=premium,
            shares=shares,
        )

    def pnl_at_expiry(self, pos: StraddlePosition, S_T: float) -> float:
        """P&L at expiry for a given final spot price S_T."""
        intrinsic = max(S_T - pos.K, 0.0) + max(pos.K - S_T, 0.0)
        return (intrinsic - pos.premium_paid) * pos.shares

    def breakeven_range(self, pos: StraddlePosition) -> Tuple[float, float]:
        """Lower and upper breakeven prices at expiry."""
        lower = pos.K - pos.premium_paid
        upper = pos.K + pos.premium_paid
        return (lower, upper)

    def delta_at(
        self,
        pos: StraddlePosition,
        S_current: float,
        T_remaining: float,
    ) -> float:
        """Net delta of the straddle at current spot and time remaining."""
        d_call = delta_call(S_current, pos.K, T_remaining, pos.r, pos.sigma)
        d_put = d_call - 1.0  # put delta = call delta - 1
        return d_call + d_put

    def gamma_scalp(
        self,
        pos: StraddlePosition,
        S_current: float,
        T_remaining: float,
        rebalance_threshold: float = 0.10,
    ) -> dict:
        """
        Compute a gamma scalp hedge trade.

        Returns a dict with:
          - 'net_delta': current net delta of the position
          - 'shares_to_trade': shares of underlying to buy/sell (sign = direction)
          - 'action': 'buy', 'sell', or 'no_trade'
          - 'gamma': current gamma of position
        """
        net_delta = self.delta_at(pos, S_current, T_remaining) * pos.shares
        g = gamma(S_current, pos.K, T_remaining, pos.r, pos.sigma) * pos.shares

        if abs(net_delta) > rebalance_threshold * pos.shares:
            shares_to_trade = -round(net_delta)
            action = "sell" if shares_to_trade < 0 else "buy"
        else:
            shares_to_trade = 0
            action = "no_trade"

        return {
            "net_delta": net_delta,
            "shares_to_trade": shares_to_trade,
            "action": action,
            "gamma": g,
        }

    def pnl_profile(
        self,
        pos: StraddlePosition,
        prices: List[float],
    ) -> List[float]:
        """P&L at expiry for each price in the list."""
        return [self.pnl_at_expiry(pos, p) for p in prices]

    def should_close(
        self,
        pos: StraddlePosition,
        S_current: float,
        T_remaining: float,
        profit_target: float = 0.50,
        stop_loss: float = 0.75,
    ) -> str:
        """
        Determine whether to close the position.

        Returns one of: 'close_profit', 'close_stop', 'hold'.
        """
        call_val = bsm_call(S_current, pos.K, T_remaining, pos.r, pos.sigma)
        put_val = bsm_put(S_current, pos.K, T_remaining, pos.r, pos.sigma)
        current_value = call_val + put_val
        pnl_pct = (current_value - pos.premium_paid) / pos.premium_paid if pos.premium_paid > 0 else 0.0

        if pnl_pct >= profit_target:
            return "close_profit"
        if pnl_pct <= -stop_loss:
            return "close_stop"
        return "hold"


# ---------------------------------------------------------------------------
# Strangle Manager
# ---------------------------------------------------------------------------


class StrangleManager:
    """Manage long strangle positions."""

    def enter_strangle(
        self,
        S: float,
        K_put: float,
        K_call: float,
        T: float,
        r: float,
        sigma: float,
        shares: int,
    ) -> StranglePosition:
        """Create a new strangle position."""
        call_px = bsm_call(S, K_call, T, r, sigma)
        put_px = bsm_put(S, K_put, T, r, sigma)
        premium = call_px + put_px
        return StranglePosition(
            symbol="",
            S=S,
            K_put=K_put,
            K_call=K_call,
            T=T,
            r=r,
            sigma=sigma,
            premium_paid=premium,
            shares=shares,
        )

    def pnl_at_expiry(self, pos: StranglePosition, S_T: float) -> float:
        """P&L at expiry for a given final spot price."""
        call_intrinsic = max(S_T - pos.K_call, 0.0)
        put_intrinsic = max(pos.K_put - S_T, 0.0)
        intrinsic = call_intrinsic + put_intrinsic
        return (intrinsic - pos.premium_paid) * pos.shares

    def probability_of_profit(
        self,
        pos: StranglePosition,
        num_sim: int = 10_000,
        seed: int = 42,
    ) -> float:
        """
        Monte Carlo estimate of probability of profit at expiry.

        Simulates lognormal price paths under BSM assumptions.
        """
        rng = random.Random(seed)
        lower_be = pos.K_put - pos.premium_paid
        upper_be = pos.K_call + pos.premium_paid

        profitable = 0
        mu = (pos.r - 0.5 * pos.sigma ** 2) * pos.T
        vol_sqrt_t = pos.sigma * math.sqrt(pos.T)

        for _ in range(num_sim):
            z = rng.gauss(0.0, 1.0)
            S_T = pos.S * math.exp(mu + vol_sqrt_t * z)
            if S_T < lower_be or S_T > upper_be:
                profitable += 1

        return profitable / num_sim
