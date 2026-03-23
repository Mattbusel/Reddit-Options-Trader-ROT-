"""Narrative momentum tracker for Reddit stock stories.

Tracks the dominant narrative for each ticker across Reddit posts, measures
whether the narrative is gaining or losing traction, and detects regime
changes in narrative type (e.g. FOMO -> fear, speculation -> fundamentals).
Maintains a historical narrative database backed by an in-memory store with
optional JSON persistence.

Narrative taxonomy
------------------
* ``"fomo"`` -- fear of missing out, momentum chasing.
* ``"fear"`` -- panic, loss worry, put buying.
* ``"speculation"`` -- unverified rumours, hype, expected catalysts.
* ``"fundamentals"`` -- earnings, revenue, PE ratio discussion.
* ``"squeeze"`` -- short squeeze, gamma squeeze setup.
* ``"neutral"`` -- no dominant narrative detected.

Example::

    from rot.nlp.narrative import NarrativeTracker

    tracker = NarrativeTracker()
    tracker.ingest(
        ticker="GME",
        post_text="To the moon! Short interest is still huge!",
        sentiment=0.9,
        post_id="t3_xyz",
    )
    state = tracker.current_state("GME")
    print(state.dominant_narrative, state.momentum, state.regime_change)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Narrative keyword mappings
# ---------------------------------------------------------------------------

_NARRATIVE_KEYWORDS: Dict[str, List[str]] = {
    "fomo": [
        "moon", "lambo", "apes", "hold", "diamond hands", "tendies",
        "yolo", "all in", "fomo", "missing out", "rocket", "100x",
    ],
    "fear": [
        "crash", "dump", "puts", "bearish", "capitulate", "sell off",
        "panic", "fear", "margin call", "going to zero", "short",
        "rekt", "bleeding", "pain",
    ],
    "speculation": [
        "rumour", "rumor", "catalyst", "leak", "merger", "acquisition",
        "fda", "earnings beat", "whisper", "hear", "allegedly",
        "sources say", "expect", "hype", "potential",
    ],
    "fundamentals": [
        "revenue", "earnings", "pe ratio", "eps", "profit", "balance sheet",
        "debt", "cash flow", "dividend", "guidance", "margin", "growth rate",
        "valuation", "intrinsic value", "dcf", "analyst",
    ],
    "squeeze": [
        "short squeeze", "gamma squeeze", "short interest", "float",
        "days to cover", "si%", "borrow rate", "ftd", "fails to deliver",
        "squeeze play",
    ],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class NarrativeEvent:
    """A single narrative data point ingested from a Reddit post.

    Attributes:
        ticker: Ticker symbol.
        post_id: Reddit post identifier.
        timestamp: Unix timestamp.
        sentiment: Post sentiment in [-1, 1].
        detected_narratives: Dict of narrative label -> keyword hit score.
        dominant: Dominant narrative label for this post.
    """

    ticker: str
    post_id: str
    timestamp: float
    sentiment: float
    detected_narratives: Dict[str, float]
    dominant: str


@dataclass
class NarrativeState:
    """Current narrative state for a ticker.

    Attributes:
        ticker: Ticker symbol.
        dominant_narrative: Current dominant narrative label.
        momentum: Rate of change of the dominant narrative's score
            (positive = gaining traction, negative = fading).
        traction_score: Absolute strength of the current narrative in [0, 1].
        regime_change: True when the dominant narrative has changed in the
            last observation window.
        previous_narrative: The narrative label that was dominant before the
            current one (if a change occurred).
        post_count: Total posts analysed for this ticker.
        updated_at: Unix timestamp of last update.
    """

    ticker: str
    dominant_narrative: str
    momentum: float
    traction_score: float
    regime_change: bool
    previous_narrative: Optional[str]
    post_count: int
    updated_at: float


# ---------------------------------------------------------------------------
# Narrative tracker
# ---------------------------------------------------------------------------


class NarrativeTracker:
    """Tracks narrative momentum and regime changes across Reddit tickers.

    Args:
        window_size: Number of recent events to use for momentum calculation
            (default 20).
        regime_change_threshold: Minimum shift in narrative dominance fraction
            to trigger a regime change flag (default 0.2).
        persistence_path: Optional path to JSON file for persistent storage.
            State is loaded on init and saved on each :meth:`ingest` call.
        momentum_ema_alpha: EMA alpha for narrative score smoothing.
    """

    def __init__(
        self,
        window_size: int = 20,
        regime_change_threshold: float = 0.2,
        persistence_path: Optional[str] = None,
        momentum_ema_alpha: float = 0.3,
    ) -> None:
        self.window_size = window_size
        self.regime_change_threshold = regime_change_threshold
        self.persistence_path = persistence_path
        self.ema_alpha = momentum_ema_alpha

        # ticker -> list of NarrativeEvent (chronological)
        self._history: Dict[str, List[NarrativeEvent]] = {}
        # ticker -> smoothed narrative scores (EMA)
        self._ema_scores: Dict[str, Dict[str, float]] = {}
        # ticker -> last dominant narrative
        self._last_dominant: Dict[str, str] = {}

        if persistence_path:
            self._load(persistence_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(
        self,
        ticker: str,
        post_text: str,
        sentiment: float,
        post_id: str = "",
        timestamp: Optional[float] = None,
    ) -> NarrativeEvent:
        """Process a Reddit post and update the ticker's narrative state.

        Args:
            ticker: Ticker symbol the post discusses.
            post_text: Full text content of the post (title + body).
            sentiment: Pre-computed sentiment in [-1, 1].
            post_id: Optional Reddit post identifier.
            timestamp: Unix timestamp; defaults to now.

        Returns:
            :class:`NarrativeEvent` for the post.
        """
        ts = timestamp or time.time()
        scores = self._score_narratives(post_text.lower(), sentiment)
        dominant = max(scores, key=scores.get) if scores else "neutral"

        event = NarrativeEvent(
            ticker=ticker,
            post_id=post_id or f"auto_{int(ts)}",
            timestamp=ts,
            sentiment=sentiment,
            detected_narratives=scores,
            dominant=dominant,
        )

        history = self._history.setdefault(ticker, [])
        history.append(event)
        if len(history) > 10_000:
            history.pop(0)

        # Update EMA scores
        ema = self._ema_scores.setdefault(
            ticker, {k: 0.0 for k in _NARRATIVE_KEYWORDS}
        )
        for label, score in scores.items():
            ema[label] = (1 - self.ema_alpha) * ema.get(label, 0.0) + self.ema_alpha * score

        if self.persistence_path:
            self._save(self.persistence_path)

        log.debug(
            "narrative_tracker.ingested",
            ticker=ticker,
            dominant=dominant,
            scores={k: round(v, 3) for k, v in scores.items()},
        )
        return event

    def current_state(self, ticker: str) -> Optional[NarrativeState]:
        """Return the current narrative state for *ticker*.

        Args:
            ticker: Ticker symbol.

        Returns:
            :class:`NarrativeState` or ``None`` when no data exists.
        """
        history = self._history.get(ticker, [])
        if not history:
            return None

        ema = self._ema_scores.get(ticker, {})
        if not ema:
            return None

        dominant = max(ema, key=ema.get)
        traction = ema[dominant]

        # Momentum: slope of dominant narrative's EMA over recent window
        window = history[-self.window_size :]
        momentum = self._compute_momentum(ticker, dominant, window)

        # Regime change detection
        prev_dominant = self._last_dominant.get(ticker)
        regime_change = False
        if prev_dominant and prev_dominant != dominant:
            prev_score = ema.get(prev_dominant, 0.0)
            if abs(traction - prev_score) >= self.regime_change_threshold:
                regime_change = True
                log.info(
                    "narrative_tracker.regime_change",
                    ticker=ticker,
                    from_narrative=prev_dominant,
                    to_narrative=dominant,
                )
        self._last_dominant[ticker] = dominant

        return NarrativeState(
            ticker=ticker,
            dominant_narrative=dominant,
            momentum=round(momentum, 4),
            traction_score=round(traction, 4),
            regime_change=regime_change,
            previous_narrative=prev_dominant if regime_change else None,
            post_count=len(history),
            updated_at=history[-1].timestamp,
        )

    def ticker_timeline(
        self, ticker: str, max_events: int = 100
    ) -> List[NarrativeEvent]:
        """Return chronological narrative events for *ticker*.

        Args:
            ticker: Ticker symbol.
            max_events: Maximum number of events to return (most recent).

        Returns:
            List of :class:`NarrativeEvent` instances.
        """
        return self._history.get(ticker, [])[-max_events:]

    def top_narratives(self, n: int = 10) -> List[Tuple[str, str, float]]:
        """Return the n tickers with the strongest current narrative momentum.

        Returns:
            List of ``(ticker, narrative, momentum)`` tuples sorted by
            |momentum| descending.
        """
        results: List[Tuple[str, str, float]] = []
        for ticker in self._history:
            state = self.current_state(ticker)
            if state:
                results.append(
                    (ticker, state.dominant_narrative, abs(state.momentum))
                )
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:n]

    def all_tickers(self) -> List[str]:
        """Return all tickers with at least one recorded event."""
        return list(self._history.keys())

    # ------------------------------------------------------------------
    # Narrative scoring
    # ------------------------------------------------------------------

    def _score_narratives(
        self, text: str, sentiment: float
    ) -> Dict[str, float]:
        """Score each narrative label based on keyword hits in *text*.

        Args:
            text: Lowercase post text.
            sentiment: Post sentiment used to weight certain narratives.

        Returns:
            Dict of narrative label -> score in [0, 1].
        """
        raw: Dict[str, float] = {}
        for label, keywords in _NARRATIVE_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in text)
            raw[label] = hits / max(len(keywords), 1)

        # Sentiment modifier: strong positive boosts fomo/squeeze,
        # strong negative boosts fear
        if sentiment > 0.5:
            raw["fomo"] = raw.get("fomo", 0.0) * 1.3
            raw["squeeze"] = raw.get("squeeze", 0.0) * 1.2
        elif sentiment < -0.5:
            raw["fear"] = raw.get("fear", 0.0) * 1.4

        # Normalise to [0, 1]
        total = sum(raw.values())
        if total < 1e-9:
            return {label: 0.0 for label in _NARRATIVE_KEYWORDS}
        return {k: v / total for k, v in raw.items()}

    # ------------------------------------------------------------------
    # Momentum computation
    # ------------------------------------------------------------------

    def _compute_momentum(
        self,
        ticker: str,
        dominant: str,
        window: List[NarrativeEvent],
    ) -> float:
        """Estimate momentum as the linear trend slope of dominant narrative scores.

        Returns:
            Slope in units of score/event (positive = gaining traction).
        """
        scores = [e.detected_narratives.get(dominant, 0.0) for e in window]
        n = len(scores)
        if n < 2:
            return 0.0

        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(scores) / n
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, scores))
        den = sum((x - x_mean) ** 2 for x in xs)
        return num / den if den > 1e-12 else 0.0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self, path: str) -> None:
        """Save EMA scores and last dominant labels to JSON."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            data = {
                "ema_scores": self._ema_scores,
                "last_dominant": self._last_dominant,
            }
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
        except Exception as exc:
            log.warning("narrative_tracker.save_error", error=str(exc))

    def _load(self, path: str) -> None:
        """Load persisted EMA scores from JSON."""
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self._ema_scores = data.get("ema_scores", {})
            self._last_dominant = data.get("last_dominant", {})
            log.info("narrative_tracker.loaded", path=path)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning("narrative_tracker.load_error", path=path, error=str(exc))
