"""Platform AI Summary Generator.

Kills: Trade Ideas ($254/mo). Generates AI trade thesis for every signal
using GPT-4o-mini at ~$5/month total for ALL users. One generation per
signal, served to everyone. Near-zero per-user cost.

Uses platform API key (not BYOK). Falls back to heuristic summary if
no platform key configured.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from rot.core.retry import async_retry_with_backoff

log = logging.getLogger(__name__)

# Short, focused prompt — minimal tokens = minimal cost
_SYSTEM_PROMPT = """You are a concise financial signal analyst. Given a trading signal, write a 1-2 sentence actionable summary. Include: the thesis, key risk, and suggested timeframe. Be direct. No disclaimers."""

_USER_TEMPLATE = """Signal: {ticker} ({stance}) — {event_type}
Source: {subreddit} | Confidence: {confidence:.0%}
Title: {post_title}
Strategy: {strategy}"""


def _build_heuristic_summary(signal: Dict[str, Any]) -> str:
    """Fast rule-based summary when no LLM is available. Zero cost."""
    ticker = signal.get("ticker", "?")
    stance = signal.get("stance", "unknown")
    event_type = signal.get("event_type", "other")
    confidence = signal.get("confidence", 0)
    strategy = "none"

    # Try to extract strategy from trade_idea
    trade_idea = signal.get("trade_idea", {})
    if isinstance(trade_idea, dict):
        strategy = trade_idea.get("strategy", "none")

    reasoning = signal.get("reasoning", {})
    thesis = ""
    if isinstance(reasoning, dict):
        thesis = reasoning.get("thesis", "")

    # Build a useful summary from what we have
    stance_word = {"bullish": "Bullish", "bearish": "Bearish", "mixed": "Mixed"}.get(stance, "Neutral")
    conf_word = "high" if confidence >= 0.7 else "moderate" if confidence >= 0.5 else "low"

    if thesis and len(thesis) > 20:
        # Truncate thesis to ~120 chars for a snappy summary
        short_thesis = thesis[:120].rsplit(" ", 1)[0] + ("..." if len(thesis) > 120 else "")
        return f"{stance_word} on ${ticker} ({conf_word} confidence). {short_thesis}"

    event_labels = {
        "earnings_rumor": "earnings expectations",
        "squeeze_chatter": "short squeeze momentum",
        "product_news": "product catalyst",
        "regulatory": "regulatory development",
        "macro": "macro conditions",
    }
    event_desc = event_labels.get(event_type, "market activity")

    if strategy and strategy != "none":
        return f"{stance_word} on ${ticker} based on {event_desc}. {conf_word.capitalize()} confidence — consider {strategy.replace('_', ' ')}."
    return f"{stance_word} on ${ticker} based on {event_desc}. {conf_word.capitalize()} confidence signal."


@async_retry_with_backoff(
    max_attempts=3,
    base_delay=2.0,
    retryable_exceptions=(ConnectionError, TimeoutError, OSError),
)
async def generate_ai_summary(signal: Dict[str, Any]) -> str:
    """Generate a platform AI summary for a signal.

    Uses GPT-4o-mini via OpenAI SDK if ROT_PLATFORM_LLM_KEY is set.
    Falls back to heuristic summary otherwise. Either way, cost is ~$0.
    """
    platform_key = os.environ.get("ROT_PLATFORM_LLM_KEY", "")
    if not platform_key or len(platform_key) < 20:
        return _build_heuristic_summary(signal)

    # Build the user prompt
    ticker = signal.get("ticker", "?")
    stance = signal.get("stance", "unknown")
    event_type = signal.get("event_type", "other")
    confidence = signal.get("confidence", 0)
    post_title = signal.get("post_title", "")
    subreddit = signal.get("subreddit", "")

    trade_idea = signal.get("trade_idea", {})
    strategy = trade_idea.get("strategy", "none") if isinstance(trade_idea, dict) else "none"

    user_prompt = _USER_TEMPLATE.format(
        ticker=ticker, stance=stance, event_type=event_type,
        confidence=confidence, post_title=post_title[:200],
        subreddit=subreddit, strategy=strategy,
    )

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=platform_key)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=100,
            temperature=0.3,
        )
        summary = resp.choices[0].message.content.strip()
        return summary[:500]
    except ImportError:
        log.debug("openai package not installed — using heuristic summary")
        return _build_heuristic_summary(signal)
    except Exception as e:
        log.warning("Platform AI summary failed for %s: %s", ticker, e)
        return _build_heuristic_summary(signal)


async def backfill_ai_summaries(db: Any, limit: int = 30) -> int:
    """Generate AI summaries for signals that don't have one yet.

    Called from the periodic cleanup loop. Processes at most `limit`
    signals per cycle to stay within rate limits and keep latency low.
    Returns count of summaries generated.
    """
    signals = await db.get_signals_needing_ai_summary(limit=limit)
    count = 0
    for sig in signals:
        try:
            summary = await generate_ai_summary(sig)
            if summary:
                await db.set_ai_summary(sig["id"], summary)
                count += 1
        except Exception as e:
            log.warning("AI summary failed for signal %s: %s", sig.get("id", "?"), e)
    if count:
        log.info("Generated %d AI summaries (of %d pending)", count, len(signals))
    return count
