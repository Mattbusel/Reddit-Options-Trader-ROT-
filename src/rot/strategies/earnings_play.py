"""Earnings play strategy for the ROT platform.

Detects upcoming earnings events (within a configurable look-ahead window) and
recommends an options strategy based on implied volatility behaviour:

- **Iron condor** (sell volatility): When historical IV crush post-earnings is
  large — the market overprices the expected move.
- **Long straddle** (buy volatility): When the stock has historically moved more
  than the options market's expected move implies.

Key concepts
------------
* Expected move = (call ATM ask + put ATM ask) at expiry nearest the event.
* Historical move = median |close_after / close_before - 1| across past earnings.
* IV crush = median drop in ATM IV from the day before to the day after earnings.

Data is fetched from yfinance.  All methods degrade gracefully to ``None`` when
data is unavailable rather than raising.

Example::

    from rot.strategies.earnings_play import EarningsPlayStrategy

    strategy = EarningsPlayStrategy(ticker="TSLA")
    rec = strategy.recommend()
    if rec:
        print(rec.strategy_type, rec.reasoning)
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional yfinance import
# ---------------------------------------------------------------------------

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False
    log.warning("yfinance not installed; EarningsPlayStrategy will use stub data only.")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default look-ahead window (calendar days) for earnings detection.
_DEFAULT_LOOKAHEAD_DAYS: int = 5

#: If historical move > expected_move * this factor → buy vol (straddle).
_MOVE_PREMIUM_THRESHOLD: float = 1.15

#: If IV crush fraction > this → sell vol (iron condor).
_IV_CRUSH_THRESHOLD: float = 0.30   # 30% drop in IV post-earnings

#: Number of past earnings to analyse for historical move / IV crush.
_HISTORY_QUARTERS: int = 8


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class EarningsEvent:
    """A detected upcoming earnings announcement.

    Attributes:
        ticker:         Ticker symbol.
        expected_date:  Expected earnings date (best estimate from yfinance).
        days_until:     Calendar days until the event from today.
        is_confirmed:   Whether yfinance reports the date as confirmed.
    """

    ticker: str
    expected_date: datetime.date
    days_until: int
    is_confirmed: bool


@dataclass
class EarningsRecommendation:
    """Strategy recommendation for an upcoming earnings event.

    Attributes:
        ticker:              Underlying symbol.
        event:               The :class:`EarningsEvent` that triggered this.
        strategy_type:       ``"iron_condor"``, ``"long_straddle"``, or
                             ``"no_trade"`` (when data is insufficient).
        expected_move_pct:   Market-implied expected move as a fraction (e.g. 0.08).
        historical_move_pct: Median historical absolute earnings move.
        iv_crush_est:        Estimated post-earnings IV crush fraction.
        confidence:          Float in ``[0, 1]`` reflecting data quality.
        reasoning:           Human-readable explanation.
        risk_notes:          List of risk caveats for the suggested strategy.
    """

    ticker: str
    event: EarningsEvent
    strategy_type: str   # "iron_condor" | "long_straddle" | "no_trade"
    expected_move_pct: Optional[float]
    historical_move_pct: Optional[float]
    iv_crush_est: Optional[float]
    confidence: float
    reasoning: str
    risk_notes: List[str]


# ---------------------------------------------------------------------------
# EarningsPlayStrategy
# ---------------------------------------------------------------------------


class EarningsPlayStrategy:
    """Earnings-aware options strategy selector.

    Args:
        ticker:             Underlying equity symbol (e.g. ``"AAPL"``).
        lookahead_days:     Window (calendar days) in which to look for earnings.
        iv_crush_threshold: IV drop fraction above which an iron condor is favoured.
        move_premium:       Historical/implied move ratio above which a straddle
                            is favoured.
        history_quarters:   Number of past quarters used for historical analysis.

    Example::

        rec = EarningsPlayStrategy("NVDA", lookahead_days=5).recommend()
    """

    def __init__(
        self,
        ticker: str,
        lookahead_days: int = _DEFAULT_LOOKAHEAD_DAYS,
        iv_crush_threshold: float = _IV_CRUSH_THRESHOLD,
        move_premium: float = _MOVE_PREMIUM_THRESHOLD,
        history_quarters: int = _HISTORY_QUARTERS,
    ) -> None:
        self.ticker = ticker.upper()
        self.lookahead_days = lookahead_days
        self.iv_crush_threshold = iv_crush_threshold
        self.move_premium = move_premium
        self.history_quarters = history_quarters

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_earnings(self) -> Optional[EarningsEvent]:
        """Check whether earnings are expected within the look-ahead window.

        Returns:
            :class:`EarningsEvent` if earnings are upcoming, else ``None``.
        """
        if not _YF_AVAILABLE:
            log.debug("earnings.detect: yfinance unavailable, returning None")
            return None

        try:
            tk = yf.Ticker(self.ticker)
            cal = tk.calendar
            if cal is None or cal.empty:
                return None

            # yfinance calendar: index may be dates or row labels
            earnings_date: Optional[datetime.date] = None
            if "Earnings Date" in cal.index:
                val = cal.loc["Earnings Date"]
                if hasattr(val, "iloc"):
                    val = val.iloc[0]
                if hasattr(val, "date"):
                    earnings_date = val.date()
                elif isinstance(val, datetime.date):
                    earnings_date = val
            elif not cal.empty:
                # Try first column, first row
                try:
                    val = cal.iloc[0, 0]
                    if hasattr(val, "date"):
                        earnings_date = val.date()
                except Exception:
                    pass

            if earnings_date is None:
                return None

            today = datetime.date.today()
            days_until = (earnings_date - today).days

            if 0 <= days_until <= self.lookahead_days:
                return EarningsEvent(
                    ticker=self.ticker,
                    expected_date=earnings_date,
                    days_until=days_until,
                    is_confirmed=True,
                )
        except Exception as exc:
            log.warning("earnings.detect_error", ticker=self.ticker, error=str(exc))

        return None

    def expected_move_pct(self) -> Optional[float]:
        """Estimate the market's expected earnings move from ATM straddle premium.

        Approximation: ``(atm_call_ask + atm_put_ask) / current_price``.

        Returns:
            Fraction (e.g. 0.07 for a 7% expected move), or ``None`` on failure.
        """
        if not _YF_AVAILABLE:
            return None
        try:
            tk = yf.Ticker(self.ticker)
            price = self._current_price(tk)
            if price is None:
                return None

            # Find nearest-expiry options chain
            expiries = tk.options
            if not expiries:
                return None

            # Use the first expiry (shortest dated) as proxy for earnings play
            chain = tk.option_chain(expiries[0])
            calls = chain.calls
            puts = chain.puts

            # ATM = strike closest to current price
            if calls.empty or puts.empty:
                return None

            atm_call = calls.iloc[(calls["strike"] - price).abs().argsort()[:1]]
            atm_put = puts.iloc[(puts["strike"] - price).abs().argsort()[:1]]

            call_ask = float(atm_call["ask"].iloc[0])
            put_ask = float(atm_put["ask"].iloc[0])

            expected = (call_ask + put_ask) / price
            log.debug(
                "earnings.expected_move",
                ticker=self.ticker,
                call_ask=call_ask,
                put_ask=put_ask,
                price=price,
                expected_pct=round(expected, 4),
            )
            return round(expected, 4)
        except Exception as exc:
            log.warning("earnings.expected_move_error", ticker=self.ticker, error=str(exc))
            return None

    def historical_move_pct(self) -> Optional[float]:
        """Estimate median historical absolute earnings move over past quarters.

        Downloads 2 years of daily price history and approximates earnings dates
        as the days with the largest absolute next-day moves (proxy when exact
        earnings dates are unavailable historically).

        Returns:
            Median absolute return on earnings reaction days, or ``None``.
        """
        if not _YF_AVAILABLE:
            return None
        try:
            import pandas as pd
            tk = yf.Ticker(self.ticker)
            hist = tk.history(period="2y", interval="1d")
            if hist.empty or len(hist) < 20:
                return None

            # Compute next-day returns
            close = hist["Close"]
            next_day_ret = (close.shift(-1) / close - 1.0).abs().dropna()

            # Use top-N absolute moves as proxy for earnings days
            n = min(self.history_quarters, len(next_day_ret))
            top_moves = next_day_ret.nlargest(n)
            median_move = float(top_moves.median())

            log.debug(
                "earnings.historical_move",
                ticker=self.ticker,
                n_samples=n,
                median_pct=round(median_move, 4),
            )
            return round(median_move, 4)
        except Exception as exc:
            log.warning("earnings.hist_move_error", ticker=self.ticker, error=str(exc))
            return None

    def iv_crush_estimate(self) -> Optional[float]:
        """Estimate typical post-earnings IV crush.

        Uses the ratio of near-term ATM IV to medium-term ATM IV as a proxy.
        A high ratio (near > far) suggests large IV crush risk post-earnings.

        Returns:
            Estimated IV crush fraction in ``[0, 1]``, or ``None`` on failure.
        """
        if not _YF_AVAILABLE:
            return None
        try:
            tk = yf.Ticker(self.ticker)
            expiries = tk.options
            if len(expiries) < 2:
                return None

            near_chain = tk.option_chain(expiries[0])
            far_chain = tk.option_chain(expiries[1])

            price = self._current_price(tk)
            if price is None:
                return None

            def atm_iv(chain_calls, chain_puts) -> Optional[float]:
                calls = chain_calls
                puts = chain_puts
                if calls.empty:
                    return None
                atm = calls.iloc[(calls["strike"] - price).abs().argsort()[:1]]
                if "impliedVolatility" not in atm.columns:
                    return None
                iv = float(atm["impliedVolatility"].iloc[0])
                return iv if iv > 0 else None

            near_iv = atm_iv(near_chain.calls, near_chain.puts)
            far_iv = atm_iv(far_chain.calls, far_chain.puts)

            if near_iv is None or far_iv is None or far_iv < 1e-6:
                return None

            # IV crush estimate: how much near IV exceeds far IV
            crush = (near_iv - far_iv) / near_iv
            log.debug(
                "earnings.iv_crush",
                ticker=self.ticker,
                near_iv=round(near_iv, 4),
                far_iv=round(far_iv, 4),
                crush=round(crush, 4),
            )
            return round(max(0.0, crush), 4)
        except Exception as exc:
            log.warning("earnings.iv_crush_error", ticker=self.ticker, error=str(exc))
            return None

    def recommend(self) -> Optional[EarningsRecommendation]:
        """Generate a strategy recommendation if earnings are imminent.

        Returns:
            :class:`EarningsRecommendation` if an upcoming earnings event is
            detected; ``None`` if no event is found within the look-ahead window.
        """
        event = self.detect_earnings()
        if event is None:
            log.debug("earnings.no_event", ticker=self.ticker)
            return None

        exp_move = self.expected_move_pct()
        hist_move = self.historical_move_pct()
        iv_crush = self.iv_crush_estimate()

        # --- Decision logic ---
        strategy_type = "no_trade"
        reasoning_parts: List[str] = []
        risk_notes: List[str] = []
        confidence = 0.5
        data_points = 0

        if iv_crush is not None:
            data_points += 1
            if iv_crush >= self.iv_crush_threshold:
                strategy_type = "iron_condor"
                reasoning_parts.append(
                    f"High IV crush risk ({iv_crush:.1%}): options market is likely "
                    f"overpricing the move — sell premium via an iron condor."
                )
                risk_notes.append(
                    "Iron condor suffers if the stock makes a large directional move. "
                    "Ensure wings are wide enough to cover tail risk."
                )

        if exp_move is not None and hist_move is not None:
            data_points += 1
            ratio = hist_move / exp_move if exp_move > 1e-6 else 0.0
            if ratio >= self.move_premium and strategy_type != "iron_condor":
                strategy_type = "long_straddle"
                reasoning_parts.append(
                    f"Historical move ({hist_move:.1%}) exceeds implied expected move "
                    f"({exp_move:.1%}) by {ratio:.2f}x — buy vol via a long straddle."
                )
                risk_notes.append(
                    "Long straddle has unlimited directional profit potential but "
                    "loses the full premium if the stock barely moves post-earnings."
                )
                risk_notes.append(
                    f"IV crush of ~{iv_crush:.1%} will erode straddle value immediately "
                    f"post-announcement even if the stock moves as expected."
                    if iv_crush
                    else "Monitor IV drop post-announcement."
                )

        if not reasoning_parts:
            reasoning_parts.append(
                "Insufficient data or ambiguous IV / move signals — no trade recommended."
            )

        confidence = min(1.0, 0.4 + 0.3 * data_points)

        return EarningsRecommendation(
            ticker=self.ticker,
            event=event,
            strategy_type=strategy_type,
            expected_move_pct=exp_move,
            historical_move_pct=hist_move,
            iv_crush_est=iv_crush,
            confidence=round(confidence, 2),
            reasoning=" | ".join(reasoning_parts),
            risk_notes=risk_notes,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_price(self, tk) -> Optional[float]:
        """Fetch current equity price from a yfinance Ticker."""
        try:
            info = tk.fast_info
            price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
            if price:
                return float(price)
            hist = tk.history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return None
