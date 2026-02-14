"""Tests for TradingView Pine Script generator.

Tests:
- Script generation for all 5 types
- Parameter substitution
- Syntax validation
- Edge cases (empty signals, single signal, 100+ signals)
"""

import pytest

from rot.integrations import PineScriptConfig, PineScriptGenerator, TVSignalOverlay


@pytest.fixture
def sample_signals():
    """Sample signals for testing."""
    return [
        TVSignalOverlay(
            timestamp=1707945600,
            ticker="AAPL",
            stance="bullish",
            confidence=0.85,
            event_type="fda_approval",
            strategy="call_debit_spread",
        ),
        TVSignalOverlay(
            timestamp=1707949200,
            ticker="TSLA",
            stance="bearish",
            confidence=0.72,
            event_type="earnings_miss",
            strategy="put_debit_spread",
        ),
        TVSignalOverlay(
            timestamp=1707952800,
            ticker="NVDA",
            stance="bullish",
            confidence=0.91,
            event_type="partnership",
            strategy="long_call",
        ),
    ]


class TestPineScriptGeneratorSignalOverlay:
    """Test signal overlay script generation."""

    def test_generate_basic_overlay(self, sample_signals):
        """Should generate valid signal overlay script."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_signal_overlay(sample_signals)

        assert "//@version=5" in script
        assert 'indicator("ROT Signals", overlay=true)' in script
        assert "signal_times" in script
        assert "signal_stances" in script
        assert "signal_confidences" in script
        assert "plotshape" in script

    def test_generate_empty_signals(self):
        """Should handle empty signal list gracefully."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_signal_overlay([])

        assert "//@version=5" in script
        assert "No signals match criteria" in script

    def test_generate_single_signal(self):
        """Should handle single signal."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        signals = [
            TVSignalOverlay(
                timestamp=1707945600,
                ticker="AAPL",
                stance="bullish",
                confidence=0.85,
            )
        ]
        script = gen.generate_signal_overlay(signals)

        assert "//@version=5" in script
        assert "1707945600" in script
        assert "plotshape" in script

    def test_generate_many_signals(self):
        """Should handle 100+ signals (tests array limits)."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        signals = [
            TVSignalOverlay(
                timestamp=1707945600 + i * 3600,
                ticker=f"TICKER{i}",
                stance="bullish" if i % 2 == 0 else "bearish",
                confidence=0.5 + (i % 50) / 100,
            )
            for i in range(150)
        ]
        script = gen.generate_signal_overlay(signals)

        assert "//@version=5" in script
        assert "signal_times" in script
        # Should contain all 150 timestamps
        assert script.count(",") >= 150

    def test_show_labels_true(self, sample_signals):
        """Should include labels when show_labels=True."""
        config = PineScriptConfig(show_labels=True)
        gen = PineScriptGenerator(config)
        script = gen.generate_signal_overlay(sample_signals)

        assert "signal_labels" in script
        assert "label.new" in script

    def test_show_labels_false(self, sample_signals):
        """Should omit labels when show_labels=False."""
        config = PineScriptConfig(show_labels=False)
        gen = PineScriptGenerator(config)
        script = gen.generate_signal_overlay(sample_signals)

        assert "signal_labels" not in script
        assert "label.new" not in script

    def test_show_lines_true(self, sample_signals):
        """Should include lines when show_lines=True."""
        config = PineScriptConfig(show_lines=True)
        gen = PineScriptGenerator(config)
        script = gen.generate_signal_overlay(sample_signals)

        assert "line.new" in script

    def test_show_lines_false(self, sample_signals):
        """Should omit lines when show_lines=False."""
        config = PineScriptConfig(show_lines=False)
        gen = PineScriptGenerator(config)
        script = gen.generate_signal_overlay(sample_signals)

        assert "line.new" not in script

    def test_confidence_color_true(self, sample_signals):
        """Should use confidence-based coloring."""
        config = PineScriptConfig(show_confidence_color=True)
        gen = PineScriptGenerator(config)
        script = gen.generate_signal_overlay(sample_signals)

        assert "signal_conf" in script
        assert "bull_color" in script
        assert "bear_color" in script

    def test_confidence_color_false(self, sample_signals):
        """Should use fixed colors when confidence coloring disabled."""
        config = PineScriptConfig(show_confidence_color=False)
        gen = PineScriptGenerator(config)
        script = gen.generate_signal_overlay(sample_signals)

        assert "bull_color = color.green" in script
        assert "bear_color = color.red" in script


class TestPineScriptGeneratorHeatmap:
    """Test confidence heatmap script generation."""

    def test_generate_heatmap(self, sample_signals):
        """Should generate valid heatmap script."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_confidence_heatmap(sample_signals)

        assert "//@version=5" in script
        assert "Confidence Heatmap" in script
        assert "bgcolor" in script
        assert "recent_stance" in script
        assert "recent_conf" in script

    def test_heatmap_empty_signals(self):
        """Should handle empty signals."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_confidence_heatmap([])

        assert "//@version=5" in script
        assert "bgcolor" in script

    def test_heatmap_includes_plot(self, sample_signals):
        """Should include confidence plot line."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_confidence_heatmap(sample_signals)

        assert "plot(recent_conf" in script
        assert "hline(0.5" in script


class TestPineScriptGeneratorWatchlist:
    """Test watchlist indicator script generation."""

    def test_generate_watchlist(self, sample_signals):
        """Should generate valid watchlist script."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_watchlist_indicator(sample_signals)

        assert "//@version=5" in script
        assert "Watchlist" in script
        assert "table.new" in script
        assert "table.cell" in script

    def test_watchlist_empty_signals(self):
        """Should handle empty signals."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_watchlist_indicator([])

        assert "//@version=5" in script
        assert "No ROT signals" in script

    def test_watchlist_limits_to_10_tickers(self):
        """Should limit watchlist to top 10 tickers."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        signals = [
            TVSignalOverlay(
                timestamp=1707945600,
                ticker=f"TICKER{i}",
                stance="bullish",
                confidence=0.5 + i / 100,  # Increasing confidence
            )
            for i in range(20)
        ]
        script = gen.generate_watchlist_indicator(signals)

        # Should create table with 10 + 1 header row = 11 rows
        assert "table.new(position.top_right, 3, 11)" in script or "table.new(position.top_right, 3, 10)" in script

    def test_watchlist_shows_ticker_stance_conf(self, sample_signals):
        """Should display ticker, stance, and confidence columns."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_watchlist_indicator(sample_signals)

        assert "Ticker" in script
        assert "Stance" in script
        assert "Conf" in script
        assert "BULL" in script or "BEAR" in script


class TestPineScriptGeneratorStrategy:
    """Test strategy backtest script generation."""

    def test_generate_strategy(self, sample_signals):
        """Should generate valid strategy script."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_strategy_backtest(sample_signals)

        assert "//@version=5" in script
        assert "strategy(" in script
        assert "initial_capital" in script
        assert "strategy.entry" in script
        assert "strategy.close" in script

    def test_strategy_empty_signals(self):
        """Should handle empty signals."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_strategy_backtest([])

        assert "//@version=5" in script
        assert "strategy(" in script

    def test_strategy_uses_config_params(self, sample_signals):
        """Should use config parameters in strategy."""
        config = PineScriptConfig(
            strategy_capital=50000.0,
            strategy_commission=0.001,
            strategy_slippage=2,
        )
        gen = PineScriptGenerator(config)
        script = gen.generate_strategy_backtest(sample_signals)

        assert "initial_capital=50000.0" in script
        assert "commission_value=0.001" in script
        assert "slippage=2" in script

    def test_strategy_entry_logic(self, sample_signals):
        """Should include entry logic for long and short."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_strategy_backtest(sample_signals)

        assert 'strategy.entry("Long", strategy.long' in script
        assert 'strategy.entry("Short", strategy.short' in script
        assert 'strategy.close("Long")' in script
        assert 'strategy.close("Short")' in script


class TestPineScriptGeneratorAlerts:
    """Test alert conditions script generation."""

    def test_generate_alerts(self, sample_signals):
        """Should generate valid alert script."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_alert_conditions(sample_signals)

        assert "//@version=5" in script
        assert "Alerts" in script
        assert "alertcondition" in script

    def test_alerts_empty_signals(self):
        """Should handle empty signals."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_alert_conditions([])

        assert "//@version=5" in script
        assert "alerts inactive" in script

    def test_alerts_bullish_enabled(self, sample_signals):
        """Should include bullish alerts when enabled."""
        config = PineScriptConfig(alert_on_bullish=True, alert_on_bearish=False)
        gen = PineScriptGenerator(config)
        script = gen.generate_alert_conditions(sample_signals)

        assert "bullish_alert" in script
        assert 'alertcondition(bullish_alert' in script

    def test_alerts_bearish_enabled(self, sample_signals):
        """Should include bearish alerts when enabled."""
        config = PineScriptConfig(alert_on_bullish=False, alert_on_bearish=True)
        gen = PineScriptGenerator(config)
        script = gen.generate_alert_conditions(sample_signals)

        assert "bearish_alert" in script
        assert 'alertcondition(bearish_alert' in script

    def test_alerts_uses_min_confidence(self, sample_signals):
        """Should use alert_min_confidence threshold."""
        config = PineScriptConfig(alert_min_confidence=0.8)
        gen = PineScriptGenerator(config)
        script = gen.generate_alert_conditions(sample_signals)

        assert "conf >= 0.8" in script

    def test_alerts_includes_visual_indicators(self, sample_signals):
        """Should include visual plotshape indicators."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)
        script = gen.generate_alert_conditions(sample_signals)

        assert "plotshape(bullish_alert" in script
        assert "plotshape(bearish_alert" in script


class TestPineScriptGeneratorGeneric:
    """Test generic generator functionality."""

    def test_generate_with_script_type(self, sample_signals):
        """Should route to correct generator based on script_type."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)

        overlay = gen.generate(sample_signals, "signal_overlay")
        assert "plotshape" in overlay

        heatmap = gen.generate(sample_signals, "confidence_heatmap")
        assert "bgcolor" in heatmap

        watchlist = gen.generate(sample_signals, "watchlist_indicator")
        assert "table.new" in watchlist

        strategy = gen.generate(sample_signals, "strategy_backtest")
        assert "strategy.entry" in strategy

        alerts = gen.generate(sample_signals, "alert_conditions")
        assert "alertcondition" in alerts

    def test_generate_invalid_script_type(self, sample_signals):
        """Should raise ValueError for invalid script_type."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)

        with pytest.raises(ValueError, match="Invalid script_type"):
            gen.generate(sample_signals, "invalid_type")  # type: ignore

    def test_config_validation_on_init(self):
        """Should validate config on generator init."""
        config = PineScriptConfig(min_confidence=-0.5)
        with pytest.raises(ValueError):
            PineScriptGenerator(config)


class TestPineScriptSyntaxValidation:
    """Test Pine Script syntax validation."""

    def test_validate_valid_script(self):
        """Should pass validation for valid script."""
        script = """
//@version=5
indicator("Test", overlay=true)
plot(close)
"""
        is_valid, msg = PineScriptGenerator.validate_pine_script(script)
        assert is_valid
        assert msg == ""

    def test_validate_missing_version(self):
        """Should fail if missing version declaration."""
        script = """
indicator("Test", overlay=true)
plot(close)
"""
        is_valid, msg = PineScriptGenerator.validate_pine_script(script)
        assert not is_valid
        assert "version" in msg.lower()

    def test_validate_unmatched_open_bracket(self):
        """Should detect unmatched open bracket."""
        script = """
//@version=5
indicator("Test", overlay=true)
array.from([1, 2, 3
"""
        is_valid, msg = PineScriptGenerator.validate_pine_script(script)
        assert not is_valid
        assert "[" in msg or "bracket" in msg.lower()

    def test_validate_unmatched_close_bracket(self):
        """Should detect unmatched close bracket."""
        script = """
//@version=5
indicator("Test", overlay=true)
array.from(1, 2, 3])
"""
        is_valid, msg = PineScriptGenerator.validate_pine_script(script)
        assert not is_valid
        assert "]" in msg or "bracket" in msg.lower()

    def test_validate_unmatched_open_paren(self):
        """Should detect unmatched open parenthesis."""
        script = """
//@version=5
indicator("Test", overlay=true
plot(close)
"""
        is_valid, msg = PineScriptGenerator.validate_pine_script(script)
        assert not is_valid
        assert "(" in msg

    def test_validate_unmatched_close_paren(self):
        """Should detect unmatched close parenthesis."""
        script = """
//@version=5
indicator("Test", overlay=true))
plot(close)
"""
        is_valid, msg = PineScriptGenerator.validate_pine_script(script)
        assert not is_valid
        assert ")" in msg

    def test_validate_unmatched_double_quote(self):
        """Should detect unmatched double quote."""
        script = """
//@version=5
indicator("Test, overlay=true)
plot(close)
"""
        is_valid, msg = PineScriptGenerator.validate_pine_script(script)
        assert not is_valid
        assert '"' in msg

    def test_validate_ignores_comments(self):
        """Should ignore syntax in comments."""
        script = """
//@version=5
// This is a comment with unmatched ( and [
indicator("Test", overlay=true)
plot(close)
"""
        is_valid, msg = PineScriptGenerator.validate_pine_script(script)
        assert is_valid

    def test_validate_generated_scripts(self, sample_signals):
        """All generated scripts should pass validation."""
        config = PineScriptConfig()
        gen = PineScriptGenerator(config)

        script_types = [
            "signal_overlay",
            "confidence_heatmap",
            "watchlist_indicator",
            "strategy_backtest",
            "alert_conditions",
        ]

        for script_type in script_types:
            script = gen.generate(sample_signals, script_type)  # type: ignore
            is_valid, msg = PineScriptGenerator.validate_pine_script(script)
            assert is_valid, f"{script_type} failed validation: {msg}"
