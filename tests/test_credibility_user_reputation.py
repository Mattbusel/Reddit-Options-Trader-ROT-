"""Tests for the UserReputation scoring system (src/rot/credibility/user_reputation.py)."""

from __future__ import annotations

import math
import time

import pytest

from rot.credibility.user_reputation import (
    ReputationStore,
    UserReputation,
    UserReputationScorer,
)


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def scorer() -> UserReputationScorer:
    return UserReputationScorer()


# ── UserReputation dataclass ───────────────────────────────


class TestUserReputationDataclass:
    def test_fields_present(self) -> None:
        rep = UserReputation(
            username="testuser",
            karma_score=0.5,
            post_history_score=0.6,
            accuracy_score=0.6,
            pump_dump_flag=False,
            weight=0.7,
        )
        assert rep.username == "testuser"
        assert rep.karma_score == 0.5
        assert rep.post_history_score == 0.6
        assert rep.accuracy_score == 0.6
        assert rep.pump_dump_flag is False
        assert rep.weight == 0.7

    def test_to_dict_keys(self) -> None:
        rep = UserReputation(
            username="u",
            karma_score=0.1,
            post_history_score=0.5,
            accuracy_score=0.5,
            pump_dump_flag=False,
            weight=0.4,
        )
        d = rep.to_dict()
        expected_keys = {"username", "karma_score", "post_history_score", "accuracy_score", "pump_dump_flag", "weight", "scored_at"}
        assert set(d.keys()) == expected_keys

    def test_scored_at_defaults_to_now(self) -> None:
        before = time.time()
        rep = UserReputation(
            username="u", karma_score=0.5, post_history_score=0.5,
            accuracy_score=0.5, pump_dump_flag=False, weight=0.5,
        )
        after = time.time()
        assert before <= rep.scored_at <= after


# ── ReputationStore ────────────────────────────────────────


class TestReputationStore:
    def test_upsert_and_get(self) -> None:
        store = ReputationStore()
        rep = UserReputation(
            username="alpha",
            karma_score=0.5, post_history_score=0.5,
            accuracy_score=0.5, pump_dump_flag=False, weight=0.6,
        )
        store.upsert(rep)
        assert store.get("alpha") is rep

    def test_get_missing_returns_none(self) -> None:
        store = ReputationStore()
        assert store.get("nobody") is None

    def test_upsert_replaces(self) -> None:
        store = ReputationStore()
        rep1 = UserReputation("x", 0.1, 0.1, 0.1, False, 0.2)
        rep2 = UserReputation("x", 0.9, 0.9, 0.9, False, 0.95)
        store.upsert(rep1)
        store.upsert(rep2)
        assert store.get("x") is rep2

    def test_len(self) -> None:
        store = ReputationStore()
        for i in range(5):
            store.upsert(UserReputation(f"u{i}", 0.5, 0.5, 0.5, False, 0.5))
        assert len(store) == 5

    def test_all_sorted_by_weight_desc(self) -> None:
        store = ReputationStore()
        for weight in [0.3, 0.9, 0.1, 0.7]:
            store.upsert(UserReputation(f"u{weight}", 0.5, 0.5, 0.5, False, weight))
        all_reps = store.all()
        weights = [r.weight for r in all_reps]
        assert weights == sorted(weights, reverse=True)


# ── UserReputationScorer ───────────────────────────────────


class TestUserReputationScorerBasics:
    def test_returns_user_reputation_instance(self, scorer: UserReputationScorer) -> None:
        rep = scorer.score("user1")
        assert isinstance(rep, UserReputation)

    def test_username_preserved(self, scorer: UserReputationScorer) -> None:
        rep = scorer.score("wsb_legend")
        assert rep.username == "wsb_legend"

    def test_weight_in_valid_range(self, scorer: UserReputationScorer) -> None:
        rep = scorer.score("u", karma=1000, account_age_days=100)
        assert 0.05 <= rep.weight <= 1.0

    def test_persist_stores_in_store(self, scorer: UserReputationScorer) -> None:
        scorer.score("persist_user", persist=True)
        assert scorer.store.get("persist_user") is not None

    def test_no_persist_does_not_store(self, scorer: UserReputationScorer) -> None:
        scorer.score("ephemeral", persist=False)
        assert scorer.store.get("ephemeral") is None


class TestKarmaScoring:
    def test_zero_karma_low_weight(self, scorer: UserReputationScorer) -> None:
        rep = scorer.score("newbie", karma=0, account_age_days=0)
        assert rep.karma_score == pytest.approx(0.0)

    def test_high_karma_high_score(self, scorer: UserReputationScorer) -> None:
        rep_low = scorer.score("low", karma=100)
        rep_high = scorer.score("high", karma=500_000)
        assert rep_high.karma_score > rep_low.karma_score

    def test_negative_karma_treated_as_zero(self, scorer: UserReputationScorer) -> None:
        rep = scorer.score("neg", karma=-5000)
        assert rep.karma_score == pytest.approx(0.0)

    def test_karma_score_max_one(self, scorer: UserReputationScorer) -> None:
        rep = scorer.score("whale", karma=10_000_000)
        assert rep.karma_score <= 1.0


class TestAccountAgeScoring:
    def test_new_account_low_weight(self, scorer: UserReputationScorer) -> None:
        rep = scorer.score("brand_new", account_age_days=5)
        # Age is 0.10, karma 0, accuracy neutral — weight should be low
        assert rep.weight < 0.5

    def test_veteran_account_boosts_weight(self) -> None:
        scorer = UserReputationScorer()
        rep_new = scorer.score("new", karma=5000, account_age_days=10)
        rep_vet = scorer.score("vet", karma=5000, account_age_days=800)
        assert rep_vet.weight > rep_new.weight


class TestManipulationFlag:
    def test_pump_dump_flag_set(self, scorer: UserReputationScorer) -> None:
        rep = scorer.score("pumper", manipulation_flags=2)
        assert rep.pump_dump_flag is True

    def test_pump_dump_flag_clear(self, scorer: UserReputationScorer) -> None:
        rep = scorer.score("clean", manipulation_flags=0)
        assert rep.pump_dump_flag is False

    def test_manipulation_flag_reduces_weight(self) -> None:
        scorer = UserReputationScorer()
        clean = scorer.score("clean", karma=50000, account_age_days=500, manipulation_flags=0)
        flagged = scorer.score("flagged", karma=50000, account_age_days=500, manipulation_flags=1)
        assert flagged.weight < clean.weight

    def test_min_weight_floor_applies(self, scorer: UserReputationScorer) -> None:
        rep = scorer.score("worst", karma=0, account_age_days=0, manipulation_flags=99)
        assert rep.weight >= 0.05


class TestApplyToConfidence:
    def test_known_user_adjusts_confidence(self, scorer: UserReputationScorer) -> None:
        scorer.score("known", karma=50000, account_age_days=500, persist=True)
        rep = scorer.store.get("known")
        assert rep is not None
        adjusted = scorer.apply_to_confidence(0.80, "known")
        assert adjusted == pytest.approx(0.80 * rep.weight, rel=1e-6)

    def test_unknown_user_unchanged(self, scorer: UserReputationScorer) -> None:
        adjusted = scorer.apply_to_confidence(0.75, "nobody_stored")
        assert adjusted == pytest.approx(0.75)

    def test_adjusted_confidence_clamped_to_one(self, scorer: UserReputationScorer) -> None:
        # Weight is always <= 1.0, so product is always <= confidence
        adjusted = scorer.apply_to_confidence(1.0, "nobody")
        assert adjusted <= 1.0

    def test_adjusted_confidence_non_negative(self) -> None:
        scorer = UserReputationScorer()
        scorer.score("flag", karma=0, account_age_days=0, manipulation_flags=5, persist=True)
        adjusted = scorer.apply_to_confidence(0.5, "flag")
        assert adjusted >= 0.0
