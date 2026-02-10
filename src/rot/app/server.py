from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict

import uvicorn

from rot.core.config import Settings
from rot.core.logging import JsonlLogger
from rot.ingest.reddit_ingestor import RedditIngestor
from rot.ingest.rss_ingestor import RSSIngestor, RSSFeedConfig
from rot.ingest.multi_ingestor import MultiSourceIngestor
from rot.trend.trend_store import TrendStore
from rot.trend.trend_engine import TrendEngine
from rot.extract.event_builder import EventBuilder
from rot.credibility.scorer import CredibilityScorer
from rot.reasoner.reasoner import Reasoner
from rot.market.trade_builder import TradeBuilder
from rot.app.runner import PipelineRunner
from rot.web.app import create_app
from rot.alerts.dispatcher import AlertDispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)


def _create_pipeline(cfg: Settings, on_signal=None) -> PipelineRunner:
    logger = JsonlLogger(root=cfg.storage_root)

    # Reddit ingestor (always created)
    reddit_ingestor = RedditIngestor(
        subreddits=cfg.reddit.subreddits,
        listing=cfg.reddit.listing,
        limit_per_sub=cfg.reddit.limit_per_sub,
        include_comments=cfg.reddit.include_comments,
        top_comments=cfg.reddit.top_comments,
        state_path=f"{cfg.storage_root}/seen_posts.json",
    )

    # Combined ingestor: Reddit + optional RSS
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
        )
        ingestor = MultiSourceIngestor([reddit_ingestor, rss_ingestor])
        log.info("RSS feeds: ACTIVE (%d feeds)", len(feed_configs))
    else:
        ingestor = reddit_ingestor
        log.info("RSS feeds: DISABLED (set ROT_RSS_ENABLED=true)")

    trend_engine = TrendEngine(
        store=TrendStore(path=f"{cfg.storage_root}/trend_state.json"),
        window_s=cfg.trend.window_s,
        threshold=cfg.trend.threshold,
        comment_weight=cfg.trend.comment_weight,
        rss_bypass=rss_active,
        rss_max_age_s=cfg.rss.max_age_s,
        rss_synthetic_score=cfg.rss.synthetic_trend_score,
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
    trade_builder = TradeBuilder(min_market_cap=cfg.market.min_market_cap)

    if reasoner.llm_available:
        log.info("LLM reasoning: ACTIVE (%s / %s)", cfg.llm.provider, cfg.llm.model)
    else:
        log.warning("LLM reasoning: FALLBACK (set ROT_LLM_API_KEY to enable)")

    return PipelineRunner(
        ingestor=ingestor,
        trend_engine=trend_engine,
        event_builder=event_builder,
        cred=cred,
        reasoner=reasoner,
        trade_builder=trade_builder,
        logger=logger,
        top_n=cfg.trend.top_n,
        on_signal=on_signal,
    )


def run_pipeline_loop(runner: PipelineRunner, interval_s: int, stop_event: threading.Event):
    """Run the pipeline in a loop until stop_event is set."""
    log.info("Pipeline loop starting (interval=%ds)", interval_s)
    while not stop_event.is_set():
        try:
            summary = runner.run_once()
            log.info(
                "Pipeline cycle: %s | snapshots=%d candidates=%d events=%d ideas=%d",
                summary["run_id"],
                summary["snapshots"],
                summary["candidates"],
                summary["events"],
                summary["trade_ideas"],
            )
        except Exception as e:
            log.error("Pipeline error: %s", e, exc_info=True)

        stop_event.wait(timeout=interval_s)
    log.info("Pipeline loop stopped")


async def _async_signal_handler(
    signal_data: Dict[str, Any],
    app,
    dispatcher: AlertDispatcher | None,
):
    """Handle a signal asynchronously: store in DB, broadcast via WebSocket, dispatch alerts."""
    from rot.web.routes.websocket import broadcast_signal

    # Store in database
    try:
        db = app.state.db
        signal_id = await db.insert_signal(signal_data)
        log.info("Signal stored: %s", signal_id)
    except Exception as e:
        log.error("Failed to store signal: %s", e)

    # Broadcast via WebSocket
    try:
        await broadcast_signal(signal_data)
    except Exception as e:
        log.error("WebSocket broadcast failed: %s", e)

    # Dispatch alerts
    if dispatcher and dispatcher.has_channels:
        try:
            await dispatcher.dispatch(signal_data)
        except Exception as e:
            log.error("Alert dispatch failed: %s", e)


async def _run_server(cfg: Settings):
    """Run the full server: pipeline thread + uvicorn, sharing ONE event loop."""
    # Create FastAPI app
    app = create_app(cfg)

    # Create alert dispatcher
    dispatcher = AlertDispatcher(
        discord_webhook_url=cfg.alert.discord_webhook_url,
        min_confidence=cfg.alert.min_confidence,
        dashboard_url=f"http://{cfg.web.host}:{cfg.web.port}",
    )

    if dispatcher.has_channels:
        log.info("Discord alerting: ACTIVE (min_confidence=%.2f)", cfg.alert.min_confidence)
    else:
        log.info("Discord alerting: DISABLED (set ROT_ALERT_DISCORD_WEBHOOK_URL to enable)")

    # Capture the RUNNING event loop — uvicorn.Server.serve() will use this same loop
    loop = asyncio.get_running_loop()

    # Signal callback: bridge sync pipeline thread -> async handlers on the running loop
    def on_signal(signal_data: Dict[str, Any]):
        try:
            asyncio.run_coroutine_threadsafe(
                _async_signal_handler(signal_data, app, dispatcher),
                loop,
            )
        except Exception as e:
            log.error("Signal handler error: %s", e)

    # Create pipeline
    runner = _create_pipeline(cfg, on_signal=on_signal)

    # Start pipeline in background thread
    stop_event = threading.Event()
    pipeline_thread = threading.Thread(
        target=run_pipeline_loop,
        args=(runner, cfg.reddit.poll_interval_s, stop_event),
        daemon=True,
        name="pipeline-loop",
    )
    pipeline_thread.start()

    log.info("Starting ROT server on %s:%d", cfg.web.host, cfg.web.port)
    log.info("Dashboard: http://%s:%d/dashboard", cfg.web.host, cfg.web.port)
    log.info("API: http://%s:%d/api/v1/health", cfg.web.host, cfg.web.port)

    # Run uvicorn as an awaitable inside the CURRENT event loop (no new loop created)
    config = uvicorn.Config(
        app,
        host=cfg.web.host,
        port=cfg.web.port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        stop_event.set()
        pipeline_thread.join(timeout=5)
        log.info("ROT server stopped")


def main():
    import os
    cfg = Settings()
    # Railway sets PORT env var dynamically — override config if present
    railway_port = os.environ.get("PORT")
    if railway_port:
        cfg.web.port = int(railway_port)
    asyncio.run(_run_server(cfg))


if __name__ == "__main__":
    main()
