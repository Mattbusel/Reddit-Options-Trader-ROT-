from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from rot.web.auth import require_tier

router = APIRouter()


@router.get("/signals/export")
async def export_signals(
    request: Request,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    ticker: Optional[str] = None,
    stance: Optional[str] = None,
    min_confidence: Optional[float] = None,
    event_type: Optional[str] = None,
):
    """Export signals as CSV. Requires Pro tier or higher."""
    user = await require_tier("pro", "premium", "ultra")(request)

    db = request.app.state.db
    signals = await db.get_signals(
        limit=limit,
        offset=offset,
        ticker=ticker,
        stance=stance,
        min_confidence=min_confidence,
        event_type=event_type,
    )

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    headers = [
        "id", "ticker", "stance", "event_type", "confidence", "trend_score",
        "quality_score", "strategy", "subreddit", "post_title", "thesis",
        "created_at",
    ]

    # Premium/Ultra get extra columns
    if user["tier"] in ("premium", "ultra"):
        headers.extend(["catalyst_window", "risk_notes", "trade_legs", "max_loss"])

    writer.writerow(headers)

    for s in signals:
        reasoning = s.get("reasoning", {}) or {}
        idea = s.get("trade_idea", {}) or {}
        created_dt = ""
        if s.get("created_at"):
            created_dt = datetime.fromtimestamp(
                s["created_at"], tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")

        row = [
            s.get("id", ""),
            s.get("ticker", ""),
            s.get("stance", ""),
            s.get("event_type", ""),
            f"{s.get('confidence', 0):.2f}",
            f"{s.get('trend_score', 0):.4f}",
            f"{s.get('quality_score', 0):.2f}",
            s.get("strategy", ""),
            s.get("subreddit", ""),
            s.get("post_title", ""),
            reasoning.get("thesis", ""),
            created_dt,
        ]

        if user["tier"] in ("premium", "ultra"):
            legs = idea.get("legs", [])
            legs_str = "; ".join(
                f"{l.get('side','').upper()} {l.get('kind','').upper()} "
                f"${l.get('strike',0):.0f} exp {l.get('expiry','')}"
                for l in legs
            ) if legs else ""
            row.extend([
                reasoning.get("catalyst_window", ""),
                "; ".join(reasoning.get("risk_notes", [])),
                legs_str,
                f"{idea.get('max_loss', 0):.2f}" if idea.get("max_loss") else "",
            ])

        writer.writerow(row)

    output.seek(0)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"rot_signals_{date_str}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
