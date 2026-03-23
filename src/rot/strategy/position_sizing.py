"""Position sizing engine for the ROT signal pipeline.

Implements multiple position sizing methods and a composite engine that
combines them into a final recommendation.  All methods are pure functions
(no side effects) wrapped in thin class interfaces so they can be used
independently or composed via ``PositionSizingEngine``.

Classes
-------
KellyCriterion
    Optimal bet fraction from win rate and average win/loss ratio.
FractionalKelly
    Conservative Kelly variants (half-Kelly, quarter-Kelly, etc.).
VolatilityScaledSizing
    Size positions inversely proportional to recent underlying volatility.
MaxLossSizing
    Size so that the worst-case loss on one position does not exceed a
    specified fraction of the portfolio.
PositionSizingEngine
    Orchestrates multiple methods and blends them into one recommendation.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SizingResult:
    """Result from a single position-sizing method."""

    method: str
    position_fraction: float   # fraction of portfolio to deploy (0-1)
    position_dollars: float    # dollar amount given portfolio_value
    rationale: str             # human-readable explanation


@dataclass(frozen=True)
class CompositeSizingResult:
    """Output of PositionSizingEngine."""

    symbol: str
    portfolio_value: float
    final_fraction: float        # blended fraction (0-1)
    final_dollars: float         # blended dollar amount
    individual_results: List[SizingResult]
    blend_method: str            # "min" | "mean" | "weighted"
    risk_flags: List[str]        # warnings about sizing inputs
    signal_confidence: float


# ---------------------------------------------------------------------------
# KellyCriterion
# ---------------------------------------------------------------------------


class KellyCriterion:
    """Full Kelly criterion: f* = (p*b - q) / b.

    Where:
    - p = win rate (probability of winning trade)
    - q = 1 - p
    - b = avg_win / avg_loss (reward-to-risk ratio)

    The formula assumes binary outcomes.  For options (asymmetric pay-offs)
    this is an approximation.

    Parameters
    ----------
    max_fraction:
        Hard cap on the Kelly fraction (default 0.50 = 50%).  Full Kelly is
        theoretically optimal but extremely volatile in practice.
    min_trades:
        Minimum number of trades in history before returning a non-trivial
        fraction.  Below this, returns ``floor_fraction``.
    floor_fraction:
        Minimum fraction returned when history is too short.  Default 0.02.
    """

    def __init__(
        self,
        max_fraction: float = 0.50,
        min_trades: int = 10,
        floor_fraction: float = 0.02,
    ) -> None:
        if not (0.0 < max_fraction <= 1.0):
            raise ValueError("max_fraction must be in (0, 1]")
        if not (0.0 <= floor_fraction <= max_fraction):
            raise ValueError("floor_fraction must be in [0, max_fraction]")
        self.max_fraction = max_fraction
        self.min_trades = min_trades
        self.floor_fraction = floor_fraction

    def compute(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        portfolio_value: float,
        n_trades: int = 0,
    ) -> SizingResult:
        """Compute full-Kelly position size.

        Parameters
        ----------
        win_rate:
            Historical win rate as a fraction in [0, 1].
        avg_win:
            Average win magnitude (positive value, e.g. 5.0 for 5% gain).
        avg_loss:
            Average loss magnitude (positive value, e.g. 3.0 for 3% loss).
        portfolio_value:
            Current total portfolio value in dollars.
        n_trades:
            Number of trades in the history used to derive stats.

        Returns
        -------
        SizingResult
        """
        if portfolio_value <= 0:
            raise ValueError("portfolio_value must be positive")

        if n_trades < self.min_trades or win_rate <= 0 or avg_loss <= 0:
            fraction = self.floor_fraction
            rationale = (
                f"Insufficient history ({n_trades} < {self.min_trades} trades). "
                f"Using floor fraction {self.floor_fraction:.1%}."
            )
        else:
            if avg_win <= 0:
                avg_win = 0.001  # avoid division by zero
            b = avg_win / avg_loss
            q = 1.0 - win_rate
            kelly = (win_rate * b - q) / b
            fraction = max(0.0, min(kelly, self.max_fraction))
            rationale = (
                f"Full Kelly: win_rate={win_rate:.1%}, b={b:.2f}, "
                f"raw_f*={kelly:.3f}, capped at {self.max_fraction:.1%}."
            )

        return SizingResult(
            method="kelly_full",
            position_fraction=round(fraction, 6),
            position_dollars=round(fraction * portfolio_value, 2),
            rationale=rationale,
        )


# ---------------------------------------------------------------------------
# FractionalKelly
# ---------------------------------------------------------------------------


class FractionalKelly:
    """Conservative Kelly that uses a fraction of the full Kelly bet.

    Half-Kelly (``kelly_fraction=0.5``) is the most common practitioner
    choice; it yields ~75% of the full-Kelly geometric growth rate while
    dramatically reducing drawdowns.

    Parameters
    ----------
    kelly_fraction:
        Multiplier applied to the full-Kelly output (e.g. 0.5 for half-Kelly).
        Must be in (0, 1].
    """

    def __init__(self, kelly_fraction: float = 0.5) -> None:
        if not (0.0 < kelly_fraction <= 1.0):
            raise ValueError("kelly_fraction must be in (0, 1]")
        self.kelly_fraction = kelly_fraction
        self._full_kelly = KellyCriterion(max_fraction=1.0)

    def compute(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        portfolio_value: float,
        n_trades: int = 0,
    ) -> SizingResult:
        """Compute fractional Kelly position size.

        Parameters
        ----------
        win_rate, avg_win, avg_loss, portfolio_value, n_trades:
            Same as ``KellyCriterion.compute()``.

        Returns
        -------
        SizingResult
        """
        base = self._full_kelly.compute(win_rate, avg_win, avg_loss, portfolio_value, n_trades)
        fraction = base.position_fraction * self.kelly_fraction
        fraction = max(0.0, min(fraction, 1.0))

        label = f"{self.kelly_fraction:.0%}-Kelly"
        rationale = (
            f"{label}: full-Kelly fraction={base.position_fraction:.3f} × "
            f"{self.kelly_fraction:.2f} = {fraction:.3f}."
        )
        return SizingResult(
            method=f"kelly_{self.kelly_fraction:.2f}",
            position_fraction=round(fraction, 6),
            position_dollars=round(fraction * portfolio_value, 2),
            rationale=rationale,
        )


# ---------------------------------------------------------------------------
# VolatilityScaledSizing
# ---------------------------------------------------------------------------


class VolatilityScaledSizing:
    """Scale position size *inversely* proportional to recent volatility.

    A position sized to a fixed volatility target:

        fraction = target_volatility / realized_volatility × base_fraction

    When volatility is high, the position is smaller; when volatility is
    low, the position is larger (up to ``max_fraction``).

    Parameters
    ----------
    target_volatility:
        Annual volatility target (decimal, e.g. 0.15 = 15% annual vol).
    base_fraction:
        Base position fraction when volatility equals the target.
    max_fraction:
        Hard cap.
    annualisation_factor:
        Multiplier to annualise the input volatility series if it is daily
        (default sqrt(252)).
    """

    def __init__(
        self,
        target_volatility: float = 0.15,
        base_fraction: float = 0.10,
        max_fraction: float = 0.30,
        annualisation_factor: float = math.sqrt(252),
    ) -> None:
        if target_volatility <= 0:
            raise ValueError("target_volatility must be positive")
        self.target_volatility = target_volatility
        self.base_fraction = base_fraction
        self.max_fraction = max_fraction
        self.annualisation_factor = annualisation_factor

    def compute(
        self,
        portfolio_value: float,
        return_series: Sequence[float],
    ) -> SizingResult:
        """Compute volatility-scaled position size.

        Parameters
        ----------
        portfolio_value:
            Current portfolio value in dollars.
        return_series:
            Recent daily (or periodic) returns as decimals (e.g. 0.02 for +2%).
            Minimum 5 observations recommended; fewer returns ``base_fraction``.

        Returns
        -------
        SizingResult
        """
        if portfolio_value <= 0:
            raise ValueError("portfolio_value must be positive")

        valid_returns = [r for r in return_series if r is not None]

        if len(valid_returns) < 5:
            fraction = self.base_fraction
            rationale = (
                f"Insufficient return history ({len(valid_returns)} observations). "
                f"Using base fraction {self.base_fraction:.1%}."
            )
        else:
            try:
                period_vol = statistics.stdev(valid_returns)
            except statistics.StatisticsError:
                period_vol = self.target_volatility / self.annualisation_factor

            annual_vol = period_vol * self.annualisation_factor

            if annual_vol < 1e-8:
                fraction = self.max_fraction
                rationale = "Near-zero realised volatility; capped at max_fraction."
            else:
                raw_fraction = self.base_fraction * (self.target_volatility / annual_vol)
                fraction = max(0.001, min(raw_fraction, self.max_fraction))
                rationale = (
                    f"Vol-scaled: realized_annual_vol={annual_vol:.1%}, "
                    f"target={self.target_volatility:.1%}, "
                    f"raw_fraction={raw_fraction:.3f}, capped at {self.max_fraction:.1%}."
                )

        return SizingResult(
            method="vol_scaled",
            position_fraction=round(fraction, 6),
            position_dollars=round(fraction * portfolio_value, 2),
            rationale=rationale,
        )


# ---------------------------------------------------------------------------
# MaxLossSizing
# ---------------------------------------------------------------------------


class MaxLossSizing:
    """Size so that max loss on a single trade never exceeds a portfolio fraction.

    Given that a position may lose up to ``max_loss_pct`` of its value,
    and we want that loss to represent at most ``portfolio_risk_pct`` of
    total portfolio equity:

        fraction = portfolio_risk_pct / max_loss_pct

    Parameters
    ----------
    portfolio_risk_pct:
        Maximum acceptable loss per trade as a fraction of portfolio (e.g.
        0.02 = 2%).  Default 0.02.
    fallback_max_loss_pct:
        Assumed max loss fraction when ``max_loss_pct`` is unknown (e.g. 0.50
        for a debit spread that can lose 100% of premium, which is ~50% of
        the underlying position notional).  Default 0.50.
    max_fraction:
        Hard cap on resulting fraction.
    """

    def __init__(
        self,
        portfolio_risk_pct: float = 0.02,
        fallback_max_loss_pct: float = 0.50,
        max_fraction: float = 0.20,
    ) -> None:
        if not (0.0 < portfolio_risk_pct < 1.0):
            raise ValueError("portfolio_risk_pct must be in (0, 1)")
        if not (0.0 < fallback_max_loss_pct <= 1.0):
            raise ValueError("fallback_max_loss_pct must be in (0, 1]")
        self.portfolio_risk_pct = portfolio_risk_pct
        self.fallback_max_loss_pct = fallback_max_loss_pct
        self.max_fraction = max_fraction

    def compute(
        self,
        portfolio_value: float,
        max_loss_pct: Optional[float] = None,
    ) -> SizingResult:
        """Compute max-loss-constrained position size.

        Parameters
        ----------
        portfolio_value:
            Current portfolio value in dollars.
        max_loss_pct:
            Maximum loss percentage of the specific position (0-1).  For a
            debit spread, this is typically 1.0 (can lose 100% of premium).
            If None, ``fallback_max_loss_pct`` is used.

        Returns
        -------
        SizingResult
        """
        if portfolio_value <= 0:
            raise ValueError("portfolio_value must be positive")

        effective_max_loss = max_loss_pct if max_loss_pct and 0 < max_loss_pct <= 1.0 else self.fallback_max_loss_pct
        raw_fraction = self.portfolio_risk_pct / effective_max_loss
        fraction = max(0.001, min(raw_fraction, self.max_fraction))

        rationale = (
            f"MaxLoss: portfolio_risk={self.portfolio_risk_pct:.1%}, "
            f"position_max_loss={effective_max_loss:.1%}, "
            f"fraction={raw_fraction:.3f} → capped={fraction:.3f}."
        )
        return SizingResult(
            method="max_loss",
            position_fraction=round(fraction, 6),
            position_dollars=round(fraction * portfolio_value, 2),
            rationale=rationale,
        )


# ---------------------------------------------------------------------------
# PositionSizingEngine
# ---------------------------------------------------------------------------


BlendMethod = Literal["min", "mean", "weighted"]


class PositionSizingEngine:
    """Combines multiple sizing methods into a single final recommendation.

    The engine runs all configured methods, then blends the resulting
    fractions using one of three strategies:

    - ``"min"``      : conservative — use the smallest fraction from any method.
    - ``"mean"``     : average — arithmetic mean of all fractions.
    - ``"weighted"`` : weight each method by its configured weight.

    Parameters
    ----------
    use_kelly:
        Include full-Kelly sizing.
    use_fractional_kelly:
        Include fractional-Kelly sizing (half-Kelly by default).
    use_vol_scaled:
        Include volatility-scaled sizing.
    use_max_loss:
        Include max-loss sizing.
    blend_method:
        How to combine the individual method fractions.
    kelly_fraction:
        Kelly fraction (for ``FractionalKelly``).  Default 0.5.
    target_volatility:
        Target annual vol for ``VolatilityScaledSizing``.  Default 0.15.
    portfolio_risk_pct:
        Max risk per trade for ``MaxLossSizing``.  Default 0.02.
    max_position_fraction:
        Hard ceiling applied after blending.  Default 0.25.
    method_weights:
        Optional dict ``{method_name: weight}`` for ``"weighted"`` blend.
        Methods not in the dict receive equal weight.
    """

    def __init__(
        self,
        use_kelly: bool = True,
        use_fractional_kelly: bool = True,
        use_vol_scaled: bool = True,
        use_max_loss: bool = True,
        blend_method: BlendMethod = "min",
        kelly_fraction: float = 0.5,
        target_volatility: float = 0.15,
        portfolio_risk_pct: float = 0.02,
        max_position_fraction: float = 0.25,
        method_weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self.blend_method = blend_method
        self.max_position_fraction = max_position_fraction
        self.method_weights = method_weights or {}

        self._kelly = KellyCriterion() if use_kelly else None
        self._frac_kelly = FractionalKelly(kelly_fraction=kelly_fraction) if use_fractional_kelly else None
        self._vol_scaled = VolatilityScaledSizing(target_volatility=target_volatility) if use_vol_scaled else None
        self._max_loss = MaxLossSizing(portfolio_risk_pct=portfolio_risk_pct) if use_max_loss else None

    def recommend(
        self,
        symbol: str,
        portfolio_value: float,
        signal_confidence: float = 0.5,
        win_rate: float = 0.5,
        avg_win: float = 5.0,
        avg_loss: float = 3.0,
        n_trades: int = 0,
        return_series: Optional[Sequence[float]] = None,
        max_loss_pct: Optional[float] = None,
    ) -> CompositeSizingResult:
        """Generate a composite position size recommendation.

        Parameters
        ----------
        symbol:
            Ticker symbol being sized.
        portfolio_value:
            Total portfolio equity in dollars.
        signal_confidence:
            Signal confidence score [0, 1] — used for risk flags.
        win_rate:
            Historical win rate for Kelly methods.
        avg_win:
            Average winning trade magnitude (positive percentage).
        avg_loss:
            Average losing trade magnitude (positive percentage).
        n_trades:
            Number of historical trades used to derive stats.
        return_series:
            Recent daily returns for vol-scaled method.
        max_loss_pct:
            Max possible loss on this specific trade structure.

        Returns
        -------
        CompositeSizingResult
        """
        if portfolio_value <= 0:
            raise ValueError("portfolio_value must be positive")

        results: List[SizingResult] = []
        risk_flags: List[str] = []

        # Validate and flag inputs
        if signal_confidence < 0.30:
            risk_flags.append(f"low_signal_confidence:{signal_confidence:.2f}")
        if n_trades < 20:
            risk_flags.append(f"limited_trade_history:{n_trades}_trades")
        if win_rate < 0.40:
            risk_flags.append(f"low_win_rate:{win_rate:.1%}")

        # Run each enabled method
        if self._kelly is not None:
            results.append(
                self._kelly.compute(win_rate, avg_win, avg_loss, portfolio_value, n_trades)
            )
        if self._frac_kelly is not None:
            results.append(
                self._frac_kelly.compute(win_rate, avg_win, avg_loss, portfolio_value, n_trades)
            )
        if self._vol_scaled is not None:
            results.append(
                self._vol_scaled.compute(portfolio_value, return_series or [])
            )
        if self._max_loss is not None:
            results.append(
                self._max_loss.compute(portfolio_value, max_loss_pct)
            )

        if not results:
            # No methods enabled: minimum default
            fraction = 0.02
        else:
            fractions = [r.position_fraction for r in results]

            if self.blend_method == "min":
                fraction = min(fractions)
            elif self.blend_method == "mean":
                fraction = sum(fractions) / len(fractions)
            else:  # weighted
                total_w = 0.0
                weighted_sum = 0.0
                for r in results:
                    w = self.method_weights.get(r.method, 1.0)
                    weighted_sum += r.position_fraction * w
                    total_w += w
                fraction = weighted_sum / total_w if total_w > 0 else sum(fractions) / len(fractions)

        # Confidence scaling: low confidence → reduce size
        if signal_confidence < 1.0:
            confidence_scale = 0.5 + signal_confidence * 0.5  # maps [0,1] → [0.5, 1.0]
            fraction *= confidence_scale

        # Hard cap
        fraction = max(0.001, min(fraction, self.max_position_fraction))
        final_dollars = round(fraction * portfolio_value, 2)

        return CompositeSizingResult(
            symbol=symbol,
            portfolio_value=portfolio_value,
            final_fraction=round(fraction, 6),
            final_dollars=final_dollars,
            individual_results=results,
            blend_method=self.blend_method,
            risk_flags=risk_flags,
            signal_confidence=signal_confidence,
        )
