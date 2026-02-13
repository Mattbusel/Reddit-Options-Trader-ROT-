"""Backtest result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class TradeRecord:
    """A single simulated trade from a backtest run."""

    signal_id: str
    ticker: str
    stance: str
    strategy: str
    event_type: str
    confidence: float
    entry_time: float   # unix timestamp
    entry_price: float
    exit_price: float
    pnl_pct: float      # percentage gain/loss
    pnl_dollars: float   # dollar gain/loss
    is_win: bool


@dataclass(frozen=True)
class EquityPoint:
    """A point on the equity curve."""

    timestamp: float
    equity: float
    trade_count: int


@dataclass(frozen=True)
class DrawdownPeriod:
    """A contiguous drawdown period."""

    start_ts: float
    trough_ts: float
    end_ts: float        # 0 if still in drawdown
    peak_equity: float
    trough_equity: float
    drawdown_pct: float  # as positive number (e.g. 15.0 means -15%)
    duration_s: float


@dataclass(frozen=True)
class BacktestResult:
    """Complete results from a backtest run."""

    # ── Summary stats ──
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float              # 0.0 - 1.0

    total_return_pct: float
    annual_return_pct: float
    final_equity: float

    # ── Risk-adjusted metrics ──
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None

    # ── Drawdown ──
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_s: float = 0.0

    # ── Trade quality ──
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0

    # ── Detailed data ──
    equity_curve: List[EquityPoint] = field(default_factory=list)
    trades: List[TradeRecord] = field(default_factory=list)
    monthly_returns: Dict[str, float] = field(default_factory=dict)
    strategy_breakdown: Dict[str, Dict[str, float]] = field(default_factory=dict)
    drawdown_periods: List[DrawdownPeriod] = field(default_factory=list)

    # ── Metadata ──
    config_dict: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "total_return_pct": round(self.total_return_pct, 2),
            "annual_return_pct": round(self.annual_return_pct, 2),
            "final_equity": round(self.final_equity, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 4) if self.sharpe_ratio is not None else None,
            "sortino_ratio": round(self.sortino_ratio, 4) if self.sortino_ratio is not None else None,
            "calmar_ratio": round(self.calmar_ratio, 4) if self.calmar_ratio is not None else None,
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "max_drawdown_duration_s": round(self.max_drawdown_duration_s, 1),
            "profit_factor": round(self.profit_factor, 4),
            "expectancy": round(self.expectancy, 4),
            "avg_win_pct": round(self.avg_win_pct, 2),
            "avg_loss_pct": round(self.avg_loss_pct, 2),
            "equity_curve": [
                {"ts": ep.timestamp, "equity": round(ep.equity, 2), "trades": ep.trade_count}
                for ep in self.equity_curve
            ],
            "trades": [
                {
                    "signal_id": t.signal_id,
                    "ticker": t.ticker,
                    "stance": t.stance,
                    "strategy": t.strategy,
                    "event_type": t.event_type,
                    "confidence": round(t.confidence, 3),
                    "entry_time": t.entry_time,
                    "entry_price": round(t.entry_price, 2),
                    "exit_price": round(t.exit_price, 2),
                    "pnl_pct": round(t.pnl_pct, 2),
                    "pnl_dollars": round(t.pnl_dollars, 2),
                    "is_win": t.is_win,
                }
                for t in self.trades
            ],
            "monthly_returns": {k: round(v, 2) for k, v in self.monthly_returns.items()},
            "strategy_breakdown": self.strategy_breakdown,
            "drawdown_periods": [
                {
                    "start_ts": dd.start_ts,
                    "trough_ts": dd.trough_ts,
                    "end_ts": dd.end_ts,
                    "peak_equity": round(dd.peak_equity, 2),
                    "trough_equity": round(dd.trough_equity, 2),
                    "drawdown_pct": round(dd.drawdown_pct, 2),
                    "duration_s": round(dd.duration_s, 1),
                }
                for dd in self.drawdown_periods
            ],
            "config": self.config_dict,
            "created_at": self.created_at,
        }
