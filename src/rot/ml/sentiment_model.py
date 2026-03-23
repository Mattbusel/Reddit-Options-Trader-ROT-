"""ML-based sentiment scoring for Reddit options text."""

from __future__ import annotations

import math
import re
import unittest
from dataclasses import dataclass, field
from typing import Dict, List

# ---------------------------------------------------------------------------
# Word lists
# ---------------------------------------------------------------------------

POSITIVE_WORDS: List[str] = [
    "bullish", "moon", "rally", "squeeze", "breakout", "gains", "rip",
    "buy", "long", "calls", "upside", "surge", "rocket", "pump", "explosive",
    "winner", "profits", "green", "ATH", "opportunity", "strong", "beat",
    "exceed", "outperform", "recovery",
]

NEGATIVE_WORDS: List[str] = [
    "bearish", "crash", "dump", "puts", "short", "collapse", "tank",
    "loss", "sell", "red", "down", "drop", "decay", "bleed", "wreck",
    "miss", "disappoint", "underperform", "baghold", "rekt", "sink",
    "plunge", "correction", "bubble", "overvalued",
]

OPTIONS_KEYWORDS: List[str] = [
    "calls", "puts", "yolo", "moon", "strike", "expiry", "theta", "gamma",
    "delta", "IV", "options", "contracts", "premium", "spread", "straddle",
    "iron condor", "covered call", "naked", "hedge", "degenerate",
    "WSB", "tendies", "DD", "retard", "apes", "squeeze", "FDs", "LEAPS",
    "vol", "implied volatility", "OTM", "ITM", "ATM",
]

# ---------------------------------------------------------------------------
# Features dataclass
# ---------------------------------------------------------------------------


@dataclass
class SentimentFeatures:
    text: str
    word_count: int = 0
    avg_word_length: float = 0.0
    exclamation_count: int = 0
    question_count: int = 0
    uppercase_ratio: float = 0.0
    positive_word_count: int = 0
    negative_word_count: int = 0
    options_keyword_count: int = 0


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class SentimentScorer:
    """Rule-based and naive-Bayes sentiment scorer."""

    # Default naive-Bayes params: log P(word | class) for small vocabulary
    _DEFAULT_NB_PARAMS: Dict = {
        "log_prior": {"BULLISH": math.log(0.5), "BEARISH": math.log(0.5)},
        "log_likelihoods": {
            "BULLISH": {
                "bullish": math.log(0.15), "moon": math.log(0.12),
                "rally": math.log(0.10), "calls": math.log(0.10),
                "gains": math.log(0.08), "green": math.log(0.08),
                "buy": math.log(0.07), "squeeze": math.log(0.06),
                "breakout": math.log(0.06), "rocket": math.log(0.05),
                "puts": math.log(0.03), "dump": math.log(0.02),
                "crash": math.log(0.02), "loss": math.log(0.02),
                "bearish": math.log(0.01),
            },
            "BEARISH": {
                "bearish": math.log(0.15), "crash": math.log(0.12),
                "dump": math.log(0.10), "puts": math.log(0.10),
                "loss": math.log(0.08), "red": math.log(0.08),
                "tank": math.log(0.07), "sell": math.log(0.06),
                "drop": math.log(0.06), "plunge": math.log(0.05),
                "bullish": math.log(0.02), "calls": math.log(0.02),
                "moon": math.log(0.02), "rally": math.log(0.02),
                "gains": math.log(0.01),
            },
        },
        "unknown_log_likelihood": math.log(0.001),
    }

    def extract_features(self, text: str) -> SentimentFeatures:
        """Extract numeric features from text."""
        f = SentimentFeatures(text=text)
        words = re.findall(r"\b\w+\b", text)
        f.word_count = len(words)
        if words:
            f.avg_word_length = sum(len(w) for w in words) / len(words)
        f.exclamation_count = text.count("!")
        f.question_count = text.count("?")
        alpha_chars = [c for c in text if c.isalpha()]
        if alpha_chars:
            f.uppercase_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        text_lower = text.lower()
        f.positive_word_count = sum(1 for w in POSITIVE_WORDS if w in text_lower)
        f.negative_word_count = sum(1 for w in NEGATIVE_WORDS if w in text_lower)
        f.options_keyword_count = sum(1 for k in OPTIONS_KEYWORDS if k in text_lower)
        return f

    def score_rule_based(self, text: str) -> float:
        """Weighted keyword scoring returning a value in [-1, +1]."""
        f = self.extract_features(text)
        score = 0.0
        # Each positive word: +0.1, negative: -0.1
        score += f.positive_word_count * 0.1
        score -= f.negative_word_count * 0.1
        # CAPS ratio bias: if ratio > 0.3 amplify direction, else reduce
        if f.uppercase_ratio > 0.3:
            score += 0.2 if score >= 0 else -0.2
        # Each "!" adds 0.05 in current direction (or positive by default)
        exclamation_bias = f.exclamation_count * 0.05
        score += exclamation_bias if score >= 0 else -exclamation_bias
        # Options keywords bias positive (YOLO culture)
        score += f.options_keyword_count * 0.03
        return max(-1.0, min(1.0, score))

    def score_naive_bayes(self, text: str, model_params: dict | None = None) -> float:
        """Log-probability scoring using pre-computed word priors.

        Returns a value in [-1, +1] where +1 is maximally bullish.
        """
        params = model_params if model_params is not None else self._DEFAULT_NB_PARAMS
        words = re.findall(r"\b\w+\b", text.lower())
        log_priors = params["log_prior"]
        log_likelihoods = params["log_likelihoods"]
        unknown_ll = params.get("unknown_log_likelihood", math.log(0.001))

        scores: Dict[str, float] = {}
        for cls, log_prior in log_priors.items():
            score = log_prior
            for word in words:
                score += log_likelihoods.get(cls, {}).get(word, unknown_ll)
            scores[cls] = score

        # Convert log-scores to a [-1, +1] scalar via softmax difference
        classes = list(scores.keys())
        if len(classes) < 2:
            return 0.0

        log_bull = scores.get("BULLISH", -1e6)
        log_bear = scores.get("BEARISH", -1e6)
        # Sigmoid of log-ratio
        diff = log_bull - log_bear
        prob_bull = 1.0 / (1.0 + math.exp(-diff))
        # Map [0,1] -> [-1, +1]
        return (prob_bull - 0.5) * 2.0

    def ensemble_score(self, text: str) -> float:
        """Average of rule-based and naive-Bayes scores."""
        rb = self.score_rule_based(text)
        nb = self.score_naive_bayes(text)
        return (rb + nb) / 2.0

    def classify(self, score: float) -> str:
        """Classify a score into BULLISH / BEARISH / NEUTRAL."""
        if score > 0.2:
            return "BULLISH"
        elif score < -0.2:
            return "BEARISH"
        else:
            return "NEUTRAL"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSentimentScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = SentimentScorer()

    def test_extract_features_word_count(self):
        f = self.scorer.extract_features("the quick brown fox")
        self.assertEqual(f.word_count, 4)

    def test_extract_features_exclamation(self):
        f = self.scorer.extract_features("To the moon!!!")
        self.assertEqual(f.exclamation_count, 3)

    def test_extract_features_question(self):
        f = self.scorer.extract_features("Will it moon?")
        self.assertEqual(f.question_count, 1)

    def test_extract_features_positive_words(self):
        f = self.scorer.extract_features("bullish breakout gains rally moon")
        self.assertGreater(f.positive_word_count, 0)

    def test_extract_features_negative_words(self):
        f = self.scorer.extract_features("bearish crash dump loss")
        self.assertGreater(f.negative_word_count, 0)

    def test_extract_features_options_keywords(self):
        f = self.scorer.extract_features("bought calls on AAPL yolo theta decay")
        self.assertGreater(f.options_keyword_count, 0)

    def test_score_rule_based_bullish_text(self):
        score = self.scorer.score_rule_based(
            "Bullish breakout! Rally to moon! gains gains gains calls calls"
        )
        self.assertGreater(score, 0.0)

    def test_score_rule_based_bearish_text(self):
        score = self.scorer.score_rule_based(
            "bearish crash dump tank loss loss puts sell sell"
        )
        self.assertLess(score, 0.0)

    def test_score_rule_based_range(self):
        for text in ["neutral text", "MOON CALLS!", "puts crash dump bearish"]:
            s = self.scorer.score_rule_based(text)
            self.assertGreaterEqual(s, -1.0)
            self.assertLessEqual(s, 1.0)

    def test_score_naive_bayes_bullish(self):
        score = self.scorer.score_naive_bayes("bullish rally gains moon calls")
        self.assertGreater(score, 0.0)

    def test_score_naive_bayes_bearish(self):
        score = self.scorer.score_naive_bayes("bearish crash dump puts loss")
        self.assertLess(score, 0.0)

    def test_score_naive_bayes_range(self):
        s = self.scorer.score_naive_bayes("some random text")
        self.assertGreaterEqual(s, -1.0)
        self.assertLessEqual(s, 1.0)

    def test_ensemble_score_range(self):
        for text in ["calls moon yolo", "dump crash sell", "meeting today"]:
            s = self.scorer.ensemble_score(text)
            self.assertGreaterEqual(s, -1.0)
            self.assertLessEqual(s, 1.0)

    def test_classify_bullish(self):
        self.assertEqual(self.scorer.classify(0.5), "BULLISH")

    def test_classify_bearish(self):
        self.assertEqual(self.scorer.classify(-0.5), "BEARISH")

    def test_classify_neutral_positive(self):
        self.assertEqual(self.scorer.classify(0.1), "NEUTRAL")

    def test_classify_neutral_negative(self):
        self.assertEqual(self.scorer.classify(-0.1), "NEUTRAL")

    def test_classify_boundary_bullish(self):
        self.assertEqual(self.scorer.classify(0.21), "BULLISH")

    def test_classify_boundary_bearish(self):
        self.assertEqual(self.scorer.classify(-0.21), "BEARISH")

    def test_uppercase_ratio(self):
        f = self.scorer.extract_features("MOON YOLO")
        self.assertGreater(f.uppercase_ratio, 0.9)

    def test_avg_word_length(self):
        f = self.scorer.extract_features("hi")
        self.assertAlmostEqual(f.avg_word_length, 2.0)

    def test_empty_text(self):
        f = self.scorer.extract_features("")
        self.assertEqual(f.word_count, 0)
        score = self.scorer.score_rule_based("")
        self.assertEqual(self.scorer.classify(score), "NEUTRAL")


if __name__ == "__main__":
    unittest.main()
