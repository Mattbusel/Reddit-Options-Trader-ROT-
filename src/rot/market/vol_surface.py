"""Volatility surface modelling for the ROT signal pipeline.

Builds implied-volatility surfaces from options chain data, computes
IV rank/percentile metrics, and classifies the current volatility regime.

Classes
-------
VolatilitySmile
    Fits a smile (IV vs strike) for a single expiration.
ImpliedVolatilitySurface
    Builds the full IV surface (strike × expiry) from an options chain.
IVRank
    IV rank percentile: where current IV sits in its 52-week range.
IVPercentile
    IV percentile: fraction of days in the past year with lower IV.
TermStructure
    VIX-like term structure of ATM IV across multiple expirations.
VolatilityRegime
    Classifies the current IV environment: high / normal / low.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SmilePoint:
    """Single point on a volatility smile."""

    strike: float
    iv: float          # implied volatility as a decimal (e.g. 0.25 = 25%)
    moneyness: float   # strike / spot  (1.0 = ATM)
    delta_approx: Optional[float] = None   # rough Black-Scholes delta if available


@dataclass(frozen=True)
class VolatilitySmileResult:
    """Output of VolatilitySmile.fit()."""

    symbol: str
    expiry: str
    spot_price: float
    points: List[SmilePoint]
    atm_iv: Optional[float]    # IV at closest-to-ATM strike
    skew: Optional[float]      # put_wing_iv - call_wing_iv  (positive = put skew)
    wing_spread: Optional[float]  # call_wing_iv + put_wing_iv  (curvature)
    n_strikes: int


@dataclass(frozen=True)
class IVSurface:
    """Full implied-volatility surface."""

    symbol: str
    spot_price: float
    smiles: Dict[str, VolatilitySmileResult]  # expiry → smile
    term_structure: List[Tuple[str, float]]   # [(expiry, atm_iv), ...]  sorted near→far
    atm_iv_nearest: Optional[float]           # ATM IV of nearest expiry
    surface_skew: Optional[float]             # average skew across expirations


@dataclass(frozen=True)
class IVRankResult:
    """Output of IVRank.compute()."""

    symbol: str
    current_iv: float
    iv_52w_high: float
    iv_52w_low: float
    iv_rank: float     # (current - low) / (high - low)  in [0, 1]
    iv_rank_pct: float  # iv_rank * 100


@dataclass(frozen=True)
class IVPercentileResult:
    """Output of IVPercentile.compute()."""

    symbol: str
    current_iv: float
    iv_percentile: float    # fraction of days in history with IV < current  [0, 1]
    iv_percentile_pct: float
    n_observations: int


@dataclass(frozen=True)
class TermStructureResult:
    """Output of TermStructure.build()."""

    symbol: str
    spot_price: float
    term_points: List[Tuple[str, float]]   # [(expiry, atm_iv), ...]
    contango: bool    # True if near-term IV < far-term IV (normal)
    backwardation: bool  # True if near-term IV > far-term IV (stressed)
    slope: Optional[float]  # linear slope of IV vs expiry index (+ = contango)


@dataclass(frozen=True)
class VolatilityRegimeResult:
    """Output of VolatilityRegime.classify()."""

    symbol: str
    current_iv: float
    iv_rank: float
    regime: str         # "high" | "normal" | "low"
    strategy_bias: str  # "sell_premium" | "buy_premium" | "neutral"
    confidence: float   # 0.0-1.0


# ---------------------------------------------------------------------------
# VolatilitySmile
# ---------------------------------------------------------------------------


class VolatilitySmile:
    """Fits a volatility smile for a single options expiration.

    Parameters
    ----------
    wing_moneyness:
        Moneyness (strike/spot) cut-off for wing classification.
        Strikes below ``1 - wing_moneyness`` are the put wing;
        strikes above ``1 + wing_moneyness`` are the call wing.
    """

    def __init__(self, wing_moneyness: float = 0.05) -> None:
        if not (0.0 < wing_moneyness < 0.5):
            raise ValueError("wing_moneyness must be in (0, 0.5)")
        self.wing_moneyness = wing_moneyness

    def fit(
        self,
        symbol: str,
        expiry: str,
        spot_price: float,
        strikes: List[float],
        ivs: List[float],
    ) -> VolatilitySmileResult:
        """Fit a smile from parallel strike and IV lists.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        expiry:
            Expiry date string (``YYYY-MM-DD``).
        spot_price:
            Current underlying price.
        strikes:
            List of strike prices (float).
        ivs:
            List of implied volatilities corresponding to each strike.
            Values must be decimals (0.25 = 25%), not percentages.

        Returns
        -------
        VolatilitySmileResult
        """
        if len(strikes) != len(ivs):
            raise ValueError("strikes and ivs must have equal length")

        if spot_price <= 0:
            raise ValueError("spot_price must be positive")

        # Build smile points, filtering invalid IVs
        points: List[SmilePoint] = []
        for k, iv in sorted(zip(strikes, ivs), key=lambda x: x[0]):
            if iv is None or iv <= 0 or iv > 10.0:  # sanity: IV between 0% and 1000%
                continue
            moneyness = k / spot_price
            points.append(SmilePoint(
                strike=round(float(k), 4),
                iv=round(float(iv), 6),
                moneyness=round(moneyness, 6),
            ))

        if not points:
            return VolatilitySmileResult(
                symbol=symbol,
                expiry=expiry,
                spot_price=spot_price,
                points=[],
                atm_iv=None,
                skew=None,
                wing_spread=None,
                n_strikes=0,
            )

        # ATM IV: closest to moneyness = 1.0
        atm_point = min(points, key=lambda p: abs(p.moneyness - 1.0))
        atm_iv = atm_point.iv

        # Skew: average put wing IV - average call wing IV
        put_wing = [p.iv for p in points if p.moneyness < (1.0 - self.wing_moneyness)]
        call_wing = [p.iv for p in points if p.moneyness > (1.0 + self.wing_moneyness)]
        skew: Optional[float] = None
        wing_spread: Optional[float] = None

        if put_wing and call_wing:
            avg_put = statistics.mean(put_wing)
            avg_call = statistics.mean(call_wing)
            skew = round(avg_put - avg_call, 6)
            wing_spread = round(avg_put + avg_call, 6)

        return VolatilitySmileResult(
            symbol=symbol,
            expiry=expiry,
            spot_price=spot_price,
            points=points,
            atm_iv=round(atm_iv, 6),
            skew=skew,
            wing_spread=wing_spread,
            n_strikes=len(points),
        )


# ---------------------------------------------------------------------------
# ImpliedVolatilitySurface
# ---------------------------------------------------------------------------


class ImpliedVolatilitySurface:
    """Builds a full IV surface (strike × expiry matrix) from options chain data.

    Accepts the raw options chain structure produced by ``MarketEnricher``
    or any compatible dict structure.

    Parameters
    ----------
    wing_moneyness:
        Passed to the underlying ``VolatilitySmile`` fitter.
    """

    def __init__(self, wing_moneyness: float = 0.05) -> None:
        self._smile_fitter = VolatilitySmile(wing_moneyness=wing_moneyness)

    def build(
        self,
        symbol: str,
        spot_price: float,
        expiry_chains: Dict[str, Dict[str, Any]],
    ) -> IVSurface:
        """Build IV surface from a dict of expiry → options chain data.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        spot_price:
            Current underlying price.
        expiry_chains:
            Mapping ``{expiry_str: {"strikes": [...], "ivs": [...]}}``.
            Each value may also contain ``"calls"`` / ``"puts"`` sub-dicts
            with ``"strike"`` and ``"impliedVolatility"`` keys (yfinance style).

        Returns
        -------
        IVSurface
        """
        smiles: Dict[str, VolatilitySmileResult] = {}

        for expiry, chain in sorted(expiry_chains.items()):
            strikes, ivs = self._extract_strikes_ivs(chain, spot_price)
            if not strikes:
                continue
            smile = self._smile_fitter.fit(
                symbol=symbol,
                expiry=expiry,
                spot_price=spot_price,
                strikes=strikes,
                ivs=ivs,
            )
            smiles[expiry] = smile

        # Build term structure from ATM IVs
        term_pts: List[Tuple[str, float]] = [
            (exp, s.atm_iv)
            for exp, s in smiles.items()
            if s.atm_iv is not None
        ]
        term_pts.sort(key=lambda x: x[0])

        atm_nearest = term_pts[0][1] if term_pts else None

        # Surface-level skew (average across expirations)
        skews = [s.skew for s in smiles.values() if s.skew is not None]
        surface_skew = statistics.mean(skews) if skews else None

        return IVSurface(
            symbol=symbol,
            spot_price=spot_price,
            smiles=smiles,
            term_structure=term_pts,
            atm_iv_nearest=atm_nearest,
            surface_skew=round(surface_skew, 6) if surface_skew is not None else None,
        )

    @staticmethod
    def _extract_strikes_ivs(
        chain: Dict[str, Any],
        spot_price: float,
    ) -> Tuple[List[float], List[float]]:
        """Extract strike/IV lists from various chain dict shapes."""
        # Direct lists
        if "strikes" in chain and "ivs" in chain:
            return list(chain["strikes"]), list(chain["ivs"])

        # yfinance-style: calls/puts DataFrames serialised as records
        strikes: List[float] = []
        ivs: List[float] = []
        for side in ("calls", "puts"):
            records = chain.get(side, [])
            if not isinstance(records, list):
                continue
            for row in records:
                k = row.get("strike")
                iv = row.get("impliedVolatility") or row.get("iv")
                if k and iv and k > 0 and iv > 0:
                    strikes.append(float(k))
                    ivs.append(float(iv))

        # Deduplicate by averaging IVs at the same strike
        if strikes:
            strike_iv: Dict[float, List[float]] = {}
            for k, iv in zip(strikes, ivs):
                strike_iv.setdefault(k, []).append(iv)
            strikes = sorted(strike_iv.keys())
            ivs = [statistics.mean(strike_iv[k]) for k in strikes]

        return strikes, ivs


# ---------------------------------------------------------------------------
# IVRank
# ---------------------------------------------------------------------------


class IVRank:
    """IV Rank: where the current IV sits within its 52-week high-low range.

    IVR = (current_iv - 52w_low) / (52w_high - 52w_low)

    IVR = 1.0 → IV is at its 52-week high.
    IVR = 0.0 → IV is at its 52-week low.

    An IVR above 0.50 generally favours *selling* premium;
    below 0.50 generally favours *buying* premium.
    """

    def compute(
        self,
        symbol: str,
        current_iv: float,
        iv_history: Sequence[float],
    ) -> IVRankResult:
        """Compute IVR from the current IV and a history of IV observations.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        current_iv:
            Current ATM implied volatility (decimal, e.g. 0.30 = 30%).
        iv_history:
            Sequence of daily (or periodic) IV observations over the past
            year (52 weeks / ~252 trading days).

        Returns
        -------
        IVRankResult
        """
        if current_iv <= 0:
            raise ValueError("current_iv must be positive")
        if not iv_history:
            raise ValueError("iv_history must not be empty")

        valid = [v for v in iv_history if v and v > 0]
        if not valid:
            raise ValueError("iv_history contains no valid positive values")

        iv_high = max(valid)
        iv_low = min(valid)

        if iv_high <= iv_low:
            rank = 0.5  # degenerate case: all values identical
        else:
            rank = (current_iv - iv_low) / (iv_high - iv_low)
            rank = max(0.0, min(1.0, rank))

        return IVRankResult(
            symbol=symbol,
            current_iv=current_iv,
            iv_52w_high=round(iv_high, 6),
            iv_52w_low=round(iv_low, 6),
            iv_rank=round(rank, 4),
            iv_rank_pct=round(rank * 100.0, 2),
        )


# ---------------------------------------------------------------------------
# IVPercentile
# ---------------------------------------------------------------------------


class IVPercentile:
    """IV Percentile: the fraction of historical days with IV *below* current.

    Unlike IVRank (which only uses the range extremes), IVP uses the full
    distribution of past IV values.

    IVP = 0.95 → current IV is higher than 95% of past days.
    IVP = 0.10 → current IV is lower than 90% of past days.
    """

    def compute(
        self,
        symbol: str,
        current_iv: float,
        iv_history: Sequence[float],
    ) -> IVPercentileResult:
        """Compute IV percentile.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        current_iv:
            Current ATM implied volatility (decimal).
        iv_history:
            Historical IV observations (typically ~252 trading days).

        Returns
        -------
        IVPercentileResult
        """
        if current_iv <= 0:
            raise ValueError("current_iv must be positive")
        if not iv_history:
            raise ValueError("iv_history must not be empty")

        valid = [v for v in iv_history if v and v > 0]
        n = len(valid)
        if n == 0:
            raise ValueError("iv_history contains no valid positive values")

        below = sum(1 for v in valid if v < current_iv)
        pct = below / n

        return IVPercentileResult(
            symbol=symbol,
            current_iv=current_iv,
            iv_percentile=round(pct, 4),
            iv_percentile_pct=round(pct * 100.0, 2),
            n_observations=n,
        )


# ---------------------------------------------------------------------------
# TermStructure
# ---------------------------------------------------------------------------


class TermStructure:
    """IV term structure: ATM IV by expiry date (VIX-like curve).

    Classifies the curve as contango (normal) or backwardation (stressed).
    """

    def build(
        self,
        symbol: str,
        spot_price: float,
        expiry_atm_ivs: List[Tuple[str, float]],
    ) -> TermStructureResult:
        """Build term structure from a list of (expiry, atm_iv) pairs.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        spot_price:
            Current underlying price.
        expiry_atm_ivs:
            List of ``(expiry_date_str, atm_iv)`` tuples.  Need not be sorted.

        Returns
        -------
        TermStructureResult
        """
        if not expiry_atm_ivs:
            return TermStructureResult(
                symbol=symbol,
                spot_price=spot_price,
                term_points=[],
                contango=False,
                backwardation=False,
                slope=None,
            )

        # Sort by expiry (lexicographic on ISO dates works correctly)
        pts = sorted(
            [(exp, iv) for exp, iv in expiry_atm_ivs if iv and iv > 0],
            key=lambda x: x[0],
        )

        if not pts:
            return TermStructureResult(
                symbol=symbol,
                spot_price=spot_price,
                term_points=[],
                contango=False,
                backwardation=False,
                slope=None,
            )

        contango = False
        backwardation = False
        slope: Optional[float] = None

        if len(pts) >= 2:
            near_iv = pts[0][1]
            far_iv = pts[-1][1]
            contango = far_iv > near_iv
            backwardation = near_iv > far_iv

            # Linear slope of IV vs index position
            n = len(pts)
            x = list(range(n))
            y = [iv for _, iv in pts]
            mx, my = sum(x) / n, sum(y) / n
            ssxx = sum((xi - mx) ** 2 for xi in x)
            ssxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
            if ssxx > 1e-12:
                slope = round(ssxy / ssxx, 6)

        return TermStructureResult(
            symbol=symbol,
            spot_price=spot_price,
            term_points=pts,
            contango=contango,
            backwardation=backwardation,
            slope=slope,
        )


# ---------------------------------------------------------------------------
# VolatilityRegime
# ---------------------------------------------------------------------------


class VolatilityRegime:
    """Classifies the current volatility regime from IVR.

    Regime definitions
    ------------------
    - ``"high"``   : IVR >= ``high_threshold``   → favour selling premium
    - ``"low"``    : IVR <= ``low_threshold``    → favour buying premium
    - ``"normal"`` : otherwise                  → neutral

    Parameters
    ----------
    high_threshold:
        IVR (0-1) above which the regime is "high".  Default 0.60.
    low_threshold:
        IVR (0-1) below which the regime is "low".  Default 0.30.
    """

    def __init__(
        self,
        high_threshold: float = 0.60,
        low_threshold: float = 0.30,
    ) -> None:
        if high_threshold <= low_threshold:
            raise ValueError("high_threshold must be greater than low_threshold")
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold

    def classify(
        self,
        symbol: str,
        current_iv: float,
        iv_history: Sequence[float],
    ) -> VolatilityRegimeResult:
        """Classify the volatility regime.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        current_iv:
            Current ATM IV (decimal).
        iv_history:
            Historical IV observations for IVR calculation.

        Returns
        -------
        VolatilityRegimeResult
        """
        ivr_calc = IVRank()
        ivr_result = ivr_calc.compute(symbol, current_iv, iv_history)
        iv_rank = ivr_result.iv_rank

        if iv_rank >= self.high_threshold:
            regime = "high"
            strategy_bias = "sell_premium"
            # Confidence scales from threshold to 1.0
            conf = (iv_rank - self.high_threshold) / (1.0 - self.high_threshold)
        elif iv_rank <= self.low_threshold:
            regime = "low"
            strategy_bias = "buy_premium"
            conf = (self.low_threshold - iv_rank) / self.low_threshold
        else:
            regime = "normal"
            strategy_bias = "neutral"
            # Maximum confidence at midpoint, fades toward thresholds
            mid = (self.high_threshold + self.low_threshold) / 2.0
            conf = 1.0 - abs(iv_rank - mid) / (mid - self.low_threshold)

        return VolatilityRegimeResult(
            symbol=symbol,
            current_iv=current_iv,
            iv_rank=iv_rank,
            regime=regime,
            strategy_bias=strategy_bias,
            confidence=round(max(0.0, min(1.0, conf)), 4),
        )
