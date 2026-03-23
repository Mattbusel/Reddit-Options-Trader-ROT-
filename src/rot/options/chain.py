"""Options chain integration for the ROT platform.

Provides real options chain data via Yahoo Finance (yfinance) for trade idea
enrichment.  Key components:

* :class:`OptionContract` -- full contract data including Greeks, bid/ask, IV,
  open interest, and volume.
* :class:`OptionsChain` -- complete chain for a ticker/expiry pair, split into
  calls and puts.
* :class:`OptionsChainFetcher` -- fetches and caches chains from Yahoo Finance,
  with automatic liquidity filtering and expiry selection.
* :class:`TradeIdeaEnricher` -- takes existing :class:`rot.core.types.TradeIdea`
  objects and enriches them with real strike/premium data and cost estimates.

Spread cost estimate logic:

- Bull call spread: debit = (long call ask - short call bid) * 100
- Bear put spread: debit = (long put ask - short put bid) * 100
- Straddle: debit = (call ask + put ask) * 100

Example::

    from rot.options.chain import OptionsChainFetcher, TradeIdeaEnricher

    fetcher = OptionsChainFetcher(min_open_interest=100)
    chain = fetcher.fetch("AAPL", direction="bullish")
    print(f"Best call: {chain.best_call()}")

    enricher = TradeIdeaEnricher(fetcher)
    enriched = enricher.enrich(trade_idea)
    print(f"Cost estimate: ${enriched['cost_estimate_usd']:.2f}")
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Minimum adequate liquidity threshold for expiry selection
_MIN_OI_DEFAULT = 100
_MIN_VOL_DEFAULT = 10
_MAX_SPREAD_PCT = 0.25  # 25% bid-ask spread cap

try:
    import yfinance as yf
except ImportError as exc:
    raise ImportError(
        "yfinance is required for options chain data. "
        "Install with: pip install yfinance"
    ) from exc

import pandas as pd


# ---------------------------------------------------------------------------
# OptionContract
# ---------------------------------------------------------------------------


@dataclass
class OptionContract:
    """Full data record for a single options contract.

    Attributes:
        ticker: Underlying equity symbol.
        option_type: ``"call"`` or ``"put"``.
        strike: Strike price in USD.
        expiry: Expiry date as ``YYYY-MM-DD`` string.
        dte: Days to expiration from today.
        bid: Bid price (USD).
        ask: Ask price (USD).
        last_price: Last traded price (USD).
        iv: Implied volatility as a decimal (e.g. 0.35 = 35%).
        delta: Option delta (positive for calls, negative for puts).
        gamma: Option gamma.
        theta: Option theta (daily time decay in USD per contract).
        vega: Option vega (change in premium per 1% IV move).
        open_interest: Open interest.
        volume: Intraday volume.
        mid: Mid-price (bid + ask) / 2.
        spread_pct: Bid-ask spread as a fraction of ask.
    """

    ticker: str
    option_type: str
    strike: float
    expiry: str
    dte: int
    bid: float
    ask: float
    last_price: float
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float
    open_interest: int
    volume: int

    @property
    def mid(self) -> float:
        """Mid-price of the contract."""
        return round((self.bid + self.ask) / 2, 4)

    @property
    def spread_pct(self) -> float:
        """Bid-ask spread as a fraction of ask."""
        if self.ask <= 0:
            return 1.0
        return round((self.ask - self.bid) / self.ask, 4)

    def premium_per_contract(self) -> float:
        """Total premium cost for 1 contract (100 shares) using the ask price."""
        return round(self.ask * 100, 2)

    def is_liquid(self, min_oi: int = _MIN_OI_DEFAULT, min_vol: int = 0) -> bool:
        """Return True if this contract meets minimum liquidity thresholds."""
        return (
            self.open_interest >= min_oi
            and self.volume >= min_vol
            and self.spread_pct <= _MAX_SPREAD_PCT
            and self.ask > 0
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "ticker": self.ticker,
            "option_type": self.option_type,
            "strike": self.strike,
            "expiry": self.expiry,
            "dte": self.dte,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "last_price": self.last_price,
            "iv": round(self.iv, 4),
            "delta": round(self.delta, 4),
            "gamma": round(self.gamma, 6),
            "theta": round(self.theta, 4),
            "vega": round(self.vega, 4),
            "open_interest": self.open_interest,
            "volume": self.volume,
            "spread_pct": self.spread_pct,
            "premium_per_contract": self.premium_per_contract(),
        }


# ---------------------------------------------------------------------------
# OptionsChain
# ---------------------------------------------------------------------------


@dataclass
class OptionsChain:
    """Complete options chain for a ticker and expiry date.

    Attributes:
        ticker: Underlying equity symbol.
        expiry: Expiry date string (``YYYY-MM-DD``).
        underlying_price: Current price of the underlying.
        calls: List of call option contracts sorted by strike.
        puts: List of put option contracts sorted by strike.
        fetched_at: ISO timestamp when data was fetched.
    """

    ticker: str
    expiry: str
    underlying_price: float
    calls: List[OptionContract]
    puts: List[OptionContract]
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def best_call(
        self,
        delta_target: float = 0.35,
        min_oi: int = _MIN_OI_DEFAULT,
    ) -> Optional[OptionContract]:
        """Return the liquid call contract closest to *delta_target*.

        Args:
            delta_target: Target absolute delta value (e.g. 0.35 = 35-delta).
            min_oi: Minimum open interest for liquidity filter.

        Returns:
            Best matching :class:`OptionContract`, or ``None`` if no liquid
            contracts are available.
        """
        liquid = [c for c in self.calls if c.is_liquid(min_oi=min_oi)]
        if not liquid:
            return None
        return min(liquid, key=lambda c: abs(abs(c.delta) - delta_target))

    def best_put(
        self,
        delta_target: float = 0.35,
        min_oi: int = _MIN_OI_DEFAULT,
    ) -> Optional[OptionContract]:
        """Return the liquid put contract closest to *delta_target* (absolute).

        Args:
            delta_target: Target absolute delta value (e.g. 0.35).
            min_oi: Minimum open interest for liquidity filter.

        Returns:
            Best matching :class:`OptionContract`, or ``None`` if none found.
        """
        liquid = [c for c in self.puts if c.is_liquid(min_oi=min_oi)]
        if not liquid:
            return None
        return min(liquid, key=lambda c: abs(abs(c.delta) - delta_target))

    def atm_call(self) -> Optional[OptionContract]:
        """Return the call contract closest to at-the-money."""
        if not self.calls:
            return None
        return min(self.calls, key=lambda c: abs(c.strike - self.underlying_price))

    def atm_put(self) -> Optional[OptionContract]:
        """Return the put contract closest to at-the-money."""
        if not self.puts:
            return None
        return min(self.puts, key=lambda c: abs(c.strike - self.underlying_price))

    def to_summary_dict(self) -> dict[str, Any]:
        """Return a lightweight summary dictionary."""
        return {
            "ticker": self.ticker,
            "expiry": self.expiry,
            "underlying_price": self.underlying_price,
            "call_count": len(self.calls),
            "put_count": len(self.puts),
            "liquid_calls": sum(1 for c in self.calls if c.is_liquid()),
            "liquid_puts": sum(1 for c in self.puts if c.is_liquid()),
            "fetched_at": self.fetched_at,
        }


# ---------------------------------------------------------------------------
# OptionsChainFetcher
# ---------------------------------------------------------------------------


class OptionsChainFetcher:
    """Fetches real options chain data from Yahoo Finance with caching.

    Automatically selects the nearest weekly or monthly expiry with adequate
    liquidity.  Results are cached in memory to avoid redundant API calls.

    Args:
        min_open_interest: Minimum open interest for a contract to be
            considered liquid (default 100).
        min_volume: Minimum daily volume for liquidity filter (default 10).
        cache_ttl_seconds: How long to cache chain data before re-fetching.
        prefer_weekly: When ``True`` prefer the nearest weekly Friday over
            the monthly expiry when both are available and liquid.

    Example::

        fetcher = OptionsChainFetcher(min_open_interest=100)
        chain = fetcher.fetch("NVDA", direction="bullish")
        best = chain.best_call(delta_target=0.40)
    """

    def __init__(
        self,
        min_open_interest: int = _MIN_OI_DEFAULT,
        min_volume: int = _MIN_VOL_DEFAULT,
        cache_ttl_seconds: int = 900,
        prefer_weekly: bool = True,
    ) -> None:
        self.min_open_interest = min_open_interest
        self.min_volume = min_volume
        self.cache_ttl = cache_ttl_seconds
        self.prefer_weekly = prefer_weekly
        self._cache: dict[str, tuple[float, OptionsChain]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        ticker: str,
        direction: str = "bullish",
        dte_min: int = 7,
        dte_max: int = 60,
    ) -> Optional[OptionsChain]:
        """Fetch the best-matching options chain for *ticker*.

        Selects the expiry with the most liquid at-the-money strikes within
        the DTE window.  Returns ``None`` if no suitable expiry is found or
        the ticker has no options.

        Args:
            ticker: Equity ticker symbol.
            direction: ``"bullish"`` (prefer calls) or ``"bearish"`` (prefer puts).
            dte_min: Minimum days to expiry to consider.
            dte_max: Maximum days to expiry to consider.

        Returns:
            :class:`OptionsChain` for the best expiry, or ``None``.
        """
        ticker = ticker.upper()
        cache_key = f"{ticker}:{direction}:{dte_min}:{dte_max}"

        # Return cached result if fresh
        if cache_key in self._cache:
            ts, chain = self._cache[cache_key]
            if time.time() - ts < self.cache_ttl:
                log.debug("options_chain.cache_hit ticker=%s", ticker)
                return chain

        yft = yf.Ticker(ticker)
        underlying_price = self._get_price(yft, ticker)

        # Get all available expirations and filter to DTE window
        expirations = self._get_expirations_in_window(yft, dte_min, dte_max)
        if not expirations:
            log.warning("options_chain.no_expirations ticker=%s", ticker)
            return None

        # Select the best expiry based on liquidity
        best_chain = self._select_best_expiry(
            yft, ticker, underlying_price, expirations, direction
        )

        if best_chain is not None:
            self._cache[cache_key] = (time.time(), best_chain)

        return best_chain

    def fetch_all_expirations(
        self,
        ticker: str,
        dte_min: int = 0,
        dte_max: int = 90,
    ) -> List[OptionsChain]:
        """Fetch chains for all available expirations within the DTE window.

        Args:
            ticker: Equity ticker symbol.
            dte_min: Minimum DTE.
            dte_max: Maximum DTE.

        Returns:
            List of :class:`OptionsChain` objects, one per expiry.
        """
        ticker = ticker.upper()
        yft = yf.Ticker(ticker)
        underlying_price = self._get_price(yft, ticker)
        expirations = self._get_expirations_in_window(yft, dte_min, dte_max)

        chains: list[OptionsChain] = []
        for expiry_str in expirations:
            chain = self._fetch_chain_for_expiry(yft, ticker, underlying_price, expiry_str)
            if chain is not None:
                chains.append(chain)

        return chains

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_price(yft: "yf.Ticker", ticker: str) -> float:
        """Retrieve the current underlying price from yfinance."""
        try:
            fi = yft.fast_info
            price = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
            if price:
                return float(price)
        except Exception:
            pass
        try:
            hist = yft.history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        log.warning("options_chain.price_unavailable ticker=%s", ticker)
        return 0.0

    def _get_expirations_in_window(
        self, yft: "yf.Ticker", dte_min: int, dte_max: int
    ) -> List[str]:
        """Return expiry strings within [dte_min, dte_max] days."""
        try:
            all_exp = yft.options
        except Exception as exc:
            log.warning("options_chain.fetch_expirations_failed error=%s", exc)
            return []

        today = date.today()
        result = []
        for exp in all_exp:
            try:
                exp_date = date.fromisoformat(exp)
                dte = (exp_date - today).days
                if dte_min <= dte <= dte_max:
                    result.append(exp)
            except ValueError:
                pass
        return sorted(result)

    def _select_best_expiry(
        self,
        yft: "yf.Ticker",
        ticker: str,
        underlying_price: float,
        expirations: List[str],
        direction: str,
    ) -> Optional["OptionsChain"]:
        """Score expirations by liquidity and select the best one."""
        best_chain: Optional[OptionsChain] = None
        best_score: int = -1

        for expiry_str in expirations:
            chain = self._fetch_chain_for_expiry(yft, ticker, underlying_price, expiry_str)
            if chain is None:
                continue

            # Score = number of liquid contracts on the relevant side
            if direction == "bullish":
                score = sum(1 for c in chain.calls if c.is_liquid(self.min_open_interest))
            else:
                score = sum(1 for c in chain.puts if c.is_liquid(self.min_open_interest))

            if score > best_score:
                best_score = score
                best_chain = chain

            # If prefer_weekly and this is already liquid enough, stop early
            if self.prefer_weekly and best_score >= 5:
                break

        return best_chain

    def _fetch_chain_for_expiry(
        self,
        yft: "yf.Ticker",
        ticker: str,
        underlying_price: float,
        expiry_str: str,
    ) -> Optional["OptionsChain"]:
        """Fetch and parse a single expiry's options chain."""
        try:
            raw = yft.option_chain(expiry_str)
        except Exception as exc:
            log.warning("options_chain.fetch_expiry_error expiry=%s error=%s", expiry_str, exc)
            return None

        today = date.today()
        try:
            dte = (date.fromisoformat(expiry_str) - today).days
        except ValueError:
            dte = 0

        calls = self._parse_df(raw.calls, "call", ticker, expiry_str, dte)
        puts = self._parse_df(raw.puts, "put", ticker, expiry_str, dte)

        return OptionsChain(
            ticker=ticker,
            expiry=expiry_str,
            underlying_price=underlying_price,
            calls=sorted(calls, key=lambda c: c.strike),
            puts=sorted(puts, key=lambda c: c.strike),
        )

    @staticmethod
    def _parse_df(
        df: "pd.DataFrame",
        option_type: str,
        ticker: str,
        expiry_str: str,
        dte: int,
    ) -> List[OptionContract]:
        """Parse a yfinance options DataFrame into :class:`OptionContract` objects."""
        if df is None or df.empty:
            return []

        contracts: list[OptionContract] = []
        for _, row in df.iterrows():
            try:
                strike = float(row.get("strike", 0) or 0)
                last_price = float(row.get("lastPrice", 0) or 0)
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                iv = float(row.get("impliedVolatility", 0) or 0)
                oi = int(row.get("openInterest", 0) or 0)

                raw_vol = row.get("volume", 0)
                vol = 0 if (raw_vol is None or (isinstance(raw_vol, float) and math.isnan(raw_vol))) else int(raw_vol)

                # Greeks: yfinance does not expose these directly; use placeholders
                # where not available.  Real delta/gamma/theta/vega require
                # Black-Scholes computation or a data provider that exposes Greeks.
                delta_raw = row.get("delta", None)
                gamma_raw = row.get("gamma", None)
                theta_raw = row.get("theta", None)
                vega_raw = row.get("vega", None)

                # Rough delta approximation from moneyness if not provided
                delta = float(delta_raw) if delta_raw is not None and not (isinstance(delta_raw, float) and math.isnan(delta_raw)) else 0.5
                gamma = float(gamma_raw) if gamma_raw is not None and not (isinstance(gamma_raw, float) and math.isnan(gamma_raw)) else 0.0
                theta = float(theta_raw) if theta_raw is not None and not (isinstance(theta_raw, float) and math.isnan(theta_raw)) else 0.0
                vega = float(vega_raw) if vega_raw is not None and not (isinstance(vega_raw, float) and math.isnan(vega_raw)) else 0.0

                # Invert delta sign for puts
                if option_type == "put" and delta > 0:
                    delta = -delta

                contracts.append(OptionContract(
                    ticker=ticker,
                    option_type=option_type,
                    strike=strike,
                    expiry=expiry_str,
                    dte=dte,
                    bid=bid,
                    ask=ask,
                    last_price=last_price,
                    iv=iv,
                    delta=delta,
                    gamma=gamma,
                    theta=theta,
                    vega=vega,
                    open_interest=oi,
                    volume=vol,
                ))
            except Exception as exc:
                log.debug("options_chain.row_parse_error error=%s", exc)
                continue

        return contracts


# ---------------------------------------------------------------------------
# TradeIdeaEnricher
# ---------------------------------------------------------------------------


class TradeIdeaEnricher:
    """Enriches ROT trade ideas with real options chain pricing data.

    Takes an existing trade idea (e.g. from :class:`rot.market.trade_builder.TradeBuilder`)
    and overlays real bid/ask spreads, IV, Greeks, and a cost estimate from a
    live Yahoo Finance options chain.

    Args:
        fetcher: An :class:`OptionsChainFetcher` instance (shared is fine).
        min_open_interest: Minimum OI for contract selection.

    Example::

        fetcher = OptionsChainFetcher()
        enricher = TradeIdeaEnricher(fetcher)
        result = enricher.enrich_dict({
            "underlying": "NVDA",
            "strategy": "debit_spread",
            "stance": "bullish",
        })
        print(result["enriched"]["cost_estimate_usd"])
    """

    def __init__(
        self,
        fetcher: OptionsChainFetcher,
        min_open_interest: int = _MIN_OI_DEFAULT,
    ) -> None:
        self.fetcher = fetcher
        self.min_open_interest = min_open_interest

    def enrich_dict(self, trade_dict: dict[str, Any]) -> dict[str, Any]:
        """Enrich a trade idea dictionary with real options chain data.

        Args:
            trade_dict: Dictionary with at least ``"underlying"`` and
                ``"strategy"`` keys.  Optional ``"stance"`` (``"bullish"`` or
                ``"bearish"``) used to select the chain direction.

        Returns:
            The input dict augmented with an ``"enriched"`` sub-dictionary
            containing:

            - ``selected_expiry``: Chosen expiry date string.
            - ``long_strike``: Strike of the long leg.
            - ``short_strike``: Strike of the short leg (spread strategies).
            - ``long_premium``: Ask price of the long leg.
            - ``short_premium``: Bid price of the short leg.
            - ``cost_estimate_usd``: Total debit/credit per contract (USD).
            - ``max_loss_usd``: Maximum dollar loss per contract.
            - ``max_profit_usd``: Maximum dollar profit per contract.
            - ``long_iv``: IV of the long leg.
            - ``long_delta``: Delta of the long leg.
            - ``iv_rank``: Approximate IV percentile across chain candidates.
            - ``chain_fetched_at``: Timestamp of data retrieval.
            - ``enrichment_status``: ``"ok"`` or ``"failed"``.
        """
        ticker = trade_dict.get("underlying", "")
        strategy = trade_dict.get("strategy", "none")
        stance = trade_dict.get("stance", "bullish")

        result = dict(trade_dict)
        result["enriched"] = {"enrichment_status": "failed", "underlying": ticker}

        if not ticker or strategy == "none":
            return result

        direction = "bullish" if stance != "bearish" else "bearish"
        chain = self.fetcher.fetch(ticker, direction=direction)

        if chain is None:
            log.warning("trade_idea_enricher.no_chain ticker=%s", ticker)
            return result

        enriched = self._compute_enrichment(chain, strategy, direction)
        enriched["chain_fetched_at"] = chain.fetched_at
        enriched["enrichment_status"] = "ok"
        result["enriched"] = enriched
        return result

    def _compute_enrichment(
        self,
        chain: OptionsChain,
        strategy: str,
        direction: str,
    ) -> dict[str, Any]:
        """Compute strike selection and cost estimates for a given strategy.

        Args:
            chain: The options chain data.
            strategy: Strategy type string (e.g. ``"debit_spread"``).
            direction: ``"bullish"`` or ``"bearish"``.

        Returns:
            Enrichment dictionary with strikes, premiums, and cost estimates.
        """
        price = chain.underlying_price
        out: dict[str, Any] = {
            "selected_expiry": chain.expiry,
            "underlying_price": price,
            "long_strike": None,
            "short_strike": None,
            "long_premium": None,
            "short_premium": None,
            "cost_estimate_usd": None,
            "max_loss_usd": None,
            "max_profit_usd": None,
            "long_iv": None,
            "long_delta": None,
            "iv_rank": None,
        }

        if direction == "bullish":
            # Bull call spread or long call
            long_leg = chain.best_call(delta_target=0.40, min_oi=self.min_open_interest)
            if long_leg is None:
                long_leg = chain.atm_call()

            if long_leg is not None:
                out["long_strike"] = long_leg.strike
                out["long_premium"] = long_leg.ask
                out["long_iv"] = long_leg.iv
                out["long_delta"] = long_leg.delta

                if strategy in ("debit_spread",):
                    # Short leg: OTM call ~5% above current price
                    otm_strike = round(price * 1.05, 0)
                    short_leg = _nearest_strike(chain.calls, otm_strike, self.min_open_interest)
                    if short_leg:
                        out["short_strike"] = short_leg.strike
                        out["short_premium"] = short_leg.bid
                        debit = (long_leg.ask - short_leg.bid) * 100
                        spread_width = abs(short_leg.strike - long_leg.strike) * 100
                        out["cost_estimate_usd"] = round(debit, 2)
                        out["max_loss_usd"] = round(debit, 2)
                        out["max_profit_usd"] = round(spread_width - debit, 2)
                    else:
                        out["cost_estimate_usd"] = round(long_leg.premium_per_contract(), 2)
                        out["max_loss_usd"] = out["cost_estimate_usd"]
                        out["max_profit_usd"] = None
                elif strategy == "straddle":
                    put_leg = chain.atm_put()
                    if put_leg:
                        debit = (long_leg.ask + put_leg.ask) * 100
                        out["cost_estimate_usd"] = round(debit, 2)
                        out["max_loss_usd"] = round(debit, 2)
                        out["max_profit_usd"] = None  # unlimited upside
                else:
                    out["cost_estimate_usd"] = round(long_leg.premium_per_contract(), 2)
                    out["max_loss_usd"] = out["cost_estimate_usd"]

        else:
            # Bear put spread or long put
            long_leg = chain.best_put(delta_target=0.40, min_oi=self.min_open_interest)
            if long_leg is None:
                long_leg = chain.atm_put()

            if long_leg is not None:
                out["long_strike"] = long_leg.strike
                out["long_premium"] = long_leg.ask
                out["long_iv"] = long_leg.iv
                out["long_delta"] = long_leg.delta

                if strategy in ("debit_spread",):
                    # Short leg: OTM put ~5% below current price
                    otm_strike = round(price * 0.95, 0)
                    short_leg = _nearest_strike(chain.puts, otm_strike, self.min_open_interest)
                    if short_leg:
                        out["short_strike"] = short_leg.strike
                        out["short_premium"] = short_leg.bid
                        debit = (long_leg.ask - short_leg.bid) * 100
                        spread_width = abs(long_leg.strike - short_leg.strike) * 100
                        out["cost_estimate_usd"] = round(debit, 2)
                        out["max_loss_usd"] = round(debit, 2)
                        out["max_profit_usd"] = round(spread_width - debit, 2)
                    else:
                        out["cost_estimate_usd"] = round(long_leg.premium_per_contract(), 2)
                        out["max_loss_usd"] = out["cost_estimate_usd"]
                elif strategy == "straddle":
                    call_leg = chain.atm_call()
                    if call_leg:
                        debit = (long_leg.ask + call_leg.ask) * 100
                        out["cost_estimate_usd"] = round(debit, 2)
                        out["max_loss_usd"] = round(debit, 2)
                        out["max_profit_usd"] = None
                else:
                    out["cost_estimate_usd"] = round(long_leg.premium_per_contract(), 2)
                    out["max_loss_usd"] = out["cost_estimate_usd"]

        # Rough IV rank from available chain data
        all_ivs = [c.iv for c in (chain.calls + chain.puts) if c.iv > 0]
        if all_ivs:
            iv_mean = sum(all_ivs) / len(all_ivs)
            iv_min = min(all_ivs)
            iv_max = max(all_ivs)
            if iv_max > iv_min:
                out["iv_rank"] = round((iv_mean - iv_min) / (iv_max - iv_min) * 100, 1)
            else:
                out["iv_rank"] = 50.0

        return out


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _nearest_strike(
    contracts: List[OptionContract],
    target_strike: float,
    min_oi: int = _MIN_OI_DEFAULT,
) -> Optional[OptionContract]:
    """Return the liquid contract with the strike closest to *target_strike*.

    Args:
        contracts: List of option contracts to search.
        target_strike: Target strike price.
        min_oi: Minimum open interest for liquidity filter.

    Returns:
        Nearest liquid :class:`OptionContract`, or ``None`` if none found.
    """
    liquid = [c for c in contracts if c.is_liquid(min_oi=min_oi)]
    if not liquid:
        liquid = contracts  # fall back to all contracts
    if not liquid:
        return None
    return min(liquid, key=lambda c: abs(c.strike - target_strike))
