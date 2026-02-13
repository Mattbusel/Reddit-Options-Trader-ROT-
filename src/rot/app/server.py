from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict

import uvicorn

from rot.core.config import Settings
from rot.core.logging import JsonlLogger, cleanup_market_cache
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
            max_entries_per_feed=cfg.rss.max_entries_per_feed,
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

    # Store in database (dedup check inside — returns None for duplicates)
    try:
        db = app.state.db
        signal_id = await db.insert_signal(signal_data)
        if not signal_id:
            return  # Duplicate signal, skip broadcast + alerts
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

    # Invalidate fast-changing dashboard caches (trending, leaderboard)
    cache = getattr(app.state, "query_cache", None)
    if cache:
        cache.invalidate("trending_")
        cache.invalidate("leaderboard_")
        cache.invalidate("landing_stats")

    # Dispatch alerts
    if dispatcher and dispatcher.has_channels:
        try:
            await dispatcher.dispatch(signal_data)
        except Exception as e:
            log.error("Alert dispatch failed: %s", e)


async def _price_check_loop(price_checker: PriceChecker, interval_s: int, stop_event: threading.Event):
    """Background task that periodically checks prices for signal performance tracking."""
    log.info("Price check loop starting (interval=%ds)", interval_s)

    # Wait 30s on startup for DB to fully initialize
    for _ in range(30):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

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

                # First: get total counts for the summary (all signals, not deduped)
                async with db.db.execute(
                    """SELECT COUNT(*) as total,
                              SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                              SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                              AVG(confidence) as avg_conf
                       FROM signals WHERE created_at > ?""",
                    (cutoff,),
                ) as cursor:
                    counts = dict(await cursor.fetchone())

                # Second: get deduplicated signals (one per ticker, best confidence)
                # with performance data for price movement info
                async with db.db.execute(
                    """SELECT s.id, s.ticker, s.stance, s.confidence, s.event_type,
                              s.strategy, s.created_at, s.post_title, s.subreddit,
                              s.time_horizon,
                              sp.price_at_signal, sp.price_1h, sp.price_4h, sp.price_1d
                       FROM signals s
                       LEFT JOIN signal_performance sp ON sp.signal_id = s.id
                       WHERE s.created_at > ?
                       GROUP BY s.ticker
                       HAVING s.confidence = MAX(s.confidence)
                       ORDER BY s.confidence DESC
                       LIMIT 15""",
                    (cutoff,),
                ) as cursor:
                    rows = await cursor.fetchall()
                    recent_signals = [dict(r) for r in rows]

                if recent_signals:
                    summary = {
                        "total_signals": counts.get("total", 0) or 0,
                        "bullish_count": counts.get("bullish", 0) or 0,
                        "bearish_count": counts.get("bearish", 0) or 0,
                        "avg_confidence": counts.get("avg_conf", 0) or 0,
                        "unique_tickers": len(recent_signals),
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


async def _x_posting_loop(db, x_poster, interval_s: int, min_confidence: float,
                           dashboard_url: str, stop_event: threading.Event):
    """Background task that posts top signals to X/Twitter every N seconds."""
    from rot.alerts.twitter import format_tweet

    log.info("X posting loop starting (interval=%ds, min_confidence=%.2f)", interval_s, min_confidence)

    # Wait 120s on startup to let signals accumulate
    for _ in range(120):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

    log.info("X posting loop: first check starting after startup delay")

    consecutive_failures = 0
    MAX_X_FAILURES = 5

    while not stop_event.is_set():
        try:
            signal = await db.get_top_signal_for_x_post(min_confidence=min_confidence)
            if signal:
                tweet_text = format_tweet(signal, dashboard_url=dashboard_url)
                tweet_id = await x_poster.post_tweet(tweet_text)
                if tweet_id:
                    consecutive_failures = 0  # Reset on success
                    await db.record_x_post(
                        signal_id=signal["id"],
                        ticker=signal["ticker"],
                        tweet_id=tweet_id,
                        tweet_text=tweet_text,
                    )
                    log.info(
                        "X post: %s (%s, %.0f%% confidence, tweet_id=%s)",
                        signal["ticker"], signal["stance"],
                        signal["confidence"] * 100, tweet_id,
                    )
                    # After successful post, wait the full interval before next post
                    wait_time = interval_s
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_X_FAILURES:
                        log.error(
                            "X posting disabled after %d consecutive failures. "
                            "Check OAuth credentials. Stopping X posting loop.",
                            MAX_X_FAILURES,
                        )
                        return  # Exit the loop entirely
                    log.warning("X post failed for %s (%d/%d)",
                                signal.get("ticker", "?"), consecutive_failures, MAX_X_FAILURES)
                    wait_time = min(900, interval_s)
            else:
                # No qualifying signal — retry sooner (15 min)
                wait_time = min(900, interval_s)
        except Exception as e:
            consecutive_failures += 1
            if consecutive_failures >= MAX_X_FAILURES:
                log.error("X posting loop disabled after %d failures: %s", MAX_X_FAILURES, e)
                return
            log.error("X posting loop error (%d/%d): %s",
                       consecutive_failures, MAX_X_FAILURES, e)
            wait_time = min(900, interval_s)

        for _ in range(wait_time):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("X posting loop stopped")


async def _cleanup_loop(db, storage_root: str, stop_event: threading.Event):
    """Background task that periodically purges old data to keep storage lean.

    Runs every 6 hours:
      - Purge old/duplicate signals, performance, x_posts, referrals, closed paper trades
      - Rotate JSONL log files (keep 7 days)
      - Clean stale market_cache.json entries
      - VACUUM SQLite to reclaim disk space
    NEVER touches: users, subscriptions, email_alert_settings, paper_portfolios
    """
    CLEANUP_INTERVAL = 3600  # 1 hour
    log.info("Cleanup loop starting (interval=%ds)", CLEANUP_INTERVAL)

    # Wait 30s on startup before first cleanup
    for _ in range(30):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

    while not stop_event.is_set():
        try:
            # 1. Database purges
            summary = await db.run_full_cleanup()
            total_deleted = sum(v for v in summary.values() if isinstance(v, int))
            log.info("Cleanup: DB purge complete — %d total rows removed | %s", total_deleted, summary)
        except Exception as e:
            log.error("Cleanup DB purge error: %s", e, exc_info=True)

        try:
            # 2. JSONL log rotation
            jsonl_logger = JsonlLogger(root=storage_root)
            rotation_results = jsonl_logger.rotate(max_age_days=3)
            rotated = sum(rotation_results.values())
            if rotated > 0:
                log.info("Cleanup: JSONL rotation — removed %d old entries across %d files",
                         rotated, len([v for v in rotation_results.values() if v > 0]))
        except Exception as e:
            log.error("Cleanup JSONL rotation error: %s", e, exc_info=True)

        try:
            # 3. Market cache cleanup
            evicted = cleanup_market_cache(storage_root, max_age_days=7)
            if evicted > 0:
                log.info("Cleanup: market cache — evicted %d stale entries", evicted)
        except Exception as e:
            log.error("Cleanup market cache error: %s", e, exc_info=True)

        log.info("Cleanup cycle complete — next run in %dh", CLEANUP_INTERVAL // 3600)

        for _ in range(CLEANUP_INTERVAL):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("Cleanup loop stopped")


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

    # Start X/Twitter posting background task
    x_post_task = None
    if cfg.twitter.enabled:
        from rot.alerts.twitter import XPoster
        x_poster = XPoster(
            api_key=cfg.twitter.api_key,
            api_secret=cfg.twitter.api_secret,
            access_token=cfg.twitter.access_token,
            access_secret=cfg.twitter.access_secret,
        )
        if x_poster.is_configured:
            x_post_task = asyncio.create_task(
                _x_posting_loop(
                    db=app.state.db,
                    x_poster=x_poster,
                    interval_s=cfg.twitter.interval_s,
                    min_confidence=cfg.twitter.min_confidence,
                    dashboard_url=cfg.twitter.dashboard_url,
                    stop_event=stop_event,
                )
            )
            log.info("X posting loop: ACTIVE (interval=%ds)", cfg.twitter.interval_s)
        else:
            log.warning("X posting: ENABLED but credentials missing")
    else:
        log.info("X posting: DISABLED (set ROT_TWITTER_ENABLED=true)")

    # Immediate startup cleanup to reclaim space on Railway restarts
    try:
        startup_summary = await app.state.db.run_full_cleanup()
        log.info("Startup cleanup (DB): %s", startup_summary)
    except Exception as e:
        log.warning("Startup cleanup (DB) failed: %s", e)

    # Aggressive JSONL + JSON state file cleanup on startup
    try:
        jsonl_logger = JsonlLogger(root=cfg.storage_root)
        rotation_results = jsonl_logger.rotate(max_age_days=3)
        rotated = sum(rotation_results.values())
        if rotated > 0:
            log.info("Startup cleanup (JSONL): removed %d old entries", rotated)
        evicted = cleanup_market_cache(cfg.storage_root, max_age_days=7)
        if evicted > 0:
            log.info("Startup cleanup (market cache): evicted %d stale entries", evicted)
    except Exception as e:
        log.warning("Startup cleanup (files) failed: %s", e)

    # Start storage cleanup background task (always active)
    cleanup_task = asyncio.create_task(
        _cleanup_loop(app.state.db, cfg.storage_root, stop_event)
    )
    log.info("Cleanup loop: ACTIVE (every 1h — purge old data, rotate logs, VACUUM)")

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
        cleanup_task.cancel()
        if digest_task:
            digest_task.cancel()
        if x_post_task:
            x_post_task.cancel()
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
