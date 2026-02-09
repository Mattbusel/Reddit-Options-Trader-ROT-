from __future__ import annotations

from rot.core.config import Settings
from rot.core.logging import JsonlLogger
from rot.ingest.reddit_ingestor import RedditIngestor
from rot.trend.trend_store import TrendStore
from rot.trend.trend_engine import TrendEngine
from rot.extract.event_builder import EventBuilder
from rot.credibility.scorer import CredibilityScorer
from rot.reasoner.reasoner import Reasoner
from rot.market.trade_builder import TradeBuilder
from rot.app.runner import PipelineRunner


def main() -> None:
    cfg = Settings()

    logger = JsonlLogger(root=cfg.storage_root)

    ingestor = RedditIngestor(
        subreddits=cfg.reddit.subreddits,
        listing=cfg.reddit.listing,
        limit_per_sub=cfg.reddit.limit_per_sub,
        include_comments=cfg.reddit.include_comments,
        top_comments=cfg.reddit.top_comments,
        state_path=f"{cfg.storage_root}/seen_posts.json",
    )
    trend_engine = TrendEngine(
        store=TrendStore(path=f"{cfg.storage_root}/trend_state.json"),
        window_s=cfg.trend.window_s,
        threshold=cfg.trend.threshold,
        comment_weight=cfg.trend.comment_weight,
    )
    event_builder = EventBuilder()
    cred = CredibilityScorer()
    reasoner = Reasoner(
        provider=cfg.llm.provider,
        api_key=cfg.llm.api_key,
        model=cfg.llm.model,
        base_url=cfg.llm.base_url,
        max_tokens=cfg.llm.max_tokens,
        temperature=cfg.llm.temperature,
    )
    trade_builder = TradeBuilder()

    runner = PipelineRunner(
        ingestor=ingestor,
        trend_engine=trend_engine,
        event_builder=event_builder,
        cred=cred,
        reasoner=reasoner,
        trade_builder=trade_builder,
        logger=logger,
        top_n=cfg.trend.top_n,
    )

    if reasoner.llm_available:
        print("🧠 LLM reasoning: ACTIVE")
    else:
        print("⚠️  LLM reasoning: FALLBACK (set ROT_LLM_API_KEY to enable)")

    runner.run_once()


if __name__ == "__main__":
    main()
