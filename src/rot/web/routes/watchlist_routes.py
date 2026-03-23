"""Watchlist routes for ROT.

HTML page:
    GET  /watchlist                         — watchlist dashboard

JSON API:
    GET  /api/v1/watchlist                  — list all items
    POST /api/v1/watchlist                  — add an item
    DELETE /api/v1/watchlist/{ticker}       — remove an item
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class WatchlistItemIn(BaseModel):
    """Payload for adding a watchlist item."""

    ticker: str
    tags: List[str] = []
    notes: str = ""
    alert_price: Optional[float] = None


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------


@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(request: Request) -> HTMLResponse:
    """Render the watchlist dashboard HTML page."""
    try:
        from rot.watchlist import Watchlist
        wl: Watchlist = request.app.state.watchlist
        items = await wl.list()
    except AttributeError:
        items = []
    except Exception as exc:
        log.warning("Error loading watchlist: %s", exc)
        items = []

    rows_html = "".join(
        f"<tr><td>{i.ticker}</td><td>{i.added_date}</td>"
        f"<td>{', '.join(i.tags)}</td><td>{i.notes}</td>"
        f"<td>{i.alert_price if i.alert_price is not None else '—'}</td></tr>"
        for i in items
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Watchlist — ROT</title>
<style>
  body{{font-family:sans-serif;margin:2rem;}}
  table{{border-collapse:collapse;width:100%;}}
  th,td{{border:1px solid #ccc;padding:0.5rem 1rem;text-align:left;}}
  th{{background:#f4f4f4;}}
</style>
</head>
<body>
<h1>Watchlist</h1>
<table>
  <thead><tr><th>Ticker</th><th>Added</th><th>Tags</th>
  <th>Notes</th><th>Alert Price</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
<p><a href="/api/v1/watchlist">JSON API</a></p>
</body>
</html>"""
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------


@router.get("/api/v1/watchlist")
async def list_watchlist(request: Request) -> JSONResponse:
    """Return all watchlist items as JSON."""
    try:
        wl = request.app.state.watchlist
        items = await wl.list()
    except AttributeError:
        raise HTTPException(status_code=503, detail="Watchlist not initialised")
    except Exception as exc:
        log.exception("Error listing watchlist: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return JSONResponse([_item_dict(i) for i in items])


@router.post("/api/v1/watchlist", status_code=201)
async def add_watchlist_item(
    request: Request, body: WatchlistItemIn
) -> JSONResponse:
    """Add a new item to the watchlist.

    Returns the stored item as JSON with HTTP 201.
    """
    try:
        from rot.watchlist import Watchlist, WatchlistItem

        wl: Watchlist = request.app.state.watchlist
        item = WatchlistItem(
            ticker=body.ticker.upper(),
            tags=body.tags,
            notes=body.notes,
            alert_price=body.alert_price,
        )
        await wl.add(item)
    except AttributeError:
        raise HTTPException(status_code=503, detail="Watchlist not initialised")
    except Exception as exc:
        log.exception("Error adding watchlist item: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return JSONResponse(_item_dict(item), status_code=201)


@router.delete("/api/v1/watchlist/{ticker}")
async def remove_watchlist_item(
    request: Request,
    ticker: str = Path(..., description="Ticker to remove"),
) -> JSONResponse:
    """Remove a ticker from the watchlist.

    Returns ``{"deleted": true}`` on success, 404 if not found.
    """
    try:
        wl = request.app.state.watchlist
        deleted = await wl.remove(ticker.upper())
    except AttributeError:
        raise HTTPException(status_code=503, detail="Watchlist not initialised")
    except Exception as exc:
        log.exception("Error removing watchlist item: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not in watchlist")

    return JSONResponse({"deleted": True, "ticker": ticker.upper()})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item_dict(item) -> Dict[str, Any]:
    return {
        "ticker": item.ticker,
        "added_date": item.added_date,
        "tags": item.tags,
        "notes": item.notes,
        "alert_price": item.alert_price,
    }
