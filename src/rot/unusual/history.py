"""Rolling historical stats for unusual activity baseline computation.

Maintains per-ticker rolling windows of IV, volume, OI, and P/C ratio
to detect anomalies via percentile rank and z-score methods.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple


@dataclass
class TickerStats:
    """Rolling statistics for a single ticker."""

    iv_history: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    volume_history: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    oi_history: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    pc_ratio_history: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    last_oi: Optional[float] = None


class UnusualHistory:
    """Maintains rolling baselines per ticker for anomaly detection.

    Thread-safe: all mutations go through a lock.
    """

    def __init__(self, max_window: int = 100) -> None:
        self._max_window = max_window
        self._tickers: Dict[str, TickerStats] = defaultdict(
            lambda: TickerStats(
                iv_history=deque(maxlen=max_window),
                volume_history=deque(maxlen=max_window),
                oi_history=deque(maxlen=max_window),
                pc_ratio_history=deque(maxlen=max_window),
            )
        )
        self._lock = threading.Lock()

    @property
    def ticker_count(self) -> int:
        with self._lock:
            return len(self._tickers)

    def update(
        self,
        ticker: str,
        iv: Optional[float] = None,
        volume: Optional[float] = None,
        oi: Optional[float] = None,
        pc_ratio: Optional[float] = None,
    ) -> None:
        """Record new observation for a ticker."""
        with self._lock:
            stats = self._tickers[ticker]
            if iv is not None and iv > 0:
                stats.iv_history.append(iv)
            if volume is not None and volume > 0:
                stats.volume_history.append(volume)
            if oi is not None and oi > 0:
                # Track previous OI for delta calculation
                if stats.oi_history:
                    stats.last_oi = stats.oi_history[-1]
                stats.oi_history.append(oi)
            if pc_ratio is not None and pc_ratio > 0:
                stats.pc_ratio_history.append(pc_ratio)

    def get_iv_rank(self, ticker: str, current_iv: float) -> Optional[float]:
        """IV percentile rank (0-100). None if insufficient history."""
        with self._lock:
            stats = self._tickers.get(ticker)
            if not stats or len(stats.iv_history) < 5:
                return None
            history = list(stats.iv_history)

        count_below = sum(1 for v in history if v < current_iv)
        return (count_below / len(history)) * 100.0

    def get_volume_zscore(self, ticker: str, current_volume: float) -> Optional[float]:
        """Volume z-score vs rolling mean. None if insufficient history."""
        with self._lock:
            stats = self._tickers.get(ticker)
            if not stats or len(stats.volume_history) < 5:
                return None
            history = list(stats.volume_history)

        mean = sum(history) / len(history)
        if mean < 1.0:
            return None
        variance = sum((v - mean) ** 2 for v in history) / len(history)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std < 1.0:
            # Low variance — use ratio instead
            return (current_volume / mean) - 1.0 if mean > 0 else None
        return (current_volume - mean) / std

    def get_volume_ratio(self, ticker: str, current_volume: float) -> Optional[float]:
        """Volume as multiple of rolling average. None if insufficient history."""
        with self._lock:
            stats = self._tickers.get(ticker)
            if not stats or len(stats.volume_history) < 3:
                return None
            history = list(stats.volume_history)

        mean = sum(history) / len(history)
        if mean < 1.0:
            return None
        return current_volume / mean

    def get_oi_change_pct(self, ticker: str, current_oi: float) -> Optional[float]:
        """OI percent change from previous observation. None if no prior data."""
        with self._lock:
            stats = self._tickers.get(ticker)
            if not stats or stats.last_oi is None or stats.last_oi < 1.0:
                return None
            prev = stats.last_oi

        return ((current_oi - prev) / prev) * 100.0

    def get_pc_ratio_zscore(
        self, ticker: str, current_ratio: float
    ) -> Optional[float]:
        """P/C ratio z-score vs rolling mean. None if insufficient history."""
        with self._lock:
            stats = self._tickers.get(ticker)
            if not stats or len(stats.pc_ratio_history) < 5:
                return None
            history = list(stats.pc_ratio_history)

        mean = sum(history) / len(history)
        variance = sum((v - mean) ** 2 for v in history) / len(history)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std < 0.01:
            return 0.0
        return (current_ratio - mean) / std

    def get_stats_snapshot(self, ticker: str) -> Dict[str, Any]:
        """Get current stats for debugging/display."""
        with self._lock:
            stats = self._tickers.get(ticker)
            if not stats:
                return {"ticker": ticker, "has_data": False}
            return {
                "ticker": ticker,
                "has_data": True,
                "iv_samples": len(stats.iv_history),
                "volume_samples": len(stats.volume_history),
                "oi_samples": len(stats.oi_history),
                "pc_ratio_samples": len(stats.pc_ratio_history),
                "last_oi": stats.last_oi,
            }

    def clear(self) -> None:
        """Clear all history."""
        with self._lock:
            self._tickers.clear()

    def clear_ticker(self, ticker: str) -> None:
        """Clear history for a specific ticker."""
        with self._lock:
            self._tickers.pop(ticker, None)
