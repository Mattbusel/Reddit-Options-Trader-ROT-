"""Tests for ML-powered strategy optimizer.

Tests the MLStrategyOptimizer class, which uses GradientBoostingClassifier
to discover winning signal patterns and auto-generate StrategyRule objects.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, List

import pytest

from rot.strategy.ml_optimizer import (
    FEATURE_NAMES,
    NUM_FEATURES,
    MLStrategyOptimizer,
    _safe_float,
    _safe_log,
    _parse_json_field,
    _get_market_data,
    _get_nlp_data,
    _get_meta,
    _market_cap_bucket,
    _body_length_bucket,
)

# Try to import sklearn — skip tests if not available
try:
    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier

    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def basic_signal() -> Dict[str, Any]:
    """A minimal signal dict for feature extraction."""
    return {
        "id": "sig-basic",
        "ticker": "AAPL",
        "stance": "bullish",
        "confidence": 0.65,
        "event_type": "earnings_rumor",
        "time_horizon": "1w",
        "subreddit": "stocks",
        "quality_score": 0.7,
        "trend_score": 0.25,
        "created_at": time.time(),
        "price_at_signal": 150.0,
        "price_1d": 155.0,
        "event_data": json.dumps({
            "meta": {
                "score": 100,
                "num_comments": 50,
                "upvote_ratio": 0.85,
                "nlp": {
                    "polarity": 0.8,
                    "conviction": 0.7,
                    "sarcasm_probability": 0.0,
                    "actionability": 0.9,
                    "thread_consensus": 0.75,
                }
            }
        }),
        "market_data": json.dumps({
            "AAPL": {
                "pct_1d": 3.33,
                "market_cap": 2.5e12,
                "atm_iv": 0.25,
                "pc_ratio": 0.8,
            }
        }),
    }


@pytest.fixture
def mock_training_signals() -> List[Dict[str, Any]]:
    """Generate 300 mock signals for training with predictable patterns."""
    signals = []
    base_time = time.time()

    for i in range(300):
        stance = random.choice(["bullish", "bearish"])
        base_price = 150.0

        # Create predictable patterns for training
        confidence = random.uniform(0.3, 0.9)

        # Higher confidence signals tend to win, lower confidence tends to lose
        if confidence > 0.65:
            # Win: price moves in direction of stance
            bias = 10.0 if stance == "bullish" else -10.0
        else:
            # Lose: price moves against stance
            bias = -10.0 if stance == "bullish" else 10.0

        price_1d = base_price + random.uniform(-3, 3) + bias

        subreddit = random.choice(["stocks", "options", "wallstreetbets"])
        event_type = random.choice(["earnings_rumor", "product_news", "regulatory"])

        # Build signal dict
        sig = {
            "id": f"sig-{i}",
            "ticker": random.choice(["AAPL", "TSLA", "NVDA"]),
            "stance": stance,
            "confidence": confidence,
            "event_type": event_type,
            "time_horizon": random.choice(["intraday", "1w", "earnings"]),
            "subreddit": subreddit,
            "quality_score": random.uniform(0.2, 0.8),
            "trend_score": random.uniform(0.05, 0.5),
            "created_at": base_time - i * 3600,
            "price_at_signal": base_price,
            "price_1d": price_1d,
            "event_data": json.dumps({
                "entities": [random.choice(["AAPL", "TSLA"])],
                "meta": {
                    "score": random.randint(10, 200),
                    "num_comments": random.randint(5, 100),
                    "upvote_ratio": random.uniform(0.5, 0.95),
                    "body_excerpt": "Sample body text " * random.randint(0, 5),
                    "author_karma": random.randint(100, 100000),
                    "author_age_days": random.randint(10, 1000),
                    "nlp": {
                        "polarity": random.uniform(-1.0, 1.0),
                        "conviction": random.uniform(0.3, 0.9),
                        "sarcasm_probability": random.uniform(0.0, 0.3),
                        "actionability": random.uniform(0.4, 1.0),
                        "thread_consensus": random.uniform(0.3, 0.9),
                        "intensity": random.uniform(0.2, 0.8),
                        "urgency": random.uniform(0.2, 0.8),
                    }
                }
            }),
            "market_data": json.dumps({
                random.choice(["AAPL", "TSLA"]): {
                    "pct_1d": ((price_1d - base_price) / base_price) * 100,
                    "market_cap": random.uniform(1e9, 1e12),
                    "atm_iv": random.uniform(0.15, 0.6),
                    "pc_ratio": random.uniform(0.5, 1.5),
                    "volume": random.uniform(1e6, 1e8),
                    "avg_volume": random.uniform(1e6, 1e8),
                }
            }),
        }

        signals.append(sig)

    return signals


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_safe_float():
    """Test _safe_float() handles various inputs."""
    assert _safe_float(3.14) == 3.14
    assert _safe_float("2.5") == 2.5
    assert _safe_float(None) == 0.0
    assert _safe_float("invalid") == 0.0
    assert _safe_float(float("nan")) == 0.0
    assert _safe_float(float("inf")) == 0.0
    assert _safe_float(None, default=1.0) == 1.0


def test_safe_log():
    """Test _safe_log() handles non-positive values."""
    assert _safe_log(100.0) == 2.0
    assert _safe_log(10.0) == 1.0
    assert _safe_log(0.0) == 0.0
    assert _safe_log(-5.0) == 0.0
    assert _safe_log(None) == 0.0


def test_parse_json_field():
    """Test _parse_json_field() handles dict, str, and invalid inputs."""
    assert _parse_json_field({"key": "value"}) == {"key": "value"}
    assert _parse_json_field('{"key": "value"}') == {"key": "value"}
    assert _parse_json_field("invalid json") == {}
    assert _parse_json_field(None) == {}
    assert _parse_json_field(123) == {}


def test_get_market_data():
    """Test _get_market_data() extracts market data dict."""
    signal = {
        "ticker": "AAPL",
        "market_data": json.dumps({
            "AAPL": {"price": 150.0, "cap": 2e12}
        })
    }
    mkt = _get_market_data(signal)
    assert mkt["price"] == 150.0
    assert mkt["cap"] == 2e12

    # Fallback to first dict value if ticker not found
    signal_fallback = {
        "ticker": "TSLA",
        "market_data": json.dumps({
            "OTHER": {"price": 100.0}
        })
    }
    mkt2 = _get_market_data(signal_fallback)
    assert mkt2["price"] == 100.0

    # Empty market_data
    assert _get_market_data({}) == {}


def test_get_nlp_data():
    """Test _get_nlp_data() extracts NLP dict from event_data.meta.nlp."""
    signal = {
        "event_data": json.dumps({
            "meta": {
                "nlp": {"polarity": 0.8, "conviction": 0.7}
            }
        })
    }
    nlp = _get_nlp_data(signal)
    assert nlp["polarity"] == 0.8
    assert nlp["conviction"] == 0.7

    # Missing nlp
    assert _get_nlp_data({}) == {}


def test_get_meta():
    """Test _get_meta() extracts meta dict from event_data."""
    signal = {
        "event_data": json.dumps({
            "meta": {"score": 100, "num_comments": 50}
        })
    }
    meta = _get_meta(signal)
    assert meta["score"] == 100
    assert meta["num_comments"] == 50


def test_market_cap_bucket():
    """Test _market_cap_bucket() ordinal encoding."""
    assert _market_cap_bucket(0.0) == 0.0  # unknown
    assert _market_cap_bucket(1e9) == 1.0  # small (<2B)
    assert _market_cap_bucket(5e9) == 2.0  # mid (<10B)
    assert _market_cap_bucket(50e9) == 3.0  # large (<200B)
    assert _market_cap_bucket(500e9) == 4.0  # mega (>=200B)


def test_body_length_bucket():
    """Test _body_length_bucket() ordinal encoding."""
    assert _body_length_bucket(0.0) == 0.0  # none
    assert _body_length_bucket(50.0) == 1.0  # short (<100)
    assert _body_length_bucket(250.0) == 2.0  # medium (<500)
    assert _body_length_bucket(600.0) == 3.0  # long


# ---------------------------------------------------------------------------
# MLStrategyOptimizer initialization tests
# ---------------------------------------------------------------------------


def test_optimizer_init():
    """Test MLStrategyOptimizer initialization."""
    opt = MLStrategyOptimizer(min_signals=100)
    assert opt.min_signals == 100
    assert opt.is_trained is False
    assert opt.feature_names == list(FEATURE_NAMES)
    assert len(opt.feature_names) == NUM_FEATURES


def test_optimizer_init_min_signals_floor():
    """Test min_signals is floored at 10."""
    opt = MLStrategyOptimizer(min_signals=5)
    assert opt.min_signals == 10


# ---------------------------------------------------------------------------
# Feature extraction tests
# ---------------------------------------------------------------------------


def test_extract_features_returns_correct_length(basic_signal):
    """Test _extract_features() returns exactly NUM_FEATURES floats."""
    opt = MLStrategyOptimizer()
    features = opt._extract_features(basic_signal)

    assert isinstance(features, list)
    assert len(features) == NUM_FEATURES
    assert all(isinstance(f, float) for f in features)


def test_extract_features_handles_missing_fields():
    """Test _extract_features() returns 0.0 for missing fields."""
    opt = MLStrategyOptimizer()
    minimal_signal = {
        "id": "sig-min",
        "ticker": "AAPL",
        "stance": "bullish",
    }

    features = opt._extract_features(minimal_signal)
    assert len(features) == NUM_FEATURES
    # Most features should be 0.0 or default values
    assert features[0] == 0.0  # confidence (missing)
    assert features[1] == 0.0  # trend_score (missing)


def test_extract_features_core_values(basic_signal):
    """Test _extract_features() extracts core values correctly."""
    opt = MLStrategyOptimizer()
    features = opt._extract_features(basic_signal)

    # Check first 3 features (confidence, trend_score, quality_score)
    assert features[0] == 0.65  # confidence
    assert features[1] == 0.25  # trend_score
    assert features[2] == 0.7  # quality_score

    # Check stance encoding (index 3)
    assert features[3] == 1.0  # bullish encoded as 1.0


def test_extract_features_event_type_onehot(basic_signal):
    """Test _extract_features() one-hot encodes event_type correctly."""
    opt = MLStrategyOptimizer()
    features = opt._extract_features(basic_signal)

    # Event type one-hot is indices 4-9
    # earnings_rumor should be index 4
    assert features[4] == 1.0  # evt_earnings_rumor
    assert features[5] == 0.0  # evt_product_news
    assert features[6] == 0.0  # evt_regulatory


def test_extract_features_subreddit_onehot(basic_signal):
    """Test _extract_features() one-hot encodes subreddit correctly."""
    opt = MLStrategyOptimizer()
    features = opt._extract_features(basic_signal)

    # Subreddit one-hot is indices 10-15
    # "stocks" should be index 11
    assert features[10] == 0.0  # sub_wallstreetbets
    assert features[11] == 1.0  # sub_stocks
    assert features[12] == 0.0  # sub_options
    assert features[15] == 0.0  # sub_other


def test_extract_features_nlp_values(basic_signal):
    """Test _extract_features() extracts NLP values correctly."""
    opt = MLStrategyOptimizer()
    features = opt._extract_features(basic_signal)

    # NLP features are indices 22-26
    assert features[22] == 0.8  # nlp_polarity
    assert features[23] == 0.7  # nlp_conviction
    assert features[24] == 0.0  # nlp_sarcasm_prob
    assert features[25] == 0.9  # nlp_actionability
    assert features[26] == 0.75  # nlp_consensus_score


def test_extract_features_market_data(basic_signal):
    """Test _extract_features() extracts market data correctly."""
    opt = MLStrategyOptimizer()
    features = opt._extract_features(basic_signal)

    # Market data is indices 17-21
    assert abs(features[17] - 3.33) < 0.01  # price_change_pct
    assert features[18] == 4.0  # market_cap_bucket (mega)
    assert features[19] == 0.25  # iv
    assert features[20] == 0.8  # put_call_ratio


# ---------------------------------------------------------------------------
# Signal labelling tests
# ---------------------------------------------------------------------------


def test_label_signals_bullish_win():
    """Test _label_signals() correctly labels bullish+up as win."""
    opt = MLStrategyOptimizer()
    signals = [
        {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.7,
            "event_type": "earnings_rumor",
            "price_at_signal": 100.0,
            "price_1d": 105.0,  # up -> win
            "event_data": "{}",
            "market_data": "{}",
        }
    ]

    features, labels = opt._label_signals(signals)
    assert len(labels) == 1
    assert labels[0] == 1  # win


def test_label_signals_bullish_loss():
    """Test _label_signals() correctly labels bullish+down as loss."""
    opt = MLStrategyOptimizer()
    signals = [
        {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.7,
            "event_type": "earnings_rumor",
            "price_at_signal": 100.0,
            "price_1d": 95.0,  # down -> loss
            "event_data": "{}",
            "market_data": "{}",
        }
    ]

    features, labels = opt._label_signals(signals)
    assert len(labels) == 1
    assert labels[0] == 0  # loss


def test_label_signals_bearish_win():
    """Test _label_signals() correctly labels bearish+down as win."""
    opt = MLStrategyOptimizer()
    signals = [
        {
            "ticker": "AAPL",
            "stance": "bearish",
            "confidence": 0.7,
            "event_type": "regulatory",
            "price_at_signal": 100.0,
            "price_1d": 95.0,  # down -> win
            "event_data": "{}",
            "market_data": "{}",
        }
    ]

    features, labels = opt._label_signals(signals)
    assert len(labels) == 1
    assert labels[0] == 1  # win


def test_label_signals_bearish_loss():
    """Test _label_signals() correctly labels bearish+up as loss."""
    opt = MLStrategyOptimizer()
    signals = [
        {
            "ticker": "AAPL",
            "stance": "bearish",
            "confidence": 0.7,
            "event_type": "regulatory",
            "price_at_signal": 100.0,
            "price_1d": 105.0,  # up -> loss
            "event_data": "{}",
            "market_data": "{}",
        }
    ]

    features, labels = opt._label_signals(signals)
    assert len(labels) == 1
    assert labels[0] == 0  # loss


def test_label_signals_skips_missing_price():
    """Test _label_signals() skips signals without price data."""
    opt = MLStrategyOptimizer()
    signals = [
        {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.7,
            "event_type": "earnings_rumor",
            "price_at_signal": 100.0,
            # Missing price_1d, price_4h, price_1h
            "event_data": "{}",
            "market_data": "{}",
        }
    ]

    features, labels = opt._label_signals(signals)
    assert len(labels) == 0  # skipped


def test_label_signals_skips_non_directional_stance():
    """Test _label_signals() skips mixed/unknown stances."""
    opt = MLStrategyOptimizer()
    signals = [
        {
            "ticker": "AAPL",
            "stance": "mixed",
            "confidence": 0.7,
            "event_type": "earnings_rumor",
            "price_at_signal": 100.0,
            "price_1d": 105.0,
            "event_data": "{}",
            "market_data": "{}",
        },
        {
            "ticker": "TSLA",
            "stance": "unknown",
            "confidence": 0.7,
            "event_type": "product_news",
            "price_at_signal": 150.0,
            "price_1d": 155.0,
            "event_data": "{}",
            "market_data": "{}",
        },
    ]

    features, labels = opt._label_signals(signals)
    assert len(labels) == 0  # both skipped


def test_label_signals_fallback_to_price_4h():
    """Test _label_signals() falls back to price_4h if price_1d missing."""
    opt = MLStrategyOptimizer()
    signals = [
        {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.7,
            "event_type": "earnings_rumor",
            "price_at_signal": 100.0,
            "price_4h": 105.0,  # fallback
            "event_data": "{}",
            "market_data": "{}",
        }
    ]

    features, labels = opt._label_signals(signals)
    assert len(labels) == 1
    assert labels[0] == 1  # win (up)


def test_label_signals_fallback_to_price_1h():
    """Test _label_signals() falls back to price_1h if price_4h also missing."""
    opt = MLStrategyOptimizer()
    signals = [
        {
            "ticker": "AAPL",
            "stance": "bearish",
            "confidence": 0.7,
            "event_type": "regulatory",
            "price_at_signal": 100.0,
            "price_1h": 95.0,  # fallback
            "event_data": "{}",
            "market_data": "{}",
        }
    ]

    features, labels = opt._label_signals(signals)
    assert len(labels) == 1
    assert labels[0] == 1  # win (down)


# ---------------------------------------------------------------------------
# Training tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_train_with_sufficient_signals(mock_training_signals):
    """Test train() with sufficient signals returns accuracy > 0."""
    opt = MLStrategyOptimizer(min_signals=100)
    result = opt.train(mock_training_signals)

    assert result["trained"] is True
    assert result["accuracy"] > 0.0
    assert result["accuracy_std"] >= 0.0
    assert result["n_samples"] >= 100
    assert result["n_features"] == NUM_FEATURES
    assert result["n_wins"] > 0
    assert result["n_losses"] > 0
    assert "feature_importances" in result
    assert opt.is_trained is True


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_train_with_insufficient_signals():
    """Test train() with insufficient signals returns trained=False."""
    opt = MLStrategyOptimizer(min_signals=500)
    signals = [
        {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.7,
            "event_type": "earnings_rumor",
            "price_at_signal": 100.0,
            "price_1d": 105.0,
            "event_data": "{}",
            "market_data": "{}",
        }
    ]

    result = opt.train(signals)
    assert result["trained"] is False
    assert result["reason"] == "insufficient_data"
    assert result["n_samples"] == 1
    assert result["min_required"] == 500


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_train_with_class_imbalance():
    """Test train() with severe class imbalance returns trained=False."""
    opt = MLStrategyOptimizer(min_signals=10)

    # Create 100 signals but all wins (no losses)
    signals = []
    for i in range(100):
        signals.append({
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.7,
            "event_type": "earnings_rumor",
            "price_at_signal": 100.0,
            "price_1d": 105.0,  # all wins
            "event_data": "{}",
            "market_data": "{}",
        })

    result = opt.train(signals)
    assert result["trained"] is False
    assert result["reason"] == "class_imbalance"
    assert result["n_wins"] == 100
    assert result["n_losses"] == 0


@pytest.mark.skipif(_HAS_SKLEARN, reason="sklearn is installed")
def test_train_without_sklearn():
    """Test train() without sklearn returns trained=False."""
    opt = MLStrategyOptimizer()
    signals = []
    result = opt.train(signals)

    assert result["trained"] is False
    assert result["reason"] == "sklearn_not_installed"


# ---------------------------------------------------------------------------
# Feature importance tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_get_feature_importance_after_training(mock_training_signals):
    """Test get_feature_importance() returns sorted list after training."""
    opt = MLStrategyOptimizer(min_signals=100)
    opt.train(mock_training_signals)

    importances = opt.get_feature_importance()
    assert len(importances) > 0
    assert all(isinstance(name, str) for name, _ in importances)
    assert all(isinstance(imp, float) for _, imp in importances)

    # Check sorted descending
    imp_values = [imp for _, imp in importances]
    assert imp_values == sorted(imp_values, reverse=True)


def test_get_feature_importance_before_training():
    """Test get_feature_importance() returns empty list before training."""
    opt = MLStrategyOptimizer()
    importances = opt.get_feature_importance()
    assert importances == []


# ---------------------------------------------------------------------------
# Rule generation tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_generate_rules_after_training(mock_training_signals):
    """Test generate_rules() produces StrategyRule objects after training."""
    opt = MLStrategyOptimizer(min_signals=100)
    opt.train(mock_training_signals)

    rules = opt.generate_rules(top_n=5)
    assert isinstance(rules, list)
    assert len(rules) <= 5
    assert len(rules) > 0  # should generate at least some rules

    # Check rule structure
    for rule in rules:
        assert hasattr(rule, "field")
        assert hasattr(rule, "operator")
        assert hasattr(rule, "value")
        assert rule.field is not None
        assert rule.operator in ("gte", "lte", "eq", "neq", "in")


def test_generate_rules_before_training():
    """Test generate_rules() returns empty list before training."""
    opt = MLStrategyOptimizer()
    rules = opt.generate_rules(top_n=5)
    assert rules == []


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_generate_rules_avoids_duplicates(mock_training_signals):
    """Test generate_rules() avoids duplicate rules on same field."""
    opt = MLStrategyOptimizer(min_signals=100)
    opt.train(mock_training_signals)

    rules = opt.generate_rules(top_n=10)
    fields = [r.field for r in rules]

    # Each field should appear at most once
    assert len(fields) == len(set(fields))


# ---------------------------------------------------------------------------
# Optimize pipeline tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_optimize_full_pipeline(mock_training_signals):
    """Test optimize() full pipeline runs without error."""
    opt = MLStrategyOptimizer(min_signals=100)
    result = opt.optimize(mock_training_signals)

    assert "model_accuracy" in result
    assert "model_accuracy_std" in result
    assert "feature_importances" in result
    assert "generated_rules" in result
    assert "n_rules" in result
    assert "n_training_signals" in result
    assert "elapsed_s" in result

    assert result["model_accuracy"] > 0.0
    assert result["n_rules"] > 0
    assert len(result["generated_rules"]) > 0


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_optimize_with_insufficient_data():
    """Test optimize() with insufficient data returns train_error."""
    opt = MLStrategyOptimizer(min_signals=1000)
    signals = []
    result = opt.optimize(signals)

    assert "train_error" in result
    assert result["model_accuracy"] == 0.0
    assert result["n_rules"] == 0


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_train_with_all_wins():
    """Test training handles all wins gracefully."""
    opt = MLStrategyOptimizer(min_signals=10)

    signals = []
    for i in range(20):
        signals.append({
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.7,
            "event_type": "earnings_rumor",
            "price_at_signal": 100.0,
            "price_1d": 105.0,  # all wins
            "event_data": "{}",
            "market_data": "{}",
        })

    result = opt.train(signals)
    # Should fail due to class imbalance (need >=10 losses)
    assert result["trained"] is False
    assert result["reason"] == "class_imbalance"


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_train_with_all_losses():
    """Test training handles all losses gracefully."""
    opt = MLStrategyOptimizer(min_signals=10)

    signals = []
    for i in range(20):
        signals.append({
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.7,
            "event_type": "earnings_rumor",
            "price_at_signal": 100.0,
            "price_1d": 95.0,  # all losses
            "event_data": "{}",
            "market_data": "{}",
        })

    result = opt.train(signals)
    # Should fail due to class imbalance (need >=10 wins)
    assert result["trained"] is False
    assert result["reason"] == "class_imbalance"


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_train_with_empty_signals():
    """Test training with empty signal list."""
    opt = MLStrategyOptimizer(min_signals=100)
    result = opt.train([])

    assert result["trained"] is False
    assert result["reason"] == "insufficient_data"
    assert result["n_samples"] == 0


def test_predict_win_probability_before_training():
    """Test predict_win_probability() returns 0.5 before training."""
    opt = MLStrategyOptimizer()
    signal = {
        "ticker": "AAPL",
        "stance": "bullish",
        "confidence": 0.7,
        "event_type": "earnings_rumor",
        "event_data": "{}",
        "market_data": "{}",
    }

    prob = opt.predict_win_probability(signal)
    assert prob == 0.5


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_predict_win_probability_after_training(mock_training_signals):
    """Test predict_win_probability() returns probability after training."""
    opt = MLStrategyOptimizer(min_signals=100)
    opt.train(mock_training_signals)

    signal = {
        "ticker": "AAPL",
        "stance": "bullish",
        "confidence": 0.8,
        "event_type": "earnings_rumor",
        "quality_score": 0.7,
        "trend_score": 0.3,
        "event_data": json.dumps({
            "meta": {
                "nlp": {"conviction": 0.8, "polarity": 0.9}
            }
        }),
        "market_data": json.dumps({
            "AAPL": {"pct_1d": 5.0, "market_cap": 2.5e12}
        }),
    }

    prob = opt.predict_win_probability(signal)
    assert 0.0 <= prob <= 1.0
    assert prob != 0.5  # should not be default


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_predict_batch(mock_training_signals):
    """Test predict_batch() returns probabilities for multiple signals."""
    opt = MLStrategyOptimizer(min_signals=100)
    opt.train(mock_training_signals)

    signals = mock_training_signals[:10]
    results = opt.predict_batch(signals)

    assert len(results) == 10
    for sig, prob in results:
        assert isinstance(sig, dict)
        assert 0.0 <= prob <= 1.0


def test_get_training_stats_before_training():
    """Test get_training_stats() returns empty dict before training."""
    opt = MLStrategyOptimizer()
    stats = opt.get_training_stats()
    assert stats == {}


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_get_training_stats_after_training(mock_training_signals):
    """Test get_training_stats() returns stats after training."""
    opt = MLStrategyOptimizer(min_signals=100)
    opt.train(mock_training_signals)

    stats = opt.get_training_stats()
    assert stats["trained"] is True
    assert "accuracy" in stats
    assert "n_samples" in stats
    assert "trained_at" in stats


def test_get_model_summary_before_training():
    """Test get_model_summary() returns not_trained status."""
    opt = MLStrategyOptimizer()
    summary = opt.get_model_summary()
    assert summary["status"] == "not_trained"


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
def test_get_model_summary_after_training(mock_training_signals):
    """Test get_model_summary() returns summary after training."""
    opt = MLStrategyOptimizer(min_signals=100)
    opt.train(mock_training_signals)

    summary = opt.get_model_summary()
    assert summary["status"] == "trained"
    assert "accuracy" in summary
    assert "n_samples" in summary
    assert "n_wins" in summary
    assert "n_losses" in summary
    assert "top_features" in summary
    assert len(summary["top_features"]) <= 10


# ---------------------------------------------------------------------------
# Rule evaluation tests
# ---------------------------------------------------------------------------


def test_evaluate_rule_gt():
    """Test _evaluate_rule() for gt operator."""
    assert MLStrategyOptimizer._evaluate_rule(10.0, "gt", 5.0) is True
    assert MLStrategyOptimizer._evaluate_rule(3.0, "gt", 5.0) is False


def test_evaluate_rule_gte():
    """Test _evaluate_rule() for gte operator."""
    assert MLStrategyOptimizer._evaluate_rule(10.0, "gte", 5.0) is True
    assert MLStrategyOptimizer._evaluate_rule(5.0, "gte", 5.0) is True
    assert MLStrategyOptimizer._evaluate_rule(3.0, "gte", 5.0) is False


def test_evaluate_rule_lt():
    """Test _evaluate_rule() for lt operator."""
    assert MLStrategyOptimizer._evaluate_rule(3.0, "lt", 5.0) is True
    assert MLStrategyOptimizer._evaluate_rule(10.0, "lt", 5.0) is False


def test_evaluate_rule_lte():
    """Test _evaluate_rule() for lte operator."""
    assert MLStrategyOptimizer._evaluate_rule(3.0, "lte", 5.0) is True
    assert MLStrategyOptimizer._evaluate_rule(5.0, "lte", 5.0) is True
    assert MLStrategyOptimizer._evaluate_rule(10.0, "lte", 5.0) is False


def test_evaluate_rule_eq():
    """Test _evaluate_rule() for eq operator."""
    assert MLStrategyOptimizer._evaluate_rule("bullish", "eq", "bullish") is True
    assert MLStrategyOptimizer._evaluate_rule("BULLISH", "eq", "bullish") is True
    assert MLStrategyOptimizer._evaluate_rule("bearish", "eq", "bullish") is False


def test_evaluate_rule_neq():
    """Test _evaluate_rule() for neq operator."""
    assert MLStrategyOptimizer._evaluate_rule("bearish", "neq", "bullish") is True
    assert MLStrategyOptimizer._evaluate_rule("bullish", "neq", "bullish") is False


def test_evaluate_rule_in():
    """Test _evaluate_rule() for in operator."""
    assert MLStrategyOptimizer._evaluate_rule("stocks", "in", ["stocks", "options"]) is True
    assert MLStrategyOptimizer._evaluate_rule("wsb", "in", ["stocks", "options"]) is False


def test_evaluate_rule_none_value():
    """Test _evaluate_rule() with None value."""
    # None should only pass for neq
    assert MLStrategyOptimizer._evaluate_rule(None, "neq", "foo") is True
    assert MLStrategyOptimizer._evaluate_rule(None, "eq", "foo") is False
    assert MLStrategyOptimizer._evaluate_rule(None, "gte", 5.0) is False
