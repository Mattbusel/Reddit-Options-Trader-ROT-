"""Tests for the multi-timeframe signal aggregator (src/rot/strategy/timeframe_aggregator.py)."""

from __future__ import annotations

import time

import pytest

from rot.strategy.timeframe_aggregator import (
    TIMEFRAME_WEIGHTS,
    CompositeResult,
    TimeframeAggregator,
    TimeframeAlignment,
    TimeframeSignal,
)


# ── Helpers ────────────────────────────────────────────────


def _sig(
    ticker: str = "AAPL",
    timeframe: str = "1h",
    signal: str = "bullish",
    confidence: float = 0.75,
    ts: float | None = None,
) -> TimeframeSignal:
    return TimeframeSignal(
        ticker=ticker,
        timeframe=timeframe,
        signal=signal,
        confidence=confidence,
        timestamp=ts if ts is not None else time.time(),
    )


NOW = time.time()


# ── TimeframeSignal dataclass ──────────────────────────────


class TestTimeframeSignalDataclass:
    def test_valid_construction(self) -> None:
        sig = _sig()
        assert sig.ticker == "AAPL"
        assert sig.timeframe == "1h"
        assert sig.signal == "bullish"
        assert 0.0 <= sig.confidence <= 1.0

    def test_invalid_timeframe_raises(self) -> None:
        with pytest.raises(ValueError, match="timeframe"):
            TimeframeSignal(ticker="X", timeframe="3h", signal="bullish", confidence=0.5, timestamp=NOW)

    def test_invalid_signal_raises(self) -> None:
        with pytest.raises(ValueError, match="signal"):
            TimeframeSignal(ticker="X", timeframe="1h", signal="sideways", confidence=0.5, timestamp=NOW)

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            TimeframeSignal(ticker="X", timeframe="1h", signal="bullish", confidence=1.5, timestamp=NOW)

    def test_negative_confidence_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            TimeframeSignal(ticker="X", timeframe="1h", signal="bullish", confidence=-0.1, timestamp=NOW)

    def test_to_dict_keys(self) -> None:
        d = _sig().to_dict()
        assert set(d.keys()) == {"ticker", "timeframe", "signal", "confidence", "timestamp", "source"}

    def test_neutral_signal_valid(self) -> None:
        sig = TimeframeSignal(ticker="SPY", timeframe="1d", signal="neutral", confidence=0.5, timestamp=NOW)
        assert sig.signal == "neutral"


# ── TimeframeAggregator ────────────────────────────────────


class TestAggregatorBasics:
    def test_no_signals_returns_none(self) -> None:
        agg = TimeframeAggregator()
        assert agg.composite_score("AAPL") is None

    def test_add_single_signal(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("AAPL", "1h", "bullish", 0.8, NOW))
        result = agg.composite_score("AAPL", now=NOW)
        assert result is not None

    def test_returns_composite_result(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("TSLA", "1d", "bullish", 0.9, NOW))
        result = agg.composite_score("TSLA", now=NOW)
        assert isinstance(result, CompositeResult)

    def test_score_in_range(self) -> None:
        agg = TimeframeAggregator()
        for tf in TIMEFRAME_WEIGHTS:
            agg.add(_sig("SPY", tf, "bullish", 0.7, NOW))
        result = agg.composite_score("SPY", now=NOW)
        assert result is not None
        assert 0.0 <= result.score <= 1.0

    def test_tickers_returns_added_tickers(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("AAPL"))
        agg.add(_sig("TSLA"))
        assert set(agg.tickers()) == {"AAPL", "TSLA"}

    def test_signals_for_ticker(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("AAPL", "1h"))
        agg.add(_sig("AAPL", "4h"))
        sigs = agg.signals_for("AAPL")
        assert len(sigs) == 2

    def test_newer_signal_replaces_older(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("X", "1h", "bullish", 0.6, NOW - 100))
        agg.add(_sig("X", "1h", "bearish", 0.9, NOW))
        sigs = agg.signals_for("X")
        assert len(sigs) == 1
        assert sigs[0].signal == "bearish"

    def test_older_signal_does_not_replace_newer(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("X", "1h", "bullish", 0.9, NOW))
        agg.add(_sig("X", "1h", "bearish", 0.6, NOW - 100))
        sigs = agg.signals_for("X")
        assert sigs[0].signal == "bullish"

    def test_clear_ticker(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("AAPL"))
        agg.add(_sig("TSLA"))
        agg.clear("AAPL")
        assert "AAPL" not in agg.tickers()
        assert "TSLA" in agg.tickers()

    def test_clear_all(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("AAPL"))
        agg.add(_sig("TSLA"))
        agg.clear()
        assert agg.tickers() == []


class TestAlignmentDetection:
    def test_full_alignment_all_bullish(self) -> None:
        agg = TimeframeAggregator()
        for tf in ["1h", "4h", "1d"]:
            agg.add(_sig("AAPL", tf, "bullish", 1.0, NOW))
        result = agg.composite_score("AAPL", now=NOW)
        assert result is not None
        assert result.alignment == TimeframeAlignment.FULL_ALIGN

    def test_full_alignment_all_bearish(self) -> None:
        agg = TimeframeAggregator()
        for tf in ["1h", "4h", "1d"]:
            agg.add(_sig("AAPL", tf, "bearish", 1.0, NOW))
        result = agg.composite_score("AAPL", now=NOW)
        assert result is not None
        assert result.alignment == TimeframeAlignment.FULL_ALIGN

    def test_divergent_mixed_signals(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("SPY", "1d", "bullish", 1.0, NOW))
        agg.add(_sig("SPY", "4h", "bearish", 1.0, NOW))
        result = agg.composite_score("SPY", now=NOW)
        assert result is not None
        assert result.alignment == TimeframeAlignment.DIVERGENT

    def test_dominant_signal_matches_majority(self) -> None:
        agg = TimeframeAggregator()
        # 3 bullish, 1 bearish — bullish should dominate
        for tf in ["1h", "4h", "1d"]:
            agg.add(_sig("MSFT", tf, "bullish", 0.8, NOW))
        agg.add(_sig("MSFT", "15m", "bearish", 0.8, NOW))
        result = agg.composite_score("MSFT", now=NOW)
        assert result is not None
        assert result.dominant_signal == "bullish"


class TestAgeFiltering:
    def test_stale_signals_excluded(self) -> None:
        agg = TimeframeAggregator(max_age_s=3600)
        old_ts = NOW - 7200  # 2 hours ago
        agg.add(_sig("AAPL", "1h", ts=old_ts))
        result = agg.composite_score("AAPL", now=NOW)
        assert result is None

    def test_fresh_signals_included(self) -> None:
        agg = TimeframeAggregator(max_age_s=3600)
        agg.add(_sig("AAPL", "1h", ts=NOW - 1800))  # 30 min ago
        result = agg.composite_score("AAPL", now=NOW)
        assert result is not None

    def test_mixed_age_only_fresh_counted(self) -> None:
        agg = TimeframeAggregator(max_age_s=3600)
        agg.add(_sig("AAPL", "1h", "bullish", 0.9, NOW - 1800))  # fresh
        # Force a stale signal at a second timeframe by adding then aging
        agg.add(_sig("AAPL", "4h", "bearish", 0.9, NOW - 7200))  # stale
        result = agg.composite_score("AAPL", now=NOW)
        assert result is not None
        assert result.dominant_signal == "bullish"  # only fresh signal counts


class TestCompositeResult:
    def test_contributing_timeframes_present(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("AAPL", "1h", ts=NOW))
        agg.add(_sig("AAPL", "4h", ts=NOW))
        result = agg.composite_score("AAPL", now=NOW)
        assert result is not None
        assert "1h" in result.contributing_timeframes
        assert "4h" in result.contributing_timeframes

    def test_signal_count_matches(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("AAPL", "1h", ts=NOW))
        agg.add(_sig("AAPL", "4h", ts=NOW))
        agg.add(_sig("AAPL", "1d", ts=NOW))
        result = agg.composite_score("AAPL", now=NOW)
        assert result is not None
        assert result.signal_count == 3

    def test_to_dict_keys(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("AAPL", "1d", ts=NOW))
        result = agg.composite_score("AAPL", now=NOW)
        assert result is not None
        d = result.to_dict()
        expected = {"ticker", "score", "raw_score", "dominant_signal", "alignment", "contributing_timeframes", "signal_count", "computed_at"}
        assert set(d.keys()) == expected

    def test_alignment_value_is_string(self) -> None:
        agg = TimeframeAggregator()
        agg.add(_sig("AAPL", "1d", ts=NOW))
        result = agg.composite_score("AAPL", now=NOW)
        assert result is not None
        assert isinstance(result.to_dict()["alignment"], str)


class TestWeightSchema:
    def test_weights_sum_to_one(self) -> None:
        total = sum(TIMEFRAME_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-9)

    def test_correct_weight_values(self) -> None:
        assert TIMEFRAME_WEIGHTS["1m"] == pytest.approx(0.05)
        assert TIMEFRAME_WEIGHTS["5m"] == pytest.approx(0.10)
        assert TIMEFRAME_WEIGHTS["15m"] == pytest.approx(0.15)
        assert TIMEFRAME_WEIGHTS["1h"] == pytest.approx(0.25)
        assert TIMEFRAME_WEIGHTS["4h"] == pytest.approx(0.20)
        assert TIMEFRAME_WEIGHTS["1d"] == pytest.approx(0.25)
