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
- Confidence = estimated probability the trade direction is correct within the time horizon.
  Calibrate so that signals at X% confidence should win roughly X% of the time.
- Confidence calibration (follow this strictly):
  0.10-0.25: Purely speculative, no supporting data, meme/YOLO energy. Likely noise.
  0.25-0.40: Some reasoning but unverified claims, single anecdotal Reddit post, no market data alignment.
  0.40-0.55: Solid thesis with real data (SI%, earnings dates, IV levels) from one source, OR market data partially confirms the direction (price trend aligns with stance).
  0.55-0.70: Strong thesis backed by verifiable data AND market context confirms (IV elevated, unusual options flow, price momentum aligns). Should feel more likely right than wrong.
  0.70-0.85: Multi-source corroboration with clear confirmed catalyst, market data strongly aligned. High conviction.
  0.85-1.00: Near-certain: confirmed M&A, published regulatory ruling, official company announcement.
- KEY RULE: If market data contradicts the post's thesis (e.g., bullish post but stock is tanking, or bearish post but IV is crushed), reduce confidence by 0.10-0.20 regardless of post quality.
- KEY RULE: If the post provides no specific data/numbers and is just opinion, confidence MUST be below 0.35.
- Hard caps:
  NEVER set confidence > 0.65 for squeeze_chatter (by nature speculative)
  NEVER set confidence > 0.35 for earnings_rumor (historically ~11% win rate; pure speculation unless backed by unusual options flow or insider data)
  NEVER set confidence > 0.85 unless the event is officially confirmed by a primary source
  If stance is "unknown", confidence MUST be below 0.25 (no directional view = no conviction)
- Stance guidance:
  "mixed" = expecting a big move but direction unclear (e.g., earnings straddle, binary event). Use for catalysts that could go either way.
  "unknown" = genuinely cannot determine any thesis or direction. This is NOT the same as mixed — it means insufficient information.
  Prefer "mixed" over "unknown" when there is a clear catalyst but uncertain direction.
  Prefer "unknown" only when the post is too vague, sarcastic, or noise-like to form any view.
- Subreddit credibility adjustments:
  r/wallstreetbets, r/shortsqueeze, r/pennystocks: discount confidence by 0.05-0.10 (higher noise)
  r/options, r/thetagang, r/investing, r/valueinvesting: no discount (higher signal quality)
- RSS/news feeds (flair="rss"): treat as institutional-quality source. Boost confidence by 0.05-0.10 vs equivalent Reddit post.
- For squeeze_chatter: note short interest data if mentioned, flag if purely speculative
- For earnings_rumor: note if pre/post earnings, estimate catalyst window
- recommended_structures should be specific: "bull call spread 5-10% OTM, 2-3 weeks out"
  not just "debit_spread"
- If IV data is provided and high (>50%), favor credit/premium-selling strategies
- If put/call OI ratio is extreme (>2.0 = heavy put buying, <0.5 = heavy call buying), note unusual positioning
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

{nlp_section}## Market Context
{market_context}

Analyze this signal and provide your structured JSON assessment.\
"""


def _format_nlp_section(nlp_data: dict | None) -> str:
    """Format NLP analysis metadata for the LLM prompt."""
    if not nlp_data:
        return ""

    lines = ["## NLP Analysis (Custom Engine)"]
    polarity = nlp_data.get("polarity", 0.0)
    intensity = nlp_data.get("intensity", 0.0)
    conviction = nlp_data.get("conviction", 0.5)
    sarcasm = nlp_data.get("sarcasm_probability", 0.0)

    lines.append(f"Sentiment polarity: {polarity:+.2f} (intensity: {intensity:.2f})")
    lines.append(f"Conviction: {conviction:.2f} | Sarcasm probability: {sarcasm:.2f}")

    # Classifications
    classifications = nlp_data.get("classifications", [])
    if classifications:
        cats = ", ".join(f"{cat}({conf:.2f})" for cat, conf in classifications[:4])
        lines.append(f"Event classifications: {cats}")

    # Temporal
    tense = nlp_data.get("tense", "unknown")
    actionability = nlp_data.get("actionability", 0.5)
    urgency = nlp_data.get("urgency", 0.0)
    lines.append(f"Tense: {tense} | Actionability: {actionability:.2f} | Urgency: {urgency:.2f}")

    # Thread consensus
    thread_consensus = nlp_data.get("thread_consensus")
    if thread_consensus is not None:
        agreement = nlp_data.get("thread_agreement_with_op", 0.0)
        contrarian = nlp_data.get("contrarian_detected", False)
        lines.append(
            f"Thread consensus: {thread_consensus:.2f} | OP agreement: {agreement:.2f}"
            + (" | CONTRARIAN DETECTED" if contrarian else "")
        )

    # Per-ticker sentiments
    ticker_sents = nlp_data.get("ticker_sentiments", {})
    if ticker_sents:
        parts = [f"{t}={s}" for t, s in ticker_sents.items()]
        lines.append(f"Per-ticker sentiment: {', '.join(parts)}")

    lines.append("")  # trailing newline
    return "\n".join(lines) + "\n"


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
    nlp_data: dict | None = None,
) -> str:
    """Build the user-turn prompt for the LLM from event fields and market context."""
    if market_data:
        lines = []
        for sym, data in market_data.items():
            if isinstance(data, dict):
                price = data.get("last_close", "N/A")
                pct = data.get("pct_1d")
                cap = data.get("market_cap")
                pct_str = f"{pct:+.2%}" if pct is not None else "N/A"
                cap_str = f"${cap:,.0f}" if cap else "N/A"
                line = f"  {sym}: price={price}, 1d_change={pct_str}, market_cap={cap_str}"
                # Append options chain data if available
                iv = data.get("atm_iv")
                if iv is not None:
                    line += f", ATM_IV={iv:.1%}"
                pc = data.get("pc_ratio")
                if pc is not None:
                    line += f", put/call_OI={pc:.2f}"
                c_oi = data.get("call_oi")
                p_oi = data.get("put_oi")
                if c_oi is not None and p_oi is not None:
                    line += f", call_OI={c_oi:,}, put_OI={p_oi:,}"
                lines.append(line)
        market_context = "\n".join(lines) if lines else "No market data available"
    else:
        market_context = "No market data available"

    subreddit_tier = _SUBREDDIT_TIERS.get(subreddit.lower(), "medium")

    nlp_section = _format_nlp_section(nlp_data)

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
        nlp_section=nlp_section,
        market_context=market_context,
    )
