"""Run the real ROT pipeline on bundled sample posts. No Reddit or LLM keys needed.

    pip install -e .
    python examples/demo.py

What it does: examples/sample/posts.json holds five sample posts (written for
this demo, not real Reddit posts) captured in two polls ten minutes apart. The
demo feeds both polls through the same classes the server uses
(rot.app.runner.PipelineRunner with TrendEngine, EventBuilder + NLPEngine,
SymbolValidator, MarketEnricher, CredibilityScorer, Reasoner, TradeBuilder) and
prints what every stage decided for every post.

Market data: by default the ticker checks and prices come from
examples/sample/market_snapshot.json, a Yahoo Finance snapshot saved by
`python examples/demo.py --refresh-market`, so the demo runs offline and gives
the same answer every time. `--live` fetches fresh data instead.

Without ROT_LLM_API_KEY the reasoner runs in its stub mode, exactly as the
server does, and no trade structure is built from a stub.

Research and education only. Not financial advice.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample"
POSTS = SAMPLE / "posts.json"
SNAPSHOT = SAMPLE / "market_snapshot.json"


def _import_rot():
    try:
        import rot  # noqa: F401
    except ImportError:
        sys.path.insert(0, str(HERE.parent / "src"))
    try:
        from rot.app.runner import PipelineRunner  # noqa: F401
    except ImportError as exc:  # pragma: no cover - friendly first-run error
        raise SystemExit(f"Could not import ROT ({exc}).\nInstall it first, from the repo root:\n"
                         "    pip install -e .\n") from exc


class SampleIngestor:
    """Replays the polls in posts.json, one poll per pipeline pass (duck-types RedditIngestor.poll)."""

    def __init__(self, path: Path, now: int) -> None:
        from rot.core.types import Post, ThreadSnapshot
        self._Post, self._Snap = Post, ThreadSnapshot
        data = json.loads(path.read_text(encoding="utf-8"))
        self.gap = int(data["poll_gap_s"])
        self.posts = data["posts"]
        self.now = now
        self.poll_no = 0

    def poll(self):
        k = self.poll_no
        self.poll_no += 1
        ts = self.now - self.gap * (1 - k)          # poll 0 ten minutes ago, poll 1 now
        out = []
        for p in self.posts:
            stats = p["polls"][k]
            post = self._Post(
                id=p["id"], created_utc=self.now - int(p["age_s"]), subreddit=p["subreddit"],
                title=p["title"], selftext=p["selftext"],
                url=f"https://www.reddit.com/r/{p['subreddit']}/comments/{p['id']}/",
                score=int(stats["score"]), num_comments=int(stats["num_comments"]),
                upvote_ratio=p.get("upvote_ratio"), author=p["author"],
                permalink=f"/r/{p['subreddit']}/comments/{p['id']}/", flair=p.get("flair"),
                is_crosspost=bool(p.get("is_crosspost")),
            )
            out.append(self._Snap(snapshot_ts=ts, post=post, top_comments=[]))
        return out


def build_pipeline(storage: Path, now: int, signals: list):
    from rot.app.runner import PipelineRunner
    from rot.core.logging import JsonlLogger
    from rot.credibility.scorer import CredibilityScorer
    from rot.extract.event_builder import EventBuilder
    from rot.market.enricher import MarketEnricher
    from rot.market.symbol_validator import SymbolValidator
    from rot.market.trade_builder import TradeBuilder
    from rot.nlp import NLPEngine
    from rot.reasoner.reasoner import Reasoner
    from rot.trend.trend_engine import TrendEngine
    from rot.trend.trend_store import TrendStore

    ingestor = SampleIngestor(POSTS, now)
    reasoner = Reasoner(provider=os.environ.get("ROT_LLM_PROVIDER", "openai"),
                        api_key=os.environ.get("ROT_LLM_API_KEY", ""),
                        model=os.environ.get("ROT_LLM_MODEL", "gpt-4o-mini"))
    runner = PipelineRunner(
        ingestor=ingestor,
        trend_engine=TrendEngine(store=TrendStore(path=str(storage / "trend_state.json"))),
        event_builder=EventBuilder(nlp_engine=NLPEngine()),
        cred=CredibilityScorer(),
        reasoner=reasoner,
        trade_builder=TradeBuilder(),
        logger=JsonlLogger(root=str(storage)),
        enricher=MarketEnricher(cache_path=str(storage / "market_cache.json")),
        symbol_validator=SymbolValidator(cache_path=str(storage / "symbol_valid_cache.json")),
        top_n=10,
        on_signal=signals.append,
    )
    reasoner.reset()
    return runner, reasoner


def seed_market_cache(storage: Path) -> str:
    """Write the bundled Yahoo Finance snapshot into the pipeline's own caches, stamped fresh."""
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    now = int(time.time())
    valid = {s: {"ok": ok, "ts": now} for s, ok in snap["symbols_valid"].items()}
    market = {s: {"ts": now, "data": d} for s, d in snap["market"].items()}
    (storage / "symbol_valid_cache.json").write_text(json.dumps(valid), encoding="utf-8")
    (storage / "market_cache.json").write_text(json.dumps(market), encoding="utf-8")
    return snap["fetched"]


def save_snapshot(storage: Path) -> None:
    valid = json.loads((storage / "symbol_valid_cache.json").read_text(encoding="utf-8"))
    market_path = storage / "market_cache.json"
    market = json.loads(market_path.read_text(encoding="utf-8")) if market_path.exists() else {}
    SNAPSHOT.write_text(json.dumps({
        "about": "Yahoo Finance data for the tickers in posts.json, saved by `python examples/demo.py --refresh-market`.",
        "fetched": time.strftime("%Y-%m-%d"),
        "symbols_valid": {s: v["ok"] for s, v in sorted(valid.items())},
        "market": {s: v["data"] for s, v in sorted(market.items())},
    }, indent=1) + "\n", encoding="utf-8")


def fmt_money(v):
    return "n/a" if v is None else f"${v:,.2f}"


def report(summaries, signals, posts, source_note, reasoner) -> None:
    by_post = {}
    for s in signals:
        ev = s.get("event")
        if ev is None or not getattr(ev, "evidence", None):
            continue
        by_post.setdefault(ev.evidence[0].post_id, []).append(s)

    print("ROT demo: the real 9-stage pipeline on 5 sample posts (two polls, 10 minutes apart)")
    print(f"market data: {source_note}")
    print(f"LLM reasoning: {'ACTIVE' if reasoner.llm_available else 'stub mode (no ROT_LLM_API_KEY)'}\n")
    for i, summ in enumerate(summaries, 1):
        print(f"pass {i}: " + ", ".join(f"{k} {summ[k]}" for k in
              ("snapshots", "candidates", "events", "trade_ideas")))
    print("  (pass 1 has nothing to compare with, so nothing can trend yet)\n")

    for p in posts:
        a, b = p["polls"]
        print(f"r/{p['subreddit']}  \"{p['title'][:70]}\"")
        print(f"  poll: {a['score']} -> {b['score']} upvotes, {a['num_comments']} -> {b['num_comments']} comments")
        sigs = by_post.get(p["id"], [])
        if not sigs:
            print("  -> no signal (no valid ticker, or not trending)\n")
            continue
        for s in sigs:
            ev, idea, pk = s["event"], s.get("trade_idea"), s.get("reasoning")
            meta = ev.meta or {}
            print(f"  event: {ev.event_type}, {ev.stance}, horizon {ev.time_horizon}, tickers {', '.join(ev.entities)}")
            mkt = (meta.get("market") or {}).get(ev.entities[0], {}) if ev.entities else {}
            print(f"  credibility: {ev.confidence:.2f}   last close {fmt_money(mkt.get('last_close'))}")
            if pk is not None:
                print(f"  reasoning: {pk.thesis[:90]}")
            if idea is not None:
                if idea.legs:
                    legs = "; ".join(f"{l.side} {l.qty} {l.kind} {l.strike:g} {l.expiry}" for l in idea.legs)
                    print(f"  trade idea: {idea.strategy} on {idea.underlying}: {legs}, max loss {fmt_money(idea.max_loss)}")
                else:
                    print(f"  trade idea: none ({', '.join(idea.do_not_trade_reasons) or 'no structure'})")
        print()
    print("Research and education only. Not financial advice.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the real ROT pipeline on bundled sample posts.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--live", action="store_true", help="fetch fresh ticker and price data from Yahoo Finance")
    g.add_argument("--refresh-market", action="store_true",
                   help="fetch fresh data and save it as examples/sample/market_snapshot.json")
    ap.add_argument("--keep", action="store_true", help="keep the run's storage folder and print its path")
    args = ap.parse_args(argv)

    _import_rot()
    logging.basicConfig(level=logging.WARNING)
    storage = Path(tempfile.mkdtemp(prefix="rot-demo-"))
    try:
        if args.live or args.refresh_market:
            source_note = f"live from Yahoo Finance, {time.strftime('%Y-%m-%d')}"
        elif SNAPSHOT.exists():
            source_note = f"bundled Yahoo Finance snapshot from {seed_market_cache(storage)} (use --live for fresh data)"
        else:
            raise SystemExit(f"{SNAPSHOT} is missing. Run with --live, or --refresh-market to recreate it.")

        now = int(time.time())
        signals: list = []
        runner, reasoner = build_pipeline(storage, now, signals)
        summaries = [runner.run_once(), runner.run_once()]
        posts = json.loads(POSTS.read_text(encoding="utf-8"))["posts"]
        report(summaries, signals, posts, source_note, reasoner)
        if args.refresh_market:
            save_snapshot(storage)
            print(f"\nsaved {SNAPSHOT.relative_to(HERE.parent)}")
        if args.keep:
            print(f"\nrun storage (JSONL audit log, caches): {storage}")
    finally:
        if not args.keep:
            shutil.rmtree(storage, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
