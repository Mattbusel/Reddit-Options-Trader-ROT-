"""Unusual options flow analysis.

Detects unusual activity, aggregates sentiment, and profiles premium
distribution across flow records.
"""

from __future__ import annotations

import unittest
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, date
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# FlowRecord
# ---------------------------------------------------------------------------

@dataclass
class FlowRecord:
    """A single options flow event."""

    timestamp: datetime
    symbol: str
    expiry: date
    strike: float
    option_type: str        # 'call' or 'put'
    size: int               # contract count
    premium: float          # total premium paid (USD)
    is_sweep: bool          # True if executed as a sweep order
    is_block: bool          # True if block trade
    sentiment: str          # 'bullish', 'bearish', or 'neutral'


# ---------------------------------------------------------------------------
# FlowAnalyzer
# ---------------------------------------------------------------------------

class FlowAnalyzer:
    """Analyze options flow records for unusual activity and sentiment."""

    # ------------------------------------------------------------------
    # Unusual activity detection
    # ------------------------------------------------------------------

    def detect_unusual_activity(
        self,
        flows: List[FlowRecord],
        avg_daily_volume: Dict[str, float],
    ) -> List[FlowRecord]:
        """Return flows where size exceeds 2x the average daily volume for that symbol."""
        result: List[FlowRecord] = []
        for record in flows:
            avg = avg_daily_volume.get(record.symbol, 0.0)
            if avg > 0 and record.size > 2.0 * avg:
                result.append(record)
        return result

    # ------------------------------------------------------------------
    # Sentiment aggregation
    # ------------------------------------------------------------------

    def aggregate_sentiment(
        self,
        flows: List[FlowRecord],
    ) -> Dict[str, float]:
        """Compute bullish ratio (bullish_count / total_count) per symbol.

        Returns a dict mapping symbol -> bullish_ratio in [0, 1].
        """
        total: Dict[str, int] = defaultdict(int)
        bullish: Dict[str, int] = defaultdict(int)

        for record in flows:
            total[record.symbol] += 1
            if record.sentiment == "bullish":
                bullish[record.symbol] += 1

        return {
            sym: bullish[sym] / total[sym]
            for sym in total
        }

    # ------------------------------------------------------------------
    # Block / sweep ratio
    # ------------------------------------------------------------------

    def block_sweep_ratio(self, flows: List[FlowRecord]) -> float:
        """Fraction of flows that are blocks or sweeps.

        Returns 0.0 if flows is empty.
        """
        if not flows:
            return 0.0
        bs_count = sum(1 for f in flows if f.is_block or f.is_sweep)
        return bs_count / len(flows)

    # ------------------------------------------------------------------
    # Top symbols by premium
    # ------------------------------------------------------------------

    def top_symbols_by_premium(
        self,
        flows: List[FlowRecord],
        n: int = 10,
    ) -> List[Tuple[str, float]]:
        """Return the top-n symbols ranked by total premium (desc)."""
        totals: Dict[str, float] = defaultdict(float)
        for record in flows:
            totals[record.symbol] += record.premium

        ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)
        return ranked[:n]

    # ------------------------------------------------------------------
    # Time-series flow
    # ------------------------------------------------------------------

    def time_series_flow(
        self,
        flows: List[FlowRecord],
        bucket_minutes: int = 5,
    ) -> Dict[str, float]:
        """Aggregate total premium into fixed-width time buckets.

        Returns a dict mapping ISO timestamp string (bucket start) -> total premium.
        Each bucket is `bucket_minutes` wide, aligned to epoch.
        """
        buckets: Dict[str, float] = defaultdict(float)
        bucket_seconds = bucket_minutes * 60

        for record in flows:
            ts_epoch = int(record.timestamp.timestamp())
            bucket_epoch = (ts_epoch // bucket_seconds) * bucket_seconds
            # Format as ISO 8601 string for readability.
            bucket_dt = datetime.utcfromtimestamp(bucket_epoch)
            key = bucket_dt.strftime("%Y-%m-%dT%H:%M:%S")
            buckets[key] += record.premium

        return dict(buckets)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestFlowAnalyzer(unittest.TestCase):
    """Unit tests for FlowAnalyzer."""

    def _make_record(
        self,
        symbol: str = "AAPL",
        size: int = 100,
        premium: float = 10_000.0,
        is_sweep: bool = False,
        is_block: bool = False,
        sentiment: str = "bullish",
        ts: datetime = None,
    ) -> FlowRecord:
        if ts is None:
            ts = datetime(2026, 3, 23, 10, 0, 0)
        return FlowRecord(
            timestamp=ts,
            symbol=symbol,
            expiry=date(2026, 6, 20),
            strike=150.0,
            option_type="call",
            size=size,
            premium=premium,
            is_sweep=is_sweep,
            is_block=is_block,
            sentiment=sentiment,
        )

    def setUp(self) -> None:
        self.analyzer = FlowAnalyzer()
        self.flows = [
            self._make_record("AAPL", size=500,  premium=50_000, sentiment="bullish"),
            self._make_record("AAPL", size=100,  premium=10_000, sentiment="bearish"),
            self._make_record("TSLA", size=1000, premium=80_000, sentiment="bullish", is_sweep=True),
            self._make_record("TSLA", size=50,   premium=4_000,  sentiment="neutral"),
            self._make_record("SPY",  size=200,  premium=20_000, is_block=True, sentiment="bearish"),
        ]

    def test_detect_unusual_activity_basic(self) -> None:
        avg_vol = {"AAPL": 100.0, "TSLA": 200.0, "SPY": 90.0}
        unusual = self.analyzer.detect_unusual_activity(self.flows, avg_vol)
        symbols = [f.symbol for f in unusual]
        # AAPL 500 > 2*100=200 → unusual
        self.assertIn("AAPL", symbols)
        # TSLA 1000 > 2*200=400 → unusual
        self.assertIn("TSLA", symbols)
        # SPY 200 > 2*90=180 → unusual
        self.assertIn("SPY", symbols)

    def test_detect_unusual_activity_no_false_positives(self) -> None:
        avg_vol = {"AAPL": 1000.0, "TSLA": 1000.0, "SPY": 1000.0}
        unusual = self.analyzer.detect_unusual_activity(self.flows, avg_vol)
        self.assertEqual(unusual, [])

    def test_detect_unusual_activity_missing_symbol(self) -> None:
        # Symbol not in avg_daily_volume should be skipped (avg=0).
        unusual = self.analyzer.detect_unusual_activity(self.flows, {})
        self.assertEqual(unusual, [])

    def test_aggregate_sentiment_bullish_ratio(self) -> None:
        ratios = self.analyzer.aggregate_sentiment(self.flows)
        # AAPL: 1 bullish, 1 bearish → 0.5
        self.assertAlmostEqual(ratios["AAPL"], 0.5)
        # TSLA: 1 bullish, 1 neutral → 0.5
        self.assertAlmostEqual(ratios["TSLA"], 0.5)
        # SPY: 0 bullish, 1 bearish → 0.0
        self.assertAlmostEqual(ratios["SPY"], 0.0)

    def test_aggregate_sentiment_all_bullish(self) -> None:
        flows = [self._make_record("X", sentiment="bullish") for _ in range(5)]
        ratios = self.analyzer.aggregate_sentiment(flows)
        self.assertAlmostEqual(ratios["X"], 1.0)

    def test_aggregate_sentiment_empty_returns_empty(self) -> None:
        ratios = self.analyzer.aggregate_sentiment([])
        self.assertEqual(ratios, {})

    def test_block_sweep_ratio_mixed(self) -> None:
        ratio = self.analyzer.block_sweep_ratio(self.flows)
        # 1 sweep (TSLA) + 1 block (SPY) = 2 out of 5
        self.assertAlmostEqual(ratio, 2 / 5)

    def test_block_sweep_ratio_empty(self) -> None:
        ratio = self.analyzer.block_sweep_ratio([])
        self.assertAlmostEqual(ratio, 0.0)

    def test_block_sweep_ratio_all_normal(self) -> None:
        flows = [self._make_record() for _ in range(3)]
        ratio = self.analyzer.block_sweep_ratio(flows)
        self.assertAlmostEqual(ratio, 0.0)

    def test_top_symbols_by_premium(self) -> None:
        ranking = self.analyzer.top_symbols_by_premium(self.flows)
        # TSLA: 84k, AAPL: 60k, SPY: 20k
        self.assertEqual(ranking[0][0], "TSLA")
        self.assertEqual(ranking[1][0], "AAPL")
        self.assertEqual(ranking[2][0], "SPY")

    def test_top_symbols_by_premium_n_limit(self) -> None:
        ranking = self.analyzer.top_symbols_by_premium(self.flows, n=1)
        self.assertEqual(len(ranking), 1)

    def test_top_symbols_by_premium_empty(self) -> None:
        ranking = self.analyzer.top_symbols_by_premium([])
        self.assertEqual(ranking, [])

    def test_time_series_flow_buckets(self) -> None:
        flows = [
            self._make_record(premium=1000.0, ts=datetime(2026, 3, 23, 10, 0, 30)),
            self._make_record(premium=2000.0, ts=datetime(2026, 3, 23, 10, 3, 0)),
            self._make_record(premium=3000.0, ts=datetime(2026, 3, 23, 10, 7, 0)),
        ]
        buckets = self.analyzer.time_series_flow(flows, bucket_minutes=5)
        # First two records fall in 10:00 bucket, third in 10:05 bucket.
        total_all = sum(buckets.values())
        self.assertAlmostEqual(total_all, 6000.0)
        self.assertEqual(len(buckets), 2)

    def test_time_series_flow_empty(self) -> None:
        buckets = self.analyzer.time_series_flow([])
        self.assertEqual(buckets, {})

    def test_time_series_flow_single_bucket(self) -> None:
        flows = [
            self._make_record(premium=500.0, ts=datetime(2026, 3, 23, 9, 0, 0)),
            self._make_record(premium=500.0, ts=datetime(2026, 3, 23, 9, 1, 0)),
        ]
        buckets = self.analyzer.time_series_flow(flows, bucket_minutes=5)
        self.assertEqual(len(buckets), 1)
        val = next(iter(buckets.values()))
        self.assertAlmostEqual(val, 1000.0)


if __name__ == "__main__":
    unittest.main()
