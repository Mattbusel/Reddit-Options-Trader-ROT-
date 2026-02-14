from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

_MODULE_LOAD_START = time.monotonic()

import uvicorn

from rot.core.config import Settings

# Heavy imports are deferred to function scope to speed up module load time.
# This lets uvicorn bind the port before scikit-learn, yfinance, PRAW, etc.
# are imported, so Railway health checks pass during cold start.

log.info("server.py module loaded — uvicorn+Settings import took %.0fms",
         (time.monotonic() - _MODULE_LOAD_START) * 1000)


def _create_pipeline(cfg: Settings, on_signal=None):
    from rot.core.logging import JsonlLogger
    from rot.ingest.reddit_ingestor import RedditIngestor
    from rot.ingest.rss_ingestor import RSSIngestor, RSSFeedConfig
    from rot.ingest.multi_ingestor import MultiSourceIngestor
    from rot.trend.trend_store import TrendStore
    from rot.trend.trend_engine import TrendEngine
    from rot.extract.event_builder import EventBuilder
    from rot.credibility.ml_scorer import MLCredibilityScorer
    from rot.reasoner.reasoner import Reasoner
    from rot.market.trade_builder import TradeBuilder
    from rot.app.runner import PipelineRunner

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
    ml_model_path = cfg.ml.model_path or f"{cfg.storage_root}/credibility_model.pkl"
    cred = MLCredibilityScorer(
        model_path=ml_model_path,
        enabled=cfg.ml.enabled,
    )
    if cred.ml_available:
        log.info("ML credibility scoring: ACTIVE (model: %s)", ml_model_path)
    else:
        log.info("ML credibility scoring: PENDING (will train when data available, heuristic active)")
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

    # Evaluate signal against active trading agents
    agent_engine = getattr(app.state, "agent_engine", None)
    if agent_engine and signal_id:
        try:
            agent_trades = await agent_engine.evaluate_signal(signal_data, signal_id)
            if agent_trades:
                log.info("Agent engine: %d trades executed for signal %s", len(agent_trades), signal_id)
        except Exception as e:
            log.error("Agent engine error: %s", e)

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


async def _ml_retrain_loop(
    db_path: str,
    model_path: str,
    scorer: MLCredibilityScorer,
    cfg_ml,
    stop_event: threading.Event,
):
    """Background task that periodically retrains the ML credibility model.

    On first run (startup), trains immediately if enough data.  Then retrains
    every ``cfg_ml.retrain_interval_s`` seconds.  After each successful train,
    hot-reloads the model into the scorer so live scoring switches over.
    """
    from rot.credibility.train import train_model_from_db

    log.info(
        "ML retrain loop starting (interval=%ds, min_samples=%d)",
        cfg_ml.retrain_interval_s,
        cfg_ml.min_training_samples,
    )

    # Wait 60s on startup for DB to initialize and accumulate first signals
    for _ in range(60):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

    while not stop_event.is_set():
        try:
            success = await train_model_from_db(
                db_path=db_path,
                output_path=model_path,
                min_samples=cfg_ml.min_training_samples,
                min_class_samples=cfg_ml.min_class_samples,
            )
            if success:
                reloaded = scorer.reload(model_path)
                if reloaded:
                    log.info("ML credibility model retrained and hot-reloaded")
                else:
                    log.warning("ML model trained but hot-reload failed")
        except Exception as e:
            log.error("ML retrain error: %s", e, exc_info=True)

        # Sleep until next retrain cycle
        for _ in range(cfg_ml.retrain_interval_s):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("ML retrain loop stopped")


async def _feedback_analysis_loop(
    analyzer,
    ml_scorer,
    cfg_feedback,
    stop_event: threading.Event,
):
    """Background task that periodically runs signal feedback analysis.

    Computes category performance, source reliability, feature importance,
    quality trends, and suppression candidates.  Results are cached in
    the analyzer and read by the Signal Quality dashboard and the suppressor.
    """
    log.info(
        "Feedback analysis loop starting (interval=%ds)",
        cfg_feedback.analysis_interval_s,
    )

    # Wait 120s on startup for DB to accumulate performance data
    for _ in range(120):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

    while not stop_event.is_set():
        try:
            results = await analyzer.run_analysis(
                ml_scorer=ml_scorer,
                days=cfg_feedback.quality_trend_window_days,
                suppress_threshold=cfg_feedback.suppress_threshold,
                min_signals=cfg_feedback.min_signals_for_suppression,
            )
            # Log quality trend alerts
            trend = results.get("quality_trend", {})
            slope = trend.get("slope")
            if slope is not None and slope < -0.02:
                log.warning(
                    "Signal quality DEGRADING: slope=%.3f over %d days",
                    slope,
                    len(trend.get("daily", [])),
                )
            candidates = results.get("suppression_candidates", [])
            if candidates:
                log.info(
                    "Feedback: %d suppression candidates identified",
                    len(candidates),
                )
        except Exception as e:
            log.error("Feedback analysis error: %s", e, exc_info=True)

        for _ in range(cfg_feedback.analysis_interval_s):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("Feedback analysis loop stopped")


async def _unusual_activity_scan_loop(
    db,
    cfg_unusual,
    stop_event: threading.Event,
):
    """Background task that scans recent signals for unusual activity events.

    Runs every ``cfg_unusual.scan_interval_s`` seconds.  Scans the most recent
    signals for IV spikes, volume surges, OI surges, and put/call skew shifts.
    Stores detected events in the ``unusual_events`` table.
    """
    from rot.unusual.detector import UnusualDetector
    from rot.unusual.config import UnusualConfig

    log.info(
        "Unusual activity scan loop starting (interval=%ds)",
        cfg_unusual.scan_interval_s,
    )

    ua_config = UnusualConfig(
        iv_rank_threshold=cfg_unusual.iv_rank_threshold,
        volume_surge_multiplier=cfg_unusual.volume_surge_multiplier,
        oi_surge_pct=cfg_unusual.oi_surge_pct,
        skew_std_threshold=cfg_unusual.skew_std_threshold,
        composite_min_score=cfg_unusual.composite_min_score,
        history_window_days=cfg_unusual.history_window_days,
    )
    detector = UnusualDetector(config=ua_config)

    # Wait 60s on startup for DB/pipeline to initialize
    for _ in range(60):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

    while not stop_event.is_set():
        try:
            # Fetch recent signals (last scan_interval * 2 to avoid gaps)
            cutoff = time.time() - cfg_unusual.scan_interval_s * 2
            async with db.db.execute(
                """SELECT id, ticker, market_data, created_at
                   FROM signals WHERE created_at > ? ORDER BY created_at DESC LIMIT 200""",
                (cutoff,),
            ) as cursor:
                rows = await cursor.fetchall()
                signals = [dict(r) for r in rows]

            if signals:
                events = detector.scan_batch(signals)
                if events:
                    await db.save_unusual_events(events)
                    log.info(
                        "Unusual activity scan: %d events from %d signals",
                        len(events), len(signals),
                    )

            # Periodic purge of old events
            await db.purge_old_unusual_events(keep_days=cfg_unusual.purge_keep_days)

        except Exception as e:
            log.error("Unusual activity scan error: %s", e, exc_info=True)

        for _ in range(cfg_unusual.scan_interval_s):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("Unusual activity scan loop stopped")


async def _export_scheduler_loop(
    db,
    cfg_export,
    stop_event: threading.Event,
):
    """Background task that runs pending scheduled exports.

    Checks for due export jobs every ``cfg_export.scheduler_interval_s`` seconds
    and generates CSV/JSON output for Enterprise users.
    """
    log.info(
        "Export scheduler loop starting (interval=%ds)",
        cfg_export.scheduler_interval_s,
    )

    # Wait 120s on startup
    for _ in range(120):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

    while not stop_event.is_set():
        try:
            # Check for pending export schedules (future: read from export_schedules table)
            # For now this loop is a placeholder that logs readiness
            log.debug("Export scheduler: check cycle (no pending jobs)")
        except Exception as e:
            log.error("Export scheduler error: %s", e, exc_info=True)

        for _ in range(cfg_export.scheduler_interval_s):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("Export scheduler loop stopped")


async def _macro_data_loop(
    db,
    cfg_macro,
    stop_event: threading.Event,
):
    """Background task that periodically refreshes macro event data.

    Runs every ``cfg_macro.calendar_poll_interval_s`` seconds.  Fetches upcoming
    economic calendar events, earnings dates, and insider trade filings.
    Purges stale data per retention config.
    """
    interval = cfg_macro.calendar_poll_interval_s
    log.info("Macro data loop starting (interval=%ds)", interval)

    # Wait 90s on startup for DB to initialize
    for _ in range(90):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

    while not stop_event.is_set():
        # 1. Economic calendar: seed recurring events + ingest RSS
        try:
            from rot.macro.calendar import EconomicCalendar
            from datetime import datetime
            cal = EconomicCalendar(db=db)
            now_dt = datetime.utcnow()
            # Seed current and next month recurring events
            next_month = now_dt.month % 12 + 1
            next_year = now_dt.year + (1 if next_month == 1 else 0)
            cal_count = await cal.seed_events(
                year=now_dt.year, months=[now_dt.month]
            )
            cal_count += await cal.seed_events(
                year=next_year, months=[next_month]
            )
            rss_count = await cal.ingest_from_rss()
            if cal_count or rss_count:
                log.info("Macro calendar refresh: %d seeded, %d from RSS", cal_count, rss_count)
        except Exception as e:
            log.debug("Macro calendar refresh: %s", e)

        # 2. Earnings calendar: fetch from yfinance for top tickers
        try:
            from rot.macro.earnings import EarningsCalendar
            earn = EarningsCalendar(db=db)
            # Fetch earnings for a rotating set of popular tickers
            top_tickers = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN",
                           "META", "GOOGL", "AMD", "SPY", "QQQ"]
            earn_count = await earn.ingest_earnings(top_tickers)
            if earn_count:
                log.info("Earnings calendar refresh: %d events updated", earn_count)
        except Exception as e:
            log.debug("Earnings calendar refresh: %s", e)

        # 3. Insider trades: ingest from SEC EDGAR Form 4
        try:
            from rot.macro.insider import InsiderFeed
            insider = InsiderFeed(db=db)
            insider_count = await insider.ingest_form4()
            congress_count = await insider.ingest_congress()
            if insider_count or congress_count:
                log.info("Insider feed refresh: %d form4, %d congress", insider_count, congress_count)
        except Exception as e:
            log.debug("Insider feed refresh: %s", e)

        try:
            await db.purge_old_macro_events(keep_days=cfg_macro.purge_keep_days)
            await db.purge_old_earnings_events(keep_days=cfg_macro.purge_keep_days)
            await db.purge_old_insider_trades(keep_days=cfg_macro.purge_keep_days)
        except Exception as e:
            log.debug("Macro data purge: %s", e)

        for _ in range(interval):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("Macro data loop stopped")


async def _cleanup_loop(db, storage_root: str, stop_event: threading.Event):
    """Background task that periodically purges old data to keep storage lean.

    Runs every 6 hours:
      - Purge old/duplicate signals, performance, x_posts, referrals, closed paper trades
      - Rotate JSONL log files (keep 7 days)
      - Clean stale market_cache.json entries
      - VACUUM SQLite to reclaim disk space
    NEVER touches: users, subscriptions, email_alert_settings, paper_portfolios
    """
    from rot.core.logging import JsonlLogger
    from rot.core.logging import cleanup_market_cache

    CLEANUP_INTERVAL = 1800  # 30 minutes
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
            evicted = cleanup_market_cache(storage_root, max_age_days=3)
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
    """Run the full server: pipeline thread + uvicorn, sharing ONE event loop.

    IMPORTANT: We start uvicorn FIRST so the port binds quickly and Railway
    health checks pass. All heavy initialization (pipeline, background loops,
    heavy imports like scikit-learn/yfinance/PRAW) happens in _heavy_init()
    which runs as an asyncio task AFTER the server is already listening.
    """
    _t0 = time.monotonic()
    from rot.web.app import create_app, connect_db, register_routes
    log.info("import create_app: %.0fms", (time.monotonic() - _t0) * 1000)

    # Create MINIMAL FastAPI app — just /health endpoint, no DB, no routes
    # This lets uvicorn bind the port in <1s so Railway health checks pass
    _t1 = time.monotonic()
    app = create_app(cfg)
    log.info("create_app(): %.0fms", (time.monotonic() - _t1) * 1000)

    # Placeholders for resources created in _heavy_init — needed for cleanup
    stop_event = threading.Event()
    background_tasks: list = []
    pipeline_thread = None

    async def _heavy_init():
        """All heavy startup work — runs AFTER uvicorn binds the port."""
        nonlocal pipeline_thread

        try:
            await _heavy_init_inner()
        except Exception:
            log.exception("FATAL: _heavy_init() crashed — routes NOT registered")

    async def _heavy_init_inner():
        """Inner implementation — separated so top-level except catches everything."""
        nonlocal pipeline_thread

        # Yield to event loop so uvicorn can bind the port first
        await asyncio.sleep(1)

        from rot.alerts.dispatcher import AlertDispatcher
        from rot.market.price_checker import PriceChecker
        from rot.core.logging import JsonlLogger
        from rot.core.logging import cleanup_market_cache

        log.info("Starting heavy initialization (DB, routes, pipeline, background loops)...")

        # Phase 1: Connect DB + register all routes
        _ti = time.monotonic()
        await connect_db(app)
        log.info("connect_db(): %.0fms", (time.monotonic() - _ti) * 1000)
        _ti = time.monotonic()
        register_routes(app)
        log.info("register_routes(): %.0fms", (time.monotonic() - _ti) * 1000)

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

        # Capture the RUNNING event loop
        loop = asyncio.get_running_loop()

        # Signal callback: bridge sync pipeline thread -> async handlers
        def on_signal(signal_data: Dict[str, Any]):
            try:
                asyncio.run_coroutine_threadsafe(
                    _async_signal_handler(signal_data, app, dispatcher, price_checker),
                    loop,
                )
            except Exception as e:
                log.error("Signal handler error: %s", e)

        # Create pipeline (triggers heavy imports: scikit-learn, yfinance, PRAW, etc.)
        runner = _create_pipeline(cfg, on_signal=on_signal)

        # Start pipeline in background thread
        pipeline_thread = threading.Thread(
            target=run_pipeline_loop,
            args=(runner, cfg.reddit.poll_interval_s, stop_event),
            daemon=True,
            name="pipeline-loop",
        )
        pipeline_thread.start()

        # Start price check background task
        background_tasks.append(asyncio.create_task(
            _price_check_loop(price_checker, cfg.market.price_check_interval_s, stop_event)
        ))

        # Start daily digest email background task
        if email_alerter and email_alerter.is_configured:
            background_tasks.append(asyncio.create_task(
                _digest_email_loop(app.state.db, email_alerter, stop_event)
            ))
            log.info("Digest email loop: ACTIVE")
        else:
            log.info("Digest email loop: DISABLED (no email alerter configured)")

        # Start X/Twitter posting background task
        if cfg.twitter.enabled:
            from rot.alerts.twitter import XPoster
            x_poster = XPoster(
                api_key=cfg.twitter.api_key,
                api_secret=cfg.twitter.api_secret,
                access_token=cfg.twitter.access_token,
                access_secret=cfg.twitter.access_secret,
            )
            if x_poster.is_configured:
                background_tasks.append(asyncio.create_task(
                    _x_posting_loop(
                        db=app.state.db,
                        x_poster=x_poster,
                        interval_s=cfg.twitter.interval_s,
                        min_confidence=cfg.twitter.min_confidence,
                        dashboard_url=cfg.twitter.dashboard_url,
                        stop_event=stop_event,
                    )
                ))
                log.info("X posting loop: ACTIVE (interval=%ds)", cfg.twitter.interval_s)
            else:
                log.warning("X posting: ENABLED but credentials missing")
        else:
            log.info("X posting: DISABLED (set ROT_TWITTER_ENABLED=true)")

        # Start storage cleanup background task (always active)
        background_tasks.append(asyncio.create_task(
            _cleanup_loop(app.state.db, cfg.storage_root, stop_event)
        ))
        log.info("Cleanup loop: ACTIVE (every 30m — purge old data, rotate logs, VACUUM)")

        # Start ML credibility retrain loop
        if cfg.ml.enabled:
            ml_model_path = cfg.ml.model_path or f"{cfg.storage_root}/credibility_model.pkl"
            background_tasks.append(asyncio.create_task(
                _ml_retrain_loop(
                    db_path=cfg.db_path,
                    model_path=ml_model_path,
                    scorer=runner.cred,
                    cfg_ml=cfg.ml,
                    stop_event=stop_event,
                )
            ))
            log.info(
                "ML retrain loop: ACTIVE (interval=%ds, model=%s)",
                cfg.ml.retrain_interval_s,
                ml_model_path,
            )
        else:
            log.info("ML retrain loop: DISABLED (set ROT_ML_ENABLED=true)")

        # Start signal feedback analysis loop
        if cfg.feedback.enabled:
            from rot.feedback.analyzer import FeedbackAnalyzer
            from rot.feedback.suppressor import SignalSuppressor

            feedback_analyzer = FeedbackAnalyzer(db=app.state.db)
            app.state.feedback_analyzer = feedback_analyzer

            if cfg.feedback.suppress_enabled:
                suppressor = SignalSuppressor(
                    analyzer=feedback_analyzer,
                    threshold=cfg.feedback.suppress_threshold,
                    source_threshold=cfg.feedback.suppress_source_threshold,
                    min_signals=cfg.feedback.min_signals_for_suppression,
                    enabled=True,
                )
                runner.suppressor = suppressor
                log.info(
                    "Signal suppressor: ACTIVE (threshold=%.0f%%, source_threshold=%.0f%%, min_signals=%d)",
                    cfg.feedback.suppress_threshold * 100,
                    cfg.feedback.suppress_source_threshold * 100,
                    cfg.feedback.min_signals_for_suppression,
                )
            else:
                log.info("Signal suppressor: DISABLED (set ROT_FEEDBACK_SUPPRESS_ENABLED=true)")

            background_tasks.append(asyncio.create_task(
                _feedback_analysis_loop(
                    analyzer=feedback_analyzer,
                    ml_scorer=runner.cred,
                    cfg_feedback=cfg.feedback,
                    stop_event=stop_event,
                )
            ))
            log.info(
                "Feedback analysis loop: ACTIVE (interval=%ds)",
                cfg.feedback.analysis_interval_s,
            )
        else:
            app.state.feedback_analyzer = None
            log.info("Feedback analysis: DISABLED (set ROT_FEEDBACK_ENABLED=true)")

        # Initialize trading agent engine (Ultra+ feature)
        if cfg.agent.enabled:
            from rot.agents.engine import AgentEngine
            agent_engine = AgentEngine(db=app.state.db)
            app.state.agent_engine = agent_engine
            log.info(
                "Agent engine: ACTIVE (max_agents_per_user=%d, max_daily_trades=%d)",
                cfg.agent.max_agents_per_user,
                cfg.agent.max_daily_trades,
            )
        else:
            app.state.agent_engine = None
            log.info("Agent engine: DISABLED (set ROT_AGENT_ENABLED=true)")

        # Start unusual activity scan loop
        background_tasks.append(asyncio.create_task(
            _unusual_activity_scan_loop(
                db=app.state.db,
                cfg_unusual=cfg.unusual,
                stop_event=stop_event,
            )
        ))
        log.info(
            "Unusual activity scan: ACTIVE (interval=%ds)",
            cfg.unusual.scan_interval_s,
        )

        # Start export scheduler loop
        background_tasks.append(asyncio.create_task(
            _export_scheduler_loop(
                db=app.state.db,
                cfg_export=cfg.export_scheduler,
                stop_event=stop_event,
            )
        ))
        log.info(
            "Export scheduler: ACTIVE (interval=%ds)",
            cfg.export_scheduler.scheduler_interval_s,
        )

        # Start macro data refresh loop
        background_tasks.append(asyncio.create_task(
            _macro_data_loop(
                db=app.state.db,
                cfg_macro=cfg.macro,
                stop_event=stop_event,
            )
        ))
        log.info(
            "Macro data loop: ACTIVE (interval=%ds)",
            cfg.macro.calendar_poll_interval_s,
        )

        # One-time startup tasks
        try:
            recalc_count = await app.state.db.recalculate_stance_aware_gains()
            if recalc_count > 0:
                log.info("Startup: recalculated %d performance records", recalc_count)
        except Exception as e:
            log.warning("Startup recalculation failed: %s", e)

        try:
            startup_summary = await app.state.db.run_full_cleanup()
            log.info("Startup cleanup (DB): %s", startup_summary)
        except Exception as e:
            log.warning("Startup cleanup (DB) failed: %s", e)

        try:
            jsonl_logger = JsonlLogger(root=cfg.storage_root)
            rotation_results = jsonl_logger.rotate(max_age_days=3)
            rotated = sum(rotation_results.values())
            if rotated > 0:
                log.info("Startup cleanup (JSONL): removed %d old entries", rotated)
            evicted = cleanup_market_cache(cfg.storage_root, max_age_days=3)
            if evicted > 0:
                log.info("Startup cleanup (market cache): evicted %d stale entries", evicted)
        except Exception as e:
            log.warning("Startup cleanup (files) failed: %s", e)

        log.info("Heavy initialization complete — all background loops running")

    # Schedule heavy init to run AFTER uvicorn binds the port
    init_task = asyncio.create_task(_heavy_init())

    log.info("Starting ROT server on %s:%d", cfg.web.host, cfg.web.port)
    log.info("Dashboard: http://%s:%d/dashboard", cfg.web.host, cfg.web.port)
    log.info("API: http://%s:%d/api/v1/health", cfg.web.host, cfg.web.port)

    # Run uvicorn as an awaitable inside the CURRENT event loop (no new loop created)
    _t2 = time.monotonic()
    config = uvicorn.Config(
        app,
        host=cfg.web.host,
        port=cfg.web.port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    log.info("uvicorn.Config: %.0fms — about to call server.serve()", (time.monotonic() - _t2) * 1000)
    try:
        await server.serve()
    finally:
        stop_event.set()
        init_task.cancel()
        for task in background_tasks:
            task.cancel()
        # Cancel DB cleanup task if it was started
        cleanup_task = getattr(app.state, "_db_cleanup_task", None)
        if cleanup_task:
            cleanup_task.cancel()
        # Close DB connection
        db = getattr(app.state, "db", None)
        if db:
            try:
                await db.close()
            except Exception:
                pass
        if pipeline_thread:
            pipeline_thread.join(timeout=5)
        log.info("ROT server stopped")


def main():
    import os
    _t0 = time.monotonic()
    cfg = Settings()
    # Railway sets PORT env var dynamically — override config if present
    railway_port = os.environ.get("PORT")
    if railway_port:
        cfg.web.port = int(railway_port)
    log.info("Server main() entry — Settings loaded in %.1fms", (time.monotonic() - _t0) * 1000)
    asyncio.run(_run_server(cfg))


if __name__ == "__main__":
    main()
