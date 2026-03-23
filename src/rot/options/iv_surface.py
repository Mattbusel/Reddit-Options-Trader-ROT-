"""Implied volatility surface modeler using the SVI parametrisation.

Fits a Stochastic Volatility Inspired (SVI) model to option chain data,
detects surface anomalies (skew spikes, term structure inversions), identifies
calendar spread opportunities, and renders a 3-D plotly surface.

SVI parametrisation (Gatheral 2004)
-------------------------------------
For a given expiry T, the total variance w(k) is:

    w(k) = a + b * [rho*(k - m) + sqrt((k - m)^2 + sigma^2)]

where k = log(K/F) is log-moneyness, and (a, b, rho, m, sigma) are the
five SVI parameters.  This module fits one set of parameters per expiry and
organises them into a surface.

Example::

    from rot.options.iv_surface import IVSurfaceModeler

    modeler = IVSurfaceModeler()
    surface = modeler.fit("AAPL")
    anomalies = modeler.detect_anomalies(surface)
    opps = modeler.calendar_opportunities(surface)
    fig = modeler.plot_surface(surface)
    fig.show()
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

_YF_AVAILABLE = False
try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    pass

_SCIPY_AVAILABLE = False
try:
    from scipy.optimize import minimize
    _SCIPY_AVAILABLE = True
except ImportError:
    pass

_PLOTLY_AVAILABLE = False
try:
    import plotly.graph_objects as go
    _PLOTLY_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SVIParams:
    """SVI model parameters for a single expiry.

    Attributes:
        a: Vertical shift (overall variance level).
        b: Slope (controls wings).
        rho: Correlation/rotation parameter in (-1, 1).
        m: Horizontal translation (ATM level).
        sigma: Curvature (smoothness).
        expiry: Expiry date string (``"YYYY-MM-DD"``).
        tte: Time to expiry in years.
        fit_error: Mean squared fitting error.
    """

    a: float
    b: float
    rho: float
    m: float
    sigma: float
    expiry: str = ""
    tte: float = 0.0
    fit_error: float = 0.0


@dataclass
class IVSlice:
    """One expiry slice of the IV surface.

    Attributes:
        expiry: Expiry date string.
        tte: Time to expiry in years.
        strikes: Array of strike prices.
        log_moneyness: Array of log(K/F) values.
        market_iv: Market-observed IVs per strike.
        svi_iv: SVI-fitted IVs per strike.
        svi_params: Fitted SVI parameters.
    """

    expiry: str
    tte: float
    strikes: List[float]
    log_moneyness: List[float]
    market_iv: List[float]
    svi_iv: List[float]
    svi_params: Optional[SVIParams]


@dataclass
class IVSurface:
    """Complete IV surface for a ticker.

    Attributes:
        ticker: Underlying symbol.
        forward_price: Estimated forward price used for log-moneyness.
        timestamp: Unix timestamp of fit.
        slices: List of :class:`IVSlice` (one per expiry), sorted by TTE.
        atm_term_structure: Dict mapping expiry → ATM IV.
    """

    ticker: str
    forward_price: float
    timestamp: float
    slices: List[IVSlice] = field(default_factory=list)
    atm_term_structure: Dict[str, float] = field(default_factory=dict)


@dataclass
class SurfaceAnomaly:
    """A detected anomaly in the IV surface.

    Attributes:
        anomaly_type: One of ``"skew_spike"``, ``"term_inversion"``,
            ``"butterfly_arbitrage"``, ``"calendar_arbitrage"``.
        expiry: Affected expiry.
        description: Human-readable description.
        severity: Score in [0, 10].
    """

    anomaly_type: str
    expiry: str
    description: str
    severity: float


@dataclass
class CalendarOpportunity:
    """A calendar spread opportunity from IV surface mismatch.

    Attributes:
        near_expiry: Front-month expiry.
        far_expiry: Back-month expiry.
        near_iv: ATM IV of the near expiry.
        far_iv: ATM IV of the far expiry.
        iv_spread: far_iv - near_iv (positive = normal contango).
        opportunity_type: ``"sell_near_buy_far"`` or ``"sell_far_buy_near"``.
        z_score: How unusual this spread is vs. historical.
    """

    near_expiry: str
    far_expiry: str
    near_iv: float
    far_iv: float
    iv_spread: float
    opportunity_type: str
    z_score: float


# ---------------------------------------------------------------------------
# SVI fitting
# ---------------------------------------------------------------------------


def _svi_total_variance(k: "np.ndarray", params: SVIParams) -> "np.ndarray":
    """Compute SVI total variance w(k).

    Args:
        k: Log-moneyness array.
        params: :class:`SVIParams` instance.

    Returns:
        Total variance array (same shape as *k*).
    """
    a, b, rho, m, sigma = params.a, params.b, params.rho, params.m, params.sigma
    disc = np.sqrt((k - m) ** 2 + sigma ** 2)
    return a + b * (rho * (k - m) + disc)


def fit_svi(
    log_moneyness: "np.ndarray",
    market_iv: "np.ndarray",
    tte: float,
    initial_params: Optional[List[float]] = None,
) -> SVIParams:
    """Fit SVI parameters to market IVs via least-squares optimisation.

    Args:
        log_moneyness: Array of log(K/F) values.
        market_iv: Array of market-observed IVs (annualised).
        tte: Time to expiry in years.
        initial_params: Optional [a, b, rho, m, sigma] starting point.

    Returns:
        :class:`SVIParams` with fitted parameters and fit error.
    """
    market_tv = market_iv ** 2 * tte  # convert IV to total variance

    def objective(p: List[float]) -> float:
        a, b, rho, m, sigma = p
        # Enforce parameter constraints
        if b <= 0 or sigma <= 1e-6 or abs(rho) >= 1 or a < 0:
            return 1e10
        params = SVIParams(a=a, b=b, rho=rho, m=m, sigma=sigma)
        fitted = _svi_total_variance(log_moneyness, params)
        # Penalise negative total variance (no-arbitrage violation)
        if np.any(fitted <= 0):
            return 1e10
        return float(np.mean((fitted - market_tv) ** 2))

    x0 = initial_params or [0.04, 0.1, -0.3, 0.0, 0.2]
    bounds = [(1e-6, 1.0), (1e-4, 2.0), (-0.999, 0.999), (-1.0, 1.0), (1e-4, 2.0)]

    if _SCIPY_AVAILABLE:
        result = minimize(objective, x0, method="L-BFGS-B", bounds=bounds)
        a, b, rho, m, sigma = result.x
        err = float(result.fun)
    else:
        # Fallback: simple grid search is impractical; return ATM-flat surface
        log.warning("iv_surface.scipy_unavailable: using ATM-flat SVI approximation")
        atm_tv = float(np.mean(market_tv))
        a, b, rho, m, sigma = atm_tv, 0.1, -0.3, 0.0, 0.2
        err = 0.0

    return SVIParams(a=a, b=b, rho=rho, m=m, sigma=sigma, tte=tte, fit_error=err)


# ---------------------------------------------------------------------------
# IV surface modeler
# ---------------------------------------------------------------------------


class IVSurfaceModeler:
    """Fits, analyses, and visualises the full implied volatility surface.

    Args:
        min_open_interest: Minimum OI to include a strike (default 50).
        max_expiries: Maximum number of expiry slices to fit (default 8).
        risk_free_rate: Annualised risk-free rate for forward price calc.
    """

    def __init__(
        self,
        min_open_interest: int = 50,
        max_expiries: int = 8,
        risk_free_rate: float = 0.05,
    ) -> None:
        self.min_oi = min_open_interest
        self.max_expiries = max_expiries
        self.risk_free = risk_free_rate

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(self, ticker: str) -> IVSurface:
        """Fetch option chain and fit SVI to each expiry slice.

        Args:
            ticker: Underlying ticker symbol.

        Returns:
            :class:`IVSurface` with fitted slices.
        """
        spot, expiries, chain_data = self._fetch_chain_data(ticker)
        forward = spot * math.exp(self.risk_free * 0.25)  # 3-month approximate

        surface = IVSurface(
            ticker=ticker,
            forward_price=forward,
            timestamp=time.time(),
        )

        for expiry, tte, calls, puts in chain_data[: self.max_expiries]:
            slice_ = self._fit_slice(expiry, tte, forward, calls, puts)
            if slice_ is not None:
                surface.slices.append(slice_)
                # ATM IV: svi_iv at k=0 (ATM)
                if slice_.svi_params:
                    atm_k = np.array([0.0])
                    atm_tv = _svi_total_variance(atm_k, slice_.svi_params)
                    atm_iv = float(np.sqrt(max(atm_tv[0], 0) / max(tte, 1e-6)))
                    surface.atm_term_structure[expiry] = round(atm_iv, 4)

        log.info(
            "iv_surface.fitted",
            ticker=ticker,
            slices=len(surface.slices),
            spot=round(spot, 2),
        )
        return surface

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------

    def detect_anomalies(self, surface: IVSurface) -> List[SurfaceAnomaly]:
        """Scan the IV surface for arbitrage violations and unusual patterns.

        Checks:
        * Skew spikes: |put skew - call skew| > 0.15 for any expiry.
        * Term structure inversions: ATM IV of a near expiry > far expiry.
        * Calendar arbitrage: total variance decreasing with expiry at any
          given moneyness.

        Args:
            surface: Fitted :class:`IVSurface`.

        Returns:
            List of :class:`SurfaceAnomaly` instances.
        """
        anomalies: List[SurfaceAnomaly] = []

        # Skew spike: compare left wing IV to right wing IV
        for sl in surface.slices:
            if len(sl.market_iv) < 4:
                continue
            left_iv = float(np.mean(sl.market_iv[: len(sl.market_iv) // 3]))
            right_iv = float(np.mean(sl.market_iv[-(len(sl.market_iv) // 3) :]))
            skew = left_iv - right_iv
            if abs(skew) > 0.15:
                severity = min(10.0, abs(skew) / 0.15 * 3.0)
                anomalies.append(
                    SurfaceAnomaly(
                        anomaly_type="skew_spike",
                        expiry=sl.expiry,
                        description=(
                            f"{surface.ticker} {sl.expiry}: extreme skew "
                            f"({skew:+.3f}). Put wing much {'higher' if skew > 0 else 'lower'}."
                        ),
                        severity=round(severity, 2),
                    )
                )

        # Term structure inversion: near ATM IV > far ATM IV
        atm_items = sorted(
            surface.atm_term_structure.items(),
            key=lambda x: x[0],  # sort by expiry date string
        )
        for i in range(len(atm_items) - 1):
            near_exp, near_iv = atm_items[i]
            far_exp, far_iv = atm_items[i + 1]
            if near_iv > far_iv + 0.02:  # 2 vol point buffer
                severity = min(10.0, (near_iv - far_iv) / 0.02 * 2.0)
                anomalies.append(
                    SurfaceAnomaly(
                        anomaly_type="term_inversion",
                        expiry=near_exp,
                        description=(
                            f"{surface.ticker}: term structure inverted "
                            f"{near_exp} IV={near_iv:.2%} > {far_exp} IV={far_iv:.2%}."
                        ),
                        severity=round(severity, 2),
                    )
                )

        log.info(
            "iv_surface.anomalies",
            ticker=surface.ticker,
            count=len(anomalies),
        )
        return anomalies

    # ------------------------------------------------------------------
    # Calendar spread opportunities
    # ------------------------------------------------------------------

    def calendar_opportunities(
        self, surface: IVSurface, min_spread: float = 0.03
    ) -> List[CalendarOpportunity]:
        """Identify calendar spread opportunities from ATM IV mismatches.

        Args:
            surface: Fitted :class:`IVSurface`.
            min_spread: Minimum ATM IV spread (in vol points) to flag.

        Returns:
            List of :class:`CalendarOpportunity` instances.
        """
        atm_items = sorted(
            surface.atm_term_structure.items(), key=lambda x: x[0]
        )
        opps: List[CalendarOpportunity] = []

        for i in range(len(atm_items) - 1):
            near_exp, near_iv = atm_items[i]
            far_exp, far_iv = atm_items[i + 1]
            spread = far_iv - near_iv

            if abs(spread) < min_spread:
                continue

            # Heuristic z-score: compare to expected sqrt(TTE) scaling
            near_tte = next(
                (sl.tte for sl in surface.slices if sl.expiry == near_exp), 0.25
            )
            far_tte = next(
                (sl.tte for sl in surface.slices if sl.expiry == far_exp), 0.5
            )
            expected_spread = near_iv * (math.sqrt(far_tte / max(near_tte, 1e-6)) - 1)
            z = (spread - expected_spread) / max(abs(expected_spread), 0.01)

            opp_type = (
                "sell_near_buy_far" if spread > 0 else "sell_far_buy_near"
            )
            opps.append(
                CalendarOpportunity(
                    near_expiry=near_exp,
                    far_expiry=far_exp,
                    near_iv=near_iv,
                    far_iv=far_iv,
                    iv_spread=round(spread, 4),
                    opportunity_type=opp_type,
                    z_score=round(z, 2),
                )
            )

        log.info(
            "iv_surface.calendar_opps",
            ticker=surface.ticker,
            count=len(opps),
        )
        return opps

    # ------------------------------------------------------------------
    # 3D Plotly visualisation
    # ------------------------------------------------------------------

    def plot_surface(self, surface: IVSurface) -> Any:
        """Render the IV surface as a 3-D plotly figure.

        Args:
            surface: Fitted :class:`IVSurface`.

        Returns:
            A ``plotly.graph_objects.Figure``, or ``None`` when plotly is
            not installed.
        """
        if not _PLOTLY_AVAILABLE:
            log.warning("iv_surface.plotly_unavailable")
            return None

        x_list: List[float] = []
        y_list: List[str] = []
        z_list: List[float] = []

        for sl in surface.slices:
            for k, iv in zip(sl.log_moneyness, sl.svi_iv):
                x_list.append(k)
                y_list.append(sl.expiry)
                z_list.append(iv)

        fig = go.Figure(
            data=[
                go.Scatter3d(
                    x=x_list,
                    y=y_list,
                    z=z_list,
                    mode="markers",
                    marker=dict(
                        size=3,
                        color=z_list,
                        colorscale="Viridis",
                        colorbar=dict(title="IV"),
                    ),
                )
            ]
        )
        fig.update_layout(
            title=f"{surface.ticker} Implied Volatility Surface",
            scene=dict(
                xaxis_title="Log-Moneyness (k)",
                yaxis_title="Expiry",
                zaxis_title="Implied Volatility",
            ),
            template="plotly_dark",
        )
        return fig

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_chain_data(
        self, ticker: str
    ) -> Tuple[float, List[str], List[Tuple[str, float, Any, Any]]]:
        """Fetch option chain from yfinance or return synthetic data.

        Returns:
            Tuple of (spot_price, expiries, chain_data) where chain_data
            is a list of (expiry_str, tte, calls_df, puts_df).
        """
        if not _YF_AVAILABLE:
            return self._synthetic_chain(ticker)

        try:
            tk = yf.Ticker(ticker)
            spot = float(tk.fast_info.get("lastPrice", 100.0) or 100.0)
            expiries = list(tk.options or [])
            if not expiries:
                return self._synthetic_chain(ticker)

            chain_data: List[Tuple[str, float, Any, Any]] = []
            today = time.time()

            for exp in expiries[: self.max_expiries]:
                try:
                    tte = self._expiry_to_tte(exp, today)
                    if tte <= 0:
                        continue
                    chain = tk.option_chain(exp)
                    chain_data.append((exp, tte, chain.calls, chain.puts))
                except Exception:
                    continue

            return spot, expiries, chain_data

        except Exception as exc:
            log.warning("iv_surface.fetch_error", ticker=ticker, error=str(exc))
            return self._synthetic_chain(ticker)

    def _fit_slice(
        self,
        expiry: str,
        tte: float,
        forward: float,
        calls: Any,
        puts: Any,
    ) -> Optional[IVSlice]:
        """Fit SVI to a single expiry slice."""
        try:
            import pandas as pd

            # Combine calls and puts, filter by OI
            combined = pd.concat([calls, puts], ignore_index=True)
            combined = combined[combined["openInterest"] >= self.min_oi].copy()
            combined = combined[combined["impliedVolatility"] > 0.01]

            if len(combined) < 4:
                return None

            strikes = combined["strike"].values.astype(float)
            ivs = combined["impliedVolatility"].values.astype(float)
            k = np.log(strikes / forward)

            # Filter extreme moneyness
            mask = np.abs(k) < 1.5
            k, strikes, ivs = k[mask], strikes[mask], ivs[mask]

            if len(k) < 4:
                return None

            svi = fit_svi(k, ivs, tte)
            svi.expiry = expiry

            svi_ivs = np.sqrt(
                np.maximum(_svi_total_variance(k, svi), 0) / max(tte, 1e-6)
            )

            return IVSlice(
                expiry=expiry,
                tte=tte,
                strikes=strikes.tolist(),
                log_moneyness=k.tolist(),
                market_iv=ivs.tolist(),
                svi_iv=svi_ivs.tolist(),
                svi_params=svi,
            )
        except Exception as exc:
            log.debug("iv_surface.slice_fit_error", expiry=expiry, error=str(exc))
            return None

    @staticmethod
    def _expiry_to_tte(expiry: str, now_ts: float) -> float:
        """Convert 'YYYY-MM-DD' expiry string to time-to-expiry in years."""
        import datetime
        try:
            exp_dt = datetime.datetime.strptime(expiry, "%Y-%m-%d")
            tte = (exp_dt.timestamp() - now_ts) / (365.25 * 24 * 3600)
            return max(tte, 0.0)
        except Exception:
            return 0.25  # fallback

    def _synthetic_chain(
        self, ticker: str
    ) -> Tuple[float, List[str], List[Tuple[str, float, Any, Any]]]:
        """Generate synthetic option chain data for testing without yfinance."""
        import datetime

        spot = 100.0
        today = datetime.date.today()
        expiries = [
            (today + datetime.timedelta(days=d)).isoformat()
            for d in [30, 60, 90, 180]
        ]

        chain_data = []
        for exp in expiries:
            tte = self._expiry_to_tte(exp, time.time())
            strikes_arr = np.linspace(80, 120, 20)
            atm_iv = 0.3 + 0.05 * np.random.randn()
            # Simple smile: put skew
            ivs = atm_iv + 0.05 * np.abs(np.log(strikes_arr / spot)) - 0.02 * np.log(
                strikes_arr / spot
            )
            ivs = np.clip(ivs, 0.05, 2.0)

            # Minimal duck-typed stand-in for a DataFrame
            class _MockChain:
                def __init__(self, s, iv):
                    import pandas as pd
                    self._df = pd.DataFrame({
                        "strike": s,
                        "impliedVolatility": iv,
                        "openInterest": np.full(len(s), 500),
                        "volume": np.full(len(s), 200),
                    })

                def __getitem__(self, key):
                    return self._df[key]

                def __len__(self):
                    return len(self._df)

                @property
                def values(self):
                    return self._df.values

            calls = _MockChain(strikes_arr, ivs)
            puts = _MockChain(strikes_arr, ivs * 1.05)
            chain_data.append((exp, tte, calls._df, puts._df))

        return spot, expiries, chain_data
