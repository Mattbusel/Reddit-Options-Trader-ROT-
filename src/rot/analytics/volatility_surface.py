"""Implied volatility surface construction and analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class VolPoint:
    """A single point on the volatility surface."""
    strike: float
    expiry: float
    iv: float
    option_type: str  # 'call' or 'put'


class VolSurface:
    """Implied volatility surface supporting interpolation and analytics."""

    def __init__(self, spot: float) -> None:
        self.spot = spot
        self._points: List[VolPoint] = []

    def add_point(self, point: VolPoint) -> None:
        """Add a vol point to the surface."""
        self._points.append(point)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _points_at_expiry(self, expiry: float) -> List[VolPoint]:
        """Return all points at a given expiry, sorted by strike."""
        pts = [p for p in self._points if abs(p.expiry - expiry) < 1e-9]
        return sorted(pts, key=lambda p: p.strike)

    def _nearest_expiry(self, expiry: float) -> Optional[float]:
        """Return the recorded expiry nearest to the requested expiry."""
        expiries = list({p.expiry for p in self._points})
        if not expiries:
            return None
        return min(expiries, key=lambda e: abs(e - expiry))

    def _all_expiries_sorted(self) -> List[float]:
        return sorted({p.expiry for p in self._points})

    def _interp1d(
        self,
        x0: float,
        x1: float,
        y0: float,
        y1: float,
        x: float,
    ) -> float:
        """Linear interpolation/extrapolation."""
        if abs(x1 - x0) < 1e-12:
            return y0
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)

    def _vol_along_expiry(self, strike: float, expiry: float) -> float:
        """Interpolate vol along the strike axis for a single expiry."""
        pts = self._points_at_expiry(expiry)
        if not pts:
            return float("nan")
        if len(pts) == 1:
            return pts[0].iv
        # Find bracketing pair.
        if strike <= pts[0].strike:
            return pts[0].iv
        if strike >= pts[-1].strike:
            return pts[-1].iv
        for i in range(len(pts) - 1):
            if pts[i].strike <= strike <= pts[i + 1].strike:
                return self._interp1d(
                    pts[i].strike, pts[i + 1].strike,
                    pts[i].iv, pts[i + 1].iv,
                    strike,
                )
        return pts[-1].iv

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def atm_vol(self, expiry: float) -> float:
        """ATM vol: vol at the strike nearest to spot for the given expiry."""
        nearest_exp = self._nearest_expiry(expiry)
        if nearest_exp is None:
            return float("nan")
        pts = self._points_at_expiry(nearest_exp)
        if not pts:
            return float("nan")
        atm_pt = min(pts, key=lambda p: abs(p.strike - self.spot))
        return atm_pt.iv

    def vol_at(self, strike: float, expiry: float) -> float:
        """Bilinear interpolation across strike and expiry."""
        expiries = self._all_expiries_sorted()
        if not expiries:
            return float("nan")

        # Find bracketing expiries.
        if expiry <= expiries[0]:
            return self._vol_along_expiry(strike, expiries[0])
        if expiry >= expiries[-1]:
            return self._vol_along_expiry(strike, expiries[-1])

        for i in range(len(expiries) - 1):
            e0, e1 = expiries[i], expiries[i + 1]
            if e0 <= expiry <= e1:
                v0 = self._vol_along_expiry(strike, e0)
                v1 = self._vol_along_expiry(strike, e1)
                return self._interp1d(e0, e1, v0, v1, expiry)
        return self._vol_along_expiry(strike, expiries[-1])

    def skew_at(self, expiry: float) -> float:
        """Skew approximation: IV(0.9·spot) − IV(1.1·spot)."""
        put_strike = 0.9 * self.spot
        call_strike = 1.1 * self.spot
        return self.vol_at(put_strike, expiry) - self.vol_at(call_strike, expiry)

    def term_structure(self) -> List[Tuple[float, float]]:
        """[(expiry, atm_vol)] sorted by expiry."""
        result = []
        for exp in self._all_expiries_sorted():
            result.append((exp, self.atm_vol(exp)))
        return result

    def vix_like(self) -> float:
        """30-day ATM vol interpolated from the surface."""
        return self.vol_at(self.spot, 30.0 / 365.0)

    def surface_plot_data(self) -> Dict:
        """Dict suitable for plotting: {strikes, expiries, ivs}."""
        strikes = sorted({p.strike for p in self._points})
        expiries = self._all_expiries_sorted()
        ivs = [
            [self.vol_at(k, e) for k in strikes]
            for e in expiries
        ]
        return {"strikes": strikes, "expiries": expiries, "ivs": ivs}

    def vol_cone(self, strikes: List[float]) -> Dict[float, Dict[float, float]]:
        """Nested dict {strike: {expiry: vol}}."""
        result: Dict[float, Dict[float, float]] = {}
        for k in strikes:
            result[k] = {}
            for e in self._all_expiries_sorted():
                result[k][e] = self.vol_at(k, e)
        return result
