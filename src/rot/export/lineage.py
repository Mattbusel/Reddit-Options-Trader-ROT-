"""Signal lineage (provenance) builder.

Reconstructs the full processing pipeline chain for a signal
from its stored metadata.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from rot.export.types import LineageStep, SignalLineage


class LineageBuilder:
    """Builds signal provenance chains from stored signal data."""

    def build_lineage(self, signal: Dict[str, Any]) -> SignalLineage:
        """Build full lineage for a single signal.

        Parameters
        ----------
        signal:
            Signal dict from database with at minimum: id, ticker, created_at,
            event_data (JSON), market_data (JSON), reasoning (JSON).
        """
        signal_id = signal.get("id", "")
        ticker = signal.get("ticker", "")
        created_at = signal.get("created_at", 0)

        event_data = signal.get("event_data", {})
        if isinstance(event_data, str):
            try:
                event_data = json.loads(event_data)
            except (json.JSONDecodeError, TypeError):
                event_data = {}

        market_data = signal.get("market_data", {})
        if isinstance(market_data, str):
            try:
                market_data = json.loads(market_data)
            except (json.JSONDecodeError, TypeError):
                market_data = {}

        reasoning_data = signal.get("reasoning", {})
        if isinstance(reasoning_data, str):
            try:
                reasoning_data = json.loads(reasoning_data)
            except (json.JSONDecodeError, TypeError):
                reasoning_data = {}

        meta = event_data.get("meta", {}) if isinstance(event_data, dict) else {}

        steps = []
        ts = created_at

        # 1. Source/Ingestion
        source = signal.get("subreddit", "")
        source_type = "reddit"
        if meta.get("source_type"):
            source_type = meta["source_type"]
        elif "rss" in source.lower() or meta.get("rss_feed"):
            source_type = "rss"
        elif meta.get("stocktwits"):
            source_type = "stocktwits"

        steps.append(LineageStep(
            stage="ingestion",
            timestamp=ts,
            details={
                "source": source_type,
                "subreddit": source,
                "post_url": signal.get("post_url", ""),
            },
        ))

        # 2. Trend Detection
        trend_score = signal.get("trend_score", 0)
        if trend_score or meta.get("trend_score"):
            steps.append(LineageStep(
                stage="trend_detection",
                timestamp=ts + 0.1,
                details={
                    "trend_score": trend_score or meta.get("trend_score", 0),
                    "features": meta.get("features", {}),
                },
            ))

        # 3. NLP Analysis
        nlp_data = meta.get("nlp", {})
        if nlp_data or meta.get("nlp_polarity") is not None:
            steps.append(LineageStep(
                stage="nlp_analysis",
                timestamp=ts + 0.2,
                details={
                    "polarity": nlp_data.get("polarity") or meta.get("nlp_polarity", 0),
                    "conviction": nlp_data.get("conviction") or meta.get("conviction", 0),
                    "sarcasm": nlp_data.get("sarcasm_probability") or meta.get("sarcasm_score", 0),
                    "classifications": nlp_data.get("classifications", []),
                },
            ))

        # 4. Entity Extraction
        entities = event_data.get("entities", [])
        if entities:
            steps.append(LineageStep(
                stage="entity_extraction",
                timestamp=ts + 0.3,
                details={"entities": entities},
            ))

        # 5. Market Enrichment
        if market_data and isinstance(market_data, dict):
            ticker_md = market_data.get(ticker, market_data)
            if isinstance(ticker_md, dict) and ticker_md:
                steps.append(LineageStep(
                    stage="market_enrichment",
                    timestamp=ts + 0.4,
                    details={
                        "last_close": ticker_md.get("last_close"),
                        "pct_1d": ticker_md.get("pct_1d"),
                        "market_cap": ticker_md.get("market_cap"),
                        "atm_iv": ticker_md.get("atm_iv"),
                    },
                ))

        # 6. Credibility Scoring
        confidence = signal.get("confidence", 0)
        cred_factors = meta.get("credibility_factors", [])
        ml_cred = meta.get("ml_credibility", {})
        steps.append(LineageStep(
            stage="credibility_scoring",
            timestamp=ts + 0.5,
            details={
                "confidence": confidence,
                "factors": cred_factors,
                "ml_score": ml_cred.get("ml_score") if ml_cred else None,
            },
        ))

        # 7. LLM Reasoning
        if reasoning_data and isinstance(reasoning_data, dict):
            thesis = reasoning_data.get("thesis", "")
            if thesis:
                steps.append(LineageStep(
                    stage="llm_reasoning",
                    timestamp=ts + 0.6,
                    details={
                        "thesis": thesis[:200],
                        "catalyst_window": reasoning_data.get("catalyst_window", ""),
                        "risk_notes_count": len(reasoning_data.get("risk_notes", [])),
                    },
                ))

        # 8. Trade Building
        trade = signal.get("trade_idea", {})
        if isinstance(trade, str):
            try:
                trade = json.loads(trade)
            except (json.JSONDecodeError, TypeError):
                trade = {}
        if trade and isinstance(trade, dict):
            strategy = trade.get("strategy") or signal.get("strategy", "none")
            if strategy != "none":
                steps.append(LineageStep(
                    stage="trade_building",
                    timestamp=ts + 0.7,
                    details={
                        "strategy": strategy,
                        "quality_score": trade.get("quality_score") or signal.get("quality_score", 0),
                        "legs_count": len(trade.get("legs", [])),
                    },
                ))

        # 9. Storage
        steps.append(LineageStep(
            stage="storage",
            timestamp=ts + 0.8,
            details={
                "signal_id": signal_id,
                "stored_at": created_at,
            },
        ))

        return SignalLineage(
            signal_id=signal_id,
            ticker=ticker,
            steps=steps,
            source=source_type,
            created_at=created_at,
        )

    def build_batch_lineage(
        self, signals: List[Dict[str, Any]],
    ) -> List[SignalLineage]:
        """Build lineage for multiple signals."""
        return [self.build_lineage(s) for s in signals]
