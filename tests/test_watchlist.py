"""Unit tests for rot.watchlist — 15+ test cases."""

from __future__ import annotations

import asyncio
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest_plugins = ("pytest_asyncio",)

# ---------------------------------------------------------------------------
# Conditional skip if aiosqlite not installed
# ---------------------------------------------------------------------------
aiosqlite = pytest.importorskip("aiosqlite", reason="aiosqlite not installed")

from rot.watchlist import Watchlist, WatchlistItem, _row_to_item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
async def wl(tmp_path):
    """In-memory watchlist backed by a temp SQLite file."""
    db_path = str(tmp_path / "test_watchlist.db")
    watchlist = Watchlist(db_path)
    await watchlist.init()
    yield watchlist
    await watchlist.close()


def make_item(
    ticker: str = "AAPL",
    tags: list | None = None,
    notes: str = "",
    alert_price: float | None = None,
) -> WatchlistItem:
    return WatchlistItem(
        ticker=ticker,
        tags=tags or [],
        notes=notes,
        alert_price=alert_price,
    )


# ---------------------------------------------------------------------------
# WatchlistItem tests
# ---------------------------------------------------------------------------

class TestWatchlistItem:
    def test_default_fields(self):
        item = WatchlistItem(ticker="TSLA")
        assert item.ticker == "TSLA"
        assert item.tags == []
        assert item.notes == ""
        assert item.alert_price is None

    def test_with_all_fields(self):
        item = WatchlistItem(
            ticker="SPY",
            added_date="2024-01-15",
            tags=["etf", "index"],
            notes="broad market",
            alert_price=450.0,
        )
        assert item.tags == ["etf", "index"]
        assert item.alert_price == pytest.approx(450.0)


# ---------------------------------------------------------------------------
# _row_to_item helper
# ---------------------------------------------------------------------------

class TestRowToItem:
    def test_basic_conversion(self):
        row = ("AAPL", "2024-01-01", "tech,growth", "A note", 150.0)
        item = _row_to_item(row)
        assert item.ticker == "AAPL"
        assert item.tags == ["tech", "growth"]
        assert item.alert_price == pytest.approx(150.0)

    def test_empty_tags(self):
        row = ("MSFT", "2024-01-01", "", "", None)
        item = _row_to_item(row)
        assert item.tags == []
        assert item.alert_price is None


# ---------------------------------------------------------------------------
# Watchlist CRUD tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWatchlistCRUD:
    async def test_add_and_list(self, wl):
        await wl.add(make_item("AAPL", tags=["tech"]))
        items = await wl.list()
        assert len(items) == 1
        assert items[0].ticker == "AAPL"

    async def test_add_multiple(self, wl):
        await wl.add(make_item("AAPL"))
        await wl.add(make_item("MSFT"))
        items = await wl.list()
        tickers = {i.ticker for i in items}
        assert tickers == {"AAPL", "MSFT"}

    async def test_remove_existing(self, wl):
        await wl.add(make_item("AAPL"))
        deleted = await wl.remove("AAPL")
        assert deleted is True
        items = await wl.list()
        assert items == []

    async def test_remove_nonexistent(self, wl):
        deleted = await wl.remove("NONEXISTENT")
        assert deleted is False

    async def test_get_existing(self, wl):
        await wl.add(make_item("TSLA", notes="EV play"))
        item = await wl.get("TSLA")
        assert item is not None
        assert item.notes == "EV play"

    async def test_get_nonexistent(self, wl):
        item = await wl.get("NONEXISTENT")
        assert item is None

    async def test_add_overwrites_existing(self, wl):
        await wl.add(make_item("AAPL", alert_price=150.0))
        await wl.add(make_item("AAPL", alert_price=180.0))  # upsert
        item = await wl.get("AAPL")
        assert item is not None
        assert item.alert_price == pytest.approx(180.0)
        items = await wl.list()
        assert len(items) == 1

    async def test_tags_persisted(self, wl):
        await wl.add(make_item("NVDA", tags=["ai", "semiconductor"]))
        item = await wl.get("NVDA")
        assert item is not None
        assert "ai" in item.tags
        assert "semiconductor" in item.tags

    async def test_alert_price_none_persisted(self, wl):
        await wl.add(make_item("AMD", alert_price=None))
        item = await wl.get("AMD")
        assert item is not None
        assert item.alert_price is None


# ---------------------------------------------------------------------------
# tag_filter tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestTagFilter:
    async def test_filter_by_tag(self, wl):
        await wl.add(make_item("AAPL", tags=["tech", "growth"]))
        await wl.add(make_item("MSFT", tags=["tech"]))
        await wl.add(make_item("XOM", tags=["energy"]))
        tech = await wl.tag_filter("tech")
        tickers = {i.ticker for i in tech}
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert "XOM" not in tickers

    async def test_filter_no_match(self, wl):
        await wl.add(make_item("AAPL", tags=["tech"]))
        result = await wl.tag_filter("energy")
        assert result == []


# ---------------------------------------------------------------------------
# check_alerts tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCheckAlerts:
    async def test_alert_triggers_at_or_below_price(self, wl):
        await wl.add(make_item("AAPL", alert_price=180.0))
        # price at exactly alert_price
        triggered = await wl.check_alerts({"AAPL": 180.0})
        assert len(triggered) == 1

    async def test_alert_triggers_below_price(self, wl):
        await wl.add(make_item("AAPL", alert_price=180.0))
        triggered = await wl.check_alerts({"AAPL": 175.0})
        assert len(triggered) == 1
        assert triggered[0].ticker == "AAPL"

    async def test_alert_does_not_trigger_above_price(self, wl):
        await wl.add(make_item("AAPL", alert_price=180.0))
        triggered = await wl.check_alerts({"AAPL": 185.0})
        assert triggered == []

    async def test_no_alert_price_never_triggers(self, wl):
        await wl.add(make_item("AAPL", alert_price=None))
        triggered = await wl.check_alerts({"AAPL": 1.0})
        assert triggered == []

    async def test_missing_price_no_trigger(self, wl):
        await wl.add(make_item("AAPL", alert_price=180.0))
        triggered = await wl.check_alerts({})
        assert triggered == []

    async def test_multiple_alerts(self, wl):
        await wl.add(make_item("AAPL", alert_price=180.0))
        await wl.add(make_item("MSFT", alert_price=400.0))
        await wl.add(make_item("NVDA", alert_price=500.0))
        triggered = await wl.check_alerts({"AAPL": 175.0, "MSFT": 410.0, "NVDA": 495.0})
        tickers = {i.ticker for i in triggered}
        assert "AAPL" in tickers
        assert "NVDA" in tickers
        assert "MSFT" not in tickers


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestWatchlistErrors:
    def test_operations_before_init_raise(self):
        wl = Watchlist(":memory:")

        async def run():
            with pytest.raises(RuntimeError, match="not initialised"):
                await wl.list()

        asyncio.run(run())
