"""Black-Scholes options pricing and Greeks computation.

Pure-Python implementation of the Black-Scholes-Merton model with all
standard Greeks (delta, gamma, theta, vega, rho) and implied volatility
calculation via bisection method.

No external dependencies — uses only Python's math module.

Design goals:
  - Correct numerical implementation of BSM formulas
  - Safe handling of edge cases (zero time, zero vol, deep ITM/OTM)
  - Portfolio-level Greeks aggregation
  - Reusable foundation for future portfolio risk features
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from rot.flow.types import GreeksSnapshot

# ── Constants ───────────────────────────────────────────

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_SQRT_2 = math.sqrt(2.0)

# Default risk-free rate (US Treasury 1-year approximate)
DEFAULT_RISK_FREE_RATE = 0.05

# Bisection method bounds for IV search
_IV_LOWER = 0.001  # 0.1% vol floor
_IV_UPPER = 5.0  # 500% vol ceiling
_IV_MAX_ITER = 100
_IV_TOLERANCE = 1e-6

# Minimum time to expiry (avoid division by zero)
_MIN_TIME = 1e-10  # ~0.003 seconds


# ── Standard Normal Distribution ────────────────────────


def _norm_cdf(x: float) -> float:
    """Cumulative distribution function for N(0,1).

    Uses the complementary error function for high accuracy.
    Equivalent to scipy.stats.norm.cdf(x) but zero-dependency.
    """
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def _norm_pdf(x: float) -> float:
    """Probability density function for N(0,1).

    Returns: e^(-x²/2) / sqrt(2π)
    """
    return math.exp(-0.5 * x * x) / _SQRT_2PI


# ── Black-Scholes Helpers ───────────────────────────────


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Compute d1 in Black-Scholes formula."""
    return (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Compute d2 in Black-Scholes formula."""
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


# ── Core Pricing ────────────────────────────────────────


class GreeksEngine:
    """Black-Scholes options pricing and Greeks computation.

    Stateless engine — all methods are pure functions that can be called
    concurrently. The risk_free_rate is a default used when callers don't
    specify one explicitly.

    Example::

        engine = GreeksEngine(risk_free_rate=0.05)
        price = engine.price(S=150, K=155, T=0.1, sigma=0.25, option_type="call")
        greeks = engine.compute_greeks(S=150, K=155, T=0.1, sigma=0.25)
        iv = engine.implied_volatility(market_price=3.50, S=150, K=155, T=0.1)
    """

    def __init__(self, risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> None:
        self._risk_free_rate = risk_free_rate

    @property
    def risk_free_rate(self) -> float:
        return self._risk_free_rate

    # ── Option Pricing ──────────────────────────────────

    def price(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        option_type: str = "call",
        r: Optional[float] = None,
    ) -> float:
        """Black-Scholes option price.

        Parameters
        ----------
        S : float
            Current underlying price.
        K : float
            Strike price.
        T : float
            Time to expiration in years (e.g. 30 days = 30/365).
        sigma : float
            Annualized volatility (e.g. 0.25 = 25%).
        option_type : str
            "call" or "put".
        r : float, optional
            Risk-free rate. Defaults to engine's rate.

        Returns
        -------
        float
            Theoretical option price.
        """
        if r is None:
            r = self._risk_free_rate

        # Edge cases
        if S <= 0 or K <= 0:
            return 0.0
        if T <= 0:
            # At expiry: intrinsic value only
            if option_type == "call":
                return max(S - K, 0.0)
            return max(K - S, 0.0)
        if sigma <= 0:
            # Zero vol: deterministic payoff
            pv_k = K * math.exp(-r * T)
            if option_type == "call":
                return max(S - pv_k, 0.0)
            return max(pv_k - S, 0.0)

        T = max(T, _MIN_TIME)
        d1_val = _d1(S, K, T, r, sigma)
        d2_val = d1_val - sigma * math.sqrt(T)

        if option_type == "call":
            return S * _norm_cdf(d1_val) - K * math.exp(-r * T) * _norm_cdf(d2_val)
        else:
            return K * math.exp(-r * T) * _norm_cdf(-d2_val) - S * _norm_cdf(-d1_val)

    # ── Greeks ──────────────────────────────────────────

    def delta(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        option_type: str = "call",
        r: Optional[float] = None,
    ) -> float:
        """Option delta: dV/dS — sensitivity to underlying price."""
        if r is None:
            r = self._risk_free_rate
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            if T <= 0:
                if option_type == "call":
                    return 1.0 if S > K else 0.0
                return -1.0 if S < K else 0.0
            return 0.0

        T = max(T, _MIN_TIME)
        d1_val = _d1(S, K, T, r, sigma)

        if option_type == "call":
            return _norm_cdf(d1_val)
        return _norm_cdf(d1_val) - 1.0

    def gamma(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        r: Optional[float] = None,
    ) -> float:
        """Option gamma: d²V/dS² — rate of delta change.

        Same for calls and puts.
        """
        if r is None:
            r = self._risk_free_rate
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0.0

        T = max(T, _MIN_TIME)
        d1_val = _d1(S, K, T, r, sigma)
        return _norm_pdf(d1_val) / (S * sigma * math.sqrt(T))

    def theta(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        option_type: str = "call",
        r: Optional[float] = None,
    ) -> float:
        """Option theta: dV/dT — time decay per year.

        Returns negative value (options lose value over time).
        Divide by 365 for daily theta.
        """
        if r is None:
            r = self._risk_free_rate
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0.0

        T = max(T, _MIN_TIME)
        d1_val = _d1(S, K, T, r, sigma)
        d2_val = d1_val - sigma * math.sqrt(T)

        # First term: time decay from volatility
        term1 = -(S * _norm_pdf(d1_val) * sigma) / (2.0 * math.sqrt(T))

        if option_type == "call":
            # Second term: risk-free rate on strike
            term2 = -r * K * math.exp(-r * T) * _norm_cdf(d2_val)
        else:
            term2 = r * K * math.exp(-r * T) * _norm_cdf(-d2_val)

        return term1 + term2

    def vega(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        r: Optional[float] = None,
    ) -> float:
        """Option vega: dV/d(sigma) — sensitivity to volatility.

        Returns value per 1.0 (100%) change in vol.
        Divide by 100 for per-1% change. Same for calls and puts.
        """
        if r is None:
            r = self._risk_free_rate
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0.0

        T = max(T, _MIN_TIME)
        d1_val = _d1(S, K, T, r, sigma)
        return S * _norm_pdf(d1_val) * math.sqrt(T)

    def rho(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        option_type: str = "call",
        r: Optional[float] = None,
    ) -> float:
        """Option rho: dV/dr — sensitivity to interest rate.

        Returns value per 1.0 (100%) change in rate.
        Divide by 100 for per-1% change.
        """
        if r is None:
            r = self._risk_free_rate
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0.0

        T = max(T, _MIN_TIME)
        d2_val = _d2(S, K, T, r, sigma)

        if option_type == "call":
            return K * T * math.exp(-r * T) * _norm_cdf(d2_val)
        return -K * T * math.exp(-r * T) * _norm_cdf(-d2_val)

    # ── All Greeks at Once ──────────────────────────────

    def compute_greeks(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        option_type: str = "call",
        r: Optional[float] = None,
        timestamp: float = 0.0,
    ) -> GreeksSnapshot:
        """Compute all Greeks for a single option.

        Parameters
        ----------
        S, K, T, sigma, option_type, r : see price()
        timestamp : float
            Unix timestamp for this snapshot.

        Returns
        -------
        GreeksSnapshot with all Greeks.
        """
        if r is None:
            r = self._risk_free_rate

        return GreeksSnapshot(
            delta=self.delta(S, K, T, sigma, option_type, r),
            gamma=self.gamma(S, K, T, sigma, r),
            theta=self.theta(S, K, T, sigma, option_type, r),
            vega=self.vega(S, K, T, sigma, r),
            rho=self.rho(S, K, T, sigma, option_type, r),
            iv=sigma,
            underlying_price=S,
            strike=K,
            dte=T * 365.0,
            option_type=option_type,
            timestamp=timestamp,
        )

    # ── Implied Volatility ──────────────────────────────

    def implied_volatility(
        self,
        market_price: float,
        S: float,
        K: float,
        T: float,
        option_type: str = "call",
        r: Optional[float] = None,
        max_iterations: int = _IV_MAX_ITER,
        tolerance: float = _IV_TOLERANCE,
    ) -> Optional[float]:
        """Calculate implied volatility via bisection method.

        Parameters
        ----------
        market_price : float
            Observed market price of the option.
        S, K, T, option_type, r : see price()
        max_iterations : int
            Maximum bisection iterations.
        tolerance : float
            Convergence tolerance in price units.

        Returns
        -------
        float or None
            Implied volatility, or None if no solution found.
        """
        if r is None:
            r = self._risk_free_rate

        if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
            return None

        # Check bounds: price must be between intrinsic and underlying
        intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
        if market_price < intrinsic - tolerance:
            return None  # Below intrinsic — no solution

        lo = _IV_LOWER
        hi = _IV_UPPER

        # Verify bounds bracket the solution
        price_lo = self.price(S, K, T, lo, option_type, r)
        price_hi = self.price(S, K, T, hi, option_type, r)

        if market_price < price_lo or market_price > price_hi:
            return None  # Market price outside computable range

        # Bisection
        for _ in range(max_iterations):
            mid = (lo + hi) / 2.0
            price_mid = self.price(S, K, T, mid, option_type, r)
            diff = price_mid - market_price

            if abs(diff) < tolerance:
                return mid

            if diff > 0:
                hi = mid
            else:
                lo = mid

        # Return best estimate even if not fully converged
        return (lo + hi) / 2.0

    # ── Portfolio Aggregation ───────────────────────────

    def portfolio_greeks(
        self,
        positions: List[Dict[str, Any]],
        r: Optional[float] = None,
        timestamp: float = 0.0,
    ) -> GreeksSnapshot:
        """Aggregate Greeks across a portfolio of option positions.

        Parameters
        ----------
        positions : List[Dict]
            Each dict must have: S, K, T, sigma, qty, option_type.
            qty > 0 for long, qty < 0 for short.
        r : float, optional
            Risk-free rate.
        timestamp : float
            Snapshot timestamp.

        Returns
        -------
        GreeksSnapshot with aggregated portfolio Greeks.
        """
        if r is None:
            r = self._risk_free_rate

        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        total_rho = 0.0

        # Weighted average IV (by absolute premium)
        iv_num = 0.0
        iv_den = 0.0

        for pos in positions:
            S = float(pos.get("S", 0))
            K = float(pos.get("K", 0))
            T = float(pos.get("T", 0))
            sigma = float(pos.get("sigma", 0))
            qty = float(pos.get("qty", 0))
            opt_type = pos.get("option_type", "call")

            if S <= 0 or K <= 0 or T <= 0 or sigma <= 0 or qty == 0:
                continue

            # Compute per-contract Greeks
            d = self.delta(S, K, T, sigma, opt_type, r)
            g = self.gamma(S, K, T, sigma, r)
            t = self.theta(S, K, T, sigma, opt_type, r)
            v = self.vega(S, K, T, sigma, r)
            rh = self.rho(S, K, T, sigma, opt_type, r)

            # Multiply by quantity (standard options = 100 shares per contract)
            multiplier = qty * 100.0
            total_delta += d * multiplier
            total_gamma += g * multiplier
            total_theta += t * multiplier
            total_vega += v * multiplier
            total_rho += rh * multiplier

            # IV weighting
            premium = abs(self.price(S, K, T, sigma, opt_type, r) * qty * 100.0)
            iv_num += sigma * premium
            iv_den += premium

        avg_iv = iv_num / iv_den if iv_den > 0 else 0.0

        return GreeksSnapshot(
            delta=total_delta,
            gamma=total_gamma,
            theta=total_theta,
            vega=total_vega,
            rho=total_rho,
            iv=avg_iv,
            timestamp=timestamp,
        )


# ── Module-level convenience ────────────────────────────

_default_engine = GreeksEngine()


def black_scholes_price(
    S: float,
    K: float,
    T: float,
    sigma: float,
    option_type: str = "call",
    r: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """Convenience function: Black-Scholes price using default engine."""
    return _default_engine.price(S, K, T, sigma, option_type, r)


def compute_iv(
    market_price: float,
    S: float,
    K: float,
    T: float,
    option_type: str = "call",
    r: float = DEFAULT_RISK_FREE_RATE,
) -> Optional[float]:
    """Convenience function: implied volatility using default engine."""
    return _default_engine.implied_volatility(market_price, S, K, T, option_type, r)
