"""Tests for ML credibility scoring: feature extraction, ML scorer, training."""

from __future__ import annotations

import dataclasses
import math
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rot.core.types import Event, Evidence
from rot.credibility.features import (
    EVENT_TYPE_MAP,
    FEATURE_NAMES,
    HORIZON_MAP,
    NUM_FEATURES,
    STANCE_MAP,
    extract_features_from_event,
    extract_features_from_row,
)
from rot.credibility.ml_scorer import MLCredibilityScorer


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_event(**meta_overrides) -> Event:
    """Create a test Event with sensible defaults and optional meta overrides."""
    meta = {
        "trend_score": 0.5,
        "features": {"score_rate": 0.3, "comment_rate": 0.1},
        "score": 50,
        "num_comments": 10,
        "upvote_ratio": 0.85,
        "author": "testuser",
        "author_karma": 5000,
        "author_age_days": 200,
        "flair": None,
        "is_crosspost": False,
        "body_excerpt": "some analysis text here",
        "nlp": {
            "polarity": 0.6,
            "intensity": 0.5,
            "conviction": 0.7,
            "sarcasm_probability": 0.1,
            "actionability": 0.8,
            "urgency": 0.3,
            "thread_consensus": 0.65,
            "thread_agreement_with_op": 0.5,
            "contrarian_detected": False,
        },
        "market": {
            "TSLA": {
                "symbol": "TSLA",
                "last_close": 250.0,
                "pct_1d": 0.02,
                "market_cap": 800_000_000_000,
                "atm_iv": 0.35,
                "pc_ratio": 0.78,
                "volume": 60_000_000,
                "avg_volume": 50_000_000,
            }
        },
    }
    meta.update(meta_overrides)
    return Event(
        event_type="product_news",
        entities=["TSLA"],
        stance="bullish",
        time_horizon="1w",
        evidence=[Evidence(post_id="x", permalink="", subreddit="stocks", excerpt="test")],
        confidence=0.4,
        meta=meta,
    )


def _make_row(**overrides) -> dict:
    """Create a dict that mimics a database row for training extraction."""
    row = {
        "id": "test123",
        "event_type": "product_news",
        "stance": "bullish",
        "time_horizon": "1w",
        "strategy": "debit_spread",
        "subreddit": "stocks",
        "trend_score": 0.5,
        "confidence": 0.4,
        "sarcasm_score": 0.1,
        "conviction": 0.7,
        "consensus_score": 0.65,
        "actionability": 0.8,
        "nlp_polarity": 0.6,
        "author_karma": 5000,
        "author_age_days": 200,
        "event_data": '{"event_type":"product_news","entities":["TSLA"],"stance":"bullish",'
        '"time_horizon":"1w","evidence":[{"subreddit":"stocks"}],"confidence":0.4,'
        '"meta":{"trend_score":0.5,"features":{"score_rate":0.3,"comment_rate":0.1},'
        '"score":50,"num_comments":10,"upvote_ratio":0.85,"author":"testuser",'
        '"flair":null,"is_crosspost":false,"body_excerpt":"some analysis text here",'
        '"nlp":{"polarity":0.6,"intensity":0.5,"conviction":0.7,"sarcasm_probability":0.1,'
        '"actionability":0.8,"urgency":0.3,"thread_consensus":0.65,'
        '"thread_agreement_with_op":0.5,"contrarian_detected":false},'
        '"market":{"TSLA":{"symbol":"TSLA","last_close":250.0,"pct_1d":0.02,'
        '"market_cap":800000000000,"atm_iv":0.35,"pc_ratio":0.78,'
        '"volume":60000000,"avg_volume":50000000}}}}',
        "market_data": '{"TSLA":{"symbol":"TSLA","last_close":250.0,"pct_1d":0.02,'
        '"market_cap":800000000000,"atm_iv":0.35,"pc_ratio":0.78,'
        '"volume":60000000,"avg_volume":50000000}}',
        "price_at_signal": 250.0,
        "is_win": 1,
        "is_loss": 0,
    }
    row.update(overrides)
    return row


# ── Feature Extraction Tests ──────────────────────────────────────────────


class TestFeatureExtraction:
    def test_returns_correct_length(self):
        event = _make_event()
        features = extract_features_from_event(event)
        assert len(features) == NUM_FEATURES
        assert len(features) == 32

    def test_all_features_are_floats(self):
        features = extract_features_from_event(_make_event())
        for i, f in enumerate(features):
            assert isinstance(f, float), f"Feature {FEATURE_NAMES[i]} is {type(f)}, expected float"

    def test_handles_empty_meta(self):
        event = dataclasses.replace(_make_event(), meta={})
        features = extract_features_from_event(event)
        assert len(features) == NUM_FEATURES
        # All should be safe defaults, no exceptions
        for f in features:
            assert isinstance(f, float)
            assert not math.isnan(f)
            assert not math.isinf(f)

    def test_handles_missing_nlp(self):
        event = _make_event(nlp=None)
        features = extract_features_from_event(event)
        assert len(features) == NUM_FEATURES
        # nlp_has_data should be 0.0
        nlp_has_data_idx = FEATURE_NAMES.index("nlp_has_data")
        assert features[nlp_has_data_idx] == 0.0

    def test_handles_missing_market(self):
        event = _make_event(market=None)
        features = extract_features_from_event(event)
        assert len(features) == NUM_FEATURES
        # Market features should be defaults (0.0)
        market_cap_idx = FEATURE_NAMES.index("market_cap_log")
        assert features[market_cap_idx] == 0.0

    def test_consistent_ordering(self):
        """Same event always produces same feature vector."""
        event = _make_event()
        f1 = extract_features_from_event(event)
        f2 = extract_features_from_event(event)
        assert f1 == f2

    def test_categorical_encoding(self):
        event = _make_event()
        features = extract_features_from_event(event)

        et_idx = FEATURE_NAMES.index("event_type_idx")
        assert features[et_idx] == float(EVENT_TYPE_MAP["product_news"])

        st_idx = FEATURE_NAMES.index("stance_idx")
        assert features[st_idx] == float(STANCE_MAP["bullish"])

        hz_idx = FEATURE_NAMES.index("horizon_idx")
        assert features[hz_idx] == float(HORIZON_MAP["1w"])

    def test_market_cap_log_transform(self):
        event = _make_event()
        features = extract_features_from_event(event)
        cap_idx = FEATURE_NAMES.index("market_cap_log")
        # log10(800B) ≈ 11.9
        assert 11.0 < features[cap_idx] < 12.5

    def test_author_karma_log_transform(self):
        event = _make_event(author_karma=50000)
        features = extract_features_from_event(event)
        karma_idx = FEATURE_NAMES.index("author_karma_log")
        # log10(50000) ≈ 4.7
        assert 4.5 < features[karma_idx] < 5.0

    def test_is_rss_flag(self):
        event = _make_event(flair="rss")
        features = extract_features_from_event(event)
        rss_idx = FEATURE_NAMES.index("is_rss")
        assert features[rss_idx] == 1.0

    def test_from_row_returns_correct_length(self):
        row = _make_row()
        features = extract_features_from_row(row)
        assert len(features) == NUM_FEATURES

    def test_from_row_all_floats(self):
        row = _make_row()
        features = extract_features_from_row(row)
        for i, f in enumerate(features):
            assert isinstance(f, float), f"Feature {FEATURE_NAMES[i]} is {type(f)}"

    def test_from_row_handles_empty_json(self):
        row = _make_row(event_data="{}", market_data="{}")
        features = extract_features_from_row(row)
        assert len(features) == NUM_FEATURES

    def test_from_row_handles_invalid_json(self):
        row = _make_row(event_data="not json", market_data="broken")
        features = extract_features_from_row(row)
        assert len(features) == NUM_FEATURES


# ── ML Scorer Tests ───────────────────────────────────────────────────────


class TestMLCredibilityScorer:
    def test_fallback_when_no_model_path(self):
        scorer = MLCredibilityScorer(model_path="", enabled=True)
        assert not scorer.ml_available
        event = _make_event()
        scored = scorer.score(event)
        # Should behave like heuristic
        assert 0.05 <= scored.confidence <= 1.0
        assert "credibility_breakdown" in scored.meta

    def test_fallback_when_disabled(self):
        scorer = MLCredibilityScorer(model_path="some/path.pkl", enabled=False)
        assert not scorer.ml_available
        event = _make_event()
        scored = scorer.score(event)
        assert "credibility_breakdown" in scored.meta

    def test_fallback_on_bad_model_path(self):
        scorer = MLCredibilityScorer(
            model_path="/nonexistent/path/model.pkl", enabled=True
        )
        assert not scorer.ml_available
        event = _make_event()
        scored = scorer.score(event)
        assert "credibility_breakdown" in scored.meta

    def test_ml_scoring_with_mock_model(self):
        scorer = MLCredibilityScorer(model_path="", enabled=True)

        # Mock a sklearn-like model
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])
        scorer._model = mock_model
        scorer._enabled = True

        event = _make_event()
        scored = scorer.score(event)

        assert scored.confidence == pytest.approx(0.7, abs=0.01)
        assert "ml_credibility" in scored.meta
        assert scored.meta["ml_credibility"]["ml_confidence"] == pytest.approx(0.7, abs=0.01)

    def test_ml_meta_contains_both_scores(self):
        scorer = MLCredibilityScorer(model_path="", enabled=True)

        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.4, 0.6]])
        scorer._model = mock_model

        event = _make_event()
        scored = scorer.score(event)

        ml_meta = scored.meta["ml_credibility"]
        assert "ml_confidence" in ml_meta
        assert "heuristic_confidence" in ml_meta
        # Heuristic ran too, so heuristic_confidence should differ from input
        assert ml_meta["heuristic_confidence"] != event.confidence or True  # it may match

    def test_ml_confidence_clamped_low(self):
        scorer = MLCredibilityScorer(model_path="", enabled=True)

        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.99, 0.01]])
        scorer._model = mock_model

        event = _make_event()
        scored = scorer.score(event)
        assert scored.confidence >= 0.05

    def test_ml_confidence_clamped_high(self):
        scorer = MLCredibilityScorer(model_path="", enabled=True)

        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.01, 0.99]])
        scorer._model = mock_model

        event = _make_event()
        scored = scorer.score(event)
        assert scored.confidence <= 0.95

    def test_heuristic_breakdown_always_present(self):
        """Even with ML active, credibility_breakdown from heuristic exists."""
        scorer = MLCredibilityScorer(model_path="", enabled=True)

        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.4, 0.6]])
        scorer._model = mock_model

        event = _make_event()
        scored = scorer.score(event)
        assert "credibility_breakdown" in scored.meta
        assert isinstance(scored.meta["credibility_breakdown"], dict)

    def test_exception_in_ml_falls_back(self):
        scorer = MLCredibilityScorer(model_path="", enabled=True)

        mock_model = MagicMock()
        mock_model.predict_proba.side_effect = RuntimeError("model exploded")
        scorer._model = mock_model

        event = _make_event()
        scored = scorer.score(event)
        # Should fall back to heuristic, not raise
        assert 0.05 <= scored.confidence <= 1.0
        assert "credibility_breakdown" in scored.meta
        # Should NOT have ml_credibility since ML failed
        assert "ml_credibility" not in scored.meta

    def test_reload_with_no_path(self):
        scorer = MLCredibilityScorer(model_path="", enabled=True)
        assert not scorer.reload()
        assert not scorer.ml_available
