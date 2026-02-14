"""Tests for rot.social.manipulation.ManipulationDetector.

Covers:
- ManipulationConfig defaults and custom values / validation
- detect_coordinated_posting: cluster detection, author threshold, window, severity
- detect_bot_network: timing-based, content-based (Jaccard), group size threshold
- detect_pump_and_dump: volume surge, bullish concentration, severity, price scoring
- detect_all: combination, min_severity filtering, severity-DESC sorting
- update_baselines: per-ticker rolling counts, stale eviction
- _jaccard_similarity: word-level Jaccard edge cases
- Edge cases: empty signals, single signal, no detection scenarios
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from rot.social.manipulation import (
    ManipulationConfig,
    ManipulationDetector,
    _jaccard_similarity,
    _TickerBaseline,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_signal(
    ticker: str = "TSLA",
    stance: str = "bullish",
    author: str = "user1",
    subreddit: str = "wallstreetbets",
    created_at: float | None = None,
    confidence: float = 0.7,
    post_title: str | None = None,
    price_at_signal: float | None = None,
    price_current: float | None = None,
) -> Dict[str, Any]:
    """Build a minimal signal dict for testing."""
    sig: Dict[str, Any] = {
        "ticker": ticker,
        "stance": stance,
        "author": author,
        "subreddit": subreddit,
        "created_at": created_at if created_at is not None else time.time(),
        "confidence": confidence,
    }
    if post_title is not None:
        sig["post_title"] = post_title
    if price_at_signal is not None:
        sig["price_at_signal"] = price_at_signal
    if price_current is not None:
        sig["price_current"] = price_current
    return sig


# ── ManipulationConfig Tests ─────────────────────────────────────────────────


class TestManipulationConfig:
    """Tests for ManipulationConfig defaults and validation."""

    def test_defaults(self):
        cfg = ManipulationConfig()
        assert cfg.coordination_window_s == 1800
        assert cfg.min_authors_for_coordination == 3
        assert cfg.bot_time_tolerance_s == 300
        assert cfg.bot_min_group_size == 3
        assert cfg.pump_volume_multiplier == 3.0
        assert cfg.pump_price_threshold_pct == 5.0
        assert cfg.min_severity_to_report == 30.0

    def test_custom_values(self):
        cfg = ManipulationConfig(
            coordination_window_s=600,
            min_authors_for_coordination=5,
            bot_time_tolerance_s=120,
            bot_min_group_size=4,
            pump_volume_multiplier=2.5,
            pump_price_threshold_pct=10.0,
            min_severity_to_report=50.0,
        )
        assert cfg.coordination_window_s == 600
        assert cfg.min_authors_for_coordination == 5
        assert cfg.bot_time_tolerance_s == 120
        assert cfg.bot_min_group_size == 4
        assert cfg.pump_volume_multiplier == 2.5
        assert cfg.pump_price_threshold_pct == 10.0
        assert cfg.min_severity_to_report == 50.0

    def test_frozen(self):
        cfg = ManipulationConfig()
        with pytest.raises(AttributeError):
            cfg.coordination_window_s = 999  # type: ignore[misc]

    def test_invalid_coordination_window(self):
        with pytest.raises(ValueError, match="coordination_window_s must be > 0"):
            ManipulationConfig(coordination_window_s=0)

    def test_invalid_bot_time_tolerance(self):
        with pytest.raises(ValueError, match="bot_time_tolerance_s must be > 0"):
            ManipulationConfig(bot_time_tolerance_s=-1)

    def test_invalid_bot_min_group_size(self):
        with pytest.raises(ValueError, match="bot_min_group_size must be >= 2"):
            ManipulationConfig(bot_min_group_size=1)

    def test_invalid_pump_volume_multiplier(self):
        with pytest.raises(ValueError, match="pump_volume_multiplier must be > 1.0"):
            ManipulationConfig(pump_volume_multiplier=1.0)

    def test_invalid_pump_price_threshold(self):
        with pytest.raises(ValueError, match="pump_price_threshold_pct must be > 0"):
            ManipulationConfig(pump_price_threshold_pct=0.0)

    def test_invalid_min_authors_for_coordination(self):
        with pytest.raises(ValueError, match="min_authors_for_coordination must be >= 2"):
            ManipulationConfig(min_authors_for_coordination=1)

    def test_invalid_min_severity_to_report_too_high(self):
        with pytest.raises(ValueError, match="min_severity_to_report must be in"):
            ManipulationConfig(min_severity_to_report=101.0)

    def test_invalid_min_severity_to_report_negative(self):
        with pytest.raises(ValueError, match="min_severity_to_report must be in"):
            ManipulationConfig(min_severity_to_report=-1.0)


# ── Coordinated Posting Tests ────────────────────────────────────────────────


class TestCoordinatedPosting:
    """Tests for detect_coordinated_posting."""

    def test_detects_3_authors_same_ticker_same_stance_within_window(self):
        """3+ distinct authors posting bullish on TSLA within 30 min => alert."""
        now = time.time()
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author="alice", created_at=now),
            _make_signal(ticker="TSLA", stance="bullish", author="bob", created_at=now + 60),
            _make_signal(ticker="TSLA", stance="bullish", author="carol", created_at=now + 120),
        ]
        det = ManipulationDetector()
        alerts = det.detect_coordinated_posting(signals)
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.alert_type == "coordinated_posting"
        assert "TSLA" in alert.tickers
        assert set(alert.authors) == {"alice", "bob", "carol"}
        assert alert.evidence["stance"] == "bullish"
        assert alert.severity > 0

    def test_not_detected_with_fewer_than_3_authors(self):
        """Only 2 authors => no coordination alert with default min_authors=3."""
        now = time.time()
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author="alice", created_at=now),
            _make_signal(ticker="TSLA", stance="bullish", author="bob", created_at=now + 60),
        ]
        det = ManipulationDetector()
        alerts = det.detect_coordinated_posting(signals)
        assert len(alerts) == 0

    def test_not_detected_outside_window(self):
        """Authors post more than coordination_window_s apart => no alert."""
        now = time.time()
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author="alice", created_at=now),
            _make_signal(ticker="TSLA", stance="bullish", author="bob", created_at=now + 1900),
            _make_signal(ticker="TSLA", stance="bullish", author="carol", created_at=now + 3800),
        ]
        det = ManipulationDetector()
        alerts = det.detect_coordinated_posting(signals)
        assert len(alerts) == 0

    def test_severity_increases_with_more_authors(self):
        """More authors in cluster => higher severity."""
        now = time.time()
        signals_3 = [
            _make_signal(ticker="TSLA", stance="bullish", author=f"user{i}", created_at=now + i * 10)
            for i in range(3)
        ]
        signals_5 = [
            _make_signal(ticker="TSLA", stance="bullish", author=f"user{i}", created_at=now + i * 10)
            for i in range(5)
        ]
        det = ManipulationDetector()
        alerts_3 = det.detect_coordinated_posting(signals_3)
        alerts_5 = det.detect_coordinated_posting(signals_5)
        assert len(alerts_3) == 1
        assert len(alerts_5) == 1
        assert alerts_5[0].severity > alerts_3[0].severity

    def test_mixed_stances_below_80pct_not_flagged(self):
        """If directional stances are split roughly 50/50, no coordination alert."""
        now = time.time()
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author="alice", created_at=now),
            _make_signal(ticker="TSLA", stance="bearish", author="bob", created_at=now + 30),
            _make_signal(ticker="TSLA", stance="bullish", author="carol", created_at=now + 60),
            _make_signal(ticker="TSLA", stance="bearish", author="dave", created_at=now + 90),
        ]
        det = ManipulationDetector()
        alerts = det.detect_coordinated_posting(signals)
        assert len(alerts) == 0

    def test_non_directional_stances_ignored(self):
        """Signals with 'mixed' or 'unknown' stance don't count as directional."""
        now = time.time()
        signals = [
            _make_signal(ticker="TSLA", stance="mixed", author="alice", created_at=now),
            _make_signal(ticker="TSLA", stance="unknown", author="bob", created_at=now + 30),
            _make_signal(ticker="TSLA", stance="mixed", author="carol", created_at=now + 60),
        ]
        det = ManipulationDetector()
        alerts = det.detect_coordinated_posting(signals)
        # No directional signals => no coordination alert
        assert len(alerts) == 0

    def test_bearish_coordination_detected(self):
        """Bearish coordination is also detected."""
        now = time.time()
        signals = [
            _make_signal(ticker="AAPL", stance="bearish", author="a1", created_at=now),
            _make_signal(ticker="AAPL", stance="bearish", author="a2", created_at=now + 10),
            _make_signal(ticker="AAPL", stance="bearish", author="a3", created_at=now + 20),
        ]
        det = ManipulationDetector()
        alerts = det.detect_coordinated_posting(signals)
        assert len(alerts) == 1
        assert alerts[0].evidence["stance"] == "bearish"

    def test_separate_tickers_produce_separate_alerts(self):
        """Coordination in two different tickers produces two separate alerts."""
        now = time.time()
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author="a1", created_at=now),
            _make_signal(ticker="TSLA", stance="bullish", author="a2", created_at=now + 10),
            _make_signal(ticker="TSLA", stance="bullish", author="a3", created_at=now + 20),
            _make_signal(ticker="AAPL", stance="bearish", author="b1", created_at=now),
            _make_signal(ticker="AAPL", stance="bearish", author="b2", created_at=now + 10),
            _make_signal(ticker="AAPL", stance="bearish", author="b3", created_at=now + 20),
        ]
        det = ManipulationDetector()
        alerts = det.detect_coordinated_posting(signals)
        assert len(alerts) == 2
        tickers_alerted = {a.tickers[0] for a in alerts}
        assert tickers_alerted == {"TSLA", "AAPL"}

    def test_custom_min_authors(self):
        """With min_authors_for_coordination=2, two authors suffice."""
        now = time.time()
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author="alice", created_at=now),
            _make_signal(ticker="TSLA", stance="bullish", author="bob", created_at=now + 10),
        ]
        cfg = ManipulationConfig(min_authors_for_coordination=2)
        det = ManipulationDetector(config=cfg)
        alerts = det.detect_coordinated_posting(signals)
        assert len(alerts) == 1


# ── Bot Network Tests ────────────────────────────────────────────────────────


class TestBotNetwork:
    """Tests for detect_bot_network (timing + content)."""

    def test_timing_based_detection(self):
        """3 authors posting at nearly identical times across multiple posts."""
        now = time.time()
        signals = []
        # 3 authors each post 4 times at almost the same timestamps
        for post_round in range(4):
            base_ts = now + post_round * 600  # every 10 min
            for author in ["bot1", "bot2", "bot3"]:
                signals.append(
                    _make_signal(
                        ticker="TSLA",
                        author=author,
                        created_at=base_ts + 5,  # all within 5s of each other
                    )
                )
        cfg = ManipulationConfig(bot_time_tolerance_s=300, bot_min_group_size=3)
        det = ManipulationDetector(config=cfg)
        alerts = det.detect_bot_network(signals)
        # Should find at least one timing-based bot network alert
        timing_alerts = [a for a in alerts if a.evidence.get("sub_pattern") == "timing"]
        assert len(timing_alerts) >= 1
        alert = timing_alerts[0]
        assert alert.alert_type == "bot_network"
        assert set(alert.authors) == {"bot1", "bot2", "bot3"}

    def test_similar_titles_detection(self):
        """3 authors posting near-identical titles => content-based bot alert."""
        now = time.time()
        title = "TSLA is going to the moon buy calls now"
        signals = [
            _make_signal(ticker="TSLA", author="spam1", created_at=now, post_title=title),
            _make_signal(ticker="TSLA", author="spam2", created_at=now + 100, post_title=title),
            _make_signal(ticker="TSLA", author="spam3", created_at=now + 200, post_title=title),
        ]
        cfg = ManipulationConfig(bot_min_group_size=3)
        det = ManipulationDetector(config=cfg)
        alerts = det.detect_bot_network(signals)
        content_alerts = [a for a in alerts if a.evidence.get("sub_pattern") == "similar_titles"]
        assert len(content_alerts) >= 1
        assert "TSLA" in content_alerts[0].tickers

    def test_not_detected_with_too_few_authors(self):
        """Only 2 authors with similar titles but bot_min_group_size=3 => no alert."""
        now = time.time()
        title = "Buy TSLA calls right now do it"
        signals = [
            _make_signal(ticker="TSLA", author="spam1", created_at=now, post_title=title),
            _make_signal(ticker="TSLA", author="spam2", created_at=now + 100, post_title=title),
        ]
        cfg = ManipulationConfig(bot_min_group_size=3)
        det = ManipulationDetector(config=cfg)
        alerts = det.detect_bot_network(signals)
        content_alerts = [a for a in alerts if a.evidence.get("sub_pattern") == "similar_titles"]
        assert len(content_alerts) == 0

    def test_dissimilar_titles_not_flagged(self):
        """Completely different titles => no content-based alert."""
        now = time.time()
        signals = [
            _make_signal(ticker="TSLA", author="u1", created_at=now, post_title="Tesla earnings beat expectations"),
            _make_signal(ticker="TSLA", author="u2", created_at=now + 10, post_title="Looking at AMD puts for next week"),
            _make_signal(ticker="TSLA", author="u3", created_at=now + 20, post_title="Anyone playing SPY straddles this month"),
        ]
        cfg = ManipulationConfig(bot_min_group_size=3)
        det = ManipulationDetector(config=cfg)
        alerts = det.detect_bot_network(signals)
        content_alerts = [a for a in alerts if a.evidence.get("sub_pattern") == "similar_titles"]
        assert len(content_alerts) == 0

    def test_timing_needs_3_co_occurrences(self):
        """Pair must have at least 3 co-occurring posts to be flagged."""
        now = time.time()
        # Only 2 posts per author => deltas list has only 2 entries => not enough
        signals = [
            _make_signal(ticker="TSLA", author="bot1", created_at=now),
            _make_signal(ticker="TSLA", author="bot2", created_at=now + 1),
            _make_signal(ticker="TSLA", author="bot3", created_at=now + 2),
            _make_signal(ticker="TSLA", author="bot1", created_at=now + 600),
            _make_signal(ticker="TSLA", author="bot2", created_at=now + 601),
            _make_signal(ticker="TSLA", author="bot3", created_at=now + 602),
        ]
        cfg = ManipulationConfig(bot_time_tolerance_s=300, bot_min_group_size=3)
        det = ManipulationDetector(config=cfg)
        alerts = det.detect_bot_network(signals)
        timing_alerts = [a for a in alerts if a.evidence.get("sub_pattern") == "timing"]
        # 2 deltas per pair (only 2 posts each) => < 3 required => no timing alert
        assert len(timing_alerts) == 0


# ── Pump-and-Dump Tests ──────────────────────────────────────────────────────


class TestPumpAndDump:
    """Tests for detect_pump_and_dump."""

    def test_volume_surge_above_baseline(self):
        """Recent signal count >> baseline mean => pump alert."""
        now = time.time()
        cfg = ManipulationConfig(pump_volume_multiplier=3.0, coordination_window_s=1800)
        det = ManipulationDetector(config=cfg)

        # Set a low baseline (mean ~2 signals per day)
        det._ticker_baselines["TSLA"] = _TickerBaseline(signal_counts=[2, 2, 2, 2, 2])

        # Create 7 recent bullish signals (within window) => ratio=7/2=3.5 > 3.0
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author=f"user{i}", created_at=now - 100 + i * 10)
            for i in range(7)
        ]
        alerts = det.detect_pump_and_dump(signals)
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.alert_type == "pump_and_dump"
        assert "TSLA" in alert.tickers
        assert alert.evidence["volume_ratio"] >= 3.0
        assert alert.evidence["bullish_pct"] == 1.0

    def test_no_alert_below_volume_threshold(self):
        """Volume ratio below pump_volume_multiplier => no alert."""
        now = time.time()
        cfg = ManipulationConfig(pump_volume_multiplier=3.0, coordination_window_s=1800)
        det = ManipulationDetector(config=cfg)
        det._ticker_baselines["TSLA"] = _TickerBaseline(signal_counts=[5, 5, 5])

        # Only 4 recent signals => ratio = 4/5 = 0.8 < 3.0
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author=f"u{i}", created_at=now - 50 + i * 10)
            for i in range(4)
        ]
        alerts = det.detect_pump_and_dump(signals)
        assert len(alerts) == 0

    def test_bullish_concentration_required(self):
        """If bullish percentage < 60%, no pump alert even with volume surge."""
        now = time.time()
        cfg = ManipulationConfig(pump_volume_multiplier=2.0, coordination_window_s=1800)
        det = ManipulationDetector(config=cfg)
        det._ticker_baselines["TSLA"] = _TickerBaseline(signal_counts=[1, 1, 1])

        # 5 signals but mostly bearish
        signals = [
            _make_signal(ticker="TSLA", stance="bearish", author="u1", created_at=now - 50),
            _make_signal(ticker="TSLA", stance="bearish", author="u2", created_at=now - 40),
            _make_signal(ticker="TSLA", stance="bearish", author="u3", created_at=now - 30),
            _make_signal(ticker="TSLA", stance="bullish", author="u4", created_at=now - 20),
            _make_signal(ticker="TSLA", stance="bearish", author="u5", created_at=now - 10),
        ]
        alerts = det.detect_pump_and_dump(signals)
        assert len(alerts) == 0

    def test_severity_scoring_with_price_data(self):
        """Price movement data contributes to severity score."""
        now = time.time()
        cfg = ManipulationConfig(pump_volume_multiplier=2.0, coordination_window_s=1800)
        det = ManipulationDetector(config=cfg)
        det._ticker_baselines["TSLA"] = _TickerBaseline(signal_counts=[1, 1])

        # Signals with price appreciation
        signals = [
            _make_signal(
                ticker="TSLA", stance="bullish", author=f"u{i}",
                created_at=now - 50 + i * 10,
                price_at_signal=100.0, price_current=110.0,
            )
            for i in range(4)
        ]
        alerts_with_price = det.detect_pump_and_dump(signals)

        # Same signals without price data
        det2 = ManipulationDetector(config=cfg)
        det2._ticker_baselines["TSLA"] = _TickerBaseline(signal_counts=[1, 1])
        signals_no_price = [
            _make_signal(
                ticker="TSLA", stance="bullish", author=f"u{i}",
                created_at=now - 50 + i * 10,
            )
            for i in range(4)
        ]
        alerts_no_price = det2.detect_pump_and_dump(signals_no_price)

        assert len(alerts_with_price) == 1
        assert len(alerts_no_price) == 1
        # Price movement should increase severity
        assert alerts_with_price[0].severity > alerts_no_price[0].severity

    def test_no_baseline_uses_default(self):
        """Without a baseline, effective baseline is 1.0 so any 3+ recent signals
        with ratio >= pump_volume_multiplier can trigger."""
        now = time.time()
        cfg = ManipulationConfig(pump_volume_multiplier=3.0, coordination_window_s=1800)
        det = ManipulationDetector(config=cfg)
        # No baseline set; effective_baseline = max(0.0, 1.0) = 1.0

        signals = [
            _make_signal(ticker="NVDA", stance="bullish", author=f"u{i}", created_at=now - 50 + i * 10)
            for i in range(4)
        ]
        alerts = det.detect_pump_and_dump(signals)
        assert len(alerts) == 1
        assert alerts[0].evidence["baseline_avg"] == 0.0
        assert alerts[0].evidence["volume_ratio"] >= 3.0

    def test_single_recent_signal_not_flagged(self):
        """Less than 2 recent signals => skip."""
        now = time.time()
        det = ManipulationDetector()
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author="u1", created_at=now - 50),
        ]
        alerts = det.detect_pump_and_dump(signals)
        assert len(alerts) == 0


# ── detect_all Tests ─────────────────────────────────────────────────────────


class TestDetectAll:
    """Tests for detect_all combining all detectors."""

    def test_combines_all_detectors(self):
        """detect_all runs coordinated_posting, bot_network, pump_and_dump."""
        now = time.time()
        cfg = ManipulationConfig(
            min_severity_to_report=0.0,
            pump_volume_multiplier=2.0,
            coordination_window_s=1800,
            min_authors_for_coordination=3,
        )
        det = ManipulationDetector(config=cfg)
        det._ticker_baselines["TSLA"] = _TickerBaseline(signal_counts=[1])

        # 4 bullish signals from 4 authors => coord + pump
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author=f"a{i}", created_at=now - 50 + i * 10)
            for i in range(4)
        ]
        alerts = det.detect_all(signals)
        alert_types = {a.alert_type for a in alerts}
        # Should have at least coordinated_posting and pump_and_dump
        assert "coordinated_posting" in alert_types
        assert "pump_and_dump" in alert_types

    def test_filters_by_min_severity(self):
        """Alerts below min_severity_to_report are filtered out."""
        now = time.time()
        cfg = ManipulationConfig(
            min_severity_to_report=90.0,
            min_authors_for_coordination=3,
        )
        det = ManipulationDetector(config=cfg)
        # 3 authors, tightly timed => coordination alert, but severity likely < 90
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author=f"u{i}", created_at=now + i * 10)
            for i in range(3)
        ]
        alerts = det.detect_all(signals)
        for a in alerts:
            assert a.severity >= 90.0

    def test_sorted_by_severity_desc(self):
        """Output alerts are sorted by severity descending."""
        now = time.time()
        cfg = ManipulationConfig(
            min_severity_to_report=0.0,
            pump_volume_multiplier=2.0,
            coordination_window_s=1800,
            min_authors_for_coordination=3,
        )
        det = ManipulationDetector(config=cfg)
        det._ticker_baselines["TSLA"] = _TickerBaseline(signal_counts=[1])

        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author=f"a{i}", created_at=now - 50 + i * 10)
            for i in range(5)
        ]
        alerts = det.detect_all(signals)
        if len(alerts) >= 2:
            for i in range(len(alerts) - 1):
                assert alerts[i].severity >= alerts[i + 1].severity

    def test_empty_signals_returns_empty(self):
        """Empty signal list => no alerts."""
        det = ManipulationDetector()
        assert det.detect_all([]) == []


# ── update_baselines Tests ───────────────────────────────────────────────────


class TestUpdateBaselines:
    """Tests for update_baselines."""

    def test_updates_per_ticker_rolling_counts(self):
        """Baseline counts updated for each ticker from signal list."""
        now = time.time()
        det = ManipulationDetector()
        signals = [
            _make_signal(ticker="TSLA", created_at=now),
            _make_signal(ticker="TSLA", created_at=now + 100),
            _make_signal(ticker="AAPL", created_at=now + 200),
        ]
        det.update_baselines(signals)
        baselines = det.ticker_baselines
        assert "TSLA" in baselines
        assert "AAPL" in baselines
        # TSLA has 2 signals on same day, AAPL has 1
        assert baselines["TSLA"].mean() > 0
        assert baselines["AAPL"].mean() > 0

    def test_empty_signals_no_update(self):
        """Empty signal list => no baselines changed."""
        det = ManipulationDetector()
        det.update_baselines([])
        assert len(det.ticker_baselines) == 0

    def test_multiple_days_update(self):
        """Signals spanning multiple days => multiple daily counts."""
        det = ManipulationDetector()
        day1_ts = 86400.0 * 100  # day 100
        day2_ts = 86400.0 * 101  # day 101
        signals = [
            _make_signal(ticker="TSLA", created_at=day1_ts + 100),
            _make_signal(ticker="TSLA", created_at=day1_ts + 200),
            _make_signal(ticker="TSLA", created_at=day2_ts + 100),
        ]
        det.update_baselines(signals)
        baseline = det.ticker_baselines["TSLA"]
        # Day 100 => 2 signals, Day 101 => 1 signal
        assert len(baseline.signal_counts) == 2
        assert baseline.signal_counts[0] == 2
        assert baseline.signal_counts[1] == 1

    def test_baseline_window_bounded(self):
        """Rolling window is capped at 20 entries."""
        det = ManipulationDetector()
        baseline = _TickerBaseline()
        for i in range(25):
            baseline.update(i)
        assert len(baseline.signal_counts) == 20
        # Most recent 20 values: 5..24
        assert baseline.signal_counts[0] == 5
        assert baseline.signal_counts[-1] == 24


# ── _jaccard_similarity Tests ────────────────────────────────────────────────


class TestJaccardSimilarity:
    """Tests for _jaccard_similarity helper."""

    def test_identical_strings(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert _jaccard_similarity("hello world", "foo bar baz") == 0.0

    def test_partial_overlap(self):
        # "hello" in common; union = {"hello", "world", "there"}
        sim = _jaccard_similarity("hello world", "hello there")
        assert abs(sim - 1 / 3) < 0.01

    def test_both_empty(self):
        assert _jaccard_similarity("", "") == 0.0

    def test_one_empty(self):
        assert _jaccard_similarity("hello", "") == 0.0

    def test_case_insensitive(self):
        assert _jaccard_similarity("Hello World", "hello world") == 1.0

    def test_duplicate_words_ignored(self):
        # Sets: {"hello", "world"} vs {"hello", "world"} => 1.0
        assert _jaccard_similarity("hello hello world", "hello world world") == 1.0


# ── Edge Case Tests ──────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases: empty signals, single signal, no-detection scenarios."""

    def test_single_signal_no_alerts(self):
        """A single signal can never trigger any detector."""
        det = ManipulationDetector()
        signals = [_make_signal()]
        assert det.detect_coordinated_posting(signals) == []
        assert det.detect_bot_network(signals) == []
        assert det.detect_pump_and_dump(signals) == []
        assert det.detect_all(signals) == []

    def test_empty_signals_all_detectors(self):
        """Empty input to each detector returns empty."""
        det = ManipulationDetector()
        assert det.detect_coordinated_posting([]) == []
        assert det.detect_bot_network([]) == []
        assert det.detect_pump_and_dump([]) == []

    def test_signals_with_no_ticker(self):
        """Signals missing ticker field are gracefully skipped."""
        now = time.time()
        det = ManipulationDetector()
        signals = [
            {"stance": "bullish", "author": "u1", "created_at": now, "confidence": 0.5},
            {"stance": "bullish", "author": "u2", "created_at": now + 10, "confidence": 0.5},
            {"stance": "bullish", "author": "u3", "created_at": now + 20, "confidence": 0.5},
        ]
        assert det.detect_coordinated_posting(signals) == []

    def test_signals_with_none_author(self):
        """Signals with None author => authors not counted, no alert."""
        now = time.time()
        det = ManipulationDetector()
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author=None, created_at=now),  # type: ignore[arg-type]
            _make_signal(ticker="TSLA", stance="bullish", author=None, created_at=now + 10),  # type: ignore[arg-type]
            _make_signal(ticker="TSLA", stance="bullish", author=None, created_at=now + 20),  # type: ignore[arg-type]
        ]
        # None authors are filtered out so fewer than min_authors
        alerts = det.detect_coordinated_posting(signals)
        assert len(alerts) == 0

    def test_detector_config_property(self):
        """config property returns the active configuration."""
        cfg = ManipulationConfig(coordination_window_s=999)
        det = ManipulationDetector(config=cfg)
        assert det.config is cfg
        assert det.config.coordination_window_s == 999

    def test_detector_default_config(self):
        """No config argument => default ManipulationConfig."""
        det = ManipulationDetector()
        assert det.config.coordination_window_s == 1800

    def test_ticker_baselines_property_returns_copy(self):
        """ticker_baselines returns a copy, mutations don't affect internal state."""
        det = ManipulationDetector()
        det._ticker_baselines["TSLA"] = _TickerBaseline(signal_counts=[5])
        baselines = det.ticker_baselines
        baselines["NEW"] = _TickerBaseline()  # mutate the copy
        assert "NEW" not in det._ticker_baselines

    def test_all_mixed_stance_signals_no_pump(self):
        """All 'mixed' stance signals => total_directional=0 => no pump alert."""
        now = time.time()
        cfg = ManipulationConfig(pump_volume_multiplier=2.0)
        det = ManipulationDetector(config=cfg)
        det._ticker_baselines["TSLA"] = _TickerBaseline(signal_counts=[1])
        signals = [
            _make_signal(ticker="TSLA", stance="mixed", author=f"u{i}", created_at=now - 20 + i * 5)
            for i in range(5)
        ]
        alerts = det.detect_pump_and_dump(signals)
        assert len(alerts) == 0

    def test_coordination_evidence_fields(self):
        """Verify evidence dict contains expected keys."""
        now = time.time()
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", author=f"u{i}", created_at=now + i * 5)
            for i in range(3)
        ]
        det = ManipulationDetector()
        alerts = det.detect_coordinated_posting(signals)
        assert len(alerts) == 1
        ev = alerts[0].evidence
        assert "pattern" in ev
        assert ev["pattern"] == "coordinated_posting"
        assert "authors" in ev
        assert "ticker" in ev
        assert "stance" in ev
        assert "dominant_pct" in ev
        assert "time_span_s" in ev
        assert "signal_count" in ev
