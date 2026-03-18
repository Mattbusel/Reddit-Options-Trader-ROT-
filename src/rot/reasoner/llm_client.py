from __future__ import annotations

import logging
from typing import Literal

from rot.core.retry import retry_with_backoff

log = logging.getLogger(__name__)


class LLMClient:
    """Provider-agnostic LLM client supporting OpenAI, Anthropic, and DeepSeek."""

    def __init__(
        self,
        provider: Literal["openai", "anthropic", "deepseek"] = "openai",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> None:
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = None

        if provider in ("openai", "deepseek"):
            try:
                import openai

                kwargs: dict = {"api_key": api_key}
                if base_url:
                    kwargs["base_url"] = base_url
                elif provider == "deepseek":
                    kwargs["base_url"] = "https://api.deepseek.com/v1"
                self._client = openai.OpenAI(**kwargs)
            except ImportError:
                log.warning("openai package not installed; LLM reasoning will use fallback")
        elif provider == "anthropic":
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                log.warning("anthropic package not installed; LLM reasoning will use fallback")

    @property
    def available(self) -> bool:
        """``True`` if the underlying LLM client was successfully initialised."""
        return self._client is not None

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError, Exception),
    )
    def complete(self, system: str, user: str) -> str:
        """Send *system* + *user* prompts to the configured LLM and return the text response."""
        if not self._client:
            raise RuntimeError("LLM client not initialized (missing API key or package)")

        if self.provider in ("openai", "deepseek"):
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            return response.choices[0].message.content or ""

        elif self.provider == "anthropic":
            response = self._client.messages.create(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            return response.content[0].text if response.content else ""

        raise ValueError(f"Unknown provider: {self.provider}")
