# Reddit Options Trader (ROT)

[English](README.md) | 简体中文 | [日本語](README.ja.md) | [한국어](README.ko.md)

**一个 Python 应用：读取 Reddit 帖子和市场新闻，发现大家突然热议的股票代码，给每条帖子的可信度打分，再把它变成一个期权交易思路，或者一个明确的不交易理由。** 它是一条 Reddit 情绪分析与期权信号流水线，带有 Web 仪表盘、REST/WebSocket API，以及可选的大模型（LLM）推理（OpenAI、Anthropic 或 DeepSeek）。

面向想把 Reddit 情绪当作交易信号来研究的开发者和散户期权交易者，也适合想了解一条社交媒体 NLP 流水线如何从头到尾搭建起来的人。

<p align="center">
  <a href="https://mattbusel.vercel.app/Reddit-Options-Trader-ROT-/"><b>项目网站</b></a> &middot;
  <a href="#try-it-in-one-command">试用</a> &middot;
  <a href="#how-it-works">工作原理</a> &middot;
  <a href="#examples">示例</a> &middot;
  <a href="docs/REFERENCE.md">完整参考</a>
</p>


[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> [!WARNING]
> **仅供研究和学习使用，不构成投资建议。** ROT 产出的是信号和交易思路，而不是经过检验的策略。期权可能让你损失全部已付权利金，Reddit 情绪噪声很大且经常被操纵，大模型推理也可能自信地给出错误结论。券商对接默认使用模拟盘交易。

<img alt="ROT Web 仪表盘：信号数量、平均置信度、看涨/看跌/分歧的占比、最新信号列表（含股票代码、立场、置信度和大模型撰写的摘要），以及热门股票代码" src="docs/img/dashboard.png" width="100%">

*在本地运行的仪表盘（2026 年 2 月截图，Reddit 实时数据）。*

<a id="try-it-in-one-command"></a>
## 一条命令试用

无需 Reddit 账号，无需 API 密钥。演示程序会在仓库自带的五条示例帖子上运行真实的流水线：

```bash
git clone https://gitlab.com/mattbusel/Reddit-Options-Trader-ROT.git && cd Reddit-Options-Trader-ROT-
pip install -e . && python examples/demo.py
```

需要 Python 3.10+。[`examples/sample/posts.json`](examples/sample/posts.json) 中的示例帖子是专门为演示编写的（不是真实的 Reddit 帖子）；股票代码校验和价格来自 2026-09-28 保存的 Yahoo Finance 快照，因此可以离线运行。加上 `--live` 可获取最新价格。

要使用 Reddit 实时数据和仪表盘运行完整应用，请把 `.env.example` 复制为 `.env`，填入你的 Reddit API 密钥，然后运行 `docker compose up --build`（然后打开 http://localhost:8000/dashboard 即可）。目前没有托管的在线实例：以前部署在 Railway 上的版本已经下线。

<a id="how-it-works"></a>
## 工作原理

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/pipeline-dark.svg">
  <img alt="以蛇形卡片排列的九个流水线阶段：抓取（5 条帖子）、趋势（4 条成为趋势，每秒点赞数加上 2 倍每秒评论数至少为 0.01）、股票代码（3 条带股票代码）、事件（3 个）、校验与补充数据（3 个获得价格）、可信度（3 个打分，0 到 1）、抑制（保留 3 个）、用大模型或桩实现推理（3 个）、交易思路（3 条记录，0 条有期权腿）。下方说明：财报传闻的置信度被限制为 0.25，低于 0.30 的门槛；立场未知时永不交易；周末会阻止所有交易。" src="docs/img/pipeline-light.svg" width="100%">
</picture>

通俗地说，每一次轮询时（默认每 20 秒轮询一次 Reddit）：

1. **抓取与趋势判断**。帖子来自 Reddit 和 RSS 新闻源。如果一条帖子的点赞数和评论数在两次轮询之间增长很快，它就“成为趋势”。
2. **找出股票代码和事件**。一个自研的 NLP 引擎会提取 `$TSLA` 这样的股票代码、事件类型（财报传闻、产品新闻、逼空讨论等）、立场（看涨、看跌、分歧）以及时间周期。股票代码会用真实市场数据进行校验。
3. **给可信度打分**。一个 0 到 1 的可信度分数会奖励 DD 帖（深度研究帖）、优质的子版块和互动度，并惩罚转帖、新账号以及拉高出货式的措辞。
4. **推理与决策**。由大模型（没有密钥时使用内置的桩实现）写出一个交易逻辑，交易构建器要么提出一个期权结构（借方/贷方价差、跨式组合等），要么记录不交易的原因。

代码：[`src/rot/app/runner.py`](src/rot/app/runner.py)（`PipelineRunner.run_once`）。示意图源码：[`scripts/make_pipeline_svg.py`](scripts/make_pipeline_svg.py)。

<a id="examples"></a>
## 示例

2026-09-28 运行 `python examples/demo.py` 的真实输出（桩推理，自带的市场数据快照）：

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

从中可以看到：r/options 上的 DD 帖得分最高（0.70），r/wallstreetbets 上的传闻得分最低（0.45）；喊单帖没有股票代码，平静的提问帖从未成为趋势，所以这两条都在早期阶段就停下了；而对全部三个事件，ROT 都拒绝交易，并记录了原因。每个阶段还会写入一份 JSONL 审计记录。`python examples/demo.py --keep` 会把它保留在磁盘上，例如：

```json
{"run_id": "run_1790631982", "trade_idea": {"underlying": "AMD", "strategy": "none", "legs": [], "max_loss": 0.0, "thesis": "Reddit chatter mentions AMD; treat as unverified signal.", "time_stop": "N/A", "quality_score": 0.0, "do_not_trade_reasons": ["unknown_stance"], "meta": {}}, "ts": 1790631982}
```

## 三步上手

1. 运行上面的演示，在示例帖子上看到每一个阶段。
2. 参照 [`.env.example`](.env.example)，把你的 Reddit API 密钥（以及可选的大模型密钥）写入 `.env`。
3. 启动应用：`docker compose up --build`，或者在 `pip install -e .` 之后运行 `python -m rot.app.server`，然后打开 http://localhost:8000/dashboard 即可。API 文档位于 `/docs`。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/REFERENCE.md](docs/REFERENCE.md) | 旧版长 README 中的全部内容：快速开始选项、架构、信号质量因素、配置、期权链、API、数据血缘、券商、风险监控、测试、部署、安全、每轮功能说明 |
| [docs/architecture.md](docs/architecture.md) | 流水线各阶段和设计决策 |
| [docs/config.md](docs/config.md) | 所有 `ROT_*` 环境变量 |
| [docs/api-reference.md](docs/api-reference.md) | REST 和 WebSocket 接口 |
| [docs/nlp-engine.md](docs/nlp-engine.md) | 自研的 NLP 引擎 |
| [docs/deployment.md](docs/deployment.md) | Docker 和自托管 |
| [SECURITY.md](SECURITY.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG.md](CHANGELOG.md) | 安全策略、贡献指南、版本历史 |

## 许可证

MIT，见 [LICENSE](LICENSE)。第三方许可证：[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。仅供研究和学习使用；作者不对任何财务损失承担责任。永远不要拿你输不起的资金去冒险。
