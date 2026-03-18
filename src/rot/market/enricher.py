from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yfinance as yf

from rot.core.types import Event
from rot.core.retry import retry_with_backoff

# Map common text aliases -> Yahoo symbols
ALIAS_MAP: Dict[str, str] = {
    "SPX": "^GSPC",
    "SP500": "^GSPC",
    "SPXW": "^GSPC",
    "TSMC": "TSM",
}

# Tokens that are almost always NOT equities (filter out early)
NON_EQUITY_TOKENS = {
    # Currencies
    "USD", "EUR", "GBP", "JPY", "CNY", "CAD", "AUD", "CHF",
    # Trading jargon & Reddit slang
    "AI", "DD", "YOLO", "WSB", "IMO", "TLDR", "OP", "HODL",
    "LOL", "WTF", "SMH", "TBH", "RN", "NFA", "DYOR", "LFG",
    "ITM", "OTM", "DTE", "FD", "PDT", "DCA", "RSI", "ROI",
    "EOD", "AH", "PRE", "ATH", "ATL", "EPS", "PE", "IV", "OI",
    "IPO", "ETF", "OTC", "SPAC", "NYSE", "AMEX",
    # Action words that look like tickers
    "BUY", "SELL", "HOLD", "DUMP", "LONG", "SHORT",
    "CALLS", "PUTS", "CALL", "PUT",
    "BULL", "BEAR", "MOON", "RIP",
    # Regulatory / macro acronyms
    "CPI", "GDP", "FOMC", "FED", "SEC", "DOJ", "FDA", "IRS",
    "NATO", "BRICS", "PLA", "IRA",
    # Government agencies (not tickers)
    "DOD", "DOE", "HHS", "NIH", "CDC", "EPA", "DHS", "DOT", "HUD",
    "USDA", "FEMA", "OSHA", "NSF", "NASA", "DARPA", "USPTO", "WIPO",
    # People / titles
    "CEO", "CFO", "COO", "CTO", "CPO", "CSO",
    # Sector words
    "TECH", "AUTO", "PHARMA", "BIO",
    # Geographic / political
    "US", "EU", "UK", "USA",
    # Common English words (2-5 uppercase chars that aren't tickers)
    "ALL", "THE", "FOR", "ARE", "HAS", "WAS", "BUT", "NOT",
    "CAN", "MAY", "HIS", "HER", "OUR", "ITS", "WHO", "HOW",
    "NEW", "OLD", "BIG", "TOP", "LOW", "HIGH", "MAX", "MIN",
    "LOT", "WAR", "TAX", "ANY", "GOT", "LET", "RUN", "SET",
    "NOW", "SAY", "USE", "WAY", "DAY", "GET",
    "JUST", "LIKE", "BEEN", "GOOD", "MOST", "SOME",
    "WELL", "MUCH", "EVEN", "ALSO", "BACK", "MADE",
    "OVER", "SUCH", "TAKE", "ONLY", "COME", "EACH",
    "MAKE", "MANY", "THAN", "THEM", "VERY", "WHEN",
    "WHAT", "WITH", "THIS", "THAT", "FROM", "HAVE",
    "WILL", "YOUR", "MORE", "THEY", "BEEN", "SAID",
    "YEAR", "YALL", "GOES", "LOOK", "SAME", "REAL",
    "LONG", "OPEN", "KEEP", "MOVE", "LAST", "NEXT",
    "TOTAL", "EVERY", "STILL", "THINK", "GOING",
    # Month names / time words
    "JAN", "FEB", "MAR", "APR", "APRIL", "JUN", "JUL",
    "AUG", "SEP", "OCT", "NOV", "DEC",
    # Business suffixes
    "LLC", "INC", "LTD", "API",
    # Common false positives from user's logs
    "LLM", "VIX", "EBT", "SME", "IVN", "YOY", "QOQ",
    "CO",
    # Profanity / slang / junk that pass yfinance but aren't real tickers
    "FUCK", "BS", "EOY", "JP", "OF", "GEX", "SIX",
    # Economic indicators / data releases (not tickers)
    "JOLTS", "NFP", "PMI", "PCE", "PPI", "ADP", "ISM",
    "PAYROLLS", "CLAIMS",
    # Business metrics that look like tickers
    "GMV", "MAU", "DAU", "ARR", "MRR", "TAM", "SAM",
    "CAGR", "EBITDA", "EBIT", "NAV", "AUM",
    # Internet / tech abbreviations
    "URL", "CDN", "SDK", "MVP", "CRM", "ERP",
    # Foreign exchanges / non-US tickers
    "LSEG", "GFC",
}


@contextlib.contextmanager
def _quiet_yfinance():
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


class MarketEnricher:
    """Lightweight yfinance market metadata enrichment with caching."""

    MAX_CACHE_SIZE = 500

    def __init__(
        self,
        cache_path: str = "storage/market_cache.json",
        ttl_s: int = 3600,
        options_ttl_s: int = 1800,
        enable_options_chain: bool = False,
        fetch_full_info: bool = False,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.ttl_s = ttl_s
        self.options_ttl_s = options_ttl_s
        self.enable_options_chain = enable_options_chain
        self._fetch_full_info = fetch_full_info
        self._cache: Dict[str, Any] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._cache = {}
        else:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache = {}
        self._prune_expired()

    def _prune_expired(self) -> None:
        """Remove expired entries, then evict oldest if over max size."""
        now = time.time()
        self._cache = {
            k: v for k, v in self._cache.items()
            if isinstance(v, dict) and (now - v.get("ts", 0)) <= self.ttl_s
        }
        if len(self._cache) > self.MAX_CACHE_SIZE:
            sorted_keys = sorted(self._cache, key=lambda k: self._cache[k].get("ts", 0))
            for k in sorted_keys[: len(self._cache) - self.MAX_CACHE_SIZE]:
                del self._cache[k]

    def _save_cache(self) -> None:
        self._prune_expired()
        try:
            self.cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass  # Intentionally suppressed

    def _fresh(self, sym: str) -> Optional[Dict[str, Any]]:
        entry = self._cache.get(sym)
        if not isinstance(entry, dict):
            return None
        ts = entry.get("ts")
        if not isinstance(ts, (int, float)):
            return None
        age = time.time() - ts
        if age <= self.ttl_s:
            data = entry.get("data")
            if isinstance(data, dict):
                # If options data is stale (past options_ttl_s), strip it
                # so it gets re-fetched while reusing other cached data
                if age > self.options_ttl_s and self.enable_options_chain:
                    return None  # Force full re-fetch for simplicity
                return data
        return None

    @retry_with_backoff(
        max_attempts=3,
        base_delay=1.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError, Exception),
    )
    def _fetch(self, sym: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {"symbol": sym}

        with _quiet_yfinance():
            t = yf.Ticker(sym)

            try:
                hist = t.history(period="5d", interval="1d")
                if hist is not None and len(hist) > 0:
                    close = float(hist["Close"].iloc[-1])
                    out["last_close"] = close
                    if len(hist) >= 2:
                        prev = float(hist["Close"].iloc[-2])
                        out["pct_1d"] = (close / prev - 1.0) if prev else None
            except Exception as e:
                out["price_error"] = str(e)

            try:
                info = getattr(t, "fast_info", None)
                if isinstance(info, dict):
                    out["currency"] = info.get("currency")
                    out["last_price"] = info.get("lastPrice") or info.get("last_price")
                    out["market_cap"] = info.get("marketCap") or info.get("market_cap")
            except Exception:
                pass  # Intentionally suppressed

            # Extended market data: sector, industry, volume, etc.
            # NOTE: t.info is very expensive (full company financials download).
            # Only fetch it when explicitly requested; otherwise skip to save
            # ~100-200KB of network per symbol and significant memory.
            if self._fetch_full_info:
                try:
                    full_info = t.info
                    if isinstance(full_info, dict):
                        out["sector"] = full_info.get("sector", "")
                        out["industry"] = full_info.get("industry", "")
                        out["volume"] = full_info.get("volume")
                        out["avg_volume"] = full_info.get("averageVolume")
                        out["fifty_two_week_high"] = full_info.get("fiftyTwoWeekHigh")
                        out["fifty_two_week_low"] = full_info.get("fiftyTwoWeekLow")
                        out["pe_ratio"] = full_info.get("trailingPE")
                        out["beta"] = full_info.get("beta")
                except Exception:
                    pass  # Intentionally suppressed

            # Options chain data: IV, open interest, put/call ratio
            if self.enable_options_chain:
                options_data = self._fetch_options_metrics(t, out.get("last_close"))
                out.update(options_data)

        return out

    @retry_with_backoff(
        max_attempts=3,
        base_delay=1.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError, Exception),
    )
    def _fetch_options_metrics(self, ticker: Any, current_price: Optional[float]) -> Dict[str, Any]:
        """Fetch implied volatility and open interest from nearest options chain."""
        metrics: Dict[str, Any] = {}
        if not current_price or current_price <= 0:
            return metrics
        try:
            expiries = ticker.options
            if not expiries:
                return metrics

            # Use nearest expiration
            nearest_expiry = expiries[0]
            chain = ticker.option_chain(nearest_expiry)
            calls, puts = chain.calls, chain.puts

            if calls is None or puts is None or calls.empty or puts.empty:
                return metrics

            metrics["options_expiry"] = nearest_expiry

            # ATM IV: find strikes closest to current price, average call + put IV
            call_strikes = calls["strike"].values
            put_strikes = puts["strike"].values

            # Find nearest ATM call
            if len(call_strikes) > 0 and "impliedVolatility" in calls.columns:
                atm_idx = abs(call_strikes - current_price).argmin()
                call_iv = calls.iloc[atm_idx]["impliedVolatility"]
                if call_iv and call_iv > 0:
                    metrics["atm_call_iv"] = float(call_iv)

            # Find nearest ATM put
            if len(put_strikes) > 0 and "impliedVolatility" in puts.columns:
                atm_idx = abs(put_strikes - current_price).argmin()
                put_iv = puts.iloc[atm_idx]["impliedVolatility"]
                if put_iv and put_iv > 0:
                    metrics["atm_put_iv"] = float(put_iv)

            # Combined ATM IV
            c_iv = metrics.get("atm_call_iv")
            p_iv = metrics.get("atm_put_iv")
            if c_iv and p_iv:
                metrics["atm_iv"] = (c_iv + p_iv) / 2
            elif c_iv:
                metrics["atm_iv"] = c_iv
            elif p_iv:
                metrics["atm_iv"] = p_iv

            # Open interest totals
            if "openInterest" in calls.columns:
                call_oi = int(calls["openInterest"].fillna(0).sum())
                metrics["call_oi"] = call_oi
            if "openInterest" in puts.columns:
                put_oi = int(puts["openInterest"].fillna(0).sum())
                metrics["put_oi"] = put_oi

            # Put/call OI ratio
            if metrics.get("call_oi") and metrics["call_oi"] > 0:
                metrics["pc_ratio"] = round(metrics.get("put_oi", 0) / metrics["call_oi"], 2)

            # ATM OI cluster: aggregate OI within 5% of current price
            lower = current_price * 0.95
            upper = current_price * 1.05
            if "openInterest" in calls.columns:
                atm_calls = calls[(calls["strike"] >= lower) & (calls["strike"] <= upper)]
                metrics["atm_call_oi"] = int(atm_calls["openInterest"].fillna(0).sum())
            if "openInterest" in puts.columns:
                atm_puts = puts[(puts["strike"] >= lower) & (puts["strike"] <= upper)]
                metrics["atm_put_oi"] = int(atm_puts["openInterest"].fillna(0).sum())

        except Exception:
            pass  # Intentionally suppressed

        return metrics

    def get_symbol(self, raw: str) -> Optional[str]:
        """Normalize a raw ticker string and return it, or None if it should be excluded."""
        s = raw.upper().strip()
        s = ALIAS_MAP.get(s, s)
        if s in NON_EQUITY_TOKENS:
            return None
        if len(s) <= 1:
            return None
        return s

    def enrich_symbols(self, symbols: list[str]) -> Dict[str, Any]:
        """Fetch and cache market data for a list of raw ticker symbols."""
        market: Dict[str, Any] = {}
        now = int(time.time())

        for raw in symbols:
            sym = self.get_symbol(raw)
            if not sym:
                continue

            cached = self._fresh(sym)
            if cached is not None:
                market[sym] = cached
                continue

            data = self._fetch(sym)
            market[sym] = data
            self._cache[sym] = {"ts": now, "data": data}

        self._save_cache()
        return market

    def enrich_event(self, event: Event) -> Event:
        """Return a new Event with market data added to meta."""
        entities = list(event.entities) if event.entities else []
        market_data = self.enrich_symbols(entities)

        new_meta = dict(event.meta)
        new_meta["market"] = market_data

        return dataclasses.replace(event, meta=new_meta)
