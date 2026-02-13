"""Tests for backtest tier gating."""

from __future__ import annotations

import pytest

from rot.web.tier_gate import gate_backtest_access


class TestFreeAccess:
    def test_no_access(self):
        access = gate_backtest_access("free")
        assert access["has_access"] is False
        assert access["has_basic"] is False
        assert access["max_days"] == 0
        assert access["max_signals"] == 0
        assert access["position_size_modes"] == []


class TestProAccess:
    def test_basic_only(self):
        access = gate_backtest_access("pro")
        assert access["has_access"] is True
        assert access["has_basic"] is True
        assert access["has_monte_carlo"] is False
        assert access["has_walk_forward"] is False
        assert access["has_risk_metrics"] is False
        assert access["has_optimizer"] is False

    def test_pro_limits(self):
        access = gate_backtest_access("pro")
        assert access["max_days"] == 30
        assert access["max_signals"] == 200
        assert access["position_size_modes"] == ["fixed_pct"]


class TestPremiumAccess:
    def test_advanced_features(self):
        access = gate_backtest_access("premium")
        assert access["has_access"] is True
        assert access["has_monte_carlo"] is True
        assert access["has_walk_forward"] is True
        assert access["has_risk_metrics"] is True
        assert access["has_benchmark"] is True
        assert access["has_optimizer"] is False
        assert access["has_comparison"] is False

    def test_premium_limits(self):
        access = gate_backtest_access("premium")
        assert access["max_days"] == 90
        assert access["max_signals"] == 1000
        assert "confidence_weighted" in access["position_size_modes"]


class TestUltraAccess:
    def test_full_access(self):
        access = gate_backtest_access("ultra")
        assert access["has_access"] is True
        assert access["has_monte_carlo"] is True
        assert access["has_optimizer"] is True
        assert access["has_comparison"] is True
        assert access["has_saved_strategies"] is True
        assert access["has_export"] is True

    def test_ultra_limits(self):
        access = gate_backtest_access("ultra")
        assert access["max_days"] == 365
        assert access["max_signals"] == 5000
        assert "kelly" in access["position_size_modes"]


class TestEnterpriseAccess:
    def test_same_as_ultra(self):
        ultra = gate_backtest_access("ultra")
        enterprise = gate_backtest_access("enterprise")
        assert ultra == enterprise


class TestTierHierarchy:
    def test_features_increase_with_tier(self):
        """Each tier should have >= features of the tier below."""
        tiers = ["free", "pro", "premium", "ultra", "enterprise"]
        prev_signals = 0
        prev_days = 0
        for tier in tiers:
            access = gate_backtest_access(tier)
            assert access["max_signals"] >= prev_signals
            assert access["max_days"] >= prev_days
            prev_signals = access["max_signals"]
            prev_days = access["max_days"]

    def test_all_tiers_return_expected_keys(self):
        expected_keys = {
            "has_access", "has_basic", "has_monte_carlo", "has_walk_forward",
            "has_risk_metrics", "has_benchmark", "has_optimizer", "has_comparison",
            "has_saved_strategies", "has_export", "max_days", "max_signals",
            "position_size_modes",
        }
        for tier in ["free", "pro", "premium", "ultra", "enterprise"]:
            access = gate_backtest_access(tier)
            assert set(access.keys()) == expected_keys, f"Missing keys for {tier}"
