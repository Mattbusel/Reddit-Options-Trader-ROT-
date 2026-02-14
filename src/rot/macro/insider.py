"""Insider & Congressional Trade Feed — SEC Form 4 + STOCK Act parsing."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

import httpx

from rot.macro.types import InsiderTrade

log = logging.getLogger(__name__)

# SEC EDGAR Form 4 RSS feed
_SEC_FORM4_RSS = "https://efts.sec.gov/LATEST/search-index?q=%22form+4%22&dateRange=custom&startdt={start}&enddt={end}&forms=4"
_SEC_FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index?q={ticker}+%22form+4%22&forms=4&dateRange=custom&startdt={start}&enddt={end}"

# Congress STOCK Act — periodic disclosure RSS (simplified)
_CONGRESS_FEEDS = [
    "https://efts.sec.gov/LATEST/search-index?q=%22periodic+transaction+report%22&forms=&dateRange=custom",
]


class InsiderFeed:
    """Tracks insider and congressional trades from SEC filings."""

    def __init__(self, db: Any, config: Any | None = None) -> None:
        self._db = db
        self._cfg = config
        self._user_agent = ""
        if config:
            self._user_agent = getattr(config, "sec_edgar_user_agent", "")

    # ── Query methods ────────────────────────────────────────────────

    async def get_recent(
        self,
        days: int = 30,
        trade_type: str | None = None,
        source: str | None = None,
    ) -> List[InsiderTrade]:
        """Return recent insider trades."""
        now = time.time()
        start = now - days * 86400
        rows = await self._db.query_insider_trades(
            start_ts=start, end_ts=now, trade_type=trade_type,
            source=source, order="desc",
        )
        return [self._row_to_trade(r) for r in rows]

    async def get_by_ticker(
        self, ticker: str, limit: int = 50
    ) -> List[InsiderTrade]:
        """Return insider trades for a specific ticker."""
        rows = await self._db.query_insider_trades(
            ticker=ticker, limit=limit, order="desc"
        )
        return [self._row_to_trade(r) for r in rows]

    async def get_notable(
        self, min_value: int = 100000, days: int = 30
    ) -> List[InsiderTrade]:
        """Return large insider trades above min_value."""
        now = time.time()
        start = now - days * 86400
        rows = await self._db.query_insider_trades(
            start_ts=start, end_ts=now, min_value=min_value, order="desc"
        )
        return [self._row_to_trade(r) for r in rows]

    async def get_buys_only(self, days: int = 30) -> List[InsiderTrade]:
        """Return only insider buys (strongest signal)."""
        return await self.get_recent(days=days, trade_type="buy")

    # ── Cross-reference with ROT signals ─────────────────────────────

    async def cross_reference_signals(
        self, days: int = 7
    ) -> List[Dict[str, Any]]:
        """Find ROT signals that align with recent insider buys.

        Returns list of {insider_trade, signal} pairs where an insider bought
        the same ticker within `days` of a bullish ROT signal.
        """
        insider_buys = await self.get_recent(days=days, trade_type="buy")
        if not insider_buys:
            return []

        # Get tickers with recent insider buys
        buy_tickers = {t.ticker for t in insider_buys}

        matches = []
        for ticker in buy_tickers:
            signals = await self._db.get_signals_for_ticker(
                ticker, limit=10, days=days
            )
            ticker_buys = [t for t in insider_buys if t.ticker == ticker]
            for sig in signals:
                if sig.get("stance") == "bullish":
                    matches.append(
                        {
                            "ticker": ticker,
                            "insider_trade": ticker_buys[0] if ticker_buys else None,
                            "signal_id": sig.get("id"),
                            "signal_confidence": sig.get("confidence", 0),
                            "signal_created": sig.get("created_at", 0),
                            "alignment": "insider_buy + bullish_signal",
                        }
                    )
        return matches

    # ── Ingestion: SEC Form 4 ────────────────────────────────────────

    async def ingest_form4(self, tickers: List[str] | None = None) -> int:
        """Parse SEC EDGAR for recent Form 4 filings.

        If tickers provided, search for those specific tickers.
        Returns count of trades ingested.
        """
        if not self._user_agent:
            log.debug("SEC EDGAR user agent not configured — skipping Form 4 ingestion")
            return 0

        count = 0
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }

        # Use EDGAR full-text search API
        from datetime import datetime, timedelta, timezone

        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        if tickers:
            for ticker in tickers[:20]:  # Limit to avoid rate limiting
                try:
                    trades = await self._search_form4_ticker(
                        ticker, start_date, end_date, headers
                    )
                    for t in trades:
                        await self._db.upsert_insider_trade(t)
                        count += 1
                except Exception as exc:
                    log.debug("Form 4 search failed for %s: %s", ticker, exc)
        else:
            # General recent Form 4 filings
            try:
                trades = await self._search_form4_recent(
                    start_date, end_date, headers
                )
                for t in trades:
                    await self._db.upsert_insider_trade(t)
                    count += 1
            except Exception as exc:
                log.debug("General Form 4 search failed: %s", exc)

        log.info("Ingested %d insider trades from SEC EDGAR", count)
        return count

    async def _search_form4_ticker(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        headers: Dict[str, str],
    ) -> List[InsiderTrade]:
        """Search EDGAR for Form 4 filings for a specific ticker."""
        url = (
            f"https://efts.sec.gov/LATEST/search-index?"
            f"q={ticker}&forms=4&dateRange=custom"
            f"&startdt={start_date}&enddt={end_date}"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 429:
                log.debug("SEC rate limited — backing off")
                return []
            resp.raise_for_status()

        return self._parse_edgar_results(resp.json(), ticker)

    async def _search_form4_recent(
        self,
        start_date: str,
        end_date: str,
        headers: Dict[str, str],
    ) -> List[InsiderTrade]:
        """Search EDGAR for recent Form 4 filings (any ticker)."""
        url = (
            f"https://efts.sec.gov/LATEST/search-index?"
            f"forms=4&dateRange=custom"
            f"&startdt={start_date}&enddt={end_date}"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 429:
                return []
            resp.raise_for_status()

        return self._parse_edgar_results(resp.json())

    def _parse_edgar_results(
        self, data: Dict[str, Any], ticker: str | None = None
    ) -> List[InsiderTrade]:
        """Parse EDGAR API JSON results into InsiderTrade list."""
        trades: List[InsiderTrade] = []
        hits = data.get("hits", {}).get("hits", [])

        for hit in hits[:50]:
            source = hit.get("_source", {})
            filing_date_str = source.get("file_date", "")
            display_names = source.get("display_names", [])
            entity_name = display_names[0] if display_names else "Unknown"

            # Extract ticker from filing if not provided
            file_ticker = ticker or ""
            tickers_found = source.get("tickers", [])
            if tickers_found:
                file_ticker = tickers_found[0]

            if not file_ticker:
                continue

            # Parse filing date
            try:
                from datetime import datetime, timezone

                dt = datetime.strptime(filing_date_str, "%Y-%m-%d")
                filing_ts = dt.timestamp()
            except (ValueError, TypeError):
                filing_ts = time.time()

            trades.append(
                InsiderTrade(
                    id=f"form4-{hit.get('_id', uuid.uuid4().hex[:8])}",
                    ticker=file_ticker.upper(),
                    insider_name=entity_name,
                    trade_type="buy",  # Will be refined with full XML parsing
                    filing_date=filing_ts,
                    source="form4",
                    title="",
                    meta={
                        "filing_url": source.get("file_url", ""),
                        "form_type": source.get("form_type", "4"),
                    },
                )
            )
        return trades

    # ── Ingestion: Congressional trades ──────────────────────────────

    async def ingest_congress(self) -> int:
        """Parse congressional trading disclosures.

        Returns count of trades ingested.
        """
        # Congress disclosures are less standardized — use RSS/scraping approach
        count = 0
        # This is a simplified implementation — full version would parse
        # House/Senate disclosure PDFs or use an API like quiverquant
        log.debug("Congressional trade ingestion — stub (requires API or PDF parsing)")
        return count

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_trade(row: Dict[str, Any]) -> InsiderTrade:
        """Convert a DB row dict to InsiderTrade."""
        meta = row.get("meta", "{}")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        return InsiderTrade(
            id=row["id"],
            ticker=row["ticker"],
            insider_name=row["insider_name"],
            trade_type=row["trade_type"],
            filing_date=row["filing_date"],
            source=row["source"],
            title=row.get("title", ""),
            shares=row.get("shares", 0),
            price=row.get("price", 0.0),
            value=row.get("value", 0.0),
            transaction_date=row.get("transaction_date"),
            meta=meta,
        )
