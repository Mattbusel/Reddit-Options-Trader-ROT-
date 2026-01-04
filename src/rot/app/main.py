from __future__ import annotations

from rot.core.logging import JsonlLogger
from rot.ingest.reddit_ingestor import RedditIngestor
from rot.trend.trend_store import TrendStore
from rot.trend.trend_engine import TrendEngine
from rot.extract.event_builder import EventBuilder
from rot.credibility.scorer import CredibilityScorer
from rot.reasoner.deepseek_client import DeepSeekReasoner
from rot.market.trade_builder import TradeBuilder
from rot.app.runner import PipelineRunner


def main() -> None:
    logger = JsonlLogger(root="storage")

    ingestor = RedditIngestor(subreddits=["wallstreetbets", "stocks"], listing="rising")
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

    runner.run_once()
    print("✅ Run complete. Check storage/*.jsonl")


if __name__ == "__main__":
    main()

