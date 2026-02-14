"""
Tests for agent tier gating in rot.web.tier_gate.

This module tests the gate_agent_access() function across all subscription tiers,
verifying feature access, agent limits, and enterprise-only capabilities.
"""

import pytest

from rot.web.tier_gate import gate_agent_access


class TestAgentTierGateFree:
    """Test agent access for Free tier."""

    def test_free_tier_no_access(self):
        """Free tier should have no agent access."""
        result = gate_agent_access("free")
        assert result["has_access"] is False

    def test_free_tier_zero_agents(self):
        """Free tier should have 0 max agents."""
        result = gate_agent_access("free")
        assert result["max_agents"] == 0

    def test_free_tier_no_signal_follower(self):
        """Free tier should not have signal follower agent."""
        result = gate_agent_access("free")
        assert result["has_signal_follower"] is False

    def test_free_tier_no_contrarian(self):
        """Free tier should not have contrarian agent."""
        result = gate_agent_access("free")
        assert result["has_contrarian"] is False

    def test_free_tier_no_momentum_rider(self):
        """Free tier should not have momentum rider agent."""
        result = gate_agent_access("free")
        assert result["has_momentum_rider"] is False

    def test_free_tier_no_custom_rules(self):
        """Free tier should not have custom rules."""
        result = gate_agent_access("free")
        assert result["has_custom_rules"] is False

    def test_free_tier_no_performance_export(self):
        """Free tier should not have performance export."""
        result = gate_agent_access("free")
        assert result["has_performance_export"] is False

    def test_free_tier_no_api(self):
        """Free tier should not have agent API access."""
        result = gate_agent_access("free")
        assert result["has_api"] is False


class TestAgentTierGatePro:
    """Test agent access for Pro tier."""

    def test_pro_tier_no_access(self):
        """Pro tier should have no agent access."""
        result = gate_agent_access("pro")
        assert result["has_access"] is False

    def test_pro_tier_zero_agents(self):
        """Pro tier should have 0 max agents."""
        result = gate_agent_access("pro")
        assert result["max_agents"] == 0

    def test_pro_tier_no_signal_follower(self):
        """Pro tier should not have signal follower agent."""
        result = gate_agent_access("pro")
        assert result["has_signal_follower"] is False

    def test_pro_tier_no_contrarian(self):
        """Pro tier should not have contrarian agent."""
        result = gate_agent_access("pro")
        assert result["has_contrarian"] is False

    def test_pro_tier_no_momentum_rider(self):
        """Pro tier should not have momentum rider agent."""
        result = gate_agent_access("pro")
        assert result["has_momentum_rider"] is False

    def test_pro_tier_no_custom_rules(self):
        """Pro tier should not have custom rules."""
        result = gate_agent_access("pro")
        assert result["has_custom_rules"] is False

    def test_pro_tier_no_performance_export(self):
        """Pro tier should not have performance export."""
        result = gate_agent_access("pro")
        assert result["has_performance_export"] is False

    def test_pro_tier_no_api(self):
        """Pro tier should not have agent API access."""
        result = gate_agent_access("pro")
        assert result["has_api"] is False


class TestAgentTierGatePremium:
    """Test agent access for Premium tier."""

    def test_premium_tier_no_access(self):
        """Premium tier should have no agent access."""
        result = gate_agent_access("premium")
        assert result["has_access"] is False

    def test_premium_tier_zero_agents(self):
        """Premium tier should have 0 max agents."""
        result = gate_agent_access("premium")
        assert result["max_agents"] == 0

    def test_premium_tier_no_signal_follower(self):
        """Premium tier should not have signal follower agent."""
        result = gate_agent_access("premium")
        assert result["has_signal_follower"] is False

    def test_premium_tier_no_contrarian(self):
        """Premium tier should not have contrarian agent."""
        result = gate_agent_access("premium")
        assert result["has_contrarian"] is False

    def test_premium_tier_no_momentum_rider(self):
        """Premium tier should not have momentum rider agent."""
        result = gate_agent_access("premium")
        assert result["has_momentum_rider"] is False

    def test_premium_tier_no_custom_rules(self):
        """Premium tier should not have custom rules."""
        result = gate_agent_access("premium")
        assert result["has_custom_rules"] is False

    def test_premium_tier_no_performance_export(self):
        """Premium tier should not have performance export."""
        result = gate_agent_access("premium")
        assert result["has_performance_export"] is False

    def test_premium_tier_no_api(self):
        """Premium tier should not have agent API access."""
        result = gate_agent_access("premium")
        assert result["has_api"] is False


class TestAgentTierGateUltra:
    """Test agent access for Ultra tier."""

    def test_ultra_tier_has_access(self):
        """Ultra tier should have agent access."""
        result = gate_agent_access("ultra")
        assert result["has_access"] is True

    def test_ultra_tier_max_agents_three(self):
        """Ultra tier should have max 3 agents."""
        result = gate_agent_access("ultra")
        assert result["max_agents"] == 3

    def test_ultra_tier_has_signal_follower(self):
        """Ultra tier should have signal follower agent."""
        result = gate_agent_access("ultra")
        assert result["has_signal_follower"] is True

    def test_ultra_tier_has_contrarian(self):
        """Ultra tier should have contrarian agent."""
        result = gate_agent_access("ultra")
        assert result["has_contrarian"] is True

    def test_ultra_tier_has_momentum_rider(self):
        """Ultra tier should have momentum rider agent."""
        result = gate_agent_access("ultra")
        assert result["has_momentum_rider"] is True

    def test_ultra_tier_no_custom_rules(self):
        """Ultra tier should NOT have custom rules (enterprise-only)."""
        result = gate_agent_access("ultra")
        assert result["has_custom_rules"] is False

    def test_ultra_tier_no_performance_export(self):
        """Ultra tier should NOT have performance export (enterprise-only)."""
        result = gate_agent_access("ultra")
        assert result["has_performance_export"] is False

    def test_ultra_tier_no_api(self):
        """Ultra tier should NOT have agent API access (enterprise-only)."""
        result = gate_agent_access("ultra")
        assert result["has_api"] is False

    def test_ultra_tier_all_results_present(self):
        """Ultra tier result should have all expected keys."""
        result = gate_agent_access("ultra")
        assert "has_access" in result
        assert "max_agents" in result
        assert "has_signal_follower" in result
        assert "has_contrarian" in result
        assert "has_momentum_rider" in result
        assert "has_custom_rules" in result
        assert "has_performance_export" in result
        assert "has_api" in result


class TestAgentTierGateEnterprise:
    """Test agent access for Enterprise tier."""

    def test_enterprise_tier_has_access(self):
        """Enterprise tier should have agent access."""
        result = gate_agent_access("enterprise")
        assert result["has_access"] is True

    def test_enterprise_tier_max_agents_ten(self):
        """Enterprise tier should have max 10 agents."""
        result = gate_agent_access("enterprise")
        assert result["max_agents"] == 10

    def test_enterprise_tier_has_signal_follower(self):
        """Enterprise tier should have signal follower agent."""
        result = gate_agent_access("enterprise")
        assert result["has_signal_follower"] is True

    def test_enterprise_tier_has_contrarian(self):
        """Enterprise tier should have contrarian agent."""
        result = gate_agent_access("enterprise")
        assert result["has_contrarian"] is True

    def test_enterprise_tier_has_momentum_rider(self):
        """Enterprise tier should have momentum rider agent."""
        result = gate_agent_access("enterprise")
        assert result["has_momentum_rider"] is True

    def test_enterprise_tier_has_custom_rules(self):
        """Enterprise tier should have custom rules."""
        result = gate_agent_access("enterprise")
        assert result["has_custom_rules"] is True

    def test_enterprise_tier_has_performance_export(self):
        """Enterprise tier should have performance export."""
        result = gate_agent_access("enterprise")
        assert result["has_performance_export"] is True

    def test_enterprise_tier_has_api(self):
        """Enterprise tier should have agent API access."""
        result = gate_agent_access("enterprise")
        assert result["has_api"] is True

    def test_enterprise_tier_all_results_present(self):
        """Enterprise tier result should have all expected keys."""
        result = gate_agent_access("enterprise")
        assert "has_access" in result
        assert "max_agents" in result
        assert "has_signal_follower" in result
        assert "has_contrarian" in result
        assert "has_momentum_rider" in result
        assert "has_custom_rules" in result
        assert "has_performance_export" in result
        assert "has_api" in result


class TestAgentTierGateComparison:
    """Cross-tier comparison tests for agent access."""

    def test_free_vs_pro_same_access(self):
        """Free and Pro tiers should have identical agent access."""
        free = gate_agent_access("free")
        pro = gate_agent_access("pro")
        assert free == pro

    def test_free_vs_premium_same_access(self):
        """Free and Premium tiers should have identical agent access."""
        free = gate_agent_access("free")
        premium = gate_agent_access("premium")
        assert free == premium

    def test_pro_vs_premium_same_access(self):
        """Pro and Premium tiers should have identical agent access."""
        pro = gate_agent_access("pro")
        premium = gate_agent_access("premium")
        assert pro == premium

    def test_ultra_has_more_agents_than_free(self):
        """Ultra tier should have more agents than Free tier."""
        ultra = gate_agent_access("ultra")
        free = gate_agent_access("free")
        assert ultra["max_agents"] > free["max_agents"]

    def test_enterprise_has_more_agents_than_ultra(self):
        """Enterprise tier should have more agents than Ultra tier."""
        enterprise = gate_agent_access("enterprise")
        ultra = gate_agent_access("ultra")
        assert enterprise["max_agents"] > ultra["max_agents"]

    def test_enterprise_only_tier_with_custom_rules(self):
        """Enterprise should be only tier with custom_rules."""
        for tier in ("free", "pro", "premium", "ultra"):
            result = gate_agent_access(tier)
            assert result["has_custom_rules"] is False

        result = gate_agent_access("enterprise")
        assert result["has_custom_rules"] is True

    def test_enterprise_only_tier_with_performance_export(self):
        """Enterprise should be only tier with performance_export."""
        for tier in ("free", "pro", "premium", "ultra"):
            result = gate_agent_access(tier)
            assert result["has_performance_export"] is False

        result = gate_agent_access("enterprise")
        assert result["has_performance_export"] is True

    def test_enterprise_only_tier_with_api(self):
        """Enterprise should be only tier with API access."""
        for tier in ("free", "pro", "premium", "ultra"):
            result = gate_agent_access(tier)
            assert result["has_api"] is False

        result = gate_agent_access("enterprise")
        assert result["has_api"] is True

    def test_all_tiers_have_same_keys(self):
        """All tiers should return dicts with identical keys."""
        tiers = ("free", "pro", "premium", "ultra", "enterprise")
        results = [gate_agent_access(tier) for tier in tiers]
        keys = set(results[0].keys())

        for result in results[1:]:
            assert set(result.keys()) == keys


class TestAgentTierGateReturnTypes:
    """Test return value types for agent tier gate."""

    def test_has_access_is_bool(self):
        """has_access should always be a boolean."""
        for tier in ("free", "pro", "premium", "ultra", "enterprise"):
            result = gate_agent_access(tier)
            assert isinstance(result["has_access"], bool)

    def test_max_agents_is_int(self):
        """max_agents should always be an integer."""
        for tier in ("free", "pro", "premium", "ultra", "enterprise"):
            result = gate_agent_access(tier)
            assert isinstance(result["max_agents"], int)

    def test_max_agents_non_negative(self):
        """max_agents should never be negative."""
        for tier in ("free", "pro", "premium", "ultra", "enterprise"):
            result = gate_agent_access(tier)
            assert result["max_agents"] >= 0

    def test_agent_features_are_bool(self):
        """Agent feature flags should always be booleans."""
        bool_keys = (
            "has_signal_follower",
            "has_contrarian",
            "has_momentum_rider",
            "has_custom_rules",
            "has_performance_export",
            "has_api",
        )
        for tier in ("free", "pro", "premium", "ultra", "enterprise"):
            result = gate_agent_access(tier)
            for key in bool_keys:
                assert isinstance(result[key], bool), f"{key} should be bool for {tier}"
