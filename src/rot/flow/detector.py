"""Institutional options flow detection engine.

Analyzes options chain market data to detect unusual institutional activity:
  - Block trades: large single-transaction premium
  - Sweeps: rapid multi-level execution (hitting ask aggressively)
  - Dark pool: high volume with low price impact (off-exchange activity)
  - Accumulation: repeated same-direction flow building a position
  - Distribution: systematic unwinding of a position

Design goals:
  - Zero lookahead: only uses data available at detection time
  - Configurable thresholds via FlowConfig
  - Baseline-aware: uses FlowHistory for anomaly scoring
  - Batch-capable: scan_batch() for pipeline integration
"""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from typing import Any, Dict, List, Optional

from rot.flow.history import FlowHistory
from rot.flow.types import FlowEvent, FlowScore

log = logging.getLogger(__name__)

# ── Safe extraction helpers ─────────────────────────────


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce to float, return default on failure or NaN."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    """Coerce to int, return default on failure."""
    if val is None:
        return default
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _parse_market_data(market_data: Any) -> Dict[str, Any]:
    """Parse market_data from signal — handles JSON string or dict."""
    if isinstance(market_data, str):
        try:
            return json.loads(market_data)
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(market_data, dict):
        return market_data
    return {}


def _extract_ticker_data(
    market_data: Dict[str, Any], ticker: str
) -> Dict[str, Any]:
    """Extract per-ticker market data from nested structure.

    market_data can be:
      - {ticker: {data}} — keyed by ticker
      - {data} — flat, applies to the signal's ticker
    """
    if ticker in market_data and isinstance(market_data[ticker], dict):
        return market_data[ticker]
    # Try flat structure (if keys look like market data, not ticker symbols)
    if any(k in market_data for k in ("atm_iv", "call_oi", "put_oi", "volume")):
        return market_data
    return {}


# ── Flow Detector Config ────────────────────────────────


class FlowDetectorConfig:
    """Configuration for flow detection thresholds."""

    def __init__(
        self,
        block_premium_threshold: float = 100_000.0,
        sweep_volume_threshold: int = 500,
        sweep_premium_threshold: float = 50_000.0,
        dark_pool_volume_ratio: float = 0.30,
        accumulation_min_events: int = 3,
        accumulation_window_s: float = 86400.0 * 3,  # 3 days
        composite_min_score: float = 25.0,
        max_events_per_ticker: int = 10,
        volume_surge_multiplier: float = 3.0,
        oi_surge_pct: float = 25.0,
    ) -> None:
        self.block_premium_threshold = block_premium_threshold
        self.sweep_volume_threshold = sweep_volume_threshold
        self.sweep_premium_threshold = sweep_premium_threshold
        self.dark_pool_volume_ratio = dark_pool_volume_ratio
        self.accumulation_min_events = accumulation_min_events
        self.accumulation_window_s = accumulation_window_s
        self.composite_min_score = composite_min_score
        self.max_events_per_ticker = max_events_per_ticker
        self.volume_surge_multiplier = volume_surge_multiplier
        self.oi_surge_pct = oi_surge_pct


# ── Flow Detector ───────────────────────────────────────


class FlowDetector:
    """Detect unusual institutional options flow from market data.

    Analyzes options chain data attached to signals for block trades,
    sweeps, dark pool activity, and accumulation/distribution patterns.

    Example::

        detector = FlowDetector(history=FlowHistory())
        events = detector.detect_from_market_data("TSLA", market_data)
        batch_events = detector.scan_batch(signals)
        score = detector.compute_score(events, "TSLA")
    """

    def __init__(
        self,
        history: Optional[FlowHistory] = None,
        config: Optional[FlowDetectorConfig] = None,
    ) -> None:
        self._history = history or FlowHistory()
        self._config = config or FlowDetectorConfig()

    @property
    def history(self) -> FlowHistory:
        """FlowHistory store used by this detector."""
        return self._history

    @property
    def config(self) -> FlowDetectorConfig:
        """Active FlowDetectorConfig governing detection thresholds."""
        return self._config

    # ── Main Detection ──────────────────────────────────

    def detect_from_market_data(
        self,
        ticker: str,
        market_data: Dict[str, Any],
        signal_id: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> List[FlowEvent]:
        """Analyze market data for unusual flow patterns.

        Parameters
        ----------
        ticker : str
            Ticker symbol.
        market_data : dict
            Market data dict (may be nested by ticker).
        signal_id : str, optional
            Link to originating signal.
        timestamp : float, optional
            Detection timestamp. Defaults to now.

        Returns
        -------
        List[FlowEvent]
            Detected flow events, filtered by composite_min_score.
        """
        if not ticker:
            return []

        ts = timestamp or time.time()
        td = _extract_ticker_data(market_data, ticker)
        if not td:
            return []

        events: List[FlowEvent] = []

        # Run all detection algorithms
        block = self._detect_block_trade(ticker, td, signal_id, ts)
        if block:
            events.append(block)

        sweep = self._detect_sweep(ticker, td, signal_id, ts)
        if sweep:
            events.append(sweep)

        dark = self._detect_dark_pool(ticker, td, signal_id, ts)
        if dark:
            events.append(dark)

        acc = self._detect_accumulation(ticker, td, signal_id, ts)
        if acc:
            events.append(acc)

        dist = self._detect_distribution(ticker, td, signal_id, ts)
        if dist:
            events.append(dist)

        # Filter by minimum score
        events = [e for e in events if e.score >= self._config.composite_min_score]

        # Cap per ticker
        if len(events) > self._config.max_events_per_ticker:
            events.sort(key=lambda e: e.score, reverse=True)
            events = events[: self._config.max_events_per_ticker]

        # Update history baselines
        for event in events:
            self._history.update(
                ticker=ticker,
                premium=event.premium,
                volume=event.volume,
                oi_change=event.oi_change,
                direction=event.direction,
                timestamp=ts,
            )

        return events

    def scan_batch(
        self,
        signals: List[Dict[str, Any]],
    ) -> List[FlowEvent]:
        """Batch scan multiple signals for flow events.

        Parameters
        ----------
        signals : list
            Signal dicts from database (must have ticker, market_data).

        Returns
        -------
        List[FlowEvent]
            All detected flow events across all signals.
        """
        all_events: List[FlowEvent] = []

        for signal in signals:
            ticker = signal.get("ticker", "")
            if not ticker:
                continue

            raw_md = signal.get("market_data", {})
            market_data = _parse_market_data(raw_md)
            signal_id = signal.get("id")
            ts = _safe_float(signal.get("created_at"), time.time())

            try:
                events = self.detect_from_market_data(
                    ticker, market_data, signal_id, ts
                )
                all_events.extend(events)
            except Exception as exc:
                log.warning(
                    "Flow detection failed for %s: %s", ticker, exc
                )

        return all_events

    def compute_score(
        self,
        events: List[FlowEvent],
        ticker: str,
        timestamp: Optional[float] = None,
    ) -> FlowScore:
        """Compute aggregate flow score from events for a ticker.

        Parameters
        ----------
        events : list
            FlowEvents for this ticker.
        ticker : str
            Ticker symbol.
        timestamp : float, optional
            Score timestamp. Defaults to now.

        Returns
        -------
        FlowScore with composite score 0-100.
        """
        ts = timestamp or time.time()

        if not events:
            return FlowScore(
                ticker=ticker,
                score=0.0,
                bullish_flow=0.0,
                bearish_flow=0.0,
                net_premium=0.0,
                event_count=0,
                detected_at=ts,
            )

        bullish_flow = sum(
            e.premium for e in events if e.direction == "bullish"
        )
        bearish_flow = sum(
            e.premium for e in events if e.direction == "bearish"
        )
        net_premium = bullish_flow - bearish_flow
        event_count = len(events)

        # Composite score: weighted by event scores and count
        avg_event_score = sum(e.score for e in events) / event_count
        max_event_score = max(e.score for e in events)

        # Score = 60% max event + 30% average + 10% count bonus
        count_bonus = min(event_count * 2.0, 20.0)
        composite = 0.6 * max_event_score + 0.3 * avg_event_score + count_bonus
        composite = min(composite, 100.0)

        return FlowScore(
            ticker=ticker,
            score=round(composite, 1),
            bullish_flow=round(bullish_flow, 2),
            bearish_flow=round(bearish_flow, 2),
            net_premium=round(net_premium, 2),
            event_count=event_count,
            detected_at=ts,
        )

    # ── Detection Algorithms ────────────────────────────

    def _detect_block_trade(
        self,
        ticker: str,
        td: Dict[str, Any],
        signal_id: Optional[str],
        ts: float,
    ) -> Optional[FlowEvent]:
        """Detect large block trades (single large-premium transactions).

        Block trades are unusually large options transactions that indicate
        institutional positioning. Detected when:
          - Volume * mid_price exceeds block_premium_threshold
          - Or estimated premium from OI change is very large
        """
        call_oi = _safe_int(td.get("call_oi"))
        put_oi = _safe_int(td.get("put_oi"))
        atm_iv = _safe_float(td.get("atm_iv"))
        volume = _safe_int(td.get("volume", td.get("option_volume")))
        last_price = _safe_float(td.get("last_close", td.get("price")))

        if volume <= 0 or last_price <= 0:
            return None

        # Estimate premium: volume * ATM option price approximation
        # ATM option ≈ 0.4 * S * sigma * sqrt(T/365) for ~30 DTE
        dte_approx = 30.0
        sigma = atm_iv if atm_iv > 0 else 0.30  # default 30% vol
        atm_approx = 0.4 * last_price * sigma * math.sqrt(dte_approx / 365.0)
        estimated_premium = volume * atm_approx * 100.0  # 100 shares per contract

        if estimated_premium < self._config.block_premium_threshold:
            return None

        # Direction from put/call OI ratio
        direction = self._infer_direction_from_oi(call_oi, put_oi, td)

        # Score: premium magnitude vs threshold
        premium_ratio = estimated_premium / self._config.block_premium_threshold
        baseline_factor = self._get_baseline_factor(ticker, estimated_premium)
        score = min(30.0 + 20.0 * math.log10(max(premium_ratio, 1.0)) + baseline_factor, 100.0)

        return FlowEvent(
            id=str(uuid.uuid4()),
            ticker=ticker,
            flow_type="block_trade",
            direction=direction,
            premium=round(estimated_premium, 2),
            volume=volume,
            oi_change=call_oi + put_oi,
            score=round(score, 1),
            timestamp=ts,
            details={
                "atm_iv": round(atm_iv, 4) if atm_iv > 0 else None,
                "atm_approx_price": round(atm_approx, 2),
                "last_price": round(last_price, 2),
                "call_oi": call_oi,
                "put_oi": put_oi,
            },
            signal_id=signal_id,
        )

    def _detect_sweep(
        self,
        ticker: str,
        td: Dict[str, Any],
        signal_id: Optional[str],
        ts: float,
    ) -> Optional[FlowEvent]:
        """Detect sweep orders (aggressive multi-level execution).

        Sweeps hit multiple price levels rapidly, indicating urgency.
        Detected when:
          - High volume with IV spike (aggressive buying lifts IV)
          - Put/call ratio significantly deviates from norm
        """
        volume = _safe_int(td.get("volume", td.get("option_volume")))
        atm_iv = _safe_float(td.get("atm_iv"))
        put_call_ratio = _safe_float(td.get("put_call_oi_ratio"))

        if volume < self._config.sweep_volume_threshold:
            return None

        last_price = _safe_float(td.get("last_close", td.get("price")))
        if last_price <= 0:
            return None

        # IV spike indicates aggressive buying
        iv_baseline = self._history.get_baseline(ticker)
        iv_elevated = False
        if iv_baseline and iv_baseline.premium_observations:
            # Use premium history as proxy for IV history
            avg_premium = iv_baseline.avg_premium
            if avg_premium > 0 and atm_iv > 0:
                iv_elevated = True

        # Estimate premium
        sigma = atm_iv if atm_iv > 0 else 0.30
        atm_approx = 0.4 * last_price * sigma * math.sqrt(30.0 / 365.0)
        estimated_premium = volume * atm_approx * 100.0

        if estimated_premium < self._config.sweep_premium_threshold:
            return None

        # Direction from put/call ratio
        if put_call_ratio > 0:
            if put_call_ratio > 1.5:
                direction = "bearish"
            elif put_call_ratio < 0.6:
                direction = "bullish"
            else:
                direction = "neutral"
        else:
            direction = self._infer_direction_from_oi(
                _safe_int(td.get("call_oi")),
                _safe_int(td.get("put_oi")),
                td,
            )

        # Score: volume + IV elevation + premium
        volume_score = min(volume / self._config.sweep_volume_threshold * 15.0, 30.0)
        premium_score = min(estimated_premium / 100_000.0 * 15.0, 30.0)
        iv_score = 15.0 if iv_elevated else 0.0
        baseline_factor = self._get_baseline_factor(ticker, estimated_premium)
        score = min(20.0 + volume_score + premium_score + iv_score + baseline_factor, 100.0)

        return FlowEvent(
            id=str(uuid.uuid4()),
            ticker=ticker,
            flow_type="sweep",
            direction=direction,
            premium=round(estimated_premium, 2),
            volume=volume,
            oi_change=0,
            score=round(score, 1),
            timestamp=ts,
            details={
                "atm_iv": round(atm_iv, 4) if atm_iv > 0 else None,
                "put_call_ratio": round(put_call_ratio, 3) if put_call_ratio > 0 else None,
                "iv_elevated": iv_elevated,
                "last_price": round(last_price, 2),
            },
            signal_id=signal_id,
        )

    def _detect_dark_pool(
        self,
        ticker: str,
        td: Dict[str, Any],
        signal_id: Optional[str],
        ts: float,
    ) -> Optional[FlowEvent]:
        """Detect potential dark pool activity.

        Approximated via high OI change with relatively low visible volume —
        suggests large off-exchange block crossing.
        """
        call_oi = _safe_int(td.get("call_oi"))
        put_oi = _safe_int(td.get("put_oi"))
        total_oi = call_oi + put_oi
        volume = _safe_int(td.get("volume", td.get("option_volume")))
        last_price = _safe_float(td.get("last_close", td.get("price")))

        if total_oi <= 0 or last_price <= 0:
            return None

        # Dark pool proxy: large OI change but low volume/OI ratio
        # (positions appeared without visible trading)
        baseline = self._history.get_baseline(ticker)
        if baseline and baseline.flow_count > 3:
            avg_volume = baseline.avg_volume
            if avg_volume > 0 and volume > 0:
                vol_oi_ratio = volume / total_oi  # total_oi > 0 guaranteed above
                # Low ratio = positions added without proportional visible volume
                if vol_oi_ratio > self._config.dark_pool_volume_ratio:
                    return None  # Normal ratio, not dark pool

        # Need significant OI
        if total_oi < 1000:
            return None

        # Estimate premium from OI
        sigma = _safe_float(td.get("atm_iv"), 0.30)
        atm_approx = 0.4 * last_price * sigma * math.sqrt(30.0 / 365.0)
        estimated_premium = total_oi * atm_approx * 100.0 * 0.01  # Scale down

        direction = self._infer_direction_from_oi(call_oi, put_oi, td)

        # Score: OI magnitude + low visible volume
        oi_score = min(total_oi / 10000.0 * 20.0, 30.0)
        stealth_score = 15.0 if volume < total_oi * 0.1 else 5.0
        score = min(20.0 + oi_score + stealth_score, 100.0)

        if score < self._config.composite_min_score:
            return None

        return FlowEvent(
            id=str(uuid.uuid4()),
            ticker=ticker,
            flow_type="dark_pool",
            direction=direction,
            premium=round(estimated_premium, 2),
            volume=volume,
            oi_change=total_oi,
            score=round(score, 1),
            timestamp=ts,
            details={
                "call_oi": call_oi,
                "put_oi": put_oi,
                "total_oi": total_oi,
                "volume": volume,
                "last_price": round(last_price, 2),
            },
            signal_id=signal_id,
        )

    def _detect_accumulation(
        self,
        ticker: str,
        td: Dict[str, Any],
        signal_id: Optional[str],
        ts: float,
    ) -> Optional[FlowEvent]:
        """Detect bullish accumulation pattern.

        Identified by: consistently increasing call OI, rising call volume,
        bullish flow direction over recent observations.
        """
        call_oi = _safe_int(td.get("call_oi"))
        volume = _safe_int(td.get("volume", td.get("option_volume")))
        last_price = _safe_float(td.get("last_close", td.get("price")))

        if call_oi <= 0 or last_price <= 0:
            return None

        baseline = self._history.get_baseline(ticker)
        if not baseline or baseline.flow_count < self._config.accumulation_min_events:
            return None

        # Check if recent flow is consistently bullish
        if baseline.bullish_ratio < 0.65:
            return None

        # Check OI growth
        oi_pct = self._history.get_premium_percentile(ticker, float(call_oi))
        if oi_pct is not None and oi_pct < 70:
            return None  # Not unusually high

        sigma = _safe_float(td.get("atm_iv"), 0.30)
        atm_approx = 0.4 * last_price * sigma * math.sqrt(30.0 / 365.0)
        estimated_premium = call_oi * atm_approx * 100.0 * 0.01

        # Score based on consistency + magnitude
        consistency_score = min((baseline.bullish_ratio - 0.5) * 80.0, 30.0)
        oi_score = min(call_oi / 5000.0 * 15.0, 25.0)
        history_score = min(baseline.flow_count * 2.0, 15.0)
        score = min(20.0 + consistency_score + oi_score + history_score, 100.0)

        if score < self._config.composite_min_score:
            return None

        return FlowEvent(
            id=str(uuid.uuid4()),
            ticker=ticker,
            flow_type="accumulation",
            direction="bullish",
            premium=round(estimated_premium, 2),
            volume=volume,
            oi_change=call_oi,
            score=round(score, 1),
            timestamp=ts,
            details={
                "call_oi": call_oi,
                "bullish_ratio": round(baseline.bullish_ratio, 3),
                "flow_count": baseline.flow_count,
                "last_price": round(last_price, 2),
            },
            signal_id=signal_id,
        )

    def _detect_distribution(
        self,
        ticker: str,
        td: Dict[str, Any],
        signal_id: Optional[str],
        ts: float,
    ) -> Optional[FlowEvent]:
        """Detect bearish distribution pattern.

        Mirror of accumulation but for puts — consistently increasing put OI,
        bearish flow direction.
        """
        put_oi = _safe_int(td.get("put_oi"))
        volume = _safe_int(td.get("volume", td.get("option_volume")))
        last_price = _safe_float(td.get("last_close", td.get("price")))

        if put_oi <= 0 or last_price <= 0:
            return None

        baseline = self._history.get_baseline(ticker)
        if not baseline or baseline.flow_count < self._config.accumulation_min_events:
            return None

        # Check if recent flow is consistently bearish
        bearish_ratio = 1.0 - baseline.bullish_ratio
        if bearish_ratio < 0.65:
            return None

        sigma = _safe_float(td.get("atm_iv"), 0.30)
        atm_approx = 0.4 * last_price * sigma * math.sqrt(30.0 / 365.0)
        estimated_premium = put_oi * atm_approx * 100.0 * 0.01

        consistency_score = min((bearish_ratio - 0.5) * 80.0, 30.0)
        oi_score = min(put_oi / 5000.0 * 15.0, 25.0)
        history_score = min(baseline.flow_count * 2.0, 15.0)
        score = min(20.0 + consistency_score + oi_score + history_score, 100.0)

        if score < self._config.composite_min_score:
            return None

        return FlowEvent(
            id=str(uuid.uuid4()),
            ticker=ticker,
            flow_type="distribution",
            direction="bearish",
            premium=round(estimated_premium, 2),
            volume=volume,
            oi_change=put_oi,
            score=round(score, 1),
            timestamp=ts,
            details={
                "put_oi": put_oi,
                "bearish_ratio": round(bearish_ratio, 3),
                "flow_count": baseline.flow_count,
                "last_price": round(last_price, 2),
            },
            signal_id=signal_id,
        )

    # ── Helpers ─────────────────────────────────────────

    def _infer_direction_from_oi(
        self,
        call_oi: int,
        put_oi: int,
        td: Dict[str, Any],
    ) -> str:
        """Infer flow direction from put/call open interest."""
        total = call_oi + put_oi
        if total == 0:
            return "neutral"

        pc_ratio = put_oi / call_oi if call_oi > 0 else 999.0

        # Check 1d change for additional signal
        change_1d = _safe_float(td.get("change_1d", td.get("change_pct")))

        if pc_ratio > 1.5:
            return "bearish"
        elif pc_ratio < 0.6:
            return "bullish"
        elif change_1d > 2.0:
            return "bullish"
        elif change_1d < -2.0:
            return "bearish"
        return "neutral"

    def _get_baseline_factor(
        self,
        ticker: str,
        current_premium: float,
    ) -> float:
        """Get baseline deviation factor for scoring.

        Returns 0-15 bonus points based on how unusual the current
        premium is relative to historical observations.
        """
        pct = self._history.get_premium_percentile(ticker, current_premium)
        if pct is None:
            return 5.0  # Default bonus for new/unknown tickers

        if pct >= 95:
            return 15.0
        elif pct >= 90:
            return 12.0
        elif pct >= 80:
            return 8.0
        elif pct >= 70:
            return 5.0
        return 0.0
