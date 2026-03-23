"""Unusual options flow detection for the Reddit Options Trader.

Ingests raw options flow records and surfaces unusual activity patterns such as
large premium sweeps, bullish/bearish divergences, and dark-pool proxies.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class OptionsFlow:
    """A single options trade record."""

    timestamp: datetime
    ticker: str
    strike: float
    expiry: str          # e.g. "2025-06-20"
    option_type: str     # "call" | "put"
    size: int            # number of contracts
    premium: float       # total dollar premium paid
    open_interest: int   # open interest at time of trade
    implied_vol: float   # implied volatility (0-1 scale)
    side: str            # "buy" | "sell"


# ---------------------------------------------------------------------------
# Analyser
# ---------------------------------------------------------------------------

class FlowAnalyzer:
    """Aggregates and analyses options flow records."""

    def __init__(self) -> None:
        self._flows: list[OptionsFlow] = []

    # ── Ingestion ──────────────────────────────────────────────────────────

    def ingest(self, flow: OptionsFlow) -> None:
        """Add a new flow record."""
        self._flows.append(flow)

    # ── Detection ─────────────────────────────────────────────────────────

    def detect_unusual(
        self,
        min_size: int = 100,
        min_premium: float = 10_000.0,
    ) -> list[OptionsFlow]:
        """Return flows that meet all three unusualness criteria.

        A flow is unusual when:
        * ``size > min_size``
        * ``premium > min_premium``
        * ``size / open_interest > 0.10``  (significant relative activity)
        """
        result = []
        for flow in self._flows:
            if flow.size <= min_size:
                continue
            if flow.premium <= min_premium:
                continue
            if flow.open_interest > 0:
                ratio = flow.size / flow.open_interest
            else:
                ratio = 0.0
            if ratio <= 0.10:
                continue
            result.append(flow)
        return result

    def bull_bear_ratio(
        self,
        ticker: str,
        window_seconds: float = 3600.0,
    ) -> float:
        """Call premium / put premium for flows in the last *window_seconds*.

        Returns ``float('inf')`` when there are no puts, ``0.0`` when there
        are no calls, and ``1.0`` when the window is empty.
        """
        now = datetime.now(tz=timezone.utc)
        call_premium = 0.0
        put_premium = 0.0

        for flow in self._flows:
            if flow.ticker != ticker:
                continue
            # Make timestamp timezone-aware if needed.
            ts = flow.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (now - ts).total_seconds()
            if age > window_seconds:
                continue
            if flow.option_type == "call":
                call_premium += flow.premium
            elif flow.option_type == "put":
                put_premium += flow.premium

        if call_premium == 0.0 and put_premium == 0.0:
            return 1.0
        if put_premium == 0.0:
            return float("inf")
        return call_premium / put_premium

    def sweep_detection(self, ticker: str) -> list[OptionsFlow]:
        """Detect sweep patterns: multiple rapid same-direction trades.

        A sweep is defined as two or more flows sharing the same
        ticker + strike + expiry + option_type + side within a 60-second window.
        Returns the constituent flows that form at least one sweep.
        """
        ticker_flows = [f for f in self._flows if f.ticker == ticker]
        # Group by key.
        groups: dict[tuple, list[OptionsFlow]] = defaultdict(list)
        for flow in ticker_flows:
            key = (flow.strike, flow.expiry, flow.option_type, flow.side)
            groups[key].append(flow)

        sweep_flows: list[OptionsFlow] = []
        for flows in groups.values():
            if len(flows) < 2:
                continue
            # Sort by time and look for at least two within 60 s.
            sorted_flows = sorted(
                flows,
                key=lambda f: (
                    f.timestamp if f.timestamp.tzinfo
                    else f.timestamp.replace(tzinfo=timezone.utc)
                ),
            )
            i = 0
            while i < len(sorted_flows) - 1:
                t0 = sorted_flows[i].timestamp
                if t0.tzinfo is None:
                    t0 = t0.replace(tzinfo=timezone.utc)
                j = i + 1
                cluster = [sorted_flows[i]]
                while j < len(sorted_flows):
                    tj = sorted_flows[j].timestamp
                    if tj.tzinfo is None:
                        tj = tj.replace(tzinfo=timezone.utc)
                    if (tj - t0).total_seconds() <= 60.0:
                        cluster.append(sorted_flows[j])
                        j += 1
                    else:
                        break
                if len(cluster) >= 2:
                    for f in cluster:
                        if f not in sweep_flows:
                            sweep_flows.append(f)
                i += 1

        return sweep_flows

    def dark_pool_proxy(self, ticker: str) -> float:
        """Fraction of volume from large block trades (> 500 contracts).

        Returns a value in [0, 1], or 0.0 if there are no flows for the ticker.
        """
        ticker_flows = [f for f in self._flows if f.ticker == ticker]
        if not ticker_flows:
            return 0.0
        total_volume = sum(f.size for f in ticker_flows)
        if total_volume == 0:
            return 0.0
        large_volume = sum(f.size for f in ticker_flows if f.size > 500)
        return large_volume / total_volume

    def flow_summary(self, ticker: str) -> dict:
        """Aggregate statistics for a ticker.

        Returns a dict with:
        * ``call_volume`` — total contracts for calls
        * ``put_volume``  — total contracts for puts
        * ``call_premium`` — total call premium paid
        * ``put_premium``  — total put premium paid
        * ``unusual_count`` — number of flows from :meth:`detect_unusual`
        * ``bull_bear_ratio`` — call_premium / put_premium
        """
        ticker_flows = [f for f in self._flows if f.ticker == ticker]
        call_volume = sum(f.size for f in ticker_flows if f.option_type == "call")
        put_volume = sum(f.size for f in ticker_flows if f.option_type == "put")
        call_premium = sum(f.premium for f in ticker_flows if f.option_type == "call")
        put_premium = sum(f.premium for f in ticker_flows if f.option_type == "put")

        unusual = [f for f in self.detect_unusual() if f.ticker == ticker]

        bb = (call_premium / put_premium) if put_premium > 0 else (
            float("inf") if call_premium > 0 else 1.0
        )

        return {
            "call_volume": call_volume,
            "put_volume": put_volume,
            "call_premium": call_premium,
            "put_premium": put_premium,
            "unusual_count": len(unusual),
            "bull_bear_ratio": bb,
        }


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from datetime import timedelta

    now = datetime.now(tz=timezone.utc)
    analyzer = FlowAnalyzer()

    # Large unusual call sweep.
    for i in range(3):
        analyzer.ingest(OptionsFlow(
            timestamp=now + timedelta(seconds=i * 15),
            ticker="SPY",
            strike=450.0,
            expiry="2025-06-20",
            option_type="call",
            size=200,
            premium=50_000.0,
            open_interest=1000,
            implied_vol=0.25,
            side="buy",
        ))

    unusual = analyzer.detect_unusual()
    assert len(unusual) == 3, f"Expected 3 unusual flows, got {len(unusual)}"

    sweeps = analyzer.sweep_detection("SPY")
    assert len(sweeps) >= 2, f"Expected sweep, got {len(sweeps)}"

    summary = analyzer.flow_summary("SPY")
    assert summary["call_volume"] == 600
    print("FlowAnalyzer smoke test passed.", file=sys.stderr)
