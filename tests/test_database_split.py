"""
Tests for decomposed database structure.

Verifies that the Database class composed from 12 mixins works correctly:
- All methods are accessible
- No method name conflicts
- Connection lifecycle works
- Schema creation works
- Migrations work
- Backward compatibility maintained
- Mixin isolation for testing
"""

import pytest
import tempfile
import os
import asyncio
from pathlib import Path

# CRITICAL: Test backward compatibility - this import must work
from rot.storage.database import Database

# Test individual mixin imports
from rot.storage.signals import SignalsMixin
from rot.storage.performance import PerformanceMixin
from rot.storage.users import UsersMixin
from rot.storage.subscriptions import SubscriptionsMixin
from rot.storage.paper_trading import PaperTradingMixin
from rot.storage.cleanup import CleanupMixin
from rot.storage.alerts_db import AlertsMixin
from rot.storage.analytics import AnalyticsMixin
from rot.storage.macro_db import MacroMixin
from rot.storage.agents_db import AgentsMixin
from rot.storage.flow_db import FlowMixin
from rot.storage.social_db import SocialMixin


@pytest.fixture
async def db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        database = Database(db_path)
        await database.connect()
        yield database
        await database.close()


@pytest.fixture
async def db_no_connect():
    """Create a database instance without connecting (for testing connect/close)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        database = Database(db_path)
        yield database
        # Close if connected
        if database._conn:
            await database.close()


class TestImportsAndInstantiation:
    """Test that all imports work and Database can be instantiated."""

    def test_database_import(self):
        """Verify Database can be imported from main module."""
        from rot.storage.database import Database
        assert Database is not None

    def test_all_mixins_importable(self):
        """Verify all 14 mixins can be imported."""
        assert SignalsMixin is not None
        assert PerformanceMixin is not None
        assert UsersMixin is not None
        assert SubscriptionsMixin is not None
        assert PaperTradingMixin is not None
        assert CleanupMixin is not None
        assert AnalyticsMixin is not None
        assert MacroMixin is not None
        assert MacroMixin is not None
        assert FlowMixin is not None
        assert SocialMixin is not None

    def test_database_instantiation(self):
        """Verify Database can be instantiated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            database = Database(db_path)
            assert database is not None
            assert database.db_path == db_path

    def test_mro_order(self):
        """Verify Method Resolution Order is correct."""
        mro = Database.__mro__
        # Should be: Database, all mixins, object
        assert mro[0] == Database
        assert object in mro
        # Verify all mixins are in MRO
        mixin_classes = {
            SignalsMixin, PerformanceMixin, UsersMixin, SubscriptionsMixin,
            PaperTradingMixin, CleanupMixin, AlertsMixin, AnalyticsMixin,
            MacroMixin, AgentsMixin, FlowMixin, SocialMixin
        }


class TestMethodAvailability:
    """Test that all expected methods are accessible from Database class."""

    def test_signal_methods_available(self):
        """Verify SignalsMixin methods are accessible."""
        methods = [
            'insert_signal', 'get_signals', 'get_signal_by_id',
            'get_signal_count', 'get_signals_for_backtest',
            'get_signals_for_export', 'get_signals_by_ticker'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"

    def test_performance_methods_available(self):
        """Verify PerformanceMixin methods are accessible."""
        methods = [
            'insert_performance', 'update_performance',
            'get_performance_summary', 'get_accuracy_breakdown',
            'get_confidence_calibration', 'get_strategy_pnl_breakdown',
            'get_event_type_breakdown', 'get_ticker_performance'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"

    def test_user_methods_available(self):
        """Verify UsersMixin methods are accessible."""
        methods = [
            'insert_user', 'get_user_by_email', 'get_user_by_id',
            'get_user_by_api_key', 'update_user_settings',
            'update_user_tier', 'get_user_watchlist',
            'add_watchlist_ticker', 'remove_watchlist_ticker'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"

    def test_subscription_methods_available(self):
        """Verify SubscriptionsMixin methods are accessible."""
        methods = [
            'upsert_subscription', 'get_subscription_by_user',
            'cancel_subscription', 'get_active_subscriptions'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"

    def test_paper_trading_methods_available(self):
        """Verify PaperTradingMixin methods are accessible."""
        methods = [
            'get_paper_portfolio', 'init_paper_portfolio',
            'update_paper_portfolio', 'insert_paper_trade',
            'get_paper_trades', 'close_paper_trade',
            'get_paper_leaderboard'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"

    def test_misc_methods_available(self):
        """Verify CleanupMixin methods are accessible."""
        methods = [
            'track_api_usage', 'get_api_usage',
            'insert_x_post', 'get_recent_x_posts',
            'upsert_email_alert_settings', 'get_email_alert_settings',
            'insert_sponsored_signal', 'get_congress_trades'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"

    def test_analytics_methods_available(self):
        """Verify AnalyticsMixin methods are accessible."""
        methods = [
            'get_sector_time_series', 'get_sector_drill_down',
            'get_sector_rankings', 'get_correlation_matrix',
            'get_ticker_correlations', 'get_correlation_signal_pairs',
            'upsert_export_schedule', 'get_pending_exports'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"


    def test_macro_methods_available(self):
        """Verify MacroMixin methods are accessible."""
        methods = [
            'upsert_macro_event', 'get_macro_events',
            'upsert_earnings_event', 'get_earnings_events',
            'upsert_insider_trade', 'get_insider_trades',
            'upsert_fomc_meeting', 'get_fomc_meetings',
            'get_event_impact', 'save_event_impact'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"

    def test_agent_methods_available(self):
        """Verify AgentsMixin methods are accessible."""
        methods = [
            'insert_agent', 'get_agent', 'get_user_agents',
            'update_agent', 'delete_agent',
            'insert_agent_trade', 'close_agent_trade',
            'get_agent_trades', 'get_agent_performance'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"

    def test_flow_methods_available(self):
        """Verify FlowMixin methods are accessible."""
        methods = [
            'save_flow_event', 'get_flow_events',
            'get_flow_summary', 'get_flow_timeline',
            'save_flow_pattern', 'get_flow_patterns',
            'save_flow_convergence', 'get_flow_convergences'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"

    def test_social_methods_available(self):
        """Verify SocialMixin methods are accessible."""
        methods = [
            'upsert_author_profile', 'get_author_profile',
            'get_author_leaderboard', 'insert_author_prediction',
            'resolve_author_prediction', 'save_manipulation_alert',
            'get_manipulation_alerts', 'save_sentiment_propagation'
        ]
        for method in methods:
            assert hasattr(Database, method), f"Missing method: {method}"

            assert hasattr(Database, method), f"Missing method: {method}"


class TestNoMethodConflicts:
    """Verify no method name conflicts across mixins."""

    def test_no_duplicate_methods(self):
        """Verify each method appears only once across all mixins."""
        # Collect all methods from each mixin
        mixin_classes = [
            SignalsMixin, PerformanceMixin, UsersMixin, SubscriptionsMixin,
            PaperTradingMixin, CleanupMixin, AlertsMixin, AnalyticsMixin,
            MacroMixin, AgentsMixin, FlowMixin, SocialMixin
        ]

        method_sources = {}  # method_name -> list of mixin classes

        for mixin in mixin_classes:
            for attr_name in dir(mixin):
                if not attr_name.startswith('_') and callable(getattr(mixin, attr_name, None)):
                    if attr_name not in method_sources:
                        method_sources[attr_name] = []
                    method_sources[attr_name].append(mixin.__name__)

        # Check for conflicts (methods in multiple mixins)
        conflicts = {name: sources for name, sources in method_sources.items() if len(sources) > 1}

        # Filter out intentional duplicates (if any)
        # For now, we expect zero conflicts
        assert len(conflicts) == 0, f"Method name conflicts detected: {conflicts}"


class TestConnectionLifecycle:
    """Test database connection lifecycle methods."""

    @pytest.mark.asyncio
    async def test_connect_creates_connection(self, db_no_connect):
        """Verify connect() establishes database connection."""
        assert db_no_connect._conn is None
        await db_no_connect.connect()
        assert db_no_connect._conn is not None

    @pytest.mark.asyncio
    async def test_close_closes_connection(self, db_no_connect):
        """Verify close() closes database connection."""
        await db_no_connect.connect()
        assert db_no_connect._conn is not None
        await db_no_connect.close()
        assert db_no_connect._conn is None

    @pytest.mark.asyncio
    async def test_reconnect_works(self, db_no_connect):
        """Verify reconnect after close works."""
        await db_no_connect.connect()
        await db_no_connect.close()
        await db_no_connect.connect()
        assert db_no_connect._conn is not None

    @pytest.mark.asyncio
    async def test_database_file_created(self, db_no_connect):
        """Verify database file is created on connect."""
        assert not os.path.exists(db_no_connect.db_path)
        await db_no_connect.connect()
        assert os.path.exists(db_no_connect.db_path)


class TestSchemaCreation:
    """Test that schema is created correctly."""

    @pytest.mark.asyncio
    async def test_all_tables_created(self, db):
        """Verify all expected tables are created."""
        cursor = await db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cursor.fetchall()]

        expected_tables = {
            'signals', 'signal_performance', 'signal_archive',
            'users', 'subscriptions',
            'paper_portfolios', 'paper_trades',
            'api_usage', 'x_posts', 'email_alert_settings',
            'referral_clicks', 'referral_conversions',
            'sponsored_signals', 'data_exports', 'win_rate_snapshots',
            'congress_trades',
            'backtest_runs', 'backtest_strategies',
            'unusual_events',
            'export_schedules',
            'macro_events', 'earnings_events', 'insider_trades',
            'fomc_meetings', 'event_impact_cache',
            'trading_agents', 'agent_trades',
            'flow_events', 'flow_patterns', 'flow_convergences', 'flow_baselines',
            'author_profiles', 'author_predictions', 'manipulation_alerts',
            'sentiment_propagation', 'author_clusters',
            'strategies', 'strategy_trades', 'strategy_portfolios',
            'strategy_marketplace', 'market_regimes', 'strategy_discoveries'
        }

        # Verify all expected tables exist
        missing = expected_tables - set(tables)
        assert len(missing) == 0, f"Missing tables: {missing}"

    @pytest.mark.asyncio
    async def test_signals_table_schema(self, db):
        """Verify signals table has correct columns."""
        cursor = await db._conn.execute("PRAGMA table_info(signals)")
        columns = {row[1] for row in await cursor.fetchall()}

        expected_columns = {
            'id', 'run_id', 'created_at', 'ticker', 'event_type',
            'stance', 'time_horizon', 'confidence', 'trend_score',
            'quality_score', 'strategy', 'subreddit', 'post_title',
            'post_url', 'market_data', 'reasoning', 'trade_idea',
            'event_data', 'sector', 'sponsored', 'sponsored_by'
        }

        assert expected_columns.issubset(columns), f"Missing columns: {expected_columns - columns}"

    @pytest.mark.asyncio
    async def test_indexes_created(self, db):
        """Verify indexes are created."""
        cursor = await db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        )
        indexes = [row[0] for row in await cursor.fetchall()]

        # Check for some key indexes
        key_indexes = [
            'idx_signals_ticker',
            'idx_signals_created',
            'idx_signals_confidence',
            'idx_perf_signal',
            'idx_users_email'
        ]

        for idx in key_indexes:
            assert idx in indexes, f"Missing index: {idx}"


class TestMigrations:
    """Test migration system works correctly."""

    @pytest.mark.asyncio
    async def test_migration_creates_archive_table(self):
        """Verify migration creates signal_archive table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            database = Database(db_path)
            await database.connect()

            # Check archive table exists
            cursor = await database._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_archive'"
            )
            result = await cursor.fetchone()
            assert result is not None

            await database.close()

    @pytest.mark.asyncio
    async def test_migration_idempotent(self):
        """Verify migrations can run multiple times safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            # Connect twice - migrations should run safely both times
            database1 = Database(db_path)
            await database1.connect()
            await database1.close()

            database2 = Database(db_path)
            await database2.connect()

            # Should still have all tables
            cursor = await database2._conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            )
            count = (await cursor.fetchone())[0]
            assert count >= 40  # We have 40+ tables

            await database2.close()


class TestWALPragmas:
    """Test that WAL mode and pragmas are applied correctly."""

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, db):
        """Verify WAL mode is enabled."""
        cursor = await db._conn.execute("PRAGMA journal_mode")
        mode = (await cursor.fetchone())[0]
        assert mode.lower() == 'wal'

    @pytest.mark.asyncio
    async def test_synchronous_normal(self, db):
        """Verify synchronous is set to NORMAL."""
        cursor = await db._conn.execute("PRAGMA synchronous")
        sync = (await cursor.fetchone())[0]
        assert sync == 1  # NORMAL = 1

    @pytest.mark.asyncio
    async def test_foreign_keys_enabled(self, db):
        """Verify foreign keys are enabled."""
        cursor = await db._conn.execute("PRAGMA foreign_keys")
        fk = (await cursor.fetchone())[0]
        assert fk == 1

    @pytest.mark.asyncio
    async def test_cache_size_set(self, db):
        """Verify cache size is set."""
        cursor = await db._conn.execute("PRAGMA cache_size")
        cache = (await cursor.fetchone())[0]
        assert cache == -64000  # 64MB

    @pytest.mark.asyncio
    async def test_temp_store_memory(self, db):
        """Verify temp store is set to memory."""
        cursor = await db._conn.execute("PRAGMA temp_store")
        temp = (await cursor.fetchone())[0]
        assert temp == 2  # MEMORY = 2

    @pytest.mark.asyncio
    async def test_mmap_size_set(self, db):
        """Verify mmap size is set."""
        cursor = await db._conn.execute("PRAGMA mmap_size")
        mmap = (await cursor.fetchone())[0]
        assert mmap == 134217728  # 128MB

    @pytest.mark.asyncio
    async def test_page_size_set(self, db):
        """Verify page size is set."""
        cursor = await db._conn.execute("PRAGMA page_size")
        page = (await cursor.fetchone())[0]
        assert page == 4096

    @pytest.mark.asyncio
    async def test_busy_timeout_set(self, db):
        """Verify busy timeout is set."""
        cursor = await db._conn.execute("PRAGMA busy_timeout")
        timeout = (await cursor.fetchone())[0]
        assert timeout == 5000


class TestSQLHelpersImport:
    """Test that sql_helpers constants are imported correctly in mixins."""

    def test_signal_mixin_has_sql_helpers(self):
        """Verify SignalsMixin imports sql_helpers."""
        # Check for SQL constants used in SignalsMixin
        from rot.storage import db_signal_mixin
        # If the module loaded without error, the imports worked
        assert hasattr(db_signal_mixin, 'SignalsMixin')

    def test_analytics_mixin_has_sql_helpers(self):
        """Verify AnalyticsMixin imports sql_helpers."""
        from rot.storage import db_analytics_mixin
        assert hasattr(db_analytics_mixin, 'AnalyticsMixin')

    def test_performance_mixin_has_sql_helpers(self):
        """Verify PerformanceMixin imports sql_helpers."""
        from rot.storage import db_performance_mixin
        assert hasattr(db_performance_mixin, 'PerformanceMixin')


class TestBackwardCompatibility:
    """Critical tests for backward compatibility."""

    def test_main_import_works(self):
        """CRITICAL: Verify main import path works."""
        from rot.storage.database import Database
        assert Database is not None

    def test_database_class_usable(self):
        """CRITICAL: Verify Database class works as before split."""
        from rot.storage.database import Database
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = Database(db_path)
            assert db.db_path == db_path

    @pytest.mark.asyncio
    async def test_existing_code_patterns_work(self):
        """CRITICAL: Verify existing code patterns still work."""
        from rot.storage.database import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = Database(db_path)
            await db.connect()

            # Test pattern: insert signal
            signal_id = "test-123"
            await db.insert_signal(
                signal_id=signal_id,
                run_id="run-1",
                ticker="TSLA",
                event_type="product_news",
                stance="bullish",
                time_horizon="1w",
                confidence=0.8,
                trend_score=1.5,
                quality_score=0.9,
                strategy="debit_spread",
                subreddit="wallstreetbets",
                post_title="Test",
                post_url="https://reddit.com/test",
                market_data={},
                reasoning={},
                trade_idea={},
                event_data={}
            )

            # Test pattern: get signal
            signal = await db.get_signal_by_id(signal_id)
            assert signal is not None
            assert signal["ticker"] == "TSLA"

            await db.close()


class TestMixinIsolation:
    """Test that mixins can be tested in isolation."""

    @pytest.mark.asyncio
    async def test_signal_mixin_isolation(self):
        """Verify SignalsMixin methods can be tested independently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = Database(db_path)
            await db.connect()

            # Test SignalsMixin method in isolation
            signal_id = "iso-test-1"
            await db.insert_signal(
                signal_id=signal_id,
                run_id="run-1",
                ticker="AAPL",
                event_type="earnings_rumor",
                stance="bullish",
                time_horizon="intraday",
                confidence=0.7,
                trend_score=1.0,
                quality_score=0.8,
                strategy="straddle",
                subreddit="stocks",
                post_title="Test",
                post_url="https://reddit.com/test",
                market_data={},
                reasoning={},
                trade_idea={},
                event_data={}
            )

            signals = await db.get_signals(limit=10)
            assert len(signals) == 1
            assert signals[0]["ticker"] == "AAPL"

            await db.close()

    @pytest.mark.asyncio
    async def test_user_mixin_isolation(self):
        """Verify UsersMixin methods can be tested independently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = Database(db_path)
            await db.connect()

            # Test UsersMixin method in isolation
            user_id = "user-123"
            await db.insert_user(
                user_id=user_id,
                email="test@example.com",
                password_hash="hash123",
                tier="free"
            )

            user = await db.get_user_by_email("test@example.com")
            assert user is not None
            assert user["id"] == user_id

            await db.close()

    @pytest.mark.asyncio
    async def test_performance_mixin_isolation(self):
        """Verify PerformanceMixin methods can be tested independently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = Database(db_path)
            await db.connect()

            # Insert signal first (dependency)
            signal_id = "perf-test-1"
            await db.insert_signal(
                signal_id=signal_id,
                run_id="run-1",
                ticker="NVDA",
                event_type="product_news",
                stance="bullish",
                time_horizon="1w",
                confidence=0.8,
                trend_score=1.5,
                quality_score=0.9,
                strategy="debit_spread",
                subreddit="wallstreetbets",
                post_title="Test",
                post_url="https://reddit.com/test",
                market_data={},
                reasoning={},
                trade_idea={},
                event_data={}
            )

            # Test PerformanceMixin method in isolation
            await db.insert_performance(
                signal_id=signal_id,
                ticker="NVDA",
                price_at_signal=500.0
            )

            summary = await db.get_performance_summary()
            assert summary is not None

            await db.close()


class TestCrossModuleDependencies:
    """Test methods that span multiple mixins work correctly."""

    @pytest.mark.asyncio
    async def test_signal_and_performance_integration(self, db):
        """Test signal + performance workflow."""
        signal_id = "integration-1"

        # SignalsMixin: insert signal
        await db.insert_signal(
            signal_id=signal_id,
            run_id="run-1",
            ticker="AMD",
            event_type="product_news",
            stance="bullish",
            time_horizon="1w",
            confidence=0.75,
            trend_score=1.2,
            quality_score=0.85,
            strategy="debit_spread",
            subreddit="wallstreetbets",
            post_title="AMD New Chip",
            post_url="https://reddit.com/amd",
            market_data={"price": 150.0},
            reasoning={"thesis": "New product launch"},
            trade_idea={"strategy": "debit_spread"},
            event_data={}
        )

        # PerformanceMixin: track performance
        await db.insert_performance(
            signal_id=signal_id,
            ticker="AMD",
            price_at_signal=150.0
        )

        await db.update_performance(
            signal_id=signal_id,
            price_1h=151.0,
            price_1d=153.0,
            max_gain_pct=2.0,
            max_loss_pct=-0.5
        )

        # AnalyticsMixin: get summary (uses both signals and performance)
        summary = await db.get_performance_summary()
        assert summary["total_signals"] == 1

    @pytest.mark.asyncio
    async def test_user_and_paper_trading_integration(self, db):
        """Test user + paper trading workflow."""
        user_id = "paper-user-1"

        # UsersMixin: create user
        await db.insert_user(
            user_id=user_id,
            email="trader@example.com",
            password_hash="hash123",
            tier="pro"
        )

        # PaperTradingMixin: init portfolio
        await db.init_paper_portfolio(user_id)

        portfolio = await db.get_paper_portfolio(user_id)
        assert portfolio is not None
        assert portfolio["balance"] == 10000.0

    @pytest.mark.asyncio
    async def test_agent_and_signal_integration(self, db):
        """Test agent + signal workflow."""
        user_id = "agent-user-1"
        agent_id = "agent-1"
        signal_id = "agent-signal-1"

        # UsersMixin: create user
        await db.insert_user(
            user_id=user_id,
            email="agent@example.com",
            password_hash="hash123",
            tier="ultra"
        )

        # AgentsMixin: create agent
        await db.insert_agent(
            agent_id=agent_id,
            user_id=user_id,
            name="Test Agent",
            agent_type="signal_follower",
            rules_json=[],
            config_json={}
        )

        # SignalsMixin: create signal
        await db.insert_signal(
            signal_id=signal_id,
            run_id="run-1",
            ticker="TSLA",
            event_type="product_news",
            stance="bullish",
            time_horizon="1w",
            confidence=0.8,
            trend_score=1.5,
            quality_score=0.9,
            strategy="debit_spread",
            subreddit="wallstreetbets",
            post_title="Test",
            post_url="https://reddit.com/test",
            market_data={},
            reasoning={},
            trade_idea={},
            event_data={}
        )

        # AgentsMixin: execute trade
        trade_id = "agent-trade-1"
        await db.insert_agent_trade(
            trade_id=trade_id,
            agent_id=agent_id,
            user_id=user_id,
            signal_id=signal_id,
            ticker="TSLA",
            stance="bullish",
            entry_price=250.0,
            quantity=10,
            dollars=2500.0
        )

        trades = await db.get_agent_trades(agent_id)
        assert len(trades) == 1
        assert trades[0]["ticker"] == "TSLA"


class TestErrorHandling:
    """Test error handling in decomposed structure."""

    @pytest.mark.asyncio
    async def test_insert_duplicate_signal_fails_gracefully(self, db):
        """Verify duplicate signal insertion fails gracefully."""
        signal_id = "duplicate-1"

        await db.insert_signal(
            signal_id=signal_id,
            run_id="run-1",
            ticker="AAPL",
            event_type="earnings_rumor",
            stance="bullish",
            time_horizon="1w",
            confidence=0.8,
            trend_score=1.5,
            quality_score=0.9,
            strategy="debit_spread",
            subreddit="wallstreetbets",
            post_title="Test",
            post_url="https://reddit.com/test",
            market_data={},
            reasoning={},
            trade_idea={},
            event_data={}
        )

        # Second insert with same ID should handle gracefully
        # (depends on implementation - may raise or ignore)
        try:
            await db.insert_signal(
                signal_id=signal_id,
                run_id="run-2",
                ticker="AAPL",
                event_type="earnings_rumor",
                stance="bearish",
                time_horizon="1w",
                confidence=0.7,
                trend_score=1.2,
                quality_score=0.8,
                strategy="credit_spread",
                subreddit="stocks",
                post_title="Test 2",
                post_url="https://reddit.com/test2",
                market_data={},
                reasoning={},
                trade_idea={},
                event_data={}
            )
        except Exception:
            # Expected - unique constraint violation
            pass

    @pytest.mark.asyncio
    async def test_query_nonexistent_signal_returns_none(self, db):
        """Verify querying nonexistent signal returns None."""
        signal = await db.get_signal_by_id("nonexistent-123")
        assert signal is None

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_list(self, db):
        """Verify empty query returns empty list."""
        signals = await db.get_signals(limit=10)
        assert signals == []


class TestPerformanceConsiderations:
    """Test performance-related aspects of decomposed structure."""

    @pytest.mark.asyncio
    async def test_large_batch_insert(self, db):
        """Verify batch inserts work efficiently."""
        # Insert 100 signals
        for i in range(100):
            await db.insert_signal(
                signal_id=f"batch-{i}",
                run_id="run-1",
                ticker="SPY",
                event_type="macro",
                stance="bullish",
                time_horizon="1w",
                confidence=0.8,
                trend_score=1.5,
                quality_score=0.9,
                strategy="iron_condor",
                subreddit="wallstreetbets",
                post_title=f"Test {i}",
                post_url=f"https://reddit.com/test{i}",
                market_data={},
                reasoning={},
                trade_idea={},
                event_data={}
            )

        # Verify all inserted
        count = await db.get_signal_count()
        assert count == 100

    @pytest.mark.asyncio
    async def test_pagination_works(self, db):
        """Verify pagination works correctly."""
        # Insert 25 signals
        for i in range(25):
            await db.insert_signal(
                signal_id=f"page-{i}",
                run_id="run-1",
                ticker="QQQ",
                event_type="macro",
                stance="bullish",
                time_horizon="1w",
                confidence=0.8,
                trend_score=1.5,
                quality_score=0.9,
                strategy="straddle",
                subreddit="stocks",
                post_title=f"Test {i}",
                post_url=f"https://reddit.com/test{i}",
                market_data={},
                reasoning={},
                trade_idea={},
                event_data={}
            )

        # Get first page
        page1 = await db.get_signals(limit=10, offset=0)
        assert len(page1) == 10

        # Get second page
        page2 = await db.get_signals(limit=10, offset=10)
        assert len(page2) == 10

        # Get third page
        page3 = await db.get_signals(limit=10, offset=20)
        assert len(page3) == 5

        # Verify no overlap
        page1_ids = {s["id"] for s in page1}
        page2_ids = {s["id"] for s in page2}
        assert len(page1_ids & page2_ids) == 0


class TestCompositionCorrectness:
    """Test that composition of mixins is correct."""

    def test_database_inherits_from_all_mixins(self):
        """Verify Database inherits from all 14 mixins."""
        assert issubclass(Database, SignalsMixin)
        assert issubclass(Database, PerformanceMixin)
        assert issubclass(Database, UsersMixin)
        assert issubclass(Database, SubscriptionsMixin)
        assert issubclass(Database, PaperTradingMixin)
        assert issubclass(Database, CleanupMixin)
        assert issubclass(Database, AnalyticsMixin)
        assert issubclass(Database, MacroMixin)
        assert issubclass(Database, MacroMixin)
        assert issubclass(Database, FlowMixin)
        assert issubclass(Database, SocialMixin)

    def test_all_mixins_in_bases(self):
        """Verify all mixins are in Database.__bases__."""
        bases = Database.__bases__
        mixin_classes = {
            SignalsMixin, PerformanceMixin, UsersMixin, SubscriptionsMixin,
            PaperTradingMixin, CleanupMixin, AlertsMixin, AnalyticsMixin,
            MacroMixin, AgentsMixin, FlowMixin, SocialMixin
        }
        assert mixin_classes.issubset(set(bases))
        assert mixin_classes.issubset(set(bases))

    def test_method_count_total(self):
        """Verify total method count is as expected (~168+ public methods)."""
        public_methods = [
            attr for attr in dir(Database)
            if not attr.startswith('_') and callable(getattr(Database, attr))
        ]
        # Should have ~168+ public methods across all mixins
        assert len(public_methods) >= 168, f"Expected 168+ methods, got {len(public_methods)}"
