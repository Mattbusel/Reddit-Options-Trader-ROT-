"""Historical data manager with in-memory caching and CSV I/O."""

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PriceBar:
    """A single OHLCV bar for one symbol."""

    timestamp: int  # Unix epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str


class DataCache:
    """Simple in-memory cache for PriceBar lists keyed by symbol."""

    def __init__(self) -> None:
        self._data: dict[str, list[PriceBar]] = {}
        self._stored_at: dict[str, float] = {}  # wall-clock time of storage

    def store(self, symbol: str, bars: list[PriceBar]) -> None:
        """Store bars for *symbol*, recording the current wall-clock time."""
        self._data[symbol] = list(bars)
        self._stored_at[symbol] = time.time()

    def get(self, symbol: str) -> Optional[list[PriceBar]]:
        """Return the cached bars or *None* if the symbol is not cached."""
        return self._data.get(symbol)

    def is_fresh(self, symbol: str, max_age_secs: float = 3600) -> bool:
        """Return *True* if the cached data is younger than *max_age_secs*."""
        stored = self._stored_at.get(symbol)
        if stored is None:
            return False
        return (time.time() - stored) < max_age_secs

    def invalidate(self, symbol: str) -> None:
        """Remove the cached entry for *symbol* (no-op if not cached)."""
        self._data.pop(symbol, None)
        self._stored_at.pop(symbol, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._data.clear()
        self._stored_at.clear()


class HistoricalDataManager:
    """Load, save, and transform historical price bar data."""

    # ------------------------------------------------------------------
    # CSV I/O
    # ------------------------------------------------------------------

    def load_csv(self, filepath: str, symbol: str) -> list[PriceBar]:
        """Parse a CSV file with columns timestamp,open,high,low,close,volume.

        Args:
            filepath: Path to the CSV file (or any ``str`` accepted by
                ``open()``).
            symbol: Ticker symbol to attach to each bar.

        Returns:
            List of :class:`PriceBar` objects sorted by timestamp ascending.
        """
        bars: list[PriceBar] = []
        with open(filepath, newline="") as fh:
            bars = self._parse_csv_stream(fh, symbol)
        return sorted(bars, key=lambda b: b.timestamp)

    @staticmethod
    def _parse_csv_stream(stream: io.TextIOBase, symbol: str) -> list[PriceBar]:
        reader = csv.DictReader(stream)
        bars: list[PriceBar] = []
        for row in reader:
            bars.append(
                PriceBar(
                    timestamp=int(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    symbol=symbol,
                )
            )
        return bars

    def load_csv_from_string(self, csv_text: str, symbol: str) -> list[PriceBar]:
        """Parse CSV directly from a string — useful for tests."""
        stream = io.StringIO(csv_text)
        bars = self._parse_csv_stream(stream, symbol)
        return sorted(bars, key=lambda b: b.timestamp)

    def save_csv(self, bars: list[PriceBar], filepath: str) -> None:
        """Write bars to *filepath* in timestamp,open,high,low,close,volume format."""
        with open(filepath, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            for bar in bars:
                writer.writerow(
                    [bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume]
                )

    # ------------------------------------------------------------------
    # Transformations
    # ------------------------------------------------------------------

    def resample(
        self, bars: list[PriceBar], new_period_minutes: int
    ) -> list[PriceBar]:
        """Aggregate bars into a larger period using OHLCV rules.

        Args:
            bars: Input bars sorted by timestamp.
            new_period_minutes: Target bar width in minutes.

        Returns:
            List of resampled bars.
        """
        if not bars:
            return []

        period_secs = new_period_minutes * 60
        bucket_bars: dict[int, list[PriceBar]] = {}
        for bar in bars:
            bucket = (bar.timestamp // period_secs) * period_secs
            bucket_bars.setdefault(bucket, []).append(bar)

        result: list[PriceBar] = []
        for bucket_ts in sorted(bucket_bars):
            group = bucket_bars[bucket_ts]
            symbol = group[0].symbol
            result.append(
                PriceBar(
                    timestamp=bucket_ts,
                    open=group[0].open,
                    high=max(b.high for b in group),
                    low=min(b.low for b in group),
                    close=group[-1].close,
                    volume=sum(b.volume for b in group),
                    symbol=symbol,
                )
            )
        return result

    def compute_returns(self, bars: list[PriceBar]) -> list[float]:
        """Compute simple close-to-close percentage returns.

        Returns a list of length ``len(bars) - 1``.
        """
        if len(bars) < 2:
            return []
        returns = []
        for i in range(1, len(bars)):
            prev = bars[i - 1].close
            curr = bars[i].close
            if prev == 0.0:
                returns.append(0.0)
            else:
                returns.append((curr - prev) / prev)
        return returns

    def split_train_test(
        self, bars: list[PriceBar], test_fraction: float = 0.2
    ) -> tuple[list[PriceBar], list[PriceBar]]:
        """Split *bars* chronologically into training and test sets.

        Args:
            bars: Input bars, assumed to be sorted by timestamp.
            test_fraction: Fraction of bars reserved for testing.

        Returns:
            ``(train_bars, test_bars)`` tuple.
        """
        if not bars:
            return [], []
        split_idx = int(len(bars) * (1.0 - test_fraction))
        split_idx = max(1, min(split_idx, len(bars) - 1))
        return bars[:split_idx], bars[split_idx:]


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------
import unittest


class TestDataCache(unittest.TestCase):
    def _make_bars(self, symbol: str = "TEST") -> list[PriceBar]:
        return [
            PriceBar(1_000, 100.0, 105.0, 99.0, 102.0, 5000.0, symbol),
            PriceBar(2_000, 102.0, 108.0, 101.0, 107.0, 6000.0, symbol),
        ]

    def test_store_and_get(self) -> None:
        cache = DataCache()
        bars = self._make_bars()
        cache.store("TEST", bars)
        result = cache.get("TEST")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)

    def test_get_missing_returns_none(self) -> None:
        cache = DataCache()
        self.assertIsNone(cache.get("UNKNOWN"))

    def test_is_fresh_immediately(self) -> None:
        cache = DataCache()
        cache.store("TEST", self._make_bars())
        self.assertTrue(cache.is_fresh("TEST"))

    def test_is_fresh_missing_symbol(self) -> None:
        cache = DataCache()
        self.assertFalse(cache.is_fresh("MISSING"))

    def test_invalidate(self) -> None:
        cache = DataCache()
        cache.store("TEST", self._make_bars())
        cache.invalidate("TEST")
        self.assertIsNone(cache.get("TEST"))

    def test_clear(self) -> None:
        cache = DataCache()
        cache.store("A", self._make_bars("A"))
        cache.store("B", self._make_bars("B"))
        cache.clear()
        self.assertIsNone(cache.get("A"))
        self.assertIsNone(cache.get("B"))

    def test_is_fresh_zero_max_age(self) -> None:
        cache = DataCache()
        cache.store("TEST", self._make_bars())
        # max_age_secs=0 should never be fresh (time elapsed >= 0)
        self.assertFalse(cache.is_fresh("TEST", max_age_secs=0))


CSV_DATA = """timestamp,open,high,low,close,volume
1000,100.0,105.0,99.0,102.0,5000.0
2000,102.0,108.0,101.0,107.0,6000.0
3000,107.0,110.0,106.0,109.0,4500.0
"""


class TestHistoricalDataManager(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = HistoricalDataManager()

    def test_load_csv_from_string(self) -> None:
        bars = self.mgr.load_csv_from_string(CSV_DATA, "AAPL")
        self.assertEqual(len(bars), 3)
        self.assertEqual(bars[0].symbol, "AAPL")

    def test_load_csv_sorted_by_timestamp(self) -> None:
        unordered = """timestamp,open,high,low,close,volume
3000,107.0,110.0,106.0,109.0,4500.0
1000,100.0,105.0,99.0,102.0,5000.0
"""
        bars = self.mgr.load_csv_from_string(unordered, "X")
        self.assertEqual(bars[0].timestamp, 1000)
        self.assertEqual(bars[1].timestamp, 3000)

    def test_compute_returns_length(self) -> None:
        bars = self.mgr.load_csv_from_string(CSV_DATA, "X")
        returns = self.mgr.compute_returns(bars)
        self.assertEqual(len(returns), len(bars) - 1)

    def test_compute_returns_values(self) -> None:
        bars = self.mgr.load_csv_from_string(CSV_DATA, "X")
        returns = self.mgr.compute_returns(bars)
        expected = (107.0 - 102.0) / 102.0
        self.assertAlmostEqual(returns[0], expected)

    def test_compute_returns_empty(self) -> None:
        self.assertEqual(self.mgr.compute_returns([]), [])

    def test_split_train_test_proportions(self) -> None:
        bars = self.mgr.load_csv_from_string(CSV_DATA, "X")
        train, test = self.mgr.split_train_test(bars, test_fraction=0.33)
        self.assertEqual(len(train) + len(test), len(bars))
        self.assertGreater(len(train), 0)
        self.assertGreater(len(test), 0)

    def test_split_train_test_empty(self) -> None:
        train, test = self.mgr.split_train_test([], 0.2)
        self.assertEqual(train, [])
        self.assertEqual(test, [])

    def test_resample_aggregates_bars(self) -> None:
        bars = self.mgr.load_csv_from_string(CSV_DATA, "X")
        # All bars are within [0, 3000] seconds — 60-minute bucket fits all.
        resampled = self.mgr.resample(bars, new_period_minutes=60)
        self.assertGreaterEqual(len(resampled), 1)

    def test_resample_ohlcv_correctness(self) -> None:
        bars = [
            PriceBar(0, 100.0, 110.0, 95.0, 105.0, 1000.0, "X"),
            PriceBar(60, 105.0, 115.0, 100.0, 112.0, 2000.0, "X"),
        ]
        resampled = self.mgr.resample(bars, new_period_minutes=2)
        # Both bars fall in the same 2-minute bucket (ts 0 and 60 → bucket 0).
        self.assertEqual(len(resampled), 1)
        r = resampled[0]
        self.assertEqual(r.open, 100.0)
        self.assertEqual(r.high, 115.0)
        self.assertEqual(r.low, 95.0)
        self.assertEqual(r.close, 112.0)
        self.assertAlmostEqual(r.volume, 3000.0)

    def test_resample_empty(self) -> None:
        self.assertEqual(self.mgr.resample([], 5), [])


if __name__ == "__main__":
    unittest.main()
