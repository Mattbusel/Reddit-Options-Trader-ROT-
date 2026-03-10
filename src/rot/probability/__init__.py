"""ROT Probability Pipeline.

Python port of the LLMTokenStreamQuantEngine stream processing architecture.
Processes ROT's information sources at the stream level — word-by-word for
Reddit posts, progressively for SEC filings and FDA press releases — using:

  - IIR integrator: accumulator = alpha * semantic_weight + (1 - alpha) * accumulator
  - Welford online variance tracker: per-ticker running mean/variance

When the accumulator crosses the confidence threshold before the document
completes, a Stage-0 pre-signal is fired tagged with ``pre_signal: true``.
Pre-signal accuracy is tracked in the ``pre_signal_events`` SQLite table.
"""

from rot.probability.stream_processor import StreamProcessor, PreSignal, IIRAccumulator

__all__ = ["StreamProcessor", "PreSignal", "IIRAccumulator"]
