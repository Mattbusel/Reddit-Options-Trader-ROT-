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
from rot.market.price_checker import PriceChecker

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
    price_checker: PriceChecker | None = None,
):
    """Handle a signal asynchronously: store in DB, broadcast via WebSocket, dispatch alerts."""
    from rot.web.routes.websocket import broadcast_signal

    signal_id = None

    # Store in database
    try:
        db = app.state.db
        signal_id = await db.insert_signal(signal_data)
        log.info("Signal stored: %s", signal_id)
    except Exception as e:
        log.error("Failed to store signal: %s", e)

    # Record initial price for performance tracking
    if signal_id and price_checker:
        try:
            event = signal_data.get("event")
            if hasattr(event, "entities"):
                entities = event.entities
            elif isinstance(event, dict):
                entities = event.get("entities", [])
            else:
                entities = []
            ticker = entities[0] if entities else None
            if ticker and ticker != "UNKNOWN":
                await price_checker.record_initial_price(signal_id, ticker)
        except Exception as e:
            log.error("Price recording failed: %s", e)

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


async def _price_check_loop(price_checker: PriceChecker, interval_s: int, stop_event: threading.Event):
    """Background task that periodically checks prices for signal performance tracking."""
    log.info("Price check loop starting (interval=%ds)", interval_s)
    while not stop_event.is_set():
        try:
            updated = await price_checker.check_pending_prices()
            if updated > 0:
                log.info("Price check cycle: updated %d records", updated)
        except Exception as e:
            log.error("Price check error: %s", e, exc_info=True)

        # Sleep using asyncio but check stop_event
        for _ in range(interval_s):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("Price check loop stopped")


async def _digest_email_loop(db, email_alerter, stop_event: threading.Event):
    """Background task that sends daily digest emails to subscribed users."""
    DIGEST_INTERVAL = 3600  # Check every hour if digests need sending
    log.info("Digest email loop starting (check interval=%ds)", DIGEST_INTERVAL)

    # Wait 60s on startup before first check to let server fully initialize
    for _ in range(60):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

    while not stop_event.is_set():
        try:
            users = await db.get_users_for_digest()
            if users:
                # Get recent signals for digest (last 24h)
                cutoff = time.time() - 86400
                async with db.db.execute(
                    """SELECT id, ticker, stance, confidence, event_type, strategy,
                              created_at, post_title, subreddit
                       FROM signals WHERE created_at > ?
                       ORDER BY confidence DESC LIMIT 25""",
                    (cutoff,),
                ) as cursor:
                    rows = await cursor.fetchall()
                    recent_signals = [dict(r) for r in rows]

                if recent_signals:
                    summary = {
                        "total_signals": len(recent_signals),
                        "top_tickers": list(set(s.get("ticker", "") for s in recent_signals[:10])),
                        "avg_confidence": sum(s.get("confidence", 0) for s in recent_signals) / len(recent_signals),
                    }

                    sent = 0
                    for u in users:
                        email_addr = u.get("email", "")
                        if email_addr:
                            try:
                                ok = await email_alerter.send_daily_digest(email_addr, recent_signals, summary)
                                if ok:
                                    await db.update_digest_sent(u["id"])
                                    sent += 1
                            except Exception as e:
                                log.error("Digest to %s failed: %s", email_addr, e)
                    if sent > 0:
                        log.info("Daily digest: sent to %d users", sent)
                else:
                    log.debug("Digest: no recent signals to send")
        except Exception as e:
            log.error("Digest email loop error: %s", e, exc_info=True)

        for _ in range(DIGEST_INTERVAL):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("Digest email loop stopped")


async def _run_server(cfg: Settings):
    """Run the full server: pipeline thread + uvicorn, sharing ONE event loop."""
    # Create FastAPI app
    app = create_app(cfg)

    # Create email alerter if configured
    email_alerter = None
    if cfg.email.enabled and (cfg.email.resend_api_key or cfg.email.smtp_host):
        from rot.alerts.email import EmailAlerter
        email_alerter = EmailAlerter(
            smtp_host=cfg.email.smtp_host,
            smtp_port=cfg.email.smtp_port,
            smtp_user=cfg.email.smtp_user,
            smtp_password=cfg.email.smtp_password,
            from_address=cfg.email.from_address,
            use_ssl=cfg.email.use_ssl,
            resend_api_key=cfg.email.resend_api_key,
        )
        if cfg.email.resend_api_key:
            log.info("Email alerter: ACTIVE (backend=Resend HTTP API, from=%s)", cfg.email.from_address)
        else:
            ssl_mode = "SSL" if cfg.email.use_ssl or cfg.email.smtp_port == 465 else "STARTTLS"
            log.info("Email alerter: ACTIVE (backend=SMTP %s:%d mode=%s)", cfg.email.smtp_host, cfg.email.smtp_port, ssl_mode)
    else:
        log.info("Email alerter: DISABLED (set ROT_EMAIL_ENABLED=true + ROT_EMAIL_RESEND_API_KEY)")

    # Store email alerter on app state so routes can send emails (e.g. password reset)
    app.state.email_alerter = email_alerter

    # Create alert dispatcher
    dispatcher = AlertDispatcher(
        discord_webhook_url=cfg.alert.discord_webhook_url,
        min_confidence=cfg.alert.min_confidence,
        dashboard_url=f"http://{cfg.web.host}:{cfg.web.port}",
        db=app.state.db,
        email_alerter=email_alerter,
    )

    if dispatcher.has_channels:
        log.info("Alert dispatching: ACTIVE (min_confidence=%.2f)", cfg.alert.min_confidence)
    else:
        log.info("Alert dispatching: DISABLED (no channels configured)")

    # Create price checker for performance tracking
    price_checker = PriceChecker(
        db=app.state.db,
        batch_size=cfg.market.price_check_batch_size,
    )
    log.info("Price checker: ACTIVE (interval=%ds, batch=%d)",
             cfg.market.price_check_interval_s, cfg.market.price_check_batch_size)

    # One-time recalculation of stance-aware gains for old records
    try:
        recalc_count = await app.state.db.recalculate_stance_aware_gains()
        if recalc_count > 0:
            log.info("Startup: recalculated %d performance records", recalc_count)
    except Exception as e:
        log.warning("Startup recalculation failed: %s", e)

    # Capture the RUNNING event loop — uvicorn.Server.serve() will use this same loop
    loop = asyncio.get_running_loop()

    # Signal callback: bridge sync pipeline thread -> async handlers on the running loop
    def on_signal(signal_data: Dict[str, Any]):
        try:
            asyncio.run_coroutine_threadsafe(
                _async_signal_handler(signal_data, app, dispatcher, price_checker),
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

    # Start price check background task
    price_check_task = asyncio.create_task(
        _price_check_loop(price_checker, cfg.market.price_check_interval_s, stop_event)
    )

    # Start daily digest email background task
    digest_task = None
    if email_alerter and email_alerter.is_configured:
        digest_task = asyncio.create_task(
            _digest_email_loop(app.state.db, email_alerter, stop_event)
        )
        log.info("Digest email loop: ACTIVE")
    else:
        log.info("Digest email loop: DISABLED (no email alerter configured)")

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
        price_check_task.cancel()
        if digest_task:
            digest_task.cancel()
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
