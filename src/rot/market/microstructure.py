"""Market microstructure analysis for the ROT signal pipeline.

Provides tools to assess execution quality, liquidity conditions, and the
relationship between Reddit sentiment signals and subsequent price discovery.

Classes
-------
BidAskSpreadAnalyzer
    Estimates effective bid-ask spread and half-spread from trade data.
OrderImbalanceDetector
    Detects buy/sell order flow imbalance that may precede directional moves.
PriceDiscoveryMetric
    Measures whether Reddit sentiment *leads* or *lags* price using
    cross-correlation of normalised sentiment and returns time-series.
MarketImpactEstimator
    Kyle (1985) lambda estimation: price impact per unit of signed order flow.
LiquidityScore
    Composite liquidity score combining spread, depth, and turnover.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpreadEstimate:
    """Output of BidAskSpreadAnalyzer."""

    symbol: str
    quoted_spread: Optional[float]     # best ask - best bid
    effective_spread: Optional[float]  # 2 * |trade_price - mid|  average
    half_spread: Optional[float]       # effective_spread / 2
    relative_spread_bps: Optional[float]  # spread / mid * 10_000
    n_trades: int
    mid_price: Optional[float]


@dataclass(frozen=True)
class ImbalanceResult:
    """Output of OrderImbalanceDetector."""

    symbol: str
    buy_volume: float
    sell_volume: float
    total_volume: float
    imbalance_ratio: float   # (buy - sell) / total  in [-1, 1]
    imbalance_pct: float     # abs(imbalance_ratio) * 100
    direction: str           # "buy_heavy" | "sell_heavy" | "balanced"
    threshold_breached: bool


@dataclass(frozen=True)
class PriceDiscoveryResult:
    """Output of PriceDiscoveryMetric."""

    symbol: str
    optimal_lag: int         # lag (in periods) at max cross-correlation
    max_correlation: float   # Pearson r at optimal lag
    leads_price: bool        # True if sentiment leads price (lag > 0)
    lags_price: bool         # True if sentiment lags price (lag < 0)
    is_contemporaneous: bool  # True if optimal_lag == 0
    n_observations: int


@dataclass(frozen=True)
class KyleLambda:
    """Output of MarketImpactEstimator (Kyle 1985 price-impact coefficient)."""

    symbol: str
    lambda_value: float      # price impact per unit signed order flow ($/share)
    r_squared: float         # fit quality of the OLS regression
    n_observations: int
    interpretation: str      # "low" | "medium" | "high" illiquidity


@dataclass(frozen=True)
class LiquidityScoreResult:
    """Output of LiquidityScore."""

    symbol: str
    composite_score: float   # 0.0 (very illiquid) – 1.0 (very liquid)
    spread_score: float      # sub-score from spread component
    depth_score: float       # sub-score from depth/OI component
    turnover_score: float    # sub-score from volume/turnover component
    classification: str      # "high" | "medium" | "low"
    components: Dict[str, float]


# ---------------------------------------------------------------------------
# BidAskSpreadAnalyzer
# ---------------------------------------------------------------------------


class BidAskSpreadAnalyzer:
    """Estimates bid-ask spread components from trade-level or quote data.

    The effective spread is calculated as the average of
    ``2 * |trade_price - mid_price|`` across all trades, following Roll (1984)
    and Glosten-Milgrom (1985).  When only a quoted spread is available (best
    ask - best bid) the effective spread is approximated as 80% of quoted.

    Parameters
    ----------
    min_trades:
        Minimum number of trade records required before spread estimates are
        considered reliable.  Below this threshold the estimates are returned
        but flagged via ``n_trades``.
    """

    def __init__(self, min_trades: int = 10) -> None:
        self.min_trades = min_trades

    def estimate(
        self,
        symbol: str,
        trades: List[Dict[str, Any]],
        *,
        best_bid: Optional[float] = None,
        best_ask: Optional[float] = None,
    ) -> SpreadEstimate:
        """Estimate spread from trade records.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        trades:
            List of trade dicts.  Each must contain ``"price"`` (float).
            Optionally ``"side"`` (``"buy"`` | ``"sell"``) for signed analysis.
            Optionally ``"size"`` (float) for volume-weighted mid.
        best_bid:
            Best bid price at time of analysis (optional).
        best_ask:
            Best ask price at time of analysis (optional).

        Returns
        -------
        SpreadEstimate
        """
        n = len(trades)

        # Mid price: prefer quote-derived, fall back to trade average
        if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask > 0:
            mid_price: Optional[float] = (best_bid + best_ask) / 2.0
            quoted_spread: Optional[float] = best_ask - best_bid
        else:
            prices = [float(t["price"]) for t in trades if t.get("price") and t["price"] > 0]
            mid_price = statistics.mean(prices) if prices else None
            quoted_spread = None

        if not trades or mid_price is None or mid_price <= 0:
            return SpreadEstimate(
                symbol=symbol,
                quoted_spread=quoted_spread,
                effective_spread=None,
                half_spread=None,
                relative_spread_bps=None,
                n_trades=n,
                mid_price=mid_price,
            )

        # Effective spread = 2 * |trade_price - mid|
        deviations = []
        for t in trades:
            price = t.get("price")
            if price and price > 0:
                deviations.append(2.0 * abs(float(price) - mid_price))

        if not deviations:
            return SpreadEstimate(
                symbol=symbol,
                quoted_spread=quoted_spread,
                effective_spread=None,
                half_spread=None,
                relative_spread_bps=None,
                n_trades=n,
                mid_price=mid_price,
            )

        effective_spread = statistics.mean(deviations)
        half_spread = effective_spread / 2.0
        relative_bps = (effective_spread / mid_price) * 10_000.0 if mid_price > 0 else None

        # If quoted spread wasn't computed, approximate from effective
        if quoted_spread is None:
            quoted_spread = effective_spread / 0.80  # effective ~ 80% of quoted

        return SpreadEstimate(
            symbol=symbol,
            quoted_spread=round(quoted_spread, 6),
            effective_spread=round(effective_spread, 6),
            half_spread=round(half_spread, 6),
            relative_spread_bps=round(relative_bps, 2) if relative_bps is not None else None,
            n_trades=n,
            mid_price=round(mid_price, 4),
        )

    def from_options_chain(
        self,
        symbol: str,
        options_data: Dict[str, Any],
    ) -> SpreadEstimate:
        """Estimate spread directly from an options chain dict.

        Accepts the same ``sym_data`` structure used by ``TradeBuilder`` and
        ``MarketEnricher``, keyed on ``options_chain.avg_bid_ask_spread_pct``
        and ``last_close``.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        options_data:
            Market data dict (output of ``MarketEnricher.enrich_symbols()``).

        Returns
        -------
        SpreadEstimate
        """
        price = options_data.get("last_close") or options_data.get("last_price")
        chain = options_data.get("options_chain", {})
        spread_pct = chain.get("avg_bid_ask_spread_pct") if isinstance(chain, dict) else None

        if price and price > 0 and spread_pct is not None:
            eff = price * spread_pct
            return SpreadEstimate(
                symbol=symbol,
                quoted_spread=round(eff / 0.80, 6),
                effective_spread=round(eff, 6),
                half_spread=round(eff / 2.0, 6),
                relative_spread_bps=round(spread_pct * 10_000.0, 2),
                n_trades=0,
                mid_price=round(float(price), 4),
            )

        return SpreadEstimate(
            symbol=symbol,
            quoted_spread=None,
            effective_spread=None,
            half_spread=None,
            relative_spread_bps=None,
            n_trades=0,
            mid_price=float(price) if price else None,
        )


# ---------------------------------------------------------------------------
# OrderImbalanceDetector
# ---------------------------------------------------------------------------


class OrderImbalanceDetector:
    """Detects significant buy/sell order flow imbalance.

    Imbalance is computed as ``(buy_volume - sell_volume) / total_volume``,
    yielding a value in [-1, 1].  When the absolute value exceeds
    ``threshold``, the result is flagged as a potential directional precursor.

    Parameters
    ----------
    threshold:
        Imbalance ratio in [0, 1] above which ``threshold_breached`` is set.
        Default 0.25 means >25% net imbalance triggers a flag.
    """

    def __init__(self, threshold: float = 0.25) -> None:
        if not (0.0 < threshold < 1.0):
            raise ValueError("threshold must be in (0, 1)")
        self.threshold = threshold

    def detect(
        self,
        symbol: str,
        trades: List[Dict[str, Any]],
    ) -> ImbalanceResult:
        """Detect order imbalance from a list of tagged trade records.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        trades:
            List of trade dicts.  Each must contain ``"side"`` (``"buy"`` |
            ``"sell"``) and ``"size"`` (float or int volume).  Records
            missing ``"side"`` or ``"size"`` are skipped.

        Returns
        -------
        ImbalanceResult
        """
        buy_vol = 0.0
        sell_vol = 0.0

        for t in trades:
            side = str(t.get("side", "")).lower()
            size = t.get("size")
            if not isinstance(size, (int, float)) or size <= 0:
                continue
            if side == "buy":
                buy_vol += float(size)
            elif side == "sell":
                sell_vol += float(size)

        total_vol = buy_vol + sell_vol

        if total_vol == 0.0:
            return ImbalanceResult(
                symbol=symbol,
                buy_volume=0.0,
                sell_volume=0.0,
                total_volume=0.0,
                imbalance_ratio=0.0,
                imbalance_pct=0.0,
                direction="balanced",
                threshold_breached=False,
            )

        ratio = (buy_vol - sell_vol) / total_vol
        abs_ratio = abs(ratio)

        if ratio > self.threshold:
            direction = "buy_heavy"
        elif ratio < -self.threshold:
            direction = "sell_heavy"
        else:
            direction = "balanced"

        return ImbalanceResult(
            symbol=symbol,
            buy_volume=round(buy_vol, 2),
            sell_volume=round(sell_vol, 2),
            total_volume=round(total_vol, 2),
            imbalance_ratio=round(ratio, 4),
            imbalance_pct=round(abs_ratio * 100.0, 2),
            direction=direction,
            threshold_breached=abs_ratio > self.threshold,
        )


# ---------------------------------------------------------------------------
# PriceDiscoveryMetric
# ---------------------------------------------------------------------------


class PriceDiscoveryMetric:
    """Measures whether Reddit sentiment leads or lags price discovery.

    Uses Pearson cross-correlation of a normalised sentiment series and a
    normalised return series at multiple lags.  A positive optimal lag
    (sentiment shifted *forward* in time to align with returns) means
    sentiment leads price; a negative lag means sentiment lags price.

    Parameters
    ----------
    max_lag:
        Maximum number of periods to test in each direction.  E.g. with
        hourly data and ``max_lag=24``, tests up to ±24 hours of lead/lag.
    """

    def __init__(self, max_lag: int = 10) -> None:
        if max_lag < 1:
            raise ValueError("max_lag must be >= 1")
        self.max_lag = max_lag

    @staticmethod
    def _zscore(series: List[float]) -> List[float]:
        """Z-score normalise a numeric series.  Returns zeros if std == 0."""
        if len(series) < 2:
            return series[:]
        mu = statistics.mean(series)
        try:
            std = statistics.stdev(series)
        except statistics.StatisticsError:
            std = 0.0
        if std < 1e-12:
            return [0.0] * len(series)
        return [(x - mu) / std for x in series]

    @staticmethod
    def _pearson(x: List[float], y: List[float]) -> float:
        """Pearson correlation between two equal-length series."""
        n = len(x)
        if n < 3:
            return 0.0
        mx, my = sum(x) / n, sum(y) / n
        cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        sx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
        sy = math.sqrt(sum((yi - my) ** 2 for yi in y))
        if sx < 1e-12 or sy < 1e-12:
            return 0.0
        return cov / (sx * sy)

    def compute(
        self,
        symbol: str,
        sentiment_series: List[float],
        return_series: List[float],
    ) -> PriceDiscoveryResult:
        """Compute cross-correlation at lags in ``[-max_lag, max_lag]``.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        sentiment_series:
            Time-ordered sentiment scores (e.g. [-1, 0, 1]).  Must be the
            same length as ``return_series``.
        return_series:
            Time-ordered price return values (e.g. percent daily returns).

        Returns
        -------
        PriceDiscoveryResult
        """
        n = len(sentiment_series)
        if n != len(return_series):
            raise ValueError("sentiment_series and return_series must have equal length")

        if n < max(5, self.max_lag * 2):
            return PriceDiscoveryResult(
                symbol=symbol,
                optimal_lag=0,
                max_correlation=0.0,
                leads_price=False,
                lags_price=False,
                is_contemporaneous=True,
                n_observations=n,
            )

        s = self._zscore(sentiment_series)
        r = self._zscore(return_series)

        best_lag = 0
        best_corr = 0.0

        for lag in range(-self.max_lag, self.max_lag + 1):
            if lag > 0:
                # Sentiment leads: shift sentiment forward
                s_slice = s[: n - lag]
                r_slice = r[lag:]
            elif lag < 0:
                # Sentiment lags: shift returns forward
                abs_lag = -lag
                s_slice = s[abs_lag:]
                r_slice = r[: n - abs_lag]
            else:
                s_slice = s
                r_slice = r

            if len(s_slice) < 3:
                continue

            corr = self._pearson(list(s_slice), list(r_slice))
            if abs(corr) > abs(best_corr):
                best_corr = corr
                best_lag = lag

        return PriceDiscoveryResult(
            symbol=symbol,
            optimal_lag=best_lag,
            max_correlation=round(best_corr, 4),
            leads_price=best_lag > 0,
            lags_price=best_lag < 0,
            is_contemporaneous=best_lag == 0,
            n_observations=n,
        )


# ---------------------------------------------------------------------------
# MarketImpactEstimator (Kyle lambda)
# ---------------------------------------------------------------------------


class MarketImpactEstimator:
    """Estimates Kyle (1985) lambda: price impact per unit signed order flow.

    Lambda is the OLS slope from regressing signed price changes
    (``delta_p``) on signed order flow (``q``):

        delta_p = lambda * q + epsilon

    A higher lambda means each unit of order flow moves price more, i.e.
    the market is *more* illiquid / informationally sensitive.

    Parameters
    ----------
    low_threshold:
        Lambda below this value is classified "low" illiquidity.
    high_threshold:
        Lambda above this value is classified "high" illiquidity.
    """

    def __init__(
        self,
        low_threshold: float = 0.01,
        high_threshold: float = 0.10,
    ) -> None:
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold

    @staticmethod
    def _ols_slope(x: List[float], y: List[float]) -> Tuple[float, float]:
        """OLS regression slope and R-squared."""
        n = len(x)
        if n < 3:
            return 0.0, 0.0
        mx, my = sum(x) / n, sum(y) / n
        ssxx = sum((xi - mx) ** 2 for xi in x)
        ssxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        if ssxx < 1e-15:
            return 0.0, 0.0
        slope = ssxy / ssxx
        intercept = my - slope * mx
        # R²
        y_hat = [intercept + slope * xi for xi in x]
        ss_res = sum((yi - yhi) ** 2 for yi, yhi in zip(y, y_hat))
        ss_tot = sum((yi - my) ** 2 for yi in y)
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-15 else 0.0
        return slope, max(0.0, r2)

    def estimate(
        self,
        symbol: str,
        signed_flows: List[float],
        price_changes: List[float],
    ) -> KyleLambda:
        """Estimate Kyle lambda from signed flow and price change series.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        signed_flows:
            Net signed order flow per period (buy vol - sell vol).  Positive
            means net buying.
        price_changes:
            Contemporaneous price changes per period (same units as prices).

        Returns
        -------
        KyleLambda
        """
        n = len(signed_flows)
        if n != len(price_changes):
            raise ValueError("signed_flows and price_changes must have equal length")

        if n < 3:
            return KyleLambda(
                symbol=symbol,
                lambda_value=0.0,
                r_squared=0.0,
                n_observations=n,
                interpretation="low",
            )

        slope, r2 = self._ols_slope(signed_flows, price_changes)
        lam = abs(slope)

        if lam < self.low_threshold:
            interpretation = "low"
        elif lam > self.high_threshold:
            interpretation = "high"
        else:
            interpretation = "medium"

        return KyleLambda(
            symbol=symbol,
            lambda_value=round(lam, 8),
            r_squared=round(r2, 4),
            n_observations=n,
            interpretation=interpretation,
        )


# ---------------------------------------------------------------------------
# LiquidityScore
# ---------------------------------------------------------------------------


class LiquidityScore:
    """Composite liquidity scoring from spread, depth, and turnover metrics.

    Each component is normalised to [0, 1] using configurable floor/cap
    anchors.  The composite score is a weighted average.

    Component weights (default)
    ---------------------------
    - spread:   0.40 — bid-ask spread (lower is more liquid)
    - depth:    0.35 — open interest / order book depth (higher is more liquid)
    - turnover: 0.25 — daily volume / float turnover (higher is more liquid)

    Classification thresholds
    -------------------------
    - >= 0.65: "high"
    - >= 0.35: "medium"
    - <  0.35: "low"
    """

    def __init__(
        self,
        spread_weight: float = 0.40,
        depth_weight: float = 0.35,
        turnover_weight: float = 0.25,
        # Anchors for normalisation
        max_spread_bps: float = 200.0,   # spread >= this → score 0
        max_oi: float = 100_000.0,       # OI >= this → depth score 1
        max_volume: float = 10_000_000.0,  # volume >= this → turnover score 1
    ) -> None:
        total = spread_weight + depth_weight + turnover_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError("weights must sum to 1.0")
        self.spread_weight = spread_weight
        self.depth_weight = depth_weight
        self.turnover_weight = turnover_weight
        self.max_spread_bps = max_spread_bps
        self.max_oi = max_oi
        self.max_volume = max_volume

    def score(
        self,
        symbol: str,
        spread_bps: Optional[float] = None,
        open_interest: Optional[float] = None,
        daily_volume: Optional[float] = None,
    ) -> LiquidityScoreResult:
        """Compute composite liquidity score.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        spread_bps:
            Effective bid-ask spread in basis points.  None → neutral (0.5).
        open_interest:
            Total open interest (options contracts or shares).  None → neutral.
        daily_volume:
            Daily traded volume (shares or contracts).  None → neutral.

        Returns
        -------
        LiquidityScoreResult
        """
        # Spread score: 0 spread → 1.0, spread >= max → 0.0
        if spread_bps is not None:
            spread_score = max(0.0, 1.0 - spread_bps / self.max_spread_bps)
        else:
            spread_score = 0.5  # neutral when unknown

        # Depth score: higher OI → higher score
        if open_interest is not None:
            depth_score = min(1.0, open_interest / self.max_oi)
        else:
            depth_score = 0.5

        # Turnover score: higher volume → higher score
        if daily_volume is not None:
            turnover_score = min(1.0, daily_volume / self.max_volume)
        else:
            turnover_score = 0.5

        composite = (
            self.spread_weight * spread_score
            + self.depth_weight * depth_score
            + self.turnover_weight * turnover_score
        )
        composite = max(0.0, min(1.0, composite))

        if composite >= 0.65:
            classification = "high"
        elif composite >= 0.35:
            classification = "medium"
        else:
            classification = "low"

        return LiquidityScoreResult(
            symbol=symbol,
            composite_score=round(composite, 4),
            spread_score=round(spread_score, 4),
            depth_score=round(depth_score, 4),
            turnover_score=round(turnover_score, 4),
            classification=classification,
            components={
                "spread_bps": spread_bps,
                "open_interest": open_interest,
                "daily_volume": daily_volume,
            },
        )

    def from_market_data(
        self,
        symbol: str,
        market_data: Dict[str, Any],
    ) -> LiquidityScoreResult:
        """Convenience wrapper: extract inputs from a ``MarketEnricher`` dict.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        market_data:
            Single-symbol dict from ``MarketEnricher.enrich_symbols()[sym]``.

        Returns
        -------
        LiquidityScoreResult
        """
        chain = market_data.get("options_chain") or {}
        spread_pct = chain.get("avg_bid_ask_spread_pct") if isinstance(chain, dict) else None
        price = market_data.get("last_close") or market_data.get("last_price")
        spread_bps: Optional[float] = None
        if spread_pct is not None and price and price > 0:
            spread_bps = float(spread_pct) * 10_000.0

        # Open interest from options chain or market info
        oi = None
        if isinstance(chain, dict):
            raw_oi = chain.get("avg_open_interest")
            if raw_oi is None:
                call_oi = market_data.get("call_oi")
                put_oi = market_data.get("put_oi")
                if call_oi is not None or put_oi is not None:
                    raw_oi = (call_oi or 0) + (put_oi or 0)
            oi = raw_oi if raw_oi else None  # treat 0 as "unknown"

        volume = market_data.get("volume") or market_data.get("avg_volume")
        volume = volume if volume else None  # treat 0 as "unknown"

        return self.score(
            symbol=symbol,
            spread_bps=spread_bps,
            open_interest=float(oi) if oi is not None else None,
            daily_volume=float(volume) if volume is not None else None,
        )
