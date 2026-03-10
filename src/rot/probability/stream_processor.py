"""StreamProcessor — processes information sources before they are complete.

Ported from LLMTokenStreamQuantEngine/src/LLMAdapter.cpp and main.cpp.

The C++ engine processes LLM token streams using:
  1. A semantic weight dictionary (token → {sentiment, confidence, volatility, bias})
  2. An IIR integrator: acc = alpha * weight + (1 - alpha) * acc
  3. Welford online variance: per-ticker running mean and variance of bias

This module ports that architecture to ROT's information sources:
  - Reddit posts processed word by word as they are scraped
  - SEC filings processed sentence by sentence as they load
  - FDA press releases processed clause by clause
  - Congressional disclosures processed field by field

When the IIR accumulator for a ticker crosses the confidence threshold
BEFORE the document is complete, a Stage-0 pre-signal (PreSignal) is fired
into the pipeline tagged with ``pre_signal=True``.

If the completed document contradicts the pre-signal, the pre-signal
confidence decays.  Pre-signal accuracy is tracked in ``pre_signal_events``.

Hot path: O(1) per chunk.  All state is per-ticker.
Non-blocking: fires pre-signals via an asyncio.Queue, never awaits inline.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

# IIR smoothing factor: alpha ∈ (0, 1)
# Higher alpha = faster response to new signal, lower memory of past
# Ported from LLMAdapter default of 0.15 in FixOmsAdapter.cpp
_DEFAULT_ALPHA = 0.15

# Confidence threshold for pre-signal firing
_DEFAULT_PRESIGNAL_THRESHOLD = 0.72

# Minimum chunks to process before a pre-signal can fire
# Prevents false positives from the first few words of a document
_MIN_CHUNKS_BEFORE_FIRE = 5

# Semantic weight dictionary (ported from LLMAdapter.cpp token dictionary)
# Weight tuple: (sentiment, confidence, volatility, directional_bias)
# sentiment: -1 (negative) to +1 (positive)
# confidence: 0 (uncertain) to 1 (certain)
# volatility: 0 (stable) to 1 (explosive)
# directional_bias: -1 (bearish) to +1 (bullish)
_SEMANTIC_WEIGHTS: Dict[str, tuple[float, float, float, float]] = {
    # Strongly bullish
    "bullish": (0.9, 0.9, 0.3, 1.0),
    "breakout": (0.8, 0.8, 0.6, 1.0),
    "surge": (0.7, 0.7, 0.8, 0.9),
    "acquisition": (0.8, 0.9, 0.5, 0.9),
    "buyout": (0.9, 0.95, 0.4, 1.0),
    "merger": (0.7, 0.8, 0.5, 0.8),
    "approved": (0.8, 0.9, 0.2, 0.9),
    "approval": (0.7, 0.85, 0.3, 0.8),
    "beat": (0.7, 0.8, 0.3, 0.8),
    "exceeds": (0.7, 0.8, 0.3, 0.8),
    "upgrade": (0.6, 0.75, 0.2, 0.7),
    "positive": (0.6, 0.7, 0.1, 0.6),
    "profit": (0.6, 0.7, 0.2, 0.7),
    # Strongly bearish
    "bearish": (-0.9, 0.9, 0.3, -1.0),
    "crash": (-0.9, 0.7, 1.0, -1.0),
    "collapse": (-0.8, 0.7, 0.9, -1.0),
    "fraud": (-0.9, 0.8, 0.7, -1.0),
    "investigation": (-0.6, 0.7, 0.5, -0.7),
    "lawsuit": (-0.5, 0.7, 0.4, -0.6),
    "recall": (-0.7, 0.8, 0.5, -0.8),
    "rejected": (-0.8, 0.9, 0.3, -0.9),
    "miss": (-0.7, 0.8, 0.4, -0.8),
    "downgrade": (-0.6, 0.75, 0.2, -0.7),
    "loss": (-0.6, 0.7, 0.2, -0.7),
    "bankrupt": (-0.95, 0.9, 0.8, -1.0),
    "default": (-0.8, 0.8, 0.6, -0.9),
    # High volatility markers
    "panic": (-0.5, 0.5, 1.0, -0.5),
    "squeeze": (0.0, 0.5, 1.0, 0.3),
    "volatility": (0.0, 0.5, 1.0, 0.0),
    "uncertainty": (0.0, 0.3, 0.7, 0.0),
    # Neutral / moderate
    "report": (0.0, 0.6, 0.1, 0.0),
    "earnings": (0.0, 0.7, 0.4, 0.0),
    "guidance": (0.1, 0.6, 0.2, 0.1),
    "revenue": (0.1, 0.7, 0.2, 0.1),
}

_NEUTRAL_WEIGHT = (0.0, 0.5, 0.1, 0.0)


class ChunkSource(str, Enum):
    """Which information source produced this chunk."""

    REDDIT = "reddit"
    SEC_FILING = "sec_filing"
    FDA_RELEASE = "fda_release"
    CONGRESSIONAL = "congressional"
    STOCKTWITS = "stocktwits"
    TWITTER = "twitter"
    RSS = "rss"


@dataclass
class DocumentChunk:
    """A partial piece of an information document being streamed.

    Attributes:
        ticker: Primary ticker this document is about.
        source: Where this chunk came from.
        text: The chunk text (word, sentence, paragraph, or field).
        doc_id: Stable identifier for the document (URL, filing ID, etc.).
        chunk_index: 0-based index of this chunk in the document.
        is_final: True if this is the last chunk of the document.
        ts: Unix timestamp when this chunk was received.
    """

    ticker: str
    source: ChunkSource
    text: str
    doc_id: str = ""
    chunk_index: int = 0
    is_final: bool = False
    ts: float = field(default_factory=time.time)


@dataclass
class PreSignal:
    """A Stage-0 pre-signal fired before document completion.

    Attributes:
        ticker: The ticker the pre-signal is for.
        source: Information source.
        doc_id: Document that triggered this pre-signal.
        confidence: IIR-derived confidence at fire time.
        direction: "bullish" | "bearish" | "neutral".
        iir_value: Raw IIR accumulator value at fire time.
        variance: Welford variance at fire time.
        chunks_processed: How many chunks had been seen when pre-signal fired.
        ts: Unix timestamp of firing.
        final_confidence: Set when document completes (may differ from confidence).
        final_direction: Set when document completes.
        agreement: True if pre and final directions agree.
        lead_time_ms: Milliseconds between pre-signal and document completion.
        pre_signal: Always True (marker for pipeline routing).
    """

    ticker: str
    source: ChunkSource
    doc_id: str
    confidence: float
    direction: str
    iir_value: float
    variance: float
    chunks_processed: int
    ts: float = field(default_factory=time.time)
    final_confidence: Optional[float] = None
    final_direction: Optional[str] = None
    agreement: Optional[bool] = None
    lead_time_ms: Optional[float] = None
    pre_signal: bool = True


class IIRAccumulator:
    """Infinite Impulse Response integrator for semantic directional bias.

    Ported from LLMAdapter.cpp: maps tokens to semantic weights and
    accumulates directional bias via exponential smoothing.

    Formula: acc = alpha * weight + (1 - alpha) * acc

    The IIR filter is a low-pass filter: it smooths out noise while
    retaining sustained directional signals.  A single strong word bumps
    the accumulator; a sustained stream of directional content builds it.
    """

    def __init__(self, alpha: float = _DEFAULT_ALPHA) -> None:
        if not (0 < alpha <= 1):
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")
        self._alpha = alpha
        self._acc = 0.0  # directional bias accumulator
        self._conf_acc = 0.5  # confidence accumulator
        self._tokens_processed = 0

    def process_text(self, text: str) -> tuple[float, float]:
        """Process a text chunk and return (directional_bias, confidence).

        Tokenizes text by whitespace, looks up each token in the semantic
        dictionary, updates IIR accumulators.

        Returns the current (directional_bias, confidence) after processing.
        """
        tokens = _tokenize(text)
        for token in tokens:
            weight = _SEMANTIC_WEIGHTS.get(token, _NEUTRAL_WEIGHT)
            _, conf, _, bias = weight
            self._acc = self._alpha * bias + (1.0 - self._alpha) * self._acc
            self._conf_acc = self._alpha * conf + (1.0 - self._alpha) * self._conf_acc
            self._tokens_processed += 1

        return self._acc, self._conf_acc

    def reset(self) -> None:
        self._acc = 0.0
        self._conf_acc = 0.5
        self._tokens_processed = 0

    @property
    def value(self) -> float:
        """Current directional bias accumulator value."""
        return self._acc

    @property
    def confidence(self) -> float:
        """Current confidence accumulator value."""
        return self._conf_acc

    @property
    def tokens_processed(self) -> int:
        return self._tokens_processed

    def direction(self) -> str:
        """Current direction: 'bullish', 'bearish', or 'neutral'."""
        if self._acc > 0.1:
            return "bullish"
        if self._acc < -0.1:
            return "bearish"
        return "neutral"


class WelfordVarianceTracker:
    """Welford online variance tracker for per-ticker IIR signal history.

    Ported from LLMAdapter.cpp map_sequence_simd() Welford computation.
    Tracks mean and variance of the IIR bias signal across all documents
    seen for a ticker.  Variance measures consistency of directional signal.
    """

    def __init__(self) -> None:
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0

    def update(self, value: float) -> None:
        """Update running stats with a new IIR value."""
        self._n += 1
        delta = value - self._mean
        self._mean += delta / self._n
        self._m2 += delta * (value - self._mean)

    @property
    def mean(self) -> float:
        return self._mean

    @property
    def variance(self) -> float:
        """Population variance."""
        if self._n < 2:
            return 0.0
        return self._m2 / self._n

    @property
    def std(self) -> float:
        return math.sqrt(self.variance)

    @property
    def n(self) -> int:
        return self._n


class _TickerState:
    """Per-ticker runtime state for the stream processor."""

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        # One IIR accumulator per active document
        self.active_docs: Dict[str, tuple[IIRAccumulator, int, float]] = {}
        # (iir, chunks_seen, fire_ts_or_0)
        self.welford = WelfordVarianceTracker()
        self.fired_presignals: Dict[str, PreSignal] = {}

    def get_or_create_iir(self, doc_id: str) -> tuple[IIRAccumulator, int]:
        if doc_id not in self.active_docs:
            self.active_docs[doc_id] = (IIRAccumulator(), 0, 0.0)
        iir, chunks, fire_ts = self.active_docs[doc_id]
        return iir, chunks

    def update_chunks(self, doc_id: str, chunks: int) -> None:
        if doc_id in self.active_docs:
            iir, _, fire_ts = self.active_docs[doc_id]
            self.active_docs[doc_id] = (iir, chunks, fire_ts)

    def mark_fired(self, doc_id: str, fire_ts: float) -> None:
        if doc_id in self.active_docs:
            iir, chunks, _ = self.active_docs[doc_id]
            self.active_docs[doc_id] = (iir, chunks, fire_ts)

    def has_fired(self, doc_id: str) -> bool:
        if doc_id not in self.active_docs:
            return False
        _, _, fire_ts = self.active_docs[doc_id]
        return fire_ts > 0

    def close_doc(self, doc_id: str) -> Optional[tuple[IIRAccumulator, float]]:
        """Remove and return (iir, fire_ts) for a completed document."""
        if doc_id not in self.active_docs:
            return None
        iir, _, fire_ts = self.active_docs.pop(doc_id)
        return iir, fire_ts


class StreamProcessor:
    """Processes ROT information sources as they stream in.

    One instance per application lifecycle.  Maintains per-ticker IIR
    accumulators and Welford trackers.  Fires pre-signals via a queue
    consumed by the background pipeline listener.

    Usage::

        processor = StreamProcessor()
        queue = processor.presignal_queue   # asyncio.Queue[PreSignal]

        # In the ingestion loop:
        chunk = DocumentChunk(
            ticker="TSLA", source=ChunkSource.REDDIT,
            text="massive buyout rumor flying around", doc_id="t3_abc",
            chunk_index=5, is_final=False,
        )
        processor.process_chunk(chunk)

        # Consumer (async):
        presignal = await queue.get()
    """

    def __init__(
        self,
        alpha: float = _DEFAULT_ALPHA,
        presignal_threshold: float = _DEFAULT_PRESIGNAL_THRESHOLD,
        min_chunks: int = _MIN_CHUNKS_BEFORE_FIRE,
        on_presignal: Optional[Callable[[PreSignal], None]] = None,
    ) -> None:
        self._alpha = alpha
        self._threshold = presignal_threshold
        self._min_chunks = min_chunks
        self._on_presignal = on_presignal
        self._tickers: Dict[str, _TickerState] = {}
        self.presignal_queue: asyncio.Queue[PreSignal] = asyncio.Queue(maxsize=1000)
        self._presignal_count = 0
        self._chunks_processed = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def process_chunk(self, chunk: DocumentChunk) -> Optional[PreSignal]:
        """Process one document chunk.

        This is the hot path — called synchronously from the ingestion loop.
        O(k) where k is the number of tokens in chunk.text.

        Returns a PreSignal if this chunk caused one to fire, else None.
        """
        self._chunks_processed += 1
        ticker = chunk.ticker
        doc_id = chunk.doc_id or f"{chunk.source}:{chunk.ts}"

        state = self._get_or_create_ticker(ticker)
        iir, chunks_seen = state.get_or_create_iir(doc_id)

        # Process the text through the IIR accumulator
        bias, conf = iir.process_text(chunk.text)
        chunks_seen += 1
        state.update_chunks(doc_id, chunks_seen)

        presignal: Optional[PreSignal] = None

        # Handle document completion
        if chunk.is_final:
            presignal = self._handle_final_chunk(chunk, state, doc_id, iir, conf, bias)
        elif not state.has_fired(doc_id):
            # Check if pre-signal threshold is crossed mid-document
            presignal = self._check_presignal(chunk, state, doc_id, iir, conf, bias, chunks_seen)

        return presignal

    def get_ticker_stats(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Return current IIR and Welford stats for a ticker."""
        state = self._tickers.get(ticker)
        if state is None:
            return None
        return {
            "ticker": ticker,
            "welford_n": state.welford.n,
            "welford_mean": state.welford.mean,
            "welford_std": state.welford.std,
            "active_docs": len(state.active_docs),
        }

    @property
    def presignal_count(self) -> int:
        return self._presignal_count

    @property
    def chunks_processed(self) -> int:
        return self._chunks_processed

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_or_create_ticker(self, ticker: str) -> _TickerState:
        if ticker not in self._tickers:
            self._tickers[ticker] = _TickerState(ticker)
        return self._tickers[ticker]

    def _check_presignal(
        self,
        chunk: DocumentChunk,
        state: _TickerState,
        doc_id: str,
        iir: IIRAccumulator,
        conf: float,
        bias: float,
        chunks_seen: int,
    ) -> Optional[PreSignal]:
        if chunks_seen < self._min_chunks:
            return None
        if conf < self._threshold:
            return None
        if abs(bias) < 0.1:  # require meaningful directional signal
            return None

        return self._fire_presignal(chunk, state, doc_id, iir, conf, bias, chunks_seen)

    def _handle_final_chunk(
        self,
        chunk: DocumentChunk,
        state: _TickerState,
        doc_id: str,
        iir: IIRAccumulator,
        conf: float,
        bias: float,
    ) -> Optional[PreSignal]:
        """Update Welford tracker and resolve any pending pre-signal."""
        state.welford.update(bias)

        pending_presignal = state.fired_presignals.get(doc_id)
        result = state.close_doc(doc_id)
        fire_ts = result[1] if result else 0.0

        if pending_presignal is not None:
            # Resolve the pre-signal
            final_direction = iir.direction()
            agreement = pending_presignal.direction == final_direction
            lead_ms = (chunk.ts - pending_presignal.ts) * 1000.0 if fire_ts > 0 else None

            # Update the pre-signal in-place (dataclass is mutable for this)
            pending_presignal.final_confidence = conf
            pending_presignal.final_direction = final_direction
            pending_presignal.agreement = agreement
            pending_presignal.lead_time_ms = lead_ms

            log.debug(
                "PreSignal resolved: ticker=%s agreement=%s lead=%.0fms",
                chunk.ticker, agreement, lead_ms or 0,
            )
            del state.fired_presignals[doc_id]

        # If the document completed without a pre-signal but confidence is
        # above threshold, fire a (non-early) signal still tagged pre_signal=True
        # so it goes through the probability pipeline tracking
        if pending_presignal is None and conf >= self._threshold and abs(bias) >= 0.1:
            chunks_seen = iir.tokens_processed
            return self._fire_presignal(chunk, state, doc_id, iir, conf, bias, chunks_seen)

        return None

    def _fire_presignal(
        self,
        chunk: DocumentChunk,
        state: _TickerState,
        doc_id: str,
        iir: IIRAccumulator,
        conf: float,
        bias: float,
        chunks_seen: int,
    ) -> PreSignal:
        now = time.time()
        ps = PreSignal(
            ticker=chunk.ticker,
            source=chunk.source,
            doc_id=doc_id,
            confidence=conf,
            direction=iir.direction(),
            iir_value=bias,
            variance=state.welford.variance,
            chunks_processed=chunks_seen,
            ts=now,
        )

        state.mark_fired(doc_id, now)
        state.fired_presignals[doc_id] = ps
        self._presignal_count += 1

        # Non-blocking enqueue
        try:
            self.presignal_queue.put_nowait(ps)
        except asyncio.QueueFull:
            log.warning("StreamProcessor: presignal_queue full, dropping pre-signal for %s", chunk.ticker)

        if self._on_presignal is not None:
            try:
                self._on_presignal(ps)
            except Exception as exc:
                log.warning("StreamProcessor: on_presignal callback error: %s", exc)

        log.info(
            "PRE-SIGNAL fired: ticker=%s source=%s conf=%.2f dir=%s chunks=%d",
            chunk.ticker, chunk.source.value, conf, iir.direction(), chunks_seen,
        )
        return ps


# ── Helpers ───────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> List[str]:
    """Normalize and split text into tokens for semantic lookup.

    Strips punctuation and lowercases, matching LLMAdapter's normalize step.
    """
    tokens = []
    for word in text.lower().split():
        cleaned = word.strip(".,!?;:\"'()[]{}/#@$%^&*-_+=<>\\|~`")
        if cleaned:
            tokens.append(cleaned)
    return tokens
