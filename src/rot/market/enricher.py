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
}


@contextlib.contextmanager
def _quiet_yfinance():
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


class MarketEnricher:
    """Lightweight yfinance market metadata enrichment with caching."""

    def __init__(self, cache_path: str = "storage/market_cache.json", ttl_s: int = 3600) -> None:
        self.cache_path = Path(cache_path)
        self.ttl_s = ttl_s
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

    def _save_cache(self) -> None:
        try:
            self.cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _fresh(self, sym: str) -> Optional[Dict[str, Any]]:
        entry = self._cache.get(sym)
        if not isinstance(entry, dict):
            return None
        ts = entry.get("ts")
        if not isinstance(ts, (int, float)):
            return None
        if (time.time() - ts) <= self.ttl_s:
            data = entry.get("data")
            if isinstance(data, dict):
                return data
        return None

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
                pass

        return out

    def get_symbol(self, raw: str) -> Optional[str]:
        s = raw.upper().strip()
        s = ALIAS_MAP.get(s, s)
        if s in NON_EQUITY_TOKENS:
            return None
        if len(s) <= 1:
            return None
        return s

    def enrich_symbols(self, symbols: list[str]) -> Dict[str, Any]:
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
