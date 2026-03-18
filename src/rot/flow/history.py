"""Rolling per-ticker flow baselines for anomaly detection.

Maintains in-memory flow statistics per ticker with LRU eviction
to bound memory usage. Used by FlowDetector to determine whether
observed flow is unusual relative to historical norms.

Design goals:
  - Memory-bounded: LRU eviction at configurable max tickers
  - Rolling window: only recent observations count
  - Fast percentile computation: for anomaly scoring
  - Thread-safe reads (GIL-protected dict access)
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Baseline Data ───────────────────────────────────────


@dataclass
class FlowBaseline:
    """Rolling baseline statistics for a single ticker.

    Mutable — updated in-place as new observations arrive.
    """

    # Cumulative stats
    net_premium: float = 0.0  # bullish - bearish cumulative
    total_premium: float = 0.0  # absolute total premium
    flow_count: int = 0  # total events observed
    bullish_count: int = 0
    bearish_count: int = 0

    # Rolling observations (premium values)
    premium_observations: List[float] = field(default_factory=list)
    volume_observations: List[int] = field(default_factory=list)
    oi_observations: List[int] = field(default_factory=list)

    # Timestamps
    first_seen: float = 0.0
    last_seen: float = 0.0

    @property
    def avg_premium(self) -> float:
        """Average premium across observations."""
        if not self.premium_observations:
            return 0.0
        return sum(self.premium_observations) / len(self.premium_observations)

    @property
    def avg_volume(self) -> float:
        """Average volume across observations."""
        if not self.volume_observations:
            return 0.0
        return sum(self.volume_observations) / len(self.volume_observations)

    @property
    def premium_std(self) -> float:
        """Standard deviation of premium observations."""
        if len(self.premium_observations) < 2:
            return 0.0
        mean = self.avg_premium
        variance = sum((x - mean) ** 2 for x in self.premium_observations) / (
            len(self.premium_observations) - 1
        )
        return math.sqrt(variance)

    @property
    def bullish_ratio(self) -> float:
        """Fraction of events that are bullish."""
        total = self.bullish_count + self.bearish_count
        if total == 0:
            return 0.5
        return self.bullish_count / total

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this flow baseline to a JSON-compatible dictionary."""
        return {
            "net_premium": round(self.net_premium, 2),
            "total_premium": round(self.total_premium, 2),
            "flow_count": self.flow_count,
            "bullish_count": self.bullish_count,
            "bearish_count": self.bearish_count,
            "avg_premium": round(self.avg_premium, 2),
            "avg_volume": round(self.avg_volume, 0),
            "premium_std": round(self.premium_std, 2),
            "bullish_ratio": round(self.bullish_ratio, 3),
            "observation_count": len(self.premium_observations),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


# ── Flow History ────────────────────────────────────────


class FlowHistory:
    """Rolling per-ticker flow baselines with LRU eviction.

    Maintains a bounded cache of per-ticker flow statistics.
    When the cache exceeds max_tickers, the least-recently-used
    ticker is evicted.

    Example::

        history = FlowHistory(max_tickers=500, max_observations=200)
        history.update("TSLA", premium=150000.0, volume=500, oi_change=1000,
                       direction="bullish")
        baseline = history.get_baseline("TSLA")
        pct = history.get_premium_percentile("TSLA", 200000.0)
    """

    def __init__(
        self,
        max_tickers: int = 500,
        max_observations: int = 200,
    ) -> None:
        self._max_tickers = max_tickers
        self._max_observations = max_observations
        self._baselines: OrderedDict[str, FlowBaseline] = OrderedDict()

    @property
    def ticker_count(self) -> int:
        """Number of tickers being tracked."""
        return len(self._baselines)

    @property
    def max_tickers(self) -> int:
        """Maximum number of tickers this history store will track simultaneously."""
        return self._max_tickers

    # ── Update ──────────────────────────────────────────

    def update(
        self,
        ticker: str,
        premium: float,
        volume: int = 0,
        oi_change: int = 0,
        direction: str = "neutral",
        timestamp: Optional[float] = None,
    ) -> None:
        """Record a new flow observation for a ticker.

        Parameters
        ----------
        ticker : str
            Ticker symbol.
        premium : float
            Absolute premium of the flow event.
        volume : int
            Contract volume.
        oi_change : int
            Change in open interest.
        direction : str
            "bullish", "bearish", or "neutral".
        timestamp : float, optional
            Unix timestamp. Defaults to now.
        """
        ts = timestamp or time.time()

        if ticker not in self._baselines:
            # Evict LRU if at capacity
            if len(self._baselines) >= self._max_tickers:
                self._baselines.popitem(last=False)
            self._baselines[ticker] = FlowBaseline(first_seen=ts)

        baseline = self._baselines[ticker]
        # Move to end (most recently used)
        self._baselines.move_to_end(ticker)

        # Update cumulative stats
        baseline.flow_count += 1
        baseline.total_premium += premium
        baseline.last_seen = ts

        if direction == "bullish":
            baseline.net_premium += premium
            baseline.bullish_count += 1
        elif direction == "bearish":
            baseline.net_premium -= premium
            baseline.bearish_count += 1

        # Add observations (bounded)
        baseline.premium_observations.append(premium)
        if len(baseline.premium_observations) > self._max_observations:
            baseline.premium_observations = baseline.premium_observations[
                -self._max_observations :
            ]

        if volume > 0:
            baseline.volume_observations.append(volume)
            if len(baseline.volume_observations) > self._max_observations:
                baseline.volume_observations = baseline.volume_observations[
                    -self._max_observations :
                ]

        if oi_change != 0:
            baseline.oi_observations.append(oi_change)
            if len(baseline.oi_observations) > self._max_observations:
                baseline.oi_observations = baseline.oi_observations[
                    -self._max_observations :
                ]

    def update_batch(
        self,
        ticker: str,
        events: List[Dict[str, Any]],
    ) -> None:
        """Batch update from multiple flow events.

        Each event dict should have: premium, volume, oi_change, direction,
        timestamp (all optional except premium).
        """
        for event in events:
            self.update(
                ticker=ticker,
                premium=float(event.get("premium", 0)),
                volume=int(event.get("volume", 0)),
                oi_change=int(event.get("oi_change", 0)),
                direction=str(event.get("direction", "neutral")),
                timestamp=event.get("timestamp"),
            )

    # ── Query ───────────────────────────────────────────

    def get_baseline(self, ticker: str) -> Optional[FlowBaseline]:
        """Get baseline for a ticker, or None if not tracked."""
        return self._baselines.get(ticker)

    def has_ticker(self, ticker: str) -> bool:
        """Check if ticker is being tracked."""
        return ticker in self._baselines

    def get_premium_percentile(
        self,
        ticker: str,
        current_premium: float,
    ) -> Optional[float]:
        """Get percentile rank of current premium vs historical.

        Returns percentile 0-100, or None if insufficient data (<5 observations).
        """
        baseline = self._baselines.get(ticker)
        if not baseline or len(baseline.premium_observations) < 5:
            return None

        sorted_obs = sorted(baseline.premium_observations)
        rank = sum(1 for x in sorted_obs if x < current_premium)
        return 100.0 * rank / len(sorted_obs)

    def get_volume_percentile(
        self,
        ticker: str,
        current_volume: int,
    ) -> Optional[float]:
        """Get percentile rank of current volume vs historical."""
        baseline = self._baselines.get(ticker)
        if not baseline or len(baseline.volume_observations) < 5:
            return None

        sorted_obs = sorted(baseline.volume_observations)
        rank = sum(1 for x in sorted_obs if x < current_volume)
        return 100.0 * rank / len(sorted_obs)

    def get_premium_zscore(
        self,
        ticker: str,
        current_premium: float,
    ) -> Optional[float]:
        """Get z-score of current premium vs historical distribution.

        Returns None if insufficient data or zero std deviation.
        """
        baseline = self._baselines.get(ticker)
        if not baseline or len(baseline.premium_observations) < 5:
            return None

        std = baseline.premium_std
        if std <= 0:
            return None

        return (current_premium - baseline.avg_premium) / std

    # ── Maintenance ─────────────────────────────────────

    def clear(self) -> None:
        """Clear all baselines."""
        self._baselines.clear()

    def remove_ticker(self, ticker: str) -> bool:
        """Remove a single ticker. Returns True if it existed."""
        if ticker in self._baselines:
            del self._baselines[ticker]
            return True
        return False

    def get_all_tickers(self) -> List[str]:
        """Get all tracked tickers (most recent last)."""
        return list(self._baselines.keys())

    def get_top_tickers(
        self,
        n: int = 10,
        sort_by: str = "total_premium",
    ) -> List[Tuple[str, FlowBaseline]]:
        """Get top N tickers by a metric.

        sort_by: "total_premium", "flow_count", "net_premium", "avg_premium"
        """
        items = list(self._baselines.items())

        if sort_by == "total_premium":
            items.sort(key=lambda x: x[1].total_premium, reverse=True)
        elif sort_by == "flow_count":
            items.sort(key=lambda x: x[1].flow_count, reverse=True)
        elif sort_by == "net_premium":
            items.sort(key=lambda x: abs(x[1].net_premium), reverse=True)
        elif sort_by == "avg_premium":
            items.sort(key=lambda x: x[1].avg_premium, reverse=True)

        return items[:n]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize all baselines for persistence."""
        return {
            ticker: baseline.to_dict()
            for ticker, baseline in self._baselines.items()
        }
