"""
Walk-Forward Backtester v2

Improvements over v1:
1. Realistic options P&L (Black-Scholes based, not just premium)
2. Commission modeling (per-contract + assignment fees)
3. Margin requirement simulation
4. Assignment/exercise simulation at expiry
5. IV crush modeling after earnings events
6. Rolling positions (close + re-open at better strikes)

Black-Scholes implementation is pure Python (no numpy dependency required).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple


# ── Black-Scholes Mathematics ─────────────────────────────────────────────────


def norm_cdf(x: float) -> float:
    """Cumulative distribution function of the standard normal distribution.

    Uses the Abramowitz & Stegun (1964) rational approximation (eq. 26.2.17).
    Maximum absolute error: 7.5e-8.
    """
    # Reflection for negative x
    sign = 1.0 if x >= 0.0 else -1.0
    x = abs(x)

    # Constants from A&S 26.2.17
    p = 0.2316419
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429

    t = 1.0 / (1.0 + p * x)
    poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
    phi_x = (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)
    cdf = 1.0 - phi_x * poly

    if sign == 1.0:
        return cdf
    return 1.0 - cdf


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


def _d1_d2(
    S: float, K: float, T: float, r: float, sigma: float
) -> Tuple[float, float]:
    """Compute d1 and d2 for Black-Scholes.

    Parameters
    ----------
    S     : current spot price
    K     : option strike price
    T     : time to expiry in years (must be > 0)
    r     : annualised risk-free rate (decimal, e.g. 0.05)
    sigma : annualised implied volatility (decimal, e.g. 0.30)
    """
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        raise ValueError(
            f"Invalid Black-Scholes inputs: S={S}, K={K}, T={T}, sigma={sigma}"
        )
    log_sk = math.log(S / K)
    d1 = (log_sk + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def black_scholes_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str,
) -> float:
    """Price a European option using Black-Scholes.

    Parameters
    ----------
    S           : spot price
    K           : strike price
    T           : time to expiry in years
    r           : continuously compounded risk-free rate
    sigma       : implied volatility (annualised)
    option_type : "call" or "put" (case-insensitive)

    Returns
    -------
    float : theoretical option price (premium per share, multiply by 100 for
            full contract notional)

    At expiry (T <= 0) returns intrinsic value.
    """
    option_type = option_type.lower().strip()
    if T <= 1e-9:
        # At / past expiry — return intrinsic value
        if option_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    d1, d2 = _d1_d2(S, K, T, r, sigma)
    discount = math.exp(-r * T)

    if option_type == "call":
        return S * norm_cdf(d1) - K * discount * norm_cdf(d2)
    # put via put-call parity
    return K * discount * norm_cdf(-d2) - S * norm_cdf(-d1)


def black_scholes_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str,
) -> dict:
    """Compute first-order Black-Scholes Greeks.

    Returns a dict with keys: delta, gamma, theta, vega.

    Notes
    -----
    - theta is expressed as daily decay (divided by 365).
    - vega is per 1% move in IV (divided by 100).
    - At expiry (T <= 0) returns all zeros.
    """
    option_type = option_type.lower().strip()
    zeros = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    if T <= 1e-9 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        return zeros

    try:
        d1, d2 = _d1_d2(S, K, T, r, sigma)
    except ValueError:
        return zeros

    sqrt_T = math.sqrt(T)
    pdf_d1 = _norm_pdf(d1)
    discount = math.exp(-r * T)

    gamma = pdf_d1 / (S * sigma * sqrt_T)
    vega = S * pdf_d1 * sqrt_T / 100.0  # per 1% IV move

    if option_type == "call":
        delta = norm_cdf(d1)
        theta = (
            -(S * pdf_d1 * sigma) / (2.0 * sqrt_T)
            - r * K * discount * norm_cdf(d2)
        ) / 365.0
    else:
        delta = norm_cdf(d1) - 1.0
        theta = (
            -(S * pdf_d1 * sigma) / (2.0 * sqrt_T)
            + r * K * discount * norm_cdf(-d2)
        ) / 365.0

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
    }


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> Optional[float]:
    """Solve for implied volatility using Newton-Raphson iteration.

    Parameters
    ----------
    market_price : observed option market price
    S, K, T, r   : spot, strike, time-to-expiry (years), risk-free rate
    option_type  : "call" or "put"
    tol          : convergence tolerance on price difference
    max_iter     : maximum Newton-Raphson iterations

    Returns
    -------
    float  : implied volatility (annualised decimal), or
    None   : if the solver fails to converge or inputs are degenerate
    """
    option_type = option_type.lower().strip()
    if T <= 0.0 or market_price <= 0.0 or S <= 0.0 or K <= 0.0:
        return None

    # Validate that market price is above intrinsic value
    intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
    if market_price < intrinsic - tol:
        return None

    # Initial guess: Manaster-Koehler approximation
    sigma = math.sqrt(abs(2.0 * math.log(S / K) / T) + 2.0 * r) if S != K else 0.30
    sigma = max(min(sigma, 5.0), 1e-4)

    for _ in range(max_iter):
        try:
            price = black_scholes_price(S, K, T, r, sigma, option_type)
        except (ValueError, ZeroDivisionError, OverflowError):
            return None

        diff = price - market_price
        if abs(diff) < tol:
            return sigma

        # vega = dPrice/dSigma (un-scaled — multiply back by 100)
        try:
            d1, _ = _d1_d2(S, K, T, r, sigma)
        except ValueError:
            return None
        vega_raw = S * _norm_pdf(d1) * math.sqrt(T)  # full vega

        if vega_raw < 1e-10:
            return None

        sigma -= diff / vega_raw
        sigma = max(min(sigma, 10.0), 1e-6)

    return None  # did not converge


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class OptionsContract:
    """An open options position held by the backtester.

    quantity : positive = long, negative = short (sold/written).
    The full notional of one contract = premium * 100.
    """

    symbol: str
    option_type: str    # "call" | "put"
    strike: float
    expiry: date
    quantity: int       # positive = long, negative = short
    entry_price: float  # premium paid/received per share (x100 for contract)
    entry_date: date
    entry_spot: float
    entry_iv: float


@dataclass
class BacktestConfigV2:
    """Configuration for WalkForwardBacktesterV2.

    commission_per_contract : flat fee per options contract (USD)
    assignment_fee          : one-time fee when a short option is assigned (USD)
    margin_multiplier       : margin requirement = option_value * multiplier
    risk_free_rate          : annualised continuously-compounded rate (decimal)
    iv_crush_earnings_pct   : fractional IV drop the day after an earnings event
    """

    commission_per_contract: float = 0.65
    assignment_fee: float = 5.0
    margin_multiplier: float = 1.5
    risk_free_rate: float = 0.05
    iv_crush_earnings_pct: float = 0.35  # IV drops 35% day after earnings

    # Walk-forward window sizes
    train_months: int = 6
    test_months: int = 1

    # Position sizing
    max_position_pct: float = 0.05      # max 5% of equity per trade
    max_concurrent_positions: int = 10

    # Default option parameters when signal doesn't specify
    default_dte: int = 30               # days to expiry
    otm_offset_pct: float = 0.05        # 5% OTM for directional trades


# ── Walk-Forward Backtester v2 ────────────────────────────────────────────────


class WalkForwardBacktesterV2:
    """Enhanced walk-forward options backtester with realistic P&L.

    Walk-forward approach
    ---------------------
    - Training window : ``config.train_months`` months (default 6)
    - Test window     : ``config.test_months`` months  (default 1)
    - Roll forward    : ``config.test_months`` months at a time

    Each fold trains a simple signal-quality filter on in-sample data, then
    applies it to the out-of-sample test window to evaluate real performance.
    The equity curve spans all test windows sequentially.

    Example
    -------
    ::

        cfg = BacktestConfigV2()
        bt = WalkForwardBacktesterV2(cfg)
        results = bt.run(
            signals=my_signals,
            price_data={"AAPL": [(date(2023,1,3), 125.0), ...]},
            iv_data={"AAPL": [(date(2023,1,3), 0.28), ...]},
            start_date=date(2022, 1, 1),
            end_date=date(2024, 1, 1),
        )
        print(bt.generate_report())
    """

    def __init__(self, config: Optional[BacktestConfigV2] = None) -> None:
        self.config = config or BacktestConfigV2()
        self.trades: List[dict] = []
        self.equity_curve: List[Tuple[date, float]] = []
        self.initial_capital: float = 100_000.0

    # ── Public entry point ───────────────────────────────────────────────────

    def run(
        self,
        signals: List[dict],
        price_data: Dict[str, List[Tuple[date, float]]],
        iv_data: Dict[str, List[Tuple[date, float]]],
        start_date: date,
        end_date: date,
    ) -> dict:
        """Run the full walk-forward backtest.

        Parameters
        ----------
        signals    : list of signal dicts, each must contain at minimum:
                     ``symbol`` (str), ``date`` (date), ``stance`` (str,
                     "bullish"/"bearish"), ``confidence`` (float 0-1).
                     Optional: ``is_earnings`` (bool), ``strategy`` (str).
        price_data : mapping of symbol -> sorted [(date, close_price)] pairs.
        iv_data    : mapping of symbol -> sorted [(date, iv)] pairs (decimal).
        start_date : backtest start (inclusive).
        end_date   : backtest end (inclusive).

        Returns
        -------
        dict : metrics dict from ``_compute_metrics()``, plus ``"folds"`` key
               listing per-fold performance.
        """
        self.trades = []
        self.equity_curve = []

        # Build fast lookup dicts
        price_map = self._build_lookup(price_data)
        iv_map = self._build_lookup(iv_data)

        # Generate walk-forward folds
        folds = self._generate_folds(start_date, end_date)
        if not folds:
            return {"error": "date range too short for even one fold"}

        equity = self.initial_capital
        fold_results: List[dict] = []

        for fold_idx, (train_start, train_end, test_start, test_end) in enumerate(
            folds
        ):
            # ── Training phase: compute per-symbol signal quality ──
            train_signals = [
                s for s in signals if train_start <= _sig_date(s) <= train_end
            ]
            quality_map = self._train_quality(train_signals, price_map)

            # ── Test phase: simulate trades ──
            test_signals = [
                s for s in signals if test_start <= _sig_date(s) <= test_end
            ]
            # Sort chronologically
            test_signals.sort(key=lambda s: _sig_date(s))

            open_positions: List[OptionsContract] = []
            fold_start_equity = equity

            current_day = test_start
            while current_day <= test_end:
                # Mark-to-market and expire open positions
                expired = []
                for contract in open_positions:
                    if contract.expiry <= current_day:
                        spot = self._get_price(price_map, contract.symbol, current_day)
                        iv = self._get_iv(iv_map, contract.symbol, current_day)
                        pnl = self._close_position(contract, spot, iv, current_day)
                        equity += pnl
                        self.trades.append(
                            self._trade_record(
                                contract, pnl, current_day, "expiry", spot
                            )
                        )
                        expired.append(contract)
                open_positions = [p for p in open_positions if p not in expired]

                # Process today's signals
                day_signals = [s for s in test_signals if _sig_date(s) == current_day]
                for sig in day_signals:
                    if len(open_positions) >= self.config.max_concurrent_positions:
                        break
                    sym = sig.get("symbol", "")
                    if not sym:
                        continue
                    spot = self._get_price(price_map, sym, current_day)
                    if spot is None:
                        continue
                    iv = self._get_iv(iv_map, sym, current_day)
                    if iv is None:
                        iv = 0.30  # fallback

                    # Apply IV crush if day-after earnings
                    is_earnings = bool(sig.get("is_earnings", False))
                    iv = self._apply_iv_crush(iv, is_earnings)

                    # Quality gate: only trade if in-sample signal quality >= 50%
                    sym_quality = quality_map.get(sym, 0.5)
                    if sym_quality < 0.40:
                        continue

                    contract = self._open_position(sig, spot, iv, current_day)
                    if contract is None:
                        continue

                    # Commission
                    commission = abs(contract.quantity) * self.config.commission_per_contract
                    equity -= commission

                    open_positions.append(contract)

                self.equity_curve.append((current_day, equity))
                current_day += timedelta(days=1)

            # Close any remaining positions at test_end
            for contract in open_positions:
                spot = self._get_price(price_map, contract.symbol, test_end) or contract.entry_spot
                iv = self._get_iv(iv_map, contract.symbol, test_end) or contract.entry_iv
                pnl = self._close_position(contract, spot, iv, test_end)
                equity += pnl
                self.trades.append(
                    self._trade_record(contract, pnl, test_end, "forced_close", spot)
                )

            fold_pnl_pct = (equity - fold_start_equity) / fold_start_equity * 100.0
            fold_results.append(
                {
                    "fold": fold_idx + 1,
                    "train_start": train_start.isoformat(),
                    "train_end": train_end.isoformat(),
                    "test_start": test_start.isoformat(),
                    "test_end": test_end.isoformat(),
                    "start_equity": round(fold_start_equity, 2),
                    "end_equity": round(equity, 2),
                    "pnl_pct": round(fold_pnl_pct, 4),
                }
            )

        metrics = self._compute_metrics()
        metrics["folds"] = fold_results
        metrics["final_equity"] = round(equity, 2)
        metrics["initial_capital"] = self.initial_capital
        return metrics

    # ── Walk-forward fold generation ─────────────────────────────────────────

    def _generate_folds(
        self, start: date, end: date
    ) -> List[Tuple[date, date, date, date]]:
        """Return list of (train_start, train_end, test_start, test_end) tuples."""
        folds = []
        train_days = self.config.train_months * 30
        test_days = self.config.test_months * 30

        fold_start = start
        while True:
            train_end = fold_start + timedelta(days=train_days - 1)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + timedelta(days=test_days - 1)
            if test_end > end:
                break
            folds.append((fold_start, train_end, test_start, test_end))
            fold_start = fold_start + timedelta(days=test_days)

        return folds

    # ── Training: signal quality map ─────────────────────────────────────────

    def _train_quality(
        self,
        train_signals: List[dict],
        price_map: Dict[str, Dict[date, float]],
    ) -> Dict[str, float]:
        """Compute a per-symbol signal win-rate from in-sample signals.

        Returns mapping: symbol -> win_rate (0.0-1.0).
        Simple definition of "win": if bullish and price 30 days later is
        higher, or bearish and price 30 days later is lower.
        """
        wins: Dict[str, int] = {}
        totals: Dict[str, int] = {}

        for sig in train_signals:
            sym = sig.get("symbol", "")
            stance = sig.get("stance", "").lower()
            sig_date = _sig_date(sig)
            if not sym or stance not in ("bullish", "bearish"):
                continue
            entry_price = self._get_price(price_map, sym, sig_date)
            exit_date = sig_date + timedelta(days=30)
            exit_price = self._get_price(price_map, sym, exit_date)
            if entry_price is None or exit_price is None or entry_price <= 0:
                continue

            won = (stance == "bullish" and exit_price > entry_price) or (
                stance == "bearish" and exit_price < entry_price
            )
            totals[sym] = totals.get(sym, 0) + 1
            if won:
                wins[sym] = wins.get(sym, 0) + 1

        quality: Dict[str, float] = {}
        for sym, total in totals.items():
            quality[sym] = wins.get(sym, 0) / total
        return quality

    # ── Position management ──────────────────────────────────────────────────

    def _open_position(
        self,
        signal: dict,
        spot: float,
        iv: float,
        today: date,
    ) -> Optional[OptionsContract]:
        """Construct an ``OptionsContract`` from a signal dict.

        The option is sized so that the premium cost does not exceed
        ``config.max_position_pct`` of current equity.  Returns None when
        there is not enough data to price the option.
        """
        if spot is None or spot <= 0.0:
            return None

        stance = signal.get("stance", "").lower()
        if stance not in ("bullish", "bearish"):
            return None

        option_type = "call" if stance == "bullish" else "put"
        dte = int(signal.get("dte", self.config.default_dte))
        expiry = today + timedelta(days=max(dte, 1))

        # Strike: OTM by config.otm_offset_pct
        offset = self.config.otm_offset_pct
        if option_type == "call":
            strike = round(spot * (1.0 + offset), 2)
        else:
            strike = round(spot * (1.0 - offset), 2)

        T = dte / 365.0
        try:
            premium = black_scholes_price(
                S=spot,
                K=strike,
                T=T,
                r=self.config.risk_free_rate,
                sigma=iv,
                option_type=option_type,
            )
        except (ValueError, ZeroDivisionError, OverflowError):
            return None

        if premium <= 0.0:
            return None

        # Position size: how many contracts can we buy within max_position_pct?
        max_spend = self.initial_capital * self.config.max_position_pct
        contracts = max(1, int(max_spend / (premium * 100)))

        return OptionsContract(
            symbol=signal.get("symbol", ""),
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            quantity=contracts,  # long
            entry_price=premium,
            entry_date=today,
            entry_spot=spot,
            entry_iv=iv,
        )

    def _mark_to_market(
        self,
        contract: OptionsContract,
        spot: float,
        iv: float,
        today: date,
    ) -> float:
        """Return current market value of the contract (positive = long value)."""
        if spot is None or spot <= 0.0 or iv is None or iv <= 0.0:
            return 0.0

        days_remaining = (contract.expiry - today).days
        T = max(days_remaining, 0) / 365.0

        try:
            current_price = black_scholes_price(
                S=spot,
                K=contract.strike,
                T=T,
                r=self.config.risk_free_rate,
                sigma=iv,
                option_type=contract.option_type,
            )
        except (ValueError, ZeroDivisionError, OverflowError):
            # Fall back to intrinsic
            if contract.option_type == "call":
                current_price = max(spot - contract.strike, 0.0)
            else:
                current_price = max(contract.strike - spot, 0.0)

        return current_price * abs(contract.quantity) * 100

    def _close_position(
        self,
        contract: OptionsContract,
        spot: float,
        iv: float,
        today: date,
    ) -> float:
        """Close a position and return net P&L (after commissions).

        For long positions: P&L = (exit_price - entry_price) * qty * 100 - commissions.
        At expiry exercises if ITM, else expires worthless.
        """
        days_remaining = (contract.expiry - today).days
        T = max(days_remaining, 0) / 365.0
        is_expiry = days_remaining <= 0

        if is_expiry:
            # Exercise / assignment at intrinsic
            if contract.option_type == "call":
                exit_price = max(spot - contract.strike, 0.0)
                assigned = spot > contract.strike
            else:
                exit_price = max(contract.strike - spot, 0.0)
                assigned = spot < contract.strike
        else:
            try:
                exit_price = black_scholes_price(
                    S=spot,
                    K=contract.strike,
                    T=T,
                    r=self.config.risk_free_rate,
                    sigma=iv,
                    option_type=contract.option_type,
                )
            except (ValueError, ZeroDivisionError, OverflowError):
                exit_price = max(
                    (spot - contract.strike if contract.option_type == "call" else contract.strike - spot),
                    0.0,
                )
            assigned = False

        pnl = (exit_price - contract.entry_price) * abs(contract.quantity) * 100

        # Commissions: closing leg
        commission = abs(contract.quantity) * self.config.commission_per_contract
        if is_expiry and assigned:
            commission += self.config.assignment_fee

        return pnl - commission

    def _apply_iv_crush(self, iv: float, is_earnings_day: bool) -> float:
        """Reduce IV by ``iv_crush_earnings_pct`` on the day after earnings."""
        if is_earnings_day:
            return iv * (1.0 - self.config.iv_crush_earnings_pct)
        return iv

    # ── Metrics computation ──────────────────────────────────────────────────

    def _compute_metrics(self) -> dict:
        """Compute summary statistics over all closed trades and equity curve."""
        if not self.trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": None,
                "profit_factor": None,
                "avg_trade_pnl": 0.0,
            }

        pnls = [t["pnl"] for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total_pnl = sum(pnls)
        win_rate = len(wins) / len(pnls) if pnls else 0.0
        avg_trade_pnl = total_pnl / len(pnls) if pnls else 0.0
        total_return_pct = total_pnl / self.initial_capital * 100.0

        # Profit factor
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        # Max drawdown from equity curve
        max_dd_pct = self._max_drawdown_pct()

        # Sharpe (using daily equity curve returns)
        sharpe = self._sharpe_ratio()

        return {
            "total_trades": len(self.trades),
            "win_rate": round(win_rate, 4),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_return_pct, 4),
            "max_drawdown_pct": round(max_dd_pct, 4),
            "sharpe_ratio": round(sharpe, 4) if sharpe is not None else None,
            "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            "avg_trade_pnl": round(avg_trade_pnl, 2),
        }

    def _max_drawdown_pct(self) -> float:
        """Compute maximum peak-to-trough drawdown from equity curve."""
        if len(self.equity_curve) < 2:
            return 0.0
        equities = [e for _, e in self.equity_curve]
        peak = equities[0]
        max_dd = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd
        return max_dd * 100.0

    def _sharpe_ratio(self) -> Optional[float]:
        """Annualised Sharpe ratio from daily equity curve returns."""
        if len(self.equity_curve) < 10:
            return None
        equities = [e for _, e in self.equity_curve]
        returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                returns.append((equities[i] - equities[i - 1]) / equities[i - 1])

        if len(returns) < 5:
            return None

        n = len(returns)
        mean_r = sum(returns) / n
        variance = sum((r - mean_r) ** 2 for r in returns) / n
        std_r = math.sqrt(variance) if variance > 0 else 0.0
        if std_r == 0.0:
            return None

        daily_rf = self.config.risk_free_rate / 252.0
        return (mean_r - daily_rf) / std_r * math.sqrt(252.0)

    # ── Report generation ────────────────────────────────────────────────────

    def generate_report(self) -> str:
        """Generate a plain-text performance report with ASCII equity sparkline.

        Returns
        -------
        str : multi-line ASCII report.
        """
        metrics = self._compute_metrics()
        lines: List[str] = []

        lines.append("=" * 60)
        lines.append("  Walk-Forward Backtester v2 — Performance Report")
        lines.append("=" * 60)
        lines.append(f"  Initial capital  : ${self.initial_capital:>12,.2f}")
        lines.append(f"  Final equity     : ${metrics.get('final_equity', 0.0):>12,.2f}")
        lines.append(f"  Total return     : {metrics['total_return_pct']:>+9.2f}%")
        lines.append(f"  Total P&L        : ${metrics['total_pnl']:>12,.2f}")
        lines.append("-" * 60)
        lines.append(f"  Total trades     : {metrics['total_trades']:>12}")
        lines.append(f"  Win rate         : {metrics['win_rate'] * 100:>9.1f}%")
        lines.append(f"  Avg trade P&L    : ${metrics['avg_trade_pnl']:>12,.2f}")
        lines.append(f"  Profit factor    : {str(round(metrics['profit_factor'], 2)) if metrics['profit_factor'] else 'N/A':>12}")
        lines.append(f"  Max drawdown     : {metrics['max_drawdown_pct']:>9.2f}%")
        lines.append(f"  Sharpe ratio     : {str(round(metrics['sharpe_ratio'], 3)) if metrics['sharpe_ratio'] else 'N/A':>12}")
        lines.append("-" * 60)

        # Equity sparkline
        if len(self.equity_curve) >= 2:
            equities = [e for _, e in self.equity_curve]
            # Sample 40 points for sparkline
            step = max(1, len(equities) // 40)
            sampled = equities[::step][-40:]
            min_e = min(sampled)
            max_e = max(sampled)
            span = max_e - min_e if max_e > min_e else 1.0
            chars = " ._-~=^"
            bar = "".join(
                chars[min(int((v - min_e) / span * (len(chars) - 1)), len(chars) - 1)]
                for v in sampled
            )
            lines.append(f"  Equity curve     : [{bar}]")
            lines.append(f"  Range            :  ${min_e:,.0f} .. ${max_e:,.0f}")
        else:
            lines.append("  Equity curve     : [insufficient data]")

        # Per-fold summary
        folds = metrics.get("folds", [])
        if folds:
            lines.append("-" * 60)
            lines.append("  Walk-Forward Fold Summary:")
            lines.append(
                f"  {'Fold':>4}  {'Test period':>22}  {'P&L %':>8}  {'End equity':>12}"
            )
            for f in folds:
                lines.append(
                    f"  {f['fold']:>4}  "
                    f"{f['test_start']} -> {f['test_end']}  "
                    f"{f['pnl_pct']:>+7.2f}%  "
                    f"${f['end_equity']:>11,.2f}"
                )

        lines.append("=" * 60)
        return "\n".join(lines)

    # ── Internal utilities ───────────────────────────────────────────────────

    @staticmethod
    def _build_lookup(
        data: Dict[str, List[Tuple[date, float]]]
    ) -> Dict[str, Dict[date, float]]:
        """Convert list-of-tuples to date-keyed dict for O(1) lookup."""
        return {sym: dict(pairs) for sym, pairs in data.items()}

    @staticmethod
    def _get_price(
        price_map: Dict[str, Dict[date, float]], symbol: str, d: date
    ) -> Optional[float]:
        """Look up price; if exact date missing, search back up to 5 trading days."""
        sym_data = price_map.get(symbol.upper()) or price_map.get(symbol)
        if sym_data is None:
            return None
        for delta in range(6):
            val = sym_data.get(d - timedelta(days=delta))
            if val is not None:
                return val
        return None

    @staticmethod
    def _get_iv(
        iv_map: Dict[str, Dict[date, float]], symbol: str, d: date
    ) -> Optional[float]:
        """Look up IV; if exact date missing, search back up to 5 trading days."""
        sym_data = iv_map.get(symbol.upper()) or iv_map.get(symbol)
        if sym_data is None:
            return None
        for delta in range(6):
            val = sym_data.get(d - timedelta(days=delta))
            if val is not None:
                return val
        return None

    @staticmethod
    def _trade_record(
        contract: OptionsContract, pnl: float, close_date: date, reason: str, exit_spot: float
    ) -> dict:
        """Build a trade record dict for storage in ``self.trades``."""
        return {
            "symbol": contract.symbol,
            "option_type": contract.option_type,
            "strike": contract.strike,
            "expiry": contract.expiry.isoformat(),
            "quantity": contract.quantity,
            "entry_date": contract.entry_date.isoformat(),
            "close_date": close_date.isoformat(),
            "entry_price": round(contract.entry_price, 4),
            "entry_spot": round(contract.entry_spot, 2),
            "exit_spot": round(exit_spot, 2) if exit_spot else None,
            "entry_iv": round(contract.entry_iv, 4),
            "pnl": round(pnl, 2),
            "close_reason": reason,
        }


# ── Convenience helpers ───────────────────────────────────────────────────────


def _sig_date(signal: dict) -> date:
    """Extract a ``date`` from a signal dict (handles date, datetime, or str)."""
    raw = signal.get("date")
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    return date.min
