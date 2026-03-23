"""Strategy-level backtesting for Reddit signal strategies.

Provides a high-level backtesting layer that sits on top of the core
``BacktestEngine``, adding signal history loading, extended metrics,
walk-forward validation, Monte Carlo simulation, and HTML report output.

Classes
-------
SignalHistoryLoader
    Loads and filters past signals from a SQLite database or an in-memory
    list (useful for testing).
BacktestMetrics
    Extended metric set: Sharpe, Sortino, max drawdown, win rate, avg P&L,
    calmar, profit factor.
WalkForwardTester
    Rolling in-sample/out-of-sample testing over configurable folds.
MonteCarloSimulator
    Bootstraps signal order to test statistical significance of results.
StrategyBacktester
    Orchestrator: loads signals, runs engine + WF + MC, generates HTML report.
"""

from __future__ import annotations

import math
import random
import statistics
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from rot.backtest.config import BacktestConfig
from rot.backtest.engine import BacktestEngine
from rot.backtest.metrics import (
    compute_max_drawdown,
    compute_sharpe_ratio,
    compute_sortino_ratio,
    compute_win_rate,
    compute_profit_factor,
    compute_expectancy,
    compute_annual_return,
)
from rot.backtest.result import BacktestResult, EquityPoint, TradeRecord
from rot.backtest.walk_forward import WalkForwardResult, run_walk_forward


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BacktestMetrics:
    """Extended backtest metric set for strategy evaluation."""

    total_trades: int
    win_rate: float
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    calmar_ratio: Optional[float]
    max_drawdown_pct: float
    total_return_pct: float
    annual_return_pct: float
    profit_factor: float
    expectancy_dollars: float
    avg_win_pct: float
    avg_loss_pct: float
    avg_pnl_pct: float      # mean P&L across ALL trades (wins + losses)
    best_trade_pct: float
    worst_trade_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4) if self.sharpe_ratio else None,
            "sortino_ratio": round(self.sortino_ratio, 4) if self.sortino_ratio else None,
            "calmar_ratio": round(self.calmar_ratio, 4) if self.calmar_ratio else None,
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "annual_return_pct": round(self.annual_return_pct, 2),
            "profit_factor": round(self.profit_factor, 4),
            "expectancy_dollars": round(self.expectancy_dollars, 2),
            "avg_win_pct": round(self.avg_win_pct, 2),
            "avg_loss_pct": round(self.avg_loss_pct, 2),
            "avg_pnl_pct": round(self.avg_pnl_pct, 2),
            "best_trade_pct": round(self.best_trade_pct, 2),
            "worst_trade_pct": round(self.worst_trade_pct, 2),
        }


@dataclass(frozen=True)
class MonteCarloResult:
    """Output from Monte Carlo simulation."""

    n_simulations: int
    n_trades: int
    # Return distribution across simulations
    mean_return_pct: float
    median_return_pct: float
    p5_return_pct: float     # 5th percentile (bad case)
    p95_return_pct: float    # 95th percentile (good case)
    prob_profit: float       # fraction of sims that were profitable
    prob_ruin: float         # fraction of sims with final equity < ruin_threshold
    # Equity distribution
    final_equity_p5: float
    final_equity_p50: float
    final_equity_p95: float
    # Statistical significance
    p_value_approx: float    # fraction of MC runs that beat observed return

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_simulations": self.n_simulations,
            "n_trades": self.n_trades,
            "mean_return_pct": round(self.mean_return_pct, 2),
            "median_return_pct": round(self.median_return_pct, 2),
            "p5_return_pct": round(self.p5_return_pct, 2),
            "p95_return_pct": round(self.p95_return_pct, 2),
            "prob_profit": round(self.prob_profit, 4),
            "prob_ruin": round(self.prob_ruin, 4),
            "final_equity_p5": round(self.final_equity_p5, 2),
            "final_equity_p50": round(self.final_equity_p50, 2),
            "final_equity_p95": round(self.final_equity_p95, 2),
            "p_value_approx": round(self.p_value_approx, 4),
        }


@dataclass
class StrategyBacktestReport:
    """Full backtest report produced by StrategyBacktester."""

    strategy_name: str
    config: BacktestConfig
    engine_result: BacktestResult
    metrics: BacktestMetrics
    walk_forward: Optional[WalkForwardResult]
    monte_carlo: Optional[MonteCarloResult]
    n_signals_loaded: int
    elapsed_s: float
    created_at: float = field(default_factory=_time.time)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "strategy_name": self.strategy_name,
            "config": self.config.to_dict(),
            "metrics": self.metrics.to_dict(),
            "n_signals_loaded": self.n_signals_loaded,
            "elapsed_s": round(self.elapsed_s, 3),
            "created_at": self.created_at,
            **self.engine_result.to_dict(),
        }
        if self.walk_forward:
            d["walk_forward"] = {
                "n_folds": self.walk_forward.n_folds,
                "stability_score": self.walk_forward.stability_score,
                "avg_oos_return_pct": self.walk_forward.avg_oos_return_pct,
                "avg_oos_win_rate": self.walk_forward.avg_oos_win_rate,
                "avg_degradation_pct": self.walk_forward.avg_degradation_pct,
                "folds": [
                    {
                        "fold_index": f.fold_index,
                        "is_signals": f.is_signals,
                        "oos_signals": f.oos_signals,
                        "is_return_pct": f.is_return_pct,
                        "oos_return_pct": f.oos_return_pct,
                        "is_win_rate": f.is_win_rate,
                        "oos_win_rate": f.oos_win_rate,
                        "degradation_pct": f.degradation_pct,
                    }
                    for f in self.walk_forward.folds
                ],
            }
        if self.monte_carlo:
            d["monte_carlo"] = self.monte_carlo.to_dict()
        return d


# ---------------------------------------------------------------------------
# SignalHistoryLoader
# ---------------------------------------------------------------------------


class SignalHistoryLoader:
    """Loads and filters historical signals for backtesting.

    Supports two backends:
    1. **In-memory list**: pass ``signals`` directly to the constructor.
    2. **SQLite database**: call ``from_db()`` with a path and optional query.

    Filtering via ``filter()`` mirrors ``BacktestEngine._apply_filters()``.
    """

    def __init__(self, signals: Optional[List[Dict[str, Any]]] = None) -> None:
        self._signals: List[Dict[str, Any]] = list(signals) if signals else []

    @classmethod
    def from_db(
        cls,
        db_path: str,
        days: int = 90,
        ticker: Optional[str] = None,
    ) -> "SignalHistoryLoader":
        """Load signals from a SQLite database.

        Parameters
        ----------
        db_path:
            Path to the SQLite database file.
        days:
            How many days back to load signals.
        ticker:
            If set, restrict to this ticker only.

        Returns
        -------
        SignalHistoryLoader
        """
        try:
            import sqlite3
        except ImportError:
            return cls([])

        cutoff = _time.time() - days * 86400

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # Try the signals + signal_performance join (ROT schema)
            query = """
                SELECT
                    s.id            AS signal_id,
                    s.ticker,
                    s.stance,
                    s.strategy,
                    s.event_type,
                    s.confidence,
                    s.created_at,
                    s.price_at_signal,
                    sp.price_1h,
                    sp.price_4h,
                    sp.price_1d,
                    sp.max_gain_pct,
                    sp.max_loss_pct
                FROM signals s
                LEFT JOIN signal_performance sp ON sp.signal_id = s.id
                WHERE s.created_at >= ?
            """
            params: list = [cutoff]

            if ticker:
                query += " AND s.ticker = ?"
                params.append(ticker)

            query += " ORDER BY s.created_at ASC"

            cur.execute(query, params)
            rows = cur.fetchall()
            conn.close()

            signals = [dict(row) for row in rows]
            return cls(signals)

        except Exception:
            return cls([])

    @property
    def signals(self) -> List[Dict[str, Any]]:
        return list(self._signals)

    def filter(
        self,
        min_confidence: float = 0.0,
        stance: Optional[str] = None,
        strategy: Optional[str] = None,
        event_type: Optional[str] = None,
        ticker: Optional[str] = None,
    ) -> "SignalHistoryLoader":
        """Return a new loader containing only matching signals.

        Parameters
        ----------
        min_confidence:
            Drop signals below this confidence.
        stance:
            Keep only this stance value.
        strategy:
            Keep only this strategy type.
        event_type:
            Keep only this event type.
        ticker:
            Keep only this ticker.

        Returns
        -------
        SignalHistoryLoader (new instance, original unmodified)
        """
        out = []
        for s in self._signals:
            if min_confidence > 0 and (s.get("confidence") or 0) < min_confidence:
                continue
            if stance and s.get("stance") != stance:
                continue
            if strategy and s.get("strategy") != strategy:
                continue
            if event_type and s.get("event_type") != event_type:
                continue
            if ticker and s.get("ticker") != ticker:
                continue
            out.append(s)
        return SignalHistoryLoader(out)

    def __len__(self) -> int:
        return len(self._signals)


# ---------------------------------------------------------------------------
# BacktestMetrics builder
# ---------------------------------------------------------------------------


def _build_metrics(result: BacktestResult) -> BacktestMetrics:
    """Construct BacktestMetrics from a BacktestResult."""
    trades = result.trades
    winners = [t for t in trades if t.is_win]
    losers = [t for t in trades if not t.is_win]

    avg_win = sum(t.pnl_pct for t in winners) / len(winners) if winners else 0.0
    avg_loss = sum(t.pnl_pct for t in losers) / len(losers) if losers else 0.0
    avg_pnl = sum(t.pnl_pct for t in trades) / len(trades) if trades else 0.0

    best = max((t.pnl_pct for t in trades), default=0.0)
    worst = min((t.pnl_pct for t in trades), default=0.0)

    calmar: Optional[float] = None
    if result.max_drawdown_pct and result.max_drawdown_pct > 0.01 and result.annual_return_pct:
        calmar = result.annual_return_pct / result.max_drawdown_pct

    return BacktestMetrics(
        total_trades=result.total_trades,
        win_rate=result.win_rate,
        sharpe_ratio=result.sharpe_ratio,
        sortino_ratio=result.sortino_ratio,
        calmar_ratio=calmar,
        max_drawdown_pct=result.max_drawdown_pct,
        total_return_pct=result.total_return_pct,
        annual_return_pct=result.annual_return_pct,
        profit_factor=result.profit_factor,
        expectancy_dollars=result.expectancy,
        avg_win_pct=round(avg_win, 4),
        avg_loss_pct=round(avg_loss, 4),
        avg_pnl_pct=round(avg_pnl, 4),
        best_trade_pct=round(best, 4),
        worst_trade_pct=round(worst, 4),
    )


# ---------------------------------------------------------------------------
# WalkForwardTester
# ---------------------------------------------------------------------------


class WalkForwardTester:
    """Walk-forward validation wrapper with configurable fold count.

    Thin wrapper around ``rot.backtest.walk_forward.run_walk_forward`` that
    adds convenience methods.
    """

    def __init__(
        self,
        n_folds: int = 5,
        in_sample_pct: float = 0.70,
    ) -> None:
        if n_folds < 2:
            raise ValueError("n_folds must be >= 2")
        if not (0.5 <= in_sample_pct < 1.0):
            raise ValueError("in_sample_pct must be in [0.5, 1.0)")
        self.n_folds = n_folds
        self.in_sample_pct = in_sample_pct

    def run(
        self,
        signals: List[Dict[str, Any]],
        config: BacktestConfig,
    ) -> WalkForwardResult:
        """Run walk-forward analysis.

        Parameters
        ----------
        signals:
            Signal list (same format as BacktestEngine.run()).
        config:
            Backtest configuration.

        Returns
        -------
        WalkForwardResult
        """
        return run_walk_forward(
            signals=signals,
            config=config,
            n_folds=self.n_folds,
            in_sample_pct=self.in_sample_pct,
        )


# ---------------------------------------------------------------------------
# MonteCarloSimulator
# ---------------------------------------------------------------------------


class MonteCarloSimulator:
    """Monte Carlo bootstrap by shuffling signal order.

    Randomly permutes the order of signals ``n_simulations`` times and runs
    a backtest on each permutation.  The resulting return distribution tells
    us whether the observed results depend on the *ordering* of signals
    (which would suggest luck / path dependency rather than edge).

    A low ``p_value_approx`` means few random orderings matched or beat the
    original result — evidence the strategy has genuine edge.

    Parameters
    ----------
    n_simulations:
        Number of Monte Carlo runs.  Default 500.
    ruin_threshold_pct:
        Portfolio drawdown at which a simulation is counted as "ruin".
        Default 50 (50% loss from starting capital).
    seed:
        Optional RNG seed for reproducibility.
    """

    def __init__(
        self,
        n_simulations: int = 500,
        ruin_threshold_pct: float = 50.0,
        seed: Optional[int] = None,
    ) -> None:
        if n_simulations < 10:
            raise ValueError("n_simulations must be >= 10")
        self.n_simulations = n_simulations
        self.ruin_threshold_pct = ruin_threshold_pct
        self._rng = random.Random(seed)

    def run(
        self,
        signals: List[Dict[str, Any]],
        config: BacktestConfig,
        observed_return_pct: float = 0.0,
    ) -> MonteCarloResult:
        """Run Monte Carlo simulation.

        Parameters
        ----------
        signals:
            Signal list for permutation.
        config:
            Backtest configuration.
        observed_return_pct:
            The actual (non-shuffled) total return for p-value calculation.

        Returns
        -------
        MonteCarloResult
        """
        if not signals:
            return MonteCarloResult(
                n_simulations=0,
                n_trades=0,
                mean_return_pct=0.0,
                median_return_pct=0.0,
                p5_return_pct=0.0,
                p95_return_pct=0.0,
                prob_profit=0.0,
                prob_ruin=0.0,
                final_equity_p5=config.starting_capital,
                final_equity_p50=config.starting_capital,
                final_equity_p95=config.starting_capital,
                p_value_approx=1.0,
            )

        engine = BacktestEngine()
        returns: List[float] = []
        final_equities: List[float] = []
        ruin_count = 0

        ruin_equity_floor = config.starting_capital * (1.0 - self.ruin_threshold_pct / 100.0)

        for _ in range(self.n_simulations):
            shuffled = list(signals)
            self._rng.shuffle(shuffled)
            # Assign new timestamps to preserve engine ordering logic
            for i, s in enumerate(shuffled):
                shuffled[i] = {**s, "created_at": float(i)}

            result = engine.run(shuffled, config)
            ret = result.total_return_pct
            eq = result.final_equity
            returns.append(ret)
            final_equities.append(eq)
            if eq <= ruin_equity_floor:
                ruin_count += 1

        returns.sort()
        final_equities.sort()
        n = len(returns)

        def _percentile(sorted_lst: List[float], pct: float) -> float:
            idx = max(0, min(int(pct * n), n - 1))
            return sorted_lst[idx]

        mean_ret = sum(returns) / n
        median_ret = _percentile(returns, 0.50)
        p5 = _percentile(returns, 0.05)
        p95 = _percentile(returns, 0.95)
        prob_profit = sum(1 for r in returns if r > 0) / n
        prob_ruin = ruin_count / n

        # p-value: fraction of MC runs that BEAT the observed result
        beats = sum(1 for r in returns if r >= observed_return_pct)
        p_value = beats / n

        return MonteCarloResult(
            n_simulations=n,
            n_trades=len(signals),
            mean_return_pct=round(mean_ret, 2),
            median_return_pct=round(median_ret, 2),
            p5_return_pct=round(p5, 2),
            p95_return_pct=round(p95, 2),
            prob_profit=round(prob_profit, 4),
            prob_ruin=round(prob_ruin, 4),
            final_equity_p5=round(_percentile(final_equities, 0.05), 2),
            final_equity_p50=round(_percentile(final_equities, 0.50), 2),
            final_equity_p95=round(_percentile(final_equities, 0.95), 2),
            p_value_approx=round(p_value, 4),
        )


# ---------------------------------------------------------------------------
# StrategyBacktester
# ---------------------------------------------------------------------------


class StrategyBacktester:
    """High-level backtester that orchestrates all sub-components.

    Runs the full analysis pipeline:
    1. Load signals via ``SignalHistoryLoader``
    2. Run core ``BacktestEngine``
    3. Compute extended ``BacktestMetrics``
    4. Optionally run ``WalkForwardTester``
    5. Optionally run ``MonteCarloSimulator``
    6. Generate HTML report

    Parameters
    ----------
    run_walk_forward:
        Whether to include walk-forward testing.
    run_monte_carlo:
        Whether to include Monte Carlo simulation.
    n_wf_folds:
        Number of walk-forward folds (default 5).
    n_mc_simulations:
        Number of Monte Carlo simulations (default 500).
    mc_seed:
        Optional seed for reproducible Monte Carlo runs.
    """

    def __init__(
        self,
        run_walk_forward: bool = True,
        run_monte_carlo: bool = True,
        n_wf_folds: int = 5,
        n_mc_simulations: int = 500,
        mc_seed: Optional[int] = None,
    ) -> None:
        self._run_wf = run_walk_forward
        self._run_mc = run_monte_carlo
        self._wf_tester = WalkForwardTester(n_folds=n_wf_folds) if run_walk_forward else None
        self._mc_sim = MonteCarloSimulator(n_simulations=n_mc_simulations, seed=mc_seed) if run_monte_carlo else None

    def run(
        self,
        strategy_name: str,
        loader: SignalHistoryLoader,
        config: Optional[BacktestConfig] = None,
    ) -> StrategyBacktestReport:
        """Run the full backtest pipeline.

        Parameters
        ----------
        strategy_name:
            Human-readable name for the strategy being tested.
        loader:
            Populated ``SignalHistoryLoader`` instance.
        config:
            Backtest configuration; defaults to ``BacktestConfig()``.

        Returns
        -------
        StrategyBacktestReport
        """
        t0 = _time.time()
        if config is None:
            config = BacktestConfig()

        signals = loader.signals

        # Core backtest
        engine = BacktestEngine()
        engine_result = engine.run(signals, config)
        metrics = _build_metrics(engine_result)

        # Walk-forward
        wf_result: Optional[WalkForwardResult] = None
        if self._wf_tester and len(signals) >= 20:
            wf_result = self._wf_tester.run(signals, config)

        # Monte Carlo
        mc_result: Optional[MonteCarloResult] = None
        if self._mc_sim and len(signals) >= 10:
            mc_result = self._mc_sim.run(
                signals,
                config,
                observed_return_pct=engine_result.total_return_pct,
            )

        elapsed = _time.time() - t0
        return StrategyBacktestReport(
            strategy_name=strategy_name,
            config=config,
            engine_result=engine_result,
            metrics=metrics,
            walk_forward=wf_result,
            monte_carlo=mc_result,
            n_signals_loaded=len(signals),
            elapsed_s=round(elapsed, 3),
        )

    def generate_html(self, report: StrategyBacktestReport) -> str:
        """Generate a standalone HTML report with charts from a backtest report.

        The report includes:
        - KPI summary cards
        - Extended metrics table
        - Walk-forward fold table (if available)
        - Monte Carlo percentile table (if available)
        - SVG equity curve chart
        - Full trade log (up to 200 rows)

        Parameters
        ----------
        report:
            StrategyBacktestReport produced by ``run()``.

        Returns
        -------
        Complete HTML string.
        """
        m = report.metrics
        r = report.engine_result
        wf = report.walk_forward
        mc = report.monte_carlo

        ret_color = "#4ade80" if m.total_return_pct >= 0 else "#f87171"
        wr_color = "#4ade80" if m.win_rate >= 0.5 else "#f87171"
        sharpe_display = f"{m.sharpe_ratio:.3f}" if m.sharpe_ratio else "N/A"
        sortino_display = f"{m.sortino_ratio:.3f}" if m.sortino_ratio else "N/A"
        calmar_display = f"{m.calmar_ratio:.3f}" if m.calmar_ratio else "N/A"
        pf_color = "#4ade80" if m.profit_factor > 1.0 else "#f87171"

        # ── KPI cards ──
        def kpi(label: str, value: str, color: str = "#fff") -> str:
            return (
                f"<div class='kpi'>"
                f"<div class='label'>{label}</div>"
                f"<div class='value' style='color:{color}'>{value}</div>"
                f"</div>"
            )

        kpis = "".join([
            kpi("Strategy", report.strategy_name),
            kpi("Trades", str(m.total_trades)),
            kpi("Win Rate", f"{m.win_rate * 100:.1f}%", wr_color),
            kpi("Total Return", f"{m.total_return_pct:+.1f}%", ret_color),
            kpi("Annual Return", f"{m.annual_return_pct:+.1f}%", ret_color),
            kpi("Max Drawdown", f"{m.max_drawdown_pct:.1f}%", "#f87171"),
            kpi("Sharpe", sharpe_display),
            kpi("Sortino", sortino_display),
            kpi("Calmar", calmar_display),
            kpi("Profit Factor", f"{m.profit_factor:.2f}", pf_color),
            kpi("Avg P&L", f"{m.avg_pnl_pct:+.2f}%"),
            kpi("Expectancy $", f"${m.expectancy_dollars:+.2f}"),
        ])

        # ── Equity curve SVG ──
        svg = _equity_svg(r.equity_curve, width=860, height=200)

        # ── Walk-forward table ──
        wf_html = ""
        if wf and wf.folds:
            rows = ""
            for f in wf.folds:
                dcolor = "#4ade80" if f.oos_return_pct >= 0 else "#f87171"
                rows += (
                    f"<tr><td>{f.fold_index + 1}</td>"
                    f"<td>{f.is_signals}</td><td>{f.oos_signals}</td>"
                    f"<td>{f.is_return_pct:+.1f}%</td>"
                    f"<td style='color:{dcolor}'>{f.oos_return_pct:+.1f}%</td>"
                    f"<td>{f.is_win_rate * 100:.0f}%</td>"
                    f"<td>{f.oos_win_rate * 100:.0f}%</td>"
                    f"<td>{f.degradation_pct:+.1f}%</td></tr>"
                )
            stab_color = "#4ade80" if wf.stability_score >= 0.6 else "#f87171"
            wf_html = f"""
<h2>Walk-Forward Analysis</h2>
<p>Stability Score: <strong style='color:{stab_color}'>{wf.stability_score:.3f}</strong>
   &nbsp;|&nbsp; Avg OOS Return: {wf.avg_oos_return_pct:+.1f}%
   &nbsp;|&nbsp; Avg Degradation: {wf.avg_degradation_pct:+.1f}%</p>
<table>
<thead><tr><th>Fold</th><th>IS Trades</th><th>OOS Trades</th>
<th>IS Return</th><th>OOS Return</th><th>IS WR</th><th>OOS WR</th><th>Degradation</th></tr></thead>
<tbody>{rows}</tbody></table>"""

        # ── Monte Carlo table ──
        mc_html = ""
        if mc:
            pcolor = "#4ade80" if mc.prob_profit >= 0.5 else "#f87171"
            pval_color = "#4ade80" if mc.p_value_approx < 0.10 else "#f87171"
            mc_html = f"""
<h2>Monte Carlo Simulation ({mc.n_simulations:,} runs)</h2>
<div class='kpi-grid'>
  <div class='kpi'><div class='label'>Prob. Profit</div>
    <div class='value' style='color:{pcolor}'>{mc.prob_profit * 100:.0f}%</div></div>
  <div class='kpi'><div class='label'>Prob. Ruin</div>
    <div class='value' style='color:#f87171'>{mc.prob_ruin * 100:.1f}%</div></div>
  <div class='kpi'><div class='label'>Median Return</div>
    <div class='value'>{mc.median_return_pct:+.1f}%</div></div>
  <div class='kpi'><div class='label'>5th Pct Return</div>
    <div class='value' style='color:#f87171'>{mc.p5_return_pct:+.1f}%</div></div>
  <div class='kpi'><div class='label'>95th Pct Return</div>
    <div class='value' style='color:#4ade80'>{mc.p95_return_pct:+.1f}%</div></div>
  <div class='kpi'><div class='label'>Median Equity</div>
    <div class='value'>${mc.final_equity_p50:,.0f}</div></div>
  <div class='kpi'><div class='label'>p-value</div>
    <div class='value' style='color:{pval_color}'>{mc.p_value_approx:.3f}</div></div>
</div>"""

        # ── Trade log ──
        trade_rows = ""
        for i, t in enumerate(r.trades[:200], 1):
            pnl_c = "#4ade80" if t.pnl_pct >= 0 else "#f87171"
            badge = "WIN" if t.is_win else "LOSS"
            bg = "#166534" if t.is_win else "#991b1b"
            trade_rows += (
                f"<tr><td>{i}</td>"
                f"<td><strong>{t.ticker}</strong></td>"
                f"<td>{t.stance}</td>"
                f"<td>{t.strategy}</td>"
                f"<td>{t.event_type}</td>"
                f"<td>{t.confidence * 100:.0f}%</td>"
                f"<td>${t.entry_price:.2f}</td>"
                f"<td>${t.exit_price:.2f}</td>"
                f"<td style='color:{pnl_c};font-weight:bold'>{t.pnl_pct:+.2f}%</td>"
                f"<td>${t.pnl_dollars:+.2f}</td>"
                f"<td><span style='background:{bg};padding:2px 6px;border-radius:4px;"
                f"font-size:11px'>{badge}</span></td></tr>\n"
            )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ROT Strategy Backtest — {report.strategy_name}</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;background:#111827;color:#e5e7eb;
  margin:0;padding:24px;}}
h1{{color:#fff;font-size:22px;margin-bottom:4px;}}
h2{{color:#fff;font-size:17px;margin-top:28px;border-bottom:1px solid #374151;
  padding-bottom:8px;}}
p{{color:#9ca3af;font-size:13px;margin:4px 0 12px;}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));
  gap:10px;margin:16px 0;}}
.kpi{{background:rgba(31,41,55,.8);border:1px solid #374151;border-radius:8px;
  padding:12px;}}
.kpi .label{{font-size:10px;color:#9ca3af;text-transform:uppercase;
  letter-spacing:.5px;margin-bottom:4px;}}
.kpi .value{{font-size:20px;font-weight:bold;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
th{{text-align:left;color:#9ca3af;border-bottom:1px solid #374151;padding:8px;
  font-weight:600;}}
td{{padding:7px 8px;border-bottom:1px solid #1f2937;}}
tr:hover{{background:rgba(31,41,55,.5);}}
.chart{{background:rgba(31,41,55,.6);border:1px solid #374151;border-radius:8px;
  padding:12px;margin:16px 0;overflow:hidden;}}
.footer{{margin-top:40px;padding-top:16px;border-top:1px solid #374151;
  font-size:11px;color:#6b7280;}}
</style>
</head>
<body>
<h1>ROT Strategy Backtest Report</h1>
<p>{report.strategy_name} &nbsp;|&nbsp;
   {report.n_signals_loaded} signals loaded &nbsp;|&nbsp;
   Computed in {report.elapsed_s:.2f}s</p>
<div class="kpi-grid">{kpis}</div>
<h2>Equity Curve</h2>
<div class="chart">{svg}</div>
{wf_html}
{mc_html}
<h2>Trade Log (first 200)</h2>
<table>
<thead><tr><th>#</th><th>Ticker</th><th>Stance</th><th>Strategy</th>
<th>Event</th><th>Conf</th><th>Entry</th><th>Exit</th>
<th>P&amp;L %</th><th>P&amp;L $</th><th>Result</th></tr></thead>
<tbody>{trade_rows}</tbody></table>
<div class="footer">
Generated by ROT (Reddit Options Trader) Strategy Backtester.
Results are simulated and for research purposes only. Not financial advice.
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# SVG equity curve helper
# ---------------------------------------------------------------------------


def _equity_svg(
    equity_curve: List[EquityPoint],
    width: int = 860,
    height: int = 200,
) -> str:
    """Render an equity curve as a minimal inline SVG."""
    if len(equity_curve) < 2:
        return f"<svg width='{width}' height='{height}'><text x='10' y='20' fill='#9ca3af'>No equity data</text></svg>"

    equities = [ep.equity for ep in equity_curve]
    e_min = min(equities)
    e_max = max(equities)
    e_range = e_max - e_min if e_max > e_min else 1.0

    pad = 20
    chart_w = width - 2 * pad
    chart_h = height - 2 * pad
    n = len(equities)

    def _x(i: int) -> float:
        return pad + (i / (n - 1)) * chart_w

    def _y(e: float) -> float:
        return pad + (1.0 - (e - e_min) / e_range) * chart_h

    # Build polyline points
    pts = " ".join(f"{_x(i):.1f},{_y(e):.1f}" for i, e in enumerate(equities))

    # Colour: green if profit, red if loss
    line_col = "#4ade80" if equities[-1] >= equities[0] else "#f87171"

    # Fill polygon (close below)
    fill_pts = (
        f"{_x(0):.1f},{_y(equities[0]):.1f} "
        + pts
        + f" {_x(n - 1):.1f},{pad + chart_h} {_x(0):.1f},{pad + chart_h}"
    )

    # Y-axis labels
    labels = ""
    for tick in [e_min, (e_min + e_max) / 2, e_max]:
        y_pos = _y(tick)
        labels += (
            f"<text x='{pad - 4}' y='{y_pos + 4:.1f}' "
            f"text-anchor='end' fill='#6b7280' font-size='10'>"
            f"${tick:,.0f}</text>"
        )

    return (
        f"<svg width='{width}' height='{height}' xmlns='http://www.w3.org/2000/svg'>"
        f"<polygon points='{fill_pts}' fill='{line_col}' fill-opacity='0.12'/>"
        f"<polyline points='{pts}' fill='none' stroke='{line_col}' stroke-width='1.5'/>"
        f"{labels}"
        f"</svg>"
    )
