from __future__ import annotations

import logging
from typing import Any, Dict

from rot.core.types import Event, ReasoningPacket
from rot.reasoner.llm_client import LLMClient
from rot.reasoner.parser import parse_reasoning_response
from rot.reasoner.prompts import SYSTEM_PROMPT, format_event_prompt

log = logging.getLogger(__name__)


class Reasoner:
    """LLM-powered event reasoning. Falls back to template if no API key configured."""

    def __init__(
        self,
        provider: str = "openai",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> None:
        self._llm: LLMClient | None = None
        if api_key:
            try:
                self._llm = LLMClient(
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if not self._llm.available:
                    self._llm = None
            except Exception as e:
                log.warning("Failed to init LLM client: %s", e)
                self._llm = None

    @property
    def llm_available(self) -> bool:
        return self._llm is not None

    def reason(self, event: Event) -> ReasoningPacket:
        if not self._llm:
            return self._stub_reason(event)

        try:
            return self._llm_reason(event)
        except Exception as e:
            log.warning("LLM reasoning failed, using fallback: %s", e)
            return self._stub_reason(event)

    def _llm_reason(self, event: Event) -> ReasoningPacket:
        evidence = event.evidence[0] if event.evidence else None
        post_title = evidence.excerpt if evidence else "Unknown"
        subreddit = evidence.subreddit if evidence else "unknown"

        meta = event.meta or {}
        features = meta.get("features", {})
        market_data = meta.get("market", {})

        # Get post details from evidence
        user_prompt = format_event_prompt(
            entities=list(event.entities),
            subreddit=subreddit,
            title=post_title,
            body_excerpt="",
            score=int(meta.get("score", 0)),
            num_comments=int(meta.get("num_comments", 0)),
            upvote_ratio=meta.get("upvote_ratio"),
            author=meta.get("author", "unknown"),
            flair=meta.get("flair"),
            is_crosspost=bool(meta.get("is_crosspost", False)),
            trend_score=float(meta.get("trend_score", event.meta.get("trend_score", 0))),
            score_rate=float(features.get("score_rate", 0)),
            comment_rate=float(features.get("comment_rate", 0)),
            market_data=market_data if market_data else None,
        )

        raw_response = self._llm.complete(SYSTEM_PROMPT, user_prompt)
        return parse_reasoning_response(raw_response, list(event.entities))

    def _stub_reason(self, event: Event) -> ReasoningPacket:
        """Fallback when no LLM is configured."""
        entities_str = ", ".join(event.entities) if event.entities else "unknown tickers"
        return ReasoningPacket(
            thesis=f"Reddit chatter mentions {entities_str}; treat as unverified signal.",
            catalyst_window="unknown",
            market_expectation="unclear; watch implied volatility + liquidity",
            invalidations=[
                "No corroboration across sources",
                "Trend decays within hours",
            ],
            recommended_structures=[
                "debit_spread (defined risk)",
                "calendar (if catalyst known)",
            ],
            risk_notes=[
                "Do not trade without market data gates",
                "LLM reasoning not available - using template fallback",
            ],
            raw={"stub": True},
        )
