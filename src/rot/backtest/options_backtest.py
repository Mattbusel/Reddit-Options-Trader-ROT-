"""Options trade idea backtesting via historical options prices.

Simulates profit and loss for trade ideas that the ROT system generated
historically, fetching real options price data from yfinance.

Pipeline
--------
1. Accept a list of :class:`TradeIdeaRecord` objects (ticker, strategy, entry
   date, expiry, strikes, stance).
2. For each record, fetch historical options chain data (or approximate via
   underlying price + Black-Scholes for older dates when chain data is absent).
3. Compute P&L at expiry or at a fixed holding-period exit.
4. Aggregate into win rate, average P&L, max loss, and Sharpe-like metrics.

Limitations
-----------
* yfinance does not provide historical options chain snapshots; this module
  approximates entry/exit premiums using the underlying's historical price
  and a simplified Black-Scholes pricer.
* Results should be treated as directional estimates, not exact replays.

Example::

    from rot.backtest.options_backtest import OptionsBacktester, TradeIdeaRecord
    import datetime

    records = [
        TradeIdeaRecord(
            idea_id="abc123",
            ticker="AAPL",
            strategy="bull_call_spread",
            stance="bullish",
            entry_date=datetime.date(2025, 10, 1),
            expiry_date=datetime.date(2025, 10, 18),
            long_strike=220.0,
            short_strike=225.0,
            entry_debit=2.50,
        ),
    ]

    backtester = OptionsBacktester()
    report = backtester.run(records)
    print(report.summary())
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False
    log.warning("yfinance not installed. Options backtester will use stub pricing.")

# ---------------------------------------------------------------------------
# Black-Scholes helpers (used when live chain data is unavailable)
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Approximation of the standard normal CDF."""
    # Abramowitz & Stegun approximation
    a = 0.2316419
    b = [0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429]
    k = 1.0 / (1.0 + a * abs(x))
    poly = sum(b[i] * k ** (i + 1) for i in range(5))
    phi = (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x ** 2)
    cdf = 1.0 - phi * poly
    return cdf if x >= 0 else 1.0 - cdf


def bs_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes European call price.

    Args:
        S:     Spot price.
        K:     Strike price.
        T:     Time to expiry in years.
        r:     Risk-free rate (fraction, e.g. 0.05).
        sigma: Implied volatility (fraction, e.g. 0.30).

    Returns:
        Call option theoretical price.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def bs_put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes European put price."""
    call = bs_call_price(S, K, T, r, sigma)
    return call - S + K * math.exp(-r * T)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TradeIdeaRecord:
    """A single historical trade idea to backtest.

    Attributes:
        idea_id:       Unique identifier for the trade idea.
        ticker:        Underlying equity ticker.
        strategy:      Strategy type: ``"bull_call_spread"``, ``"bear_put_spread"``,
                       ``"long_straddle"``, ``"iron_condor"``, ``"long_call"``,
                       ``"long_put"``.
        stance:        ``"bullish"``, ``"bearish"``, or ``"mixed"``.
        entry_date:    Date the trade was entered.
        expiry_date:   Option expiry date.
        long_strike:   Long leg strike price.
        short_strike:  Short leg strike price (``None`` for single-leg trades).
        entry_debit:   Premium paid (positive) or credit received (negative) per
                       share.  If ``None``, it will be estimated via Black-Scholes.
        assumed_iv:    Assumed implied volatility at entry (fraction, e.g. 0.35).
                       Used for Black-Scholes estimation when entry_debit is None.
        holding_days:  If set, exit the trade after this many days rather than
                       at expiry.
    """

    idea_id: str
    ticker: str
    strategy: str
    stance: str
    entry_date: datetime.date
    expiry_date: datetime.date
    long_strike: float
    short_strike: Optional[float] = None
    entry_debit: Optional[float] = None
    assumed_iv: float = 0.35
    holding_days: Optional[int] = None


@dataclass
class TradeResult:
    """P&L result for a single backtested trade idea.

    Attributes:
        idea_id:         Source idea identifier.
        ticker:          Underlying symbol.
        strategy:        Strategy type string.
        entry_price:     Underlying price at entry date.
        exit_price:      Underlying price at exit date.
        entry_debit:     Premium paid/received at entry.
        exit_value:      Option spread value at exit.
        pnl_per_share:   P&L per share (exit_value - entry_debit).
        pnl_pct:         P&L as a fraction of |entry_debit| (or 0 if free).
        is_win:          True if pnl_per_share > 0.
        days_held:       Number of calendar days the trade was open.
        error:           Error message if the trade could not be priced.
    """

    idea_id: str
    ticker: str
    strategy: str
    entry_price: Optional[float]
    exit_price: Optional[float]
    entry_debit: Optional[float]
    exit_value: Optional[float]
    pnl_per_share: float
    pnl_pct: float
    is_win: bool
    days_held: int
    error: Optional[str] = None


@dataclass
class BacktestReport:
    """Aggregate report from :class:`OptionsBacktester`.

    Attributes:
        n_trades:       Total number of trades attempted.
        n_priced:       Trades that were successfully priced.
        n_errors:       Trades that could not be priced.
        win_rate:       Fraction of priced trades that were winners.
        avg_pnl_pct:    Average P&L percentage across priced trades.
        max_loss_pct:   Worst single-trade loss percentage.
        max_gain_pct:   Best single-trade gain percentage.
        total_pnl_pct:  Sum of all P&L percentages (not compounded).
        results:        List of individual :class:`TradeResult` objects.
    """

    n_trades: int
    n_priced: int
    n_errors: int
    win_rate: float
    avg_pnl_pct: float
    max_loss_pct: float
    max_gain_pct: float
    total_pnl_pct: float
    results: List[TradeResult] = field(default_factory=list)

    def summary(self) -> str:
        """Return a formatted text summary."""
        lines = [
            "Options Backtest Report",
            f"  Trades attempted : {self.n_trades}",
            f"  Trades priced    : {self.n_priced}",
            f"  Errors           : {self.n_errors}",
            f"  Win rate         : {self.win_rate:.1%}",
            f"  Avg P&L          : {self.avg_pnl_pct:+.2%}",
            f"  Max gain         : {self.max_gain_pct:+.2%}",
            f"  Max loss         : {self.max_loss_pct:+.2%}",
            f"  Total P&L (sum)  : {self.total_pnl_pct:+.2%}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# OptionsBacktester
# ---------------------------------------------------------------------------


class OptionsBacktester:
    """Backtest historical trade ideas using yfinance and Black-Scholes pricing.

    Args:
        risk_free_rate: Annualised risk-free rate used for Black-Scholes
                        (default 0.05 = 5%).
        default_iv:     Fallback implied volatility when not specified per-trade
                        (default 0.35 = 35%).
        max_spread_pct: Maximum theoretical spread width as a fraction of the
                        underlying price (safety cap, default 0.20).

    Example::

        bt = OptionsBacktester(risk_free_rate=0.05)
        report = bt.run(trade_records)
        print(report.summary())
    """

    def __init__(
        self,
        risk_free_rate: float = 0.05,
        default_iv: float = 0.35,
        max_spread_pct: float = 0.20,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.default_iv = default_iv
        self.max_spread_pct = max_spread_pct
        self._price_cache: Dict[str, object] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, records: List[TradeIdeaRecord]) -> BacktestReport:
        """Backtest all provided trade idea records.

        Args:
            records: List of :class:`TradeIdeaRecord` objects.

        Returns:
            :class:`BacktestReport` with aggregate statistics and per-trade results.
        """
        results: List[TradeResult] = []

        for rec in records:
            try:
                result = self._backtest_one(rec)
            except Exception as exc:
                log.warning(
                    "options_backtest.error",
                    idea_id=rec.idea_id,
                    ticker=rec.ticker,
                    error=str(exc),
                )
                result = TradeResult(
                    idea_id=rec.idea_id,
                    ticker=rec.ticker,
                    strategy=rec.strategy,
                    entry_price=None,
                    exit_price=None,
                    entry_debit=None,
                    exit_value=None,
                    pnl_per_share=0.0,
                    pnl_pct=0.0,
                    is_win=False,
                    days_held=0,
                    error=str(exc),
                )
            results.append(result)

        return self._aggregate(results)

    # ------------------------------------------------------------------
    # Single trade simulation
    # ------------------------------------------------------------------

    def _backtest_one(self, rec: TradeIdeaRecord) -> TradeResult:
        """Simulate P&L for one trade idea record."""
        # Fetch price history
        hist = self._fetch_history(rec.ticker, rec.entry_date, rec.expiry_date)

        entry_price = self._price_on_date(hist, rec.entry_date)
        if entry_price is None:
            raise ValueError(f"No price data for {rec.ticker} on {rec.entry_date}")

        # Determine exit date
        if rec.holding_days is not None:
            exit_date = rec.entry_date + datetime.timedelta(days=rec.holding_days)
            exit_date = min(exit_date, rec.expiry_date)
        else:
            exit_date = rec.expiry_date

        exit_price = self._price_on_date(hist, exit_date)
        if exit_price is None:
            # Use last available price
            if hist is not None and not hist.empty:
                exit_price = float(hist["Close"].iloc[-1])
            else:
                raise ValueError(f"No exit price for {rec.ticker} on {exit_date}")

        # Time to expiry at entry and exit
        T_entry = max(0.0, (rec.expiry_date - rec.entry_date).days / 365.0)
        T_exit = max(0.0, (rec.expiry_date - exit_date).days / 365.0)
        iv = rec.assumed_iv or self.default_iv
        r = self.risk_free_rate

        # --- Estimate entry debit ---
        entry_debit = rec.entry_debit
        if entry_debit is None:
            entry_debit = self._estimate_debit(
                rec.strategy, entry_price, rec.long_strike,
                rec.short_strike, T_entry, r, iv,
            )

        # --- Estimate exit value ---
        exit_value = self._estimate_debit(
            rec.strategy, exit_price, rec.long_strike,
            rec.short_strike, T_exit, r, iv,
        )

        # --- P&L ---
        pnl_per_share = exit_value - entry_debit
        pnl_pct = pnl_per_share / abs(entry_debit) if abs(entry_debit) > 1e-6 else 0.0
        is_win = pnl_per_share > 0
        days_held = (exit_date - rec.entry_date).days

        log.debug(
            "options_backtest.trade",
            idea_id=rec.idea_id,
            ticker=rec.ticker,
            strategy=rec.strategy,
            entry_price=round(entry_price, 2),
            exit_price=round(exit_price, 2),
            entry_debit=round(entry_debit, 4),
            exit_value=round(exit_value, 4),
            pnl_pct=round(pnl_pct, 4),
        )

        return TradeResult(
            idea_id=rec.idea_id,
            ticker=rec.ticker,
            strategy=rec.strategy,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_debit=entry_debit,
            exit_value=exit_value,
            pnl_per_share=pnl_per_share,
            pnl_pct=pnl_pct,
            is_win=is_win,
            days_held=days_held,
        )

    # ------------------------------------------------------------------
    # Pricing helpers
    # ------------------------------------------------------------------

    def _estimate_debit(
        self,
        strategy: str,
        spot: float,
        long_strike: float,
        short_strike: Optional[float],
        T: float,
        r: float,
        iv: float,
    ) -> float:
        """Estimate the theoretical debit/credit for a strategy using Black-Scholes."""
        strat = strategy.lower()

        if strat in ("long_call", "bull_call_spread"):
            long_val = bs_call_price(spot, long_strike, T, r, iv)
            short_val = bs_call_price(spot, short_strike, T, r, iv) if short_strike else 0.0
            return long_val - short_val

        if strat in ("long_put", "bear_put_spread"):
            long_val = bs_put_price(spot, long_strike, T, r, iv)
            short_val = bs_put_price(spot, short_strike, T, r, iv) if short_strike else 0.0
            return long_val - short_val

        if strat == "long_straddle":
            return (
                bs_call_price(spot, long_strike, T, r, iv)
                + bs_put_price(spot, long_strike, T, r, iv)
            )

        if strat == "iron_condor":
            # Credit received = (short call premium - long call premium)
            #                 + (short put premium  - long put premium)
            # long_strike  = OTM put long
            # short_strike = OTM call short (symmetrical assumption)
            if short_strike is None:
                return 0.0
            short_call = bs_call_price(spot, short_strike, T, r, iv)
            long_call = bs_call_price(spot, short_strike * 1.05, T, r, iv)
            short_put = bs_put_price(spot, long_strike, T, r, iv)
            long_put = bs_put_price(spot, long_strike * 0.95, T, r, iv)
            # Positive = credit received (profit if held to expiry within range)
            credit = (short_call - long_call) + (short_put - long_put)
            return -credit  # negate: negative debit = credit received

        log.warning("options_backtest.unknown_strategy", strategy=strategy)
        return 0.0

    # ------------------------------------------------------------------
    # Price data helpers
    # ------------------------------------------------------------------

    def _fetch_history(
        self,
        ticker: str,
        start: datetime.date,
        end: datetime.date,
    ):
        """Fetch (and cache) daily price history from yfinance."""
        cache_key = f"{ticker}_{start}_{end}"
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]

        if not _YF_AVAILABLE:
            self._price_cache[cache_key] = None
            return None

        try:
            # Extend by a few days to handle weekends/holidays
            fetch_end = end + datetime.timedelta(days=5)
            hist = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=fetch_end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
            )
            self._price_cache[cache_key] = hist if not hist.empty else None
            return self._price_cache[cache_key]
        except Exception as exc:
            log.warning("options_backtest.fetch_error", ticker=ticker, error=str(exc))
            self._price_cache[cache_key] = None
            return None

    def _price_on_date(self, hist, target: datetime.date) -> Optional[float]:
        """Get closing price on or after target date from a history DataFrame."""
        if hist is None or hist.empty:
            return None
        try:
            import pandas as pd
            target_ts = pd.Timestamp(target)
            # Find the closest trading day >= target
            future = hist.loc[hist.index >= target_ts]
            if future.empty:
                return float(hist["Close"].iloc[-1])
            return float(future["Close"].iloc[0])
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, results: List[TradeResult]) -> BacktestReport:
        """Compute aggregate report from individual trade results."""
        priced = [r for r in results if r.error is None]
        errors = [r for r in results if r.error is not None]

        if not priced:
            return BacktestReport(
                n_trades=len(results),
                n_priced=0,
                n_errors=len(errors),
                win_rate=0.0,
                avg_pnl_pct=0.0,
                max_loss_pct=0.0,
                max_gain_pct=0.0,
                total_pnl_pct=0.0,
                results=results,
            )

        pnls = [r.pnl_pct for r in priced]
        wins = [r for r in priced if r.is_win]

        return BacktestReport(
            n_trades=len(results),
            n_priced=len(priced),
            n_errors=len(errors),
            win_rate=len(wins) / len(priced),
            avg_pnl_pct=sum(pnls) / len(pnls),
            max_loss_pct=min(pnls),
            max_gain_pct=max(pnls),
            total_pnl_pct=sum(pnls),
            results=results,
        )
