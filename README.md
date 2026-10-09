# Reddit Options Trader (ROT)

English | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

**A Python app that reads Reddit and market news, spots which stock tickers people are suddenly excited about, scores how trustworthy each post looks, and turns it into an options trade idea, or a clear reason not to trade.** It is a Reddit sentiment and options signal pipeline with a web dashboard, a REST/WebSocket API and optional LLM reasoning (OpenAI, Anthropic or DeepSeek).

For developers and retail options traders who want to study Reddit sentiment as a signal, and for anyone curious how a social-media NLP pipeline is built end to end.

<p align="center">
  <a href="https://mattbusel.vercel.app/Reddit-Options-Trader-ROT-/"><b>Project site</b></a> &middot;
  <a href="#try-it-in-one-command">Try it</a> &middot;
  <a href="#how-it-works">How it works</a> &middot;
  <a href="#examples">Examples</a> &middot;
  <a href="docs/REFERENCE.md">Full reference</a>
</p>


[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> [!WARNING]
> **Research and educational tool only. Not financial advice.** ROT produces signals and trade ideas, not a tested strategy. Options can lose 100% of the premium paid, Reddit sentiment is noisy and often manipulated, and LLM reasoning can be confidently wrong. Broker integration defaults to paper trading.

<img alt="The ROT web dashboard: signal counts, average confidence, a bullish/bearish/mixed split, a list of the latest signals with ticker, stance, confidence and an LLM-written summary, and trending tickers" src="docs/img/dashboard.png" width="100%">

*The dashboard running locally (February 2026 screenshot, live Reddit data).*

## Try it in one command

No Reddit account, no API keys. The demo runs the real pipeline on five bundled sample posts:

```bash
git clone https://gitlab.com/mattbusel/Reddit-Options-Trader-ROT.git && cd Reddit-Options-Trader-ROT-
pip install -e . && python examples/demo.py
```

Python 3.10+. The sample posts in [`examples/sample/posts.json`](examples/sample/posts.json) were written for the demo (they are not real Reddit posts); ticker checks and prices come from a Yahoo Finance snapshot saved on 2026-09-28, so it runs offline. Add `--live` for fresh prices.

To run the full app with live Reddit data and the dashboard, copy `.env.example` to `.env`, add your Reddit API keys, and run `docker compose up --build` (then open http://localhost:8000/dashboard). There is no hosted instance: the old Railway deployment is offline.

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/pipeline-dark.svg">
  <img alt="The nine pipeline stages as a snake of cards: ingest (5 posts), trend (4 trending, upvotes per second plus 2 times comments per second at least 0.01), tickers (3 with a ticker), event (3), validate and enrich (3 priced), credibility (3 scored 0 to 1), suppress (3 kept), reason with an LLM or stub (3), trade idea (3 records, 0 with legs). Below: earnings rumours are clamped to confidence 0.25, below the 0.30 bar; an unknown stance never trades; weekends block every trade." src="docs/img/pipeline-light.svg" width="100%">
</picture>

In plain words, on every poll (Reddit is polled every 20 seconds by default):

1. **Ingest and trend.** Posts come in from Reddit and RSS news feeds. A post "trends" when its upvotes and comments grow fast between two polls.
2. **Find the ticker and the story.** A custom NLP engine pulls out `$TSLA`-style tickers, the kind of event (earnings rumour, product news, squeeze chatter...), the stance (bullish, bearish, mixed) and the time horizon. Tickers are checked against real market data.
3. **Score trust.** A credibility score from 0 to 1 rewards DD posts, good subreddits and engagement, and penalises cross-posts, new accounts and pump-and-dump language.
4. **Reason and decide.** An LLM (or a built-in stub when there is no key) writes a thesis, and the trade builder either proposes a structure (debit/credit spread, straddle...) or records why it will not trade.

Code: [`src/rot/app/runner.py`](src/rot/app/runner.py) (`PipelineRunner.run_once`). Diagram source: [`scripts/make_pipeline_svg.py`](scripts/make_pipeline_svg.py).

## Examples

Real output of `python examples/demo.py` on 2026-09-28 (stub reasoning, bundled market snapshot):

```text
ROT demo: the real 9-stage pipeline on 5 sample posts (two polls, 10 minutes apart)
market data: bundled Yahoo Finance snapshot from 2026-09-28 (use --live for fresh data)
LLM reasoning: stub mode (no ROT_LLM_API_KEY)

pass 1: snapshots 5, candidates 0, events 0, trade_ideas 0
pass 2: snapshots 5, candidates 4, events 3, trade_ideas 3
  (pass 1 has nothing to compare with, so nothing can trend yet)

r/options  "NVDA DD: data center demand still outrunning supply into next quarter"
  poll: 420 -> 610 upvotes, 88 -> 131 comments
  event: earnings_rumor, bullish, horizon earnings, tickers NVDA
  credibility: 0.70   last close $228.86
  reasoning: Reddit chatter mentions NVDA; treat as unverified signal.
  trade idea: none (confidence_too_low)

r/wallstreetbets  "TSLA puts printing? Deliveries miss rumor going around"
  poll: 150 -> 390 upvotes, 60 -> 142 comments
  event: earnings_rumor, bearish, horizon unknown, tickers TSLA
  credibility: 0.45   last close $357.45
  reasoning: Reddit chatter mentions TSLA; treat as unverified signal.
  trade idea: none (confidence_too_low)

r/pennystocks  "This ticker is going to the moon 1000% guaranteed, get in before it ex"
  poll: 12 -> 40 upvotes, 9 -> 30 comments
  -> no signal (no valid ticker, or not trending)

r/stocks  "AMD earnings next week: what is priced in?"
  poll: 230 -> 300 upvotes, 75 -> 110 comments
  event: earnings_rumor, unknown, horizon earnings, tickers AMD
  credibility: 0.55   last close $607.87
  reasoning: Reddit chatter mentions AMD; treat as unverified signal.
  trade idea: none (unknown_stance)

r/investing  "How do you all think about rebalancing in a high-rate world?"
  poll: 80 -> 81 upvotes, 40 -> 41 comments
  -> no signal (no valid ticker, or not trending)
```

What it shows: the DD post on r/options scores highest (0.70) and the r/wallstreetbets rumour lowest (0.45); the hype post has no ticker and the calm question never trends, so both stop early; and ROT refuses to trade all three events, for the reasons it logs. Every stage also writes a JSONL audit trail. `python examples/demo.py --keep` leaves it on disk, for example:

```json
{"run_id": "run_1790631982", "trade_idea": {"underlying": "AMD", "strategy": "none", "legs": [], "max_loss": 0.0, "thesis": "Reddit chatter mentions AMD; treat as unverified signal.", "time_stop": "N/A", "quality_score": 0.0, "do_not_trade_reasons": ["unknown_stance"], "meta": {}}, "ts": 1790631982}
```

## Use it in 3 steps

1. Run the demo above to see every stage on sample posts.
2. Put your Reddit API keys (and optionally an LLM key) in `.env`, from [`.env.example`](.env.example).
3. Start the app: `docker compose up --build`, or `python -m rot.app.server` after `pip install -e .`, and open http://localhost:8000/dashboard. API docs are at `/docs`.

## Documentation

| Document | What is in it |
|---|---|
| [docs/REFERENCE.md](docs/REFERENCE.md) | Everything from the old long README: quickstart options, architecture, signal quality factors, configuration, options chain, API, lineage, brokers, risk monitor, tests, deployment, security, per-round feature notes |
| [docs/architecture.md](docs/architecture.md) | Pipeline stages and design decisions |
| [docs/config.md](docs/config.md) | Every `ROT_*` environment variable |
| [docs/api-reference.md](docs/api-reference.md) | REST and WebSocket endpoints |
| [docs/nlp-engine.md](docs/nlp-engine.md) | The custom NLP engine |
| [docs/deployment.md](docs/deployment.md) | Docker and self-hosting |
| [SECURITY.md](SECURITY.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG.md](CHANGELOG.md) | Security policy, contributing, history |

## License

MIT, see [LICENSE](LICENSE). Third-party licenses: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). Research and education only; the authors accept no liability for financial losses. Never risk capital you cannot afford to lose.
