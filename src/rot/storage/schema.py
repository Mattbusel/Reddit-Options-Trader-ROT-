"""
Database schema definitions for ROT.

All CREATE TABLE and CREATE INDEX statements extracted from the original database.py monolith.
Used by the migration system in base.py.

Exports:
    SCHEMA_SQL: List of DDL statements to create all tables and indexes
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'other',
    stance TEXT NOT NULL DEFAULT 'unknown',
    time_horizon TEXT NOT NULL DEFAULT 'unknown',
    confidence REAL NOT NULL DEFAULT 0.0,
    trend_score REAL NOT NULL DEFAULT 0.0,
    quality_score REAL NOT NULL DEFAULT 0.0,
    strategy TEXT NOT NULL DEFAULT 'none',
    subreddit TEXT NOT NULL DEFAULT '',
    post_title TEXT NOT NULL DEFAULT '',
    post_url TEXT NOT NULL DEFAULT '',
    market_data TEXT NOT NULL DEFAULT '{}',
    reasoning TEXT NOT NULL DEFAULT '{}',
    trade_idea TEXT NOT NULL DEFAULT '{}',
    event_data TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_confidence ON signals(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_signals_stance ON signals(stance);
CREATE INDEX IF NOT EXISTS idx_signals_dedup ON signals(post_url, ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_signals_event_type ON signals(event_type);
CREATE INDEX IF NOT EXISTS idx_signals_strategy ON signals(strategy);

CREATE TABLE IF NOT EXISTS signal_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL REFERENCES signals(id),
    ticker TEXT NOT NULL,
    price_at_signal REAL,
    price_1h REAL,
    price_4h REAL,
    price_1d REAL,
    price_1w REAL,
    max_gain_pct REAL,
    max_loss_pct REAL,
    checked_at REAL
);

CREATE INDEX IF NOT EXISTS idx_perf_signal ON signal_performance(signal_id);
CREATE INDEX IF NOT EXISTS idx_perf_ticker ON signal_performance(ticker);
CREATE INDEX IF NOT EXISTS idx_perf_checked ON signal_performance(checked_at);
CREATE INDEX IF NOT EXISTS idx_signals_created_ticker ON signals(created_at DESC, ticker);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    api_key_hash TEXT UNIQUE,
    tier TEXT NOT NULL DEFAULT 'free',
    created_at REAL NOT NULL,
    settings TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key_hash);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    called_at REAL NOT NULL,
    ip_address TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_api_usage_user_day ON api_usage(user_id, called_at);

CREATE TABLE IF NOT EXISTS auth_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_address TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    attempted_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_attempts_lookup ON auth_attempts(ip_address, endpoint, attempted_at);

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL REFERENCES users(id),
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    tier TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'active',
    current_period_end REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe ON subscriptions(stripe_subscription_id);

CREATE TABLE IF NOT EXISTS email_alert_settings (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    enabled INTEGER NOT NULL DEFAULT 0,
    digest_enabled INTEGER NOT NULL DEFAULT 1,
    realtime_enabled INTEGER NOT NULL DEFAULT 0,
    min_confidence REAL NOT NULL DEFAULT 0.6,
    tickers TEXT NOT NULL DEFAULT '[]',
    stances TEXT NOT NULL DEFAULT '[]',
    event_types TEXT NOT NULL DEFAULT '[]',
    last_digest_at REAL NOT NULL DEFAULT 0,
    webhook_url TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS x_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    tweet_id TEXT NOT NULL DEFAULT '',
    tweet_text TEXT NOT NULL DEFAULT '',
    posted_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_x_posts_posted ON x_posts(posted_at DESC);

CREATE TABLE IF NOT EXISTS referral_clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_code TEXT NOT NULL,
    ip_address TEXT NOT NULL DEFAULT '',
    clicked_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_referral_clicks_code ON referral_clicks(ref_code);

CREATE TABLE IF NOT EXISTS referral_conversions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_code TEXT NOT NULL,
    referred_user_id TEXT NOT NULL,
    converted_at REAL NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    commission_amount REAL NOT NULL DEFAULT 0.0,
    paid_out INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_referral_conv_code ON referral_conversions(ref_code);

CREATE TABLE IF NOT EXISTS sponsored_signals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    ticker TEXT NOT NULL DEFAULT '',
    press_url TEXT NOT NULL DEFAULT '',
    press_content TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    signal_id TEXT DEFAULT NULL,
    created_at REAL NOT NULL,
    analyzed_at REAL DEFAULT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sponsored_user ON sponsored_signals(user_id);
CREATE INDEX IF NOT EXISTS idx_sponsored_status ON sponsored_signals(status);
CREATE INDEX IF NOT EXISTS idx_sponsored_created ON sponsored_signals(created_at DESC);

CREATE TABLE IF NOT EXISTS data_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    export_type TEXT NOT NULL DEFAULT 'signals',
    format TEXT NOT NULL DEFAULT 'csv',
    requested_at REAL NOT NULL,
    completed_at REAL DEFAULT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    filters TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_data_exports_user ON data_exports(user_id);

CREATE TABLE IF NOT EXISTS paper_portfolios (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    balance REAL NOT NULL DEFAULT 10000.0,
    initial_balance REAL NOT NULL DEFAULT 10000.0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    total_pnl REAL NOT NULL DEFAULT 0.0,
    last_trade_at REAL
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    signal_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    stance TEXT NOT NULL DEFAULT 'unknown',
    entry_price REAL NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    paper_balance_after REAL NOT NULL,
    created_at REAL NOT NULL,
    closed_at REAL,
    exit_price REAL,
    pnl_dollars REAL,
    pnl_pct REAL,
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_user ON paper_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);

CREATE TABLE IF NOT EXISTS win_rate_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at REAL NOT NULL,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,
    winners INTEGER NOT NULL DEFAULT 0,
    losers INTEGER NOT NULL DEFAULT 0,
    neutral INTEGER NOT NULL DEFAULT 0,
    total_tracked INTEGER NOT NULL DEFAULT 0,
    avg_gain_pct REAL,
    avg_loss_pct REAL,
    avg_1d_return_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_wr_snapshot_at ON win_rate_snapshots(snapshot_at DESC);

CREATE TABLE IF NOT EXISTS congress_trades (
    id TEXT PRIMARY KEY,
    politician TEXT NOT NULL DEFAULT '',
    party TEXT NOT NULL DEFAULT '',
    chamber TEXT NOT NULL DEFAULT '',
    ticker TEXT NOT NULL DEFAULT '',
    trade_type TEXT NOT NULL DEFAULT '',
    amount_range TEXT NOT NULL DEFAULT '',
    filed_at REAL NOT NULL,
    disclosure_date TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_congress_ticker ON congress_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_congress_filed ON congress_trades(filed_at DESC);
CREATE INDEX IF NOT EXISTS idx_congress_politician ON congress_trades(politician);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    monte_carlo_json TEXT NOT NULL DEFAULT '{}',
    risk_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_user ON backtest_runs(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_strategies (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    last_result_json TEXT NOT NULL DEFAULT '{}',
    last_run_at REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_backtest_strats_user ON backtest_strategies(user_id, is_active, created_at DESC);

CREATE TABLE IF NOT EXISTS unusual_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.0,
    details_json TEXT NOT NULL DEFAULT '{}',
    signal_id TEXT DEFAULT NULL,
    detected_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_unusual_ticker ON unusual_events(ticker);
CREATE INDEX IF NOT EXISTS idx_unusual_type ON unusual_events(event_type);
CREATE INDEX IF NOT EXISTS idx_unusual_detected ON unusual_events(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_unusual_score ON unusual_events(score DESC);
CREATE INDEX IF NOT EXISTS idx_unusual_signal ON unusual_events(signal_id);

CREATE TABLE IF NOT EXISTS signal_archive (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'other',
    stance TEXT NOT NULL DEFAULT 'unknown',
    strategy TEXT NOT NULL DEFAULT 'none',
    confidence REAL NOT NULL DEFAULT 0.5,
    subreddit TEXT NOT NULL DEFAULT '',
    quality_score REAL NOT NULL DEFAULT 0.0,
    sector TEXT NOT NULL DEFAULT '',
    post_title TEXT NOT NULL DEFAULT '',
    price_at_signal REAL NOT NULL DEFAULT 0.0,
    price_1h REAL,
    price_4h REAL,
    price_1d REAL,
    max_gain_pct REAL,
    max_loss_pct REAL,
    archived_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_archive_created ON signal_archive(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_archive_ticker ON signal_archive(ticker);
CREATE INDEX IF NOT EXISTS idx_archive_event_type ON signal_archive(event_type);
CREATE INDEX IF NOT EXISTS idx_archive_stance ON signal_archive(stance);
CREATE INDEX IF NOT EXISTS idx_archive_strategy ON signal_archive(strategy);
CREATE INDEX IF NOT EXISTS idx_archive_subreddit ON signal_archive(subreddit);

CREATE TABLE IF NOT EXISTS macro_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    name TEXT NOT NULL,
    scheduled_at REAL NOT NULL,
    actual_at REAL,
    country TEXT DEFAULT 'US',
    importance TEXT DEFAULT 'medium',
    category TEXT NOT NULL,
    consensus_value REAL,
    actual_value REAL,
    previous_value REAL,
    surprise_pct REAL,
    affected_sectors TEXT DEFAULT '[]',
    affected_tickers TEXT DEFAULT '[]',
    source TEXT DEFAULT '',
    meta TEXT DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0,
    has_actual INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_macro_scheduled ON macro_events(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_macro_type_sched ON macro_events(event_type, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_macro_category ON macro_events(category);
CREATE INDEX IF NOT EXISTS idx_macro_importance ON macro_events(importance);

CREATE TABLE IF NOT EXISTS earnings_events (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    report_date REAL NOT NULL,
    fiscal_quarter TEXT DEFAULT '',
    eps_estimate REAL,
    eps_actual REAL,
    revenue_estimate REAL,
    revenue_actual REAL,
    surprise_pct REAL,
    expected_move_pct REAL,
    actual_move_pct REAL,
    iv_before REAL,
    iv_after REAL,
    iv_crush_pct REAL,
    meta TEXT DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_earnings_ticker_date ON earnings_events(ticker, report_date);
CREATE INDEX IF NOT EXISTS idx_earnings_date ON earnings_events(report_date);

CREATE TABLE IF NOT EXISTS insider_trades (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    insider_name TEXT NOT NULL,
    title TEXT DEFAULT '',
    trade_type TEXT NOT NULL,
    shares INTEGER DEFAULT 0,
    price REAL DEFAULT 0.0,
    value REAL DEFAULT 0.0,
    filing_date REAL NOT NULL,
    transaction_date REAL,
    source TEXT NOT NULL DEFAULT 'form4',
    meta TEXT DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_insider_ticker ON insider_trades(ticker, filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_insider_source ON insider_trades(source, filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_insider_value ON insider_trades(value DESC);
CREATE INDEX IF NOT EXISTS idx_insider_type ON insider_trades(trade_type);

CREATE TABLE IF NOT EXISTS fomc_meetings (
    id TEXT PRIMARY KEY,
    meeting_date REAL NOT NULL,
    rate_decision TEXT DEFAULT '',
    rate_before REAL DEFAULT 0.0,
    rate_after REAL DEFAULT 0.0,
    statement_text TEXT DEFAULT '',
    statement_diff TEXT DEFAULT '',
    hawkish_score REAL DEFAULT 0.0,
    dovish_score REAL DEFAULT 0.0,
    dot_plot_median REAL,
    meta TEXT DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_fomc_date ON fomc_meetings(meeting_date);

CREATE TABLE IF NOT EXISTS event_impact_cache (
    event_type TEXT PRIMARY KEY,
    avg_spy_move REAL DEFAULT 0.0,
    avg_vix_change REAL DEFAULT 0.0,
    sample_size INTEGER DEFAULT 0,
    reactions_json TEXT DEFAULT '[]',
    sector_sensitivity_json TEXT DEFAULT '[]',
    computed_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trading_agents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL DEFAULT '',
    agent_type TEXT NOT NULL DEFAULT 'signal_follower',
    status TEXT NOT NULL DEFAULT 'active',
    rules_json TEXT NOT NULL DEFAULT '[]',
    config_json TEXT NOT NULL DEFAULT '{}',
    min_confidence REAL NOT NULL DEFAULT 0.4,
    max_daily_trades INTEGER NOT NULL DEFAULT 5,
    max_position_dollars REAL NOT NULL DEFAULT 2000.0,
    max_portfolio_exposure_pct REAL NOT NULL DEFAULT 50.0,
    stop_loss_pct REAL NOT NULL DEFAULT 10.0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agents_user ON trading_agents(user_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON trading_agents(status);

CREATE TABLE IF NOT EXISTS agent_trades (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES trading_agents(id),
    user_id TEXT NOT NULL,
    signal_id TEXT DEFAULT NULL,
    ticker TEXT NOT NULL,
    stance TEXT NOT NULL DEFAULT 'unknown',
    entry_price REAL NOT NULL DEFAULT 0.0,
    quantity REAL NOT NULL DEFAULT 1,
    dollars REAL NOT NULL DEFAULT 0.0,
    created_at REAL NOT NULL,
    closed_at REAL,
    exit_price REAL,
    pnl_dollars REAL,
    pnl_pct REAL,
    status TEXT NOT NULL DEFAULT 'open',
    paper_trade_id TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_trades_agent ON agent_trades(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_trades_user ON agent_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_trades_status ON agent_trades(status);
CREATE INDEX IF NOT EXISTS idx_agent_trades_created ON agent_trades(created_at DESC);

CREATE TABLE IF NOT EXISTS flow_events (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    flow_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    premium REAL NOT NULL DEFAULT 0.0,
    volume INTEGER NOT NULL DEFAULT 0,
    oi_change INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0.0,
    details_json TEXT NOT NULL DEFAULT '{}',
    signal_id TEXT DEFAULT NULL,
    detected_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_flow_events_ticker ON flow_events(ticker);
CREATE INDEX IF NOT EXISTS idx_flow_events_type ON flow_events(flow_type);
CREATE INDEX IF NOT EXISTS idx_flow_events_direction ON flow_events(direction);
CREATE INDEX IF NOT EXISTS idx_flow_events_detected ON flow_events(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_flow_events_score ON flow_events(score DESC);
CREATE INDEX IF NOT EXISTS idx_flow_events_signal ON flow_events(signal_id);

CREATE TABLE IF NOT EXISTS flow_patterns (
    id TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL,
    tickers_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.0,
    timeframe TEXT NOT NULL DEFAULT '',
    event_count INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    detected_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_flow_patterns_type ON flow_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_flow_patterns_detected ON flow_patterns(detected_at DESC);

CREATE TABLE IF NOT EXISTS flow_convergences (
    id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    flow_event_ids_json TEXT NOT NULL DEFAULT '[]',
    convergence_score REAL NOT NULL DEFAULT 0.0,
    convergence_type TEXT NOT NULL,
    signal_stance TEXT NOT NULL DEFAULT '',
    flow_direction TEXT NOT NULL DEFAULT '',
    net_flow_premium REAL NOT NULL DEFAULT 0.0,
    details_json TEXT NOT NULL DEFAULT '{}',
    detected_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_flow_conv_signal ON flow_convergences(signal_id);
CREATE INDEX IF NOT EXISTS idx_flow_conv_ticker ON flow_convergences(ticker);
CREATE INDEX IF NOT EXISTS idx_flow_conv_type ON flow_convergences(convergence_type);
CREATE INDEX IF NOT EXISTS idx_flow_conv_detected ON flow_convergences(detected_at DESC);

CREATE TABLE IF NOT EXISTS flow_baselines (
    ticker TEXT PRIMARY KEY,
    net_premium REAL NOT NULL DEFAULT 0.0,
    avg_premium REAL NOT NULL DEFAULT 0.0,
    flow_count INTEGER NOT NULL DEFAULT 0,
    last_direction TEXT NOT NULL DEFAULT 'neutral',
    observations_json TEXT NOT NULL DEFAULT '{}',
    last_updated REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS author_profiles (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    username TEXT NOT NULL,
    total_signals INTEGER NOT NULL DEFAULT 0,
    win_count INTEGER NOT NULL DEFAULT 0,
    loss_count INTEGER NOT NULL DEFAULT 0,
    accuracy REAL,
    roi_if_followed REAL,
    sharpe REAL,
    reputation_score REAL,
    stats_json TEXT NOT NULL DEFAULT '{}',
    first_seen REAL NOT NULL,
    last_seen REAL,
    updated_at REAL,
    UNIQUE(platform, username)
);
CREATE INDEX IF NOT EXISTS idx_author_prof_platform ON author_profiles(platform);
CREATE INDEX IF NOT EXISTS idx_author_prof_reputation ON author_profiles(reputation_score DESC);
CREATE INDEX IF NOT EXISTS idx_author_prof_accuracy ON author_profiles(accuracy DESC);

CREATE TABLE IF NOT EXISTS author_predictions (
    id TEXT PRIMARY KEY,
    author_id TEXT NOT NULL,
    signal_id TEXT,
    ticker TEXT NOT NULL,
    stance TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    outcome TEXT,
    pnl_pct REAL,
    created_at REAL NOT NULL,
    resolved_at REAL
);
CREATE INDEX IF NOT EXISTS idx_author_pred_author ON author_predictions(author_id);
CREATE INDEX IF NOT EXISTS idx_author_pred_signal ON author_predictions(signal_id);
CREATE INDEX IF NOT EXISTS idx_author_pred_ticker ON author_predictions(ticker);
CREATE INDEX IF NOT EXISTS idx_author_pred_outcome ON author_predictions(outcome);
CREATE INDEX IF NOT EXISTS idx_author_pred_created ON author_predictions(created_at DESC);

CREATE TABLE IF NOT EXISTS manipulation_alerts (
    id TEXT PRIMARY KEY,
    alert_type TEXT NOT NULL,
    tickers_json TEXT NOT NULL DEFAULT '[]',
    authors_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    severity REAL NOT NULL DEFAULT 0.0,
    detected_at REAL NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_manip_type ON manipulation_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_manip_detected ON manipulation_alerts(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_manip_severity ON manipulation_alerts(severity DESC);

CREATE TABLE IF NOT EXISTS sentiment_propagation (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    origin_sub TEXT NOT NULL,
    spread_to TEXT NOT NULL,
    origin_ts REAL NOT NULL,
    spread_ts REAL NOT NULL,
    lag_seconds REAL NOT NULL DEFAULT 0.0,
    detected_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prop_ticker ON sentiment_propagation(ticker);
CREATE INDEX IF NOT EXISTS idx_prop_origin ON sentiment_propagation(origin_sub);
CREATE INDEX IF NOT EXISTS idx_prop_spread ON sentiment_propagation(spread_ts DESC);

CREATE TABLE IF NOT EXISTS author_clusters (
    id TEXT PRIMARY KEY,
    authors_json TEXT NOT NULL DEFAULT '[]',
    similarity_score REAL NOT NULL DEFAULT 0.0,
    common_tickers_json TEXT NOT NULL DEFAULT '[]',
    detected_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cluster_similarity ON author_clusters(similarity_score DESC);
CREATE INDEX IF NOT EXISTS idx_cluster_detected ON author_clusters(detected_at DESC);

CREATE TABLE IF NOT EXISTS strategies (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    rules_json TEXT NOT NULL DEFAULT '[]',
    config_json TEXT NOT NULL DEFAULT '{}',
    performance_json TEXT NOT NULL DEFAULT '{}',
    health_score REAL NOT NULL DEFAULT 1.0,
    is_active INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_strategy_user ON strategies(user_id);
CREATE INDEX IF NOT EXISTS idx_strategy_active ON strategies(is_active);
CREATE INDEX IF NOT EXISTS idx_strategy_source ON strategies(source);

CREATE TABLE IF NOT EXISTS strategy_trades (
    id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    signal_id TEXT NOT NULL DEFAULT '',
    ticker TEXT NOT NULL,
    stance TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    pnl_pct REAL,
    created_at REAL NOT NULL,
    resolved_at REAL
);
CREATE INDEX IF NOT EXISTS idx_strade_strategy ON strategy_trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_strade_ticker ON strategy_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_strade_created ON strategy_trades(created_at DESC);

CREATE TABLE IF NOT EXISTS strategy_portfolios (
    strategy_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    balance REAL NOT NULL DEFAULT 10000.0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    total_pnl REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (strategy_id, user_id)
);

CREATE TABLE IF NOT EXISTS strategy_marketplace (
    id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    performance_json TEXT NOT NULL DEFAULT '{}',
    subscriber_count INTEGER NOT NULL DEFAULT 0,
    rating REAL NOT NULL DEFAULT 0.0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_marketplace_author ON strategy_marketplace(author_id);
CREATE INDEX IF NOT EXISTS idx_marketplace_rating ON strategy_marketplace(rating DESC);
CREATE INDEX IF NOT EXISTS idx_marketplace_subs ON strategy_marketplace(subscriber_count DESC);

CREATE TABLE IF NOT EXISTS market_regimes (
    id TEXT PRIMARY KEY,
    regime_type TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL,
    indicators_json TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5,
    detected_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_regime_type ON market_regimes(regime_type);
CREATE INDEX IF NOT EXISTS idx_regime_start ON market_regimes(start_ts DESC);

CREATE TABLE IF NOT EXISTS strategy_discoveries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    search_config_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    strategies_found INTEGER NOT NULL DEFAULT 0,
    elapsed_s REAL NOT NULL DEFAULT 0.0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_discovery_user ON strategy_discoveries(user_id);
CREATE INDEX IF NOT EXISTS idx_discovery_created ON strategy_discoveries(created_at DESC);

CREATE TABLE IF NOT EXISTS export_schedules (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'csv',
    frequency TEXT NOT NULL DEFAULT 'daily',
    filters_json TEXT NOT NULL DEFAULT '{}',
    last_run_at REAL DEFAULT NULL,
    next_run_at REAL NOT NULL,
    created_at REAL NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_export_schedules_user ON export_schedules(user_id);
CREATE INDEX IF NOT EXISTS idx_export_schedules_next_run ON export_schedules(next_run_at);

CREATE TABLE IF NOT EXISTS mcp_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    stream_id TEXT NOT NULL,
    message_json TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mcp_events_stream ON mcp_events(stream_id, id);
CREATE INDEX IF NOT EXISTS idx_mcp_events_event_id ON mcp_events(event_id);
CREATE INDEX IF NOT EXISTS idx_mcp_events_created ON mcp_events(created_at);
"""
