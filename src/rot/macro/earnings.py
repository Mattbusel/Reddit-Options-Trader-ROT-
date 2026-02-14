"""Earnings Calendar — earnings date tracking, IV crush analysis, strategy suggestions."""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from typing import Any, Dict, List, Optional

from rot.macro.types import EarningsEvent

log = logging.getLogger(__name__)


class EarningsCalendar:
    """Manages earnings events — ingestion, IV crush history, strategy suggestions."""

    def __init__(self, db: Any, market_enricher: Any = None) -> None:
        self._db = db
        self._enricher = market_enricher

    # ── Query methods ────────────────────────────────────────────────

    async def get_upcoming(self, days: int = 14) -> List[EarningsEvent]:
        """Return earnings events in the next `days` days."""
        now = time.time()
        end = now + days * 86400
        rows = await self._db.query_earnings_events(
            start_ts=now, end_ts=end, order="asc"
        )
        return [self._row_to_event(r) for r in rows]

    async def get_past(self, days: int = 30) -> List[EarningsEvent]:
        """Return earnings events from the last `days` days."""
        now = time.time()
        start = now - days * 86400
        rows = await self._db.query_earnings_events(
            start_ts=start, end_ts=now, order="desc"
        )
        return [self._row_to_event(r) for r in rows]

    async def get_by_ticker(
        self, ticker: str, quarters: int = 12
    ) -> List[EarningsEvent]:
        """Return earnings history for a specific ticker."""
        rows = await self._db.query_earnings_events(
            ticker=ticker, limit=quarters, order="desc"
        )
        return [self._row_to_event(r) for r in rows]

    async def get_this_week(self) -> List[EarningsEvent]:
        """Earnings in the next 7 days."""
        return await self.get_upcoming(days=7)

    # ── IV Crush Analysis ────────────────────────────────────────────

    async def get_iv_crush_history(
        self, ticker: str, lookback: int = 8
    ) -> List[Dict[str, Any]]:
        """Return historical IV crush data for a ticker's earnings events.

        Each entry has: report_date, iv_before, iv_after, iv_crush_pct,
        actual_move_pct, expected_move_pct.
        """
        events = await self.get_by_ticker(ticker, quarters=lookback)
        results = []
        for e in events:
            if e.iv_before is not None and e.iv_after is not None:
                crush = 0.0
                if e.iv_before > 0:
                    crush = round(
                        (e.iv_before - e.iv_after) / e.iv_before * 100, 1
                    )
                results.append(
                    {
                        "report_date": e.report_date,
                        "fiscal_quarter": e.fiscal_quarter,
                        "iv_before": e.iv_before,
                        "iv_after": e.iv_after,
                        "iv_crush_pct": crush,
                        "expected_move_pct": e.expected_move_pct or 0.0,
                        "actual_move_pct": e.actual_move_pct or 0.0,
                        "surprise_pct": e.surprise_pct or 0.0,
                    }
                )
        return results

    def compute_expected_move(
        self, atm_call_price: float, atm_put_price: float, underlying_price: float
    ) -> float:
        """Compute expected move from ATM straddle price.

        Expected move = (ATM call + ATM put) / underlying_price × 100
        This is the market's implied earnings move.
        """
        if underlying_price <= 0:
            return 0.0
        straddle = atm_call_price + atm_put_price
        return round(straddle / underlying_price * 100, 2)

    # ── Strategy Suggestions ─────────────────────────────────────────

    async def recommend_strategy(self, ticker: str) -> Dict[str, Any]:
        """Suggest pre-earnings strategy based on IV crush history.

        Analyzes: average IV crush %, expected vs actual move track record,
        and suggests selling premium (if consistent crush) or buying (if
        actual moves exceed expectations).
        """
        crush_history = await self.get_iv_crush_history(ticker, lookback=8)

        if len(crush_history) < 3:
            return {
                "ticker": ticker,
                "strategy": "none",
                "confidence": "low",
                "reason": "Insufficient earnings history for recommendation.",
                "crush_history": crush_history,
            }

        avg_crush = sum(h["iv_crush_pct"] for h in crush_history) / len(
            crush_history
        )
        avg_expected = sum(h["expected_move_pct"] for h in crush_history) / len(
            crush_history
        )
        avg_actual = sum(
            abs(h["actual_move_pct"]) for h in crush_history
        ) / len(crush_history)

        # How often does actual move exceed expected?
        exceeds_count = sum(
            1
            for h in crush_history
            if abs(h["actual_move_pct"]) > h["expected_move_pct"]
        )
        exceeds_pct = exceeds_count / len(crush_history) * 100

        if avg_crush > 20 and exceeds_pct < 40:
            # Consistent IV crush, actual moves rarely exceed expected
            strategy = "iron_condor"
            reason = (
                f"Average IV crush of {avg_crush:.0f}% with actual moves exceeding "
                f"expected only {exceeds_pct:.0f}% of the time. Sell premium."
            )
            confidence = "high" if len(crush_history) >= 6 else "medium"
        elif exceeds_pct > 60:
            # Actual moves frequently exceed expected — buy straddle
            strategy = "straddle"
            reason = (
                f"Actual earnings moves exceed expectations {exceeds_pct:.0f}% of the time. "
                f"Average actual move: {avg_actual:.1f}% vs expected: {avg_expected:.1f}%. Buy vol."
            )
            confidence = "medium"
        elif avg_crush > 10:
            # Moderate crush — credit spread
            strategy = "credit_spread"
            reason = (
                f"Moderate IV crush ({avg_crush:.0f}%). "
                f"Consider selling directional premium if you have a thesis."
            )
            confidence = "medium"
        else:
            strategy = "none"
            reason = (
                f"Mixed IV crush history ({avg_crush:.0f}%). "
                f"No clear edge from vol alone."
            )
            confidence = "low"

        return {
            "ticker": ticker,
            "strategy": strategy,
            "confidence": confidence,
            "reason": reason,
            "avg_iv_crush_pct": round(avg_crush, 1),
            "avg_expected_move_pct": round(avg_expected, 2),
            "avg_actual_move_pct": round(avg_actual, 2),
            "exceeds_expected_pct": round(exceeds_pct, 1),
            "sample_size": len(crush_history),
            "crush_history": crush_history,
        }

    # ── Ingestion ────────────────────────────────────────────────────

    async def ingest_earnings(self, tickers: List[str]) -> int:
        """Fetch earnings dates from yfinance for given tickers.

        Returns count of events upserted.
        """
        count = 0
        for ticker in tickers:
            try:
                events = self._fetch_earnings_yfinance(ticker)
                for e in events:
                    await self._db.upsert_earnings_event(e)
                    count += 1
            except Exception as exc:
                log.debug("Failed to fetch earnings for %s: %s", ticker, exc)
        log.info("Ingested %d earnings events for %d tickers", count, len(tickers))
        return count

    def _fetch_earnings_yfinance(self, ticker: str) -> List[EarningsEvent]:
        """Fetch earnings data from yfinance."""
        try:
            import yfinance as yf
        except ImportError:
            log.warning("yfinance not installed — skipping earnings fetch")
            return []

        events: List[EarningsEvent] = []
        try:
            t = yf.Ticker(ticker)
            # Get earnings dates
            dates = getattr(t, "earnings_dates", None)
            if dates is None or dates.empty:
                return events

            for idx, row in dates.head(12).iterrows():
                # idx is a Timestamp
                report_ts = float(idx.timestamp())
                eps_est = row.get("EPS Estimate")
                eps_act = row.get("Reported EPS")
                surprise = row.get("Surprise(%)")

                # Clean NaN
                if eps_est is not None and (isinstance(eps_est, float) and math.isnan(eps_est)):
                    eps_est = None
                if eps_act is not None and (isinstance(eps_act, float) and math.isnan(eps_act)):
                    eps_act = None
                if surprise is not None and (isinstance(surprise, float) and math.isnan(surprise)):
                    surprise = None

                quarter = idx.strftime("%Y-Q") + str((idx.month - 1) // 3 + 1)

                events.append(
                    EarningsEvent(
                        id=f"earnings-{ticker}-{idx.strftime('%Y%m%d')}",
                        ticker=ticker.upper(),
                        report_date=report_ts,
                        fiscal_quarter=quarter,
                        eps_estimate=float(eps_est) if eps_est is not None else None,
                        eps_actual=float(eps_act) if eps_act is not None else None,
                        surprise_pct=float(surprise) if surprise is not None else None,
                    )
                )
        except Exception as exc:
            log.debug("yfinance earnings fetch failed for %s: %s", ticker, exc)
        return events

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_event(row: Dict[str, Any]) -> EarningsEvent:
        """Convert a DB row dict to EarningsEvent."""
        meta = row.get("meta", "{}")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        return EarningsEvent(
            id=row["id"],
            ticker=row["ticker"],
            report_date=row["report_date"],
            fiscal_quarter=row.get("fiscal_quarter", ""),
            eps_estimate=row.get("eps_estimate"),
            eps_actual=row.get("eps_actual"),
            revenue_estimate=row.get("revenue_estimate"),
            revenue_actual=row.get("revenue_actual"),
            surprise_pct=row.get("surprise_pct"),
            expected_move_pct=row.get("expected_move_pct"),
            actual_move_pct=row.get("actual_move_pct"),
            iv_before=row.get("iv_before"),
            iv_after=row.get("iv_after"),
            iv_crush_pct=row.get("iv_crush_pct"),
            meta=meta,
        )
