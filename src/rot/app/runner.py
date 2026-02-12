from __future__ import annotations

import dataclasses
import time
from typing import Any, Callable, Dict, List, Optional

from rot.core.logging import JsonlLogger
from rot.ingest.reddit_ingestor import RedditIngestor
from rot.trend.trend_engine import TrendEngine
from rot.trend.ranker import top_n_candidates
from rot.trend.ticker_ranker import top_ticker_candidates
from rot.extract.event_builder import EventBuilder
from rot.credibility.scorer import CredibilityScorer
from rot.reasoner.reasoner import Reasoner
from rot.market.trade_builder import TradeBuilder
from rot.market.enricher import MarketEnricher
from rot.market.symbol_validator import SymbolValidator


class PipelineRunner:
    def __init__(
        self,
        ingestor: RedditIngestor,
        trend_engine: TrendEngine,
        event_builder: EventBuilder,
        cred: CredibilityScorer,
        reasoner: Reasoner,
        trade_builder: TradeBuilder,
        logger: JsonlLogger,
        enricher: MarketEnricher | None = None,
        symbol_validator: SymbolValidator | None = None,
        top_n: int = 10,
        on_signal: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.ingestor = ingestor
        self.trend_engine = trend_engine
        self.event_builder = event_builder
        self.cred = cred
        self.reasoner = reasoner
        self.trade_builder = trade_builder
        self.log = logger
        self.enricher = enricher or MarketEnricher()
        self.symbol_validator = symbol_validator or SymbolValidator()
        self.top_n = top_n
        self.on_signal = on_signal
        self._emitted_keys: set = set()  # (post_url, ticker) dedup

    def _emit_signal(self, signal_data: Dict[str, Any]) -> None:
        if not self.on_signal:
            return

        # Extract dedup key from event dataclass
        event = signal_data.get("event")
        if event is None:
            return

        entities = event.entities if hasattr(event, "entities") else []
        ticker = entities[0] if entities else "UNKNOWN"

        evidence = event.evidence if hasattr(event, "evidence") else []
        post_url = evidence[0].permalink if evidence else ""

        dedup_key = (post_url, ticker)
        if dedup_key in self._emitted_keys:
            return  # Already emitted this signal

        self._emitted_keys.add(dedup_key)

        # Prevent unbounded memory growth
        if len(self._emitted_keys) > 10_000:
            self._emitted_keys.clear()

        try:
            self.on_signal(signal_data)
        except Exception:
            pass

    def run_once(self) -> dict:
        run_id = f"run_{int(time.time())}"

        # 1) ingest
        snapshots = self.ingestor.poll()
        # Note: raw snapshot logging removed to reduce JSONL volume
        # (~150 entries/cycle × 4320 cycles/day was the largest JSONL stream)

        # Save trend store state after detection
        # 2) trend detect
        candidates = self.trend_engine.detect(snapshots)
        for c in candidates:
            self.log.write("trend_candidates", {"run_id": run_id, "candidate": c})

        # Save trend store if it supports persistence
        if hasattr(self.trend_engine.store, "save"):
            self.trend_engine.store.save()

        # 2a) Top signals (ALL)
        top_all = top_n_candidates(candidates, n=self.top_n)
        for rank, c in enumerate(top_all, start=1):
            p = c.snapshot.post
            self.log.write(
                "top_signals",
                {
                    "run_id": run_id,
                    "rank": rank,
                    "trend_score": c.trend_score,
                    "subreddit": p.subreddit,
                    "title": p.title,
                    "post_id": p.id,
                    "permalink": p.permalink,
                },
            )

        # Build extracted entities map once (used by prints + ticker ranking)
        extracted_by_key: dict[str, list[str]] = {}
        for c in candidates:
            p = c.snapshot.post
            ents = self.event_builder.extract_entities(p.title, p.selftext)
            extracted_by_key[c.key] = ents

        if top_all:
            print("🔥 Top signals:")
            for i, c in enumerate(top_all, start=1):
                p = c.snapshot.post
                ents = extracted_by_key.get(c.key, [])
                ents_s = ",".join(ents[:5]) if ents else "-"
                print(f"  {i}. {p.subreddit} | {p.title[:80]} [{ents_s}] (score={c.trend_score:.3f})")

        # 2b) Build events once, reuse downstream
        events = []
        ticker_candidates = []

        for c in candidates:
            evs = self.event_builder.from_candidate(c)
            if evs:
                ticker_candidates.append(c)
                events.extend(evs)

        ticker_candidate_count = sum(
            1
            for c in candidates
            if any(self.symbol_validator.is_valid(sym) for sym in extracted_by_key.get(c.key, []))
        )

        # 2c) Top signals (TICKER-AWARE)
        top_ticker_pairs = top_ticker_candidates(
            candidates=candidates,
            extracted=extracted_by_key,
            validator=self.symbol_validator,
            n=self.top_n,
        )

        for rank, (c, syms) in enumerate(top_ticker_pairs, start=1):
            p = c.snapshot.post
            self.log.write(
                "top_ticker_signals",
                {
                    "run_id": run_id,
                    "rank": rank,
                    "trend_score": c.trend_score,
                    "subreddit": p.subreddit,
                    "title": p.title,
                    "post_id": p.id,
                    "permalink": p.permalink,
                    "symbols": syms,
                },
            )

        if top_ticker_pairs:
            print("🎯 Top ticker signals:")
            for i, (c, syms) in enumerate(top_ticker_pairs, 1):
                p = c.snapshot.post
                print(f"  {i}. {p.subreddit} | {p.title[:80]} [{','.join(syms)}] (score={c.trend_score:.3f})")

        # 3) validate entities, enrich, score
        # Pre-filter: only keep entities that pass SymbolValidator (uses cached yfinance lookups)
        validated_events = []
        for e in events:
            valid_entities = [
                sym for sym in e.entities
                if self.symbol_validator.is_valid(sym)
            ]
            if not valid_entities:
                continue  # skip events with no valid tickers
            validated_events.append(
                dataclasses.replace(e, entities=tuple(valid_entities))
                if isinstance(e.entities, tuple)
                else dataclasses.replace(e, entities=valid_entities)
            )

        events = [self.enricher.enrich_event(e) for e in validated_events]
        scored = [self.cred.score(e) for e in events]
        for e in scored:
            self.log.write("events", {"run_id": run_id, "event": e})

        # 4) reason + ideas
        idea_count = 0
        stub_count = 0
        for e in scored:
            packet = self.reasoner.reason(e)
            self.log.write("reasoning", {"run_id": run_id, "event": e, "packet": packet})

            # Quality gate: skip storing/emitting signals with no real LLM analysis
            raw = packet.raw or {}
            if raw.get("stub"):
                stub_count += 1
                continue

            # Merge LLM confidence back onto Event so the stored signal uses
            # the LLM-calibrated value instead of the heuristic pre-LLM value.
            llm_confidence = raw.get("confidence")
            if llm_confidence is not None and not raw.get("error"):
                e = dataclasses.replace(e, confidence=float(llm_confidence))

            ideas = self.trade_builder.build(packet, e)
            for idea in ideas:
                idea_count += 1
                self.log.write("trade_ideas", {"run_id": run_id, "trade_idea": idea})

                # Emit signal for downstream consumers (WebSocket, Discord, DB)
                self._emit_signal({
                    "run_id": run_id,
                    "event": e,
                    "reasoning": packet,
                    "trade_idea": idea,
                })

        return {
            "run_id": run_id,
            "snapshots": len(snapshots),
            "candidates": len(candidates),
            "ticker_candidates": len(ticker_candidates),
            "ticker_candidate_count": ticker_candidate_count,
            "events": len(scored),
            "stubs_skipped": stub_count,
            "trade_ideas": idea_count,
            "top_signals": len(top_all),
            "top_ticker_signals": len(top_ticker_pairs),
        }
