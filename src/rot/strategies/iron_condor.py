"""Iron condor options strategy implementation."""

from __future__ import annotations

import math
import random
from typing import List, Tuple


class IronCondor:
    """Iron condor options strategy builder and analyzer."""

    def __init__(
        self,
        S: float,
        short_put: float,
        long_put: float,
        short_call: float,
        long_call: float,
        T: float,
        r: float,
        sigma: float,
    ):
        """
        Parameters
        ----------
        S           : current underlying price
        short_put   : strike of the short put (inner, higher strike)
        long_put    : strike of the long put (outer, lower strike)
        short_call  : strike of the short call (inner, lower strike)
        long_call   : strike of the long call (outer, higher strike)
        T           : time to expiration in years
        r           : risk-free rate
        sigma       : implied volatility
        """
        self.S = S
        self.short_put = short_put
        self.long_put = long_put
        self.short_call = short_call
        self.long_call = long_call
        self.T = T
        self.r = r
        self.sigma = sigma

    # ------------------------------------------------------------------
    # BSM helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Standard normal CDF via math.erfc."""
        return 0.5 * math.erfc(-x / math.sqrt(2.0))

    def bsm_price(self, K: float, option_type: str) -> float:
        """Black-Scholes-Merton option price."""
        S, T, r, sigma = self.S, self.T, self.r, self.sigma
        if T <= 0:
            if option_type == 'call':
                return max(S - K, 0.0)
            return max(K - S, 0.0)
        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T
        if option_type == 'call':
            return S * self._norm_cdf(d1) - K * math.exp(-r * T) * self._norm_cdf(d2)
        # put
        return K * math.exp(-r * T) * self._norm_cdf(-d2) - S * self._norm_cdf(-d1)

    # ------------------------------------------------------------------
    # Strategy metrics
    # ------------------------------------------------------------------

    def net_premium(self) -> float:
        """Total credit received: (short put + short call) - (long put + long call)."""
        return (
            self.bsm_price(self.short_put, 'put')
            + self.bsm_price(self.short_call, 'call')
            - self.bsm_price(self.long_put, 'put')
            - self.bsm_price(self.long_call, 'call')
        )

    def max_profit(self) -> float:
        """Maximum profit = net premium received."""
        return self.net_premium()

    def max_loss(self) -> float:
        """Maximum loss = wing width - net premium."""
        put_wing = self.short_put - self.long_put
        call_wing = self.long_call - self.short_call
        wing = max(put_wing, call_wing)
        return wing - self.net_premium()

    def breakeven_lower(self) -> float:
        """Lower breakeven = short_put - net_premium."""
        return self.short_put - self.net_premium()

    def breakeven_upper(self) -> float:
        """Upper breakeven = short_call + net_premium."""
        return self.short_call + self.net_premium()

    def pnl_at_expiry(self, S_T: float) -> float:
        """P&L at expiration given final underlying price S_T."""
        premium = self.net_premium()

        # Put spread P&L (short put + long put)
        short_put_pnl = -max(self.short_put - S_T, 0.0)
        long_put_pnl = max(self.long_put - S_T, 0.0)

        # Call spread P&L (short call + long call)
        short_call_pnl = -max(S_T - self.short_call, 0.0)
        long_call_pnl = max(S_T - self.long_call, 0.0)

        return premium + short_put_pnl + long_put_pnl + short_call_pnl + long_call_pnl

    def pnl_profile(self, prices: List[float]) -> List[float]:
        """P&L profile over a list of underlying prices."""
        return [self.pnl_at_expiry(p) for p in prices]

    def probability_of_profit(self, num_simulations: int = 10000, seed: int = 42) -> float:
        """Monte Carlo estimate of probability that the trade expires profitable."""
        rng = random.Random(seed)
        profitable = 0
        T = max(self.T, 1e-10)
        for _ in range(num_simulations):
            z = rng.gauss(0.0, 1.0)
            S_T = self.S * math.exp(
                (self.r - 0.5 * self.sigma ** 2) * T + self.sigma * math.sqrt(T) * z
            )
            if self.pnl_at_expiry(S_T) > 0:
                profitable += 1
        return profitable / num_simulations

    def adjustment_needed(self, current_S: float, delta_threshold: float = 0.30) -> str:
        """
        Determine if an adjustment is needed based on proximity to short strikes.
        Returns 'roll_up', 'roll_down', or 'none'.
        """
        # Approximate delta of short put and short call using BSM
        # Temporarily set S to current_S for computation
        orig_S = self.S
        self.S = current_S
        put_delta = self._bsm_delta(self.short_put, 'put')
        call_delta = self._bsm_delta(self.short_call, 'call')
        self.S = orig_S

        if abs(put_delta) >= delta_threshold:
            return 'roll_down'
        if call_delta >= delta_threshold:
            return 'roll_up'
        return 'none'

    def _bsm_delta(self, K: float, option_type: str) -> float:
        """BSM delta for the current S, sigma, T, r."""
        S, T, r, sigma = self.S, self.T, self.r, self.sigma
        if T <= 0:
            if option_type == 'call':
                return 1.0 if S > K else 0.0
            return -1.0 if S < K else 0.0
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        if option_type == 'call':
            return self._norm_cdf(d1)
        return self._norm_cdf(d1) - 1.0

    @staticmethod
    def optimal_strikes(
        S: float, sigma: float, T: float, target_delta: float = 0.16
    ) -> Tuple[float, float, float, float]:
        """
        Find put and call strikes at approximately target_delta using Newton's method.
        Returns (long_put, short_put, short_call, long_call).
        """
        from math import log, exp, sqrt, erfc

        def norm_cdf(x: float) -> float:
            return 0.5 * erfc(-x / sqrt(2.0))

        def find_strike_call(delta_target: float) -> float:
            # d1 such that N(d1) = delta_target → d1 = N^{-1}(delta_target)
            # Bisect on K
            lo, hi = S * 0.5, S * 3.0
            for _ in range(60):
                mid = (lo + hi) / 2.0
                sqrt_T = sqrt(max(T, 1e-10))
                d1 = (log(S / mid) + (0.0 + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
                delta = norm_cdf(d1)
                if delta > delta_target:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2.0

        def find_strike_put(delta_target: float) -> float:
            # |delta_put| = target → N(-d1) = target
            lo, hi = S * 0.1, S * 1.5
            for _ in range(60):
                mid = (lo + hi) / 2.0
                sqrt_T = sqrt(max(T, 1e-10))
                d1 = (log(S / mid) + (0.0 + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
                abs_delta = norm_cdf(-d1)
                if abs_delta < delta_target:
                    hi = mid
                else:
                    lo = mid
            return (lo + hi) / 2.0

        short_call = find_strike_call(target_delta)
        short_put = find_strike_put(target_delta)
        wing_width = (short_call - short_put) * 0.5
        long_call = short_call + wing_width
        long_put = short_put - wing_width
        return (long_put, short_put, short_call, long_call)
