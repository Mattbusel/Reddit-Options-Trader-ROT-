"""Black-Scholes options pricer with full Greeks engine.

Provides closed-form pricing for European call and put options under the
Black-Scholes-Merton model, together with all five first-order Greeks (Delta,
Gamma, Theta, Vega, Rho) and second-order Greeks (Vanna, Volga, Charm, Speed).

Additionally exposes:
* :func:`implied_volatility` — Newton-Raphson + bisection hybrid solver.
* :class:`OptionsPricer` — batch pricer and Greeks grid builder.
* :class:`SurfacePoint` — one (strike, expiry, iv) point on the IV surface.
* :func:`put_call_parity_check` — verify put-call parity for arbitrage detection.

All prices and Greeks follow standard market conventions:
- Prices are in the same currency as ``S`` (spot price).
- Theta is expressed as price change *per calendar day* (divide by 365).
- Vega is expressed as price change per 1% move in IV (divide by 100 for raw).
- Rho is expressed as price change per 1% move in risk-free rate.

References:
    Black, F. & Scholes, M. (1973). *The Pricing of Options and Corporate Liabilities*.
    Merton, R. C. (1973). *Theory of Rational Option Pricing*.

Example::

    from rot.options.bs_pricer import black_scholes_price, greeks, implied_volatility

    price = black_scholes_price(S=150.0, K=155.0, T=0.25, r=0.05, sigma=0.30, option_type="call")
    g = greeks(S=150.0, K=155.0, T=0.25, r=0.05, sigma=0.30, option_type="call")
    iv = implied_volatility(market_price=price, S=150.0, K=155.0, T=0.25, r=0.05, option_type="call")
    print(f"Price={price:.4f}, Delta={g.delta:.4f}, IV={iv:.4f}")
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_DAYS_PER_YEAR = 365.0
_IV_LO = 1e-5   # minimum IV for bisection
_IV_HI = 20.0   # maximum IV for bisection (2000%)
_MAX_NR_ITER = 100
_MAX_BISECT_ITER = 100
_CONVERGENCE_TOL = 1e-7

# ---------------------------------------------------------------------------
# Normal distribution helpers
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


# ---------------------------------------------------------------------------
# Core Black-Scholes formula
# ---------------------------------------------------------------------------


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> Tuple[float, float]:
    """Compute d1 and d2 for the Black-Scholes model.

    Args:
        S: Spot price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free interest rate (annualised, continuously compounded).
        sigma: Implied volatility (annualised).
        q: Continuous dividend yield (default 0).

    Returns:
        Tuple (d1, d2).

    Raises:
        ValueError: When T <= 0 or sigma <= 0.
    """
    if T <= 0.0:
        raise ValueError(f"T must be > 0, got {T}")
    if sigma <= 0.0:
        raise ValueError(f"sigma must be > 0, got {sigma}")
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / sq
    d2 = d1 - sq
    return d1, d2


def black_scholes_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
    q: float = 0.0,
) -> float:
    """Black-Scholes-Merton price for a European option.

    Args:
        S: Spot price (> 0).
        K: Strike price (> 0).
        T: Time to expiry in years (> 0).
        r: Annualised risk-free rate (continuously compounded).
        sigma: Annualised implied volatility (> 0).
        option_type: ``"call"`` or ``"put"`` (case-insensitive).
        q: Continuous dividend yield (default 0).

    Returns:
        Option price in the same currency as S.
    """
    otype = option_type.lower()
    if otype not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    discount = math.exp(-r * T)
    forward_discount = math.exp(-q * T)

    if otype == "call":
        price = S * forward_discount * _norm_cdf(d1) - K * discount * _norm_cdf(d2)
    else:
        price = K * discount * _norm_cdf(-d2) - S * forward_discount * _norm_cdf(-d1)

    return max(price, 0.0)


def put_call_parity_check(
    call_price: float,
    put_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float = 0.0,
    tolerance: float = 0.01,
) -> Tuple[bool, float]:
    """Verify put-call parity: C - P = S·e^{-qT} - K·e^{-rT}.

    Returns:
        (is_satisfied, deviation) — where deviation is the absolute difference
        between the observed spread and the theoretical parity value.
    """
    observed_spread = call_price - put_price
    theoretical = S * math.exp(-q * T) - K * math.exp(-r * T)
    deviation = abs(observed_spread - theoretical)
    return deviation <= tolerance, deviation


# ---------------------------------------------------------------------------
# Greeks dataclass
# ---------------------------------------------------------------------------


@dataclass
class Greeks:
    """All computed Greeks for a single option.

    First-order Greeks:
        delta:  Rate of change of price with respect to spot.
        gamma:  Rate of change of delta with respect to spot.
        theta:  Rate of change of price with respect to time (per calendar day).
        vega:   Rate of change of price with respect to 1% change in IV.
        rho:    Rate of change of price with respect to 1% change in risk-free rate.

    Second-order Greeks:
        vanna:  Rate of change of delta with respect to IV (= d²V/dS·dσ).
        volga:  Rate of change of vega with respect to IV (= d²V/dσ²).
        charm:  Rate of change of delta with respect to time (delta bleed).
        speed:  Rate of change of gamma with respect to spot (= d³V/dS³).
    """

    # Inputs (stored for reference)
    S: float
    K: float
    T: float
    r: float
    sigma: float
    option_type: str
    price: float

    # First-order
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0   # per calendar day
    vega: float = 0.0    # per 1% sigma move
    rho: float = 0.0     # per 1% rate move

    # Second-order
    vanna: float = 0.0
    volga: float = 0.0
    charm: float = 0.0
    speed: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "price": self.price,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "rho": self.rho,
            "vanna": self.vanna,
            "volga": self.volga,
            "charm": self.charm,
            "speed": self.speed,
        }

    def __str__(self) -> str:
        return (
            f"Greeks({self.option_type.upper()} S={self.S} K={self.K} T={self.T:.4f} "
            f"σ={self.sigma:.4f} | price={self.price:.4f} Δ={self.delta:.4f} "
            f"Γ={self.gamma:.6f} Θ={self.theta:.4f}/day ν={self.vega:.4f}/1% "
            f"ρ={self.rho:.4f}/1%)"
        )


def greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
    q: float = 0.0,
) -> Greeks:
    """Compute all first- and second-order Greeks for a European option.

    Args:
        S, K, T, r, sigma, option_type, q: See :func:`black_scholes_price`.

    Returns:
        :class:`Greeks` populated with all computed values.
    """
    otype = option_type.lower()
    if otype not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    price = black_scholes_price(S, K, T, r, sigma, otype, q)
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    nd1 = _norm_cdf(d1)
    nd2 = _norm_cdf(d2)
    n_neg_d1 = _norm_cdf(-d1)
    n_neg_d2 = _norm_cdf(-d2)
    phi_d1 = _norm_pdf(d1)

    sq_t = math.sqrt(T)
    discount = math.exp(-r * T)
    fwd_discount = math.exp(-q * T)

    # Delta
    if otype == "call":
        delta = fwd_discount * nd1
    else:
        delta = -fwd_discount * n_neg_d1

    # Gamma (same for calls and puts)
    gamma = fwd_discount * phi_d1 / (S * sigma * sq_t)

    # Theta (per calendar year, then divide by 365 for per-day)
    if otype == "call":
        theta_annual = (
            -(S * fwd_discount * phi_d1 * sigma) / (2.0 * sq_t)
            - r * K * discount * nd2
            + q * S * fwd_discount * nd1
        )
    else:
        theta_annual = (
            -(S * fwd_discount * phi_d1 * sigma) / (2.0 * sq_t)
            + r * K * discount * n_neg_d2
            - q * S * fwd_discount * n_neg_d1
        )
    theta = theta_annual / _DAYS_PER_YEAR  # per calendar day

    # Vega (per 1% move in sigma = per 0.01 sigma)
    vega_raw = S * fwd_discount * phi_d1 * sq_t
    vega = vega_raw * 0.01  # per 1%

    # Rho (per 1% move in r = per 0.01 rate)
    if otype == "call":
        rho = K * T * discount * nd2 * 0.01
    else:
        rho = -K * T * discount * n_neg_d2 * 0.01

    # Vanna = d(delta)/d(sigma) = -phi(d1)*d2/sigma
    vanna = -fwd_discount * phi_d1 * d2 / sigma

    # Volga / Vomma = d(vega)/d(sigma) = vega_raw * d1 * d2 / sigma
    volga = vega_raw * d1 * d2 / sigma

    # Charm = d(delta)/d(T)  (delta bleed per year, often presented as per day)
    if otype == "call":
        charm_annual = (
            -fwd_discount * phi_d1 * (2.0 * (r - q) * T - d2 * sigma * sq_t)
            / (2.0 * T * sigma * sq_t)
            + q * fwd_discount * nd1
        )
    else:
        charm_annual = (
            -fwd_discount * phi_d1 * (2.0 * (r - q) * T - d2 * sigma * sq_t)
            / (2.0 * T * sigma * sq_t)
            - q * fwd_discount * n_neg_d1
        )
    charm = charm_annual / _DAYS_PER_YEAR

    # Speed = d(gamma)/d(S) = -gamma * (1 + d1/(sigma*sqrt(T))) / S
    speed = -gamma * (1.0 + d1 / (sigma * sq_t)) / S

    return Greeks(
        S=S, K=K, T=T, r=r, sigma=sigma, option_type=otype, price=price,
        delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho,
        vanna=vanna, volga=volga, charm=charm, speed=speed,
    )


# ---------------------------------------------------------------------------
# Implied volatility solver
# ---------------------------------------------------------------------------


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str = "call",
    q: float = 0.0,
    initial_guess: Optional[float] = None,
    max_iterations: int = _MAX_NR_ITER,
    tolerance: float = _CONVERGENCE_TOL,
) -> float:
    """Solve for implied volatility using Newton-Raphson with bisection fallback.

    Uses Newton-Raphson iterations (vega as Jacobian). Falls back to bisection
    when Newton-Raphson diverges or vega is too small.

    Args:
        market_price: Observed option market price.
        S, K, T, r, option_type, q: Standard BS parameters (no sigma needed).
        initial_guess: Starting σ (default: ``sqrt(2π/T) * market_price / S``).
        max_iterations: Maximum Newton-Raphson iterations.
        tolerance: Convergence criterion (|price error| < tolerance).

    Returns:
        Implied volatility σ as a decimal (e.g. 0.25 = 25%).

    Raises:
        ValueError: When convergence fails.
    """
    otype = option_type.lower()
    if market_price <= 0.0:
        raise ValueError(f"market_price must be > 0, got {market_price}")
    if T <= 0.0:
        raise ValueError(f"T must be > 0, got {T}")

    # Intrinsic value check.
    if otype == "call":
        intrinsic = max(S - K * math.exp(-r * T), 0.0)
    else:
        intrinsic = max(K * math.exp(-r * T) - S, 0.0)
    if market_price < intrinsic - tolerance:
        raise ValueError(
            f"market_price {market_price:.4f} is below intrinsic value {intrinsic:.4f}"
        )

    # Initial guess: Brenner-Subrahmanyam approximation if not provided.
    if initial_guess is None:
        sigma = math.sqrt(2.0 * math.pi / T) * market_price / S
        sigma = max(min(sigma, _IV_HI), _IV_LO)
    else:
        sigma = float(initial_guess)

    # Newton-Raphson.
    for _ in range(max_iterations):
        price = black_scholes_price(S, K, T, r, sigma, otype, q)
        error = price - market_price
        if abs(error) < tolerance:
            return sigma
        # Vega = raw dV/dσ
        d1, _ = _d1_d2(S, K, T, r, sigma, q)
        vega_raw = S * math.exp(-q * T) * _norm_pdf(d1) * math.sqrt(T)
        if vega_raw < 1e-10:
            break  # switch to bisection
        sigma -= error / vega_raw
        sigma = max(min(sigma, _IV_HI), _IV_LO)

    # Bisection fallback.
    lo, hi = _IV_LO, _IV_HI
    for _ in range(_MAX_BISECT_ITER):
        mid = 0.5 * (lo + hi)
        price_mid = black_scholes_price(S, K, T, r, mid, otype, q)
        price_lo = black_scholes_price(S, K, T, r, lo, otype, q)
        if (price_mid - market_price) * (price_lo - market_price) < 0.0:
            hi = mid
        else:
            lo = mid
        if abs(price_mid - market_price) < tolerance:
            return mid
    mid = 0.5 * (lo + hi)
    if abs(black_scholes_price(S, K, T, r, mid, otype, q) - market_price) < 1e-4:
        return mid
    raise ValueError(
        f"IV solver did not converge for market_price={market_price:.4f}, "
        f"S={S}, K={K}, T={T:.4f}, r={r}, option_type={otype}"
    )


# ---------------------------------------------------------------------------
# Batch pricer
# ---------------------------------------------------------------------------


@dataclass
class PriceRequest:
    """A single option pricing request."""
    S: float
    K: float
    T: float
    r: float
    sigma: float
    option_type: str = "call"
    q: float = 0.0
    label: str = ""


@dataclass
class PriceResult:
    """Result of a single pricing request."""
    label: str
    option_type: str
    S: float
    K: float
    T: float
    sigma: float
    price: float
    greeks: Greeks
    error: Optional[str] = None


class OptionsPricer:
    """Batch pricer and Greeks grid builder.

    Example::

        pricer = OptionsPricer(r=0.05)
        results = pricer.price_batch([
            PriceRequest(S=150, K=145, T=0.25, r=0.05, sigma=0.30, option_type="call"),
            PriceRequest(S=150, K=155, T=0.25, r=0.05, sigma=0.30, option_type="put"),
        ])
        for r in results:
            print(r.greeks)
    """

    def __init__(self, r: float = 0.05, q: float = 0.0) -> None:
        self.r = r
        self.q = q

    def price_batch(self, requests: List[PriceRequest]) -> List[PriceResult]:
        """Price a list of option requests, capturing any per-item errors."""
        results: List[PriceResult] = []
        for req in requests:
            try:
                g = greeks(
                    S=req.S, K=req.K, T=req.T, r=req.r,
                    sigma=req.sigma, option_type=req.option_type, q=req.q,
                )
                results.append(PriceResult(
                    label=req.label,
                    option_type=req.option_type,
                    S=req.S, K=req.K, T=req.T, sigma=req.sigma,
                    price=g.price,
                    greeks=g,
                ))
            except Exception as exc:  # noqa: BLE001
                log.warning("Pricing error for %r: %s", req.label, exc)
                results.append(PriceResult(
                    label=req.label,
                    option_type=req.option_type,
                    S=req.S, K=req.K, T=req.T, sigma=req.sigma,
                    price=float("nan"),
                    greeks=Greeks(  # type: ignore[call-arg]
                        S=req.S, K=req.K, T=req.T, r=req.r,
                        sigma=req.sigma, option_type=req.option_type, price=float("nan"),
                    ),
                    error=str(exc),
                ))
        return results

    def strike_grid(
        self,
        S: float,
        T: float,
        sigma: float,
        strikes: List[float],
        option_type: str = "call",
    ) -> List[PriceResult]:
        """Price across a range of strikes for a fixed expiry and IV."""
        requests = [
            PriceRequest(
                S=S, K=K, T=T, r=self.r, sigma=sigma,
                option_type=option_type, q=self.q,
                label=f"K={K:.1f}",
            )
            for K in strikes
        ]
        return self.price_batch(requests)

    def expiry_grid(
        self,
        S: float,
        K: float,
        sigma: float,
        expiries_years: List[float],
        option_type: str = "call",
    ) -> List[PriceResult]:
        """Price across a range of expiries for a fixed strike and IV."""
        requests = [
            PriceRequest(
                S=S, K=K, T=T, r=self.r, sigma=sigma,
                option_type=option_type, q=self.q,
                label=f"T={T:.4f}",
            )
            for T in expiries_years
            if T > 0.0
        ]
        return self.price_batch(requests)
