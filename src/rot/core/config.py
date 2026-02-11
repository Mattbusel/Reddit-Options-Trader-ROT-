from __future__ import annotations

from typing import Any, List, Literal, Optional

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
    price_check_interval_s: int = 300  # 5 minutes
    price_check_batch_size: int = 50
    enable_options_chain: bool = True
    options_cache_ttl_s: int = 1800  # 30 min (shorter than price cache)


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
                url="https://feeds.content.dowjones.io/public/rss/mw_topstories",
                label="marketwatch-top",
            ),
            RSSFeedEntry(
                url="https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
                label="marketwatch-realtime",
            ),
            RSSFeedEntry(
                url="https://www.investing.com/rss/news_25.rss",
                label="investing-com-stocks",
            ),
            RSSFeedEntry(
                url="https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,QQQ,AAPL,TSLA,NVDA,AMZN,MSFT&region=US&lang=en-US",
                label="yahoo-finance-top",
            ),
            RSSFeedEntry(
                url="https://www.cnbc.com/id/20409666/device/rss/rss.html",
                label="cnbc-market",
            ),
            RSSFeedEntry(
                url="https://seekingalpha.com/market_currents.xml",
                label="seekingalpha-currents",
            ),
            # ── Institutional / Government feeds ──
            RSSFeedEntry(
                url="https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
                label="fda-press-releases",
            ),
            RSSFeedEntry(
                url="https://www.federalreserve.gov/feeds/press_all.xml",
                label="fed-press-releases",
            ),
            RSSFeedEntry(
                url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K&dateb=&owner=include&count=20&search_text=&action=getcompany&output=atom",
                label="sec-8k-filings",
            ),
            RSSFeedEntry(
                url="https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945",
                label="dod-contracts",
            ),
        ]
    )


class StockTwitsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_STOCKTWITS_")

    enabled: bool = False
    symbols: List[str] = Field(
        default_factory=lambda: ["TSLA", "AAPL", "NVDA", "SPY", "QQQ", "AMD", "AMZN", "MSFT"]
    )
    trending_enabled: bool = True
    poll_interval_s: int = 180  # 3 minutes


class TwitterConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_TWITTER_")

    enabled: bool = False
    bearer_token: str = ""
    cashtags: List[str] = Field(
        default_factory=lambda: ["TSLA", "AAPL", "NVDA", "SPY", "QQQ"]
    )
    accounts: List[str] = Field(
        default_factory=lambda: ["unusual_whales", "zerohedge", "DeItaone"]
    )
    poll_interval_s: int = 180
    max_results: int = 20


class EmailConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_EMAIL_")

    # Resend HTTP API (recommended for cloud providers like Railway)
    resend_api_key: str = ""  # Set this to use Resend instead of SMTP

    # SMTP settings (fallback, for local dev or self-hosted)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    use_ssl: bool = False  # True = SMTP_SSL (port 465), False = STARTTLS (port 587)

    # Shared settings
    from_address: str = "ROT Alerts <alerts@rot.app>"
    enabled: bool = False


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


class TwitterConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_TWITTER_")

    api_key: str = ""           # Consumer / API key
    api_secret: str = ""        # Consumer / API secret
    access_token: str = ""      # User access token (for the ROT account)
    access_secret: str = ""     # User access token secret
    enabled: bool = False
    interval_s: int = 10800     # 3 hours
    min_confidence: float = 0.5  # Lowered to get posts flowing
    dashboard_url: str = "https://web-production-71423.up.railway.app"


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
        env_prefix="ROT_",
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
    stocktwits: StockTwitsConfig = Field(default_factory=StockTwitsConfig)
    twitter: TwitterConfig = Field(default_factory=TwitterConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    stripe: StripeConfig = Field(default_factory=StripeConfig)
    tier_limits: TierConfig = Field(default_factory=TierConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    twitter: TwitterConfig = Field(default_factory=TwitterConfig)
    storage_root: str = "storage"
    db_path: str = ""  # auto-derived from storage_root if empty

    def model_post_init(self, __context: Any) -> None:
        if not self.db_path:
            self.db_path = f"{self.storage_root}/rot.db"
