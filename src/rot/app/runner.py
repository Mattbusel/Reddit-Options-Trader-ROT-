from __future__ import annotations

import time

from rot.core.logging import JsonlLogger
from rot.ingest.reddit_ingestor import RedditIngestor
from rot.trend.trend_engine import TrendEngine
from rot.extract.event_builder import EventBuilder
from rot.credibility.scorer import CredibilityScorer
from rot.reasoner.deepseek_client import DeepSeekReasoner
from rot.market.trade_builder import TradeBuilder


class PipelineRunner:
    def __init__(self, ingestor: RedditIngestor, trend_engine: TrendEngine, event_builder: EventBuilder, cred: CredibilityScorer, reasoner: DeepSeekReasoner, trade_builder: TradeBuilder, logger: JsonlLogger) -> None:
        self.ingestor = ingestor
        self.trend_engine = trend_engine
        self.event_builder = event_builder
        self.cred = cred
        self.reasoner = reasoner
        self.trade_builder = trade_builder
        self.log = logger

    def run_once(self) -> dict:
        run_id = f"run_{int(time.time())}"
        snapshots = self.ingestor.poll()
        for s in snapshots:
            self.log.write("snapshots", {"run_id": run_id, "snapshot": s})

        candidates = self.trend_engine.detect(snapshots)
        for c in candidates:
            self.log.write("trend_candidates", {"run_id": run_id, "candidate": c})

        events = []
        for c in candidates:
            events.extend(self.event_builder.from_candidate(c))

        scored = [self.cred.score(e) for e in events]
        for e in scored:
            self.log.write("events", {"run_id": run_id, "event": e})

        idea_count = 0
        for e in scored:
            packet = self.reasoner.reason(e)
            self.log.write("reasoning", {"run_id": run_id, "event": e, "packet": packet})
            ideas = self.trade_builder.build(packet, e)
            for idea in ideas:
                idea_count += 1
                self.log.write("trade_ideas", {"run_id": run_id, "trade_idea": idea})

        return {
            "run_id": run_id,
            "snapshots": len(snapshots),
            "candidates": len(candidates),
            "events": len(scored),
            "trade_ideas": idea_count,
        }
