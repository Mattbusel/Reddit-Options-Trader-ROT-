"""Options flow anomaly detection for the ROT platform.

Detects unusual options activity that may indicate informed or "smart money"
positioning:

- Large block trades relative to open interest
- Unusual call/put ratio vs 30-day historical average
- Dark pool volume spikes (approximated via unusual volume-to-OI ratio)
- Composite "smart money" flag with confidence scoring

The detector is intentionally stateless between tickers so it can be used in
parallel across a watchlist.  Historical baselines are supplied by the caller
(e.g. from a database or rolling computation).

Example::

    from rot.options.flow_anomaly import FlowAnomalyDetector, FlowSnapshot

    snapshot = FlowSnapshot(
        ticker="AAPL",
        call_volume=12_000,
        put_volume=3_000,
        call_oi=50_000,
        put_oi=60_000,
        block_trades=[{"volume": 5000, "oi": 8000, "side": "call"}],
        dark_pool_volume=4_000,
        total_volume=15_000,
        avg_cp_ratio_30d=0.9,
        avg_volume_30d=6_000,
    )

    detector = FlowAnomalyDetector()
    result = detector.analyze(snapshot)
    if result.smart_money_flag:
        print(f"Smart money signal: {result.summary}")
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants / thresholds
# ---------------------------------------------------------------------------

#: A block trade is flagged if volume / open_interest exceeds this ratio.
_BLOCK_OI_RATIO_THRESHOLD: float = 0.10   # 10% of OI in a single trade

#: Call/put ratio is "unusual" if it deviates by more than this from 30d avg.
_CP_RATIO_DEVIATION: float = 0.50          # 50% relative deviation

#: Dark pool volume is flagged if it exceeds this fraction of total volume.
_DARK_POOL_FRACTION_THRESHOLD: float = 0.25

#: Volume-vs-30d-avg multiplier that triggers a volume spike alert.
_VOLUME_SPIKE_MULTIPLIER: float = 2.5


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BlockTrade:
    """A single block trade observation.

    Attributes:
        volume: Number of contracts traded in the block.
        oi:     Open interest on the same strike/expiry at trade time.
        side:   ``"call"`` or ``"put"``.
        premium: Optional total premium paid (USD).
        strike:  Optional strike price.
        expiry:  Optional expiry date string (e.g. ``"2026-04-18"``).
    """

    volume: int
    oi: int
    side: str  # "call" | "put"
    premium: Optional[float] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None

    @property
    def oi_ratio(self) -> float:
        """Volume as a fraction of open interest (0 if OI is 0)."""
        if self.oi <= 0:
            return 0.0
        return self.volume / self.oi


@dataclass
class FlowSnapshot:
    """A point-in-time snapshot of options flow for one ticker.

    Attributes:
        ticker:            Underlying equity ticker symbol.
        call_volume:       Total call volume today.
        put_volume:        Total put volume today.
        call_oi:           Total call open interest.
        put_oi:            Total put open interest.
        block_trades:      List of :class:`BlockTrade` objects (or raw dicts).
        dark_pool_volume:  Estimated dark pool options volume (contracts).
        total_volume:      Total options volume (calls + puts).
        avg_cp_ratio_30d:  30-day average call/put volume ratio.
        avg_volume_30d:    30-day average total options volume.
    """

    ticker: str
    call_volume: int
    put_volume: int
    call_oi: int
    put_oi: int
    block_trades: List[BlockTrade] = field(default_factory=list)
    dark_pool_volume: int = 0
    total_volume: int = 0
    avg_cp_ratio_30d: float = 1.0
    avg_volume_30d: float = 0.0

    def __post_init__(self) -> None:
        # Normalise block_trades: accept dicts for ergonomic construction
        normalised: List[BlockTrade] = []
        for bt in self.block_trades:
            if isinstance(bt, dict):
                normalised.append(
                    BlockTrade(
                        volume=int(bt.get("volume", 0)),
                        oi=int(bt.get("oi", 0)),
                        side=str(bt.get("side", "call")),
                        premium=bt.get("premium"),
                        strike=bt.get("strike"),
                        expiry=bt.get("expiry"),
                    )
                )
            else:
                normalised.append(bt)
        self.block_trades = normalised

        # Derive total_volume if not supplied
        if self.total_volume == 0:
            self.total_volume = self.call_volume + self.put_volume

    @property
    def cp_ratio(self) -> float:
        """Current call/put volume ratio (inf if put_volume == 0)."""
        if self.put_volume == 0:
            return float("inf")
        return self.call_volume / self.put_volume


@dataclass
class AnomalyFlag:
    """A single detected anomaly.

    Attributes:
        category:    Short category string (e.g. ``"block_trade"``, ``"cp_ratio"``).
        description: Human-readable description.
        severity:    ``"low"``, ``"medium"``, or ``"high"``.
        confidence:  Float in ``[0, 1]`` representing detection confidence.
        metadata:    Additional key-value details.
    """

    category: str
    description: str
    severity: str  # "low" | "medium" | "high"
    confidence: float
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class FlowAnomalyResult:
    """Full anomaly detection result for one :class:`FlowSnapshot`.

    Attributes:
        ticker:           Underlying ticker.
        flags:            List of individual :class:`AnomalyFlag` detections.
        smart_money_flag: True if multiple high-confidence anomalies co-occur.
        composite_score:  Weighted confidence score in ``[0, 1]``.
        bullish_lean:     True if anomalies lean bullish (call-heavy flow).
        bearish_lean:     True if anomalies lean bearish (put-heavy flow).
        summary:          One-line human-readable summary.
    """

    ticker: str
    flags: List[AnomalyFlag]
    smart_money_flag: bool
    composite_score: float
    bullish_lean: bool
    bearish_lean: bool
    summary: str


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class FlowAnomalyDetector:
    """Detects unusual options flow for a single ticker snapshot.

    Args:
        block_oi_threshold:     OI ratio above which a block trade is flagged.
        cp_ratio_deviation:     Relative deviation from 30d avg to flag C/P ratio.
        dark_pool_fraction:     Dark pool fraction threshold.
        volume_spike_mult:      Volume-vs-30d-avg multiplier for spike detection.
        smart_money_min_flags:  Minimum number of high/medium flags to set
                                :attr:`FlowAnomalyResult.smart_money_flag`.

    Example::

        detector = FlowAnomalyDetector()
        result = detector.analyze(snapshot)
    """

    def __init__(
        self,
        block_oi_threshold: float = _BLOCK_OI_RATIO_THRESHOLD,
        cp_ratio_deviation: float = _CP_RATIO_DEVIATION,
        dark_pool_fraction: float = _DARK_POOL_FRACTION_THRESHOLD,
        volume_spike_mult: float = _VOLUME_SPIKE_MULTIPLIER,
        smart_money_min_flags: int = 2,
    ) -> None:
        self.block_oi_threshold = block_oi_threshold
        self.cp_ratio_deviation = cp_ratio_deviation
        self.dark_pool_fraction = dark_pool_fraction
        self.volume_spike_mult = volume_spike_mult
        self.smart_money_min_flags = smart_money_min_flags

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, snapshot: FlowSnapshot) -> FlowAnomalyResult:
        """Run all anomaly checks against the given flow snapshot.

        Args:
            snapshot: :class:`FlowSnapshot` for one ticker.

        Returns:
            :class:`FlowAnomalyResult` with all detected flags and composite score.
        """
        flags: List[AnomalyFlag] = []

        flags.extend(self._check_block_trades(snapshot))
        flags.extend(self._check_cp_ratio(snapshot))
        flags.extend(self._check_dark_pool(snapshot))
        flags.extend(self._check_volume_spike(snapshot))

        composite = self._composite_score(flags)
        smart_money = self._is_smart_money(flags)

        bullish, bearish = self._directional_lean(snapshot, flags)
        summary = self._build_summary(snapshot.ticker, flags, composite, bullish, bearish)

        return FlowAnomalyResult(
            ticker=snapshot.ticker,
            flags=flags,
            smart_money_flag=smart_money,
            composite_score=composite,
            bullish_lean=bullish,
            bearish_lean=bearish,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_block_trades(self, snap: FlowSnapshot) -> List[AnomalyFlag]:
        """Flag block trades where volume/OI exceeds threshold."""
        found: List[AnomalyFlag] = []
        for bt in snap.block_trades:
            ratio = bt.oi_ratio
            if ratio >= self.block_oi_threshold:
                severity = "high" if ratio >= 0.30 else "medium"
                confidence = min(1.0, ratio / 0.30)
                found.append(
                    AnomalyFlag(
                        category="block_trade",
                        description=(
                            f"Large {bt.side} block trade: {bt.volume:,} contracts "
                            f"({ratio:.1%} of OI)"
                        ),
                        severity=severity,
                        confidence=round(confidence, 3),
                        metadata={
                            "side": bt.side,
                            "volume": bt.volume,
                            "oi": bt.oi,
                            "oi_ratio": round(ratio, 4),
                            "strike": bt.strike,
                            "expiry": bt.expiry,
                        },
                    )
                )
        return found

    def _check_cp_ratio(self, snap: FlowSnapshot) -> List[AnomalyFlag]:
        """Flag unusual call/put ratio vs 30-day average."""
        found: List[AnomalyFlag] = []
        if snap.avg_cp_ratio_30d <= 0:
            return found

        current = snap.cp_ratio
        if not math.isfinite(current):
            # Extreme call skew (no puts)
            found.append(
                AnomalyFlag(
                    category="cp_ratio",
                    description="Extreme call skew: zero put volume detected.",
                    severity="high",
                    confidence=0.90,
                    metadata={"current_cp_ratio": "inf", "avg_30d": snap.avg_cp_ratio_30d},
                )
            )
            return found

        relative_dev = abs(current - snap.avg_cp_ratio_30d) / snap.avg_cp_ratio_30d
        if relative_dev >= self.cp_ratio_deviation:
            bullish_flag = current > snap.avg_cp_ratio_30d
            severity = "high" if relative_dev >= 1.0 else "medium"
            confidence = min(1.0, relative_dev / 1.0)
            direction = "call-heavy (bullish lean)" if bullish_flag else "put-heavy (bearish lean)"
            found.append(
                AnomalyFlag(
                    category="cp_ratio",
                    description=(
                        f"Unusual C/P ratio: {current:.2f} vs 30d avg {snap.avg_cp_ratio_30d:.2f} "
                        f"({direction}, {relative_dev:.0%} deviation)"
                    ),
                    severity=severity,
                    confidence=round(confidence, 3),
                    metadata={
                        "current_cp_ratio": round(current, 4),
                        "avg_30d": snap.avg_cp_ratio_30d,
                        "relative_deviation": round(relative_dev, 4),
                        "bullish": bullish_flag,
                    },
                )
            )
        return found

    def _check_dark_pool(self, snap: FlowSnapshot) -> List[AnomalyFlag]:
        """Flag elevated dark pool volume fraction."""
        found: List[AnomalyFlag] = []
        if snap.total_volume <= 0 or snap.dark_pool_volume <= 0:
            return found

        fraction = snap.dark_pool_volume / snap.total_volume
        if fraction >= self.dark_pool_fraction:
            severity = "high" if fraction >= 0.40 else "medium"
            confidence = min(1.0, fraction / 0.40)
            found.append(
                AnomalyFlag(
                    category="dark_pool",
                    description=(
                        f"Dark pool volume spike: {snap.dark_pool_volume:,} contracts "
                        f"({fraction:.1%} of total volume)"
                    ),
                    severity=severity,
                    confidence=round(confidence, 3),
                    metadata={
                        "dark_pool_volume": snap.dark_pool_volume,
                        "total_volume": snap.total_volume,
                        "fraction": round(fraction, 4),
                    },
                )
            )
        return found

    def _check_volume_spike(self, snap: FlowSnapshot) -> List[AnomalyFlag]:
        """Flag total volume that is unusually high vs 30-day average."""
        found: List[AnomalyFlag] = []
        if snap.avg_volume_30d <= 0 or snap.total_volume <= 0:
            return found

        mult = snap.total_volume / snap.avg_volume_30d
        if mult >= self.volume_spike_mult:
            severity = "high" if mult >= 5.0 else "medium"
            confidence = min(1.0, (mult - self.volume_spike_mult) / (5.0 - self.volume_spike_mult + 1e-9))
            found.append(
                AnomalyFlag(
                    category="volume_spike",
                    description=(
                        f"Volume spike: {snap.total_volume:,} contracts "
                        f"({mult:.1f}x 30d avg of {snap.avg_volume_30d:,.0f})"
                    ),
                    severity=severity,
                    confidence=round(max(0.0, confidence), 3),
                    metadata={
                        "total_volume": snap.total_volume,
                        "avg_30d": snap.avg_volume_30d,
                        "multiplier": round(mult, 2),
                    },
                )
            )
        return found

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    _SEVERITY_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3}

    def _composite_score(self, flags: List[AnomalyFlag]) -> float:
        """Weighted average confidence across all flags; 0 if no flags."""
        if not flags:
            return 0.0
        total_w = 0.0
        weighted_sum = 0.0
        for f in flags:
            w = self._SEVERITY_WEIGHTS.get(f.severity, 0.3)
            weighted_sum += w * f.confidence
            total_w += w
        return round(weighted_sum / total_w, 4) if total_w > 0 else 0.0

    def _is_smart_money(self, flags: List[AnomalyFlag]) -> bool:
        """True if >= ``smart_money_min_flags`` medium/high flags detected."""
        significant = [f for f in flags if f.severity in ("medium", "high")]
        return len(significant) >= self.smart_money_min_flags

    def _directional_lean(
        self, snap: FlowSnapshot, flags: List[AnomalyFlag]
    ) -> tuple[bool, bool]:
        """Determine bullish / bearish lean from C/P ratio and block trades."""
        call_score = 0
        put_score = 0

        # C/P ratio
        if math.isfinite(snap.cp_ratio):
            if snap.cp_ratio > snap.avg_cp_ratio_30d * 1.2:
                call_score += 1
            elif snap.cp_ratio < snap.avg_cp_ratio_30d * 0.8:
                put_score += 1

        # Block trades
        for bt in snap.block_trades:
            if bt.oi_ratio >= self.block_oi_threshold:
                if bt.side == "call":
                    call_score += 1
                else:
                    put_score += 1

        bullish = call_score > put_score
        bearish = put_score > call_score
        return bullish, bearish

    def _build_summary(
        self,
        ticker: str,
        flags: List[AnomalyFlag],
        score: float,
        bullish: bool,
        bearish: bool,
    ) -> str:
        if not flags:
            return f"{ticker}: No unusual options flow detected."
        lean = "bullish" if bullish else ("bearish" if bearish else "neutral")
        return (
            f"{ticker}: {len(flags)} anomaly flag(s) detected "
            f"(composite score {score:.2f}, {lean} lean)."
        )
