"""Unusual activity detection engine.

Scans signal market data for IV spikes, volume surges, OI surges,
put/call skew shifts, and sweep-like patterns. Produces scored events.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from rot.unusual.config import UnusualDetectorConfig
from rot.unusual.history import UnusualHistory
from rot.unusual.types import UnusualEvent, UnusualScore, UnusualSummary


# Human-readable flag names for each event type
_FLAG_NAMES = {
    "iv_spike": "High IV",
    "volume_surge": "Volume Spike",
    "oi_surge": "OI Surge",
    "skew_shift": "Extreme P/C Ratio",
    "sweep": "Sweep Activity",
}


class UnusualDetector:
    """Detects unusual options activity from signal market data."""

    def __init__(
        self,
        history: Optional[UnusualHistory] = None,
        config: Optional[UnusualDetectorConfig] = None,
    ) -> None:
        self._history = history or UnusualHistory()
        self._config = config or UnusualDetectorConfig()

    @property
    def history(self) -> UnusualHistory:
        return self._history

    @property
    def config(self) -> UnusualDetectorConfig:
        return self._config

    def scan_signal(self, signal: Dict[str, Any]) -> List[UnusualEvent]:
        """Scan a single signal's market data for unusual activity.

        Parameters
        ----------
        signal:
            Signal dict with at minimum: ticker, market_data (dict or JSON-parsed),
            id (optional signal_id), created_at (optional timestamp).

        Returns
        -------
        List of UnusualEvent instances (may be empty).
        """
        ticker = signal.get("ticker", "")
        if not ticker:
            return []

        market_data = signal.get("market_data", {})
        if isinstance(market_data, str):
            import json
            try:
                market_data = json.loads(market_data)
            except (json.JSONDecodeError, TypeError):
                return []
        if not isinstance(market_data, dict):
            return []

        # Extract ticker-specific market data
        ticker_data = market_data.get(ticker, market_data)
        if not isinstance(ticker_data, dict):
            return []

        signal_id = signal.get("id") or signal.get("signal_id")
        now = signal.get("created_at") or time.time()

        # Extract raw values (handle both naming conventions)
        iv = _get_float(ticker_data, "atm_iv", "impliedVolatility")
        call_oi = _get_float(ticker_data, "call_oi", "callOpenInterest")
        put_oi = _get_float(ticker_data, "put_oi", "putOpenInterest")
        total_oi = (call_oi or 0) + (put_oi or 0)
        pc_ratio = _get_float(ticker_data, "pc_ratio", "putCallRatio")
        volume = _get_float(ticker_data, "volume")
        avg_volume = _get_float(ticker_data, "avg_volume", "averageVolume")

        # Update history baselines
        self._history.update(
            ticker=ticker,
            iv=iv,
            volume=volume,
            oi=total_oi if total_oi > 0 else None,
            pc_ratio=pc_ratio,
        )

        events: List[UnusualEvent] = []
        cfg = self._config

        # --- 1. IV Spike Detection ---
        if iv is not None and iv > 0:
            iv_rank = self._history.get_iv_rank(ticker, iv)
            if iv_rank is not None and iv_rank >= cfg.iv_rank_threshold:
                # Score: linear scale from threshold to 100
                raw = (iv_rank - cfg.iv_rank_threshold) / (100.0 - cfg.iv_rank_threshold)
                score = min(100.0, raw * cfg.iv_weight * (100.0 / cfg.total_weight()) * 4)
                events.append(UnusualEvent(
                    ticker=ticker,
                    event_type="iv_spike",
                    score=round(min(score, 100.0), 1),
                    details={
                        "atm_iv": round(iv, 4),
                        "iv_rank": round(iv_rank, 1),
                        "threshold": cfg.iv_rank_threshold,
                    },
                    detected_at=now,
                    signal_id=signal_id,
                ))

        # --- 2. Volume Surge Detection ---
        if volume is not None and volume > 0:
            vol_ratio = self._history.get_volume_ratio(ticker, volume)
            # Also check vs avg_volume from market data as fallback
            if vol_ratio is None and avg_volume and avg_volume > 0:
                vol_ratio = volume / avg_volume
            if vol_ratio is not None and vol_ratio >= cfg.volume_surge_multiplier:
                raw = (vol_ratio - cfg.volume_surge_multiplier) / cfg.volume_surge_multiplier
                score = min(100.0, (0.5 + raw * 0.5) * cfg.volume_weight * (100.0 / cfg.total_weight()) * 4)
                events.append(UnusualEvent(
                    ticker=ticker,
                    event_type="volume_surge",
                    score=round(min(score, 100.0), 1),
                    details={
                        "volume": volume,
                        "avg_volume": avg_volume,
                        "volume_ratio": round(vol_ratio, 2),
                        "threshold": cfg.volume_surge_multiplier,
                    },
                    detected_at=now,
                    signal_id=signal_id,
                ))

        # --- 3. OI Surge Detection ---
        if total_oi > 0:
            oi_change = self._history.get_oi_change_pct(ticker, total_oi)
            if oi_change is not None and oi_change >= cfg.oi_surge_pct:
                raw = (oi_change - cfg.oi_surge_pct) / max(cfg.oi_surge_pct, 1.0)
                score = min(100.0, (0.5 + raw * 0.5) * cfg.oi_weight * (100.0 / cfg.total_weight()) * 4)
                events.append(UnusualEvent(
                    ticker=ticker,
                    event_type="oi_surge",
                    score=round(min(score, 100.0), 1),
                    details={
                        "total_oi": total_oi,
                        "call_oi": call_oi,
                        "put_oi": put_oi,
                        "oi_change_pct": round(oi_change, 2),
                        "threshold": cfg.oi_surge_pct,
                    },
                    detected_at=now,
                    signal_id=signal_id,
                ))

        # --- 4. Put/Call Skew Shift ---
        if pc_ratio is not None and pc_ratio > 0:
            pc_zscore = self._history.get_pc_ratio_zscore(ticker, pc_ratio)
            abs_zscore = abs(pc_zscore) if pc_zscore is not None else 0
            if pc_zscore is not None and abs_zscore >= cfg.skew_std_threshold:
                raw = (abs_zscore - cfg.skew_std_threshold) / cfg.skew_std_threshold
                score = min(100.0, (0.5 + raw * 0.5) * cfg.skew_weight * (100.0 / cfg.total_weight()) * 4)
                direction = "bearish_skew" if pc_ratio > 1.5 else "bullish_skew"
                events.append(UnusualEvent(
                    ticker=ticker,
                    event_type="skew_shift",
                    score=round(min(score, 100.0), 1),
                    details={
                        "pc_ratio": round(pc_ratio, 3),
                        "pc_zscore": round(pc_zscore, 2),
                        "direction": direction,
                        "threshold_std": cfg.skew_std_threshold,
                    },
                    detected_at=now,
                    signal_id=signal_id,
                ))

        # --- 5. Sweep Detection (approximation) ---
        # High vol/OI ratio suggests aggressive near-term positioning
        if volume and total_oi and total_oi > 0:
            vol_oi = volume / total_oi
            if vol_oi >= cfg.sweep_vol_oi_threshold:
                raw = (vol_oi - cfg.sweep_vol_oi_threshold) / cfg.sweep_vol_oi_threshold
                score = min(100.0, (0.5 + raw * 0.5) * cfg.sweep_weight * (100.0 / cfg.total_weight()) * 4)
                events.append(UnusualEvent(
                    ticker=ticker,
                    event_type="sweep",
                    score=round(min(score, 100.0), 1),
                    details={
                        "vol_oi_ratio": round(vol_oi, 2),
                        "volume": volume,
                        "total_oi": total_oi,
                        "threshold": cfg.sweep_vol_oi_threshold,
                    },
                    detected_at=now,
                    signal_id=signal_id,
                ))

        # Cap events per signal
        if len(events) > self._config.max_events_per_signal:
            events.sort(key=lambda e: e.score, reverse=True)
            events = events[: self._config.max_events_per_signal]

        return events

    def scan_batch(self, signals: List[Dict[str, Any]]) -> List[UnusualEvent]:
        """Scan multiple signals for unusual activity."""
        all_events: List[UnusualEvent] = []
        for signal in signals:
            all_events.extend(self.scan_signal(signal))
        return all_events

    def compute_score(self, events: List[UnusualEvent]) -> UnusualScore:
        """Compute composite unusual score from a list of events.

        The composite score is the weighted sum of per-type max scores,
        normalized to 0-100.
        """
        if not events:
            return UnusualScore(
                composite_score=0.0,
                flags=[],
                component_scores={},
                events=[],
            )

        cfg = self._config
        total_weight = cfg.total_weight()

        # Per-type max score
        type_max: Dict[str, float] = {}
        for e in events:
            if e.event_type not in type_max or e.score > type_max[e.event_type]:
                type_max[e.event_type] = e.score

        # Weight each component
        weight_map = {
            "iv_spike": cfg.iv_weight,
            "volume_surge": cfg.volume_weight,
            "oi_surge": cfg.oi_weight,
            "skew_shift": cfg.skew_weight,
            "sweep": cfg.sweep_weight,
        }

        weighted_sum = 0.0
        active_weight = 0.0
        for etype, score in type_max.items():
            w = weight_map.get(etype, 0.0)
            weighted_sum += score * w
            active_weight += w

        composite = weighted_sum / total_weight if total_weight > 0 else 0.0
        composite = min(100.0, max(0.0, composite))

        flags = [_FLAG_NAMES.get(et, et) for et in sorted(type_max.keys())]

        return UnusualScore(
            composite_score=round(composite, 1),
            flags=flags,
            component_scores={k: round(v, 1) for k, v in type_max.items()},
            events=events,
        )

    def compute_summary(self, events: List[UnusualEvent]) -> UnusualSummary:
        """Compute aggregate summary from a list of events."""
        if not events:
            return UnusualSummary(
                total_events=0,
                unique_tickers=0,
                avg_score=0.0,
                top_tickers=[],
                type_breakdown={},
                highest_score_event=None,
            )

        # Type breakdown
        type_counts: Dict[str, int] = {}
        for e in events:
            type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1

        # Per-ticker aggregation
        ticker_data: Dict[str, List[float]] = {}
        for e in events:
            ticker_data.setdefault(e.ticker, []).append(e.score)

        top_tickers = sorted(
            [
                {
                    "ticker": t,
                    "count": len(scores),
                    "avg_score": round(sum(scores) / len(scores), 1),
                }
                for t, scores in ticker_data.items()
            ],
            key=lambda x: x["count"],
            reverse=True,
        )[:10]

        avg_score = sum(e.score for e in events) / len(events)
        highest = max(events, key=lambda e: e.score)

        return UnusualSummary(
            total_events=len(events),
            unique_tickers=len(ticker_data),
            avg_score=round(avg_score, 1),
            top_tickers=top_tickers,
            type_breakdown=type_counts,
            highest_score_event=highest,
        )


def _get_float(d: Dict[str, Any], *keys: str) -> Optional[float]:
    """Try multiple keys, return first valid float or None."""
    import math
    for key in keys:
        val = d.get(key)
        if val is not None:
            try:
                f = float(val)
                # NaN check - use math.isnan for clarity
                return None if math.isnan(f) else f
            except (TypeError, ValueError):
                continue
    return None
