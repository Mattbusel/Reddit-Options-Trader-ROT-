from __future__ import annotations

import time

from rot.core.logging import JsonlLogger
from rot.ingest.reddit_ingestor import RedditIngestor
from rot.trend.trend_store import TrendStore
from rot.trend.trend_engine import TrendEngine
from rot.extract.event_builder import EventBuilder
from rot.credibility.scorer import CredibilityScorer
from rot.reasoner.deepseek_client import DeepSeekReasoner
from rot.market.trade_builder import TradeBuilder
from rot.app.runner import PipelineRunner


def loop(interval_s: int = 20) -> None:
    logger = JsonlLogger(root="storage")

    ingestor = RedditIngestor(
        subreddits=["wallstreetbets", "stocks"],
        listing="hot",
        limit_per_sub=50,
    )
    trend_engine = TrendEngine(store=TrendStore(), window_s=1800)
    event_builder = EventBuilder()
    cred = CredibilityScorer()
    reasoner = DeepSeekReasoner(api_key=None)
    trade_builder = TradeBuilder()

    runner = PipelineRunner(
        ingestor=ingestor,
        trend_engine=trend_engine,
        event_builder=event_builder,
        cred=cred,
        reasoner=reasoner,
        trade_builder=trade_builder,
        logger=logger,
    )

    while True:
        summary = runner.run_once()
        if isinstance(summary, dict) and "run_id" in summary:
            print(
                f"✅ {summary['run_id']} | snapshots={summary.get('snapshots')} "
                f"candidates={summary.get('candidates')} events={summary.get('events')} "
                f"ideas={summary.get('trade_ideas')}"
            )
        time.sleep(interval_s)

        # Debug: print top 3 trend candidates this run (if any)
        try:
            import json
            with open("storage/trend_candidates.jsonl", "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            if lines:
                last = json.loads(lines[-1])
                c = last.get("candidate", {})
                post = c.get("snapshot", {}).get("post", {})
                print(f"   ↳ top: {c.get('trend_score'):.4f} | {post.get('subreddit')} | {post.get('title')[:90]}")
        except Exception:
            pass



if __name__ == "__main__":
    loop()
