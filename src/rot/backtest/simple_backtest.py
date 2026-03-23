"""Simple event-driven backtesting engine for the ROT platform.

Runs a signal-driven simulation over historical price data, tracking trades,
equity curve, and key performance statistics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Signal:
    """A trading signal emitted by a strategy."""

    timestamp: datetime
    symbol: str
    direction: int  # +1 for long, -1 for short
    strength: float  # [0, 1]
    source: str


@dataclass
class Trade:
    """A completed round-trip trade."""

    entry_time: datetime
    exit_time: datetime
    symbol: str
    direction: int
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    return_pct: float


@dataclass
class BacktestResult:
    """Aggregated results from a backtest run."""

    trades: list[Trade]
    equity_curve: list[float]
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    avg_trade_duration_days: float


@dataclass
class _OpenPosition:
    symbol: str
    direction: int
    entry_price: float
    entry_time: datetime
    quantity: float
    signal_source: str


class SimpleBacktester:
    """Event-driven backtester that processes signals against historical price data.

    Parameters
    ----------
    initial_capital : float
        Starting equity in dollars.
    position_size_pct : float
        Fraction of capital allocated per trade (default 10%).
    slippage_bps : float
        One-way slippage in basis points applied to fill price.
    commission_per_trade : float
        Flat commission deducted per trade (entry and exit each).
    max_holding_days : int
        Maximum number of calendar days to hold a position before forced exit.
    """

    def __init__(
        self,
        initial_capital: float,
        position_size_pct: float = 0.10,
        slippage_bps: float = 5.0,
        commission_per_trade: float = 1.0,
        max_holding_days: int = 20,
    ) -> None:
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct
        self.slippage_bps = slippage_bps
        self.commission_per_trade = commission_per_trade
        self.max_holding_days = max_holding_days

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def sharpe_ratio(returns: list[float], risk_free_daily: float = 0.0) -> float:
        """Annualised Sharpe ratio from a list of daily returns."""
        if len(returns) < 2:
            return 0.0
        n = len(returns)
        mean = sum(returns) / n - risk_free_daily
        variance = sum((r - mean - risk_free_daily) ** 2 for r in returns) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0.0:
            return 0.0
        return (mean / std) * math.sqrt(252)

    @staticmethod
    def max_drawdown(equity_curve: list[float]) -> float:
        """Maximum peak-to-trough drawdown as a positive fraction."""
        if not equity_curve:
            return 0.0
        peak = equity_curve[0]
        max_dd = 0.0
        for val in equity_curve:
            if val > peak:
                peak = val
            dd = (peak - val) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_slippage(self, price: float, direction: int) -> float:
        """Apply slippage: buys fill higher, sells fill lower."""
        slip = price * self.slippage_bps / 10_000.0
        return price + slip * direction

    def _find_price(
        self,
        symbol: str,
        after_ts: datetime,
        price_data: dict[str, list[tuple[datetime, float]]],
    ) -> Optional[tuple[datetime, float]]:
        """Find the first price bar for `symbol` at or after `after_ts`."""
        bars = price_data.get(symbol, [])
        for ts, px in bars:
            if ts >= after_ts:
                return (ts, px)
        return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        signals: list[Signal],
        price_data: dict[str, list[tuple[datetime, float]]],
    ) -> BacktestResult:
        """Run the backtest and return aggregated results.

        Parameters
        ----------
        signals : list[Signal]
            Sorted list of trading signals (chronological order preferred).
        price_data : dict
            Mapping of symbol → list of (timestamp, price) tuples, sorted
            chronologically.
        """
        capital = self.initial_capital
        equity_curve: list[float] = [capital]
        completed_trades: list[Trade] = []
        open_positions: dict[str, _OpenPosition] = {}  # symbol → position

        # Sort signals chronologically.
        sorted_signals = sorted(signals, key=lambda s: s.timestamp)

        for sig in sorted_signals:
            symbol = sig.symbol

            # Check if there is already an open position for this symbol.
            if symbol in open_positions:
                pos = open_positions[symbol]

                # Opposite signal → close position.
                if sig.direction != pos.direction:
                    fill = self._find_price(symbol, sig.timestamp, price_data)
                    if fill:
                        exit_ts, exit_px = fill
                        exit_px_slip = self._apply_slippage(exit_px, -pos.direction)
                        gross_pnl = (exit_px_slip - pos.entry_price) * pos.direction * pos.quantity
                        net_pnl = gross_pnl - 2.0 * self.commission_per_trade
                        ret_pct = net_pnl / (pos.entry_price * pos.quantity) if pos.entry_price > 0 else 0.0

                        trade = Trade(
                            entry_time=pos.entry_time,
                            exit_time=exit_ts,
                            symbol=symbol,
                            direction=pos.direction,
                            entry_price=pos.entry_price,
                            exit_price=exit_px_slip,
                            quantity=pos.quantity,
                            pnl=net_pnl,
                            return_pct=ret_pct,
                        )
                        completed_trades.append(trade)
                        capital += net_pnl
                        equity_curve.append(capital)
                        del open_positions[symbol]
                # Same direction → ignore (already long/short).
            else:
                # Open new position.
                fill = self._find_price(symbol, sig.timestamp, price_data)
                if fill:
                    entry_ts, entry_px = fill
                    entry_px_slip = self._apply_slippage(entry_px, sig.direction)
                    position_value = capital * self.position_size_pct
                    quantity = position_value / entry_px_slip if entry_px_slip > 0 else 0.0

                    if quantity > 0:
                        open_positions[symbol] = _OpenPosition(
                            symbol=symbol,
                            direction=sig.direction,
                            entry_price=entry_px_slip,
                            entry_time=entry_ts,
                            quantity=quantity,
                            signal_source=sig.source,
                        )

            # Force-close positions held beyond max_holding_days.
            symbols_to_close = []
            for sym, pos in open_positions.items():
                bars = price_data.get(sym, [])
                for ts, px in bars:
                    days_held = (ts - pos.entry_time).total_seconds() / 86_400.0
                    if days_held >= self.max_holding_days:
                        exit_px_slip = self._apply_slippage(px, -pos.direction)
                        gross_pnl = (exit_px_slip - pos.entry_price) * pos.direction * pos.quantity
                        net_pnl = gross_pnl - 2.0 * self.commission_per_trade
                        ret_pct = net_pnl / (pos.entry_price * pos.quantity) if pos.entry_price > 0 else 0.0
                        trade = Trade(
                            entry_time=pos.entry_time,
                            exit_time=ts,
                            symbol=sym,
                            direction=pos.direction,
                            entry_price=pos.entry_price,
                            exit_price=exit_px_slip,
                            quantity=pos.quantity,
                            pnl=net_pnl,
                            return_pct=ret_pct,
                        )
                        completed_trades.append(trade)
                        capital += net_pnl
                        equity_curve.append(capital)
                        symbols_to_close.append(sym)
                        break

            for sym in symbols_to_close:
                open_positions.pop(sym, None)

        # Close any remaining open positions at last available price.
        for sym, pos in open_positions.items():
            bars = price_data.get(sym, [])
            if bars:
                exit_ts, exit_px = bars[-1]
                exit_px_slip = self._apply_slippage(exit_px, -pos.direction)
                gross_pnl = (exit_px_slip - pos.entry_price) * pos.direction * pos.quantity
                net_pnl = gross_pnl - 2.0 * self.commission_per_trade
                ret_pct = net_pnl / (pos.entry_price * pos.quantity) if pos.entry_price > 0 else 0.0
                trade = Trade(
                    entry_time=pos.entry_time,
                    exit_time=exit_ts,
                    symbol=sym,
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    exit_price=exit_px_slip,
                    quantity=pos.quantity,
                    pnl=net_pnl,
                    return_pct=ret_pct,
                )
                completed_trades.append(trade)
                capital += net_pnl
                equity_curve.append(capital)

        # Compute metrics.
        total_return = (capital - self.initial_capital) / self.initial_capital

        # Equity-curve daily returns for Sharpe.
        daily_returns: list[float] = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]
            if prev > 0:
                daily_returns.append((equity_curve[i] - prev) / prev)

        sharpe = self.sharpe_ratio(daily_returns)
        mdd = self.max_drawdown(equity_curve)

        wins = [t for t in completed_trades if t.pnl > 0]
        losses = [t for t in completed_trades if t.pnl <= 0]
        win_rate = len(wins) / len(completed_trades) if completed_trades else 0.0

        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        durations: list[float] = [
            (t.exit_time - t.entry_time).total_seconds() / 86_400.0
            for t in completed_trades
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        return BacktestResult(
            trades=completed_trades,
            equity_curve=equity_curve,
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=mdd,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_trade_duration_days=avg_duration,
        )
