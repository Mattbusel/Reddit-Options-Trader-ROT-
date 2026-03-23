"""Options chain analytics routes.

GET /api/v1/options/chain/:ticker — full chain analytics JSON
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/v1/options/chain/{ticker}")
async def get_options_chain(
    ticker: str = Path(..., description="Ticker symbol, e.g. AAPL"),
    expiry_days: int = Query(30, ge=1, le=365, description="Target days to expiry"),
) -> JSONResponse:
    """Fetch full options chain analytics for *ticker*.

    Returns max-pain price, put/call ratio, IV skew, and the raw call/put
    quotes for the expiry nearest to *expiry_days* from today.

    Args:
        ticker: Ticker symbol.
        expiry_days: Target days to expiry (default 30).

    Returns:
        JSON body with keys: ``ticker``, ``spot_price``, ``expiry``,
        ``max_pain``, ``put_call_ratio``, ``skew``, ``calls``, ``puts``.
    """
    try:
        from rot.analytics.chain_analyzer import ChainAnalyzer
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    analyzer = ChainAnalyzer()

    try:
        snapshot = analyzer.fetch_chain(ticker.upper(), expiry_target_days=expiry_days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        log.exception("Error fetching chain for %s: %s", ticker, exc)
        raise HTTPException(status_code=502, detail=f"Failed to fetch chain: {exc}")

    try:
        mp = analyzer.max_pain(snapshot)
    except Exception:
        mp = None

    try:
        pcr = analyzer.put_call_ratio(snapshot)
    except Exception:
        pcr = None

    try:
        sk = analyzer.skew(snapshot)
    except Exception:
        sk = None

    def _quote_dict(q) -> Dict[str, Any]:
        return {
            "strike": q.strike,
            "bid": q.bid,
            "ask": q.ask,
            "mid": q.mid,
            "iv": q.iv,
            "delta": q.delta,
            "gamma": q.gamma,
            "theta": q.theta,
            "open_interest": q.open_interest,
            "volume": q.volume,
        }

    return JSONResponse(
        {
            "ticker": snapshot.ticker,
            "spot_price": snapshot.spot_price,
            "expiry": snapshot.expiry.isoformat(),
            "timestamp": snapshot.timestamp,
            "max_pain": mp,
            "put_call_ratio": pcr,
            "skew": sk,
            "calls": [_quote_dict(q) for q in snapshot.calls],
            "puts": [_quote_dict(q) for q in snapshot.puts],
        }
    )
