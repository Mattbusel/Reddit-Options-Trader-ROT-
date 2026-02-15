"""Institutional flow pattern recognition.

Detects higher-level patterns from sequences of FlowEvents:
  - Repeat buyer: same direction, same ticker, across multiple observations
  - Accumulation sequence: gradually building a position over days
  - Hedging: simultaneous bullish + bearish flow (protective positioning)
  - Rolling: closing near-term options, opening far-term (maintaining exposure)
  - Cross-ticker: related tickers showing correlated flow (sector rotation)

Design goals:
  - Stateless pattern recognizer (reusable across scans)
  - Configurable confidence thresholds
  - Time-window-aware grouping
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional

from rot.flow.types import FlowEvent, FlowPattern

log = logging.getLogger(__name__)

# ── Sector Groups (for cross-ticker detection) ──────────

_SECTOR_GROUPS: Dict[str, List[str]] = {
    "mega_tech": ["AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA"],
    "semis": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "MU", "MRVL"],
    "financials": ["JPM", "BAC", "GS", "MS", "C", "WFC", "BLK", "SCHW"],
    "energy": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "VLO"],
    "healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT"],
    "consumer": ["WMT", "COST", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW"],
    "indices": ["SPY", "QQQ", "IWM", "DIA", "VXX", "UVXY"],
}

# Reverse lookup: ticker → sector
_TICKER_SECTOR: Dict[str, str] = {}
for _sector, _tickers in _SECTOR_GROUPS.items():
    for _t in _tickers:
        _TICKER_SECTOR[_t] = _sector


# ── Pattern Config ──────────────────────────────────────


class FlowPatternConfig:
    """Configuration for pattern recognition thresholds."""

    def __init__(
        self,
        min_confidence: float = 0.4,
        repeat_buyer_min_events: int = 3,
        repeat_buyer_window_s: float = 86400.0 * 3,  # 3 days
        accumulation_min_events: int = 4,
        accumulation_window_s: float = 86400.0 * 7,  # 7 days
        hedging_window_s: float = 3600.0 * 8,  # 8 hours
        rolling_window_s: float = 86400.0 * 5,  # 5 days
        cross_ticker_min_count: int = 3,
        cross_ticker_window_s: float = 3600.0 * 12,  # 12 hours
    ) -> None:
        self.min_confidence = min_confidence
        self.repeat_buyer_min_events = repeat_buyer_min_events
        self.repeat_buyer_window_s = repeat_buyer_window_s
        self.accumulation_min_events = accumulation_min_events
        self.accumulation_window_s = accumulation_window_s
        self.hedging_window_s = hedging_window_s
        self.rolling_window_s = rolling_window_s
        self.cross_ticker_min_count = cross_ticker_min_count
        self.cross_ticker_window_s = cross_ticker_window_s


# ── Pattern Recognizer ──────────────────────────────────


class FlowPatternRecognizer:
    """Recognize institutional patterns from flow events.

    Analyzes sequences of FlowEvents to detect higher-level patterns
    that indicate institutional strategy (accumulation, hedging, etc.).

    Example::

        recognizer = FlowPatternRecognizer()
        patterns = recognizer.recognize(flow_events)
    """

    def __init__(self, config: Optional[FlowPatternConfig] = None) -> None:
        self._config = config or FlowPatternConfig()

    @property
    def config(self) -> FlowPatternConfig:
        return self._config

    def recognize(
        self,
        events: List[FlowEvent],
        timestamp: Optional[float] = None,
    ) -> List[FlowPattern]:
        """Detect all patterns from a list of flow events.

        Parameters
        ----------
        events : list
            Flow events (may span multiple tickers).
        timestamp : float, optional
            Detection timestamp. Defaults to now.

        Returns
        -------
        List[FlowPattern]
            Detected patterns above min_confidence.
        """
        if not events:
            return []

        ts = timestamp or time.time()
        patterns: List[FlowPattern] = []

        # Group events by ticker
        by_ticker = self._group_by_ticker(events)

        # Per-ticker patterns
        for ticker, ticker_events in by_ticker.items():
            if len(ticker_events) < 2:
                continue

            # Sort by timestamp
            ticker_events.sort(key=lambda e: e.timestamp)

            patterns.extend(self._detect_repeat_buyer(ticker, ticker_events, ts))
            patterns.extend(self._detect_accumulation_sequence(ticker, ticker_events, ts))
            patterns.extend(self._detect_hedging(ticker, ticker_events, ts))
            patterns.extend(self._detect_rolling(ticker, ticker_events, ts))

        # Cross-ticker patterns
        patterns.extend(self._detect_cross_ticker(events, ts))

        # Filter by minimum confidence
        patterns = [p for p in patterns if p.confidence >= self._config.min_confidence]

        return patterns

    # ── Per-Ticker Patterns ─────────────────────────────

    def _detect_repeat_buyer(
        self,
        ticker: str,
        events: List[FlowEvent],
        ts: float,
    ) -> List[FlowPattern]:
        """Detect repeat buyer: same direction over multiple observations.

        A repeat buyer consistently takes positions in the same direction,
        suggesting conviction and institutional accumulation.
        """
        patterns: List[FlowPattern] = []
        window = self._config.repeat_buyer_window_s
        min_events = self._config.repeat_buyer_min_events

        # Check bullish repeats
        bullish = [e for e in events if e.direction == "bullish"]
        if len(bullish) >= min_events:
            # Check if within time window
            recent = [e for e in bullish if ts - e.timestamp <= window]
            if len(recent) >= min_events:
                total_premium = sum(e.premium for e in recent)
                consistency = len(recent) / max(len(events), 1)
                confidence = min(
                    0.4 + 0.1 * (len(recent) - min_events) + 0.2 * consistency,
                    0.95,
                )

                patterns.append(FlowPattern(
                    id=str(uuid.uuid4()),
                    pattern_type="repeat_buyer",
                    tickers=[ticker],
                    confidence=round(confidence, 3),
                    timeframe=self._classify_timeframe(recent),
                    event_count=len(recent),
                    details={
                        "direction": "bullish",
                        "total_premium": round(total_premium, 2),
                        "event_types": self._count_types(recent),
                    },
                    detected_at=ts,
                ))

        # Check bearish repeats
        bearish = [e for e in events if e.direction == "bearish"]
        if len(bearish) >= min_events:
            recent = [e for e in bearish if ts - e.timestamp <= window]
            if len(recent) >= min_events:
                total_premium = sum(e.premium for e in recent)
                consistency = len(recent) / max(len(events), 1)
                confidence = min(
                    0.4 + 0.1 * (len(recent) - min_events) + 0.2 * consistency,
                    0.95,
                )

                patterns.append(FlowPattern(
                    id=str(uuid.uuid4()),
                    pattern_type="repeat_buyer",
                    tickers=[ticker],
                    confidence=round(confidence, 3),
                    timeframe=self._classify_timeframe(recent),
                    event_count=len(recent),
                    details={
                        "direction": "bearish",
                        "total_premium": round(total_premium, 2),
                        "event_types": self._count_types(recent),
                    },
                    detected_at=ts,
                ))

        return patterns

    def _detect_accumulation_sequence(
        self,
        ticker: str,
        events: List[FlowEvent],
        ts: float,
    ) -> List[FlowPattern]:
        """Detect gradual position building over time.

        Accumulation sequences show increasing premium/volume in the same
        direction, spread over multiple days — building a large position
        without moving the market.
        """
        patterns: List[FlowPattern] = []
        window = self._config.accumulation_window_s
        min_events = self._config.accumulation_min_events

        recent = [e for e in events if ts - e.timestamp <= window]
        if len(recent) < min_events:
            return patterns

        # Check for increasing premium trend in dominant direction
        bullish = [e for e in recent if e.direction == "bullish"]
        bearish = [e for e in recent if e.direction == "bearish"]

        for direction, dir_events in [("bullish", bullish), ("bearish", bearish)]:
            if len(dir_events) < min_events:
                continue

            # Sort by time and check for increasing premiums
            sorted_events = sorted(dir_events, key=lambda e: e.timestamp)
            premiums = [e.premium for e in sorted_events]

            # Check if premiums are generally increasing (allow some variance)
            increases = sum(
                1 for i in range(1, len(premiums)) if premiums[i] >= premiums[i - 1] * 0.8
            )
            increase_ratio = increases / max(len(premiums) - 1, 1)

            if increase_ratio < 0.5:
                continue  # Not accumulating

            # Time spread — must be over multiple days
            time_span = sorted_events[-1].timestamp - sorted_events[0].timestamp
            if time_span < 3600.0 * 12:  # Less than 12 hours = not gradual
                continue

            total_premium = sum(e.premium for e in sorted_events)
            confidence = min(
                0.4 + 0.15 * increase_ratio + 0.1 * min(len(sorted_events) / 10.0, 1.0),
                0.95,
            )

            patterns.append(FlowPattern(
                id=str(uuid.uuid4()),
                pattern_type="accumulation_sequence",
                tickers=[ticker],
                confidence=round(confidence, 3),
                timeframe=self._classify_timeframe(sorted_events),
                event_count=len(sorted_events),
                details={
                    "direction": direction,
                    "total_premium": round(total_premium, 2),
                    "increase_ratio": round(increase_ratio, 3),
                    "time_span_hours": round(time_span / 3600.0, 1),
                },
                detected_at=ts,
            ))

        return patterns

    def _detect_hedging(
        self,
        ticker: str,
        events: List[FlowEvent],
        ts: float,
    ) -> List[FlowPattern]:
        """Detect hedging: simultaneous bullish + bearish flow.

        Hedging patterns show large positions in both directions within
        a short time window — indicates protective positioning rather
        than directional betting.
        """
        patterns: List[FlowPattern] = []
        window = self._config.hedging_window_s

        recent = [e for e in events if ts - e.timestamp <= window]
        if len(recent) < 2:
            return patterns

        bullish = [e for e in recent if e.direction == "bullish"]
        bearish = [e for e in recent if e.direction == "bearish"]

        if not bullish or not bearish:
            return patterns

        bull_premium = sum(e.premium for e in bullish)
        bear_premium = sum(e.premium for e in bearish)

        # Hedging: both sides must be significant
        min_side = min(bull_premium, bear_premium)
        max_side = max(bull_premium, bear_premium)

        if min_side < 10_000:  # At least $10k on smaller side
            return patterns

        # Balance ratio: closer to 1.0 = more balanced hedge
        balance = min_side / max_side if max_side > 0 else 0
        if balance < 0.2:  # Too one-sided to be a hedge
            return patterns

        confidence = min(0.4 + 0.3 * balance + 0.1 * min(len(recent) / 6.0, 1.0), 0.95)

        patterns.append(FlowPattern(
            id=str(uuid.uuid4()),
            pattern_type="hedging",
            tickers=[ticker],
            confidence=round(confidence, 3),
            timeframe=self._classify_timeframe(recent),
            event_count=len(recent),
            details={
                "bull_premium": round(bull_premium, 2),
                "bear_premium": round(bear_premium, 2),
                "balance_ratio": round(balance, 3),
                "bullish_events": len(bullish),
                "bearish_events": len(bearish),
            },
            detected_at=ts,
        ))

        return patterns

    def _detect_rolling(
        self,
        ticker: str,
        events: List[FlowEvent],
        ts: float,
    ) -> List[FlowPattern]:
        """Detect position rolling: closing near-term, opening far-term.

        Rolling patterns show distribution (selling) followed by accumulation
        (buying) within a window — maintaining directional exposure while
        extending time horizon.
        """
        patterns: List[FlowPattern] = []
        window = self._config.rolling_window_s

        recent = [e for e in events if ts - e.timestamp <= window]
        if len(recent) < 2:
            return patterns

        # Look for distribution followed by accumulation (or vice versa)
        dist_events = [e for e in recent if e.flow_type == "distribution"]
        acc_events = [e for e in recent if e.flow_type == "accumulation"]

        if not dist_events or not acc_events:
            return patterns

        # Distribution should come before accumulation
        avg_dist_time = sum(e.timestamp for e in dist_events) / len(dist_events)
        avg_acc_time = sum(e.timestamp for e in acc_events) / len(acc_events)

        if avg_acc_time <= avg_dist_time:
            return patterns  # Wrong order

        dist_premium = sum(e.premium for e in dist_events)
        acc_premium = sum(e.premium for e in acc_events)

        # Should be roughly similar magnitude
        if dist_premium <= 0 or acc_premium <= 0:
            return patterns
        ratio = min(dist_premium, acc_premium) / max(dist_premium, acc_premium)
        if ratio < 0.3:
            return patterns

        confidence = min(0.5 + 0.2 * ratio + 0.1 * min(len(recent) / 6.0, 1.0), 0.95)

        patterns.append(FlowPattern(
            id=str(uuid.uuid4()),
            pattern_type="rolling",
            tickers=[ticker],
            confidence=round(confidence, 3),
            timeframe=self._classify_timeframe(recent),
            event_count=len(recent),
            details={
                "dist_premium": round(dist_premium, 2),
                "acc_premium": round(acc_premium, 2),
                "size_ratio": round(ratio, 3),
                "time_gap_hours": round((avg_acc_time - avg_dist_time) / 3600.0, 1),
            },
            detected_at=ts,
        ))

        return patterns

    # ── Cross-Ticker Patterns ───────────────────────────

    def _detect_cross_ticker(
        self,
        events: List[FlowEvent],
        ts: float,
    ) -> List[FlowPattern]:
        """Detect correlated flow across related tickers.

        When multiple tickers in the same sector show similar flow
        direction within a time window, it indicates sector-level
        institutional positioning.
        """
        patterns: List[FlowPattern] = []
        window = self._config.cross_ticker_window_s
        min_count = self._config.cross_ticker_min_count

        recent = [e for e in events if ts - e.timestamp <= window]
        if len(recent) < min_count:
            return patterns

        # Group by sector
        sector_events: Dict[str, List[FlowEvent]] = defaultdict(list)
        for event in recent:
            sector = _TICKER_SECTOR.get(event.ticker)
            if sector:
                sector_events[sector].append(event)

        for sector, sec_events in sector_events.items():
            # Count unique tickers
            tickers = list({e.ticker for e in sec_events})
            if len(tickers) < min_count:
                continue

            # Check directional alignment
            bullish = sum(1 for e in sec_events if e.direction == "bullish")
            bearish = sum(1 for e in sec_events if e.direction == "bearish")
            total = bullish + bearish
            if total == 0:
                continue

            dominant_ratio = max(bullish, bearish) / total
            if dominant_ratio < 0.65:
                continue  # Not aligned enough

            dominant_dir = "bullish" if bullish > bearish else "bearish"
            total_premium = sum(e.premium for e in sec_events)

            confidence = min(
                0.4 + 0.2 * (dominant_ratio - 0.5) * 2 + 0.1 * min(len(tickers) / 5.0, 1.0),
                0.95,
            )

            patterns.append(FlowPattern(
                id=str(uuid.uuid4()),
                pattern_type="cross_ticker",
                tickers=sorted(tickers),
                confidence=round(confidence, 3),
                timeframe=self._classify_timeframe(sec_events),
                event_count=len(sec_events),
                details={
                    "sector": sector,
                    "direction": dominant_dir,
                    "alignment_ratio": round(dominant_ratio, 3),
                    "total_premium": round(total_premium, 2),
                    "unique_tickers": len(tickers),
                },
                detected_at=ts,
            ))

        return patterns

    # ── Helpers ─────────────────────────────────────────

    def _group_by_ticker(
        self,
        events: List[FlowEvent],
    ) -> Dict[str, List[FlowEvent]]:
        """Group events by ticker."""
        grouped: Dict[str, List[FlowEvent]] = defaultdict(list)
        for e in events:
            grouped[e.ticker].append(e)
        return dict(grouped)

    def _classify_timeframe(self, events: List[FlowEvent]) -> str:
        """Classify the timeframe of a pattern from event timestamps."""
        if not events:
            return "1h"
        timestamps = [e.timestamp for e in events]
        span = max(timestamps) - min(timestamps)
        if span < 3600 * 4:
            return "4h"
        elif span < 86400:
            return "1d"
        elif span < 86400 * 7:
            return "1w"
        return "1m"

    def _count_types(self, events: List[FlowEvent]) -> Dict[str, int]:
        """Count flow event types."""
        counts: Dict[str, int] = defaultdict(int)
        for e in events:
            counts[e.flow_type] += 1
        return dict(counts)
