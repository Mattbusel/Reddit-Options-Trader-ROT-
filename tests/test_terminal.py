import pytest

from rot.web.tier_gate import gate_terminal_access


class TestTerminalAccessGate:
    """Test Bloomberg-lite Terminal tier gate functionality."""

    def test_free_tier_no_access(self):
        """Free tier should have no Terminal access."""
        result = gate_terminal_access("free")
        assert result["has_access"] is False
        assert result["has_options_flow"] is False
        assert result["has_news_wire"] is False
        assert result["has_watchlist_alerts"] is False
        assert result["has_heatmap"] is False
        assert result["refresh_interval_s"] == 0
        assert result["max_signals_feed"] == 0

    def test_pro_tier_no_access(self):
        """Pro tier should have no Terminal access."""
        result = gate_terminal_access("pro")
        assert result["has_access"] is False
        assert result["has_options_flow"] is False
        assert result["has_news_wire"] is False
        assert result["has_watchlist_alerts"] is False
        assert result["has_heatmap"] is False
        assert result["refresh_interval_s"] == 0
        assert result["max_signals_feed"] == 0

    def test_premium_tier_basic_access(self):
        """Premium tier should have basic Terminal access."""
        result = gate_terminal_access("premium")
        assert result["has_access"] is True
        assert result["has_options_flow"] is False
        assert result["has_news_wire"] is True
        assert result["has_watchlist_alerts"] is False
        assert result["has_heatmap"] is True
        assert result["refresh_interval_s"] == 60
        assert result["max_signals_feed"] == 25

    def test_ultra_tier_full_access(self):
        """Ultra tier should have full Terminal access with fast refresh."""
        result = gate_terminal_access("ultra")
        assert result["has_access"] is True
        assert result["has_options_flow"] is True
        assert result["has_news_wire"] is True
        assert result["has_watchlist_alerts"] is True
        assert result["has_heatmap"] is True
        assert result["refresh_interval_s"] == 30
        assert result["max_signals_feed"] == 50

    def test_enterprise_tier_full_access(self):
        """Enterprise tier should have full Terminal access with fast refresh."""
        result = gate_terminal_access("enterprise")
        assert result["has_access"] is True
        assert result["has_options_flow"] is True
        assert result["has_news_wire"] is True
        assert result["has_watchlist_alerts"] is True
        assert result["has_heatmap"] is True
        assert result["refresh_interval_s"] == 30
        assert result["max_signals_feed"] == 50

    def test_has_options_flow_restricted_to_ultra_plus(self):
        """has_options_flow should only be available for ultra and enterprise tiers."""
        for tier in ("free", "pro", "premium"):
            assert gate_terminal_access(tier)["has_options_flow"] is False

        for tier in ("ultra", "enterprise"):
            assert gate_terminal_access(tier)["has_options_flow"] is True

    def test_has_news_wire_available_premium_plus(self):
        """has_news_wire should be available for premium and above."""
        for tier in ("free", "pro"):
            assert gate_terminal_access(tier)["has_news_wire"] is False

        for tier in ("premium", "ultra", "enterprise"):
            assert gate_terminal_access(tier)["has_news_wire"] is True

    def test_has_watchlist_alerts_restricted_to_ultra_plus(self):
        """has_watchlist_alerts should only be available for ultra and enterprise tiers."""
        for tier in ("free", "pro", "premium"):
            assert gate_terminal_access(tier)["has_watchlist_alerts"] is False

        for tier in ("ultra", "enterprise"):
            assert gate_terminal_access(tier)["has_watchlist_alerts"] is True

    def test_refresh_interval_progression(self):
        """refresh_interval_s should progress: 0 (free/pro) -> 60 (premium) -> 30 (ultra/enterprise)."""
        assert gate_terminal_access("free")["refresh_interval_s"] == 0
        assert gate_terminal_access("pro")["refresh_interval_s"] == 0
        assert gate_terminal_access("premium")["refresh_interval_s"] == 60
        assert gate_terminal_access("ultra")["refresh_interval_s"] == 30
        assert gate_terminal_access("enterprise")["refresh_interval_s"] == 30

    def test_max_signals_feed_progression(self):
        """max_signals_feed should progress: 0 (free/pro) -> 25 (premium) -> 50 (ultra/enterprise)."""
        assert gate_terminal_access("free")["max_signals_feed"] == 0
        assert gate_terminal_access("pro")["max_signals_feed"] == 0
        assert gate_terminal_access("premium")["max_signals_feed"] == 25
        assert gate_terminal_access("ultra")["max_signals_feed"] == 50
        assert gate_terminal_access("enterprise")["max_signals_feed"] == 50

    def test_has_heatmap_available_premium_plus(self):
        """has_heatmap should be available for premium and above."""
        for tier in ("free", "pro"):
            assert gate_terminal_access(tier)["has_heatmap"] is False

        for tier in ("premium", "ultra", "enterprise"):
            assert gate_terminal_access(tier)["has_heatmap"] is True

    def test_return_dict_keys(self):
        """Return dict should have all expected keys."""
        result = gate_terminal_access("premium")
        expected_keys = {
            "has_access",
            "has_options_flow",
            "has_news_wire",
            "has_watchlist_alerts",
            "has_heatmap",
            "refresh_interval_s",
            "max_signals_feed",
        }
        assert set(result.keys()) == expected_keys

    def test_all_tiers_have_access_key(self):
        """All tiers should return has_access key."""
        for tier in ("free", "pro", "premium", "ultra", "enterprise"):
            result = gate_terminal_access(tier)
            assert "has_access" in result
            assert isinstance(result["has_access"], bool)
