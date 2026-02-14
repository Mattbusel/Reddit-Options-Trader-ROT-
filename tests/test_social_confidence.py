"""Tests for rot.social.confidence.AuthorConfidenceAdjuster."""

import pytest

from rot.social.confidence import AuthorConfidenceAdjuster, ConfidenceAdjusterConfig
from rot.social.types import AuthorProfile


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_profile(
    *,
    author_id: str = "author1",
    platform: str = "reddit",
    username: str = "test_user",
    win_count: int = 0,
    loss_count: int = 0,
    accuracy: float | None = None,
    reputation_score: float | None = None,
    total_signals: int = 0,
) -> AuthorProfile:
    return AuthorProfile(
        id=author_id,
        platform=platform,
        username=username,
        total_signals=total_signals,
        win_count=win_count,
        loss_count=loss_count,
        accuracy=accuracy,
        reputation_score=reputation_score,
    )


# ── ConfidenceAdjusterConfig ────────────────────────────────────────────────


class TestConfidenceAdjusterConfig:
    def test_defaults(self):
        cfg = ConfidenceAdjusterConfig()
        assert cfg.max_boost == 0.15
        assert cfg.max_penalty == 0.15
        assert cfg.min_predictions_to_adjust == 10
        assert cfg.accuracy_neutral_point == 0.50
        assert cfg.reputation_weight == 0.6
        assert cfg.accuracy_weight == 0.4
        assert cfg.enabled is True

    def test_custom_values(self):
        cfg = ConfidenceAdjusterConfig(
            max_boost=0.20,
            max_penalty=0.10,
            min_predictions_to_adjust=5,
            accuracy_neutral_point=0.55,
            reputation_weight=0.3,
            accuracy_weight=0.7,
            enabled=False,
        )
        assert cfg.max_boost == 0.20
        assert cfg.max_penalty == 0.10
        assert cfg.min_predictions_to_adjust == 5
        assert cfg.accuracy_neutral_point == 0.55
        assert cfg.reputation_weight == 0.3
        assert cfg.accuracy_weight == 0.7
        assert cfg.enabled is False


# ── Cache management ────────────────────────────────────────────────────────


class TestCacheManagement:
    def test_update_cache_bulk(self):
        adj = AuthorConfidenceAdjuster()
        profiles = [
            _make_profile(author_id="a1", username="u1"),
            _make_profile(author_id="a2", username="u2"),
            _make_profile(author_id="a3", username="u3"),
        ]
        adj.update_cache(profiles)
        assert adj.get_cached_profile_count() == 3

    def test_update_cache_overwrites_existing(self):
        adj = AuthorConfidenceAdjuster()
        p1 = _make_profile(author_id="a1", username="u1", win_count=5, loss_count=5)
        p2 = _make_profile(author_id="a1", username="u1", win_count=10, loss_count=10)
        adj.update_cache([p1])
        adj.update_cache([p2])
        assert adj.get_cached_profile_count() == 1

    def test_set_profile_single(self):
        adj = AuthorConfidenceAdjuster()
        p = _make_profile(author_id="solo")
        adj.set_profile(p)
        assert adj.get_cached_profile_count() == 1

    def test_clear_cache(self):
        adj = AuthorConfidenceAdjuster()
        adj.update_cache([
            _make_profile(author_id="a1", username="u1"),
            _make_profile(author_id="a2", username="u2"),
        ])
        assert adj.get_cached_profile_count() == 2
        adj.clear_cache()
        assert adj.get_cached_profile_count() == 0

    def test_get_cached_profile_count_empty(self):
        adj = AuthorConfidenceAdjuster()
        assert adj.get_cached_profile_count() == 0


# ── get_adjustment ──────────────────────────────────────────────────────────


class TestGetAdjustment:
    def test_returns_zero_when_disabled(self):
        cfg = ConfidenceAdjusterConfig(enabled=False)
        adj = AuthorConfidenceAdjuster(cfg)
        p = _make_profile(win_count=20, loss_count=0, accuracy=1.0, reputation_score=100.0)
        adj.set_profile(p)
        assert adj.get_adjustment("author1") == 0.0

    def test_returns_zero_when_author_not_in_cache(self):
        adj = AuthorConfidenceAdjuster()
        assert adj.get_adjustment("nonexistent") == 0.0

    def test_returns_zero_when_insufficient_predictions(self):
        cfg = ConfidenceAdjusterConfig(min_predictions_to_adjust=10)
        adj = AuthorConfidenceAdjuster(cfg)
        # 3 wins + 3 losses = 6 decided, below threshold of 10
        p = _make_profile(win_count=3, loss_count=3, reputation_score=50.0)
        adj.set_profile(p)
        assert adj.get_adjustment("author1") == 0.0

    def test_positive_adjustment_high_accuracy(self):
        cfg = ConfidenceAdjusterConfig(min_predictions_to_adjust=5)
        adj = AuthorConfidenceAdjuster(cfg)
        # 9 wins / 1 loss = 0.9 accuracy => well above 0.5 neutral
        p = _make_profile(win_count=9, loss_count=1, reputation_score=75.0)
        adj.set_profile(p)
        result = adj.get_adjustment("author1")
        assert result > 0.0

    def test_negative_adjustment_low_accuracy(self):
        cfg = ConfidenceAdjusterConfig(min_predictions_to_adjust=5)
        adj = AuthorConfidenceAdjuster(cfg)
        # 1 win / 9 losses = 0.1 accuracy => well below 0.5 neutral
        p = _make_profile(win_count=1, loss_count=9, reputation_score=25.0)
        adj.set_profile(p)
        result = adj.get_adjustment("author1")
        assert result < 0.0

    def test_scaling_with_max_boost(self):
        cfg = ConfidenceAdjusterConfig(
            max_boost=0.20,
            min_predictions_to_adjust=2,
            accuracy_weight=1.0,
            reputation_weight=0.0,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        # Perfect accuracy => accuracy_score = 1.0, combined = 1.0, adjustment = 1.0 * 0.20
        p = _make_profile(win_count=10, loss_count=0, accuracy=1.0)
        adj.set_profile(p)
        result = adj.get_adjustment("author1")
        assert result == pytest.approx(0.20, abs=1e-6)

    def test_scaling_with_max_penalty(self):
        cfg = ConfidenceAdjusterConfig(
            max_penalty=0.10,
            min_predictions_to_adjust=2,
            accuracy_weight=1.0,
            reputation_weight=0.0,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        # Zero accuracy => accuracy_score = -1.0, combined = -1.0, adjustment = -1.0 * 0.10
        p = _make_profile(win_count=0, loss_count=10, accuracy=0.0)
        adj.set_profile(p)
        result = adj.get_adjustment("author1")
        assert result == pytest.approx(-0.10, abs=1e-6)

    def test_reputation_only_influence(self):
        cfg = ConfidenceAdjusterConfig(
            min_predictions_to_adjust=2,
            accuracy_weight=0.0,
            reputation_weight=1.0,
            max_boost=0.15,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        # reputation=100 => rep_score = (100-50)/50 = 1.0, combined = 1.0 * 1.0 = 1.0
        p = _make_profile(win_count=5, loss_count=5, reputation_score=100.0)
        adj.set_profile(p)
        result = adj.get_adjustment("author1")
        assert result == pytest.approx(0.15, abs=1e-6)

    def test_reputation_penalty_influence(self):
        cfg = ConfidenceAdjusterConfig(
            min_predictions_to_adjust=2,
            accuracy_weight=0.0,
            reputation_weight=1.0,
            max_penalty=0.15,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        # reputation=0 => rep_score = (0-50)/50 = -1.0, combined = -1.0
        p = _make_profile(win_count=5, loss_count=5, reputation_score=0.0)
        adj.set_profile(p)
        result = adj.get_adjustment("author1")
        assert result == pytest.approx(-0.15, abs=1e-6)

    def test_neutral_reputation_no_effect(self):
        cfg = ConfidenceAdjusterConfig(
            min_predictions_to_adjust=2,
            accuracy_weight=0.0,
            reputation_weight=1.0,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        # reputation=50 => rep_score = 0.0
        p = _make_profile(win_count=5, loss_count=5, reputation_score=50.0)
        adj.set_profile(p)
        result = adj.get_adjustment("author1")
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_no_reputation_defaults_to_zero(self):
        cfg = ConfidenceAdjusterConfig(
            min_predictions_to_adjust=2,
            accuracy_weight=0.0,
            reputation_weight=1.0,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        # reputation_score=None => reputation component = 0.0
        p = _make_profile(win_count=5, loss_count=5, reputation_score=None)
        adj.set_profile(p)
        result = adj.get_adjustment("author1")
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_accuracy_from_computed_when_explicit_is_none(self):
        """When accuracy is None, computed_accuracy from win/loss is used."""
        cfg = ConfidenceAdjusterConfig(
            min_predictions_to_adjust=2,
            accuracy_weight=1.0,
            reputation_weight=0.0,
            max_boost=0.15,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        # accuracy=None, computed_accuracy = 8/10 = 0.8
        p = _make_profile(win_count=8, loss_count=2, accuracy=None)
        adj.set_profile(p)
        result = adj.get_adjustment("author1")
        # accuracy_score = (0.8 - 0.5) / 0.5 = 0.6
        # combined = 1.0 * 0.6 = 0.6
        # adjustment = 0.6 * 0.15 = 0.09
        assert result == pytest.approx(0.09, abs=1e-6)

    def test_explicit_accuracy_overrides_computed(self):
        """Explicit accuracy field takes precedence over computed."""
        cfg = ConfidenceAdjusterConfig(
            min_predictions_to_adjust=2,
            accuracy_weight=1.0,
            reputation_weight=0.0,
            max_boost=0.15,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        # explicit accuracy=0.9, even though computed would be 5/10=0.5
        p = _make_profile(win_count=5, loss_count=5, accuracy=0.9)
        adj.set_profile(p)
        result = adj.get_adjustment("author1")
        # accuracy_score = (0.9 - 0.5) / 0.5 = 0.8
        # combined = 1.0 * 0.8 = 0.8
        # adjustment = 0.8 * 0.15 = 0.12
        assert result == pytest.approx(0.12, abs=1e-6)


# ── adjust_confidence ───────────────────────────────────────────────────────


class TestAdjustConfidence:
    def test_applies_positive_adjustment(self):
        cfg = ConfidenceAdjusterConfig(
            min_predictions_to_adjust=2,
            accuracy_weight=1.0,
            reputation_weight=0.0,
            max_boost=0.10,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        p = _make_profile(win_count=10, loss_count=0, accuracy=1.0)
        adj.set_profile(p)
        new_conf, applied = adj.adjust_confidence("author1", 0.50)
        assert applied == pytest.approx(0.10, abs=1e-6)
        assert new_conf == pytest.approx(0.60, abs=1e-6)

    def test_clamps_to_upper_bound(self):
        cfg = ConfidenceAdjusterConfig(
            min_predictions_to_adjust=2,
            accuracy_weight=1.0,
            reputation_weight=0.0,
            max_boost=0.20,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        p = _make_profile(win_count=10, loss_count=0, accuracy=1.0)
        adj.set_profile(p)
        new_conf, applied = adj.adjust_confidence("author1", 0.95)
        assert new_conf == 1.0
        assert applied == pytest.approx(0.20, abs=1e-6)

    def test_clamps_to_lower_bound(self):
        cfg = ConfidenceAdjusterConfig(
            min_predictions_to_adjust=2,
            accuracy_weight=1.0,
            reputation_weight=0.0,
            max_penalty=0.20,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        p = _make_profile(win_count=0, loss_count=10, accuracy=0.0)
        adj.set_profile(p)
        new_conf, applied = adj.adjust_confidence("author1", 0.10)
        assert new_conf == 0.05  # clamped to floor
        assert applied == pytest.approx(-0.20, abs=1e-6)

    def test_no_adjustment_when_disabled(self):
        cfg = ConfidenceAdjusterConfig(enabled=False)
        adj = AuthorConfidenceAdjuster(cfg)
        p = _make_profile(win_count=10, loss_count=0, accuracy=1.0, reputation_score=100.0)
        adj.set_profile(p)
        new_conf, applied = adj.adjust_confidence("author1", 0.50)
        assert new_conf == 0.50
        assert applied == 0.0

    def test_returns_tuple(self):
        adj = AuthorConfidenceAdjuster()
        result = adj.adjust_confidence("nobody", 0.60)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result == (0.60, 0.0)


# ── get_adjustment_explanation ──────────────────────────────────────────────


class TestGetAdjustmentExplanation:
    def test_reason_disabled(self):
        cfg = ConfidenceAdjusterConfig(enabled=False)
        adj = AuthorConfidenceAdjuster(cfg)
        explanation = adj.get_adjustment_explanation("anyone")
        assert explanation["reason"] == "disabled"
        assert explanation["adjustment"] == 0.0

    def test_reason_no_profile(self):
        adj = AuthorConfidenceAdjuster()
        explanation = adj.get_adjustment_explanation("ghost")
        assert explanation["reason"] == "no_profile"
        assert explanation["has_profile"] is False
        assert explanation["adjustment"] == 0.0

    def test_reason_insufficient_data(self):
        cfg = ConfidenceAdjusterConfig(min_predictions_to_adjust=20)
        adj = AuthorConfidenceAdjuster(cfg)
        p = _make_profile(win_count=3, loss_count=3, reputation_score=50.0)
        adj.set_profile(p)
        explanation = adj.get_adjustment_explanation("author1")
        assert explanation["reason"] == "insufficient_data"
        assert explanation["has_profile"] is True
        assert explanation["decided_count"] == 6
        assert explanation["adjustment"] == 0.0

    def test_reason_boosted_high_accuracy(self):
        cfg = ConfidenceAdjusterConfig(min_predictions_to_adjust=2)
        adj = AuthorConfidenceAdjuster(cfg)
        p = _make_profile(win_count=9, loss_count=1, reputation_score=80.0)
        adj.set_profile(p)
        explanation = adj.get_adjustment_explanation("author1")
        assert explanation["reason"] == "boosted_high_accuracy"
        assert explanation["adjustment"] > 0.0
        assert explanation["has_profile"] is True

    def test_reason_penalized_low_accuracy(self):
        cfg = ConfidenceAdjusterConfig(min_predictions_to_adjust=2)
        adj = AuthorConfidenceAdjuster(cfg)
        p = _make_profile(win_count=1, loss_count=9, reputation_score=10.0)
        adj.set_profile(p)
        explanation = adj.get_adjustment_explanation("author1")
        assert explanation["reason"] == "penalized_low_accuracy"
        assert explanation["adjustment"] < 0.0

    def test_reason_neutral(self):
        cfg = ConfidenceAdjusterConfig(
            min_predictions_to_adjust=2,
            accuracy_weight=1.0,
            reputation_weight=0.0,
        )
        adj = AuthorConfidenceAdjuster(cfg)
        # accuracy exactly at neutral (0.5) => adjustment = 0
        p = _make_profile(win_count=5, loss_count=5, reputation_score=None)
        adj.set_profile(p)
        explanation = adj.get_adjustment_explanation("author1")
        assert explanation["reason"] == "neutral"
        assert explanation["adjustment"] == 0.0
