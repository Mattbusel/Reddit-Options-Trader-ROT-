"""FAQ — How ROT Tracks Win Rate and Signal Performance."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional

router = APIRouter()


def _base_context(request: Request, user: dict | None) -> dict:
    tier = (user or {}).get("tier", "free")
    badge_map = {
        "free": "bg-gray-700 text-gray-300",
        "pro": "bg-blue-700/60 text-blue-200",
        "premium": "bg-purple-700/60 text-purple-200",
        "ultra": "bg-orange-700/60 text-orange-200",
        "admin": "bg-red-700/60 text-red-200",
    }
    return {
        "request": request,
        "user": user,
        "tier": tier,
        "tier_badge_class": badge_map.get(tier, badge_map["free"]),
        "stripe_enabled": bool(request.app.state.settings.stripe.secret_key),
    }


FAQ_DATA = [
    {
        "q": "What is the Win Rate?",
        "a": "The Win Rate is the percentage of resolved signals that moved in the predicted direction by more than 0.5%. It is calculated as: <strong>Win Rate = Winners / (Winners + Losers) &times; 100</strong>. Neutral signals (price moved less than 0.5%) are excluded from the win rate calculation since they fall within normal bid-ask spread noise.",
    },
    {
        "q": "How does ROT detect a signal?",
        "a": "ROT continuously scans popular options and trading subreddits (r/wallstreetbets, r/options, r/stocks, r/investing, and others). Each post is analyzed by a credibility scorer that extracts the ticker, stance (bullish/bearish/mixed), confidence level, strategy type, and event data. Signals are deduplicated so the same post+ticker combination only counts once.",
    },
    {
        "q": "How is a signal's stance determined?",
        "a": "The stance (bullish, bearish, or mixed) comes from natural language analysis of the Reddit post. Keywords, context, and sentiment indicators determine whether the author is recommending a long position (bullish), short position (bearish), or is presenting both sides (mixed). The confidence score (0-100%) reflects how strongly the post commits to a directional thesis.",
    },
    {
        "q": "How does price tracking work?",
        "a": "When a signal is created, ROT records the current market price of the underlying ticker. A background price checker then captures the price at four intervals: <strong>1 hour, 4 hours, 1 day, and 1 week</strong> after the signal. These snapshots allow us to evaluate how the trade idea performed over time.",
    },
    {
        "q": "Which price snapshot is used to judge win/loss?",
        "a": "ROT uses the <strong>best available</strong> price snapshot in priority order: 1-day &gt; 4-hour &gt; 1-hour. This means if the 1-day price is available, that's used. If not (e.g., the signal is less than 24 hours old), the 4-hour price is used, and so on. This ensures that newer signals aren't judged too early while older signals get a fair evaluation window.",
    },
    {
        "q": "What is the 0.5% threshold and why does it exist?",
        "a": "A <strong>0.5% minimum movement threshold</strong> filters out noise. If the price moves less than 0.5% in either direction, the signal is classified as <strong>neutral</strong> rather than a win or loss. This exists because bid-ask spreads, minor fluctuations, and market noise can create small price movements that don't represent a meaningful directional outcome. Neutral signals are tracked but excluded from the win rate percentage.",
    },
    {
        "q": "How does stance-aware scoring work?",
        "a": "Win/loss is determined relative to the signal's stance:<ul class='list-disc list-inside mt-2 space-y-1'><li><strong>Bullish signals</strong>: A win if the price went <em>up</em> by more than 0.5%</li><li><strong>Bearish signals</strong>: A win if the price went <em>down</em> by more than 0.5%</li></ul>This means a bearish signal on a stock that dropped 3% is scored as a win, not a loss. The system correctly interprets the author's intended trade direction.",
    },
    {
        "q": "What do the confidence buckets mean?",
        "a": "The dashboard breaks down win rate by confidence tiers to show whether higher-confidence signals actually perform better:<ul class='list-disc list-inside mt-2 space-y-1'><li><strong>&lt;30%</strong> &mdash; Low confidence (speculative, vague thesis)</li><li><strong>30-50%</strong> &mdash; Moderate confidence</li><li><strong>50-70%</strong> &mdash; High confidence (clear thesis with supporting data)</li><li><strong>70%+</strong> &mdash; Very high confidence (strong conviction with catalysts)</li></ul>A bucket needs at least 3 decided signals before a win rate is displayed, to avoid misleading statistics from tiny sample sizes.",
    },
    {
        "q": "How does ROT keep the win rate after signals are purged?",
        "a": "Signal data is retained for 14 days to keep storage costs low. However, <strong>before</strong> any old signals are deleted, the system takes a <strong>win-rate snapshot</strong> &mdash; recording the total winners, losers, and neutral counts for the signals about to be purged. These snapshots are stored permanently in a separate table and are automatically merged with live signal data when the dashboard calculates your win rate. This means the win/loss record persists indefinitely even though the raw signal data is cycled out every two weeks.",
    },
    {
        "q": "Why are signals only kept for 14 days?",
        "a": "Retaining every signal forever would significantly increase database and hosting costs, which would drive up subscription prices. The 14-day window provides enough time for all price checkpoints (1h, 4h, 1d, 1w) to be recorded and for outcomes to be fully resolved. Before deletion, the outcomes are permanently snapshotted so no win/loss data is ever lost. Users who want to keep the raw signal data can export it via CSV or the API at any time.",
    },
    {
        "q": "What is a 'tradeable' signal?",
        "a": "A tradeable signal is any signal with a <strong>bullish</strong> or <strong>bearish</strong> stance. These represent posts where the author has a clear directional thesis. Signals with a 'mixed' or 'unknown' stance are still tracked but treated as neutral for win/loss purposes since there is no directional bet to evaluate.",
    },
    {
        "q": "How is the Signal Map (scatter plot) organized?",
        "a": "The Signal Map plots each signal on two axes:<ul class='list-disc list-inside mt-2 space-y-1'><li><strong>X-axis (Confidence %)</strong>: How confident the signal's thesis is (0-100%)</li><li><strong>Y-axis (Trend Score)</strong>: How much community traction/buzz the ticker has</li></ul>The quadrants help identify signal quality:<ul class='list-disc list-inside mt-2 space-y-1'><li><strong>Top-Right</strong>: Hot &amp; Confident &mdash; high conviction + trending</li><li><strong>Top-Left</strong>: Trending, Uncertain &mdash; buzzing but weak thesis</li><li><strong>Bottom-Right</strong>: Confident, Quiet &mdash; strong thesis, low buzz</li><li><strong>Bottom-Left</strong>: Weak Signals &mdash; low confidence, low traction</li></ul>",
    },
    {
        "q": "Does ROT provide financial advice?",
        "a": "No. ROT is a <strong>signal intelligence</strong> tool, not a financial advisor. It aggregates and analyzes public Reddit discussions to surface trading sentiment and ideas. The win rate and performance metrics are statistical measures of how Reddit-sourced signals have historically performed. Always do your own research and consult a licensed financial advisor before making investment decisions.",
    },
    {
        "q": "Can I export the win rate data?",
        "a": "Yes. Pro and higher tier subscribers can export signal data via CSV or the API. The export includes the raw signal data, price snapshots, and performance outcomes for all signals within your plan's data retention window. The permanent win-rate snapshots ensure your historical win/loss totals remain accurate in the dashboard even after the raw data is cycled out.",
    },
]


@router.get("/faq", response_class=HTMLResponse)
async def faq(request: Request):
    """FAQ — How ROT Tracks Win Rate and Signal Performance."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)

    # Build FAQPage JSON-LD schema for SEO
    faq_items = []
    for item in FAQ_DATA:
        faq_items.append({
            "@type": "Question",
            "name": item["q"],
            "acceptedAnswer": {
                "@type": "Answer",
                "text": item["a"],
            },
        })
    faq_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": faq_items,
    })

    base = str(request.base_url).rstrip("/")

    ctx.update({
        "faqs": FAQ_DATA,
        "faq_schema": faq_schema,
        "share_url": f"{base}/faq",
        "share_text": "How ROT tracks win rate for Reddit options signals",
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("faq.html", ctx)
