from __future__ import annotations

SYSTEM_PROMPT = """\
You are an options trading analyst specializing in Reddit-sourced market signals.
Given a Reddit market event with evidence and market context, provide structured analysis.

You must output valid JSON matching this exact schema:

{
  "event_type": "earnings_rumor" | "product_news" | "regulatory" | "squeeze_chatter" | "macro" | "other",
  "stance": "bullish" | "bearish" | "mixed" | "unknown",
  "time_horizon": "intraday" | "1w" | "earnings" | "longer" | "unknown",
  "confidence": <float 0.0-1.0>,
  "thesis": "<1-2 sentence investment thesis>",
  "catalyst_window": "<when the catalyst expires or resolves>",
  "market_expectation": "<what the market is currently pricing based on available data>",
  "invalidations": ["<condition that would disprove this thesis>", ...],
  "recommended_structures": ["<options strategy with brief rationale>", ...],
  "risk_notes": ["<key risk to highlight>", ...]
}

Guidelines:
- Confidence calibration (follow this strictly):
  0.10-0.25: Single Reddit post, purely speculative, no data ("trust me bro", YOLO posts)
  0.25-0.40: Post with some reasoning but unverified or anecdotal claims
  0.40-0.55: DD post with actual numbers (SI%, earnings dates, revenue) from a single source
  0.55-0.70: Multiple corroborating Reddit posts OR DD with verifiable data + market data confirmation
  0.70-0.85: Strong multi-source evidence with clear, confirmed catalyst and market alignment
  0.85-1.00: Reserved for near-certain events (confirmed M&A, published regulatory ruling)
- Hard caps:
  NEVER set confidence > 0.70 for squeeze_chatter (by nature speculative)
  NEVER set confidence > 0.85 unless the event is officially confirmed by a primary source
- Subreddit credibility adjustments:
  r/wallstreetbets, r/shortsqueeze, r/pennystocks: discount confidence by 0.05-0.10 (higher noise)
  r/options, r/thetagang, r/investing, r/valueinvesting: no discount (higher signal quality)
- For squeeze_chatter: note short interest data if mentioned, flag if purely speculative
- For earnings_rumor: note if pre/post earnings, estimate catalyst window
- recommended_structures should be specific: "bull call spread 5-10% OTM, 2-3 weeks out"
  not just "debit_spread"
- Always include at least one invalidation and one risk note
- If evidence is too thin to form a thesis, set confidence < 0.3 and strategy to "none"

Output ONLY the JSON object, no markdown fencing, no explanation.\
"""

_SUBREDDIT_TIERS = {
    "wallstreetbets": "low", "wallstreetbetsogs": "low",
    "shortsqueeze": "low", "pennystocks": "low",
    "stocks": "medium", "stockmarket": "medium",
    "options": "high", "thetagang": "high",
    "investing": "high", "valueinvesting": "high",
}

EVENT_TEMPLATE = """\
## Reddit Signal
Ticker(s): {entities}
Subreddit: r/{subreddit} (credibility: {subreddit_tier})
Post title: "{title}"
Body excerpt: "{body_excerpt}"
Post score: {score} | Comments: {num_comments} | Upvote ratio: {upvote_ratio}
Author: {author} | Flair: {flair}
Is crosspost: {is_crosspost}

## Trend Metrics
Trend score: {trend_score:.4f}
Score velocity: {score_rate:.4f}/s
Comment velocity: {comment_rate:.4f}/s

## Market Context
{market_context}

Analyze this signal and provide your structured JSON assessment.\
"""


def format_event_prompt(
    entities: list[str],
    subreddit: str,
    title: str,
    body_excerpt: str,
    score: int,
    num_comments: int,
    upvote_ratio: float | None,
    author: str,
    flair: str | None,
    is_crosspost: bool,
    trend_score: float,
    score_rate: float,
    comment_rate: float,
    market_data: dict | None,
) -> str:
    if market_data:
        lines = []
        for sym, data in market_data.items():
            if isinstance(data, dict):
                price = data.get("last_close", "N/A")
                pct = data.get("pct_1d")
                cap = data.get("market_cap")
                pct_str = f"{pct:+.2%}" if pct is not None else "N/A"
                cap_str = f"${cap:,.0f}" if cap else "N/A"
                lines.append(f"  {sym}: price={price}, 1d_change={pct_str}, market_cap={cap_str}")
        market_context = "\n".join(lines) if lines else "No market data available"
    else:
        market_context = "No market data available"

    subreddit_tier = _SUBREDDIT_TIERS.get(subreddit.lower(), "medium")

    return EVENT_TEMPLATE.format(
        entities=", ".join(entities) if entities else "None extracted",
        subreddit=subreddit,
        subreddit_tier=subreddit_tier,
        title=title[:200],
        body_excerpt=body_excerpt[:500],
        score=score,
        num_comments=num_comments,
        upvote_ratio=upvote_ratio or "N/A",
        author=author,
        flair=flair or "None",
        is_crosspost=is_crosspost,
        trend_score=trend_score,
        score_rate=score_rate,
        comment_rate=comment_rate,
        market_context=market_context,
    )
