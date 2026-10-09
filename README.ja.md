# Reddit Options Trader (ROT)

[English](README.md) | [简体中文](README.zh-CN.md) | 日本語 | [한국어](README.ko.md)

**Reddit と市場ニュースを読み、みんなが急に盛り上がっている銘柄（ティッカー）を見つけ、各投稿の信頼度をスコア化して、オプション取引のアイデア、または取引しない明確な理由に変える Python アプリです。** Reddit のセンチメント分析とオプションのシグナルを生み出すパイプラインで、Web ダッシュボード、REST/WebSocket API、オプションの LLM による推論（OpenAI、Anthropic、DeepSeek）を備えています。

Reddit のセンチメントをシグナルとして研究したい開発者や個人のオプショントレーダー、そして SNS の自然言語処理（NLP）パイプラインがどのように端から端まで組み立てられているのかに興味がある方に向けたプロジェクトです。

<p align="center">
  <a href="https://mattbusel.vercel.app/Reddit-Options-Trader-ROT-/"><b>プロジェクトサイト</b></a> &middot;
  <a href="#try-it-in-one-command">試してみる</a> &middot;
  <a href="#how-it-works">仕組み</a> &middot;
  <a href="#examples">実行例</a> &middot;
  <a href="docs/REFERENCE.md">詳細リファレンス</a>
</p>


[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> [!WARNING]
> **研究・学習用のツールです。投資助言ではありません。** ROT が出すのはシグナルと取引アイデアであり、検証済みの戦略ではありません。オプションは支払ったプレミアムの 100% を失うことがあり、Reddit のセンチメントはノイズが多く操作されることもしばしばで、LLM の推論は自信満々に間違えることがあります。ブローカー連携はデフォルトでペーパートレードです。

<img alt="ROT の Web ダッシュボード：シグナル数、平均信頼度、強気/弱気/混在の内訳、ティッカー・スタンス・信頼度・LLM が書いた要約付きの最新シグナル一覧、話題のティッカー" src="docs/img/dashboard.png" width="100%">

*ローカルで動かしているダッシュボード（2026 年 2 月のスクリーンショット、Reddit のライブデータ）。*

<a id="try-it-in-one-command"></a>
## コマンドひとつで試す

Reddit アカウントも API キーも不要です。デモは同梱の 5 件のサンプル投稿で本物のパイプラインを動かします。

```bash
git clone https://gitlab.com/mattbusel/Reddit-Options-Trader-ROT.git && cd Reddit-Options-Trader-ROT-
pip install -e . && python examples/demo.py
```

Python 3.10 以上が必要です。[`examples/sample/posts.json`](examples/sample/posts.json) のサンプル投稿はデモ用に書いたもので、実際の Reddit 投稿ではありません。ティッカーのチェックと価格は 2026-09-28 に保存した Yahoo Finance のスナップショットを使うので、オフラインで動きます。最新の価格を使うには `--live` を付けてください。

Reddit のライブデータとダッシュボード付きでアプリ全体を動かすには、`.env.example` を `.env` にコピーし、Reddit の API キーを追加して `docker compose up --build` を実行します（そのあと http://localhost:8000/dashboard を開きます）。ホストされたインスタンスはありません。以前の Railway へのデプロイは停止しています。

<a id="how-it-works"></a>
## 仕組み

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/pipeline-dark.svg">
  <img alt="9 つのパイプライン段階を蛇行するカードで表した図：取り込み（投稿 5 件）、トレンド（4 件がトレンド入り、1 秒あたりの upvote + 2 × 1 秒あたりのコメントが 0.01 以上）、ティッカー（3 件にティッカーあり）、イベント（3 件）、検証と情報付加（3 件に価格）、信頼度（3 件を 0 から 1 でスコア化）、抑制（3 件を残す）、LLM またはスタブによる推論（3 件）、取引アイデア（3 件の記録、レグ付きは 0 件）。下部：決算のうわさは信頼度 0.25 に抑えられ、0.30 の基準を下回る。スタンス不明は決して取引しない。週末はすべての取引をブロックする。" src="docs/img/pipeline-light.svg" width="100%">
</picture>

ざっくり言うと、ポーリングのたびに（デフォルトでは Reddit を 20 秒ごとにポーリング）次のことを行います。

1. **取り込みとトレンド判定**。投稿は Reddit と RSS のニュースフィードから入ってきます。2 回のポーリングの間に upvote とコメントが急に増えた投稿が「トレンド入り」します。
2. **ティッカーと話題を見つける**。独自の NLP エンジンが `$TSLA` のようなティッカー、イベントの種類（決算のうわさ、製品ニュース、スクイーズの話題など）、スタンス（強気、弱気、混在）、時間軸を抽出します。ティッカーは実際の市場データで照合されます。
3. **信頼度をスコア化する**。0 から 1 の信頼度スコアは、DD 投稿（デューデリジェンス投稿）、質の良いサブレディット、エンゲージメントを加点し、クロスポスト、新規アカウント、パンプ・アンド・ダンプ的な言い回しを減点します。
4. **推論して判断する**。LLM（キーがない場合は内蔵のスタブ）が取引の根拠を書き、トレードビルダーが具体的な構成（デビット/クレジット・スプレッド、ストラドルなど）を提案するか、取引しない理由を記録します。

コード：[`src/rot/app/runner.py`](src/rot/app/runner.py)（`PipelineRunner.run_once`）。図のソース：[`scripts/make_pipeline_svg.py`](scripts/make_pipeline_svg.py)。

<a id="examples"></a>
## 実行例

2026-09-28 に `python examples/demo.py` を実行した実際の出力です（スタブ推論、同梱の市場スナップショット）。

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

ここから分かること：r/options の DD 投稿が最も高いスコア（0.70）、r/wallstreetbets のうわさが最も低いスコア（0.45）でした。煽り投稿にはティッカーがなく、落ち着いた質問はトレンド入りしないため、どちらも早い段階で止まります。そして ROT は 3 つのイベントすべてについて取引を見送り、その理由をログに残します。各段階は JSONL の監査ログも書き出します。`python examples/demo.py --keep` を使うとそれがディスクに残ります。例：

```json
{"run_id": "run_1790631982", "trade_idea": {"underlying": "AMD", "strategy": "none", "legs": [], "max_loss": 0.0, "thesis": "Reddit chatter mentions AMD; treat as unverified signal.", "time_stop": "N/A", "quality_score": 0.0, "do_not_trade_reasons": ["unknown_stance"], "meta": {}}, "ts": 1790631982}
```

## 3 ステップで使う

1. 上のデモを実行して、サンプル投稿で各段階を確認します。
2. [`.env.example`](.env.example) をもとに、Reddit の API キー（必要なら LLM のキーも）を `.env` に書きます。
3. アプリを起動します：`docker compose up --build`、または `pip install -e .` のあとに `python -m rot.app.server` を実行してから http://localhost:8000/dashboard を開きます。API ドキュメントは `/docs` にあります。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [docs/REFERENCE.md](docs/REFERENCE.md) | 以前の長い README の内容すべて：クイックスタートのオプション、アーキテクチャ、シグナル品質の要因、設定、オプションチェーン、API、リネージ、ブローカー、リスクモニター、テスト、デプロイ、セキュリティ、ラウンドごとの機能メモ |
| [docs/architecture.md](docs/architecture.md) | パイプラインの各段階と設計上の判断 |
| [docs/config.md](docs/config.md) | すべての `ROT_*` 環境変数 |
| [docs/api-reference.md](docs/api-reference.md) | REST と WebSocket のエンドポイント |
| [docs/nlp-engine.md](docs/nlp-engine.md) | 独自の NLP エンジン |
| [docs/deployment.md](docs/deployment.md) | Docker とセルフホスティング |
| [SECURITY.md](SECURITY.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG.md](CHANGELOG.md) | セキュリティポリシー、コントリビューション、履歴 |

## ライセンス

MIT。[LICENSE](LICENSE) を参照してください。サードパーティのライセンス：[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。研究・学習用のみです。作者は金銭的な損失について一切責任を負いません。失っても困らない資金以外は決してリスクにさらさないでください。
