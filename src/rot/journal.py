"""Automated Trade Journal for the Reddit Options Trader (ROT) system.

Tracks every trade idea from signal generation through to outcome resolution,
storing the full lifecycle in a SQLite table.  After an option's expiry date
passes, the journal automatically fetches the actual price move and records the
outcome.

Key types
---------
:class:`JournalEntry`
    One row in the journal: signal metadata + post-hoc outcome.

:class:`JournalReport`
    Aggregated statistics over all (or filtered) entries.

:class:`TradeJournal`
    The main object — wraps an aiosqlite connection, provides insert/query/
    update helpers, and exposes an ``auto_resolve_expired()`` coroutine that
    the background task runner should call periodically.

FastAPI integration
-------------------
Two routes are registered here and imported in ``app.py``:

- ``GET /journal``              — HTML page (dark theme, table view)
- ``GET /api/journal/report``   — JSON :class:`JournalReport`

Example::

    from rot.journal import TradeJournal, JournalEntry
    import aiosqlite

    async with aiosqlite.connect("rot.db") as db:
        journal = TradeJournal(db)
        await journal.init_schema()

        entry_id = await journal.insert(JournalEntry(
            signal_id="sig_001",
            ticker="AAPL",
            strategy_type="bull_call_spread",
            entry_date="2026-03-10",
            expiry_date="2026-03-21",
            predicted_direction="bullish",
            confidence_score=0.78,
        ))

        report = await journal.get_report()
        print(report)
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class JournalEntry:
    """One trade-idea lifecycle record.

    Attributes:
        signal_id:           Foreign key to the ``signals`` table.
        ticker:              Underlying ticker symbol (e.g. ``"AAPL"``).
        strategy_type:       Options strategy name (``"long_call"``,
                             ``"bull_put_spread"``, etc.).
        entry_date:          ISO-8601 date when the trade idea was generated
                             (``"YYYY-MM-DD"``).
        expiry_date:         ISO-8601 option expiry date.
        predicted_direction: ``"bullish"`` or ``"bearish"`` or ``"neutral"``.
        confidence_score:    Model confidence in [0, 1].
        notes:               Free-text analyst notes.
        actual_outcome:      ``"win"``, ``"loss"``, or ``"neutral"`` — filled
                             in automatically after expiry.
        pnl_estimate:        Estimated PnL as a fraction of premium (e.g. 0.5 =
                             50 % gain, -1.0 = full loss).  ``None`` until resolved.
        price_at_entry:      Underlying spot price when the idea was generated.
        price_at_expiry:     Underlying spot price at expiry.  ``None`` until resolved.
        id:                  Auto-assigned DB row ID; leave as 0 on insert.
        created_at:          Unix timestamp of row creation; auto-set on insert.
    """
    signal_id:           str
    ticker:              str
    strategy_type:       str
    entry_date:          str    # ISO-8601 date string
    expiry_date:         str    # ISO-8601 date string
    predicted_direction: str    # "bullish" | "bearish" | "neutral"
    confidence_score:    float  # [0, 1]
    notes:               str    = ""
    actual_outcome:      Optional[str]   = None   # "win" | "loss" | "neutral"
    pnl_estimate:        Optional[float] = None
    price_at_entry:      Optional[float] = None
    price_at_expiry:     Optional[float] = None
    id:                  int    = 0
    created_at:          float  = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict."""
        return {
            "id":                  self.id,
            "signal_id":           self.signal_id,
            "ticker":              self.ticker,
            "strategy_type":       self.strategy_type,
            "entry_date":          self.entry_date,
            "expiry_date":         self.expiry_date,
            "predicted_direction": self.predicted_direction,
            "confidence_score":    round(self.confidence_score, 4),
            "notes":               self.notes,
            "actual_outcome":      self.actual_outcome,
            "pnl_estimate":        round(self.pnl_estimate, 4) if self.pnl_estimate is not None else None,
            "price_at_entry":      self.price_at_entry,
            "price_at_expiry":     self.price_at_expiry,
            "created_at":          self.created_at,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "JournalEntry":
        """Construct a :class:`JournalEntry` from a database row dict."""
        return cls(
            id=row.get("id", 0),
            signal_id=row.get("signal_id", ""),
            ticker=row.get("ticker", ""),
            strategy_type=row.get("strategy_type", ""),
            entry_date=row.get("entry_date", ""),
            expiry_date=row.get("expiry_date", ""),
            predicted_direction=row.get("predicted_direction", ""),
            confidence_score=float(row.get("confidence_score", 0.0)),
            notes=row.get("notes", ""),
            actual_outcome=row.get("actual_outcome"),
            pnl_estimate=row.get("pnl_estimate"),
            price_at_entry=row.get("price_at_entry"),
            price_at_expiry=row.get("price_at_expiry"),
            created_at=float(row.get("created_at", time.time())),
        )


@dataclass
class JournalReport:
    """Aggregated statistics over journal entries.

    Attributes:
        total_entries:         Total trades logged.
        resolved_entries:      Trades with a known outcome.
        win_rate:              Fraction of resolved trades that were wins.
        avg_pnl:               Mean PnL estimate across resolved trades.
        best_trade:            Entry with the highest ``pnl_estimate``.
        worst_trade:           Entry with the lowest ``pnl_estimate``.
        accuracy_by_strategy:  Win rate per strategy type.
        accuracy_by_direction: Win rate per predicted direction.
    """
    total_entries:         int
    resolved_entries:      int
    win_rate:              float
    avg_pnl:               float
    best_trade:            Optional[JournalEntry]
    worst_trade:           Optional[JournalEntry]
    accuracy_by_strategy:  Dict[str, float]
    accuracy_by_direction: Dict[str, float]

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict."""
        return {
            "total_entries":         self.total_entries,
            "resolved_entries":      self.resolved_entries,
            "win_rate":              round(self.win_rate, 4),
            "avg_pnl":               round(self.avg_pnl, 4),
            "best_trade":            self.best_trade.to_dict() if self.best_trade else None,
            "worst_trade":           self.worst_trade.to_dict() if self.worst_trade else None,
            "accuracy_by_strategy":  {k: round(v, 4) for k, v in self.accuracy_by_strategy.items()},
            "accuracy_by_direction": {k: round(v, 4) for k, v in self.accuracy_by_direction.items()},
        }


# ---------------------------------------------------------------------------
# Outcome resolver
# ---------------------------------------------------------------------------


def _fetch_price(ticker: str) -> Optional[float]:
    """Fetch the current/last closing price for ``ticker`` via yfinance.

    Args:
        ticker: Ticker symbol (e.g. ``"AAPL"``).

    Returns:
        Closing price or ``None`` if unavailable.
    """
    try:
        import yfinance as yf  # type: ignore
        info = yf.Ticker(ticker).fast_info
        return float(info.last_price)
    except Exception as exc:
        log.debug("journal.fetch_price_error ticker=%s err=%s", ticker, exc)
        return None


def _determine_outcome(
    predicted_direction: str,
    price_at_entry: Optional[float],
    price_at_expiry: Optional[float],
) -> tuple[str, float]:
    """Derive the actual outcome from entry and expiry prices.

    A bullish prediction is a ``"win"`` if the underlying moved up at
    expiry; bearish = win if it moved down; neutral = win if |move| < 2 %.

    Args:
        predicted_direction: ``"bullish"``, ``"bearish"``, or ``"neutral"``.
        price_at_entry:      Underlying price when the trade was entered.
        price_at_expiry:     Underlying price at expiry.

    Returns:
        Tuple ``(outcome: str, pnl_estimate: float)``.  PnL estimate is a rough
        fraction-of-premium heuristic: +0.5 for a correct 1 % move, -1.0 for a
        wrong 1 % move (linear interpolation, capped at ±1).
    """
    if price_at_entry is None or price_at_expiry is None or price_at_entry <= 0:
        return ("unknown", 0.0)

    pct_move = (price_at_expiry - price_at_entry) / price_at_entry

    if predicted_direction == "bullish":
        correct = pct_move > 0.0
    elif predicted_direction == "bearish":
        correct = pct_move < 0.0
    else:  # neutral
        correct = abs(pct_move) < 0.02

    outcome = "win" if correct else "loss"
    # Very rough PnL heuristic: up to ±1.0 based on magnitude of move.
    sign = 1.0 if correct else -1.0
    pnl = sign * min(1.0, abs(pct_move) * 20)  # 5 % move → ~100 % PnL
    return (outcome, round(pnl, 4))


# ---------------------------------------------------------------------------
# TradeJournal
# ---------------------------------------------------------------------------


class TradeJournal:
    """Persistent trade journal backed by an aiosqlite database connection.

    All methods are async-safe.  Pass in a shared ``aiosqlite.Connection``
    so the journal reuses the application's existing DB connection pool.

    Args:
        db: An open ``aiosqlite.Connection`` (or any compatible async cursor
            factory with the aiosqlite interface).
    """

    _CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS trade_journal (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id           TEXT    NOT NULL,
        ticker              TEXT    NOT NULL,
        strategy_type       TEXT    NOT NULL DEFAULT '',
        entry_date          TEXT    NOT NULL,
        expiry_date         TEXT    NOT NULL,
        predicted_direction TEXT    NOT NULL DEFAULT 'neutral',
        confidence_score    REAL    NOT NULL DEFAULT 0.0,
        notes               TEXT    NOT NULL DEFAULT '',
        actual_outcome      TEXT,
        pnl_estimate        REAL,
        price_at_entry      REAL,
        price_at_expiry     REAL,
        created_at          REAL    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_tj_ticker     ON trade_journal(ticker);
    CREATE INDEX IF NOT EXISTS idx_tj_expiry     ON trade_journal(expiry_date);
    CREATE INDEX IF NOT EXISTS idx_tj_outcome    ON trade_journal(actual_outcome);
    CREATE INDEX IF NOT EXISTS idx_tj_signal     ON trade_journal(signal_id);
    """

    def __init__(self, db) -> None:
        self._db = db

    async def init_schema(self) -> None:
        """Create the ``trade_journal`` table and indexes (idempotent).

        Should be called once during application startup.
        """
        for statement in self._CREATE_TABLE_SQL.strip().split(";"):
            stmt = statement.strip()
            if stmt:
                await self._db.execute(stmt)
        await self._db.commit()
        log.info("journal.schema_ready")

    async def insert(self, entry: JournalEntry) -> int:
        """Insert a new journal entry and return its assigned row ID.

        Args:
            entry: A :class:`JournalEntry` with ``id=0`` (auto-assigned).

        Returns:
            The new row's auto-incremented ID.
        """
        cursor = await self._db.execute(
            """
            INSERT INTO trade_journal (
                signal_id, ticker, strategy_type, entry_date, expiry_date,
                predicted_direction, confidence_score, notes,
                actual_outcome, pnl_estimate, price_at_entry, price_at_expiry,
                created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entry.signal_id, entry.ticker, entry.strategy_type,
                entry.entry_date, entry.expiry_date, entry.predicted_direction,
                entry.confidence_score, entry.notes,
                entry.actual_outcome, entry.pnl_estimate,
                entry.price_at_entry, entry.price_at_expiry,
                entry.created_at,
            ),
        )
        await self._db.commit()
        row_id = cursor.lastrowid or 0
        log.info("journal.insert id=%d ticker=%s signal=%s", row_id, entry.ticker, entry.signal_id)
        return row_id

    async def get_by_id(self, entry_id: int) -> Optional[JournalEntry]:
        """Fetch a single entry by its primary key.

        Args:
            entry_id: Row ID in ``trade_journal``.

        Returns:
            :class:`JournalEntry` or ``None`` if not found.
        """
        cursor = await self._db.execute(
            "SELECT * FROM trade_journal WHERE id = ?", (entry_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return JournalEntry.from_row(dict(zip(cols, row)))

    async def list_entries(
        self,
        ticker: Optional[str] = None,
        outcome: Optional[str] = None,
        strategy: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[JournalEntry]:
        """List journal entries with optional filters.

        Args:
            ticker:   Filter to a specific ticker.
            outcome:  Filter to ``"win"``, ``"loss"``, or ``"neutral"``.
            strategy: Filter to a specific strategy type.
            limit:    Maximum rows to return.
            offset:   Pagination offset.

        Returns:
            List of :class:`JournalEntry` objects.
        """
        clauses: List[str] = []
        params: List[Any]  = []
        if ticker:
            clauses.append("ticker = ?");    params.append(ticker.upper())
        if outcome:
            clauses.append("actual_outcome = ?"); params.append(outcome)
        if strategy:
            clauses.append("strategy_type = ?"); params.append(strategy)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT * FROM trade_journal
            {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params += [limit, offset]
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [JournalEntry.from_row(dict(zip(cols, r))) for r in rows]

    async def update_outcome(
        self,
        entry_id: int,
        actual_outcome: str,
        pnl_estimate: float,
        price_at_expiry: float,
    ) -> None:
        """Update the outcome fields for a resolved trade.

        Args:
            entry_id:        Row ID to update.
            actual_outcome:  ``"win"``, ``"loss"``, or ``"neutral"``.
            pnl_estimate:    Estimated PnL fraction.
            price_at_expiry: Underlying price at expiry.
        """
        await self._db.execute(
            """
            UPDATE trade_journal
            SET actual_outcome=?, pnl_estimate=?, price_at_expiry=?
            WHERE id=?
            """,
            (actual_outcome, pnl_estimate, price_at_expiry, entry_id),
        )
        await self._db.commit()
        log.info(
            "journal.outcome_updated id=%d outcome=%s pnl=%.4f",
            entry_id, actual_outcome, pnl_estimate,
        )

    async def auto_resolve_expired(self) -> int:
        """Resolve all entries whose expiry date has passed and have no outcome.

        Fetches the current price via ``yfinance`` and computes the outcome
        heuristically.  Should be called periodically (e.g. daily).

        Returns:
            Number of entries resolved in this call.
        """
        today = date.today().isoformat()
        cursor = await self._db.execute(
            """
            SELECT * FROM trade_journal
            WHERE actual_outcome IS NULL
              AND expiry_date < ?
            """,
            (today,),
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        unresolved = [JournalEntry.from_row(dict(zip(cols, r))) for r in rows]

        resolved_count = 0
        for entry in unresolved:
            price = _fetch_price(entry.ticker)
            if price is None:
                continue
            outcome, pnl = _determine_outcome(
                entry.predicted_direction,
                entry.price_at_entry,
                price,
            )
            if outcome == "unknown":
                continue
            await self.update_outcome(
                entry_id=entry.id,
                actual_outcome=outcome,
                pnl_estimate=pnl,
                price_at_expiry=price,
            )
            resolved_count += 1

        if resolved_count:
            log.info("journal.auto_resolve resolved=%d", resolved_count)
        return resolved_count

    async def get_report(
        self,
        ticker: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> JournalReport:
        """Compute aggregated statistics over (optionally filtered) entries.

        Args:
            ticker:   Restrict to a specific ticker (None = all).
            strategy: Restrict to a specific strategy type (None = all).

        Returns:
            :class:`JournalReport` with win rate, avg PnL, best/worst trade, etc.
        """
        entries = await self.list_entries(ticker=ticker, strategy=strategy, limit=10_000)
        resolved = [e for e in entries if e.actual_outcome in ("win", "loss", "neutral")]

        win_rate = 0.0
        avg_pnl  = 0.0
        if resolved:
            wins     = sum(1 for e in resolved if e.actual_outcome == "win")
            win_rate = wins / len(resolved)
            pnl_vals = [e.pnl_estimate for e in resolved if e.pnl_estimate is not None]
            avg_pnl  = float(sum(pnl_vals) / len(pnl_vals)) if pnl_vals else 0.0

        # Best / worst by pnl_estimate.
        pnl_entries = [e for e in resolved if e.pnl_estimate is not None]
        best_trade  = max(pnl_entries, key=lambda e: e.pnl_estimate, default=None)  # type: ignore[arg-type]
        worst_trade = min(pnl_entries, key=lambda e: e.pnl_estimate, default=None)  # type: ignore[arg-type]

        # Accuracy by strategy.
        by_strategy: Dict[str, List[str]] = {}
        for e in resolved:
            by_strategy.setdefault(e.strategy_type, []).append(e.actual_outcome)
        acc_by_strategy = {
            strat: sum(1 for o in outcomes if o == "win") / len(outcomes)
            for strat, outcomes in by_strategy.items() if outcomes
        }

        # Accuracy by predicted direction.
        by_dir: Dict[str, List[str]] = {}
        for e in resolved:
            by_dir.setdefault(e.predicted_direction, []).append(e.actual_outcome)
        acc_by_dir = {
            d: sum(1 for o in outcomes if o == "win") / len(outcomes)
            for d, outcomes in by_dir.items() if outcomes
        }

        return JournalReport(
            total_entries=len(entries),
            resolved_entries=len(resolved),
            win_rate=win_rate,
            avg_pnl=avg_pnl,
            best_trade=best_trade,
            worst_trade=worst_trade,
            accuracy_by_strategy=acc_by_strategy,
            accuracy_by_direction=acc_by_dir,
        )


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

if _FASTAPI_AVAILABLE:
    router = APIRouter()

    @router.get("/api/journal/report", tags=["journal"])
    async def journal_report_api(request: Request) -> JSONResponse:
        """Return the aggregated :class:`JournalReport` as JSON.

        Query parameters:
            ticker:   Optional ticker filter.
            strategy: Optional strategy-type filter.

        Returns:
            JSON serialisation of :class:`JournalReport`.
        """
        db      = request.app.state.db
        journal = TradeJournal(db)
        ticker   = request.query_params.get("ticker")
        strategy = request.query_params.get("strategy")
        try:
            await journal.init_schema()
            report = await journal.get_report(ticker=ticker, strategy=strategy)
            return JSONResponse({"success": True, "report": report.to_dict()})
        except Exception as exc:
            log.error("journal.report_error %s", exc, exc_info=True)
            return JSONResponse(
                {"success": False, "error": str(exc)}, status_code=500
            )

    @router.get("/journal", response_class=HTMLResponse, tags=["journal"])
    async def journal_page(request: Request) -> HTMLResponse:
        """Render the Trade Journal HTML page (dark theme).

        Returns:
            HTML page listing all trade journal entries with sortable columns
            and links to the JSON API.
        """
        db      = request.app.state.db
        journal = TradeJournal(db)
        try:
            await journal.init_schema()
            entries = await journal.list_entries(limit=200)
            report  = await journal.get_report()
        except Exception as exc:
            log.error("journal.page_error %s", exc)
            entries = []
            report  = JournalReport(0, 0, 0.0, 0.0, None, None, {}, {})

        def _outcome_badge(outcome: Optional[str]) -> str:
            colors = {"win": "#3fb950", "loss": "#f85149", "neutral": "#8b949e"}
            c = colors.get(outcome or "", "#8b949e")
            return f'<span style="color:{c};font-weight:700">{outcome or "pending"}</span>'

        def _dir_badge(d: str) -> str:
            colors = {"bullish": "#3fb950", "bearish": "#f85149", "neutral": "#8b949e"}
            c = colors.get(d, "#8b949e")
            return f'<span style="color:{c}">{d}</span>'

        rows_html = "".join(
            f"""<tr>
              <td>{e.id}</td>
              <td><strong>{e.ticker}</strong></td>
              <td>{e.strategy_type}</td>
              <td>{e.entry_date}</td>
              <td>{e.expiry_date}</td>
              <td>{_dir_badge(e.predicted_direction)}</td>
              <td>{e.confidence_score:.0%}</td>
              <td>{_outcome_badge(e.actual_outcome)}</td>
              <td>{"—" if e.pnl_estimate is None else f"{e.pnl_estimate:+.1%}"}</td>
            </tr>"""
            for e in entries
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ROT — Trade Journal</title>
  <style>
    body {{ background:#0d1117; color:#c9d1d9; font-family:'Segoe UI',sans-serif;
            font-size:14px; margin:0; padding:0; }}
    header {{ background:#161b22; border-bottom:1px solid #30363d;
              padding:16px 24px; }}
    header h1 {{ color:#58a6ff; margin:0; }}
    .stats {{ display:flex; gap:16px; padding:16px 24px; flex-wrap:wrap; }}
    .stat-card {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
                  padding:12px 20px; min-width:150px; }}
    .stat-card .label {{ color:#8b949e; font-size:0.75rem; text-transform:uppercase;
                         letter-spacing:0.05em; }}
    .stat-card .value {{ font-size:1.4rem; font-weight:700; color:#c9d1d9; }}
    main {{ padding:0 24px 24px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th, td {{ padding:8px 12px; text-align:left;
              border-bottom:1px solid #21262d; }}
    th {{ background:#161b22; color:#8b949e; font-size:0.75rem;
          text-transform:uppercase; letter-spacing:0.05em; position:sticky;
          top:0; }}
    tr:hover {{ background:#1c2128; }}
    a {{ color:#58a6ff; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
  </style>
</head>
<body>
<header>
  <h1>Trade Journal</h1>
  <div style="color:#8b949e;font-size:0.8rem;margin-top:4px">
    Auto-resolves expired trades nightly &nbsp;|&nbsp;
    <a href="/api/journal/report">JSON Report API</a>
  </div>
</header>
<div class="stats">
  <div class="stat-card">
    <div class="label">Total Trades</div>
    <div class="value">{report.total_entries}</div>
  </div>
  <div class="stat-card">
    <div class="label">Resolved</div>
    <div class="value">{report.resolved_entries}</div>
  </div>
  <div class="stat-card">
    <div class="label">Win Rate</div>
    <div class="value" style="color:#3fb950">{report.win_rate:.1%}</div>
  </div>
  <div class="stat-card">
    <div class="label">Avg PnL</div>
    <div class="value" style="color:{'#3fb950' if report.avg_pnl>=0 else '#f85149'}">
      {report.avg_pnl:+.1%}
    </div>
  </div>
</div>
<main>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Ticker</th><th>Strategy</th>
        <th>Entry</th><th>Expiry</th><th>Direction</th>
        <th>Confidence</th><th>Outcome</th><th>PnL Est.</th>
      </tr>
    </thead>
    <tbody>
      {rows_html if rows_html else '<tr><td colspan="9" style="text-align:center;color:#8b949e">No entries yet.</td></tr>'}
    </tbody>
  </table>
</main>
</body>
</html>"""
        return HTMLResponse(content=html)
