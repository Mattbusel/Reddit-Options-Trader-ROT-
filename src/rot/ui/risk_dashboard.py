"""Streamlit risk dashboard for the ROT platform.

Displays a live portfolio risk overview including:
- Current portfolio Greeks (delta, gamma, vega, theta) aggregated across all positions.
- Concentration risk heatmap (position weight by ticker).
- Stress test scenarios: market down 10%, VIX spike (+15 pts), combined shock.

Run with::

    streamlit run src/rot/ui/risk_dashboard.py

The dashboard is intentionally self-contained: it can load position data from
a JSON/CSV file or accept a dependency-injected portfolio dict so it can be
embedded in larger Streamlit apps.

Example (programmatic)::

    from rot.ui.risk_dashboard import build_risk_dashboard
    positions = [
        {
            "ticker": "AAPL",
            "strategy": "bull_call_spread",
            "quantity": 10,
            "delta": 0.45,
            "gamma": 0.03,
            "vega": 0.18,
            "theta": -0.12,
            "notional_usd": 5_000.0,
        },
        ...
    ]
    build_risk_dashboard(positions)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Optional Streamlit / pandas import (graceful degradation for non-UI use)
# ---------------------------------------------------------------------------

try:
    import streamlit as st
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False

try:
    import pandas as pd
    _PD_AVAILABLE = True
except ImportError:
    _PD_AVAILABLE = False

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class OptionPosition:
    """A single options position in the portfolio.

    Attributes:
        ticker:        Underlying equity symbol.
        strategy:      Strategy type string (e.g. ``"bull_call_spread"``).
        quantity:      Number of contracts (1 contract = 100 shares).
        delta:         Per-share delta (directional sensitivity).
        gamma:         Per-share gamma (delta convexity).
        vega:          Per-share vega (volatility sensitivity, per 1 pt IV move).
        theta:         Per-share theta (daily time decay, negative = cost).
        notional_usd:  Total notional value of the position in USD.
    """

    ticker: str
    strategy: str
    quantity: int
    delta: float
    gamma: float
    vega: float
    theta: float
    notional_usd: float = 0.0


@dataclass
class PortfolioGreeks:
    """Aggregated Greeks for the entire portfolio.

    Each value is scaled by ``quantity * 100`` (contract multiplier).

    Attributes:
        net_delta:  Total directional exposure (shares equivalent).
        net_gamma:  Total convexity.
        net_vega:   Total vega (P&L per 1% IV increase across all positions).
        net_theta:  Total daily time decay in USD.
        total_notional: Sum of position notional values.
    """

    net_delta: float
    net_gamma: float
    net_vega: float
    net_theta: float
    total_notional: float


@dataclass
class StressResult:
    """Result of a single stress test scenario.

    Attributes:
        scenario_name:  Human-readable scenario label.
        pnl_usd:        Estimated P&L in USD.
        pnl_pct:        P&L as a fraction of total notional.
        description:    What the scenario assumes.
    """

    scenario_name: str
    pnl_usd: float
    pnl_pct: float
    description: str


# ---------------------------------------------------------------------------
# Risk computation helpers
# ---------------------------------------------------------------------------


def aggregate_greeks(positions: List[OptionPosition]) -> PortfolioGreeks:
    """Compute portfolio-level aggregated Greeks.

    Args:
        positions: List of :class:`OptionPosition` objects.

    Returns:
        :class:`PortfolioGreeks` scaled by contract multiplier (100).
    """
    multiplier = 100  # standard equity options contract = 100 shares
    net_delta = sum(p.delta * p.quantity * multiplier for p in positions)
    net_gamma = sum(p.gamma * p.quantity * multiplier for p in positions)
    net_vega = sum(p.vega * p.quantity * multiplier for p in positions)
    net_theta = sum(p.theta * p.quantity * multiplier for p in positions)
    total_notional = sum(p.notional_usd for p in positions)
    return PortfolioGreeks(
        net_delta=round(net_delta, 2),
        net_gamma=round(net_gamma, 4),
        net_vega=round(net_vega, 2),
        net_theta=round(net_theta, 2),
        total_notional=round(total_notional, 2),
    )


def concentration_weights(positions: List[OptionPosition]) -> Dict[str, float]:
    """Return each ticker's share of total notional.

    Args:
        positions: List of :class:`OptionPosition` objects.

    Returns:
        Dict mapping ticker -> fraction of total notional.
    """
    total = sum(p.notional_usd for p in positions)
    if total < 1e-6:
        return {}
    by_ticker: Dict[str, float] = {}
    for p in positions:
        by_ticker[p.ticker] = by_ticker.get(p.ticker, 0.0) + p.notional_usd
    return {t: round(v / total, 4) for t, v in sorted(by_ticker.items(), key=lambda x: -x[1])}


def run_stress_tests(
    greeks: PortfolioGreeks,
    positions: List[OptionPosition],
) -> List[StressResult]:
    """Run predefined stress test scenarios.

    Scenarios:
    1. Market down 10%: P&L ≈ delta * (-0.10 * avg_price) + 0.5 * gamma * move^2
    2. VIX spike +15 pts: P&L ≈ net_vega * 15
    3. Combined shock: down 10% + VIX +15

    Args:
        greeks:    Pre-computed :class:`PortfolioGreeks`.
        positions: Original positions list (used to estimate avg underlying price).

    Returns:
        List of :class:`StressResult` objects.
    """
    # Estimate average underlying price weighted by notional
    total_notional = greeks.total_notional or 1.0
    avg_price = sum(
        p.notional_usd / max(abs(p.delta) * p.quantity * 100, 1) * p.notional_usd
        for p in positions
        if abs(p.delta) > 1e-6 and p.quantity > 0
    ) / total_notional if total_notional > 0 else 100.0
    # Fallback: use 100 as a generic equity price
    avg_price = max(10.0, min(avg_price, 5_000.0))

    move_down_10 = -0.10 * avg_price  # dollar move per share
    # First-order (delta) + second-order (gamma) P&L for 10% down
    pnl_down10 = (
        greeks.net_delta * move_down_10
        + 0.5 * greeks.net_gamma * move_down_10 ** 2
    )
    # Vega P&L for VIX +15 (vega is per 1 pt IV move; VIX proxy = ATM IV)
    pnl_vix_spike = greeks.net_vega * 15.0
    # Combined
    pnl_combined = pnl_down10 + pnl_vix_spike

    def pct(pnl: float) -> float:
        return pnl / total_notional if total_notional > 1e-6 else 0.0

    return [
        StressResult(
            scenario_name="Market Down 10%",
            pnl_usd=round(pnl_down10, 2),
            pnl_pct=round(pct(pnl_down10), 4),
            description=(
                f"Underlying falls 10% (~${move_down_10:.2f}/share). "
                "P&L estimated via delta + gamma approximation."
            ),
        ),
        StressResult(
            scenario_name="VIX Spike +15 pts",
            pnl_usd=round(pnl_vix_spike, 2),
            pnl_pct=round(pct(pnl_vix_spike), 4),
            description=(
                "Implied volatility rises +15 percentage points across all positions. "
                "P&L estimated via net vega."
            ),
        ),
        StressResult(
            scenario_name="Combined Shock (Down 10% + VIX +15)",
            pnl_usd=round(pnl_combined, 2),
            pnl_pct=round(pct(pnl_combined), 4),
            description="Market falls 10% simultaneously with a VIX +15 spike.",
        ),
    ]


# ---------------------------------------------------------------------------
# Dashboard builder (Streamlit)
# ---------------------------------------------------------------------------


def build_risk_dashboard(positions: List[OptionPosition]) -> None:
    """Render the full risk dashboard in a Streamlit app.

    Args:
        positions: List of :class:`OptionPosition` objects representing the
                   current portfolio.

    Raises:
        ImportError: If ``streamlit`` or ``pandas`` are not installed.
    """
    if not _ST_AVAILABLE:
        raise ImportError("streamlit is required. Run: pip install streamlit")
    if not _PD_AVAILABLE:
        raise ImportError("pandas is required. Run: pip install pandas")

    st.set_page_config(page_title="ROT Risk Dashboard", layout="wide")
    st.title("ROT Options Risk Dashboard")

    if not positions:
        st.info("No positions loaded. Add positions to see risk metrics.")
        return

    greeks = aggregate_greeks(positions)
    weights = concentration_weights(positions)
    stress = run_stress_tests(greeks, positions)

    # ── Section 1: Portfolio Greeks ──
    st.header("Portfolio Greeks")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Net Delta", f"{greeks.net_delta:+,.2f}", help="Shares equivalent directional exposure")
    col2.metric("Net Gamma", f"{greeks.net_gamma:+,.4f}", help="Rate of delta change per $1 move")
    col3.metric("Net Vega", f"${greeks.net_vega:+,.2f}", help="P&L per 1 pt IV increase")
    col4.metric("Net Theta", f"${greeks.net_theta:+,.2f}/day", help="Daily time decay (negative = cost)")
    col5.metric("Total Notional", f"${greeks.total_notional:,.0f}")

    st.divider()

    # ── Section 2: Concentration Risk ──
    st.header("Concentration Risk")

    conc_df = pd.DataFrame(
        [(t, w * 100) for t, w in weights.items()],
        columns=["Ticker", "Weight (%)"],
    )
    conc_df = conc_df.sort_values("Weight (%)", ascending=False)

    col_a, col_b = st.columns([2, 3])
    with col_a:
        st.dataframe(conc_df.style.format({"Weight (%)": "{:.1f}%"}), use_container_width=True)
        # Flag tickers with > 25% concentration
        concentrated = conc_df[conc_df["Weight (%)"] > 25.0]
        if not concentrated.empty:
            st.warning(
                f"High concentration risk: {', '.join(concentrated['Ticker'].tolist())} "
                f"each exceed 25% of notional."
            )
    with col_b:
        st.bar_chart(conc_df.set_index("Ticker")["Weight (%)"])

    st.divider()

    # ── Section 3: Positions Table ──
    st.header("Current Positions")
    pos_df = pd.DataFrame([
        {
            "Ticker": p.ticker,
            "Strategy": p.strategy,
            "Qty": p.quantity,
            "Delta": p.delta,
            "Gamma": p.gamma,
            "Vega": p.vega,
            "Theta": p.theta,
            "Notional ($)": p.notional_usd,
        }
        for p in positions
    ])
    st.dataframe(
        pos_df.style.format({
            "Delta": "{:.3f}",
            "Gamma": "{:.4f}",
            "Vega": "{:.3f}",
            "Theta": "{:.3f}",
            "Notional ($)": "${:,.0f}",
        }),
        use_container_width=True,
    )

    st.divider()

    # ── Section 4: Stress Tests ──
    st.header("Stress Test Scenarios")
    for s in stress:
        colour = "normal" if s.pnl_usd >= 0 else "inverse"
        sign = "+" if s.pnl_usd >= 0 else ""
        with st.expander(f"{s.scenario_name}: {sign}${s.pnl_usd:,.2f} ({s.pnl_pct:+.1%})", expanded=True):
            st.caption(s.description)
            st.metric(
                label="Estimated P&L",
                value=f"{sign}${s.pnl_usd:,.2f}",
                delta=f"{s.pnl_pct:+.1%} of notional",
                delta_color=colour,
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _demo_positions() -> List[OptionPosition]:
    """Generate demo positions for the standalone dashboard run."""
    return [
        OptionPosition(
            ticker="AAPL", strategy="bull_call_spread", quantity=10,
            delta=0.45, gamma=0.03, vega=0.18, theta=-0.12, notional_usd=5_500.0,
        ),
        OptionPosition(
            ticker="NVDA", strategy="long_straddle", quantity=5,
            delta=0.02, gamma=0.08, vega=0.55, theta=-0.38, notional_usd=8_200.0,
        ),
        OptionPosition(
            ticker="SPY", strategy="iron_condor", quantity=20,
            delta=-0.05, gamma=-0.02, vega=-0.40, theta=0.22, notional_usd=11_000.0,
        ),
        OptionPosition(
            ticker="TSLA", strategy="long_put", quantity=8,
            delta=-0.38, gamma=0.04, vega=0.25, theta=-0.18, notional_usd=3_800.0,
        ),
    ]


if __name__ == "__main__" and _ST_AVAILABLE:
    # When run directly via `streamlit run`, render the demo dashboard.
    build_risk_dashboard(_demo_positions())
