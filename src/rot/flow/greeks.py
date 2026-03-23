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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
        """Annualized risk-free rate used for Black-Scholes pricing."""
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


# ── scipy-backed API ─────────────────────────────────────
# The classes below prefer scipy.stats.norm for N(d1)/N(d2) calculations
# when scipy is installed, and fall back to the pure-Python helpers above.

try:
    from scipy.stats import norm as _scipy_norm  # type: ignore[import-untyped]

    def _N(x: float) -> float:  # noqa: N802
        """scipy CDF of standard normal."""
        return float(_scipy_norm.cdf(x))

    def _n(x: float) -> float:  # noqa: N802
        """scipy PDF of standard normal."""
        return float(_scipy_norm.pdf(x))

except ImportError:  # pragma: no cover
    # Graceful degradation — use the pure-Python implementations.
    _N = _norm_cdf  # type: ignore[assignment]
    _n = _norm_pdf  # type: ignore[assignment]


@dataclass(frozen=True)
class OptionGreeks:
    """All standard Black-Scholes Greeks for a single option contract.

    Attributes:
        delta: Rate of change of option price with respect to underlying price.
        gamma: Rate of change of delta with respect to underlying price.
        theta: Rate of time decay (per year; divide by 365 for daily).
        vega: Sensitivity to a 1.0 (100%) change in implied volatility.
        rho: Sensitivity to a 1.0 (100%) change in the risk-free rate.
        implied_volatility: Annualised implied volatility used in the calculation.
    """

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    implied_volatility: float

    def to_dict(self) -> Dict[str, float]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "delta": round(self.delta, 6),
            "gamma": round(self.gamma, 6),
            "theta": round(self.theta, 6),
            "vega": round(self.vega, 6),
            "rho": round(self.rho, 6),
            "implied_volatility": round(self.implied_volatility, 6),
        }


class BlackScholesGreeks:
    """Stateless Black-Scholes Greeks calculator with scipy.stats.norm.

    Provides individual Greek methods mirroring ``GreeksEngine`` but using
    the scipy standard-normal CDF/PDF when available, and returning
    ``OptionGreeks`` dataclasses.

    Example::

        bsg = BlackScholesGreeks(risk_free_rate=0.05)
        g = bsg.all_greeks(S=150, K=155, T=0.25, sigma=0.30, option_type="call")
        print(g.delta, g.gamma, g.vega)
    """

    def __init__(self, risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> None:
        self._r = risk_free_rate

    # ── Individual Greeks ────────────────────────────────

    def delta(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        option_type: str = "call",
        r: Optional[float] = None,
    ) -> float:
        """Black-Scholes delta using scipy N(d1)."""
        if r is None:
            r = self._r
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            if T <= 0:
                if option_type == "call":
                    return 1.0 if S > K else 0.0
                return -1.0 if S < K else 0.0
            return 0.0
        T = max(T, _MIN_TIME)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        return _N(d1) if option_type == "call" else _N(d1) - 1.0

    def gamma(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        r: Optional[float] = None,
    ) -> float:
        """Black-Scholes gamma using scipy n(d1)."""
        if r is None:
            r = self._r
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0.0
        T = max(T, _MIN_TIME)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        return _n(d1) / (S * sigma * math.sqrt(T))

    def theta(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        option_type: str = "call",
        r: Optional[float] = None,
    ) -> float:
        """Black-Scholes theta using scipy n(d1) / N(d2)."""
        if r is None:
            r = self._r
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0.0
        T = max(T, _MIN_TIME)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        term1 = -(S * _n(d1) * sigma) / (2.0 * math.sqrt(T))
        if option_type == "call":
            return term1 - r * K * math.exp(-r * T) * _N(d2)
        return term1 + r * K * math.exp(-r * T) * _N(-d2)

    def vega(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        r: Optional[float] = None,
    ) -> float:
        """Black-Scholes vega using scipy n(d1)."""
        if r is None:
            r = self._r
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0.0
        T = max(T, _MIN_TIME)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        return S * _n(d1) * math.sqrt(T)

    def rho(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        option_type: str = "call",
        r: Optional[float] = None,
    ) -> float:
        """Black-Scholes rho using scipy N(d2)."""
        if r is None:
            r = self._r
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0.0
        T = max(T, _MIN_TIME)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        if option_type == "call":
            return K * T * math.exp(-r * T) * _N(d2)
        return -K * T * math.exp(-r * T) * _N(-d2)

    # ── All Greeks at once ───────────────────────────────

    def all_greeks(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        option_type: str = "call",
        r: Optional[float] = None,
    ) -> OptionGreeks:
        """Compute all five Greeks and return an ``OptionGreeks`` dataclass.

        Parameters
        ----------
        S : Underlying spot price.
        K : Strike price.
        T : Time to expiry in years.
        sigma : Annualised implied volatility.
        option_type : ``"call"`` or ``"put"``.
        r : Risk-free rate (defaults to engine rate).
        """
        if r is None:
            r = self._r
        return OptionGreeks(
            delta=self.delta(S, K, T, sigma, option_type, r),
            gamma=self.gamma(S, K, T, sigma, r),
            theta=self.theta(S, K, T, sigma, option_type, r),
            vega=self.vega(S, K, T, sigma, r),
            rho=self.rho(S, K, T, sigma, option_type, r),
            implied_volatility=sigma,
        )


class GreeksCalculator:
    """High-level Greeks calculator for a single option given market parameters.

    Wraps ``BlackScholesGreeks`` and accepts common option-specification
    fields (strike, expiry as days-to-expiry, spot, risk-free rate,
    volatility) so callers don't have to manage time conversion.

    Example::

        calc = GreeksCalculator(
            strike=155.0,
            dte_days=30,
            spot=150.0,
            risk_free_rate=0.05,
            volatility=0.28,
        )
        greeks = calc.compute("call")
    """

    def __init__(
        self,
        strike: float,
        dte_days: float,
        spot: float,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        volatility: float = 0.25,
    ) -> None:
        """Initialise the calculator.

        Parameters
        ----------
        strike : Option strike price.
        dte_days : Days to expiration (calendar days).
        spot : Current underlying spot price.
        risk_free_rate : Annualised risk-free rate (e.g. 0.05 = 5%).
        volatility : Annualised implied volatility (e.g. 0.25 = 25%).
        """
        self.strike = strike
        self.dte_days = dte_days
        self.spot = spot
        self.risk_free_rate = risk_free_rate
        self.volatility = volatility
        self._bsg = BlackScholesGreeks(risk_free_rate=risk_free_rate)

    @property
    def T(self) -> float:
        """Time to expiration in years."""
        return max(self.dte_days / 365.0, _MIN_TIME)

    def compute(self, option_type: str = "call") -> OptionGreeks:
        """Compute all Greeks for the configured option parameters.

        Parameters
        ----------
        option_type : ``"call"`` or ``"put"``.

        Returns
        -------
        OptionGreeks
            All five Black-Scholes Greeks plus implied volatility.
        """
        return self._bsg.all_greeks(
            S=self.spot,
            K=self.strike,
            T=self.T,
            sigma=self.volatility,
            option_type=option_type,
            r=self.risk_free_rate,
        )


class SpreadGreeks:
    """Aggregates Greeks across multi-leg options spreads.

    Supports common spread structures: bull call spread, bear put spread,
    straddle, strangle, and arbitrary custom multi-leg structures.

    A ``leg`` is a dict with keys:
      - ``side``: ``"buy"`` or ``"sell"``
      - ``kind``: ``"call"`` or ``"put"``
      - ``strike``: float
      - ``dte_days``: float
      - ``spot``: float
      - ``volatility``: float
      - ``qty``: int (number of contracts, positive)

    Example::

        spread = SpreadGreeks(spot=150.0, risk_free_rate=0.05)
        result = spread.bull_call_spread(
            long_strike=150.0, short_strike=160.0,
            dte_days=30, volatility=0.25,
        )
        print(result.delta, result.gamma)
    """

    def __init__(
        self,
        spot: float = 0.0,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    ) -> None:
        self._spot = spot
        self._r = risk_free_rate
        self._bsg = BlackScholesGreeks(risk_free_rate=risk_free_rate)

    # ── Aggregate arbitrary legs ─────────────────────────

    def aggregate(self, legs: List[Dict[str, Any]]) -> OptionGreeks:
        """Aggregate Greeks across an arbitrary list of option legs.

        Each leg is a dict with keys: ``side``, ``kind``, ``strike``,
        ``dte_days``, ``spot``, ``volatility``, ``qty``.

        Sign convention: ``"buy"`` legs are +qty, ``"sell"`` legs are -qty.
        All Greeks are summed (per-contract) across all legs with qty=100.

        Parameters
        ----------
        legs : List of leg specification dicts.

        Returns
        -------
        OptionGreeks with summed Greeks.  ``implied_volatility`` is the
        premium-weighted average IV across all legs.
        """
        total = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
        iv_num = 0.0
        iv_den = 0.0

        for leg in legs:
            side = leg.get("side", "buy")
            kind = leg.get("kind", "call")
            K = float(leg.get("strike", self._spot))
            dte = float(leg.get("dte_days", 30))
            S = float(leg.get("spot", self._spot))
            sigma = float(leg.get("volatility", 0.25))
            qty = int(leg.get("qty", 1))
            sign = 1.0 if side == "buy" else -1.0
            multiplier = sign * qty * 100.0  # standard 100-share contract

            if S <= 0 or K <= 0 or dte <= 0 or sigma <= 0 or qty == 0:
                continue

            T = max(dte / 365.0, _MIN_TIME)
            g = self._bsg.all_greeks(S=S, K=K, T=T, sigma=sigma, option_type=kind)

            total["delta"] += g.delta * multiplier
            total["gamma"] += g.gamma * multiplier
            total["theta"] += g.theta * multiplier
            total["vega"] += g.vega * multiplier
            total["rho"] += g.rho * multiplier

            # Premium weight for IV average
            price = _default_engine.price(S, K, T, sigma, kind, self._r)
            prem = abs(price * qty * 100.0)
            iv_num += sigma * prem
            iv_den += prem

        avg_iv = iv_num / iv_den if iv_den > 0 else 0.0
        return OptionGreeks(
            delta=total["delta"],
            gamma=total["gamma"],
            theta=total["theta"],
            vega=total["vega"],
            rho=total["rho"],
            implied_volatility=avg_iv,
        )

    # ── Common spread constructors ───────────────────────

    def bull_call_spread(
        self,
        long_strike: float,
        short_strike: float,
        dte_days: float,
        volatility: float,
        spot: Optional[float] = None,
    ) -> OptionGreeks:
        """Bull call debit spread: long lower call, short higher call."""
        S = spot if spot is not None else self._spot
        legs = [
            {"side": "buy", "kind": "call", "strike": long_strike, "dte_days": dte_days, "spot": S, "volatility": volatility, "qty": 1},
            {"side": "sell", "kind": "call", "strike": short_strike, "dte_days": dte_days, "spot": S, "volatility": volatility, "qty": 1},
        ]
        return self.aggregate(legs)

    def bear_put_spread(
        self,
        long_strike: float,
        short_strike: float,
        dte_days: float,
        volatility: float,
        spot: Optional[float] = None,
    ) -> OptionGreeks:
        """Bear put debit spread: long higher put, short lower put."""
        S = spot if spot is not None else self._spot
        legs = [
            {"side": "buy", "kind": "put", "strike": long_strike, "dte_days": dte_days, "spot": S, "volatility": volatility, "qty": 1},
            {"side": "sell", "kind": "put", "strike": short_strike, "dte_days": dte_days, "spot": S, "volatility": volatility, "qty": 1},
        ]
        return self.aggregate(legs)

    def straddle(
        self,
        strike: float,
        dte_days: float,
        volatility: float,
        spot: Optional[float] = None,
        side: str = "buy",
    ) -> OptionGreeks:
        """Long (or short) straddle: ATM call + ATM put at the same strike."""
        S = spot if spot is not None else self._spot
        legs = [
            {"side": side, "kind": "call", "strike": strike, "dte_days": dte_days, "spot": S, "volatility": volatility, "qty": 1},
            {"side": side, "kind": "put", "strike": strike, "dte_days": dte_days, "spot": S, "volatility": volatility, "qty": 1},
        ]
        return self.aggregate(legs)
