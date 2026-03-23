from __future__ import annotations

import logging

from rot.core.types import Event, ReasoningPacket
from rot.reasoner.llm_client import LLMClient
from rot.reasoner.parser import parse_reasoning_response
from rot.reasoner.prompts import SYSTEM_PROMPT, format_event_prompt

log = logging.getLogger(__name__)


_PLACEHOLDER_KEYS = {"your_api_key", "sk-...", "your-api-key", "changeme", "test", ""}


class Reasoner:
    """LLM-powered event reasoning with circuit breaker and stub fallback.

    Wraps a configurable LLM provider (OpenAI, Anthropic, or DeepSeek) and
    converts ``Event`` objects into structured ``ReasoningPacket`` objects
    containing thesis, risk notes, and trade structure recommendations.

    Circuit breaker behaviour: after 3 consecutive LLM failures the reasoner
    stops sending requests and returns stub packets with ``raw["stub"] = True``
    until it is reset externally (e.g. by a restart or a successful call in a
    future run).

    Fallback hierarchy:
    1. Real LLM call if ``api_key`` is set and non-placeholder.
    2. Template-based stub if no API key or key is a placeholder.
    3. Template-based stub if circuit breaker is open.
    4. Template-based stub if the LLM call fails (and increments failure count).

    Args:
        provider: One of ``"openai"``, ``"anthropic"``, or ``"deepseek"``.
        api_key: API key for the provider. Empty string disables LLM reasoning.
        model: Model name (e.g. ``"gpt-4o-mini"``, ``"claude-sonnet-4-6"``).
        base_url: Optional custom base URL for OpenAI-compatible endpoints.
        max_tokens: Maximum output tokens per LLM call.
        temperature: Sampling temperature (0.0-1.0).
    """

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
        self._consecutive_failures = 0
        self._max_failures = 3

        if api_key:
            # Reject known placeholder / example keys
            stripped = api_key.strip()
            if stripped.lower() in _PLACEHOLDER_KEYS or len(stripped) < 20:
                log.warning(
                    "LLM API key appears to be a placeholder ('%s...') — "
                    "using fallback reasoning. Set a real key in OPENAI_API_KEY.",
                    stripped[:8],
                )
            else:
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
        """``True`` if the LLM client was initialised with a valid API key."""
        return self._llm is not None

    def reset(self) -> None:
        """Clear stale circuit-breaker failure state.

        Call this on process startup (or after a deployment) to ensure that
        failure counts accumulated in a previous process run are not inherited.
        After calling ``reset()`` the reasoner will attempt live LLM calls
        again (subject to ``_max_failures``).

        This is a no-op when no LLM client is configured (stub-only mode).
        """
        self._consecutive_failures = 0
        log.info("Reasoner circuit breaker reset: failure count cleared.")

    def reason(self, event: Event) -> ReasoningPacket:
        """Produce a reasoning packet for a market event.

        Uses the configured LLM provider when available.  After
        ``_max_failures`` consecutive LLM errors the circuit breaker trips and
        all subsequent calls use the stub fallback until the object is
        re-instantiated.

        Args:
            event: Structured market event to reason about.

        Returns:
            A ``ReasoningPacket`` with ``thesis``, ``confidence``, ``stance``,
            and the raw LLM JSON payload (or stub values on fallback).
        """
        if not self._llm or self._consecutive_failures >= self._max_failures:
            return self._stub_reason(event)

        try:
            result = self._llm_reason(event)
            self._consecutive_failures = 0  # Reset on success
            return result
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_failures:
                log.error(
                    "LLM reasoning disabled after %d consecutive failures: %s",
                    self._max_failures, e,
                )
            else:
                log.warning(
                    "LLM reasoning failed (%d/%d), using fallback: %s",
                    self._consecutive_failures, self._max_failures, e,
                )
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
            nlp_data=meta.get("nlp"),
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
