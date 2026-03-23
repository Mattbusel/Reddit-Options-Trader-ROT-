"""Persistent watchlist manager for ROT.

Stores user-defined watchlist items in SQLite via aiosqlite and exposes
async CRUD operations plus price-alert checking.

Example::

    import asyncio
    from rot.watchlist import Watchlist, WatchlistItem

    async def main():
        wl = Watchlist("watchlist.db")
        await wl.init()
        await wl.add(WatchlistItem(ticker="AAPL", tags=["tech"], notes="",
                                   alert_price=180.0))
        items = await wl.list()
        alerts = await wl.check_alerts({"AAPL": 175.0})

    asyncio.run(main())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class WatchlistItem:
    """A single entry in the persistent watchlist.

    Attributes:
        ticker: Ticker symbol (e.g. ``"AAPL"``).
        added_date: ISO date string when the item was added.
        tags: Arbitrary string tags for filtering.
        notes: Free-text notes.
        alert_price: Optional price level at which an alert fires.  The alert
            triggers when the current price is at or below this level (i.e.
            the price has *crossed down through* alert_price, useful for
            buy-the-dip alerts).  ``None`` disables alerts for this item.
    """

    ticker: str
    added_date: str = field(default_factory=lambda: date.today().isoformat())
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    alert_price: Optional[float] = None


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


class Watchlist:
    """SQLite-backed persistent watchlist.

    Args:
        db_path: Path to the SQLite database file.  Defaults to
            ``"watchlist.db"`` in the current directory.
    """

    def __init__(self, db_path: str = "watchlist.db") -> None:
        self._db_path = db_path
        self._db: Optional[object] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Open the database connection and create the schema if needed."""
        try:
            import aiosqlite  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "aiosqlite is required for Watchlist. "
                "Install it with: pip install aiosqlite"
            ) from exc

        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker      TEXT PRIMARY KEY,
                added_date  TEXT NOT NULL,
                tags        TEXT NOT NULL DEFAULT '',
                notes       TEXT NOT NULL DEFAULT '',
                alert_price REAL
            )
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def add(self, item: WatchlistItem) -> None:
        """Insert or replace a watchlist item.

        Args:
            item: :class:`WatchlistItem` to persist.
        """
        self._require_init()
        tags_str = ",".join(item.tags)
        await self._db.execute(  # type: ignore[union-attr]
            """
            INSERT INTO watchlist (ticker, added_date, tags, notes, alert_price)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                added_date  = excluded.added_date,
                tags        = excluded.tags,
                notes       = excluded.notes,
                alert_price = excluded.alert_price
            """,
            (item.ticker, item.added_date, tags_str, item.notes, item.alert_price),
        )
        await self._db.commit()  # type: ignore[union-attr]

    async def remove(self, ticker: str) -> bool:
        """Remove an item from the watchlist.

        Args:
            ticker: Ticker symbol to remove.

        Returns:
            ``True`` if a row was deleted, ``False`` if the ticker was not found.
        """
        self._require_init()
        cursor = await self._db.execute(  # type: ignore[union-attr]
            "DELETE FROM watchlist WHERE ticker = ?", (ticker,)
        )
        await self._db.commit()  # type: ignore[union-attr]
        return cursor.rowcount > 0

    async def list(self) -> List[WatchlistItem]:
        """Return all watchlist items ordered by added_date descending.

        Returns:
            List of :class:`WatchlistItem`.
        """
        self._require_init()
        cursor = await self._db.execute(  # type: ignore[union-attr]
            "SELECT ticker, added_date, tags, notes, alert_price "
            "FROM watchlist ORDER BY added_date DESC"
        )
        rows = await cursor.fetchall()
        return [_row_to_item(r) for r in rows]

    async def get(self, ticker: str) -> Optional[WatchlistItem]:
        """Fetch a single item by ticker.

        Args:
            ticker: Ticker symbol.

        Returns:
            :class:`WatchlistItem` or ``None`` if not found.
        """
        self._require_init()
        cursor = await self._db.execute(  # type: ignore[union-attr]
            "SELECT ticker, added_date, tags, notes, alert_price "
            "FROM watchlist WHERE ticker = ?",
            (ticker,),
        )
        row = await cursor.fetchone()
        return _row_to_item(row) if row else None

    async def tag_filter(self, tag: str) -> List[WatchlistItem]:
        """Return items that have *tag* in their tag list.

        Uses a substring match on the serialised tag string for simplicity.

        Args:
            tag: Tag string to filter by.

        Returns:
            List of :class:`WatchlistItem` that contain the tag.
        """
        all_items = await self.list()
        return [item for item in all_items if tag in item.tags]

    # ------------------------------------------------------------------
    # Alert checking
    # ------------------------------------------------------------------

    async def check_alerts(self, prices: Dict[str, float]) -> List[WatchlistItem]:
        """Return watchlist items whose current price is at or below alert_price.

        Args:
            prices: Current prices as ``{ticker: price}``.

        Returns:
            List of :class:`WatchlistItem` where
            ``prices[ticker] <= item.alert_price``.
        """
        all_items = await self.list()
        triggered: List[WatchlistItem] = []
        for item in all_items:
            if item.alert_price is None:
                continue
            current = prices.get(item.ticker)
            if current is not None and current <= item.alert_price:
                triggered.append(item)
        return triggered

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _require_init(self) -> None:
        if self._db is None:
            raise RuntimeError(
                "Watchlist not initialised. Call `await watchlist.init()` first."
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_item(row: tuple) -> WatchlistItem:
    """Convert a DB row tuple to a :class:`WatchlistItem`."""
    ticker, added_date, tags_str, notes, alert_price = row
    tags = [t for t in tags_str.split(",") if t] if tags_str else []
    return WatchlistItem(
        ticker=ticker,
        added_date=added_date,
        tags=tags,
        notes=notes or "",
        alert_price=float(alert_price) if alert_price is not None else None,
    )
