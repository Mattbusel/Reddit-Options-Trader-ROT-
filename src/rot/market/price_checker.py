"""Background price-checking job for signal performance tracking.

Periodically checks current prices for signals and updates the
signal_performance table with 1h, 4h, 1d, 1w price snapshots and
computed gain/loss percentages.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import yfinance as yf

from rot.market.enricher import _quiet_yfinance

log = logging.getLogger(__name__)


class PriceChecker:
    """Fetches current prices and updates signal_performance records."""

    def __init__(self, db, batch_size: int = 50) -> None:
        self.db = db
        self.batch_size = batch_size

    def _get_current_price(self, ticker: str) -> Optional[float]:
        """Fetch the current/last price for a ticker via yfinance."""
        try:
            with _quiet_yfinance():
                t = yf.Ticker(ticker)
                hist = t.history(period="1d", interval="1d")
                if hist is not None and len(hist) > 0:
                    return float(hist["Close"].iloc[-1])
        except Exception as e:
            log.debug("Price fetch failed for %s: %s", ticker, e)
        return None

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

        Returns the number of records updated.
        """
        pending = await self.db.get_unchecked_performances(limit=self.batch_size)
        if not pending:
            return 0

        updated = 0
        now = time.time()

        for perf in pending:
            ticker = perf.get("ticker", "")
            signal_created = perf.get("created_at", 0) or perf.get("checked_at", 0)
            price_at_signal = perf.get("price_at_signal")
            perf_id = perf.get("id")

            if not ticker or not price_at_signal or not perf_id:
                continue

            age_s = now - signal_created
            updates: Dict[str, Any] = {}

            # Determine which time windows need checking
            needs_1h = perf.get("price_1h") is None and age_s >= 3600
            needs_4h = perf.get("price_4h") is None and age_s >= 14400
            needs_1d = perf.get("price_1d") is None and age_s >= 86400
            needs_1w = perf.get("price_1w") is None and age_s >= 604800

            if not (needs_1h or needs_4h or needs_1d or needs_1w):
                continue

            current_price = self._get_current_price(ticker)
            if current_price is None:
                continue

            if needs_1h and perf.get("price_1h") is None:
                updates["price_1h"] = current_price
            if needs_4h and perf.get("price_4h") is None:
                updates["price_4h"] = current_price
            if needs_1d and perf.get("price_1d") is None:
                updates["price_1d"] = current_price
            if needs_1w and perf.get("price_1w") is None:
                updates["price_1w"] = current_price

            # Compute max gain/loss across all tracked prices
            tracked_prices = []
            for key in ("price_1h", "price_4h", "price_1d", "price_1w"):
                p = updates.get(key) or perf.get(key)
                if p is not None:
                    tracked_prices.append(p)

            if tracked_prices and price_at_signal > 0:
                pct_changes = [(p / price_at_signal - 1.0) * 100 for p in tracked_prices]
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
            log.info("Price check: updated %d/%d records", updated, len(pending))

        return updated
