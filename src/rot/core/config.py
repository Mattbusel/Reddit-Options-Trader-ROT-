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


class RSSFeedEntry(BaseSettings):
    """Configuration for a single RSS feed."""

    model_config = SettingsConfigDict(env_prefix="ROT_RSS_FEED_")

    url: str = ""
    label: str = ""


class RSSConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_RSS_")

    enabled: bool = False
    poll_interval_s: int = 300  # 5 minutes
    max_age_s: int = 3600  # freshness gate for trend bypass (1 hour)
    synthetic_trend_score: float = 0.5  # trend_score assigned to fresh RSS items
    feeds: List[RSSFeedEntry] = Field(
        default_factory=lambda: [
            RSSFeedEntry(
                url="https://feeds.reuters.com/reuters/businessNews",
                label="reuters-business",
            ),
            RSSFeedEntry(
                url="https://feeds.reuters.com/reuters/companyNews",
                label="reuters-company",
            ),
            RSSFeedEntry(
                url=(
                    "https://www.sec.gov/cgi-bin/browse-edgar"
                    "?action=getcurrent&type=8-K&dateb=&owner=include"
                    "&count=40&search_text=&output=atom"
                ),
                label="sec-8k-filings",
            ),
        ]
    )


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_AUTH_")

    jwt_secret: str = ""  # falls back to web.secret_key if empty
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours


class StripeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_STRIPE_")

    secret_key: str = ""  # empty = Stripe disabled
    webhook_secret: str = ""
    pro_price_id: str = ""
    premium_price_id: str = ""
    ultra_price_id: str = ""
    success_url: str = "/dashboard?upgraded=1"
    cancel_url: str = "/pricing"


class TierConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_TIER_")

    free_signal_delay_s: int = 900  # 15 minutes
    free_page_limit: int = 10
    free_api_limit_day: int = 100
    pro_api_limit_day: int = 5000
    premium_api_limit_day: int = 25000
    ultra_api_limit_day: int = 50000


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
    rss: RSSConfig = Field(default_factory=RSSConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    stripe: StripeConfig = Field(default_factory=StripeConfig)
    tier_limits: TierConfig = Field(default_factory=TierConfig)
    storage_root: str = "storage"
    db_path: str = "storage/rot.db"
