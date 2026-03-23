"""FinBERT-based transformer sentiment analysis for financial text.

Augments or replaces the lexicon-based :class:`~rot.nlp.sentiment.SentimentAnalyzer`
with a FinBERT model (``ProsusAI/finbert``) via the HuggingFace ``transformers``
library.  FinBERT is pre-trained on financial news and earnings call text,
making it substantially more accurate for Reddit options discussion than a
general-purpose sentiment model.

The module is designed to degrade gracefully: if ``transformers`` / ``torch``
are not installed, it falls back to a lightweight lexicon-based scoring stub so
the rest of the ROT pipeline continues to function.

Caching: The model is loaded once per process and cached on the instance (or
module-level singleton).  For production use, pass ``device="cuda"`` if a GPU
is available.

Example::

    from rot.nlp.transformer_sentiment import TransformerSentimentAnalyzer

    analyzer = TransformerSentimentAnalyzer()
    result = analyzer.analyze("NVDA earnings crushed it — loading up on calls!")
    print(result.polarity, result.label, result.confidence)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy imports
# ---------------------------------------------------------------------------

_TRANSFORMERS_AVAILABLE = False
_TORCH_AVAILABLE = False

try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    pass

try:
    from transformers import pipeline as hf_pipeline, Pipeline
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    log.warning(
        "transformers not installed. "
        "Run: pip install transformers torch  "
        "Falling back to stub sentiment scoring."
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default HuggingFace model ID for financial sentiment.
_FINBERT_MODEL: str = "ProsusAI/finbert"

#: FinBERT label mapping -> polarity score.
_LABEL_POLARITY: dict[str, float] = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
}

#: Maximum token length for FinBERT (512 BPE tokens; ~350 words).
_MAX_LENGTH: int = 512

#: Fallback lexicon for stub mode (word -> polarity [-1, 1]).
_STUB_LEXICON: dict[str, float] = {
    "bullish": 0.8, "bull": 0.7, "calls": 0.6, "moon": 0.9,
    "buy": 0.5, "long": 0.5, "beats": 0.7, "crushed": 0.8,
    "strong": 0.6, "growth": 0.5, "profit": 0.6, "upgrade": 0.7,
    "bearish": -0.8, "bear": -0.7, "puts": -0.6, "crash": -0.9,
    "sell": -0.5, "short": -0.5, "miss": -0.7, "recession": -0.8,
    "weak": -0.6, "loss": -0.6, "downgrade": -0.7, "fear": -0.6,
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class TransformerSentimentResult:
    """Sentiment analysis result from :class:`TransformerSentimentAnalyzer`.

    Attributes:
        label:      Raw FinBERT label: ``"positive"``, ``"negative"``, or
                    ``"neutral"``.
        polarity:   Normalised polarity score in ``[-1, +1]``.
        confidence: Model confidence (softmax probability) in ``[0, 1]``.
        text_len:   Number of characters in the input text.
        truncated:  True if the text was truncated before inference.
        backend:    ``"finbert"`` or ``"stub"`` (when transformers unavailable).
    """

    label: str
    polarity: float
    confidence: float
    text_len: int
    truncated: bool
    backend: str


# ---------------------------------------------------------------------------
# TransformerSentimentAnalyzer
# ---------------------------------------------------------------------------


class TransformerSentimentAnalyzer:
    """FinBERT-backed sentiment analyzer for financial / Reddit text.

    Args:
        model_name:  HuggingFace model identifier (default ``"ProsusAI/finbert"``).
        device:      PyTorch device string: ``"cpu"``, ``"cuda"``, or ``"cuda:0"``.
                     Defaults to CUDA if available, else CPU.
        batch_size:  Batch size for :meth:`analyze_batch` (default 16).
        max_length:  Maximum token length; longer texts are truncated.

    Example::

        analyzer = TransformerSentimentAnalyzer(device="cpu")
        res = analyzer.analyze("Interest rates are rising — bearish for growth stocks.")
        print(res.polarity)  # e.g. -0.82
    """

    def __init__(
        self,
        model_name: str = _FINBERT_MODEL,
        device: Optional[str] = None,
        batch_size: int = 16,
        max_length: int = _MAX_LENGTH,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self._pipeline: Optional["Pipeline"] = None  # type: ignore[type-arg]

        # Resolve device
        if device is not None:
            self._device = device
        elif _TORCH_AVAILABLE and torch.cuda.is_available():
            self._device = "cuda"
        else:
            self._device = "cpu"

        self._backend = "stub"

        if _TRANSFORMERS_AVAILABLE:
            self._load_pipeline()

    # ------------------------------------------------------------------
    # Pipeline loading
    # ------------------------------------------------------------------

    def _load_pipeline(self) -> None:
        """Load the FinBERT HuggingFace pipeline (called once at init)."""
        try:
            device_id = 0 if self._device.startswith("cuda") else -1
            self._pipeline = hf_pipeline(
                task="text-classification",
                model=self.model_name,
                device=device_id,
                truncation=True,
                max_length=self.max_length,
            )
            self._backend = "finbert"
            log.info(
                "transformer_sentiment.loaded",
                model=self.model_name,
                device=self._device,
            )
        except Exception as exc:
            log.warning(
                "transformer_sentiment.load_failed",
                model=self.model_name,
                error=str(exc),
                fallback="stub",
            )
            self._pipeline = None
            self._backend = "stub"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, text: str) -> TransformerSentimentResult:
        """Analyze the sentiment of a single text string.

        Args:
            text: Raw financial text (Reddit post, news headline, etc.).
                  Will be preprocessed and truncated if necessary.

        Returns:
            :class:`TransformerSentimentResult` with label, polarity, and
            confidence.
        """
        clean, truncated = self._preprocess(text)

        if self._pipeline is not None:
            return self._run_finbert(clean, truncated, text)
        else:
            return self._stub_analyze(clean, truncated, text)

    def analyze_batch(self, texts: List[str]) -> List[TransformerSentimentResult]:
        """Analyze a batch of texts, leveraging batched inference when available.

        Args:
            texts: List of raw text strings.

        Returns:
            List of :class:`TransformerSentimentResult`, one per input.
        """
        if not texts:
            return []

        if self._pipeline is not None:
            return self._run_finbert_batch(texts)
        else:
            return [self.analyze(t) for t in texts]

    # ------------------------------------------------------------------
    # FinBERT inference
    # ------------------------------------------------------------------

    def _run_finbert(
        self, clean_text: str, truncated: bool, original: str
    ) -> TransformerSentimentResult:
        """Run single inference through the FinBERT pipeline."""
        try:
            outputs = self._pipeline(clean_text)  # type: ignore[misc]
            out = outputs[0] if isinstance(outputs, list) else outputs
            label = str(out.get("label", "neutral")).lower()
            score = float(out.get("score", 0.5))
            polarity = _LABEL_POLARITY.get(label, 0.0) * score

            return TransformerSentimentResult(
                label=label,
                polarity=round(polarity, 4),
                confidence=round(score, 4),
                text_len=len(original),
                truncated=truncated,
                backend="finbert",
            )
        except Exception as exc:
            log.warning("finbert.inference_error", error=str(exc))
            return self._stub_analyze(clean_text, truncated, original)

    def _run_finbert_batch(self, texts: List[str]) -> List[TransformerSentimentResult]:
        """Run batched inference through the FinBERT pipeline."""
        preprocessed = [self._preprocess(t) for t in texts]
        clean_texts = [p[0] for p in preprocessed]
        truncated_flags = [p[1] for p in preprocessed]

        try:
            outputs = self._pipeline(clean_texts, batch_size=self.batch_size)  # type: ignore[misc]
            results = []
            for i, out in enumerate(outputs):
                label = str(out.get("label", "neutral")).lower()
                score = float(out.get("score", 0.5))
                polarity = _LABEL_POLARITY.get(label, 0.0) * score
                results.append(
                    TransformerSentimentResult(
                        label=label,
                        polarity=round(polarity, 4),
                        confidence=round(score, 4),
                        text_len=len(texts[i]),
                        truncated=truncated_flags[i],
                        backend="finbert",
                    )
                )
            return results
        except Exception as exc:
            log.warning("finbert.batch_error", error=str(exc))
            return [self.analyze(t) for t in texts]

    # ------------------------------------------------------------------
    # Stub fallback
    # ------------------------------------------------------------------

    def _stub_analyze(
        self, clean_text: str, truncated: bool, original: str
    ) -> TransformerSentimentResult:
        """Simple lexicon stub used when transformers is not available."""
        words = clean_text.lower().split()
        scores = [_STUB_LEXICON.get(w, 0.0) for w in words]
        if not scores:
            polarity = 0.0
        else:
            polarity = sum(scores) / max(len(scores), 1)
            polarity = max(-1.0, min(1.0, polarity))

        label = "positive" if polarity > 0.05 else ("negative" if polarity < -0.05 else "neutral")
        confidence = min(1.0, abs(polarity) + 0.4)

        return TransformerSentimentResult(
            label=label,
            polarity=round(polarity, 4),
            confidence=round(confidence, 4),
            text_len=len(original),
            truncated=truncated,
            backend="stub",
        )

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------

    def _preprocess(self, text: str) -> tuple[str, bool]:
        """Clean and optionally truncate text for model input.

        Returns:
            Tuple ``(cleaned_text, was_truncated)``.
        """
        # Remove URLs
        cleaned = re.sub(r"https?://\S+", "", text)
        # Remove Reddit-style markdown (bold, italic, links)
        cleaned = re.sub(r"\*{1,2}(.*?)\*{1,2}", r"\1", cleaned)
        cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
        # Collapse whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Approximate truncation (chars; FinBERT tokeniser will handle tokens)
        truncated = False
        char_limit = self.max_length * 4  # ~4 chars/token rough estimate
        if len(cleaned) > char_limit:
            cleaned = cleaned[:char_limit]
            truncated = True

        return cleaned, truncated

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def backend(self) -> str:
        """Active backend: ``"finbert"`` or ``"stub"``."""
        return self._backend

    @property
    def is_finbert(self) -> bool:
        """True if the FinBERT model is loaded and active."""
        return self._backend == "finbert"

    def __repr__(self) -> str:
        return (
            f"TransformerSentimentAnalyzer("
            f"model={self.model_name!r}, device={self._device!r}, "
            f"backend={self._backend!r})"
        )
