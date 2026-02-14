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
    poll_interval_s: Optional[int] = None  # None → use global RSSConfig.poll_interval_s


class RSSConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_RSS_")

    enabled: bool = False
    poll_interval_s: int = 300  # 5 minutes
    max_age_s: int = 3600  # freshness gate for trend bypass (1 hour)
    synthetic_trend_score: float = 0.5  # trend_score assigned to fresh RSS items
    max_entries_per_feed: int = 50  # cap entries per feed (DoD returns 500+)
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
            # Department of Defense (ContentType: 400=contracts, 9=releases, 1=news)
            # Polled every 30 min — these publish daily/weekly, not in real time.
            RSSFeedEntry(
                url="https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=400&Site=945&max=20",
                label="dod-contracts",
                poll_interval_s=1800,
            ),
            RSSFeedEntry(
                url="https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=9&Site=945&max=20",
                label="dod-releases",
                poll_interval_s=1800,
            ),
            RSSFeedEntry(
                url="https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=20",
                label="dod-news",
                poll_interval_s=1800,
            ),
            # FDA / Pharma regulatory — polled every 30 min (low frequency publishers)
            RSSFeedEntry(
                url="https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
                label="fda-press-releases",
                poll_interval_s=1800,
            ),
            RSSFeedEntry(
                url="https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drugs/rss.xml",
                label="fda-drugs",
                poll_interval_s=1800,
            ),
            # fda-safety-alerts removed — returns HTTP 404
            RSSFeedEntry(
                url="https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml",
                label="fda-recalls",
                poll_interval_s=1800,
            ),
            # Federal Reserve
            RSSFeedEntry(
                url="https://www.federalreserve.gov/feeds/press_all.xml",
                label="fed-press-releases",
            ),
            # SEC 8-K feed removed — consistently returns 403
            # biopharma-dive removed — returns HTTP 403
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


class TwitterIngestConfig(BaseSettings):
    """Config for reading/ingesting tweets (API v2 Bearer Token)."""

    model_config = SettingsConfigDict(env_prefix="ROT_TWITTER_INGEST_")

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


class TwitterPosterConfig(BaseSettings):
    """Config for posting signals to X/Twitter (OAuth 1.0a)."""

    model_config = SettingsConfigDict(env_prefix="ROT_TWITTER_")

    api_key: str = ""           # Consumer / API key
    api_secret: str = ""        # Consumer / API secret
    access_token: str = ""      # User access token (for the ROT account)
    access_secret: str = ""     # User access token secret
    enabled: bool = False
    interval_s: int = 10800     # 3 hours
    min_confidence: float = 0.5  # Lowered to get posts flowing
    dashboard_url: str = "https://web-production-71423.up.railway.app"


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
    enterprise_price_id: str = ""
    success_url: str = "/dashboard?upgraded=1"
    cancel_url: str = "/pricing"


class TierConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_TIER_")

    free_signal_delay_s: int = 900  # 15 minutes
    free_page_limit: int = 10
    # API is a paid product — zero free calls
    free_api_limit_day: int = 0       # blocked entirely
    pro_api_limit_day: int = 1000     # 50/min burst
    premium_api_limit_day: int = 5000  # 200/min burst
    ultra_api_limit_day: int = 25000   # 500/min burst
    enterprise_api_limit_day: int = 100000  # 2,000/min burst


class SponsoredConfig(BaseSettings):
    """Config for sponsored signal analysis (enterprise feature)."""

    model_config = SettingsConfigDict(env_prefix="ROT_SPONSORED_")

    enabled: bool = False
    max_pending_per_user: int = 10
    auto_analyze: bool = True
    label_text: str = "Sponsored Analysis"


class MLConfig(BaseSettings):
    """Config for ML-based credibility scoring."""

    model_config = SettingsConfigDict(env_prefix="ROT_ML_")

    enabled: bool = True  # ML scoring enabled by default (falls back to heuristic when no model)
    model_path: str = ""  # auto-derived from storage_root if empty
    min_training_samples: int = 100  # minimum resolved signals to train
    retrain_interval_s: int = 86400  # retrain every 24 hours
    min_class_samples: int = 30  # minimum samples per class (win/loss)


class FeedbackConfig(BaseSettings):
    """Config for signal feedback engine (quality analysis + adaptive suppression)."""

    model_config = SettingsConfigDict(env_prefix="ROT_FEEDBACK_")

    enabled: bool = True  # Enable feedback analysis background loop
    analysis_interval_s: int = 21600  # 6 hours between analysis cycles
    suppress_enabled: bool = True  # Enable adaptive signal suppression
    suppress_threshold: float = 0.20  # Suppress categories with win_rate < 20%
    suppress_source_threshold: float = 0.15  # Suppress (event_type, source) with win_rate < 15%
    min_signals_for_suppression: int = 30  # Minimum decided signals before suppression kicks in
    quality_trend_window_days: int = 30  # Rolling window for trend analysis


class UnusualActivityConfig(BaseSettings):
    """Config for unusual activity detection engine."""

    model_config = SettingsConfigDict(env_prefix="ROT_UNUSUAL_")

    scan_interval_s: int = 300  # 5 minutes between scans
    iv_rank_threshold: float = 80.0  # flag if IV rank > 80th percentile
    volume_surge_multiplier: float = 2.0  # flag if volume > 2x average
    oi_surge_pct: float = 20.0  # flag if OI increases > 20%
    skew_std_threshold: float = 2.0  # flag if P/C ratio > 2 std devs from mean
    composite_min_score: float = 40.0  # minimum composite score to store
    history_window_days: int = 20  # rolling window for baselines
    purge_keep_days: int = 90  # days to keep unusual events


class SectorConfig(BaseSettings):
    """Config for sector rotation analysis."""

    model_config = SettingsConfigDict(env_prefix="ROT_SECTOR_")

    min_signals: int = 2  # minimum signals per sector for analysis
    momentum_window_days: int = 30  # rolling window for momentum


class ExportSchedulerConfig(BaseSettings):
    """Config for enterprise export scheduler."""

    model_config = SettingsConfigDict(env_prefix="ROT_EXPORT_")

    scheduler_interval_s: int = 3600  # 1 hour between scheduler checks
    max_rows_per_export: int = 1000000  # max rows per export


class BacktestServerConfig(BaseSettings):
    """Config for backtesting engine server-side limits."""

    model_config = SettingsConfigDict(env_prefix="ROT_BACKTEST_")

    max_signals: int = 5000  # max signals per backtest run
    monte_carlo_sims: int = 1000  # default Monte Carlo simulations
    walk_forward_folds: int = 5  # default walk-forward folds
    optimizer_max_combos: int = 500  # max parameter combinations for grid search


class AgentConfig(BaseSettings):
    """Config for autonomous trading agents."""

    model_config = SettingsConfigDict(env_prefix="ROT_AGENT_")

    enabled: bool = False  # master switch for agent engine
    eval_interval_s: int = 60  # fallback polling interval (primary path is signal callback)
    max_agents_per_user: int = 5  # max agents a single user can create
    max_daily_trades: int = 20  # global daily trade cap across all agents


class ArchiveConfig(BaseSettings):
    """Config for signal archive retention."""

    model_config = SettingsConfigDict(env_prefix="ROT_ARCHIVE_")

    keep_days: int = 365  # how long to keep archived signals (1 year)


class MacroConfig(BaseSettings):
    """Config for macro events & economic calendar engine."""

    model_config = SettingsConfigDict(env_prefix="ROT_MACRO_")

    enabled: bool = True
    calendar_poll_interval_s: int = 3600  # 1 hour
    earnings_poll_interval_s: int = 14400  # 4 hours
    insider_poll_interval_s: int = 7200  # 2 hours
    fomc_poll_interval_s: int = 86400  # daily
    impact_cache_ttl_s: int = 86400  # 1 day
    sec_edgar_user_agent: str = ""  # Required by SEC: "Company admin@email.com"
    earnings_lookback_quarters: int = 12
    insider_min_value: int = 50000  # Min $ value for notable insider trades
    seasonal_lookback_years: int = 10
    purge_keep_days: int = 365  # Keep macro events for 1 year


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
    twitter_ingest: TwitterIngestConfig = Field(default_factory=TwitterIngestConfig)
    twitter: TwitterPosterConfig = Field(default_factory=TwitterPosterConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    stripe: StripeConfig = Field(default_factory=StripeConfig)
    tier_limits: TierConfig = Field(default_factory=TierConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    sponsored: SponsoredConfig = Field(default_factory=SponsoredConfig)
    ml: MLConfig = Field(default_factory=MLConfig)
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)
    backtest_server: BacktestServerConfig = Field(default_factory=BacktestServerConfig)
    unusual: UnusualActivityConfig = Field(default_factory=UnusualActivityConfig)
    sector: SectorConfig = Field(default_factory=SectorConfig)
    export_scheduler: ExportSchedulerConfig = Field(default_factory=ExportSchedulerConfig)
    archive: ArchiveConfig = Field(default_factory=ArchiveConfig)
    macro: MacroConfig = Field(default_factory=MacroConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    storage_root: str = "storage"
    db_path: str = ""  # auto-derived from storage_root if empty

    def model_post_init(self, __context: Any) -> None:
        if not self.db_path:
            self.db_path = f"{self.storage_root}/rot.db"
