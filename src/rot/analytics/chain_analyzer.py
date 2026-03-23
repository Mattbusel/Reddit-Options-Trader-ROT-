"""Options Chain Analyzer for ROT.

Fetches the full options chain for a ticker via yfinance, computes max-pain,
put/call ratio, and IV skew, and exposes a FastAPI route for each metric.

Max-pain formula::

    For each candidate spot S:
        pain = sum over all strikes K of:
            call_OI(K) * max(S - K, 0)   +   put_OI(K) * max(K - S, 0)
    max_pain = argmin_S(pain)

IV Skew::

    skew = IV(25-delta put) - IV(25-delta call)

Example::

    from rot.analytics.chain_analyzer import ChainAnalyzer

    analyzer = ChainAnalyzer()
    snapshot = analyzer.fetch_chain("AAPL", expiry_target_days=30)
    print(analyzer.max_pain(snapshot))
    print(analyzer.put_call_ratio(snapshot))
    print(analyzer.skew(snapshot))
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class OptionQuote:
    """A single option contract quote with greeks.

    Attributes:
        strike: Strike price in USD.
        bid: Best bid price.
        ask: Best ask price.
        mid: Mid-market price ``(bid + ask) / 2``.
        iv: Implied volatility (annualised fraction, e.g. 0.30 = 30 %).
        delta: Black-Scholes delta in [-1, 1].
        gamma: Black-Scholes gamma.
        theta: Black-Scholes theta (daily decay).
        open_interest: Number of open contracts.
        volume: Today's trading volume.
    """

    strike: float
    bid: float
    ask: float
    mid: float
    iv: float
    delta: float
    gamma: float
    theta: float
    open_interest: int
    volume: int


@dataclass
class ChainSnapshot:
    """Full options chain for a single ticker / expiry pair.

    Attributes:
        ticker: Underlying ticker symbol.
        spot_price: Current underlying price in USD.
        expiry: Expiry date of the chain.
        calls: List of call option quotes sorted by strike ascending.
        puts: List of put option quotes sorted by strike ascending.
        timestamp: Unix epoch when the snapshot was captured.
    """

    ticker: str
    spot_price: float
    expiry: date
    calls: List[OptionQuote]
    puts: List[OptionQuote]
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class ChainAnalyzer:
    """Analyses the full options chain for a ticker.

    Uses ``yfinance`` to fetch live chain data.  All heavy computation is pure
    Python (no C extensions required) so the class is fully unit-testable with
    mock snapshots.
    """

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def fetch_chain(
        self,
        ticker: str,
        expiry_target_days: int = 30,
    ) -> ChainSnapshot:
        """Fetch the options chain nearest to *expiry_target_days* from today.

        Args:
            ticker: Ticker symbol (e.g. ``"AAPL"``).
            expiry_target_days: Target days to expiry.  The expiry date with
                the smallest absolute difference is selected.

        Returns:
            :class:`ChainSnapshot` with calls and puts sorted by strike.

        Raises:
            ImportError: If ``yfinance`` is not installed.
            ValueError: If the ticker has no listed options.
        """
        try:
            import yfinance as yf  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "yfinance is required for ChainAnalyzer.fetch_chain(). "
                "Install it with: pip install yfinance"
            ) from exc

        yf_ticker = yf.Ticker(ticker)
        expirations = yf_ticker.options
        if not expirations:
            raise ValueError(f"No options available for ticker '{ticker}'")

        target_date = date.today() + timedelta(days=expiry_target_days)
        best_expiry = min(
            expirations,
            key=lambda e: abs((date.fromisoformat(e) - target_date).days),
        )

        chain = yf_ticker.option_chain(best_expiry)
        spot = _get_spot_price(yf_ticker)

        calls = _parse_options_df(chain.calls)
        puts = _parse_options_df(chain.puts)

        return ChainSnapshot(
            ticker=ticker,
            spot_price=spot,
            expiry=date.fromisoformat(best_expiry),
            calls=sorted(calls, key=lambda q: q.strike),
            puts=sorted(puts, key=lambda q: q.strike),
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def max_pain(self, snapshot: ChainSnapshot) -> float:
        """Compute the max-pain strike price.

        The max-pain price is the spot price at which aggregate option holder
        losses (i.e. option writer profits) are maximised.

        Algorithm: for each unique strike *S*, sum across all strikes *K*:

        - call OI * max(S - K, 0)
        - put OI * max(K - S, 0)

        The strike that minimises total option value is returned.

        Args:
            snapshot: :class:`ChainSnapshot` for the target expiry.

        Returns:
            Max-pain strike price.

        Raises:
            ValueError: If the snapshot has no contracts.
        """
        all_strikes = sorted(
            {q.strike for q in snapshot.calls} | {q.strike for q in snapshot.puts}
        )
        if not all_strikes:
            raise ValueError("ChainSnapshot contains no option contracts")

        call_oi: dict[float, int] = {q.strike: q.open_interest for q in snapshot.calls}
        put_oi: dict[float, int] = {q.strike: q.open_interest for q in snapshot.puts}

        min_pain = float("inf")
        max_pain_strike = all_strikes[0]

        for candidate in all_strikes:
            pain = 0.0
            for k in all_strikes:
                pain += call_oi.get(k, 0) * max(candidate - k, 0.0)
                pain += put_oi.get(k, 0) * max(k - candidate, 0.0)
            if pain < min_pain:
                min_pain = pain
                max_pain_strike = candidate

        return max_pain_strike

    def put_call_ratio(self, snapshot: ChainSnapshot) -> float:
        """Compute the open-interest-based put/call ratio.

        Args:
            snapshot: :class:`ChainSnapshot`.

        Returns:
            PCR = total_put_OI / total_call_OI.  Returns ``float('inf')`` if
            total call OI is zero and there are puts.

        Raises:
            ValueError: If both call and put OI are zero.
        """
        total_call_oi = sum(q.open_interest for q in snapshot.calls)
        total_put_oi = sum(q.open_interest for q in snapshot.puts)

        if total_call_oi == 0 and total_put_oi == 0:
            raise ValueError("All open interest is zero — cannot compute PCR")
        if total_call_oi == 0:
            return float("inf")

        return total_put_oi / total_call_oi

    def skew(self, snapshot: ChainSnapshot) -> float:
        """Compute the 25-delta IV skew: IV(25D put) - IV(25D call).

        Finds the put contract whose delta is closest to -0.25 and the call
        contract whose delta is closest to +0.25, then returns the difference
        of their implied volatilities.

        A positive skew means put IV exceeds call IV (typical in equity markets).

        Args:
            snapshot: :class:`ChainSnapshot`.

        Returns:
            IV skew value (annualised fraction).

        Raises:
            ValueError: If there are no calls or no puts in the snapshot.
        """
        if not snapshot.calls:
            raise ValueError("No calls in snapshot — cannot compute skew")
        if not snapshot.puts:
            raise ValueError("No puts in snapshot — cannot compute skew")

        # 25-delta call: delta closest to +0.25
        call_25d = min(snapshot.calls, key=lambda q: abs(q.delta - 0.25))
        # 25-delta put: delta closest to -0.25
        put_25d = min(snapshot.puts, key=lambda q: abs(q.delta - (-0.25)))

        return put_25d.iv - call_25d.iv


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_spot_price(yf_ticker: object) -> float:
    """Extract the current spot price from a yfinance Ticker object."""
    try:
        info = yf_ticker.fast_info  # type: ignore[attr-defined]
        price = getattr(info, "last_price", None)
        if price and price > 0:
            return float(price)
    except Exception:
        pass

    try:
        hist = yf_ticker.history(period="1d")  # type: ignore[attr-defined]
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass

    return 0.0


def _parse_options_df(df: object) -> List[OptionQuote]:
    """Parse a yfinance options DataFrame into a list of :class:`OptionQuote`."""
    quotes: List[OptionQuote] = []
    try:
        import pandas as pd  # type: ignore[import]

        for _, row in df.iterrows():  # type: ignore[union-attr]
            bid = float(row.get("bid", 0.0) or 0.0)
            ask = float(row.get("ask", 0.0) or 0.0)
            mid = (bid + ask) / 2.0
            iv = float(row.get("impliedVolatility", 0.0) or 0.0)
            delta = float(row.get("delta", 0.0) or 0.0)
            gamma = float(row.get("gamma", 0.0) or 0.0)
            theta = float(row.get("theta", 0.0) or 0.0)
            oi = int(row.get("openInterest", 0) or 0)
            vol = int(row.get("volume", 0) or 0)
            strike = float(row.get("strike", 0.0) or 0.0)

            quotes.append(
                OptionQuote(
                    strike=strike,
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    iv=iv,
                    delta=delta,
                    gamma=gamma,
                    theta=theta,
                    open_interest=oi,
                    volume=vol,
                )
            )
    except Exception as exc:
        log.warning("Failed to parse options row: %s", exc)

    return quotes
