"""
Unusual options activity (options flow) analysis.

Detects sweep activity, computes unusual volume scores, IV percentile,
put/call ratio, and aggregates flow data by expiry and dark-pool-like
large prints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


# ─── DATA MODEL ──────────────────────────────────────────────────────────────

@dataclass
class OptionsFlow:
    """A single options flow record (one side of a trade)."""

    symbol: str
    expiry_date: date
    strike: float
    option_type: str          # "call" or "put"
    volume: float
    open_interest: float
    implied_vol: float
    premium_usd: float
    unusual_score: float = 0.0


# ─── FLOW ANALYSER ───────────────────────────────────────────────────────────

class FlowAnalyzer:
    """Analyses an options flow dataset for unusual activity and sentiment."""

    # ── Static scoring helpers ────────────────────────────────────────────────

    @staticmethod
    def unusual_volume_score(
        volume: float,
        open_interest: float,
        avg_daily_volume: float,
    ) -> float:
        """Composite unusualness score.

        Score = (volume / max(OI, 1)) + (volume / max(ADV, 1))

        Higher scores indicate more unusual activity relative to open
        interest and average daily volume.

        Args:
            volume:            Today's option volume.
            open_interest:     Open interest (prior session).
            avg_daily_volume:  30-day average daily option volume.

        Returns:
            Dimensionless unusualness score ≥ 0.
        """
        oi_ratio = volume / max(open_interest, 1.0)
        adv_ratio = volume / max(avg_daily_volume, 1.0)
        return oi_ratio + adv_ratio

    @staticmethod
    def iv_percentile(current_iv: float, iv_history: List[float]) -> float:
        """IV percentile rank of the current IV within the historical distribution.

        Args:
            current_iv:  Current implied volatility (e.g. 0.35 = 35%).
            iv_history:  Historical IV series (at least 1 value).

        Returns:
            Percentile in [0, 100].
        """
        if not iv_history:
            return 50.0
        below = sum(1 for v in iv_history if v < current_iv)
        return 100.0 * below / len(iv_history)

    @staticmethod
    def scan_unusual_activity(
        options_data: List[OptionsFlow],
        min_score: float = 2.0,
    ) -> List[OptionsFlow]:
        """Filters for flows with unusual_score ≥ min_score.

        Args:
            options_data: List of OptionsFlow records (unusual_score pre-set).
            min_score:    Minimum score threshold.

        Returns:
            Sorted list (descending score) of unusual flows.
        """
        unusual = [f for f in options_data if f.unusual_score >= min_score]
        return sorted(unusual, key=lambda f: f.unusual_score, reverse=True)

    @staticmethod
    def detect_sweep(trades: List[dict]) -> bool:
        """Detects an options sweep: many small trades executing rapidly.

        A sweep is identified when ≥ 5 trades occur and at least 80% are
        below the median size (consistent with splitting a large order).

        Args:
            trades: List of dicts with at least a 'size' key (float/int).

        Returns:
            True if sweep-like activity is detected.
        """
        if len(trades) < 5:
            return False

        sizes = sorted(t.get("size", 0) for t in trades)
        median_idx = len(sizes) // 2
        median_size = sizes[median_idx]

        if median_size <= 0:
            return False

        small_count = sum(1 for s in sizes if s <= median_size)
        return small_count / len(sizes) >= 0.8

    @staticmethod
    def put_call_ratio(calls_volume: float, puts_volume: float) -> float:
        """Put/call ratio.

        Args:
            calls_volume: Total call volume.
            puts_volume:  Total put volume.

        Returns:
            PCR = puts / calls. Returns 1.0 if calls_volume is 0.
        """
        if calls_volume <= 0.0:
            return 1.0
        return puts_volume / calls_volume

    @staticmethod
    def sentiment(pcr: float) -> str:
        """Market sentiment from put/call ratio.

        Args:
            pcr: Put/call ratio.

        Returns:
            "bullish" (PCR < 0.7), "neutral" (0.7–1.2), or "bearish" (PCR > 1.2).
        """
        if pcr < 0.7:
            return "bullish"
        elif pcr <= 1.2:
            return "neutral"
        else:
            return "bearish"

    @staticmethod
    def largest_trades(flows: List[OptionsFlow], top_n: int = 10) -> List[OptionsFlow]:
        """Returns the top-N flows by premium_usd.

        Args:
            flows:  List of OptionsFlow records.
            top_n:  Number of records to return.

        Returns:
            List of up to top_n flows sorted by premium descending.
        """
        return sorted(flows, key=lambda f: f.premium_usd, reverse=True)[:top_n]

    @staticmethod
    def flow_by_expiry(flows: List[OptionsFlow]) -> Dict[date, List[OptionsFlow]]:
        """Groups flows by expiry date.

        Args:
            flows: List of OptionsFlow records.

        Returns:
            Dict mapping expiry_date → list of flows.
        """
        result: Dict[date, List[OptionsFlow]] = {}
        for flow in flows:
            result.setdefault(flow.expiry_date, []).append(flow)
        return result

    @staticmethod
    def dark_pool_activity(
        flows: List[OptionsFlow],
        threshold_pct: float = 0.9,
    ) -> List[OptionsFlow]:
        """Identifies flows where volume exceeds threshold_pct × open_interest.

        Such prints may indicate block/dark-pool trades where an institution
        is opening a large new position relative to existing OI.

        Args:
            flows:          List of OptionsFlow records.
            threshold_pct:  Fraction of OI above which a trade is flagged (default 0.9).

        Returns:
            Filtered list of large-print flows, sorted by volume descending.
        """
        flagged = [
            f for f in flows
            if f.open_interest > 0 and f.volume >= threshold_pct * f.open_interest
        ]
        return sorted(flagged, key=lambda f: f.volume, reverse=True)


__all__ = ["OptionsFlow", "FlowAnalyzer"]
