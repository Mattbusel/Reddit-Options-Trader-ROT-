<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Credibility Scoring

- **Files**: `src/rot/credibility/{scorer,ml_scorer,features,train}.py`
- **DB**: reads `signal_performance` (training), writes to `event_data` JSON in `signals`
- **Config**: `ROT_ML_ENABLED` (True), `ROT_ML_MODEL_PATH`, `ROT_ML_MIN_TRAINING_SAMPLES` (100), `ROT_ML_RETRAIN_INTERVAL_S` (86400), `ROT_ML_MIN_CLASS_SAMPLES` (30)
- **Pipeline Stage 6**: after market enrichment, before suppression (6.5). Modifies `event.confidence`.

## Dual-Path Architecture
`MLCredibilityScorer.score(event)` always runs heuristic internally, then:
- **ML available**: confidence = P(win) from GradientBoosting [0.05, 0.95]
- **ML unavailable**: confidence = heuristic adjustment [0.05, 1.0]
- Both scores stored in `meta["ml_credibility"]` for A/B monitoring

## ML Path: GradientBoosting
- scikit-learn `GradientBoostingClassifier`, binary (win/loss), 5-fold CV
- **32 features** (`features.py`): post metadata (score, comments, upvote_ratio, body_len, crosspost), trend (score, velocities), NLP (polarity, intensity, conviction, sarcasm, actionability, urgency, consensus), market (price_change, cap_log, IV, P/C ratio), author (karma_log, age), categorical (event_type one-hot, stance one-hot, subreddit group)
- Same extraction for inference (Event) and training (DB row)
- **Live training** (`train.py`): background loop every 24h, queries resolved outcomes, needs 100+ signals with 30+ per class, saves pickle, hot-reloads

## Heuristic Path: 12 Factors (`scorer.py`)
| # | Factor | Adj | Condition |
|---|--------|-----|-----------|
| 0 | institutional_rss | +0.15 | FDA/DoD/Fed/SEC RSS |
| 0b | news_rss | +0.05 | Other RSS |
| 1 | dd_flair | +0.15 | DD flair + body>=200 |
| 1b | dd_flair_shallow | +0.05 | DD flair + short body |
| 1c | quality_flair | +0.05 | Discussion/TA/Fundamentals |
| 2 | too_many_tickers | -0.15 | 5+ entities |
| 2b | focused_ticker | +0.05 | 1 entity |
| 3 | crosspost_penalty | -0.10 | Is crosspost |
| 4 | high_score | +0.05 | Score > 100 |
| 4b | controversial | -0.05 | Upvote ratio < 0.6 |
| 5 | high_discussion | +0.05 | Comments > score*0.5 |
| 6 | has_body_analysis | +0.05 | Body > 100 chars |
| 7 | subreddit_boost | +0.05 | options/thetagang/investing |
| 7b | subreddit_penalty | -0.05..-0.10 | wsb/shortsqueeze/pennystocks |
| 8a-e | author_karma/age | -0.10..+0.10 | Karma/age thresholds |
| 9 | nlp_sarcasm | -0.00..-0.15 | Sarcasm > 0.5 |
| 10 | nlp_conviction | -0.05..+0.05 | Conviction thresholds |
| 11 | nlp_consensus | -0.05..+0.10 | Thread consensus/contrarian |
| 12 | nlp_actionability | -0.10 | Actionability < 0.3 |

## Tests
`test_credibility.py` (12 heuristic factors), `test_ml_credibility.py` (features, fallback, mock inference)
