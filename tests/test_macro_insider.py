"""Tests for rot.macro.insider — InsiderFeed (SEC Form 4, query, cross-ref)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rot.macro.insider import InsiderFeed
from rot.macro.types import InsiderTrade


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_row(
    *,
    id: str = "t1",
    ticker: str = "AAPL",
    insider_name: str = "Tim Cook",
    trade_type: str = "buy",
    filing_date: float = 1700000000.0,
    source: str = "form4",
    title: str = "CEO",
    shares: int = 5000,
    price: float = 150.0,
    value: float = 750000.0,
    transaction_date: float | None = 1699999000.0,
    meta: str | dict = "{}",
) -> dict:
    """Build a DB-row dict suitable for _row_to_trade."""
    return {
        "id": id,
        "ticker": ticker,
        "insider_name": insider_name,
        "trade_type": trade_type,
        "filing_date": filing_date,
        "source": source,
        "title": title,
        "shares": shares,
        "price": price,
        "value": value,
        "transaction_date": transaction_date,
        "meta": meta,
    }


def _mock_db() -> AsyncMock:
    """Return an AsyncMock database with default empty return values."""
    db = AsyncMock()
    db.query_insider_trades = AsyncMock(return_value=[])
    db.get_signals_for_ticker = AsyncMock(return_value=[])
    db.upsert_insider_trade = AsyncMock()
    return db


def _mock_config(user_agent: str = "test-agent/1.0 test@example.com") -> MagicMock:
    cfg = MagicMock()
    cfg.sec_edgar_user_agent = user_agent
    return cfg


# ── 1. get_recent ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_recent_returns_trades():
    """get_recent converts DB rows to InsiderTrade objects."""
    db = _mock_db()
    db.query_insider_trades.return_value = [_make_row(), _make_row(id="t2", ticker="MSFT")]
    feed = InsiderFeed(db)

    result = await feed.get_recent(days=30)

    assert len(result) == 2
    assert all(isinstance(t, InsiderTrade) for t in result)
    assert result[0].ticker == "AAPL"
    assert result[1].ticker == "MSFT"
    db.query_insider_trades.assert_awaited_once()
    call_kwargs = db.query_insider_trades.call_args.kwargs
    assert call_kwargs["trade_type"] is None
    assert call_kwargs["source"] is None
    assert call_kwargs["order"] == "desc"


@pytest.mark.asyncio
async def test_get_recent_with_trade_type_filter():
    """get_recent passes trade_type to the DB query."""
    db = _mock_db()
    db.query_insider_trades.return_value = [_make_row(trade_type="sell")]
    feed = InsiderFeed(db)

    result = await feed.get_recent(days=14, trade_type="sell")

    assert len(result) == 1
    assert result[0].trade_type == "sell"
    call_kwargs = db.query_insider_trades.call_args.kwargs
    assert call_kwargs["trade_type"] == "sell"


@pytest.mark.asyncio
async def test_get_recent_with_source_filter():
    """get_recent passes source to the DB query."""
    db = _mock_db()
    db.query_insider_trades.return_value = [_make_row(source="congress")]
    feed = InsiderFeed(db)

    result = await feed.get_recent(days=7, source="congress")

    assert len(result) == 1
    assert result[0].source == "congress"
    call_kwargs = db.query_insider_trades.call_args.kwargs
    assert call_kwargs["source"] == "congress"


@pytest.mark.asyncio
async def test_get_recent_empty():
    """get_recent returns empty list when DB has no rows."""
    db = _mock_db()
    feed = InsiderFeed(db)

    result = await feed.get_recent()

    assert result == []


@pytest.mark.asyncio
async def test_get_recent_timestamp_range():
    """get_recent passes correct start_ts/end_ts window."""
    db = _mock_db()
    feed = InsiderFeed(db)

    before = time.time()
    await feed.get_recent(days=10)
    after = time.time()

    call_kwargs = db.query_insider_trades.call_args.kwargs
    assert before - 10 * 86400 <= call_kwargs["start_ts"] <= after - 10 * 86400
    assert before <= call_kwargs["end_ts"] <= after


# ── 2. get_by_ticker ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_by_ticker_returns_trades():
    """get_by_ticker queries for a specific ticker with limit."""
    db = _mock_db()
    db.query_insider_trades.return_value = [
        _make_row(id="t1"),
        _make_row(id="t2"),
    ]
    feed = InsiderFeed(db)

    result = await feed.get_by_ticker("AAPL", limit=25)

    assert len(result) == 2
    call_kwargs = db.query_insider_trades.call_args.kwargs
    assert call_kwargs["ticker"] == "AAPL"
    assert call_kwargs["limit"] == 25
    assert call_kwargs["order"] == "desc"


@pytest.mark.asyncio
async def test_get_by_ticker_empty():
    """get_by_ticker returns empty list for unknown ticker."""
    db = _mock_db()
    feed = InsiderFeed(db)

    result = await feed.get_by_ticker("ZZZZ")

    assert result == []


# ── 3. get_notable ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_notable_filters_by_min_value():
    """get_notable passes min_value to DB query."""
    db = _mock_db()
    db.query_insider_trades.return_value = [_make_row(value=500000.0)]
    feed = InsiderFeed(db)

    result = await feed.get_notable(min_value=200000, days=14)

    assert len(result) == 1
    assert result[0].value == 500000.0
    call_kwargs = db.query_insider_trades.call_args.kwargs
    assert call_kwargs["min_value"] == 200000
    assert call_kwargs["order"] == "desc"


@pytest.mark.asyncio
async def test_get_notable_empty():
    """get_notable returns empty when no large trades exist."""
    db = _mock_db()
    feed = InsiderFeed(db)

    result = await feed.get_notable(min_value=1_000_000)

    assert result == []


# ── 4. get_buys_only ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_buys_only_delegates_to_get_recent():
    """get_buys_only calls get_recent with trade_type='buy'."""
    db = _mock_db()
    db.query_insider_trades.return_value = [_make_row(trade_type="buy")]
    feed = InsiderFeed(db)

    result = await feed.get_buys_only(days=15)

    assert len(result) == 1
    assert result[0].trade_type == "buy"
    call_kwargs = db.query_insider_trades.call_args.kwargs
    assert call_kwargs["trade_type"] == "buy"


# ── 5. cross_reference_signals ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_reference_signals_finds_matches():
    """cross_reference_signals returns matches when insider buys align with bullish signals."""
    db = _mock_db()
    db.query_insider_trades.return_value = [_make_row(ticker="TSLA", trade_type="buy")]
    db.get_signals_for_ticker.return_value = [
        {"id": "sig1", "stance": "bullish", "confidence": 0.85, "created_at": 1700000000.0},
    ]
    feed = InsiderFeed(db)

    result = await feed.cross_reference_signals(days=7)

    assert len(result) == 1
    assert result[0]["ticker"] == "TSLA"
    assert result[0]["signal_id"] == "sig1"
    assert result[0]["signal_confidence"] == 0.85
    assert result[0]["alignment"] == "insider_buy + bullish_signal"
    assert isinstance(result[0]["insider_trade"], InsiderTrade)


@pytest.mark.asyncio
async def test_cross_reference_signals_no_insider_buys():
    """cross_reference_signals returns empty when no insider buys exist."""
    db = _mock_db()
    # get_recent with trade_type="buy" returns empty
    feed = InsiderFeed(db)

    result = await feed.cross_reference_signals(days=7)

    assert result == []
    # Should not even query signals
    db.get_signals_for_ticker.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_reference_signals_no_bullish_signals():
    """cross_reference_signals returns empty when signals exist but none are bullish."""
    db = _mock_db()
    db.query_insider_trades.return_value = [_make_row(ticker="NVDA", trade_type="buy")]
    db.get_signals_for_ticker.return_value = [
        {"id": "sig1", "stance": "bearish", "confidence": 0.7},
        {"id": "sig2", "stance": "neutral", "confidence": 0.5},
    ]
    feed = InsiderFeed(db)

    result = await feed.cross_reference_signals(days=7)

    assert result == []


@pytest.mark.asyncio
async def test_cross_reference_signals_multiple_tickers():
    """cross_reference_signals handles multiple tickers with insider buys."""
    db = _mock_db()
    db.query_insider_trades.return_value = [
        _make_row(id="t1", ticker="AAPL", trade_type="buy"),
        _make_row(id="t2", ticker="MSFT", trade_type="buy"),
    ]

    async def mock_signals(ticker, limit=10, days=7):
        if ticker == "AAPL":
            return [{"id": "s1", "stance": "bullish", "confidence": 0.9}]
        return [{"id": "s2", "stance": "bearish", "confidence": 0.6}]

    db.get_signals_for_ticker.side_effect = mock_signals
    feed = InsiderFeed(db)

    result = await feed.cross_reference_signals(days=7)

    # Only AAPL has a bullish match
    assert len(result) == 1
    assert result[0]["ticker"] == "AAPL"


# ── 6. ingest_form4 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_form4_skips_without_user_agent():
    """ingest_form4 returns 0 when no SEC user agent is configured."""
    db = _mock_db()
    feed = InsiderFeed(db, config=None)

    count = await feed.ingest_form4(tickers=["AAPL"])

    assert count == 0
    db.upsert_insider_trade.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_form4_skips_empty_user_agent():
    """ingest_form4 returns 0 when user agent is empty string."""
    db = _mock_db()
    cfg = _mock_config(user_agent="")
    feed = InsiderFeed(db, config=cfg)

    count = await feed.ingest_form4()

    assert count == 0


@pytest.mark.asyncio
async def test_ingest_form4_with_tickers_success():
    """ingest_form4 fetches and stores trades for given tickers."""
    db = _mock_db()
    cfg = _mock_config()
    feed = InsiderFeed(db, config=cfg)

    mock_trades = [
        InsiderTrade(
            id="form4-abc",
            ticker="AAPL",
            insider_name="Tim Cook",
            trade_type="buy",
            filing_date=1700000000.0,
            source="form4",
        ),
    ]

    with patch.object(feed, "_search_form4_ticker", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_trades
        count = await feed.ingest_form4(tickers=["AAPL"])

    assert count == 1
    db.upsert_insider_trade.assert_awaited_once_with(mock_trades[0])


@pytest.mark.asyncio
async def test_ingest_form4_no_tickers_general_search():
    """ingest_form4 without tickers does a general Form 4 search."""
    db = _mock_db()
    cfg = _mock_config()
    feed = InsiderFeed(db, config=cfg)

    mock_trades = [
        InsiderTrade(
            id="form4-xyz",
            ticker="GOOG",
            insider_name="Sundar Pichai",
            trade_type="buy",
            filing_date=1700000000.0,
            source="form4",
        ),
        InsiderTrade(
            id="form4-qrs",
            ticker="META",
            insider_name="Mark Zuckerberg",
            trade_type="sell",
            filing_date=1700001000.0,
            source="form4",
        ),
    ]

    with patch.object(feed, "_search_form4_recent", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_trades
        count = await feed.ingest_form4(tickers=None)

    assert count == 2
    assert db.upsert_insider_trade.await_count == 2


@pytest.mark.asyncio
async def test_ingest_form4_rate_limited_429():
    """ingest_form4 handles 429 rate-limiting gracefully by returning 0 trades."""
    db = _mock_db()
    cfg = _mock_config()
    feed = InsiderFeed(db, config=cfg)

    # _search_form4_ticker returns empty on 429
    with patch.object(feed, "_search_form4_ticker", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = []
        count = await feed.ingest_form4(tickers=["AAPL"])

    assert count == 0


@pytest.mark.asyncio
async def test_ingest_form4_ticker_search_exception():
    """ingest_form4 logs and continues when a ticker search raises an exception."""
    db = _mock_db()
    cfg = _mock_config()
    feed = InsiderFeed(db, config=cfg)

    with patch.object(feed, "_search_form4_ticker", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        count = await feed.ingest_form4(tickers=["BAD"])

    # Should not crash — logs and returns 0
    assert count == 0


# ── 7. ingest_congress ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_congress_returns_zero():
    """ingest_congress is a stub that always returns 0."""
    db = _mock_db()
    feed = InsiderFeed(db)

    count = await feed.ingest_congress()

    assert count == 0


# ── 8. _row_to_trade ───────────────────────────────────────────────────


def test_row_to_trade_normal():
    """_row_to_trade converts a DB row dict to InsiderTrade."""
    row = _make_row(meta='{"note": "cluster buy"}')
    trade = InsiderFeed._row_to_trade(row)

    assert isinstance(trade, InsiderTrade)
    assert trade.id == "t1"
    assert trade.ticker == "AAPL"
    assert trade.insider_name == "Tim Cook"
    assert trade.trade_type == "buy"
    assert trade.filing_date == 1700000000.0
    assert trade.source == "form4"
    assert trade.title == "CEO"
    assert trade.shares == 5000
    assert trade.price == 150.0
    assert trade.value == 750000.0
    assert trade.transaction_date == 1699999000.0
    assert trade.meta == {"note": "cluster buy"}


def test_row_to_trade_meta_as_json_string():
    """_row_to_trade parses meta from a JSON string."""
    row = _make_row(meta='{"form_type": "4", "filing_url": "https://sec.gov/x"}')
    trade = InsiderFeed._row_to_trade(row)

    assert trade.meta == {"form_type": "4", "filing_url": "https://sec.gov/x"}


def test_row_to_trade_meta_as_dict():
    """_row_to_trade handles meta already being a dict (not JSON string)."""
    row = _make_row(meta={"already": "parsed"})
    trade = InsiderFeed._row_to_trade(row)

    assert trade.meta == {"already": "parsed"}


def test_row_to_trade_meta_invalid_json():
    """_row_to_trade falls back to empty dict when meta is invalid JSON."""
    row = _make_row(meta="not-valid-json{{{")
    trade = InsiderFeed._row_to_trade(row)

    assert trade.meta == {}


def test_row_to_trade_missing_optional_fields():
    """_row_to_trade uses defaults for missing optional fields."""
    row = {
        "id": "t99",
        "ticker": "TSLA",
        "insider_name": "Elon Musk",
        "trade_type": "sell",
        "filing_date": 1700000000.0,
        "source": "form4",
        # title, shares, price, value, transaction_date, meta all missing
    }
    trade = InsiderFeed._row_to_trade(row)

    assert trade.title == ""
    assert trade.shares == 0
    assert trade.price == 0.0
    assert trade.value == 0.0
    assert trade.transaction_date is None
    assert trade.meta == {}


# ── 9. _parse_edgar_results ─────────────────────────────────────────────


def test_parse_edgar_results_normal():
    """_parse_edgar_results builds InsiderTrade list from EDGAR JSON."""
    db = _mock_db()
    feed = InsiderFeed(db)

    data = {
        "hits": {
            "hits": [
                {
                    "_id": "0001234-24-000001",
                    "_source": {
                        "file_date": "2024-11-15",
                        "display_names": ["Tim Cook"],
                        "tickers": ["AAPL"],
                        "file_url": "https://sec.gov/filing/1",
                        "form_type": "4",
                    },
                },
                {
                    "_id": "0001234-24-000002",
                    "_source": {
                        "file_date": "2024-11-14",
                        "display_names": ["Satya Nadella"],
                        "tickers": ["MSFT"],
                        "file_url": "https://sec.gov/filing/2",
                        "form_type": "4",
                    },
                },
            ]
        }
    }

    trades = feed._parse_edgar_results(data)

    assert len(trades) == 2
    assert trades[0].id == "form4-0001234-24-000001"
    assert trades[0].ticker == "AAPL"
    assert trades[0].insider_name == "Tim Cook"
    assert trades[0].trade_type == "buy"
    assert trades[0].source == "form4"
    assert trades[0].meta["filing_url"] == "https://sec.gov/filing/1"
    assert trades[1].ticker == "MSFT"
    assert trades[1].insider_name == "Satya Nadella"


def test_parse_edgar_results_with_ticker_override():
    """_parse_edgar_results uses provided ticker when source has none."""
    db = _mock_db()
    feed = InsiderFeed(db)

    data = {
        "hits": {
            "hits": [
                {
                    "_id": "abc123",
                    "_source": {
                        "file_date": "2024-11-10",
                        "display_names": ["Jane Doe"],
                        "tickers": [],
                    },
                },
            ]
        }
    }

    trades = feed._parse_edgar_results(data, ticker="GOOG")

    assert len(trades) == 1
    assert trades[0].ticker == "GOOG"


def test_parse_edgar_results_empty_hits():
    """_parse_edgar_results returns empty list when no hits."""
    db = _mock_db()
    feed = InsiderFeed(db)

    assert feed._parse_edgar_results({"hits": {"hits": []}}) == []
    assert feed._parse_edgar_results({}) == []
    assert feed._parse_edgar_results({"hits": {}}) == []


def test_parse_edgar_results_missing_fields():
    """_parse_edgar_results handles entries with missing optional fields."""
    db = _mock_db()
    feed = InsiderFeed(db)

    data = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "file_date": "2024-11-10",
                        "display_names": [],
                        "tickers": ["XYZ"],
                        # file_url missing
                    },
                    # _id missing
                },
            ]
        }
    }

    trades = feed._parse_edgar_results(data)

    assert len(trades) == 1
    assert trades[0].ticker == "XYZ"
    assert trades[0].insider_name == "Unknown"
    assert trades[0].meta["filing_url"] == ""


def test_parse_edgar_results_skips_no_ticker():
    """_parse_edgar_results skips entries without any ticker (and no override)."""
    db = _mock_db()
    feed = InsiderFeed(db)

    data = {
        "hits": {
            "hits": [
                {
                    "_id": "no-ticker",
                    "_source": {
                        "file_date": "2024-11-10",
                        "display_names": ["Nobody"],
                        "tickers": [],
                    },
                },
            ]
        }
    }

    trades = feed._parse_edgar_results(data, ticker=None)

    assert trades == []


def test_parse_edgar_results_invalid_date():
    """_parse_edgar_results falls back to current time for unparseable dates."""
    db = _mock_db()
    feed = InsiderFeed(db)

    data = {
        "hits": {
            "hits": [
                {
                    "_id": "bad-date",
                    "_source": {
                        "file_date": "not-a-date",
                        "display_names": ["Test"],
                        "tickers": ["TEST"],
                    },
                },
            ]
        }
    }

    before = time.time()
    trades = feed._parse_edgar_results(data)
    after = time.time()

    assert len(trades) == 1
    # Falls back to time.time() for invalid date
    assert before <= trades[0].filing_date <= after


# ── Init tests ──────────────────────────────────────────────────────────


def test_init_no_config():
    """InsiderFeed with no config sets empty user agent."""
    db = _mock_db()
    feed = InsiderFeed(db, config=None)

    assert feed._user_agent == ""


def test_init_with_config():
    """InsiderFeed extracts sec_edgar_user_agent from config."""
    db = _mock_db()
    cfg = _mock_config("MyApp/1.0 admin@example.com")
    feed = InsiderFeed(db, config=cfg)

    assert feed._user_agent == "MyApp/1.0 admin@example.com"


def test_init_config_missing_attribute():
    """InsiderFeed handles config without sec_edgar_user_agent gracefully."""
    db = _mock_db()
    cfg = MagicMock(spec=[])  # no attributes at all
    feed = InsiderFeed(db, config=cfg)

    assert feed._user_agent == ""
