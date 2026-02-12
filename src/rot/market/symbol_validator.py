from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

import yfinance as yf

from rot.market.enricher import ALIAS_MAP, NON_EQUITY_TOKENS, _quiet_yfinance


@dataclass
class SymbolValidator:
    cache_path: str = "storage/symbol_valid_cache.json"
    ttl_s: int = 7 * 24 * 3600  # 7d
    max_cache_size: int = 5000

    def __post_init__(self) -> None:
        self._cache: Dict[str, Dict[str, object]] = {}
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception:
                self._cache = {}
        self._prune_expired()

    def _prune_expired(self) -> None:
        """Remove entries older than ttl_s, then cap at max_cache_size."""
        import time as _time
        now = _time.time()
        self._cache = {
            k: v for k, v in self._cache.items()
            if isinstance(v, dict) and (now - v.get("ts", 0)) <= self.ttl_s
        }
        if len(self._cache) > self.max_cache_size:
            sorted_keys = sorted(self._cache, key=lambda k: self._cache[k].get("ts", 0))
            for k in sorted_keys[: len(self._cache) - self.max_cache_size]:
                del self._cache[k]

    def _save(self) -> None:
        self._prune_expired()
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f)

    def normalize(self, sym: str) -> str:
        s = sym.strip().upper()
        if s.startswith("$"):
            s = s[1:]
        return ALIAS_MAP.get(s, s)

    def is_valid(self, sym: str) -> bool:
        s = self.normalize(sym)

        # hard filters
        if not s or len(s) < 2 or len(s) > 6:
            return False
        if s in NON_EQUITY_TOKENS:
            return False

        # cache hit (respect TTL)
        import time as _time
        entry = self._cache.get(s)
        if entry and isinstance(entry, dict) and "ok" in entry:
            if (_time.time() - entry.get("ts", 0)) <= self.ttl_s:
                return bool(entry["ok"])

        ok = False
        try:
            with _quiet_yfinance():
                t = yf.Ticker(s)
                # Fast existence checks that don't scream too much:
                fi = getattr(t, "fast_info", None)
                if fi:
                    # last_price exists for many real tickers
                    lp = fi.get("lastPrice") or fi.get("last_price")
                    ok = lp is not None
                if not ok:
                    # fallback: 1d history should exist for real symbols
                    hist = t.history(period="1d")
                    ok = (hist is not None) and (len(hist) > 0)
        except Exception:
            ok = False

        self._cache[s] = {"ok": ok, "ts": _time.time()}
        self._save()
        return ok
