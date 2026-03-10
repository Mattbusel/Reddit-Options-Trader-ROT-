"""Background price-checking job for signal performance tracking.

Periodically checks current prices for signals and updates the
signal_performance table with 1h, 4h, 1d, 1w price snapshots and
computed gain/loss percentages.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

from rot.market.enricher import _quiet_yfinance

log = logging.getLogger(__name__)


class PriceChecker:
    """Fetches current prices and updates signal_performance records."""

    def __init__(self, db, batch_size: int = 50) -> None:
        self.db = db
        self.batch_size = batch_size

    def _get_current_price(self, ticker: str, retries: int = 3) -> Optional[float]:
        """Fetch the current/last price for a ticker via yfinance with retry."""
        for attempt in range(retries):
            try:
                with _quiet_yfinance():
                    t = yf.Ticker(ticker)
                    hist = t.history(period="1d", interval="1m")
                    if hist is not None and len(hist) > 0:
                        return float(hist["Close"].iloc[-1])
            except Exception as e:
                if attempt < retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    log.debug("Price fetch retry %d/%d for %s in %ds: %s",
                              attempt + 1, retries, ticker, wait, e)
                    time.sleep(wait)
                else:
                    log.warning("Price fetch failed for %s after %d attempts: %s",
                                ticker, retries, e)
        return None

    def _get_prices_batch(self, tickers: List[str]) -> Dict[str, Optional[float]]:
        """Fetch current prices for multiple tickers in one yfinance call."""
        if not tickers:
            return {}

        results: Dict[str, Optional[float]] = {}

        try:
            with _quiet_yfinance():
                data = yf.download(
                    tickers, period="1d", interval="1m",
                    group_by="ticker", progress=False, threads=True,
                )
                for t in tickers:
                    try:
                        if len(tickers) == 1:
                            close = data["Close"].iloc[-1]
                        else:
                            close = data[t]["Close"].iloc[-1]
                        results[t] = float(close) if not pd.isna(close) else None
                    except (KeyError, IndexError):
                        results[t] = None
            log.info("Batch price fetch: got %d/%d prices",
                     sum(1 for v in results.values() if v is not None), len(tickers))
        except Exception as e:
            log.warning("Batch price fetch failed, falling back to individual: %s", e)
            # Fall back to individual fetches
            for t in tickers:
                results[t] = self._get_current_price(t)

        return results

    async def record_initial_price(self, signal_id: str, ticker: str) -> None:
        """Record the initial price when a signal is first created."""
        if not ticker or ticker == "UNKNOWN":
            return

        price = self._get_current_price(ticker)
        if price is None:
            log.debug("Could not get initial price for %s", ticker)
            return

        try:
            await self.db.insert_signal_performance(signal_id, ticker, price)
            log.info("Recorded initial price for %s: $%.2f", ticker, price)
        except Exception as e:
            log.error("Failed to record initial price for %s: %s", ticker, e)

    async def check_pending_prices(self) -> int:
        """Check and update prices for signals that need tracking.

        Uses batch fetching to minimize API calls. Returns the number
        of records updated.
        """
        pending = await self.db.get_unchecked_performances(limit=self.batch_size)
        if not pending:
            return 0

        now = time.time()

        # First pass: identify which tickers actually need price checks
        tickers_needed: set[str] = set()
        actionable: list[dict] = []

        for perf in pending:
            ticker = perf.get("ticker", "")
            signal_created = perf.get("created_at", 0) or perf.get("checked_at", 0)
            price_at_signal = perf.get("price_at_signal")
            perf_id = perf.get("id")

            if not ticker or not price_at_signal or not perf_id:
                continue

            age_s = now - signal_created
            needs_1h = perf.get("price_1h") is None and age_s >= 3600
            needs_4h = perf.get("price_4h") is None and age_s >= 14400
            needs_1d = perf.get("price_1d") is None and age_s >= 86400
            needs_1w = perf.get("price_1w") is None and age_s >= 604800

            if needs_1h or needs_4h or needs_1d or needs_1w:
                tickers_needed.add(ticker)
                actionable.append(perf)

        if not tickers_needed:
            return 0

        # Batch fetch all needed prices in one API call
        prices = self._get_prices_batch(list(tickers_needed))

        # Second pass: apply prices to records
        updated = 0
        for perf in actionable:
            ticker = perf.get("ticker", "")
            signal_created = perf.get("created_at", 0) or perf.get("checked_at", 0)
            price_at_signal = perf.get("price_at_signal")
            perf_id = perf.get("id")

            current_price = prices.get(ticker)
            if current_price is None:
                continue

            age_s = now - signal_created
            updates: Dict[str, Any] = {}

            if perf.get("price_1h") is None and age_s >= 3600:
                updates["price_1h"] = current_price
            if perf.get("price_4h") is None and age_s >= 14400:
                updates["price_4h"] = current_price
            if perf.get("price_1d") is None and age_s >= 86400:
                updates["price_1d"] = current_price
            if perf.get("price_1w") is None and age_s >= 604800:
                updates["price_1w"] = current_price

            # Compute stance-aware gain/loss across all tracked prices
            # For bullish signals: price UP = gain. For bearish: price DOWN = gain.
            tracked_prices = []
            for key in ("price_1h", "price_4h", "price_1d", "price_1w"):
                p = updates.get(key) or perf.get(key)
                if p is not None:
                    tracked_prices.append(p)

            if tracked_prices and price_at_signal > 0:
                stance = perf.get("signal_stance", "bullish")
                raw_pct_changes = [(p / price_at_signal - 1.0) * 100 for p in tracked_prices]

                if stance == "bearish":
                    # For bearish signals, invert: price drop = positive gain
                    pct_changes = [-pct for pct in raw_pct_changes]
                else:
                    # For bullish/mixed/unknown: price rise = positive gain
                    pct_changes = raw_pct_changes

                updates["max_gain_pct"] = max(pct_changes)
                updates["max_loss_pct"] = min(pct_changes)

            if updates:
                updates["checked_at"] = now
                try:
                    await self.db.update_performance_prices(perf_id, updates)
                    updated += 1
                except Exception as e:
                    log.error("Failed to update performance for %s: %s", ticker, e)

        if updated > 0:
            log.info("Price check: updated %d/%d records (%d unique tickers)",
                     updated, len(pending), len(tickers_needed))

        return updated
