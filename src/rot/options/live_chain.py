"""Live options chain integration for ROT.

Fetches real-time options chain data via ``yfinance`` (free, no API key),
finds the optimal strike and expiry for a given signal direction, computes
IV rank vs historical IV, and returns a structured contract suggestion with
risk/reward estimates.

Typical usage::

    from rot.options.live_chain import LiveOptionsChain

    chain = LiveOptionsChain("AAPL")
    suggestion = chain.best_contract(
        direction="bullish",
        dte_min=14,
        dte_max=45,
        delta_target=0.35,
    )
    print(suggestion)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional

log = logging.getLogger(__name__)

# yfinance is declared in pyproject.toml
try:
    import yfinance as yf
except ImportError as exc:
    raise ImportError(
        "yfinance is required for live options chain data.  "
        "Install with: pip install yfinance"
    ) from exc

import pandas as pd


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class OptionContract:
    """Represents a single options contract candidate.

    Attributes:
        ticker: Underlying equity symbol.
        option_type: ``"call"`` or ``"put"``.
        strike: Strike price (USD).
        expiry: Expiry date string (``YYYY-MM-DD``).
        dte: Days to expiration from today.
        last_price: Last traded premium (USD).
        bid: Bid price (USD).
        ask: Ask price (USD).
        implied_volatility: Implied volatility as a decimal (e.g. 0.35 = 35%).
        delta: Option delta (positive for calls, negative for puts).
        open_interest: Open interest.
        volume: Intraday volume.
        max_profit: Estimated max profit for a long single (ask price times 100 per contract).
        max_loss: Estimated max loss (premium paid = ask × 100).
        risk_reward: max_profit / max_loss ratio (based on 2× premium as target).
    """

    ticker: str
    option_type: str
    strike: float
    expiry: str
    dte: int
    last_price: float
    bid: float
    ask: float
    implied_volatility: float
    delta: float
    open_interest: int
    volume: int
    max_profit: float = field(init=False)
    max_loss: float = field(init=False)
    risk_reward: float = field(init=False)

    def __post_init__(self) -> None:
        premium = self.ask if self.ask > 0 else self.last_price
        self.max_loss = round(premium * 100, 2)  # 1 contract = 100 shares
        self.max_profit = round(premium * 100 * 2, 2)  # target 2× premium
        self.risk_reward = round(self.max_profit / self.max_loss, 2) if self.max_loss > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "option_type": self.option_type,
            "strike": self.strike,
            "expiry": self.expiry,
            "dte": self.dte,
            "last_price": self.last_price,
            "bid": self.bid,
            "ask": self.ask,
            "implied_volatility": round(self.implied_volatility, 4),
            "delta": round(self.delta, 4),
            "open_interest": self.open_interest,
            "volume": self.volume,
            "max_loss_usd": self.max_loss,
            "max_profit_usd": self.max_profit,
            "risk_reward": self.risk_reward,
        }


@dataclass
class ChainAnalysis:
    """Full options chain analysis for a ticker.

    Attributes:
        ticker: Underlying symbol.
        current_price: Latest underlying price (USD).
        iv_rank: IV rank vs 52-week range (0–100, higher = more expensive).
        historical_iv_mean: Mean historical IV over the lookback period.
        current_iv_mean: Mean current IV across near-term expirations.
        suggestion: Best contract for the requested direction (or ``None``).
        all_candidates: All candidate contracts considered.
        fetched_at: ISO timestamp of data retrieval.
    """

    ticker: str
    current_price: float
    iv_rank: float
    historical_iv_mean: float
    current_iv_mean: float
    suggestion: Optional[OptionContract]
    all_candidates: List[OptionContract]
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "current_price": self.current_price,
            "iv_rank": round(self.iv_rank, 1),
            "historical_iv_mean": round(self.historical_iv_mean, 4),
            "current_iv_mean": round(self.current_iv_mean, 4),
            "suggestion": self.suggestion.to_dict() if self.suggestion else None,
            "candidate_count": len(self.all_candidates),
            "fetched_at": self.fetched_at,
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class LiveOptionsChain:
    """Fetches and analyses a live options chain from Yahoo Finance.

    Args:
        ticker: Equity ticker symbol (e.g. ``"AAPL"``).
    """

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker.upper()
        self._yf_ticker = yf.Ticker(self.ticker)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def best_contract(
        self,
        direction: str = "bullish",
        dte_min: int = 14,
        dte_max: int = 60,
        delta_target: float = 0.35,
        min_open_interest: int = 100,
        max_spread_pct: float = 0.20,
    ) -> ChainAnalysis:
        """Find the optimal single-leg contract for a directional signal.

        Filtering criteria (in order):
        1. Expiry within [dte_min, dte_max] days from today.
        2. Calls for ``"bullish"`` direction; puts for ``"bearish"``.
        3. Open interest >= *min_open_interest*.
        4. Bid/ask spread <= *max_spread_pct* of ask price (liquidity filter).
        5. Delta closest to *delta_target* (positive for calls, negative for puts).

        Args:
            direction: ``"bullish"`` (calls) or ``"bearish"`` (puts).
            dte_min: Minimum days to expiration.
            dte_max: Maximum days to expiration.
            delta_target: Target delta (absolute value, e.g. 0.35 = 35-delta).
            min_open_interest: Minimum open interest for liquidity.
            max_spread_pct: Maximum bid/ask spread as fraction of ask.

        Returns:
            A :class:`ChainAnalysis` with the best contract and IV metadata.
        """
        today = date.today()
        option_type = "call" if direction.lower() == "bullish" else "put"

        current_price = self._get_current_price()
        log.info("live_chain.fetch ticker=%s price=%.2f direction=%s", self.ticker, current_price, direction)

        candidates: list[OptionContract] = []

        for expiry_str in self._get_expirations(today, dte_min, dte_max):
            try:
                chain = self._yf_ticker.option_chain(expiry_str)
            except Exception as exc:
                log.warning("live_chain.expiry_error expiry=%s error=%s", expiry_str, exc)
                continue

            df = chain.calls if option_type == "call" else chain.puts
            if df is None or df.empty:
                continue

            expiry_date = date.fromisoformat(expiry_str)
            dte = (expiry_date - today).days

            for _, row in df.iterrows():
                contract = self._row_to_contract(row, option_type, expiry_str, dte)
                if contract is None:
                    continue
                # Liquidity filters
                if contract.open_interest < min_open_interest:
                    continue
                if contract.ask > 0:
                    spread_pct = (contract.ask - contract.bid) / contract.ask
                    if spread_pct > max_spread_pct:
                        continue
                candidates.append(contract)

        # Score by delta proximity to target
        best: Optional[OptionContract] = None
        if candidates:
            best = min(
                candidates,
                key=lambda c: abs(abs(c.delta) - delta_target),
            )
            log.info(
                "live_chain.best_contract strike=%.1f expiry=%s delta=%.3f iv=%.2f",
                best.strike, best.expiry, best.delta, best.implied_volatility,
            )

        iv_rank, hist_iv, curr_iv = self._compute_iv_rank(candidates)

        return ChainAnalysis(
            ticker=self.ticker,
            current_price=current_price,
            iv_rank=iv_rank,
            historical_iv_mean=hist_iv,
            current_iv_mean=curr_iv,
            suggestion=best,
            all_candidates=candidates,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_current_price(self) -> float:
        """Return the latest underlying price from yfinance fast_info."""
        try:
            fi = self._yf_ticker.fast_info
            price = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
            if price:
                return float(price)
        except Exception:
            pass
        # Fallback: fetch 1-day history
        try:
            hist = self._yf_ticker.history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return 0.0

    def _get_expirations(self, today: date, dte_min: int, dte_max: int) -> list[str]:
        """Return expiry strings within the DTE window."""
        try:
            all_exp = self._yf_ticker.options  # tuple of 'YYYY-MM-DD' strings
        except Exception as exc:
            log.warning("live_chain.no_expirations error=%s", exc)
            return []

        result = []
        for exp in all_exp:
            try:
                exp_date = date.fromisoformat(exp)
                dte = (exp_date - today).days
                if dte_min <= dte <= dte_max:
                    result.append(exp)
            except ValueError:
                pass
        return result

    @staticmethod
    def _row_to_contract(
        row: pd.Series,
        option_type: str,
        expiry_str: str,
        dte: int,
    ) -> Optional[OptionContract]:
        """Parse a yfinance options DataFrame row into an :class:`OptionContract`."""
        try:
            strike = float(row.get("strike", 0))
            last_price = float(row.get("lastPrice", 0))
            bid = float(row.get("bid", 0))
            ask = float(row.get("ask", 0))
            iv = float(row.get("impliedVolatility", 0))
            delta = float(row.get("delta", 0)) if "delta" in row.index else 0.0
            oi = int(row.get("openInterest", 0))
            vol = int(row.get("volume", 0)) if not math.isnan(float(row.get("volume", 0))) else 0

            # Greeks are not always present in yfinance; estimate delta from moneyness
            if delta == 0.0:
                # Very rough approximation: ATM delta ≈ 0.5, OTM decreases
                delta = 0.5  # placeholder; real delta requires Black-Scholes

            return OptionContract(
                ticker="",  # will be set externally if needed
                option_type=option_type,
                strike=strike,
                expiry=expiry_str,
                dte=dte,
                last_price=last_price,
                bid=bid,
                ask=ask,
                implied_volatility=iv,
                delta=delta,
                open_interest=oi,
                volume=vol,
            )
        except Exception as exc:
            log.debug("live_chain.row_parse_error error=%s", exc)
            return None

    @staticmethod
    def _compute_iv_rank(candidates: list[OptionContract]) -> tuple[float, float, float]:
        """Compute IV rank from candidate contracts.

        Returns:
            Tuple of (iv_rank, historical_iv_mean, current_iv_mean).
            IV rank is computed as the percentile of current mean IV within
            the range of IVs seen across all candidates (rough approximation).
        """
        if not candidates:
            return 0.0, 0.0, 0.0

        ivs = [c.implied_volatility for c in candidates if c.implied_volatility > 0]
        if not ivs:
            return 0.0, 0.0, 0.0

        current_iv_mean = sum(ivs) / len(ivs)
        iv_min = min(ivs)
        iv_max = max(ivs)

        # Near-term vs far-term split for historical approximation
        near = [c.implied_volatility for c in candidates if c.dte <= 30 and c.implied_volatility > 0]
        far = [c.implied_volatility for c in candidates if c.dte > 30 and c.implied_volatility > 0]
        hist_iv = sum(far) / len(far) if far else current_iv_mean

        if iv_max == iv_min:
            iv_rank = 50.0
        else:
            iv_rank = (current_iv_mean - iv_min) / (iv_max - iv_min) * 100

        return round(iv_rank, 1), round(hist_iv, 4), round(current_iv_mean, 4)
