<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Social Intelligence Network

**Module**: `src/rot/social/` (7 files)
**Tier**: Pro+ (gated by `gate_social_access()`)

## Modules

| File | Purpose |
|------|---------|
| `types.py` | AuthorProfile, AuthorPrediction, ManipulationAlert, SentimentPropagation, AuthorCluster, ContrarianSignal |
| `tracker.py` | Record/resolve predictions, compute accuracy/ROI/Sharpe, leaderboard, history |
| `manipulation.py` | Coordinated posting, bot network, pump-and-dump detection |
| `propagation.py` | Cross-subreddit/platform spread, virality velocity, leading/lagging subs |
| `network.py` | Co-mention graph, hierarchical clustering, community detection, contrarian signals |
| `confidence.py` | AuthorConfidenceAdjuster: pipeline Stage 6 plugin, boost/penalize by author accuracy |

## Author Tracking

`AuthorTracker` records predictions when signals are created, resolves them against actual price outcomes. Computes accuracy, ROI-if-followed, Sharpe ratio, reputation score.

## Manipulation Detection

- **coordinated_posting** — Multiple authors posting same ticker in short window
- **bot_network** — High-frequency posting, low account age, threshold `BOT_DETECTION_THRESHOLD` (0.8)
- **pump_and_dump** — Price spike + volume spike within `PUMP_DUMP_WINDOW_S` (2h)

## Confidence Adjustment (Pipeline Plugin)

`AuthorConfidenceAdjuster` hooks into Stage 6. Authors with >60% win rate + 10+ predictions get confidence boost. Authors with <30% win rate get penalized.

## DB Tables

- `author_profiles` — id, platform, username, total_signals, win/loss counts, accuracy, roi_if_followed, sharpe, reputation_score, stats_json, first/last_seen, updated_at
- `author_predictions` — id, author_id, signal_id, ticker, stance, confidence, outcome, pnl_pct, created_at, resolved_at
- `manipulation_alerts` — id, alert_type, tickers_json, authors_json, evidence_json, severity, detected_at, resolved
- `sentiment_propagation` — id, ticker, origin_sub, spread_to, origin_ts, spread_ts, lag_seconds, detected_at
- `author_clusters` — id, authors_json, similarity_score, common_tickers_json, detected_at

## Routes

- `GET /social` — Dashboard
- `GET /social/author/{username}` — Author profile page
- `GET /api/v1/social/leaderboard` — Author accuracy leaderboard
- `GET /api/v1/social/author/{username}` — Author profile JSON
- `GET /api/v1/social/manipulation` — Manipulation alerts
- `GET /api/v1/social/propagation/{ticker}` — Sentiment propagation timeline
- `GET /api/v1/social/contrarian` — Contrarian signals

## Tier Gating

Pro: leaderboard only. Premium: author profiles + manipulation alerts. Ultra: propagation + contrarian + export.

## Background Loops

- `_author_resolution_loop()` every 1h — resolves pending predictions against price outcomes
- `_manipulation_scan_loop()` every 30min — scans for coordinated posting, bots, pump-dump

## Config (`ROT_SOCIAL_*`)

TRACKING_ENABLED=True, MANIPULATION_SCAN_INTERVAL_S=1800, AUTHOR_RESOLUTION_INTERVAL_S=3600, MIN_PREDICTIONS_FOR_SCORE=10, BOT_DETECTION_THRESHOLD=0.8, PUMP_DUMP_WINDOW_S=7200, PROPAGATION_MAX_LAG_S=86400, PURGE_KEEP_DAYS=180
