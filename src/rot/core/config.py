from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedditConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_REDDIT_")

    client_id: str = ""
    client_secret: str = ""
    user_agent: str = "rot:v0.1 (by u_rotbot)"
    subreddits: List[str] = ["wallstreetbets", "stocks", "options"]
    listing: str = "hot"
    limit_per_sub: int = 50
    include_comments: bool = False
    top_comments: int = 10
    poll_interval_s: int = 20


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_LLM_")

    provider: Literal["openai", "anthropic", "deepseek"] = "openai"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    base_url: Optional[str] = None
    max_tokens: int = 1024
    temperature: float = 0.3


class MarketConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_MARKET_")

    cache_ttl_s: int = 3600
    symbol_cache_ttl_s: int = 604800
    min_market_cap: float = 1e8  # $100M minimum


class TrendConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_TREND_")

    window_s: int = 1800
    threshold: float = 0.01
    comment_weight: float = 2.0
    top_n: int = 10


class AlertConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_ALERT_")

    discord_webhook_url: Optional[str] = None
    min_confidence: float = 0.6


class WebConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_WEB_")

    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    reddit: RedditConfig = Field(default_factory=RedditConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    trend: TrendConfig = Field(default_factory=TrendConfig)
    alert: AlertConfig = Field(default_factory=AlertConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    storage_root: str = "storage"
    db_path: str = "storage/rot.db"
