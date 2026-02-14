"""Tests for TradingView tier gating.

Tests:
- gate_tradingview_access() across all tiers
- Feature access flags (pine_script_generator, signal_feed, webhook)
- Limits (max_script_signals, max_days_history)
"""

import pytest

from rot.web.tier_gate import gate_tradingview_access


class TestTradingViewTierGateFree:
    """Test TradingView access for Free tier."""

    def test_free_tier_has_basic_access(self):
        """Free tier can view TradingView page."""
        result = gate_tradingview_access("free")
        assert result["has_access"] is True

    def test_free_tier_no_pine_script_generator(self):
        """Free tier cannot generate Pine Scripts."""
        result = gate_tradingview_access("free")
        assert result["has_pine_script_generator"] is False

    def test_free_tier_no_signal_feed(self):
        """Free tier cannot access JSON signal feed."""
        result = gate_tradingview_access("free")
        assert result["has_signal_feed"] is False

    def test_free_tier_no_webhook(self):
        """Free tier cannot use webhook."""
        result = gate_tradingview_access("free")
        assert result["has_webhook"] is False

    def test_free_tier_zero_script_signals(self):
        """Free tier has 0 max script signals."""
        result = gate_tradingview_access("free")
        assert result["max_script_signals"] == 0

    def test_free_tier_zero_days_history(self):
        """Free tier has 0 days history."""
        result = gate_tradingview_access("free")
        assert result["max_days_history"] == 0


class TestTradingViewTierGatePro:
    """Test TradingView access for Pro tier."""

    def test_pro_tier_has_access(self):
        """Pro tier has full access."""
        result = gate_tradingview_access("pro")
        assert result["has_access"] is True

    def test_pro_tier_has_pine_script_generator(self):
        """Pro tier can generate Pine Scripts."""
        result = gate_tradingview_access("pro")
        assert result["has_pine_script_generator"] is True

    def test_pro_tier_has_signal_feed(self):
        """Pro tier can access signal feed."""
        result = gate_tradingview_access("pro")
        assert result["has_signal_feed"] is True

    def test_pro_tier_has_webhook(self):
        """Pro tier can use webhook."""
        result = gate_tradingview_access("pro")
        assert result["has_webhook"] is True

    def test_pro_tier_50_script_signals(self):
        """Pro tier has 50 max script signals."""
        result = gate_tradingview_access("pro")
        assert result["max_script_signals"] == 50

    def test_pro_tier_30_days_history(self):
        """Pro tier has 30 days history."""
        result = gate_tradingview_access("pro")
        assert result["max_days_history"] == 30


class TestTradingViewTierGatePremium:
    """Test TradingView access for Premium tier."""

    def test_premium_tier_has_access(self):
        """Premium tier has full access."""
        result = gate_tradingview_access("premium")
        assert result["has_access"] is True

    def test_premium_tier_has_pine_script_generator(self):
        """Premium tier can generate Pine Scripts."""
        result = gate_tradingview_access("premium")
        assert result["has_pine_script_generator"] is True

    def test_premium_tier_has_signal_feed(self):
        """Premium tier can access signal feed."""
        result = gate_tradingview_access("premium")
        assert result["has_signal_feed"] is True

    def test_premium_tier_has_webhook(self):
        """Premium tier can use webhook."""
        result = gate_tradingview_access("premium")
        assert result["has_webhook"] is True

    def test_premium_tier_100_script_signals(self):
        """Premium tier has 100 max script signals."""
        result = gate_tradingview_access("premium")
        assert result["max_script_signals"] == 100

    def test_premium_tier_90_days_history(self):
        """Premium tier has 90 days history."""
        result = gate_tradingview_access("premium")
        assert result["max_days_history"] == 90


class TestTradingViewTierGateUltra:
    """Test TradingView access for Ultra tier."""

    def test_ultra_tier_has_access(self):
        """Ultra tier has full access."""
        result = gate_tradingview_access("ultra")
        assert result["has_access"] is True

    def test_ultra_tier_has_pine_script_generator(self):
        """Ultra tier can generate Pine Scripts."""
        result = gate_tradingview_access("ultra")
        assert result["has_pine_script_generator"] is True

    def test_ultra_tier_has_signal_feed(self):
        """Ultra tier can access signal feed."""
        result = gate_tradingview_access("ultra")
        assert result["has_signal_feed"] is True

    def test_ultra_tier_has_webhook(self):
        """Ultra tier can use webhook."""
        result = gate_tradingview_access("ultra")
        assert result["has_webhook"] is True

    def test_ultra_tier_100_script_signals(self):
        """Ultra tier has 100 max script signals."""
        result = gate_tradingview_access("ultra")
        assert result["max_script_signals"] == 100

    def test_ultra_tier_365_days_history(self):
        """Ultra tier has 365 days history."""
        result = gate_tradingview_access("ultra")
        assert result["max_days_history"] == 365


class TestTradingViewTierGateEnterprise:
    """Test TradingView access for Enterprise tier."""

    def test_enterprise_tier_has_access(self):
        """Enterprise tier has full access."""
        result = gate_tradingview_access("enterprise")
        assert result["has_access"] is True

    def test_enterprise_tier_has_pine_script_generator(self):
        """Enterprise tier can generate Pine Scripts."""
        result = gate_tradingview_access("enterprise")
        assert result["has_pine_script_generator"] is True

    def test_enterprise_tier_has_signal_feed(self):
        """Enterprise tier can access signal feed."""
        result = gate_tradingview_access("enterprise")
        assert result["has_signal_feed"] is True

    def test_enterprise_tier_has_webhook(self):
        """Enterprise tier can use webhook."""
        result = gate_tradingview_access("enterprise")
        assert result["has_webhook"] is True

    def test_enterprise_tier_100_script_signals(self):
        """Enterprise tier has 100 max script signals."""
        result = gate_tradingview_access("enterprise")
        assert result["max_script_signals"] == 100

    def test_enterprise_tier_365_days_history(self):
        """Enterprise tier has 365 days history."""
        result = gate_tradingview_access("enterprise")
        assert result["max_days_history"] == 365


class TestTradingViewTierGateAdmin:
    """Test TradingView access for Admin tier."""

    def test_admin_tier_has_access(self):
        """Admin tier has full access."""
        result = gate_tradingview_access("admin")
        assert result["has_access"] is True

    def test_admin_tier_has_pine_script_generator(self):
        """Admin tier can generate Pine Scripts."""
        result = gate_tradingview_access("admin")
        assert result["has_pine_script_generator"] is True

    def test_admin_tier_has_signal_feed(self):
        """Admin tier can access signal feed."""
        result = gate_tradingview_access("admin")
        assert result["has_signal_feed"] is True

    def test_admin_tier_has_webhook(self):
        """Admin tier can use webhook."""
        result = gate_tradingview_access("admin")
        assert result["has_webhook"] is True

    def test_admin_tier_100_script_signals(self):
        """Admin tier has 100 max script signals."""
        result = gate_tradingview_access("admin")
        assert result["max_script_signals"] == 100

    def test_admin_tier_365_days_history(self):
        """Admin tier has 365 days history."""
        result = gate_tradingview_access("admin")
        assert result["max_days_history"] == 365


class TestTradingViewTierGateComparison:
    """Test tier comparisons and upgrades."""

    def test_free_to_pro_upgrade_unlocks_generator(self):
        """Upgrading from Free to Pro unlocks Pine Script generator."""
        free = gate_tradingview_access("free")
        pro = gate_tradingview_access("pro")

        assert free["has_pine_script_generator"] is False
        assert pro["has_pine_script_generator"] is True

    def test_pro_to_premium_increases_limits(self):
        """Upgrading from Pro to Premium increases limits."""
        pro = gate_tradingview_access("pro")
        premium = gate_tradingview_access("premium")

        assert pro["max_script_signals"] == 50
        assert premium["max_script_signals"] == 100

        assert pro["max_days_history"] == 30
        assert premium["max_days_history"] == 90

    def test_premium_to_ultra_increases_history(self):
        """Upgrading from Premium to Ultra increases history."""
        premium = gate_tradingview_access("premium")
        ultra = gate_tradingview_access("ultra")

        assert premium["max_days_history"] == 90
        assert ultra["max_days_history"] == 365

    def test_all_paid_tiers_have_core_features(self):
        """All paid tiers have core TradingView features."""
        for tier in ["pro", "premium", "ultra", "enterprise", "admin"]:
            result = gate_tradingview_access(tier)
            assert result["has_access"] is True
            assert result["has_pine_script_generator"] is True
            assert result["has_signal_feed"] is True
            assert result["has_webhook"] is True
