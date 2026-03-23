"""Signal Quality API -- JSON endpoints for programmatic access.

Provides ``GET /api/v1/signals/quality`` which returns a
:class:`SignalQualityReport` with accuracy statistics and per-ticker
performance breakdowns.

The endpoint is gated at the Pro tier and above.

Example response::

    {
        "total_signals": 412,
        "decided_signals": 318,
        "accuracy_pct": 61.3,
        "avg_return_if_followed": 2.14,
        "top_tickers": [{"ticker": "NVDA", "win_rate": 0.78, "count": 23}],
        "worst_tickers": [{"ticker": "TSLA", "win_rate": 0.31, "count": 16}],
        "by_strategy": {"debit_spread": {"win_rate": 0.60, "count": 89}},
        "by_stance": {"bullish": {"win_rate": 0.63, "count": 210}},
        "computed_at": "2026-03-22T10:30:00+00:00"
    }
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from rot.web.auth import get_current_user_optional
from rot.web.rate_limit import rate_limit_headers
from rot.web.tier_gate import gate_signal_quality_access

log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# SignalQualityReport
# ---------------------------------------------------------------------------


def _build_report(results: dict[str, Any]) -> dict[str, Any]:
    """Transform raw feedback-analysis results into the SignalQualityReport format.

    Args:
        results: Raw dict from ``FeedbackAnalyzer.get_cached_results()``
            (or equivalent).

    Returns:
        Flat dictionary matching the SignalQualityReport schema.
    """
    category_perf: list[dict] = results.get("category_performance", [])
    source_rel: list[dict] = results.get("source_reliability", [])

    # Aggregate totals across all categories
    total_signals = sum(row.get("total", 0) for row in category_perf)
    decided_signals = sum(row.get("decided", 0) for row in category_perf)
    total_wins = sum(
        int(row.get("decided", 0) * row.get("win_rate", 0.0))
        for row in category_perf
        if row.get("decided", 0) > 0
    )
    accuracy_pct = round(
        (total_wins / decided_signals * 100) if decided_signals > 0 else 0.0, 2
    )

    # Per-ticker breakdown
    ticker_stats: dict[str, dict] = {}
    for row in category_perf:
        ticker = row.get("ticker") or row.get("entity") or row.get("category", "")
        if not ticker:
            continue
        if ticker not in ticker_stats:
            ticker_stats[ticker] = {"ticker": ticker, "wins": 0, "total": 0}
        decided = row.get("decided", 0)
        win_rate = row.get("win_rate", 0.0)
        wins = int(decided * win_rate) if decided > 0 else 0
        ticker_stats[ticker]["total"] += decided
        ticker_stats[ticker]["wins"] += wins

    ticker_list = [
        {
            "ticker": v["ticker"],
            "win_rate": round(v["wins"] / v["total"], 4) if v["total"] > 0 else 0.0,
            "count": v["total"],
        }
        for v in ticker_stats.values()
        if v["total"] >= 3  # minimum sample threshold
    ]
    ticker_list_sorted = sorted(ticker_list, key=lambda x: x["win_rate"], reverse=True)
    top_tickers = ticker_list_sorted[:10]
    worst_tickers = list(reversed(ticker_list_sorted[-10:]))

    # Per-strategy breakdown
    by_strategy: dict[str, dict] = {}
    for row in category_perf:
        strategy = row.get("strategy", "unknown") or "unknown"
        if strategy not in by_strategy:
            by_strategy[strategy] = {"wins": 0, "total": 0}
        decided = row.get("decided", 0)
        wr = row.get("win_rate", 0.0)
        by_strategy[strategy]["total"] += decided
        by_strategy[strategy]["wins"] += int(decided * wr)

    strategy_summary = {
        k: {
            "win_rate": round(v["wins"] / v["total"], 4) if v["total"] > 0 else 0.0,
            "count": v["total"],
        }
        for k, v in by_strategy.items()
        if v["total"] > 0
    }

    # Per-stance breakdown
    by_stance: dict[str, dict] = {}
    for row in category_perf:
        stance = row.get("stance", "unknown") or "unknown"
        if stance not in by_stance:
            by_stance[stance] = {"wins": 0, "total": 0}
        decided = row.get("decided", 0)
        wr = row.get("win_rate", 0.0)
        by_stance[stance]["total"] += decided
        by_stance[stance]["wins"] += int(decided * wr)

    stance_summary = {
        k: {
            "win_rate": round(v["wins"] / v["total"], 4) if v["total"] > 0 else 0.0,
            "count": v["total"],
        }
        for k, v in by_stance.items()
        if v["total"] > 0
    }

    # Source reliability summary
    source_summary = [
        {
            "source": row.get("source", "unknown"),
            "win_rate": round(row.get("win_rate", 0.0), 4),
            "count": row.get("decided", 0),
            "avg_confidence": round(row.get("avg_confidence", 0.0), 4),
        }
        for row in source_rel
        if row.get("decided", 0) >= 3
    ]

    # Average return heuristic: use calibration data if available
    calibration = results.get("calibration_detailed", [])
    avg_return: float = 0.0
    if calibration:
        returns = [c.get("avg_return", 0.0) for c in calibration if c.get("avg_return") is not None]
        if returns:
            avg_return = round(sum(returns) / len(returns), 4)

    return {
        "total_signals": total_signals,
        "decided_signals": decided_signals,
        "accuracy_pct": accuracy_pct,
        "avg_return_if_followed": avg_return,
        "top_tickers": top_tickers,
        "worst_tickers": worst_tickers,
        "by_strategy": strategy_summary,
        "by_stance": stance_summary,
        "source_reliability": source_summary[:20],
        "computed_at": results.get("computed_at") or datetime.now(timezone.utc).isoformat(),
    }


def _empty_report() -> dict[str, Any]:
    """Return a structurally-valid but empty SignalQualityReport."""
    return {
        "total_signals": 0,
        "decided_signals": 0,
        "accuracy_pct": 0.0,
        "avg_return_if_followed": 0.0,
        "top_tickers": [],
        "worst_tickers": [],
        "by_strategy": {},
        "by_stance": {},
        "source_reliability": [],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "note": "Analysis engine is computing results; please check back in a few minutes.",
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/signals/quality")
async def get_signal_quality(
    request: Request,
    min_sample: int = Query(
        default=3,
        ge=1,
        le=100,
        description="Minimum signal count for a ticker to appear in top/worst lists.",
    ),
) -> JSONResponse:
    """Return signal accuracy statistics and per-ticker performance metrics.

    This endpoint aggregates the ROT feedback analysis engine's cached results
    into a :class:`SignalQualityReport`.  Data is refreshed approximately every
    5 minutes by the background analysis worker.

    Tier gate: **Pro** and above.

    Args:
        min_sample: Minimum number of decided signals for a ticker to be
            included in top/worst ticker rankings.  Defaults to 3.

    Returns:
        JSON body matching the SignalQualityReport schema documented above.

    Raises:
        403: If the requesting user is below the Pro tier.
        401: If the request is unauthenticated.
    """
    user = await get_current_user_optional(request)
    headers = rate_limit_headers(user)

    if not user:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required", "error_code": "UNAUTHORIZED"},
            headers=headers,
        )

    tier = user.get("tier", "free")
    access = gate_signal_quality_access(tier)

    if not access.get("has_access"):
        return JSONResponse(
            status_code=403,
            content={
                "error": "Pro tier or above required for signal quality API.",
                "error_code": "TIER_REQUIRED",
                "required_tier": "pro",
                "upgrade_url": "/pricing",
            },
            headers=headers,
        )

    # Retrieve cached analysis results from app state
    analyzer = getattr(request.app.state, "feedback_analyzer", None)
    cache = getattr(request.app.state, "query_cache", None)

    raw_results: dict[str, Any] = {}
    if analyzer:
        if cache:
            raw_results = await cache.get_or_fetch(
                "feedback_analysis_api",
                lambda: _async_get_results(analyzer),
                ttl=300,
            )
        else:
            raw_results = getattr(analyzer, "_last_analysis", {}) or {}

    if not raw_results or not raw_results.get("computed_at"):
        return JSONResponse(
            content=_empty_report(),
            status_code=200,
            headers=headers,
        )

    # Build and filter the report
    report = _build_report(raw_results)

    # Re-apply min_sample filter to top/worst tickers
    report["top_tickers"] = [t for t in report["top_tickers"] if t["count"] >= min_sample]
    report["worst_tickers"] = [t for t in report["worst_tickers"] if t["count"] >= min_sample]

    log.debug(
        "signal_quality_api.ok user=%s total_signals=%d accuracy_pct=%.1f",
        user.get("id"),
        report["total_signals"],
        report["accuracy_pct"],
    )

    return JSONResponse(content=report, status_code=200, headers=headers)


async def _async_get_results(analyzer: object) -> dict[str, Any]:
    """Thin async wrapper for query_cache compatibility."""
    return getattr(analyzer, "_last_analysis", {}) or {}
