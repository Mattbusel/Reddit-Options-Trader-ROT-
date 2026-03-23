"""Implied Volatility Rank Calculator.

Computes IV rank and IV percentile for any optionable symbol by fetching the
live options chain via yfinance and inverting ATM option prices to implied
volatility using Newton-Raphson BSM inversion.

IV Rank formula::

    iv_rank = (current_iv - iv_52w_low) / (iv_52w_high - iv_52w_low) * 100

IV Percentile: fraction of trading days in the past year where IV was below
the current reading (requires a rolling IV history).

Classification:

- ``IV_CRUSH_ZONE``: iv_rank > 80 — high IV, premium sellers prefer this
- ``NORMAL``: 20 <= iv_rank <= 80
- ``IV_EXPANSION_ZONE``: iv_rank < 20 — low IV, option buyers prefer this

Example::

    from rot.analytics.iv_rank import IVRankCalculator

    calc = IVRankCalculator()
    data = calc.analyze("AAPL")
    print(data.iv_rank)          # e.g. 63.4
    print(data.classification)   # IVRegime.NORMAL
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SQRT_2PI = math.sqrt(2 * math.pi)
_DAYS_PER_YEAR = 252
_BSM_MAX_ITER = 50
_BSM_TOL = 1e-8
_BSM_MIN_VEGA = 1e-12


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class IVRegime(str, Enum):
    IV_CRUSH_ZONE = "IV_CRUSH_ZONE"       # iv_rank > 80
    NORMAL = "NORMAL"                     # 20 <= iv_rank <= 80
    IV_EXPANSION_ZONE = "IV_EXPANSION_ZONE"  # iv_rank < 20


# ---------------------------------------------------------------------------
# IVData
# ---------------------------------------------------------------------------

@dataclass
class IVData:
    """Implied volatility analytics for a single symbol.

    Attributes:
        symbol: Ticker symbol.
        current_iv: Current ATM implied volatility (0–1 annualised fraction).
        iv_52w_high: Highest IV observed in the trailing 52 weeks.
        iv_52w_low: Lowest IV observed in the trailing 52 weeks.
        iv_rank: IV rank 0–100 relative to the 52-week range.
        iv_percentile: Fraction of days (0–100) where IV was below current.
        iv_mean_30d: Mean IV over the past 30 trading days.
        classification: :class:`IVRegime` label.
        timestamp: Unix epoch of the computation.
    """

    symbol: str
    current_iv: float
    iv_52w_high: float
    iv_52w_low: float
    iv_rank: float
    iv_percentile: float
    iv_mean_30d: float
    classification: IVRegime
    timestamp: float


# ---------------------------------------------------------------------------
# Black-Scholes-Merton helpers
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _bsm_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes-Merton call price."""
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K * math.exp(-r * T))
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def _bsm_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """BSM vega (dC/dsigma)."""
    if T <= 0 or sigma <= 0:
        return _BSM_MIN_VEGA
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return S * _norm_pdf(d1) * math.sqrt(T)


def _implied_vol_newton(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.05,
    sigma0: float = 0.3,
) -> Optional[float]:
    """Newton-Raphson inversion of BSM for implied volatility.

    Args:
        market_price: Observed option mid-price.
        S: Underlying spot price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate (default 5 %).
        sigma0: Initial guess for IV.

    Returns:
        Implied volatility as an annualised fraction, or ``None`` if the
        solver does not converge.
    """
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return None

    sigma = sigma0
    for _ in range(_BSM_MAX_ITER):
        price = _bsm_call_price(S, K, T, r, sigma)
        vega = _bsm_vega(S, K, T, r, sigma)
        if vega < _BSM_MIN_VEGA:
            break
        diff = price - market_price
        sigma -= diff / vega
        sigma = max(1e-6, min(sigma, 5.0))   # clamp to [0.0001, 500 %]
        if abs(diff) < _BSM_TOL:
            return sigma

    return None


# ---------------------------------------------------------------------------
# IVRankCalculator
# ---------------------------------------------------------------------------

class IVRankCalculator:
    """Computes IV rank and IV percentile for options.

    Args:
        risk_free_rate: Annualised risk-free rate used in BSM inversion
            (default 0.05 = 5 %).
        history_days: Number of trading days of IV history to fetch for
            percentile and mean calculations (default 252 = 1 year).
    """

    def __init__(
        self,
        risk_free_rate: float = 0.05,
        history_days: int = _DAYS_PER_YEAR,
    ) -> None:
        self._rfr = risk_free_rate
        self._history_days = history_days

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(iv_rank: float) -> IVRegime:
        if iv_rank > 80.0:
            return IVRegime.IV_CRUSH_ZONE
        if iv_rank < 20.0:
            return IVRegime.IV_EXPANSION_ZONE
        return IVRegime.NORMAL

    @staticmethod
    def _iv_rank(current: float, low: float, high: float) -> float:
        denom = high - low
        if denom < 1e-10:
            return 50.0
        return (current - low) / denom * 100.0

    @staticmethod
    def _iv_percentile(current: float, history: List[float]) -> float:
        if not history:
            return 50.0
        below = sum(1 for v in history if v < current)
        return below / len(history) * 100.0

    def _fetch_atm_iv(self, symbol: str) -> Optional[float]:
        """Fetch ATM IV from yfinance options chain via Newton-Raphson BSM.

        Returns the median IV of the two nearest-ATM call options for the
        nearest available expiry with > 7 DTE.  Returns ``None`` on failure.
        """
        try:
            import yfinance as yf  # type: ignore[import]

            ticker = yf.Ticker(symbol)
            spot_info = ticker.fast_info
            spot = float(getattr(spot_info, "last_price", 0) or 0)
            if spot <= 0:
                hist = ticker.history(period="1d")
                if hist.empty:
                    return None
                spot = float(hist["Close"].iloc[-1])

            expiries = ticker.options
            if not expiries:
                return None

            # Pick the first expiry with > 7 calendar days
            import datetime

            target_exp = None
            for exp_str in expiries:
                exp_date = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte = (exp_date - datetime.date.today()).days
                if dte >= 7:
                    target_exp = exp_str
                    break

            if target_exp is None:
                target_exp = expiries[0]

            chain = ticker.option_chain(target_exp)
            calls = chain.calls
            if calls.empty:
                return None

            calls = calls.copy()
            calls["moneyness"] = abs(calls["strike"] - spot)
            calls = calls.sort_values("moneyness").head(4)

            import datetime as _dt
            exp_date = _dt.datetime.strptime(target_exp, "%Y-%m-%d").date()
            T = max(1 / _DAYS_PER_YEAR, (_dt.date.today() - exp_date).days / -365.0)

            ivs: List[float] = []
            for _, row in calls.iterrows():
                mid = (row.get("bid", 0) + row.get("ask", 0)) / 2.0
                if mid <= 0:
                    mid = row.get("lastPrice", 0)
                iv = _implied_vol_newton(mid, spot, float(row["strike"]), T, self._rfr)
                if iv and 0.01 <= iv <= 5.0:
                    ivs.append(iv)

            if not ivs:
                # Fall back to yfinance's own impliedVolatility field
                raw_ivs = calls["impliedVolatility"].dropna().tolist()
                ivs = [v for v in raw_ivs if 0.01 <= v <= 5.0]

            return float(sum(ivs) / len(ivs)) if ivs else None

        except Exception as exc:
            log.warning("Failed to fetch ATM IV for %s: %s", symbol, exc)
            return None

    def _fetch_iv_history(self, symbol: str) -> List[float]:
        """Fetch a rolling IV series via yfinance historical data.

        Approximates IV history from historical realized volatility scaled by
        a 1.1x VRP factor where true IV history is unavailable.
        """
        try:
            import yfinance as yf  # type: ignore[import]

            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1y", interval="1d")
            if hist.empty or len(hist) < 20:
                return []

            closes = hist["Close"].values.tolist()
            returns = [
                math.log(closes[i] / closes[i - 1])
                for i in range(1, len(closes))
                if closes[i - 1] > 0
            ]

            # Rolling 21-day realized vol annualised — proxy for IV history
            window = 21
            iv_series: List[float] = []
            for i in range(window, len(returns) + 1):
                window_rets = returns[i - window : i]
                mean_r = sum(window_rets) / window
                variance = sum((r - mean_r) ** 2 for r in window_rets) / (window - 1)
                rv = math.sqrt(variance * _DAYS_PER_YEAR)
                # Apply rough VRP premium
                iv_series.append(rv * 1.1)

            return iv_series

        except Exception as exc:
            log.warning("Failed to fetch IV history for %s: %s", symbol, exc)
            return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, symbol: str) -> IVData:
        """Compute IV rank and related metrics for *symbol*.

        Fetches the live options chain via yfinance, extracts ATM IV via
        Newton-Raphson BSM inversion, and computes IV rank, IV percentile,
        and 30-day mean IV from historical realized volatility.

        Args:
            symbol: Ticker symbol (e.g. ``"AAPL"``).

        Returns:
            :class:`IVData` with all computed metrics.  Falls back to
            estimated values if live data is unavailable.
        """
        current_iv = self._fetch_atm_iv(symbol)
        iv_history = self._fetch_iv_history(symbol)

        # Fallback values if live fetch fails
        if current_iv is None:
            if iv_history:
                current_iv = iv_history[-1]
            else:
                current_iv = 0.30

        if iv_history:
            iv_52w_high = max(iv_history)
            iv_52w_low = min(iv_history)
            days_30 = iv_history[-30:] if len(iv_history) >= 30 else iv_history
            iv_mean_30d = sum(days_30) / len(days_30)
            iv_percentile = self._iv_percentile(current_iv, iv_history)
        else:
            iv_52w_high = current_iv * 1.5
            iv_52w_low = current_iv * 0.5
            iv_mean_30d = current_iv
            iv_percentile = 50.0

        iv_rank = self._iv_rank(current_iv, iv_52w_low, iv_52w_high)
        iv_rank = max(0.0, min(100.0, iv_rank))

        return IVData(
            symbol=symbol,
            current_iv=current_iv,
            iv_52w_high=iv_52w_high,
            iv_52w_low=iv_52w_low,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            iv_mean_30d=iv_mean_30d,
            classification=self._classify(iv_rank),
            timestamp=time.time(),
        )

    def analyze_batch(self, symbols: List[str]) -> List[IVData]:
        """Analyze multiple symbols, skipping failures.

        Args:
            symbols: List of ticker symbols.

        Returns:
            List of :class:`IVData` for symbols that succeeded.
        """
        results = []
        for sym in symbols:
            try:
                results.append(self.analyze(sym))
            except Exception as exc:
                log.warning("IV analysis failed for %s: %s", sym, exc)
        return results
