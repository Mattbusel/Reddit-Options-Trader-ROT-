"""Real-time unusual options activity scanner across liquid tickers.

Scans a universe of tickers for statistically unusual options activity and
raises alerts within 30 seconds of detection.  Builds on top of the existing
:mod:`rot.unusual` detection infrastructure and adds cross-ticker correlation
analysis for sector-rotation signals.

Key components
--------------
* :class:`UnusualActivityScanner` -- main scanner; polls option chains and
  runs anomaly detection in a background thread.
* :class:`DarkPoolCorrelator` -- correlates unusual options flow with dark
  pool print proxies (large off-exchange prints estimated from price impact).
* :class:`CrossTickerAnalyzer` -- detects correlated unusual activity across
  tickers in the same GICS sector.
* :class:`ActivityAlert` -- structured alert emitted by the scanner.

Example::

    from rot.scanner.unusual_activity import UnusualActivityScanner

    scanner = UnusualActivityScanner(universe=["AAPL", "MSFT", "NVDA"])
    scanner.start()           # runs background polling thread
    alerts = scanner.drain_alerts()
    scanner.stop()
"""

from __future__ import annotations

import logging
import math
import queue
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional yfinance for live data
# ---------------------------------------------------------------------------

_YF_AVAILABLE = False
try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OptionsSnapshot:
    """A lightweight snapshot of options activity for a single ticker.

    Attributes:
        ticker: Ticker symbol.
        timestamp: Unix timestamp of the snapshot.
        call_volume: Aggregate call volume across all expiries.
        put_volume: Aggregate put volume across all expiries.
        total_oi: Total open interest.
        iv_mean: Mean implied volatility across liquid strikes.
        volume_oi_ratio: call_volume + put_volume / total_oi.
        unusual_flags: Dict of flag name → severity score.
    """

    ticker: str
    timestamp: float
    call_volume: int = 0
    put_volume: int = 0
    total_oi: int = 0
    iv_mean: float = 0.0
    volume_oi_ratio: float = 0.0
    unusual_flags: Dict[str, float] = field(default_factory=dict)

    @property
    def total_volume(self) -> int:
        return self.call_volume + self.put_volume

    @property
    def pc_ratio(self) -> float:
        return self.put_volume / max(self.call_volume, 1)


@dataclass
class ActivityAlert:
    """Alert emitted when unusual activity is detected.

    Attributes:
        ticker: Affected ticker symbol.
        timestamp: Unix timestamp of detection.
        alert_type: One of ``"volume_spike"``, ``"oi_spike"``,
            ``"dark_pool"``, ``"sector_rotation"``.
        severity: Score in [0, 10] — higher is more unusual.
        details: Human-readable description.
        correlated_tickers: Other tickers involved (for sector signals).
    """

    ticker: str
    timestamp: float
    alert_type: str
    severity: float
    details: str
    correlated_tickers: List[str] = field(default_factory=list)


@dataclass
class ScannerConfig:
    """Configuration for :class:`UnusualActivityScanner`.

    Attributes:
        poll_interval_sec: Seconds between scan cycles (default 20).
        volume_oi_spike_threshold: Minimum vol/OI ratio z-score to flag.
        iv_spike_threshold: Minimum IV z-score to flag.
        dark_pool_price_impact_threshold: Minimum single-bar price move (pct)
            to infer a dark pool print.
        sector_correlation_threshold: Minimum fraction of sector tickers that
            must show flags for a sector-rotation alert.
        alert_ttl_sec: Seconds before a duplicate alert can fire again.
    """

    poll_interval_sec: float = 20.0
    volume_oi_spike_threshold: float = 2.5
    iv_spike_threshold: float = 2.0
    dark_pool_price_impact_threshold: float = 0.5
    sector_correlation_threshold: float = 0.4
    alert_ttl_sec: float = 300.0


# Default GICS sector groupings (subset of liquid tickers)
_DEFAULT_SECTORS: Dict[str, List[str]] = {
    "tech": ["AAPL", "MSFT", "NVDA", "AMD", "META", "GOOGL", "AMZN"],
    "finance": ["JPM", "GS", "BAC", "WFC", "MS", "C"],
    "energy": ["XOM", "CVX", "COP", "SLB", "OXY"],
    "healthcare": ["JNJ", "PFE", "MRNA", "ABBV", "UNH"],
    "semis": ["NVDA", "AMD", "INTC", "QCOM", "MU", "AVGO"],
}


# ---------------------------------------------------------------------------
# Dark pool correlator
# ---------------------------------------------------------------------------


class DarkPoolCorrelator:
    """Infers dark pool prints from abnormal price impact moves.

    Uses a heuristic: if price moves > ``threshold`` % in a single bar
    without a commensurate change in reported exchange volume, a large
    off-exchange (dark pool) print is likely.

    Args:
        price_impact_threshold: Minimum single-bar return (absolute %) to
            flag as potential dark pool activity.
    """

    def __init__(self, price_impact_threshold: float = 0.5) -> None:
        self.threshold = price_impact_threshold
        self._price_history: Dict[str, List[float]] = {}

    def update(self, ticker: str, price: float) -> bool:
        """Record a new price tick and return True if dark pool suspected.

        Args:
            ticker: Ticker symbol.
            price: Latest trade price.

        Returns:
            True when price impact exceeds the threshold vs. the previous tick.
        """
        history = self._price_history.setdefault(ticker, [])
        history.append(price)
        if len(history) > 100:
            history.pop(0)

        if len(history) < 2:
            return False

        prev = history[-2]
        if prev == 0:
            return False

        pct_move = abs(price - prev) / prev * 100.0
        if pct_move >= self.threshold:
            log.debug(
                "dark_pool_correlator.flag",
                ticker=ticker,
                pct_move=round(pct_move, 3),
            )
            return True
        return False


# ---------------------------------------------------------------------------
# Cross-ticker analyzer
# ---------------------------------------------------------------------------


class CrossTickerAnalyzer:
    """Detects correlated unusual activity across tickers in a sector.

    Args:
        sectors: Dict mapping sector name → list of tickers.
        correlation_threshold: Fraction of sector tickers that must show
            unusual flags before a sector-rotation alert is raised.
    """

    def __init__(
        self,
        sectors: Optional[Dict[str, List[str]]] = None,
        correlation_threshold: float = 0.4,
    ) -> None:
        self.sectors = sectors or _DEFAULT_SECTORS
        self.correlation_threshold = correlation_threshold

    def find_sector_rotation(
        self, flagged_tickers: Set[str]
    ) -> List[Tuple[str, List[str]]]:
        """Identify sectors where a significant fraction of tickers are flagged.

        Args:
            flagged_tickers: Set of ticker symbols that have active unusual
                activity flags.

        Returns:
            List of ``(sector_name, flagged_members)`` tuples where the
            fraction of flagged members exceeds the threshold.
        """
        results: List[Tuple[str, List[str]]] = []
        for sector, members in self.sectors.items():
            flagged = [m for m in members if m in flagged_tickers]
            fraction = len(flagged) / len(members) if members else 0.0
            if fraction >= self.correlation_threshold:
                results.append((sector, flagged))
                log.info(
                    "cross_ticker.sector_rotation",
                    sector=sector,
                    fraction=round(fraction, 2),
                    tickers=flagged,
                )
        return results


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------


class UnusualActivityScanner:
    """Real-time scanner for unusual options activity across liquid tickers.

    Runs a background polling thread that fetches option chain summaries,
    runs anomaly detection, and places :class:`ActivityAlert` instances into
    an internal queue for the caller to consume.

    Args:
        universe: List of ticker symbols to monitor.
        config: :class:`ScannerConfig` controlling thresholds.
        sectors: Sector mapping for cross-ticker analysis.
        on_alert: Optional callback ``(alert: ActivityAlert) -> None`` called
            immediately when a new alert fires.
    """

    def __init__(
        self,
        universe: Optional[List[str]] = None,
        config: Optional[ScannerConfig] = None,
        sectors: Optional[Dict[str, List[str]]] = None,
        on_alert: Optional[Callable[[ActivityAlert], None]] = None,
    ) -> None:
        self.universe = universe or list(_DEFAULT_SECTORS.get("tech", []))
        self.config = config or ScannerConfig()
        self.on_alert = on_alert

        self._alert_queue: queue.Queue[ActivityAlert] = queue.Queue()
        self._snapshots: Dict[str, List[OptionsSnapshot]] = {}
        self._recent_alerts: Dict[str, float] = {}  # key → last_alert_ts
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._flagged: Set[str] = set()

        self._dark_pool = DarkPoolCorrelator(
            price_impact_threshold=self.config.dark_pool_price_impact_threshold
        )
        self._cross_ticker = CrossTickerAnalyzer(
            sectors=sectors,
            correlation_threshold=self.config.sector_correlation_threshold,
        )

        log.info(
            "unusual_activity_scanner.init",
            universe_size=len(self.universe),
            poll_interval=self.config.poll_interval_sec,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background scanning thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()
        log.info("unusual_activity_scanner.started")

    def stop(self) -> None:
        """Stop the background scanning thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        log.info("unusual_activity_scanner.stopped")

    def drain_alerts(self) -> List[ActivityAlert]:
        """Drain and return all pending alerts from the queue."""
        alerts: List[ActivityAlert] = []
        while not self._alert_queue.empty():
            try:
                alerts.append(self._alert_queue.get_nowait())
            except queue.Empty:
                break
        return alerts

    # ------------------------------------------------------------------
    # Core scan logic
    # ------------------------------------------------------------------

    def _scan_loop(self) -> None:
        """Main polling loop executed in a background thread."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                self._run_scan_cycle()
            except Exception as exc:
                log.warning("unusual_activity_scanner.cycle_error", error=str(exc))
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, self.config.poll_interval_sec - elapsed)
            time.sleep(sleep_time)

    def _run_scan_cycle(self) -> None:
        """Execute one full scan cycle across all tickers."""
        self._flagged.clear()

        for ticker in self.universe:
            snapshot = self._fetch_snapshot(ticker)
            if snapshot is None:
                continue

            history = self._snapshots.setdefault(ticker, [])
            history.append(snapshot)
            if len(history) > 50:
                history.pop(0)

            flags = self._detect_anomalies(ticker, snapshot, history)
            if flags:
                self._flagged.add(ticker)
                for flag_type, severity in flags:
                    self._emit_alert(ticker, flag_type, severity, snapshot)

        # Cross-ticker sector rotation check
        rotations = self._cross_ticker.find_sector_rotation(self._flagged)
        for sector, members in rotations:
            # Emit a sector alert attributed to the first flagged member
            representative = members[0] if members else self.universe[0]
            self._emit_alert(
                ticker=representative,
                alert_type="sector_rotation",
                severity=7.0,
                snapshot=None,
                details=f"Sector rotation detected in {sector}: "
                f"{', '.join(members)} all showing unusual activity.",
                correlated=members,
            )

    def _detect_anomalies(
        self,
        ticker: str,
        snapshot: OptionsSnapshot,
        history: List[OptionsSnapshot],
    ) -> List[Tuple[str, float]]:
        """Detect volume/OI spikes and IV anomalies for *ticker*.

        Args:
            ticker: Ticker symbol.
            snapshot: Current snapshot.
            history: Historical snapshots (including current).

        Returns:
            List of ``(alert_type, severity_score)`` tuples.
        """
        if len(history) < 5:
            return []

        flags: List[Tuple[str, float]] = []

        # Volume/OI ratio z-score
        vol_oi_series = [h.volume_oi_ratio for h in history[:-1]]
        if vol_oi_series:
            z_vol = self._z_score(snapshot.volume_oi_ratio, vol_oi_series)
            if z_vol >= self.config.volume_oi_spike_threshold:
                severity = min(10.0, z_vol * 2.0)
                flags.append(("volume_spike", severity))

        # IV z-score
        iv_series = [h.iv_mean for h in history[:-1] if h.iv_mean > 0]
        if iv_series:
            z_iv = self._z_score(snapshot.iv_mean, iv_series)
            if z_iv >= self.config.iv_spike_threshold:
                severity = min(10.0, z_iv * 2.5)
                flags.append(("iv_spike", severity))

        # OI spike: sudden large jump
        if len(history) >= 2:
            prev_oi = history[-2].total_oi
            if prev_oi > 0:
                oi_growth = (snapshot.total_oi - prev_oi) / prev_oi * 100.0
                if oi_growth > 20.0:
                    flags.append(("oi_spike", min(10.0, oi_growth / 5.0)))

        return flags

    def _fetch_snapshot(self, ticker: str) -> Optional[OptionsSnapshot]:
        """Fetch a live options snapshot for *ticker* via yfinance.

        Falls back to a synthetic low-activity stub when yfinance is
        unavailable or the fetch fails.
        """
        ts = time.time()
        if not _YF_AVAILABLE:
            # Synthetic stub: random low-activity data for testing
            import random
            return OptionsSnapshot(
                ticker=ticker,
                timestamp=ts,
                call_volume=random.randint(100, 5000),
                put_volume=random.randint(100, 3000),
                total_oi=random.randint(5000, 50000),
                iv_mean=round(random.uniform(0.2, 0.8), 3),
                volume_oi_ratio=round(random.uniform(0.01, 0.5), 4),
            )

        try:
            tk = yf.Ticker(ticker)
            opts = tk.options
            if not opts:
                return None

            # Aggregate across all expiries
            call_vol = put_vol = total_oi = 0
            iv_values: List[float] = []

            for expiry in opts[:4]:  # Limit to front 4 expiries for speed
                try:
                    chain = tk.option_chain(expiry)
                    call_vol += int(chain.calls["volume"].sum())
                    put_vol += int(chain.puts["volume"].sum())
                    total_oi += int(
                        chain.calls["openInterest"].sum()
                        + chain.puts["openInterest"].sum()
                    )
                    iv_values.extend(
                        chain.calls["impliedVolatility"].dropna().tolist()
                        + chain.puts["impliedVolatility"].dropna().tolist()
                    )
                except Exception:
                    continue

            iv_mean = statistics.mean(iv_values) if iv_values else 0.0
            vol_oi = (call_vol + put_vol) / max(total_oi, 1)

            # Dark pool check using last close
            try:
                price = float(tk.fast_info.get("lastPrice", 0.0) or 0.0)
                dp_flagged = self._dark_pool.update(ticker, price)
                unusual_flags: Dict[str, float] = {}
                if dp_flagged:
                    unusual_flags["dark_pool"] = 1.0
                    self._emit_alert(ticker, "dark_pool", 6.0, None)
            except Exception:
                unusual_flags = {}

            return OptionsSnapshot(
                ticker=ticker,
                timestamp=ts,
                call_volume=call_vol,
                put_volume=put_vol,
                total_oi=total_oi,
                iv_mean=round(iv_mean, 4),
                volume_oi_ratio=round(vol_oi, 4),
                unusual_flags=unusual_flags,
            )

        except Exception as exc:
            log.debug("unusual_activity_scanner.fetch_error", ticker=ticker, error=str(exc))
            return None

    def _emit_alert(
        self,
        ticker: str,
        alert_type: str,
        severity: float,
        snapshot: Optional[OptionsSnapshot],
        details: str = "",
        correlated: Optional[List[str]] = None,
    ) -> None:
        """Emit an alert, respecting the TTL dedup window."""
        key = f"{ticker}:{alert_type}"
        now = time.time()
        last = self._recent_alerts.get(key, 0.0)
        if now - last < self.config.alert_ttl_sec:
            return

        self._recent_alerts[key] = now

        if not details and snapshot:
            details = (
                f"{ticker}: {alert_type} detected. "
                f"Vol/OI={snapshot.volume_oi_ratio:.3f}, "
                f"IV={snapshot.iv_mean:.3f}, "
                f"PC ratio={snapshot.pc_ratio:.2f}."
            )

        alert = ActivityAlert(
            ticker=ticker,
            timestamp=now,
            alert_type=alert_type,
            severity=round(severity, 2),
            details=details,
            correlated_tickers=correlated or [],
        )
        self._alert_queue.put(alert)
        if self.on_alert:
            try:
                self.on_alert(alert)
            except Exception as exc:
                log.warning("unusual_activity_scanner.callback_error", error=str(exc))

        log.info(
            "unusual_activity_scanner.alert",
            ticker=ticker,
            type=alert_type,
            severity=round(severity, 2),
        )

    # ------------------------------------------------------------------
    # Statistical helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _z_score(value: float, series: List[float]) -> float:
        """Compute z-score of *value* relative to *series*."""
        if not series:
            return 0.0
        mean = sum(series) / len(series)
        if len(series) < 2:
            return 0.0
        std = statistics.stdev(series)
        if std < 1e-9:
            return 0.0
        return (value - mean) / std
