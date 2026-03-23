"""Sentiment momentum and mean-reversion detector for ROT.

Analyses the *dynamics* of a sentiment time-series rather than its absolute
level.  Key capabilities:

* **Sentiment momentum score**: An exponentially-weighted moving average (EWMA)
  of consecutive sentiment changes, revealing whether positive (or negative)
  sentiment is *accelerating* or *decelerating*.
* **Mean-reversion signal**: Detects when sentiment has stretched far from its
  long-run mean and is likely to snap back — the opposite of momentum.
* **Regime classifier**: Labels each observation as one of four regimes:
  ``trending_bull``, ``trending_bear``, ``reverting_up``, ``reverting_down``,
  or ``neutral``.
* **Divergence detector**: Flags when price trend and sentiment momentum diverge
  (potential early warning of price reversal).
* **Cross-asset sentiment spread**: Computes the spread between two tickers'
  sentiment momentum, a factor used in pairs-trade idea generation.

All computations are done in pure Python with ``numpy`` for vectorised ops
where needed.  No network I/O.

Example::

    from rot.sentiment.momentum_detector import SentimentMomentumDetector

    detector = SentimentMomentumDetector(ewma_span=10, zscore_window=30)
    history = [0.2, 0.3, 0.5, 0.6, 0.55, 0.4, 0.2, -0.1, -0.3]
    analysis = detector.analyse("AAPL", history)
    print(analysis.regime, analysis.momentum_score, analysis.reversion_signal)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SentimentRegime(str, Enum):
    """Market sentiment regime classification."""

    TRENDING_BULL = "trending_bull"
    TRENDING_BEAR = "trending_bear"
    REVERTING_UP = "reverting_up"      # mean-reversion from bear
    REVERTING_DOWN = "reverting_down"  # mean-reversion from bull
    NEUTRAL = "neutral"


class MomentumSignal(str, Enum):
    """Directional momentum signal."""

    STRONG_BULL = "strong_bull"
    BULL = "bull"
    NEUTRAL = "neutral"
    BEAR = "bear"
    STRONG_BEAR = "strong_bear"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MomentumAnalysis:
    """Full momentum and mean-reversion analysis for one ticker."""

    ticker: str
    # Raw inputs
    history: List[float]
    # Momentum
    momentum_score: float          # EWMA of consecutive differences
    momentum_signal: MomentumSignal
    momentum_zscore: float         # z-score of momentum vs its own history
    momentum_acceleration: float   # 2nd derivative — is momentum speeding up?
    # Mean-reversion
    sentiment_zscore: float        # z-score of current sentiment vs window mean
    reversion_signal: float        # positive = expect upward reversion
    is_stretched: bool             # True when |sentiment_zscore| > threshold
    # Regime
    regime: SentimentRegime
    # Additional stats
    rolling_mean: float
    rolling_std: float
    ewma_value: float              # current EWMA sentiment level
    half_life_estimate: float      # estimated mean-reversion half-life (observations)
    # Divergence (optional — set by divergence_check())
    price_divergence: Optional[float] = None
    divergence_flag: bool = False


@dataclass
class PairSpreadAnalysis:
    """Sentiment momentum spread between two tickers."""

    ticker_a: str
    ticker_b: str
    momentum_a: float
    momentum_b: float
    spread: float                  # momentum_a - momentum_b
    spread_zscore: float           # z-score vs historical spread
    regime_a: SentimentRegime
    regime_b: SentimentRegime
    long_ticker: str               # ticker with higher momentum
    short_ticker: str
    signal_strength: float         # |spread_zscore| normalised to [0, 1]


# ---------------------------------------------------------------------------
# Helper maths
# ---------------------------------------------------------------------------


def _ewma(series: np.ndarray, span: int) -> np.ndarray:
    """Compute EWMA with given span (alpha = 2/(span+1))."""
    alpha = 2.0 / (span + 1)
    result = np.zeros_like(series, dtype=float)
    if len(series) == 0:
        return result
    result[0] = series[0]
    for i in range(1, len(series)):
        result[i] = alpha * series[i] + (1.0 - alpha) * result[i - 1]
    return result


def _rolling_zscore(series: np.ndarray, window: int) -> np.ndarray:
    """Compute rolling z-score at each point using a trailing window."""
    n = len(series)
    zscores = np.zeros(n)
    for i in range(n):
        lo = max(0, i - window + 1)
        window_slice = series[lo : i + 1]
        mean = np.mean(window_slice)
        std = np.std(window_slice)
        zscores[i] = (series[i] - mean) / std if std > 1e-10 else 0.0
    return zscores


def _half_life(series: np.ndarray) -> float:
    """Estimate mean-reversion half-life via AR(1) regression.

    The half-life is ``-ln(2) / ln(|rho|)`` where ``rho`` is the lag-1
    autocorrelation.  Returns ``inf`` for pure random walk (|rho| >= 1).
    """
    if len(series) < 4:
        return float("inf")
    y = series[1:]
    x = series[:-1]
    # OLS: y = alpha + rho*x
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    cov = np.mean((x - x_mean) * (y - y_mean))
    var = np.mean((x - x_mean) ** 2)
    rho = cov / var if var > 1e-10 else 1.0
    if abs(rho) >= 1.0:
        return float("inf")
    return -math.log(2.0) / math.log(abs(rho))


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class SentimentMomentumDetector:
    """Detects sentiment momentum and mean-reversion dynamics.

    Args:
        ewma_span: EWMA span for the momentum smoothing (default: 10).
        zscore_window: Rolling window for z-score computation (default: 30).
        stretch_threshold: |z-score| above which sentiment is "stretched" (default: 1.5).
        strong_signal_threshold: |momentum_zscore| above which signal is "strong" (default: 1.0).
    """

    def __init__(
        self,
        ewma_span: int = 10,
        zscore_window: int = 30,
        stretch_threshold: float = 1.5,
        strong_signal_threshold: float = 1.0,
    ) -> None:
        self.ewma_span = max(ewma_span, 2)
        self.zscore_window = max(zscore_window, 5)
        self.stretch_threshold = stretch_threshold
        self.strong_signal_threshold = strong_signal_threshold

    # ------------------------------------------------------------------
    # Main analysis entry point
    # ------------------------------------------------------------------

    def analyse(self, ticker: str, sentiment_history: Sequence[float]) -> MomentumAnalysis:
        """Compute momentum and mean-reversion analysis for a ticker's sentiment history.

        Args:
            ticker: Ticker symbol (for labelling).
            sentiment_history: Ordered sequence of sentiment scores (oldest first),
                               each in [-1, 1].

        Returns:
            :class:`MomentumAnalysis` with all computed fields.
        """
        arr = np.array(list(sentiment_history), dtype=float)
        n = len(arr)

        if n == 0:
            return self._empty_analysis(ticker)

        # ── EWMA level ────────────────────────────────────────────────────────
        ewma_arr = _ewma(arr, self.ewma_span)
        ewma_value = float(ewma_arr[-1])

        # ── Sentiment z-score (current level vs rolling mean) ─────────────────
        window = min(self.zscore_window, n)
        rolling_window = arr[max(0, n - window):]
        rolling_mean = float(np.mean(rolling_window))
        rolling_std = float(np.std(rolling_window))
        sentiment_zscore = (
            (arr[-1] - rolling_mean) / rolling_std if rolling_std > 1e-10 else 0.0
        )

        # ── Momentum: EWMA of first differences ───────────────────────────────
        if n >= 2:
            diffs = np.diff(arr)
            ewma_diffs = _ewma(diffs, self.ewma_span)
            momentum_score = float(ewma_diffs[-1])
        else:
            diffs = np.array([0.0])
            ewma_diffs = np.array([0.0])
            momentum_score = 0.0

        # ── Momentum z-score ──────────────────────────────────────────────────
        if len(ewma_diffs) >= 2:
            mom_window = min(self.zscore_window, len(ewma_diffs))
            mom_slice = ewma_diffs[max(0, len(ewma_diffs) - mom_window):]
            mom_mean = float(np.mean(mom_slice))
            mom_std = float(np.std(mom_slice))
            momentum_zscore = (momentum_score - mom_mean) / mom_std if mom_std > 1e-10 else 0.0
        else:
            momentum_zscore = 0.0

        # ── Momentum acceleration (second derivative of EWMA) ─────────────────
        if len(ewma_diffs) >= 2:
            ewma_diffs2 = _ewma(np.diff(ewma_diffs), self.ewma_span)
            momentum_acceleration = float(ewma_diffs2[-1]) if len(ewma_diffs2) > 0 else 0.0
        else:
            momentum_acceleration = 0.0

        # ── Reversion signal ─────────────────────────────────────────────────
        # When sentiment is stretched above mean (high z-score), expect reversion down.
        # Signal: -sentiment_zscore (negative = expect down-reversion, positive = up).
        reversion_signal = -sentiment_zscore

        # ── Half-life ─────────────────────────────────────────────────────────
        half_life_estimate = _half_life(arr)

        # ── Stretched flag ───────────────────────────────────────────────────
        is_stretched = abs(sentiment_zscore) > self.stretch_threshold

        # ── Momentum signal label ────────────────────────────────────────────
        momentum_signal = self._classify_momentum(momentum_zscore)

        # ── Regime ───────────────────────────────────────────────────────────
        regime = self._classify_regime(
            momentum_score=momentum_score,
            momentum_zscore=momentum_zscore,
            sentiment_zscore=sentiment_zscore,
            is_stretched=is_stretched,
        )

        return MomentumAnalysis(
            ticker=ticker,
            history=list(arr),
            momentum_score=momentum_score,
            momentum_signal=momentum_signal,
            momentum_zscore=momentum_zscore,
            momentum_acceleration=momentum_acceleration,
            sentiment_zscore=sentiment_zscore,
            reversion_signal=reversion_signal,
            is_stretched=is_stretched,
            regime=regime,
            rolling_mean=rolling_mean,
            rolling_std=rolling_std,
            ewma_value=ewma_value,
            half_life_estimate=half_life_estimate,
        )

    # ------------------------------------------------------------------
    # Divergence detection
    # ------------------------------------------------------------------

    def divergence_check(
        self,
        analysis: MomentumAnalysis,
        price_returns: Sequence[float],
        window: int = 10,
    ) -> MomentumAnalysis:
        """Check for sentiment/price divergence and annotate the analysis.

        A divergence occurs when sentiment momentum and price momentum point in
        opposite directions over the recent ``window`` observations.

        Args:
            analysis: Previously computed :class:`MomentumAnalysis`.
            price_returns: Recent price log-returns (same length as sentiment history
                           or at least ``window`` long).
            window: Look-back window for price momentum.

        Returns:
            The same analysis object with ``price_divergence`` and
            ``divergence_flag`` populated.
        """
        price_arr = np.array(list(price_returns), dtype=float)
        if len(price_arr) < 2:
            return analysis

        # Price momentum: cumulative return over window
        pw = min(window, len(price_arr))
        price_momentum = float(np.sum(price_arr[-pw:]))

        # Divergence = sentiment_momentum and price_momentum have opposite signs
        sent_mom = analysis.momentum_score
        divergence = sent_mom * price_momentum  # negative = divergence

        analysis.price_divergence = divergence
        analysis.divergence_flag = divergence < -1e-6

        if analysis.divergence_flag:
            log.debug(
                "Sentiment/price divergence for %s: sent_mom=%.4f price_mom=%.4f",
                analysis.ticker,
                sent_mom,
                price_momentum,
            )

        return analysis

    # ------------------------------------------------------------------
    # Cross-asset spread
    # ------------------------------------------------------------------

    def pair_spread(
        self,
        ticker_a: str,
        history_a: Sequence[float],
        ticker_b: str,
        history_b: Sequence[float],
        spread_history: Optional[Sequence[float]] = None,
    ) -> PairSpreadAnalysis:
        """Compute the sentiment momentum spread between two assets.

        Args:
            ticker_a, ticker_b: Ticker labels.
            history_a, history_b: Sentiment histories for each ticker.
            spread_history: Historical spread values for z-scoring. If ``None``,
                            a one-point z-score of 0.0 is returned.

        Returns:
            :class:`PairSpreadAnalysis` describing the momentum spread.
        """
        analysis_a = self.analyse(ticker_a, history_a)
        analysis_b = self.analyse(ticker_b, history_b)

        spread = analysis_a.momentum_score - analysis_b.momentum_score

        if spread_history and len(spread_history) > 1:
            hist_arr = np.array(list(spread_history), dtype=float)
            sh_mean = float(np.mean(hist_arr))
            sh_std = float(np.std(hist_arr))
            spread_zscore = (spread - sh_mean) / sh_std if sh_std > 1e-10 else 0.0
        else:
            spread_zscore = 0.0

        signal_strength = min(abs(spread_zscore) / max(self.strong_signal_threshold, 1e-10), 1.0)

        if spread >= 0:
            long_ticker, short_ticker = ticker_a, ticker_b
        else:
            long_ticker, short_ticker = ticker_b, ticker_a

        return PairSpreadAnalysis(
            ticker_a=ticker_a,
            ticker_b=ticker_b,
            momentum_a=analysis_a.momentum_score,
            momentum_b=analysis_b.momentum_score,
            spread=spread,
            spread_zscore=spread_zscore,
            regime_a=analysis_a.regime,
            regime_b=analysis_b.regime,
            long_ticker=long_ticker,
            short_ticker=short_ticker,
            signal_strength=signal_strength,
        )

    # ------------------------------------------------------------------
    # Batch analysis
    # ------------------------------------------------------------------

    def analyse_batch(
        self, ticker_histories: Dict[str, Sequence[float]]
    ) -> Dict[str, MomentumAnalysis]:
        """Analyse multiple tickers at once.

        Args:
            ticker_histories: Mapping from ticker → sentiment history.

        Returns:
            Mapping from ticker → :class:`MomentumAnalysis`.
        """
        return {
            ticker: self.analyse(ticker, history)
            for ticker, history in ticker_histories.items()
        }

    def top_momentum_tickers(
        self,
        ticker_histories: Dict[str, Sequence[float]],
        n: int = 5,
        direction: str = "bull",
    ) -> List[MomentumAnalysis]:
        """Return the top-N tickers by momentum score in the given direction.

        Args:
            ticker_histories: Mapping from ticker → sentiment history.
            n: How many top tickers to return.
            direction: ``"bull"`` (highest momentum) or ``"bear"`` (most negative).

        Returns:
            Sorted list of :class:`MomentumAnalysis` objects.
        """
        all_analyses = list(self.analyse_batch(ticker_histories).values())
        reverse = direction.lower() != "bear"
        sorted_analyses = sorted(
            all_analyses,
            key=lambda a: a.momentum_score,
            reverse=reverse,
        )
        return sorted_analyses[:n]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify_momentum(self, momentum_zscore: float) -> MomentumSignal:
        """Map a momentum z-score to a :class:`MomentumSignal`."""
        thr = self.strong_signal_threshold
        if momentum_zscore >= thr:
            return MomentumSignal.STRONG_BULL
        elif momentum_zscore >= 0.3:
            return MomentumSignal.BULL
        elif momentum_zscore <= -thr:
            return MomentumSignal.STRONG_BEAR
        elif momentum_zscore <= -0.3:
            return MomentumSignal.BEAR
        return MomentumSignal.NEUTRAL

    def _classify_regime(
        self,
        momentum_score: float,
        momentum_zscore: float,
        sentiment_zscore: float,
        is_stretched: bool,
    ) -> SentimentRegime:
        """Classify the current sentiment regime."""
        thr = 0.3  # minimum momentum z-score to be "trending"

        if is_stretched:
            # Stretched and sentiment above mean → expect downward reversion
            if sentiment_zscore > self.stretch_threshold:
                return SentimentRegime.REVERTING_DOWN
            # Stretched and sentiment below mean → expect upward reversion
            elif sentiment_zscore < -self.stretch_threshold:
                return SentimentRegime.REVERTING_UP

        if momentum_zscore >= thr and momentum_score > 0:
            return SentimentRegime.TRENDING_BULL
        if momentum_zscore <= -thr and momentum_score < 0:
            return SentimentRegime.TRENDING_BEAR

        return SentimentRegime.NEUTRAL

    def _empty_analysis(self, ticker: str) -> MomentumAnalysis:
        """Return a neutral empty analysis for a ticker with no history."""
        return MomentumAnalysis(
            ticker=ticker,
            history=[],
            momentum_score=0.0,
            momentum_signal=MomentumSignal.NEUTRAL,
            momentum_zscore=0.0,
            momentum_acceleration=0.0,
            sentiment_zscore=0.0,
            reversion_signal=0.0,
            is_stretched=False,
            regime=SentimentRegime.NEUTRAL,
            rolling_mean=0.0,
            rolling_std=0.0,
            ewma_value=0.0,
            half_life_estimate=float("inf"),
        )
