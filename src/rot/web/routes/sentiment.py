"""Sentiment Heatmap — Reddit sentiment across tickers over time."""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web import tier_gate

router = APIRouter()


def _base_context(request: Request, user: dict | None) -> dict:
    tier = (user or {}).get("tier", "free")
    badge_map = {
        "free": "bg-gray-700 text-gray-300",
        "pro": "bg-blue-700/60 text-blue-200",
        "premium": "bg-purple-700/60 text-purple-200",
        "ultra": "bg-orange-700/60 text-orange-200",
    }
    return {
        "request": request,
        "user": user,
        "tier": tier,
        "tier_badge_class": badge_map.get(tier, badge_map["free"]),
        "stripe_enabled": bool(request.app.state.settings.stripe.secret_key),
    }


def _time_label(ts: float, bucket_s: int) -> str:
    """Format a time bucket for display."""
    import datetime
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    if bucket_s <= 3600:
        return dt.strftime("%H:%M")
    elif bucket_s <= 14400:
        return dt.strftime("%m/%d %H:%M")
    else:
        return dt.strftime("%m/%d")


@router.get("/sentiment", response_class=HTMLResponse)
async def sentiment_heatmap(request: Request, hours: str = "24"):
    """Sentiment Heatmap — Reddit sentiment across tickers over time."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)
    tier = ctx["tier"]

    access = tier_gate.gate_sentiment_access(tier)
    hours_int = min(int(hours) if hours.isdigit() else 24, access["max_hours"])

    db = request.app.state.db
    raw_data = await db.get_sentiment_heatmap(
        hours=hours_int,
        ticker_limit=access["max_tickers"],
    )

    # Build the heatmap grid: {ticker: {time_bucket: {bullish, bearish, mixed, count, confidence}}}
    ticker_data = defaultdict(dict)
    all_buckets = set()
    ticker_counts = defaultdict(int)

    for row in raw_data:
        t = row["ticker"]
        bucket = row["time_bucket"]
        ticker_counts[t] += row["signal_count"]
        all_buckets.add(bucket)

        bull = row["bullish"]
        bear = row["bearish"]
        total = row["signal_count"]

        if bull > bear:
            sentiment = "bullish"
        elif bear > bull:
            sentiment = "bearish"
        elif bull > 0 and bear > 0:
            sentiment = "mixed"
        else:
            sentiment = "neutral"

        ticker_data[t][bucket] = {
            "sentiment": sentiment,
            "count": total,
            "confidence": round(row["avg_confidence"], 2),
            "bullish": bull,
            "bearish": bear,
        }

    # Sort tickers by total signal count (most active first), limit to tier max
    top_tickers = sorted(ticker_counts.keys(), key=lambda t: ticker_counts[t], reverse=True)
    top_tickers = top_tickers[:access["max_tickers"]]

    # Sort time buckets
    sorted_buckets = sorted(all_buckets)

    # Determine bucket size for labels
    if hours_int <= 24:
        bucket_s = 3600
    elif hours_int <= 168:
        bucket_s = 14400
    else:
        bucket_s = 86400

    bucket_labels = [_time_label(b, bucket_s) for b in sorted_buckets]

    # Hottest right now: tickers with most signals in latest 2 buckets
    recent_buckets = sorted_buckets[-2:] if len(sorted_buckets) >= 2 else sorted_buckets
    hot_now = []
    for t in top_tickers[:20]:
        recent_count = sum(
            ticker_data[t].get(b, {}).get("count", 0)
            for b in recent_buckets
        )
        if recent_count > 0:
            hot_now.append({"ticker": t, "count": recent_count})
    hot_now.sort(key=lambda x: x["count"], reverse=True)

    # Time range options
    time_options = [
        {"value": "24", "label": "24h", "min_tier": "free"},
        {"value": "168", "label": "7d", "min_tier": "pro"},
        {"value": "720", "label": "30d", "min_tier": "premium"},
        {"value": "2160", "label": "90d", "min_tier": "ultra"},
    ]

    ctx.update({
        "tickers": top_tickers,
        "buckets": sorted_buckets,
        "bucket_labels": bucket_labels,
        "ticker_data": dict(ticker_data),
        "hot_now": hot_now[:5],
        "total_tickers": len(top_tickers),
        "total_signals": sum(ticker_counts.values()),
        "selected_hours": str(hours_int),
        "time_options": time_options,
        "access": access,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("sentiment.html", ctx)
