# Credibility Scoring — ROT Feature Reference
> Part of the ROT documentation suite. See [CLAUDE.md](../../CLAUDE.md) for the full index.

## Quick Start for Agents
- Key files: `src/rot/credibility/scorer.py`, `src/rot/credibility/ml_scorer.py`, `src/rot/credibility/features.py`, `src/rot/credibility/train.py`
- DB tables: `signal_performance` (training data source), `signals` (stores results in `event_data` JSON)
- Routes: None dedicated (credibility is a pipeline stage, not a user-facing feature)
- Config: `ROT_ML_ENABLED`, `ROT_ML_MODEL_PATH`, `ROT_ML_MIN_TRAINING_SAMPLES`, `ROT_ML_RETRAIN_INTERVAL_S`, `ROT_ML_MIN_CLASS_SAMPLES`

---

## Pipeline Position

Credibility scoring is **Stage 6** in the pipeline, after market enrichment and before adaptive suppression (Stage 6.5). It directly modifies `event.confidence`, which is then used by all downstream stages (suppressor, LLM reasoning, trade building, storage).

## Dual-Path Architecture

```
Event arrives
    |
    v
MLCredibilityScorer.score(event)
    |
    +--> Heuristic scorer always runs (for comparison metadata)
    |
    +--> ML model available?
         |
         YES --> P(win) from GradientBoosting [0.05, 0.95]
         NO  --> Heuristic adjustment [0.05, 1.0]
    |
    v
Both scores stored in meta["ml_credibility"]
event.confidence = chosen score
```

## ML Path: GradientBoosting Classifier

### Model
- **Algorithm**: scikit-learn `GradientBoostingClassifier`
- **Target**: Binary classification (win vs loss)
- **Output**: P(win) probability used as confidence score
- **Range**: Clamped to [0.05, 0.95]
- **Validation**: 5-fold cross-validation during training

### 32-Feature Vector (`features.py`)

Features extracted from Event metadata, organized by category:

| Category | Features | Source |
|----------|----------|--------|
| Post metadata | score, num_comments, upvote_ratio, body_length, is_crosspost | `event.meta` |
| Trend | trend_score, score_velocity, comment_velocity | `event.meta` |
| NLP | polarity, intensity, conviction, sarcasm_prob, actionability, urgency, consensus_score | NLP analysis |
| Market | price_change_1d, market_cap (log), atm_iv, put_call_ratio | Market enrichment |
| Author | karma (log), account_age_days | Post metadata |
| Categorical | event_type (one-hot), stance (one-hot), subreddit group | Encoded features |

The same feature extraction logic is shared between inference (`Event` objects) and training (`DB row` dicts) to ensure consistency.

### Live Training (`train.py`)

Training runs in a background loop every 24 hours:
1. Queries `signal_performance` for resolved win/loss outcomes
2. Requires 100+ decided signals with 30+ in each class (win/loss)
3. Extracts 32-feature vectors from stored event metadata
4. Trains GradientBoosting with 5-fold cross-validation
5. Saves model as pickle file
6. Hot-reloads into `MLCredibilityScorer` without server restart

### First Deployment Behavior

When no trained model exists (insufficient data), `MLCredibilityScorer` automatically falls back to the heuristic scorer. As signals accumulate and get price-checked, the ML model will eventually train and activate.

## Heuristic Path: 12-Factor Scoring (`scorer.py`)

The heuristic path adjusts `event.confidence` by adding/subtracting factors. It always runs internally (even when ML is active) to provide comparison data.

### Factor Table

| # | Factor | Adjustment | Condition |
|---|--------|-----------|-----------|
| 0 | `institutional_rss` | +0.15 | RSS from FDA/DoD/Fed/SEC feeds |
| 0b | `news_rss` | +0.05 | Any other RSS source |
| 1 | `dd_flair` | +0.15 | DD flair + body >= 200 chars |
| 1b | `dd_flair_shallow` | +0.05 | DD flair + short body |
| 1c | `quality_flair` | +0.05 | Discussion/TA/Fundamentals flair |
| 2 | `too_many_tickers` | -0.15 | 5+ entities |
| 2b | `focused_ticker` | +0.05 | Exactly 1 entity |
| 3 | `crosspost_penalty` | -0.10 | Post is a crosspost |
| 4 | `high_score` | +0.05 | Post score > 100 |
| 4b | `controversial` | -0.05 | Upvote ratio < 0.6 |
| 5 | `high_discussion` | +0.05 | Comments > score x 0.5 |
| 6 | `has_body_analysis` | +0.05 | Body > 100 chars |
| 7 | `subreddit_boost` | +0.05 | options/thetagang/investing/valueinvesting |
| 7b | `subreddit_penalty` | -0.05 to -0.10 | wsb/shortsqueeze/pennystocks |
| 8a-e | `author_karma/age` | -0.10 to +0.10 | Karma and account age checks |
| 9 | `nlp_sarcasm` | -0.00 to -0.15 | Sarcasm probability > 0.5 |
| 10a-b | `nlp_conviction` | -0.05 to +0.05 | Conviction > 0.7 or < 0.3 |
| 11a-c | `nlp_consensus` | -0.05 to +0.10 | Thread consensus / contrarian |
| 12 | `nlp_actionability` | -0.10 | Temporal actionability < 0.3 |

## A/B Monitoring

Both ML and heuristic scores are stored in `meta["ml_credibility"]` for every signal:
```json
{
  "ml_score": 0.62,
  "heuristic_score": 0.55,
  "model_version": "2026-02-10",
  "used_ml": true
}
```
This enables offline analysis comparing ML vs heuristic accuracy over time.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_ML_ENABLED` | `True` | Enable ML scoring (falls back to heuristic if no model) |
| `ROT_ML_MODEL_PATH` | `""` | Path to model pickle (auto-derived if empty) |
| `ROT_ML_MIN_TRAINING_SAMPLES` | `100` | Min resolved signals to start training |
| `ROT_ML_RETRAIN_INTERVAL_S` | `86400` | Seconds between retrain attempts (24h) |
| `ROT_ML_MIN_CLASS_SAMPLES` | `30` | Min samples per class (win/loss) |

## Tests

- `test_credibility.py` -- All 12 heuristic scoring factors
- `test_ml_credibility.py` -- ML feature extraction, scorer fallback, mock model inference
