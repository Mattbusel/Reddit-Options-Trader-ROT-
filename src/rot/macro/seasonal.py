"""Seasonal Pattern Analyzer — monthly seasonality for tickers and sectors."""

from __future__ import annotations

import logging
import statistics
from typing import Any, Dict, List

from rot.macro.types import SeasonalPattern

log = logging.getLogger(__name__)

# ── Historical sector seasonal tendencies (pre-computed baselines) ────
# These are long-term averages compiled from market data.
# Format: sector → {month: avg_excess_return_pct}
_SECTOR_SEASONAL_BASELINES: Dict[str, Dict[int, float]] = {
    "Technology": {
        1: 0.8, 2: -0.3, 3: 0.5, 4: 1.2, 5: -0.1, 6: 0.3,
        7: 1.5, 8: -0.4, 9: -1.2, 10: 0.9, 11: 1.8, 12: 0.6,
    },
    "Financials": {
        1: 1.5, 2: 0.2, 3: 0.1, 4: 0.8, 5: -0.5, 6: -0.2,
        7: 0.6, 8: -0.8, 9: -0.3, 10: 1.0, 11: 1.2, 12: 0.9,
    },
    "Energy": {
        1: -0.3, 2: 0.5, 3: 0.8, 4: 0.3, 5: -0.2, 6: 1.0,
        7: -0.1, 8: 0.2, 9: -0.5, 10: 1.5, 11: 0.8, 12: 1.2,
    },
    "Healthcare": {
        1: 0.3, 2: 0.1, 3: -0.2, 4: 0.5, 5: 0.8, 6: 0.2,
        7: 0.4, 8: -0.3, 9: -0.1, 10: 0.7, 11: 0.6, 12: 0.4,
    },
    "Consumer Discretionary": {
        1: 0.5, 2: -0.2, 3: 0.3, 4: 0.8, 5: -0.5, 6: 0.1,
        7: 0.6, 8: -0.3, 9: -0.8, 10: 1.2, 11: 2.0, 12: 1.5,
    },
    "Consumer Staples": {
        1: -0.1, 2: 0.3, 3: 0.4, 4: 0.2, 5: 0.6, 6: 0.1,
        7: 0.3, 8: 0.2, 9: -0.1, 10: 0.4, 11: 0.3, 12: 0.5,
    },
    "Industrials": {
        1: 0.6, 2: 0.1, 3: 0.3, 4: 0.5, 5: -0.4, 6: -0.2,
        7: 0.8, 8: -0.5, 9: -0.6, 10: 1.3, 11: 1.5, 12: 0.7,
    },
    "Materials": {
        1: 0.4, 2: 0.2, 3: 0.6, 4: 0.3, 5: -0.3, 6: -0.1,
        7: 0.5, 8: -0.4, 9: -0.5, 10: 1.0, 11: 0.8, 12: 0.4,
    },
    "Real Estate": {
        1: 0.2, 2: 0.5, 3: -0.1, 4: 0.4, 5: 0.3, 6: 0.6,
        7: 0.2, 8: -0.3, 9: -0.7, 10: 0.5, 11: 0.4, 12: 0.3,
    },
    "Utilities": {
        1: -0.2, 2: 0.4, 3: 0.3, 4: 0.1, 5: 0.5, 6: 0.3,
        7: -0.1, 8: 0.2, 9: 0.1, 10: 0.3, 11: 0.2, 12: 0.4,
    },
}

# ── SPY monthly seasonal (long-term averages) ───────────────────────
_SPY_MONTHLY_AVG: Dict[int, float] = {
    1: 1.0, 2: 0.1, 3: 1.0, 4: 1.3, 5: 0.2, 6: 0.2,
    7: 1.2, 8: -0.1, 9: -0.7, 10: 0.8, 11: 1.5, 12: 1.3,
}

_MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


class SeasonalAnalyzer:
    """Analyzes seasonal patterns for tickers and sectors."""

    def __init__(self, db: Any = None) -> None:
        self._db = db

    # ── Ticker seasonal patterns (from yfinance data) ────────────────

    def compute_seasonal_patterns(
        self,
        monthly_returns: Dict[int, List[float]],
        ticker_or_sector: str,
    ) -> List[SeasonalPattern]:
        """Compute seasonal patterns from monthly returns data.

        monthly_returns: {month (1-12): [list of annual returns for that month]}
        """
        patterns: List[SeasonalPattern] = []
        for month in range(1, 13):
            returns = monthly_returns.get(month, [])
            if not returns:
                continue
            avg_ret = statistics.mean(returns)
            wins = sum(1 for r in returns if r > 0)
            win_rate = wins / len(returns) * 100 if returns else 0.0
            median_ret = statistics.median(returns) if returns else 0.0
            best = max(returns) if returns else 0.0
            worst = min(returns) if returns else 0.0
            patterns.append(
                SeasonalPattern(
                    ticker_or_sector=ticker_or_sector,
                    month=month,
                    avg_return_pct=round(avg_ret, 2),
                    win_rate_pct=round(win_rate, 1),
                    sample_years=len(returns),
                    best_year_return=round(best, 2),
                    worst_year_return=round(worst, 2),
                    median_return_pct=round(median_ret, 2),
                )
            )
        return patterns

    def fetch_ticker_seasonals(
        self, ticker: str, lookback_years: int = 10
    ) -> List[SeasonalPattern]:
        """Fetch and compute seasonal patterns for a ticker using yfinance.

        Returns list of 12 SeasonalPattern (one per month).
        """
        try:
            import yfinance as yf
        except ImportError:
            log.warning("yfinance not installed — cannot compute seasonals")
            return []

        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=f"{lookback_years}y", interval="1mo")
            if hist is None or hist.empty:
                return []

            monthly_returns: Dict[int, List[float]] = {}
            closes = hist["Close"].tolist()
            dates = hist.index.tolist()

            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    ret = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
                    month = dates[i].month
                    monthly_returns.setdefault(month, []).append(ret)

            return self.compute_seasonal_patterns(monthly_returns, ticker)
        except Exception as exc:
            log.debug("Failed to compute seasonals for %s: %s", ticker, exc)
            return []

    # ── Sector seasonal patterns (pre-computed baselines) ────────────

    def get_sector_patterns(self, sector: str) -> List[SeasonalPattern]:
        """Return pre-computed sector seasonal patterns."""
        baseline = _SECTOR_SEASONAL_BASELINES.get(sector)
        if not baseline:
            return []
        patterns: List[SeasonalPattern] = []
        for month, avg_ret in baseline.items():
            patterns.append(
                SeasonalPattern(
                    ticker_or_sector=sector,
                    month=month,
                    avg_return_pct=avg_ret,
                    win_rate_pct=55.0 + avg_ret * 5,  # Rough estimate
                    sample_years=20,
                    median_return_pct=avg_ret * 0.9,
                )
            )
        return patterns

    def get_all_sector_patterns(self) -> Dict[str, List[SeasonalPattern]]:
        """Return seasonal patterns for all sectors."""
        return {
            sector: self.get_sector_patterns(sector)
            for sector in _SECTOR_SEASONAL_BASELINES
        }

    # ── Current month bias ───────────────────────────────────────────

    def get_current_bias(self, month: int) -> Dict[str, Any]:
        """Return seasonal bias for the current month.

        Returns dict with spy_avg, top_sectors, bottom_sectors, narrative.
        """
        spy_avg = _SPY_MONTHLY_AVG.get(month, 0.0)
        month_name = _MONTH_NAMES.get(month, "")

        # Rank sectors by this month's seasonal return
        sector_returns = []
        for sector, baselines in _SECTOR_SEASONAL_BASELINES.items():
            ret = baselines.get(month, 0.0)
            sector_returns.append((sector, ret))
        sector_returns.sort(key=lambda x: x[1], reverse=True)

        top_sectors = [(s, r) for s, r in sector_returns[:3]]
        bottom_sectors = [(s, r) for s, r in sector_returns[-3:]]

        # Build narrative
        if spy_avg > 0.8:
            bias = "historically bullish"
        elif spy_avg > 0.3:
            bias = "slightly bullish"
        elif spy_avg > -0.3:
            bias = "neutral"
        elif spy_avg > -0.8:
            bias = "slightly bearish"
        else:
            bias = "historically bearish"

        narrative = (
            f"{month_name} is {bias} for SPY (avg: {spy_avg:+.1f}%). "
            f"Top sector: {top_sectors[0][0]} ({top_sectors[0][1]:+.1f}%). "
            f"Weakest: {bottom_sectors[-1][0]} ({bottom_sectors[-1][1]:+.1f}%)."
        )

        return {
            "month": month,
            "month_name": month_name,
            "spy_avg_return_pct": spy_avg,
            "bias": bias,
            "top_sectors": top_sectors,
            "bottom_sectors": bottom_sectors,
            "narrative": narrative,
        }

    # ── Sector rotation calendar ─────────────────────────────────────

    def get_rotation_calendar(self) -> List[Dict[str, Any]]:
        """Return full 12-month sector rotation calendar.

        For each month, shows which sectors historically outperform.
        """
        calendar: List[Dict[str, Any]] = []
        for month in range(1, 13):
            bias = self.get_current_bias(month)
            calendar.append(bias)
        return calendar
