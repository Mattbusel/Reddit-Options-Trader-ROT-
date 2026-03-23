"""Options Strategy Screener.

Scans a watchlist for options setups that match configurable criteria and
scores each candidate by a weighted combination of IV rank, volume, open
interest, and edge estimate.

Strategies screened:

- ``CoveredCall``
- ``CashSecuredPut``
- ``IronCondor``
- ``BullPutSpread``
- ``BearCallSpread``

Example::

    from rot.screener import StrategyScreener, ScreenCriteria

    screener = StrategyScreener()
    criteria = ScreenCriteria(
        min_iv_rank=40.0,
        max_iv_rank=90.0,
        min_volume=100,
        min_open_interest=500,
        min_days_to_expiry=14,
        max_days_to_expiry=60,
    )
    results = screener.scan(["AAPL", "TSLA", "SPY"], criteria)
    for r in results[:5]:
        print(r.symbol, r.strategy, f"score={r.score:.2f}")
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from rot.analytics.iv_rank import IVData, IVRankCalculator

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategy enum
# ---------------------------------------------------------------------------

class Strategy(str, Enum):
    COVERED_CALL = "CoveredCall"
    CASH_SECURED_PUT = "CashSecuredPut"
    IRON_CONDOR = "IronCondor"
    BULL_PUT_SPREAD = "BullPutSpread"
    BEAR_CALL_SPREAD = "BearCallSpread"


# ---------------------------------------------------------------------------
# ScreenCriteria
# ---------------------------------------------------------------------------

@dataclass
class ScreenCriteria:
    """Filter parameters for the options screener.

    Attributes:
        min_iv_rank: Minimum IV rank (0–100) required.
        max_iv_rank: Maximum IV rank (0–100) allowed.
        min_volume: Minimum daily options volume.
        min_open_interest: Minimum open interest on the target contract.
        min_days_to_expiry: Minimum DTE for the target expiry.
        max_days_to_expiry: Maximum DTE for the target expiry.
    """

    min_iv_rank: float = 0.0
    max_iv_rank: float = 100.0
    min_volume: int = 0
    min_open_interest: int = 0
    min_days_to_expiry: int = 7
    max_days_to_expiry: int = 90


# ---------------------------------------------------------------------------
# ScreenResult
# ---------------------------------------------------------------------------

@dataclass
class ScreenResult:
    """A screened options setup candidate.

    Attributes:
        symbol: Ticker symbol.
        strategy: Strategy name (e.g. ``"IronCondor"``).
        score: Weighted score 0–100; higher is better.
        details: Strategy-specific metadata (IV rank, edge estimate, etc.).
        timestamp: Unix epoch of the screen.
    """

    symbol: str
    strategy: Strategy
    score: float
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Score weights
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "iv_rank": 0.40,       # primary driver: selling premium when IV is rich
    "volume": 0.20,        # liquidity proxy
    "open_interest": 0.20, # liquidity proxy
    "edge": 0.20,          # estimated edge from IV vs realised vol spread
}


# ---------------------------------------------------------------------------
# Per-strategy scoring helpers
# ---------------------------------------------------------------------------

def _score_covered_call(iv_data: IVData, chain_stats: Dict[str, float]) -> float:
    """CoveredCall: prefer high IV rank (premium seller) and good call liquidity."""
    iv_component = iv_data.iv_rank / 100.0
    vol_component = _log_normalise(chain_stats.get("call_volume", 0), 1_000)
    oi_component = _log_normalise(chain_stats.get("call_oi", 0), 5_000)
    edge = _estimate_edge(iv_data)
    return _weighted(iv_component, vol_component, oi_component, edge) * 100.0


def _score_cash_secured_put(iv_data: IVData, chain_stats: Dict[str, float]) -> float:
    """CashSecuredPut: prefer high IV rank and put liquidity."""
    iv_component = iv_data.iv_rank / 100.0
    vol_component = _log_normalise(chain_stats.get("put_volume", 0), 1_000)
    oi_component = _log_normalise(chain_stats.get("put_oi", 0), 5_000)
    edge = _estimate_edge(iv_data)
    return _weighted(iv_component, vol_component, oi_component, edge) * 100.0


def _score_iron_condor(iv_data: IVData, chain_stats: Dict[str, float]) -> float:
    """IronCondor: needs very high IV rank for adequate premium on both wings."""
    # Penalise if IV rank < 50 — condors need rich premium
    iv_component = max(0.0, (iv_data.iv_rank - 50.0) / 50.0)
    vol_component = _log_normalise(
        (chain_stats.get("call_volume", 0) + chain_stats.get("put_volume", 0)) / 2.0,
        1_000,
    )
    oi_component = _log_normalise(
        (chain_stats.get("call_oi", 0) + chain_stats.get("put_oi", 0)) / 2.0,
        5_000,
    )
    edge = _estimate_edge(iv_data)
    return _weighted(iv_component, vol_component, oi_component, edge) * 100.0


def _score_bull_put_spread(iv_data: IVData, chain_stats: Dict[str, float]) -> float:
    """BullPutSpread: directionally bullish credit spread; medium-to-high IV rank."""
    iv_component = iv_data.iv_rank / 100.0 * 0.8 + 0.2   # floor boost
    vol_component = _log_normalise(chain_stats.get("put_volume", 0), 1_000)
    oi_component = _log_normalise(chain_stats.get("put_oi", 0), 5_000)
    edge = _estimate_edge(iv_data)
    return _weighted(iv_component, vol_component, oi_component, edge) * 100.0


def _score_bear_call_spread(iv_data: IVData, chain_stats: Dict[str, float]) -> float:
    """BearCallSpread: directionally bearish credit spread; medium-to-high IV rank."""
    iv_component = iv_data.iv_rank / 100.0 * 0.8 + 0.2
    vol_component = _log_normalise(chain_stats.get("call_volume", 0), 1_000)
    oi_component = _log_normalise(chain_stats.get("call_oi", 0), 5_000)
    edge = _estimate_edge(iv_data)
    return _weighted(iv_component, vol_component, oi_component, edge) * 100.0


def _estimate_edge(iv_data: IVData) -> float:
    """Estimate premium seller edge as IV vs 30-day mean spread (normalised)."""
    if iv_data.iv_mean_30d <= 0:
        return 0.5
    raw_edge = (iv_data.current_iv - iv_data.iv_mean_30d) / iv_data.iv_mean_30d
    return max(0.0, min(1.0, 0.5 + raw_edge))


def _log_normalise(value: float, scale: float) -> float:
    if value <= 0 or scale <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(scale))


def _weighted(iv: float, vol: float, oi: float, edge: float) -> float:
    return (
        _WEIGHTS["iv_rank"] * iv
        + _WEIGHTS["volume"] * vol
        + _WEIGHTS["open_interest"] * oi
        + _WEIGHTS["edge"] * edge
    )


# ---------------------------------------------------------------------------
# Chain stats fetcher
# ---------------------------------------------------------------------------

def _fetch_chain_stats(symbol: str, min_dte: int, max_dte: int) -> Dict[str, float]:
    """Fetch aggregate volume and open interest from yfinance options chain."""
    try:
        import yfinance as yf  # type: ignore[import]
        import datetime

        ticker = yf.Ticker(symbol)
        expiries = ticker.options
        if not expiries:
            return {}

        stats: Dict[str, float] = {
            "call_volume": 0.0,
            "put_volume": 0.0,
            "call_oi": 0.0,
            "put_oi": 0.0,
        }

        today = datetime.date.today()
        matched = False
        for exp_str in expiries:
            exp_date = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if min_dte <= dte <= max_dte:
                matched = True
                chain = ticker.option_chain(exp_str)
                calls = chain.calls
                puts = chain.puts

                stats["call_volume"] += float(calls["volume"].fillna(0).sum())
                stats["put_volume"] += float(puts["volume"].fillna(0).sum())
                stats["call_oi"] += float(calls["openInterest"].fillna(0).sum())
                stats["put_oi"] += float(puts["openInterest"].fillna(0).sum())

        if not matched and expiries:
            # fall back to nearest expiry
            chain = ticker.option_chain(expiries[0])
            calls = chain.calls
            puts = chain.puts
            stats["call_volume"] = float(calls["volume"].fillna(0).sum())
            stats["put_volume"] = float(puts["volume"].fillna(0).sum())
            stats["call_oi"] = float(calls["openInterest"].fillna(0).sum())
            stats["put_oi"] = float(puts["openInterest"].fillna(0).sum())

        return stats

    except Exception as exc:
        log.warning("Failed to fetch chain stats for %s: %s", symbol, exc)
        return {}


def _meets_criteria(
    chain_stats: Dict[str, float],
    criteria: ScreenCriteria,
    iv_rank: float,
) -> bool:
    total_vol = chain_stats.get("call_volume", 0) + chain_stats.get("put_volume", 0)
    total_oi = chain_stats.get("call_oi", 0) + chain_stats.get("put_oi", 0)
    if total_vol < criteria.min_volume:
        return False
    if total_oi < criteria.min_open_interest:
        return False
    if not (criteria.min_iv_rank <= iv_rank <= criteria.max_iv_rank):
        return False
    return True


# ---------------------------------------------------------------------------
# StrategyScreener
# ---------------------------------------------------------------------------

_STRATEGY_SCORERS = {
    Strategy.COVERED_CALL: _score_covered_call,
    Strategy.CASH_SECURED_PUT: _score_cash_secured_put,
    Strategy.IRON_CONDOR: _score_iron_condor,
    Strategy.BULL_PUT_SPREAD: _score_bull_put_spread,
    Strategy.BEAR_CALL_SPREAD: _score_bear_call_spread,
}


class StrategyScreener:
    """Scans a watchlist for options setups matching :class:`ScreenCriteria`.

    Args:
        iv_calculator: Optional pre-configured :class:`IVRankCalculator`.
            A default instance is created if not provided.
    """

    def __init__(self, iv_calculator: Optional[IVRankCalculator] = None) -> None:
        self._iv_calc = iv_calculator or IVRankCalculator()

    def _screen_symbol(
        self,
        symbol: str,
        criteria: ScreenCriteria,
    ) -> List[ScreenResult]:
        """Screen a single symbol and return all passing strategy results."""
        results: List[ScreenResult] = []
        try:
            iv_data = self._iv_calc.analyze(symbol)
            chain_stats = _fetch_chain_stats(
                symbol,
                criteria.min_days_to_expiry,
                criteria.max_days_to_expiry,
            )

            if not _meets_criteria(chain_stats, criteria, iv_data.iv_rank):
                return []

            for strategy, scorer in _STRATEGY_SCORERS.items():
                score = scorer(iv_data, chain_stats)
                results.append(
                    ScreenResult(
                        symbol=symbol,
                        strategy=strategy,
                        score=round(score, 2),
                        details={
                            "iv_rank": round(iv_data.iv_rank, 1),
                            "iv_percentile": round(iv_data.iv_percentile, 1),
                            "current_iv": round(iv_data.current_iv, 4),
                            "iv_regime": iv_data.classification.value,
                            "call_volume": int(chain_stats.get("call_volume", 0)),
                            "put_volume": int(chain_stats.get("put_volume", 0)),
                            "call_oi": int(chain_stats.get("call_oi", 0)),
                            "put_oi": int(chain_stats.get("put_oi", 0)),
                            "edge_estimate": round(_estimate_edge(iv_data), 3),
                        },
                    )
                )
        except Exception as exc:
            log.warning("Screening failed for %s: %s", symbol, exc)

        return results

    def scan(
        self,
        watchlist: List[str],
        criteria: ScreenCriteria,
    ) -> List[ScreenResult]:
        """Screen every symbol in *watchlist* against *criteria*.

        Args:
            watchlist: List of ticker symbols to screen.
            criteria: :class:`ScreenCriteria` with filter thresholds.

        Returns:
            List of :class:`ScreenResult` sorted by score descending.
            Symbols that fail the criteria filters are excluded.
        """
        all_results: List[ScreenResult] = []
        for symbol in watchlist:
            all_results.extend(self._screen_symbol(symbol, criteria))

        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results

    def scan_top(
        self,
        watchlist: List[str],
        criteria: ScreenCriteria,
        top_n: int = 10,
    ) -> List[ScreenResult]:
        """Return the top-N results by score.

        Args:
            watchlist: List of ticker symbols.
            criteria: Filter thresholds.
            top_n: Maximum number of results to return.

        Returns:
            Up to *top_n* :class:`ScreenResult` sorted by score descending.
        """
        return self.scan(watchlist, criteria)[:top_n]
