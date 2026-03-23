"""Options paper trading simulator for the ROT platform.

Simulates options trades without committing real capital.  Positions are
tracked by an in-memory registry; mark-to-market updates can use either a
direct price lookup or Black-Scholes-Merton (BSM) valuation when an IV
surface is provided.

Usage::

    from rot.paper.options_paper import OptionsPaperTrader

    trader = OptionsPaperTrader(initial_capital=100_000)
    pos_id = trader.open_trade(
        ticker="AAPL",
        strategy="long_call",
        strikes=[150.0],
        expiry="2026-06-20",
        premium=3.50,
        quantity=10,
    )
    trader.mark_to_market(
        prices={"AAPL_150C_20260620": 4.20},
        iv_surface={},
    )
    summary = trader.get_summary()
    closed = trader.close_trade(pos_id, exit_premium=4.20)
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class OptionPosition:
    """A single open options position.

    Attributes:
        contract_id:     Unique contract identifier (auto-generated).
        ticker:          Underlying equity ticker symbol.
        strategy:        Strategy label (e.g. ``"long_call"``, ``"iron_condor"``).
        strikes:         List of strike prices involved in the strategy.
        expiry:          Expiry date string (e.g. ``"2026-06-20"``).
        quantity:        Number of contracts (positive = long, negative = short).
        entry_premium:   Per-share premium paid/received at trade open.
        current_value:   Per-share mark-to-market value (updated by
                         :meth:`OptionsPaperTrader.mark_to_market`).
        delta:           Current option delta (optional, from IV surface).
        pnl:             Unrealised P&L in dollars:
                         ``(current_value - entry_premium) * quantity * 100``.
    """

    contract_id: str
    ticker: str
    strategy: str
    strikes: List[float]
    expiry: str
    quantity: int
    entry_premium: float
    current_value: float = field(init=False)
    delta: float = 0.0
    opened_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.current_value = self.entry_premium

    @property
    def pnl(self) -> float:
        """Unrealised P&L in dollars (each contract = 100 shares)."""
        return (self.current_value - self.entry_premium) * self.quantity * 100


@dataclass
class ClosedTrade:
    """Record of a closed options trade.

    Attributes:
        contract_id:    Position identifier.
        ticker:         Underlying ticker.
        strategy:       Strategy label.
        entry_premium:  Per-share entry premium.
        exit_premium:   Per-share exit premium.
        quantity:       Number of contracts traded.
        realised_pnl:   Realised P&L in dollars.
        is_winner:      ``True`` if ``realised_pnl > 0``.
    """

    contract_id: str
    ticker: str
    strategy: str
    entry_premium: float
    exit_premium: float
    quantity: int
    realised_pnl: float

    @property
    def is_winner(self) -> bool:
        return self.realised_pnl > 0


@dataclass
class PortfolioSummary:
    """Snapshot of the paper trading portfolio.

    Attributes:
        total_pnl:       Sum of unrealised P&L across all open positions
                         plus all realised P&L from closed trades.
        open_positions:  Number of currently open positions.
        closed_trades:   Total number of closed trades.
        win_rate:        Fraction of closed trades that were profitable.
        max_drawdown:    Maximum peak-to-trough decline in portfolio equity.
        cash:            Current cash balance.
    """

    total_pnl: float
    open_positions: int
    closed_trades: int
    win_rate: float
    max_drawdown: float
    cash: float


# ---------------------------------------------------------------------------
# BSM helpers
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc approximation."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _bsm_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes-Merton call price.

    Parameters
    ----------
    S:     Current underlying price.
    K:     Strike price.
    T:     Time to expiry in years.
    r:     Risk-free rate (annualised, fractional).
    sigma: Implied volatility (annualised, fractional).
    """
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        return max(0.0, S - K)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def _bsm_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes-Merton put price (via call-put parity)."""
    call = _bsm_call(S, K, T, r, sigma)
    return call + K * math.exp(-r * T) - S


def _bsm_delta_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)


def _bsm_delta_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return _bsm_delta_call(S, K, T, r, sigma) - 1.0


# ---------------------------------------------------------------------------
# Paper trader
# ---------------------------------------------------------------------------


class OptionsPaperTrader:
    """Simulate options trading without real capital.

    Parameters
    ----------
    initial_capital:
        Starting cash balance in dollars.

    Notes
    -----
    * Each contract represents 100 shares of the underlying.
    * Premiums and prices are per-share (standard options convention).
    * ``mark_to_market`` accepts a ``prices`` dict keyed by ``contract_id``
      for direct price lookup.  When a contract_id is not found in ``prices``,
      the BSM model is used if ``iv_surface`` contains the ticker.
    """

    def __init__(self, initial_capital: float = 100_000.0) -> None:
        if initial_capital <= 0:
            raise ValueError(
                f"initial_capital must be positive, got {initial_capital}"
            )
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._positions: Dict[str, OptionPosition] = {}
        self._closed: List[ClosedTrade] = []
        self._equity_history: List[float] = [initial_capital]

    # ------------------------------------------------------------------
    # Trade management
    # ------------------------------------------------------------------

    def open_trade(
        self,
        ticker: str,
        strategy: str,
        strikes: List[float],
        expiry: str,
        premium: float,
        quantity: int,
    ) -> str:
        """Open a new options position.

        Parameters
        ----------
        ticker:   Underlying ticker (e.g. ``"AAPL"``).
        strategy: Strategy name (e.g. ``"long_call"``, ``"covered_call"``).
        strikes:  Strike prices involved (single strike for vanilla options).
        expiry:   Expiry date string (``"YYYY-MM-DD"`` format recommended).
        premium:  Per-share premium (debit for long, credit for short).
        quantity: Number of contracts (positive).

        Returns
        -------
        str
            Unique position identifier for subsequent :meth:`close_trade` calls.

        Raises
        ------
        ValueError
            If *premium* or *quantity* are non-positive.
        """
        if premium < 0:
            raise ValueError(f"premium must be >= 0, got {premium}")
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")

        position_id = str(uuid.uuid4())
        cost = premium * quantity * 100  # total debit for long positions
        self._cash -= cost

        pos = OptionPosition(
            contract_id=position_id,
            ticker=ticker,
            strategy=strategy,
            strikes=list(strikes),
            expiry=expiry,
            quantity=quantity,
            entry_premium=premium,
        )
        self._positions[position_id] = pos
        self._record_equity()
        return position_id

    def close_trade(self, position_id: str, exit_premium: float) -> ClosedTrade:
        """Close an open position at *exit_premium*.

        Parameters
        ----------
        position_id:
            Identifier returned by :meth:`open_trade`.
        exit_premium:
            Per-share premium received (long close) or paid (short close).

        Returns
        -------
        ClosedTrade
            Realised trade record.

        Raises
        ------
        KeyError
            If *position_id* does not correspond to an open position.
        ValueError
            If *exit_premium* is negative.
        """
        if position_id not in self._positions:
            raise KeyError(f"Position {position_id!r} not found")
        if exit_premium < 0:
            raise ValueError(f"exit_premium must be >= 0, got {exit_premium}")

        pos = self._positions.pop(position_id)
        realised_pnl = (exit_premium - pos.entry_premium) * pos.quantity * 100
        self._cash += exit_premium * pos.quantity * 100

        trade = ClosedTrade(
            contract_id=pos.contract_id,
            ticker=pos.ticker,
            strategy=pos.strategy,
            entry_premium=pos.entry_premium,
            exit_premium=exit_premium,
            quantity=pos.quantity,
            realised_pnl=realised_pnl,
        )
        self._closed.append(trade)
        self._record_equity()
        return trade

    def mark_to_market(
        self,
        prices: Dict[str, float],
        iv_surface: Dict[str, dict],
    ) -> None:
        """Update current_value for all open positions.

        Lookup order per position:
        1. Direct price lookup by ``contract_id`` in *prices*.
        2. BSM valuation when *iv_surface* contains the ticker and the
           surface dict includes ``{spot, iv, r, T}`` keys.
        3. No update (value stays at entry_premium) if neither is available.

        Parameters
        ----------
        prices:
            ``{contract_id: per_share_price}`` mapping.
        iv_surface:
            ``{ticker: {"spot": float, "iv": float, "r": float, "T": float}}``
            mapping used for BSM valuation when a direct price is unavailable.
        """
        for pos_id, pos in self._positions.items():
            if pos_id in prices:
                pos.current_value = prices[pos_id]
                continue

            surface = iv_surface.get(pos.ticker)
            if surface is None:
                continue

            S = float(surface.get("spot", 0.0))
            iv = float(surface.get("iv", 0.0))
            r = float(surface.get("r", 0.0))
            T = float(surface.get("T", 0.0))

            if not pos.strikes:
                continue

            K = pos.strikes[0]
            strategy_lower = pos.strategy.lower()

            if "put" in strategy_lower:
                pos.current_value = _bsm_put(S, K, T, r, iv)
                pos.delta = _bsm_delta_put(S, K, T, r, iv)
            else:
                # Default: treat as call
                pos.current_value = _bsm_call(S, K, T, r, iv)
                pos.delta = _bsm_delta_call(S, K, T, r, iv)

        self._record_equity()

    # ------------------------------------------------------------------
    # Portfolio reporting
    # ------------------------------------------------------------------

    def get_summary(self) -> PortfolioSummary:
        """Compute and return the current portfolio snapshot."""
        unrealised = sum(pos.pnl for pos in self._positions.values())
        realised = sum(t.realised_pnl for t in self._closed)
        total_pnl = unrealised + realised

        n_closed = len(self._closed)
        win_rate = (
            sum(1 for t in self._closed if t.is_winner) / n_closed
            if n_closed > 0
            else 0.0
        )

        max_dd = self._compute_max_drawdown()

        return PortfolioSummary(
            total_pnl=total_pnl,
            open_positions=len(self._positions),
            closed_trades=n_closed,
            win_rate=win_rate,
            max_drawdown=max_dd,
            cash=self._cash,
        )

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def positions(self) -> Dict[str, OptionPosition]:
        """Read-only view of open positions."""
        return dict(self._positions)

    @property
    def closed_trades(self) -> List[ClosedTrade]:
        """Ordered list of closed trades."""
        return list(self._closed)

    @property
    def cash(self) -> float:
        """Current cash balance."""
        return self._cash

    @property
    def initial_capital(self) -> float:
        """Starting capital."""
        return self._initial_capital

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _record_equity(self) -> None:
        """Snapshot total equity (cash + open MTM) into history."""
        unrealised = sum(pos.pnl for pos in self._positions.values())
        equity = self._cash + unrealised
        self._equity_history.append(equity)

    def _compute_max_drawdown(self) -> float:
        """Peak-to-trough maximum drawdown (negative or zero)."""
        equity = self._equity_history
        if len(equity) < 2:
            return 0.0
        peak = equity[0]
        max_dd = 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = (e - peak) / peak if peak != 0 else 0.0
            if dd < max_dd:
                max_dd = dd
        return max_dd
