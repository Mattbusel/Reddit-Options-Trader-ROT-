"""Automated Greek hedging for options portfolios."""

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class GreekExposure:
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0


@dataclass
class HedgeRecommendation:
    action: str
    quantity: float
    instrument: str
    cost_estimate: float
    greek_change: GreekExposure
    reason: str


class GreekHedger:
    def __init__(
        self,
        target_delta: float = 0.0,
        target_gamma: float = 0.0,
        delta_tolerance: float = 0.05,
        gamma_tolerance: float = 0.01,
    ):
        self.target_delta = target_delta
        self.target_gamma = target_gamma
        self.delta_tolerance = delta_tolerance
        self.gamma_tolerance = gamma_tolerance

    @staticmethod
    def compute_portfolio_greeks(positions: List[Dict]) -> GreekExposure:
        """Sum greeks weighted by quantity/sign across all positions."""
        exposure = GreekExposure()
        for pos in positions:
            qty = pos.get("quantity", 1)
            sign = 1 if pos.get("side", "long").lower() == "long" else -1
            multiplier = qty * sign
            exposure.delta += pos.get("delta", 0.0) * multiplier
            exposure.gamma += pos.get("gamma", 0.0) * multiplier
            exposure.theta += pos.get("theta", 0.0) * multiplier
            exposure.vega += pos.get("vega", 0.0) * multiplier
            exposure.rho += pos.get("rho", 0.0) * multiplier
        return exposure

    def delta_hedge(
        self, exposure: GreekExposure, stock_price: float
    ) -> List[HedgeRecommendation]:
        """Recommend stock/futures trades to neutralise delta."""
        recommendations = []
        delta_error = exposure.delta - self.target_delta
        if abs(delta_error) <= self.delta_tolerance:
            return recommendations

        # Number of shares to trade: -delta_error shares (each share has delta=1)
        shares = -delta_error
        action = "buy" if shares > 0 else "sell"
        qty = abs(shares)
        cost = qty * stock_price
        recommendations.append(
            HedgeRecommendation(
                action=action,
                quantity=qty,
                instrument="stock",
                cost_estimate=cost,
                greek_change=GreekExposure(delta=-delta_error),
                reason=f"Delta hedge: portfolio delta={exposure.delta:.4f}, target={self.target_delta:.4f}",
            )
        )
        return recommendations

    def gamma_hedge(
        self,
        exposure: GreekExposure,
        atm_gamma: float,
        atm_price: float,
    ) -> List[HedgeRecommendation]:
        """Recommend ATM option trades to neutralise gamma."""
        recommendations = []
        gamma_error = exposure.gamma - self.target_gamma
        if abs(gamma_error) <= self.gamma_tolerance or atm_gamma == 0:
            return recommendations

        # Contracts needed: -gamma_error / atm_gamma
        contracts = -gamma_error / atm_gamma
        action = "buy" if contracts > 0 else "sell"
        qty = abs(contracts)
        cost = qty * atm_price
        recommendations.append(
            HedgeRecommendation(
                action=action,
                quantity=qty,
                instrument="ATM_option",
                cost_estimate=cost,
                greek_change=GreekExposure(gamma=-gamma_error),
                reason=f"Gamma hedge: portfolio gamma={exposure.gamma:.4f}, target={self.target_gamma:.4f}",
            )
        )
        return recommendations

    def vega_hedge(
        self,
        exposure: GreekExposure,
        vega_per_contract: float,
        contract_price: float,
    ) -> List[HedgeRecommendation]:
        """Recommend vega-neutralising trades."""
        recommendations = []
        if vega_per_contract == 0 or abs(exposure.vega) < 1e-8:
            return recommendations

        contracts = -exposure.vega / vega_per_contract
        action = "buy" if contracts > 0 else "sell"
        qty = abs(contracts)
        cost = qty * contract_price
        recommendations.append(
            HedgeRecommendation(
                action=action,
                quantity=qty,
                instrument="vega_option",
                cost_estimate=cost,
                greek_change=GreekExposure(vega=-exposure.vega),
                reason=f"Vega hedge: portfolio vega={exposure.vega:.4f}",
            )
        )
        return recommendations

    def full_hedge(
        self,
        exposure: GreekExposure,
        stock_price: float,
        atm_gamma: float,
        atm_price: float,
    ) -> List[HedgeRecommendation]:
        """Full hedge: delta first, then gamma, then vega."""
        recs: List[HedgeRecommendation] = []
        recs.extend(self.delta_hedge(exposure, stock_price))
        recs.extend(self.gamma_hedge(exposure, atm_gamma, atm_price))
        recs.extend(self.vega_hedge(exposure, atm_gamma * stock_price, atm_price))
        return recs

    @staticmethod
    def hedge_cost(recommendations: List[HedgeRecommendation]) -> float:
        return sum(r.cost_estimate for r in recommendations)

    @staticmethod
    def residual_exposure(
        exposure: GreekExposure, recommendations: List[HedgeRecommendation]
    ) -> GreekExposure:
        residual = GreekExposure(
            delta=exposure.delta,
            gamma=exposure.gamma,
            theta=exposure.theta,
            vega=exposure.vega,
            rho=exposure.rho,
        )
        for rec in recommendations:
            residual.delta += rec.greek_change.delta
            residual.gamma += rec.greek_change.gamma
            residual.theta += rec.greek_change.theta
            residual.vega += rec.greek_change.vega
            residual.rho += rec.greek_change.rho
        return residual
