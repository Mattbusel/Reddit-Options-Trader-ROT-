"""Macro event calendar with signal suppression for ROT.

Fetches upcoming economic events (FOMC decisions, CPI releases, earnings) from
free sources, suppresses trade signals in a configurable window around major
events, and attaches event-risk warnings to signal output.

The module delegates event generation to the existing
:mod:`rot.macro.calendar` engine (which already implements recurring rule-based
scheduling) and adds:

- A clean public API for querying "is now inside an event blackout window?"
- Automatic warning attachment to ROT signal dicts
- A configurable suppression window (default: ±24 h around each event)

Typical usage::

    from rot.calendar.macro_events import MacroEventCalendar

    cal = MacroEventCalendar()

    # Check before generating a signal
    check = cal.check_signal(ticker="AAPL")
    if check.suppressed:
        print(f"Signal suppressed: {check.reason}")
    else:
        my_signal["event_warnings"] = check.warnings
        dispatch(my_signal)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Window (hours) before and after a high-impact event in which signals are suppressed
_DEFAULT_SUPPRESS_HOURS_BEFORE = 24
_DEFAULT_SUPPRESS_HOURS_AFTER = 24

# Minimum importance level to trigger suppression
_SUPPRESS_IMPORTANCE_LEVELS = {"high", "critical"}

# Minimum importance level to attach a warning (but not suppress)
_WARN_IMPORTANCE_LEVELS = {"medium", "high", "critical"}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventRisk:
    """A single event that poses risk to a trade signal.

    Attributes:
        name: Human-readable event name.
        event_type: Machine-readable event type key.
        importance: ``"low"``, ``"medium"``, ``"high"``, or ``"critical"``.
        event_time: UTC datetime of the event.
        hours_until: Hours until the event from the time of the check.
        category: Event category string.
    """

    name: str
    event_type: str
    importance: str
    event_time: datetime
    hours_until: float
    category: str = "other"


@dataclass(frozen=True)
class SignalCheckResult:
    """Output of :meth:`MacroEventCalendar.check_signal`.

    Attributes:
        suppressed: Whether the signal should be blocked entirely.
        reason: Human-readable suppression reason (empty if not suppressed).
        warnings: List of event risk warning strings to attach to the signal.
        upcoming_events: All events found within the look-ahead window.
    """

    suppressed: bool
    reason: str
    warnings: List[str]
    upcoming_events: List[EventRisk]


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


class MacroEventCalendar:
    """Queries the macro event schedule and gates/warns on ROT trade signals.

    Args:
        suppress_hours_before: Hours before a high-impact event to suppress signals.
        suppress_hours_after: Hours after a high-impact event to suppress signals.
        lookahead_hours: Total look-ahead window for fetching upcoming events.
    """

    def __init__(
        self,
        suppress_hours_before: float = _DEFAULT_SUPPRESS_HOURS_BEFORE,
        suppress_hours_after: float = _DEFAULT_SUPPRESS_HOURS_AFTER,
        lookahead_hours: float = 72.0,
    ) -> None:
        self._suppress_before = suppress_hours_before
        self._suppress_after = suppress_hours_after
        self._lookahead = lookahead_hours

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_signal(
        self,
        ticker: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> SignalCheckResult:
        """Check whether a trade signal should be suppressed or warned.

        Args:
            ticker: Optional ticker for earnings-specific suppression.
                When provided, the earnings calendar for this ticker is
                also checked.
            now: Reference UTC datetime (defaults to ``datetime.now(UTC)``).

        Returns:
            A :class:`SignalCheckResult` with suppression flag and warnings.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        upcoming = self._fetch_upcoming(now, ticker=ticker)
        warnings: list[str] = []
        suppress_reason = ""

        for event in upcoming:
            delta_h = event.hours_until
            in_suppress_window = (
                -self._suppress_after <= delta_h <= self._suppress_before
            )
            in_warn_window = -self._suppress_after * 2 <= delta_h <= self._lookahead

            if event.importance in _SUPPRESS_IMPORTANCE_LEVELS and in_suppress_window:
                if not suppress_reason:
                    direction = "in" if delta_h >= 0 else "ago"
                    h_label = f"{abs(delta_h):.1f}h"
                    suppress_reason = (
                        f"High-impact event '{event.name}' occurs "
                        f"{h_label} {direction} — signal suppressed."
                    )
                log.info(
                    "macro.suppress ticker=%s event=%s hours_until=%.1f",
                    ticker or "any", event.name, event.hours_until,
                )

            if event.importance in _WARN_IMPORTANCE_LEVELS and in_warn_window:
                direction = "in" if delta_h >= 0 else "ago"
                h_label = f"{abs(delta_h):.0f}h"
                warnings.append(
                    f"[Event Risk] {event.name} ({event.importance.upper()}) "
                    f"— {h_label} {direction}"
                )

        return SignalCheckResult(
            suppressed=bool(suppress_reason),
            reason=suppress_reason,
            warnings=warnings,
            upcoming_events=upcoming,
        )

    def enrich_signal(
        self,
        signal: Dict[str, Any],
        ticker: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Attach event risk warnings to a signal dict in-place.

        If the signal should be suppressed, a ``"suppressed"`` key is added.
        Otherwise, ``"event_warnings"`` lists any nearby events.

        Args:
            signal: ROT signal dictionary to enrich.
            ticker: Optional ticker for earnings lookup.
            now: Reference timestamp.

        Returns:
            The same *signal* dict, mutated.
        """
        result = self.check_signal(ticker=ticker, now=now)
        if result.suppressed:
            signal["suppressed"] = True
            signal["suppression_reason"] = result.reason
        signal["event_warnings"] = result.warnings
        signal["upcoming_macro_events"] = [
            {
                "name": e.name,
                "event_type": e.event_type,
                "importance": e.importance,
                "hours_until": round(e.hours_until, 1),
            }
            for e in result.upcoming_events
        ]
        return signal

    def upcoming_events(
        self,
        ticker: Optional[str] = None,
        now: Optional[datetime] = None,
        hours: float = 72.0,
    ) -> List[EventRisk]:
        """Return all upcoming events within *hours* from *now*.

        Args:
            ticker: Include ticker-specific earnings if provided.
            now: Reference time (defaults to UTC now).
            hours: Look-ahead window in hours.

        Returns:
            Sorted list of :class:`EventRisk` objects.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        orig_lookahead = self._lookahead
        self._lookahead = hours
        events = self._fetch_upcoming(now, ticker=ticker)
        self._lookahead = orig_lookahead
        return events

    # ------------------------------------------------------------------
    # Internal event fetching
    # ------------------------------------------------------------------

    def _fetch_upcoming(
        self,
        now: datetime,
        ticker: Optional[str] = None,
    ) -> List[EventRisk]:
        """Collect upcoming macro + optional earnings events."""
        events: list[EventRisk] = []
        events.extend(self._fetch_macro_events(now))
        if ticker:
            earnings = self._fetch_earnings_event(ticker, now)
            if earnings:
                events.append(earnings)
        # Sort by proximity
        events.sort(key=lambda e: abs(e.hours_until))
        return events

    def _fetch_macro_events(self, now: datetime) -> List[EventRisk]:
        """Delegate to rot.macro.calendar for recurring scheduled events."""
        try:
            from rot.macro.calendar import EconomicCalendar  # type: ignore[import]

            cal = EconomicCalendar()
            # Fetch events for today + lookahead window
            lookahead_date = (now + timedelta(hours=self._lookahead)).date()
            raw_events = cal.get_events_between(now.date(), lookahead_date)
        except Exception as exc:
            log.debug("macro_events.calendar_error error=%s", exc)
            raw_events = []
            # Fall back to a basic hardcoded list for robustness
            return self._hardcoded_events(now)

        result: list[EventRisk] = []
        for ev in raw_events:
            try:
                ev_time = self._parse_event_time(ev, now)
                if ev_time is None:
                    continue
                hours_until = (ev_time - now).total_seconds() / 3600
                if abs(hours_until) > self._lookahead:
                    continue
                result.append(EventRisk(
                    name=getattr(ev, "name", str(ev)),
                    event_type=getattr(ev, "event_type", "unknown"),
                    importance=getattr(ev, "importance", "medium"),
                    event_time=ev_time,
                    hours_until=hours_until,
                    category=getattr(ev, "category", "other"),
                ))
            except Exception:
                pass
        return result

    def _fetch_earnings_event(
        self, ticker: str, now: datetime
    ) -> Optional[EventRisk]:
        """Try to get the next earnings date for *ticker* via yfinance."""
        try:
            import yfinance as yf  # type: ignore[import]

            info = yf.Ticker(ticker).calendar
            if info is None or info.empty:
                return None

            # yfinance calendar may have 'Earnings Date' as index or column
            if hasattr(info, "T"):
                info = info.T
            if "Earnings Date" in info.columns:
                earn_val = info["Earnings Date"].iloc[0]
            elif hasattr(info, "index") and "Earnings Date" in info.index:
                earn_val = info.loc["Earnings Date"].iloc[0]
            else:
                return None

            # Convert to datetime
            if hasattr(earn_val, "to_pydatetime"):
                ev_time = earn_val.to_pydatetime().replace(tzinfo=timezone.utc)
            else:
                from dateutil.parser import parse as dtparse  # type: ignore[import]
                ev_time = dtparse(str(earn_val)).replace(tzinfo=timezone.utc)

            hours_until = (ev_time - now).total_seconds() / 3600
            if abs(hours_until) > self._lookahead:
                return None

            return EventRisk(
                name=f"{ticker} Earnings",
                event_type="earnings",
                importance="high",
                event_time=ev_time,
                hours_until=hours_until,
                category="earnings",
            )
        except Exception as exc:
            log.debug("macro_events.earnings_error ticker=%s error=%s", ticker, exc)
            return None

    def _hardcoded_events(self, now: datetime) -> List[EventRisk]:
        """Return a minimal list of well-known recurring events as a fallback.

        Uses deterministic monthly rules similar to the rot.macro.calendar
        engine but without the full dependency chain.
        """
        from calendar import monthcalendar

        events: list[EventRisk] = []
        year, month = now.year, now.month

        def _nth_weekday(n: int, weekday: int) -> Optional[datetime]:
            """Return the nth occurrence (1-based) of weekday in current month."""
            weeks = monthcalendar(year, month)
            found = [w[weekday] for w in weeks if w[weekday] != 0]
            if len(found) >= n:
                return datetime(year, month, found[n - 1], 14, 0, tzinfo=timezone.utc)
            return None

        # FOMC ~ 3rd Wednesday
        fomc = _nth_weekday(3, 2)  # Wednesday = 2
        if fomc:
            h = (fomc - now).total_seconds() / 3600
            if abs(h) <= self._lookahead:
                events.append(EventRisk(
                    name="FOMC Interest Rate Decision",
                    event_type="fomc_decision",
                    importance="critical",
                    event_time=fomc,
                    hours_until=h,
                    category="monetary_policy",
                ))

        # CPI ~ 2nd Tuesday at 08:30 ET (13:30 UTC)
        cpi = _nth_weekday(2, 1)  # Tuesday = 1
        if cpi:
            cpi = cpi.replace(hour=13, minute=30)
            h = (cpi - now).total_seconds() / 3600
            if abs(h) <= self._lookahead:
                events.append(EventRisk(
                    name="Consumer Price Index (CPI)",
                    event_type="cpi",
                    importance="high",
                    event_time=cpi,
                    hours_until=h,
                    category="inflation",
                ))

        # NFP ~ 1st Friday at 08:30 ET (13:30 UTC)
        nfp = _nth_weekday(1, 4)  # Friday = 4
        if nfp:
            nfp = nfp.replace(hour=13, minute=30)
            h = (nfp - now).total_seconds() / 3600
            if abs(h) <= self._lookahead:
                events.append(EventRisk(
                    name="Nonfarm Payrolls",
                    event_type="nonfarm_payrolls",
                    importance="high",
                    event_time=nfp,
                    hours_until=h,
                    category="employment",
                ))

        return events

    @staticmethod
    def _parse_event_time(ev: Any, now: datetime) -> Optional[datetime]:
        """Extract a UTC datetime from a MacroEvent-like object."""
        # Try common attribute patterns from rot.macro.types.MacroEvent
        for attr in ("event_time", "scheduled_time", "date", "datetime"):
            val = getattr(ev, attr, None)
            if val is None:
                continue
            if isinstance(val, datetime):
                if val.tzinfo is None:
                    val = val.replace(tzinfo=timezone.utc)
                return val
            if isinstance(val, str):
                try:
                    from dateutil.parser import parse as dtparse  # type: ignore[import]
                    parsed = dtparse(val)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed
                except Exception:
                    pass
        return None
