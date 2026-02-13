"""Core backtesting engine — portfolio simulation from signal history.

Takes a list of signal dicts (from ``get_backtest_signals()``) and a
``BacktestConfig`` and produces a ``BacktestResult``.

Design goals:
  - Zero lookahead bias (signals sorted chronologically, processed in order)
  - Stance-aware P&L (mirrors ``_WIN_CASE_SQL`` / ``_LOSS_CASE_SQL`` from database.py)
  - Pluggable position sizing (fixed %, Kelly, confidence-weighted)
  - Stop-loss / take-profit simulation via ``max_gain_pct`` / ``max_loss_pct``
"""

from __future__ import annotations

import math
import time as _time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from rot.backtest.config import BacktestConfig
from rot.backtest.metrics import (
    compute_annual_return,
    compute_calmar_ratio,
    compute_cvar,
    compute_drawdown_periods,
    compute_expectancy,
    compute_mae_mfe,
    compute_max_drawdown,
    compute_monthly_returns,
    compute_profit_factor,
    compute_recovery_factor,
    compute_sharpe_ratio,
    compute_sortino_ratio,
    compute_strategy_breakdown,
    compute_var,
    compute_win_rate,
)
from rot.backtest.result import BacktestResult, EquityPoint, TradeRecord


# ── Stance-aware P&L calculation (mirrors database.py SQL) ──


def _compute_pnl_pct(
    stance: str,
    strategy: str,
    entry_price: float,
    exit_price: float,
    max_gain_pct: Optional[float] = None,
    max_loss_pct: Optional[float] = None,
) -> float:
    """Compute P&L percentage given stance/strategy/prices.

    Mirrors the win/loss logic from database.py ``_WIN_CASE_SQL`` /
    ``_LOSS_CASE_SQL``:
      - **bullish**: pnl = (exit - entry) / entry
      - **bearish**: pnl = (entry - exit) / entry  (profit when price drops)
      - **mixed/unknown**: pnl = 0 (neutral, no directional bet)

    Only bullish and bearish signals count as trades. Strategy type is
    irrelevant for win/loss determination.

    If stop_loss or take_profit are active (via max_loss_pct / max_gain_pct from
    signal_performance), the raw pnl is clamped.
    """
    if entry_price <= 0:
        return 0.0

    raw_move = (exit_price - entry_price) / entry_price  # signed

    if stance == "bullish":
        pnl = raw_move
    elif stance == "bearish":
        pnl = -raw_move  # bearish profits when price drops
    else:
        # mixed/unknown stance → neutral (no directional bet to evaluate)
        pnl = 0.0

    pnl_pct = pnl * 100  # convert to percentage

    # Apply stop-loss / take-profit caps from max_gain_pct / max_loss_pct
    if max_gain_pct is not None and pnl_pct > max_gain_pct:
        pnl_pct = max_gain_pct
    if max_loss_pct is not None and pnl_pct < -abs(max_loss_pct):
        pnl_pct = -abs(max_loss_pct)

    return pnl_pct


def _resolve_exit_price(signal: Dict[str, Any], use_1d: bool) -> Optional[float]:
    """Pick exit price from signal_performance columns.

    Mirrors ``_PRICE_COL = COALESCE(sp.price_1d, sp.price_4h, sp.price_1h)``
    from database.py. When ``use_1d=False``, prefers 4h first.
    """
    if use_1d:
        candidates = [
            signal.get("price_1d"),
            signal.get("price_4h"),
            signal.get("price_1h"),
        ]
    else:
        candidates = [
            signal.get("price_4h"),
            signal.get("price_1h"),
            signal.get("price_1d"),
        ]
    for p in candidates:
        if p is not None and p > 0:
            return float(p)
    return None


# ── Position sizing ──


def _position_size_fixed(equity: float, pct: float) -> float:
    """Fixed percentage of current equity."""
    return equity * (pct / 100.0)


def _position_size_kelly(
    equity: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    max_pct: float = 25.0,
) -> float:
    """Kelly criterion: f* = (p*b - q) / b  where p=win rate, b=avg_win/avg_loss.

    Capped at ``max_pct`` of equity to avoid extreme bets. Uses half-Kelly
    for safety (Kelly is aggressive in practice).
    """
    if avg_loss <= 0 or win_rate <= 0:
        return equity * 0.02  # minimum 2%
    b = avg_win / avg_loss
    q = 1.0 - win_rate
    kelly_fraction = (win_rate * b - q) / b
    kelly_fraction = max(0.01, min(kelly_fraction, max_pct / 100.0))
    # Half-Kelly for safety
    return equity * (kelly_fraction / 2.0)


def _position_size_confidence(
    equity: float,
    confidence: float,
    base_pct: float = 5.0,
) -> float:
    """Scale position by signal confidence: high confidence → larger position.

    Range: 0.5x to 2x the base percentage.
    """
    scale = 0.5 + confidence * 1.5  # maps [0,1] → [0.5, 2.0]
    return equity * (base_pct / 100.0) * scale


# ── Main Engine ──


class BacktestEngine:
    """Stateless backtest engine.

    Usage::

        engine = BacktestEngine()
        result = engine.run(signals, config)
    """

    def run(
        self,
        signals: List[Dict[str, Any]],
        config: BacktestConfig,
    ) -> BacktestResult:
        """Run a full backtest simulation.

        Parameters
        ----------
        signals:
            List of signal dicts from ``database.get_backtest_signals()``.
            Expected keys: signal_id, ticker, stance, strategy, event_type,
            confidence, created_at, price_at_signal, price_1h, price_4h,
            price_1d, max_gain_pct, max_loss_pct.
        config:
            Backtest configuration (position sizing, filters, etc.).

        Returns
        -------
        BacktestResult with full metrics, equity curve, and trade records.
        """
        # 1. Filter signals
        filtered = self._apply_filters(signals, config)

        # 2. Sort chronologically (no lookahead bias)
        filtered.sort(key=lambda s: s.get("created_at", 0))

        # 3. Simulate portfolio
        equity = config.starting_capital
        trades: List[TradeRecord] = []
        equity_curve: List[EquityPoint] = [
            EquityPoint(
                timestamp=filtered[0]["created_at"] if filtered else _time.time(),
                equity=equity,
                trade_count=0,
            )
        ]

        # Running stats for Kelly sizing
        total_wins = 0
        total_losses = 0
        sum_win_pct = 0.0
        sum_loss_pct = 0.0

        # Track concurrent positions (simplified: each signal is one trade)
        open_count = 0
        # We process signals sequentially; since we use exit prices that
        # are already resolved, each "position" opens and closes instantly
        # in our simulation (entry → known exit). This is a simplification;
        # real walk-forward would need to track overlapping positions.

        for sig in filtered:
            # Check exit price availability
            exit_price = _resolve_exit_price(sig, config.use_1d_price)
            entry_price = sig.get("price_at_signal")

            if exit_price is None or entry_price is None or entry_price <= 0:
                continue  # skip signals without price data

            # Skip non-directional signals — only bullish/bearish are tradeable
            stance = sig.get("stance", "unknown")
            if stance not in ("bullish", "bearish"):
                continue

            # Position sizing
            if config.position_size_mode == "kelly":
                running_win_rate = (
                    total_wins / (total_wins + total_losses)
                    if (total_wins + total_losses) > 0
                    else 0.5
                )
                avg_win = (
                    sum_win_pct / total_wins if total_wins > 0 else 2.0
                )
                avg_loss = (
                    sum_loss_pct / total_losses if total_losses > 0 else 2.0
                )
                position_value = _position_size_kelly(
                    equity, running_win_rate, avg_win, avg_loss
                )
            elif config.position_size_mode == "confidence_weighted":
                position_value = _position_size_confidence(
                    equity,
                    sig.get("confidence", 0.5),
                    config.position_size_pct,
                )
            else:  # fixed_pct
                position_value = _position_size_fixed(
                    equity, config.position_size_pct
                )

            # Don't risk more than current equity
            position_value = min(position_value, equity)
            if position_value < 1.0:
                continue  # can't trade with < $1

            # Compute P&L
            strategy = sig.get("strategy", "debit_spread")

            # Stop loss / take profit: use config values or signal's max_gain/max_loss
            stop_loss = None
            take_profit = None
            if config.stop_loss_pct > 0:
                stop_loss = config.stop_loss_pct
            if config.take_profit_pct > 0:
                take_profit = config.take_profit_pct

            # Use signal's actual max_gain/max_loss to cap the exit realism
            sig_max_gain = sig.get("max_gain_pct")
            sig_max_loss = sig.get("max_loss_pct")

            pnl_pct = _compute_pnl_pct(
                stance=stance,
                strategy=strategy,
                entry_price=entry_price,
                exit_price=exit_price,
                max_gain_pct=take_profit if take_profit else sig_max_gain,
                max_loss_pct=stop_loss if stop_loss else sig_max_loss,
            )

            pnl_dollars = position_value * (pnl_pct / 100.0)
            is_win = pnl_pct > 0

            # Update equity
            equity += pnl_dollars

            # Prevent negative equity (can't lose more than position)
            if equity < 0:
                equity = 0.0

            # Record trade
            trade = TradeRecord(
                signal_id=sig.get("signal_id", ""),
                ticker=sig.get("ticker", ""),
                stance=stance,
                strategy=strategy,
                event_type=sig.get("event_type", "other"),
                confidence=sig.get("confidence", 0.0),
                entry_time=sig.get("created_at", 0.0),
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_pct=round(pnl_pct, 4),
                pnl_dollars=round(pnl_dollars, 2),
                is_win=is_win,
            )
            trades.append(trade)

            # Update running stats for Kelly
            if is_win:
                total_wins += 1
                sum_win_pct += abs(pnl_pct)
            else:
                total_losses += 1
                sum_loss_pct += abs(pnl_pct)

            # Record equity point
            equity_curve.append(
                EquityPoint(
                    timestamp=sig.get("created_at", 0.0),
                    equity=round(equity, 2),
                    trade_count=len(trades),
                )
            )

        # 4. Compute metrics
        return self._build_result(trades, equity_curve, config)

    def _apply_filters(
        self,
        signals: List[Dict[str, Any]],
        config: BacktestConfig,
    ) -> List[Dict[str, Any]]:
        """Filter signals based on config criteria."""
        result = []
        for s in signals:
            if config.min_confidence > 0 and s.get("confidence", 0) < config.min_confidence:
                continue
            if config.strategy_filter and s.get("strategy") != config.strategy_filter:
                continue
            if config.event_type_filter and s.get("event_type") != config.event_type_filter:
                continue
            if config.stance_filter and s.get("stance") != config.stance_filter:
                continue
            if config.ticker_filter and s.get("ticker") != config.ticker_filter:
                continue
            result.append(s)
        return result

    def _build_result(
        self,
        trades: List[TradeRecord],
        equity_curve: List[EquityPoint],
        config: BacktestConfig,
    ) -> BacktestResult:
        """Assemble BacktestResult from trades and equity curve."""
        total = len(trades)
        winners = [t for t in trades if t.is_win]
        losers = [t for t in trades if not t.is_win]

        win_rate = compute_win_rate(trades)
        final_equity = equity_curve[-1].equity if equity_curve else config.starting_capital

        total_return_pct = (
            (final_equity - config.starting_capital) / config.starting_capital * 100
            if config.starting_capital > 0
            else 0.0
        )

        # Time span for annualization
        if len(equity_curve) >= 2:
            span_s = equity_curve[-1].timestamp - equity_curve[0].timestamp
            span_days = max(1, int(span_s / 86400))
        else:
            span_days = config.days

        annual_return = compute_annual_return(total_return_pct, span_days)

        # Risk-adjusted ratios
        sharpe = compute_sharpe_ratio(equity_curve)
        sortino = compute_sortino_ratio(equity_curve)
        max_dd_pct, max_dd_dur = compute_max_drawdown(equity_curve)
        calmar = compute_calmar_ratio(annual_return, max_dd_pct)

        # Trade quality
        profit_factor = compute_profit_factor(trades)
        expectancy = compute_expectancy(trades)
        avg_win_pct = (
            sum(t.pnl_pct for t in winners) / len(winners) if winners else 0.0
        )
        avg_loss_pct = (
            sum(t.pnl_pct for t in losers) / len(losers) if losers else 0.0
        )

        # Detailed breakdowns
        monthly = compute_monthly_returns(trades)
        strategy_bd = compute_strategy_breakdown(trades)
        dd_periods = compute_drawdown_periods(equity_curve)

        return BacktestResult(
            total_trades=total,
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=round(win_rate, 4),
            total_return_pct=round(total_return_pct, 2),
            annual_return_pct=round(annual_return, 2),
            final_equity=round(final_equity, 2),
            sharpe_ratio=round(sharpe, 4) if sharpe is not None else None,
            sortino_ratio=round(sortino, 4) if sortino is not None else None,
            calmar_ratio=round(calmar, 4) if calmar is not None else None,
            max_drawdown_pct=round(max_dd_pct, 2),
            max_drawdown_duration_s=round(max_dd_dur, 1),
            profit_factor=round(profit_factor, 4),
            expectancy=round(expectancy, 4),
            avg_win_pct=round(avg_win_pct, 2),
            avg_loss_pct=round(avg_loss_pct, 2),
            equity_curve=equity_curve,
            trades=trades,
            monthly_returns=monthly,
            strategy_breakdown=strategy_bd,
            drawdown_periods=dd_periods,
            config_dict=config.to_dict(),
            created_at=_time.time(),
        )
