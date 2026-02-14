"""Tests for TradingView integration types.

Tests:
- TVSignalOverlay creation and conversion to Pine arrays
- PineScriptConfig validation
- Edge cases and error handling
"""

import pytest

from rot.integrations.types import PineScriptConfig, TVSignalOverlay


class TestTVSignalOverlay:
    """Test TVSignalOverlay dataclass."""

    def test_create_bullish_signal(self):
        """Should create bullish signal overlay."""
        sig = TVSignalOverlay(
            timestamp=1707945600,
            ticker="AAPL",
            stance="bullish",
            confidence=0.85,
        )
        assert sig.timestamp == 1707945600
        assert sig.ticker == "AAPL"
        assert sig.stance == "bullish"
        assert sig.confidence == 0.85

    def test_create_bearish_signal(self):
        """Should create bearish signal overlay."""
        sig = TVSignalOverlay(
            timestamp=1707945600,
            ticker="TSLA",
            stance="bearish",
            confidence=0.72,
        )
        assert sig.stance == "bearish"
        assert sig.confidence == 0.72

    def test_to_pine_arrays_bullish(self):
        """Should convert bullish signal to Pine arrays."""
        sig = TVSignalOverlay(
            timestamp=1707945600,
            ticker="AAPL",
            stance="bullish",
            confidence=0.85,
        )
        arrays = sig.to_pine_arrays()
        assert arrays["ts"] == 1707945600
        assert arrays["stance_code"] == 1
        assert arrays["conf"] == 0.85
        assert "AAPL" in arrays["label"]
        assert "0.85" in arrays["label"]

    def test_to_pine_arrays_bearish(self):
        """Should convert bearish signal to Pine arrays."""
        sig = TVSignalOverlay(
            timestamp=1707945600,
            ticker="TSLA",
            stance="bearish",
            confidence=0.72,
        )
        arrays = sig.to_pine_arrays()
        assert arrays["stance_code"] == -1
        assert arrays["conf"] == 0.72

    def test_to_pine_arrays_mixed(self):
        """Should convert mixed signal to Pine arrays."""
        sig = TVSignalOverlay(
            timestamp=1707945600,
            ticker="NVDA",
            stance="mixed",
            confidence=0.50,
        )
        arrays = sig.to_pine_arrays()
        assert arrays["stance_code"] == 0

    def test_to_pine_arrays_unknown(self):
        """Should convert unknown signal to Pine arrays."""
        sig = TVSignalOverlay(
            timestamp=1707945600,
            ticker="AMD",
            stance="unknown",
            confidence=0.30,
        )
        arrays = sig.to_pine_arrays()
        assert arrays["stance_code"] == 0

    def test_custom_label(self):
        """Should use custom label if provided."""
        sig = TVSignalOverlay(
            timestamp=1707945600,
            ticker="AAPL",
            stance="bullish",
            confidence=0.85,
            label="Custom Label",
        )
        arrays = sig.to_pine_arrays()
        assert arrays["label"] == "Custom Label"

    def test_enriched_fields(self):
        """Should store enriched fields."""
        sig = TVSignalOverlay(
            timestamp=1707945600,
            ticker="AAPL",
            stance="bullish",
            confidence=0.85,
            event_type="fda_approval",
            strategy="call_debit_spread",
            time_horizon="1_week",
            trend_score=0.92,
            signal_id="sig_123",
        )
        assert sig.event_type == "fda_approval"
        assert sig.strategy == "call_debit_spread"
        assert sig.time_horizon == "1_week"
        assert sig.trend_score == 0.92
        assert sig.signal_id == "sig_123"

    def test_immutable(self):
        """Signal overlay should be immutable."""
        sig = TVSignalOverlay(
            timestamp=1707945600,
            ticker="AAPL",
            stance="bullish",
            confidence=0.85,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            sig.confidence = 0.90  # type: ignore


class TestPineScriptConfig:
    """Test PineScriptConfig dataclass."""

    def test_default_config(self):
        """Should create config with defaults."""
        config = PineScriptConfig()
        assert config.ticker is None
        assert config.min_confidence == 0.0
        assert config.days == 30
        assert config.max_signals == 100

    def test_custom_config(self):
        """Should create config with custom values."""
        config = PineScriptConfig(
            ticker="AAPL",
            min_confidence=0.7,
            days=60,
            max_signals=50,
        )
        assert config.ticker == "AAPL"
        assert config.min_confidence == 0.7
        assert config.days == 60
        assert config.max_signals == 50

    def test_validate_success(self):
        """Valid config should pass validation."""
        config = PineScriptConfig(
            min_confidence=0.5,
            days=30,
            max_signals=100,
        )
        config.validate()  # Should not raise

    def test_validate_min_confidence_too_low(self):
        """Should reject min_confidence < 0.0."""
        config = PineScriptConfig(min_confidence=-0.1)
        with pytest.raises(ValueError, match="min_confidence"):
            config.validate()

    def test_validate_min_confidence_too_high(self):
        """Should reject min_confidence > 1.0."""
        config = PineScriptConfig(min_confidence=1.1)
        with pytest.raises(ValueError, match="min_confidence"):
            config.validate()

    def test_validate_days_too_low(self):
        """Should reject days < 1."""
        config = PineScriptConfig(days=0)
        with pytest.raises(ValueError, match="days"):
            config.validate()

    def test_validate_max_signals_too_low(self):
        """Should reject max_signals < 1."""
        config = PineScriptConfig(max_signals=0)
        with pytest.raises(ValueError, match="max_signals"):
            config.validate()

    def test_validate_strategy_commission_too_low(self):
        """Should reject strategy_commission < 0.0."""
        config = PineScriptConfig(strategy_commission=-0.01)
        with pytest.raises(ValueError, match="strategy_commission"):
            config.validate()

    def test_validate_strategy_commission_too_high(self):
        """Should reject strategy_commission > 1.0."""
        config = PineScriptConfig(strategy_commission=1.5)
        with pytest.raises(ValueError, match="strategy_commission"):
            config.validate()

    def test_validate_strategy_slippage_negative(self):
        """Should reject negative slippage."""
        config = PineScriptConfig(strategy_slippage=-1)
        with pytest.raises(ValueError, match="strategy_slippage"):
            config.validate()

    def test_validate_alert_min_confidence_too_low(self):
        """Should reject alert_min_confidence < 0.0."""
        config = PineScriptConfig(alert_min_confidence=-0.1)
        with pytest.raises(ValueError, match="alert_min_confidence"):
            config.validate()

    def test_validate_alert_min_confidence_too_high(self):
        """Should reject alert_min_confidence > 1.0."""
        config = PineScriptConfig(alert_min_confidence=1.5)
        with pytest.raises(ValueError, match="alert_min_confidence"):
            config.validate()

    def test_display_options(self):
        """Should store display options."""
        config = PineScriptConfig(
            show_labels=False,
            show_lines=True,
            show_confidence_color=False,
        )
        assert config.show_labels is False
        assert config.show_lines is True
        assert config.show_confidence_color is False

    def test_strategy_options(self):
        """Should store strategy options."""
        config = PineScriptConfig(
            strategy_capital=50000.0,
            strategy_commission=0.001,
            strategy_slippage=2,
        )
        assert config.strategy_capital == 50000.0
        assert config.strategy_commission == 0.001
        assert config.strategy_slippage == 2

    def test_alert_options(self):
        """Should store alert options."""
        config = PineScriptConfig(
            alert_on_bullish=False,
            alert_on_bearish=True,
            alert_min_confidence=0.8,
        )
        assert config.alert_on_bullish is False
        assert config.alert_on_bearish is True
        assert config.alert_min_confidence == 0.8

    def test_mutable(self):
        """Config should be mutable."""
        config = PineScriptConfig()
        config.ticker = "AAPL"
        config.min_confidence = 0.8
        assert config.ticker == "AAPL"
        assert config.min_confidence == 0.8
