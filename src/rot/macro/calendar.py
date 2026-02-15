"""Economic Calendar — event ingestion, scheduling, and queries."""

from __future__ import annotations

import json
import logging
import time
import uuid
from calendar import monthcalendar
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

from rot.macro.types import (
    CATEGORY_SECTOR_SENSITIVITY,
    EVENT_TYPE_CATEGORY,
    EVENT_TYPE_IMPORTANCE,
    MacroEvent,
)

log = logging.getLogger(__name__)

# ── Recurring event schedule ─────────────────────────────────────────
# Maps event_type → (day_of_week_rule, description)
# These are generated deterministically for future months.

_RECURRING_RULES: Dict[str, Dict[str, Any]] = {
    # Employment — NFP is first Friday of the month
    "nonfarm_payrolls": {
        "name": "Nonfarm Payrolls",
        "rule": "first_friday",
        "time_et": "08:30",
    },
    "initial_claims": {
        "name": "Initial Jobless Claims",
        "rule": "every_thursday",
        "time_et": "08:30",
    },
    # Inflation — CPI is typically 2nd or 3rd week Tuesday/Wednesday
    "cpi": {
        "name": "Consumer Price Index (CPI)",
        "rule": "second_tuesday",
        "time_et": "08:30",
    },
    "core_cpi": {
        "name": "Core CPI (ex Food & Energy)",
        "rule": "second_tuesday",  # released same day as CPI
        "time_et": "08:30",
    },
    "ppi": {
        "name": "Producer Price Index (PPI)",
        "rule": "second_wednesday",
        "time_et": "08:30",
    },
    # Consumer
    "retail_sales": {
        "name": "Retail Sales",
        "rule": "third_tuesday",
        "time_et": "08:30",
    },
    "michigan_sentiment": {
        "name": "Michigan Consumer Sentiment",
        "rule": "second_friday",
        "time_et": "10:00",
    },
    "consumer_confidence": {
        "name": "Conference Board Consumer Confidence",
        "rule": "last_tuesday",
        "time_et": "10:00",
    },
    # Manufacturing
    "ism_manufacturing": {
        "name": "ISM Manufacturing PMI",
        "rule": "first_business_day",
        "time_et": "10:00",
    },
    "ism_services": {
        "name": "ISM Services PMI",
        "rule": "third_business_day",
        "time_et": "10:00",
    },
    # Housing
    "existing_home_sales": {
        "name": "Existing Home Sales",
        "rule": "third_thursday",
        "time_et": "10:00",
    },
    "housing_starts": {
        "name": "Housing Starts & Building Permits",
        "rule": "third_wednesday",
        "time_et": "08:30",
    },
    # Markets
    "opex": {
        "name": "Monthly Options Expiration (OPEX)",
        "rule": "third_friday",
        "time_et": "16:00",
    },
}


# Decision is announced on the second day of each 2-day meeting.
_FOMC_DECISION_DATES_2026 = [
    "2026-01-29", "2026-03-18", "2026-05-06", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> int:
    """Return day-of-month for the n-th occurrence of weekday (0=Mon) in month.

    Returns 0 if n-th occurrence doesn't exist.
    """
    count = 0
    for week in monthcalendar(year, month):
        if week[weekday] != 0:
            count += 1
            if count == n:
                return week[weekday]
    return 0


def _last_weekday_of_month(year: int, month: int, weekday: int) -> int:
    """Return day-of-month for the last occurrence of weekday in month."""
    for week in reversed(monthcalendar(year, month)):
        if week[weekday] != 0:
            return week[weekday]
    return 0


def _first_business_day_of_month(year: int, month: int) -> int:
    """Return day-of-month for the first business day (Mon-Fri)."""
    for week in monthcalendar(year, month):
        for wd in range(5):  # Mon-Fri
            if week[wd] != 0:
                return week[wd]
    return 1


def _resolve_rule(rule: str, year: int, month: int) -> int:
    """Resolve a scheduling rule to a day-of-month."""
    rules = {
        "first_friday": lambda: _nth_weekday_of_month(year, month, 4, 1),
        "every_thursday": lambda: _nth_weekday_of_month(year, month, 3, 1),  # first for monthly
        "second_tuesday": lambda: _nth_weekday_of_month(year, month, 1, 2),
        "second_wednesday": lambda: _nth_weekday_of_month(year, month, 2, 2),
        "second_friday": lambda: _nth_weekday_of_month(year, month, 4, 2),
        "third_tuesday": lambda: _nth_weekday_of_month(year, month, 1, 3),
        "third_wednesday": lambda: _nth_weekday_of_month(year, month, 2, 3),
        "third_thursday": lambda: _nth_weekday_of_month(year, month, 3, 3),
        "third_friday": lambda: _nth_weekday_of_month(year, month, 4, 3),
        "last_tuesday": lambda: _last_weekday_of_month(year, month, 1),
        "first_business_day": lambda: _first_business_day_of_month(year, month),
        "third_business_day": lambda: _first_business_day_of_month(year, month) + 2,
    }
    fn = rules.get(rule)
    if fn is None:
        return 0
    return fn()


def _make_timestamp(year: int, month: int, day: int, time_et: str) -> float:
    """Create a Unix timestamp from date + ET time string."""
    h, m = (int(x) for x in time_et.split(":"))
    dt = datetime(year, month, day, h, m, tzinfo=timezone.utc)
    # Approximate ET as UTC-5 (ignoring DST for simplicity)
    ts = dt.timestamp() + 5 * 3600
    return ts


class EconomicCalendar:
    """Manages economic calendar events — ingestion, generation, and queries."""

    def __init__(self, db: Any, config: Any | None = None) -> None:
        self._db = db
        self._cfg = config

    # ── Query methods ────────────────────────────────────────────────

    async def get_upcoming(self, days: int = 7) -> List[MacroEvent]:
        """Return events scheduled within the next `days` days."""
        now = time.time()
        end = now + days * 86400
        rows = await self._db.query_macro_events(
            start_ts=now, end_ts=end, order="asc"
        )
        return [self._row_to_event(r) for r in rows]

    async def get_past(self, days: int = 30) -> List[MacroEvent]:
        """Return events from the last `days` days."""
        now = time.time()
        start = now - days * 86400
        rows = await self._db.query_macro_events(
            start_ts=start, end_ts=now, order="desc"
        )
        return [self._row_to_event(r) for r in rows]

    async def get_by_type(
        self, event_type: str, limit: int = 50
    ) -> List[MacroEvent]:
        """Return events of a specific type."""
        rows = await self._db.query_macro_events(
            event_type=event_type, limit=limit, order="desc"
        )
        return [self._row_to_event(r) for r in rows]

    async def get_by_category(
        self, category: str, days: int = 30
    ) -> List[MacroEvent]:
        """Return events for a specific category."""
        now = time.time()
        start = now - days * 86400
        rows = await self._db.query_macro_events(
            category=category, start_ts=start, order="desc"
        )
        return [self._row_to_event(r) for r in rows]

    async def get_this_week(self) -> List[MacroEvent]:
        """Convenience: upcoming events in the next 7 days."""
        return await self.get_upcoming(days=7)

    async def get_next_critical(self, limit: int = 5) -> List[MacroEvent]:
        """Return the next few critical/high-importance events."""
        now = time.time()
        end = now + 30 * 86400
        rows = await self._db.query_macro_events(
            start_ts=now,
            end_ts=end,
            importance_in=["critical", "high"],
            limit=limit,
            order="asc",
        )
        return [self._row_to_event(r) for r in rows]

    # ── Generation methods ───────────────────────────────────────────

    def generate_recurring(
        self, year: int, month: int
    ) -> List[MacroEvent]:
        """Generate recurring events for a given year/month."""
        events: List[MacroEvent] = []
        for event_type, rule in _RECURRING_RULES.items():
            day = _resolve_rule(rule["rule"], year, month)
            if day == 0:
                continue
            ts = _make_timestamp(year, month, day, rule["time_et"])
            category = EVENT_TYPE_CATEGORY.get(event_type, "other")
            importance = EVENT_TYPE_IMPORTANCE.get(event_type, "medium")
            affected = CATEGORY_SECTOR_SENSITIVITY.get(category, [])
            events.append(
                MacroEvent(
                    id=f"recurring-{event_type}-{year}-{month:02d}",
                    event_type=event_type,
                    name=rule["name"],
                    scheduled_at=ts,
                    category=category,
                    importance=importance,
                    affected_sectors=affected,
                    source="recurring",
                )
            )
        return events

    def generate_fomc_events(self, year: int = 2026) -> List[MacroEvent]:
        """Generate FOMC meeting events for a year."""
        dates = _FOMC_DECISION_DATES_2026 if year == 2026 else []
        events: List[MacroEvent] = []
        for ds in dates:
            dt = datetime.strptime(ds, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            # Decision at 2:00 PM ET = 19:00 UTC
            ts = dt.timestamp() + 19 * 3600
            events.append(
                MacroEvent(
                    id=f"fomc-decision-{ds}",
                    event_type="fomc_decision",
                    name="FOMC Rate Decision",
                    scheduled_at=ts,
                    category="monetary_policy",
                    importance="critical",
                    affected_sectors=CATEGORY_SECTOR_SENSITIVITY.get(
                        "monetary_policy", []
                    ),
                    source="fed_calendar",
                )
            )
        return events

    async def seed_events(self, year: int, months: List[int] | None = None) -> int:
        """Generate and save recurring events for given months.

        Returns count of events upserted.
        """
        if months is None:
            months = list(range(1, 13))
        count = 0
        for month in months:
            events = self.generate_recurring(year, month)
            for e in events:
                await self._db.upsert_macro_event(e)
                count += 1
        # FOMC
        fomc = self.generate_fomc_events(year)
        for e in fomc:
            await self._db.upsert_macro_event(e)
            count += 1
        log.info("Seeded %d macro events for %d", count, year)
        return count

    # ── External ingestion ───────────────────────────────────────────

    async def ingest_from_rss(self) -> int:
        """Poll RSS feeds for macro-relevant news. Returns count of new events."""
        # Fed press releases RSS
        count = 0
        feeds = [
            (
                "https://www.federalreserve.gov/feeds/press_all.xml",
                "fed_press",
                "monetary_policy",
            ),
        ]
        for url, source, category in feeds:
            try:
                events = await self._fetch_rss_events(url, source, category)
                for e in events:
                    saved = await self._db.upsert_macro_event(e)
                    if saved:
                        count += 1
            except Exception as exc:
                log.warning("Failed to ingest RSS %s: %s", url, exc)
        return count

    async def _fetch_rss_events(
        self, url: str, source: str, category: str
    ) -> List[MacroEvent]:
        """Fetch and parse RSS feed into MacroEvents."""
        try:
            import feedparser
        except ImportError:
            log.warning("feedparser not installed — skipping RSS ingestion")
            return []

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        events: List[MacroEvent] = []
        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            published = entry.get("published_parsed")
            if published:
                from calendar import timegm

                ts = float(timegm(published))
            else:
                ts = time.time()
            events.append(
                MacroEvent(
                    id=f"{source}-{uuid.uuid4().hex[:8]}",
                    event_type="fed_speech",
                    name=title[:200],
                    scheduled_at=ts,
                    category=category,
                    importance="medium",
                    source=source,
                    meta={"link": entry.get("link", "")},
                )
            )
        return events

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_event(row: Dict[str, Any]) -> MacroEvent:
        """Convert a DB row dict to MacroEvent."""
        sectors = row.get("affected_sectors", "[]")
        if isinstance(sectors, str):
            try:
                sectors = json.loads(sectors)
            except (json.JSONDecodeError, TypeError):
                sectors = []
        tickers = row.get("affected_tickers", "[]")
        if isinstance(tickers, str):
            try:
                tickers = json.loads(tickers)
            except (json.JSONDecodeError, TypeError):
                tickers = []
        meta = row.get("meta", "{}")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        return MacroEvent(
            id=row["id"],
            event_type=row["event_type"],
            name=row["name"],
            scheduled_at=row["scheduled_at"],
            category=row.get("category", "other"),
            importance=row.get("importance", "medium"),
            country=row.get("country", "US"),
            actual_at=row.get("actual_at"),
            consensus_value=row.get("consensus_value"),
            actual_value=row.get("actual_value"),
            previous_value=row.get("previous_value"),
            surprise_pct=row.get("surprise_pct"),
            affected_sectors=sectors,
            affected_tickers=tickers,
            source=row.get("source", ""),
            meta=meta,
        )

    @staticmethod
    def find_nearby_events(
        events: List[MacroEvent], signal_ts: float, window_hours: int = 24
    ) -> List[MacroEvent]:
        """Find events within a time window of a signal timestamp."""
        window_s = window_hours * 3600
        return [
            e
            for e in events
            if abs(e.scheduled_at - signal_ts) <= window_s
        ]
