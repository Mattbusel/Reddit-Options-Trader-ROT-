from __future__ import annotations

import time

from rot.core.config import Settings
from rot.core.logging import JsonlLogger
from rot.ingest.reddit_ingestor import RedditIngestor
from rot.ingest.rss_ingestor import RSSIngestor, RSSFeedConfig
from rot.ingest.stocktwits_ingestor import StockTwitsIngestor
from rot.ingest.twitter_ingestor import TwitterIngestor
from rot.ingest.multi_ingestor import MultiSourceIngestor
from rot.trend.trend_store import TrendStore
from rot.trend.trend_engine import TrendEngine
from rot.extract.event_builder import EventBuilder
from rot.credibility.scorer import CredibilityScorer
from rot.reasoner.reasoner import Reasoner
from rot.market.trade_builder import TradeBuilder
from rot.app.runner import PipelineRunner


def loop() -> None:
    cfg = Settings()

    logger = JsonlLogger(root=cfg.storage_root)

    reddit_ingestor = RedditIngestor(
        subreddits=cfg.reddit.subreddits,
        listing=cfg.reddit.listing,
        limit_per_sub=cfg.reddit.limit_per_sub,
        include_comments=cfg.reddit.include_comments,
        top_comments=cfg.reddit.top_comments,
        state_path=f"{cfg.storage_root}/seen_posts.json",
    )

    sources = [reddit_ingestor]

    rss_active = cfg.rss.enabled and bool(cfg.rss.feeds)
    if rss_active:
        feed_configs = [
            RSSFeedConfig(url=f.url, label=f.label, poll_interval_s=cfg.rss.poll_interval_s)
            for f in cfg.rss.feeds
            if f.url
        ]
        rss_ingestor = RSSIngestor(
            feeds=feed_configs,
            state_path=f"{cfg.storage_root}/seen_rss.json",
            max_entries_per_feed=cfg.rss.max_entries_per_feed,
        )
        sources.append(rss_ingestor)
        print(f"📡 RSS feeds: ACTIVE ({len(feed_configs)} feeds)")

    stocktwits_active = cfg.stocktwits.enabled
    if stocktwits_active:
        stocktwits_ingestor = StockTwitsIngestor(
            symbols=cfg.stocktwits.symbols,
            state_path=f"{cfg.storage_root}/seen_stocktwits.json",
            trending_enabled=cfg.stocktwits.trending_enabled,
        )
        sources.append(stocktwits_ingestor)
        print(f"📊 StockTwits: ACTIVE ({len(cfg.stocktwits.symbols)} symbols)")

    twitter_active = cfg.twitter_ingest.enabled and bool(cfg.twitter_ingest.bearer_token)
    if twitter_active:
        twitter_ingestor = TwitterIngestor(
            bearer_token=cfg.twitter_ingest.bearer_token,
            cashtags=cfg.twitter_ingest.cashtags,
            accounts=cfg.twitter_ingest.accounts,
            state_path=f"{cfg.storage_root}/seen_twitter.json",
            max_results=cfg.twitter_ingest.max_results,
        )
        sources.append(twitter_ingestor)
        print(f"🐦 Twitter/X ingest: ACTIVE ({len(cfg.twitter_ingest.cashtags)} cashtags, {len(cfg.twitter_ingest.accounts)} accounts)")

    ingestor = MultiSourceIngestor(sources) if len(sources) > 1 else sources[0]

    trend_engine = TrendEngine(
        store=TrendStore(path=f"{cfg.storage_root}/trend_state.json"),
        window_s=cfg.trend.window_s,
        threshold=cfg.trend.threshold,
        comment_weight=cfg.trend.comment_weight,
        rss_bypass=rss_active,
        rss_max_age_s=cfg.rss.max_age_s,
        rss_synthetic_score=cfg.rss.synthetic_trend_score,
        stocktwits_bypass=stocktwits_active,
        twitter_bypass=twitter_active,
    )
    event_builder = EventBuilder()
    cred = CredibilityScorer()
    reasoner = Reasoner(
        provider=cfg.llm.provider,
        api_key=cfg.llm.api_key,
        model=cfg.llm.model,
        base_url=cfg.llm.base_url,
        max_tokens=cfg.llm.max_tokens,
        temperature=cfg.llm.temperature,
    )
    trade_builder = TradeBuilder()

    runner = PipelineRunner(
        ingestor=ingestor,
        trend_engine=trend_engine,
        event_builder=event_builder,
        cred=cred,
        reasoner=reasoner,
        trade_builder=trade_builder,
        logger=logger,
        top_n=cfg.trend.top_n,
    )

    if reasoner.llm_available:
        print("🧠 LLM reasoning: ACTIVE")
    else:
        print("⚠️  LLM reasoning: FALLBACK (set ROT_LLM_API_KEY to enable)")

    while True:
        summary = runner.run_once()
        print(
            f"✅ {summary['run_id']} | snapshots={summary['snapshots']} "
            f"candidates={summary['candidates']} ticker_candidates={summary['ticker_candidates']} "
            f"events={summary['events']} ideas={summary['trade_ideas']} "
            f"top_all={summary['top_signals']} top_ticker={summary['top_ticker_signals']}"
        )
        time.sleep(cfg.reddit.poll_interval_s)


if __name__ == "__main__":
    loop()
