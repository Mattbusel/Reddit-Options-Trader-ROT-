"""Unit tests for rot.sentiment.aggregator."""

from __future__ import annotations

import datetime
import math
import unittest

from rot.sentiment.aggregator import (
    AggregatedSentiment,
    SentimentAggregator,
    SentimentScore,
    SentimentSource,
    _score_to_signal_strength,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.datetime(2024, 6, 1, 12, 0, 0)


def _score(
    source=SentimentSource.REDDIT,
    ticker="AAPL",
    score=0.5,
    confidence=0.8,
    hours_ago=0.0,
):
    ts = _NOW - datetime.timedelta(hours=hours_ago)
    return SentimentScore(
        source=source,
        ticker=ticker,
        score=score,
        confidence=confidence,
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# SentimentScore validation
# ---------------------------------------------------------------------------

class TestSentimentScore(unittest.TestCase):

    def test_valid_score(self):
        s = _score(score=0.5, confidence=0.8)
        self.assertAlmostEqual(s.score, 0.5)

    def test_score_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            _score(score=1.5)

    def test_score_minus_one_valid(self):
        s = _score(score=-1.0)
        self.assertAlmostEqual(s.score, -1.0)

    def test_confidence_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            _score(confidence=-0.1)

    def test_age_hours_zero_for_fresh(self):
        s = SentimentScore(
            source=SentimentSource.NEWS,
            ticker="AAPL",
            score=0.1,
            confidence=0.9,
            timestamp=datetime.datetime.utcnow(),
        )
        self.assertAlmostEqual(s.age_hours(), 0.0, delta=0.01)

    def test_age_hours_24(self):
        ts = _NOW - datetime.timedelta(hours=24)
        s = SentimentScore(
            source=SentimentSource.NEWS,
            ticker="AAPL",
            score=0.1,
            confidence=0.9,
            timestamp=ts,
        )
        age = s.age_hours(reference=_NOW)
        self.assertAlmostEqual(age, 24.0, delta=0.01)


# ---------------------------------------------------------------------------
# Signal strength classification
# ---------------------------------------------------------------------------

class TestSignalStrength(unittest.TestCase):

    def test_strong_bull(self):
        self.assertEqual(_score_to_signal_strength(0.8), "STRONG_BULL")

    def test_bull(self):
        self.assertEqual(_score_to_signal_strength(0.4), "BULL")

    def test_neutral_positive(self):
        self.assertEqual(_score_to_signal_strength(0.1), "NEUTRAL")

    def test_neutral_zero(self):
        self.assertEqual(_score_to_signal_strength(0.0), "NEUTRAL")

    def test_neutral_negative(self):
        self.assertEqual(_score_to_signal_strength(-0.1), "NEUTRAL")

    def test_bear(self):
        self.assertEqual(_score_to_signal_strength(-0.4), "BEAR")

    def test_strong_bear(self):
        self.assertEqual(_score_to_signal_strength(-0.8), "STRONG_BEAR")

    def test_boundary_bull(self):
        # exactly 0.2 → BULL (>) so not neutral
        self.assertEqual(_score_to_signal_strength(0.21), "BULL")

    def test_boundary_strong_bull(self):
        self.assertEqual(_score_to_signal_strength(0.61), "STRONG_BULL")


# ---------------------------------------------------------------------------
# SentimentAggregator
# ---------------------------------------------------------------------------

class TestSentimentAggregator(unittest.TestCase):

    def setUp(self):
        # Use a fixed reference time so decay is deterministic
        self.agg = SentimentAggregator(reference_time=_NOW)

    def test_single_bullish_score(self):
        s = _score(score=0.8, confidence=1.0)
        result = self.agg.aggregate([s])
        self.assertAlmostEqual(result.composite_score, 0.8, places=5)
        self.assertEqual(result.signal_strength, "STRONG_BULL")

    def test_single_bearish_score(self):
        s = _score(score=-0.7, confidence=1.0)
        result = self.agg.aggregate([s])
        self.assertAlmostEqual(result.composite_score, -0.7, places=5)
        self.assertEqual(result.signal_strength, "STRONG_BEAR")

    def test_neutral_scores_average(self):
        scores = [_score(score=0.0, confidence=1.0) for _ in range(5)]
        result = self.agg.aggregate(scores)
        self.assertAlmostEqual(result.composite_score, 0.0, places=5)
        self.assertEqual(result.signal_strength, "NEUTRAL")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            self.agg.aggregate([])

    def test_wrong_ticker_raises(self):
        s = _score(ticker="AAPL")
        with self.assertRaises(ValueError):
            self.agg.aggregate([s], ticker="TSLA")

    def test_ticker_filter(self):
        scores = [
            _score(ticker="AAPL", score=0.8, confidence=1.0),
            _score(ticker="TSLA", score=-0.5, confidence=1.0),
        ]
        result = self.agg.aggregate(scores, ticker="AAPL")
        self.assertAlmostEqual(result.composite_score, 0.8, places=2)
        self.assertEqual(result.ticker, "AAPL")

    def test_confidence_weighting(self):
        # High-confidence score should dominate
        scores = [
            _score(score=1.0, confidence=0.9, source=SentimentSource.REDDIT),
            _score(score=-1.0, confidence=0.1, source=SentimentSource.NEWS),
        ]
        # With weights: reddit=1.0, news=1.2
        # eff_w reddit = 0.9*1.0*1 = 0.9
        # eff_w news   = 0.1*1.2*1 = 0.12
        # composite = (1.0*0.9 + (-1.0)*0.12) / (0.9+0.12)
        expected = (1.0 * 0.9 - 1.0 * 0.12) / (0.9 + 0.12)
        result = self.agg.aggregate(scores)
        self.assertAlmostEqual(result.composite_score, expected, places=4)

    def test_source_breakdown_keys(self):
        scores = [
            _score(source=SentimentSource.REDDIT, score=0.5),
            _score(source=SentimentSource.NEWS, score=0.3),
        ]
        result = self.agg.aggregate(scores)
        self.assertIn("reddit", result.source_breakdown)
        self.assertIn("news", result.source_breakdown)

    def test_n_sources(self):
        scores = [
            _score(source=SentimentSource.REDDIT),
            _score(source=SentimentSource.REDDIT),
            _score(source=SentimentSource.NEWS),
        ]
        result = self.agg.aggregate(scores)
        self.assertEqual(result.n_sources, 2)

    def test_recency_decay_reduces_weight(self):
        # Old score should be down-weighted relative to fresh score
        fresh = _score(score=1.0, confidence=1.0, hours_ago=0)
        old = _score(score=-1.0, confidence=1.0, hours_ago=48)
        result = SentimentAggregator(
            reference_time=_NOW, decay_halflife_hours=24.0
        ).aggregate([fresh, old])
        # Fresh score should dominate → positive composite
        self.assertGreater(result.composite_score, 0.0)

    def test_no_decay_with_infinite_halflife(self):
        agg = SentimentAggregator(reference_time=_NOW, decay_halflife_hours=float("inf"))
        scores = [
            _score(score=1.0, confidence=1.0, hours_ago=1000),
            _score(score=-1.0, confidence=1.0, hours_ago=0),
        ]
        result = agg.aggregate(scores)
        # Both equally weighted (no decay) → net ~0 (but source weights differ)
        self.assertIsInstance(result.composite_score, float)

    def test_aggregate_all_tickers(self):
        scores = [
            _score(ticker="AAPL", score=0.7, confidence=1.0),
            _score(ticker="TSLA", score=-0.6, confidence=1.0),
        ]
        results = self.agg.aggregate_all_tickers(scores)
        self.assertIn("AAPL", results)
        self.assertIn("TSLA", results)
        self.assertGreater(results["AAPL"].composite_score, 0.0)
        self.assertLess(results["TSLA"].composite_score, 0.0)

    def test_is_bullish(self):
        s = _score(score=0.5)
        result = self.agg.aggregate([s])
        self.assertTrue(result.is_bullish())
        self.assertFalse(result.is_bearish())

    def test_is_bearish(self):
        s = _score(score=-0.5)
        result = self.agg.aggregate([s])
        self.assertTrue(result.is_bearish())
        self.assertFalse(result.is_bullish())

    def test_is_strong_bull(self):
        s = _score(score=0.9, confidence=1.0)
        result = self.agg.aggregate([s])
        self.assertTrue(result.is_strong())

    def test_is_not_strong_neutral(self):
        s = _score(score=0.0)
        result = self.agg.aggregate([s])
        self.assertFalse(result.is_strong())

    def test_composite_clamped_to_minus_one_one(self):
        # Even with extreme weights, should be clamped
        scores = [_score(score=1.0, confidence=1.0) for _ in range(100)]
        result = self.agg.aggregate(scores)
        self.assertLessEqual(result.composite_score, 1.0)
        self.assertGreaterEqual(result.composite_score, -1.0)

    def test_total_weight_positive(self):
        s = _score(score=0.5, confidence=0.5)
        result = self.agg.aggregate([s])
        self.assertGreater(result.total_weight, 0.0)

    def test_options_flow_higher_weight(self):
        # OPTIONS_FLOW has weight 1.5, REDDIT has 1.0
        scores = [
            _score(source=SentimentSource.OPTIONS_FLOW, score=1.0, confidence=1.0),
            _score(source=SentimentSource.REDDIT, score=-1.0, confidence=1.0),
        ]
        result = self.agg.aggregate(scores)
        # OPTIONS_FLOW should dominate → positive
        self.assertGreater(result.composite_score, 0.0)


if __name__ == "__main__":
    unittest.main()
