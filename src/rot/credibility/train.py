"""Train the ML credibility model from historical signal performance data.

Can be run standalone:
    python -m rot.credibility.train [--db-path PATH] [--output PATH]

Or called programmatically via ``train_model_from_db()`` for live retraining
inside the server process.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Guard sklearn import — only needed at training time, not during normal scoring
try:
    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.pipeline import Pipeline

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

from rot.credibility.features import FEATURE_NAMES, extract_features_from_row

# ── Training SQL ───────────────────────────────────────────────────────────
# Uses the same stance-aware win/loss CASE logic as database.py

_PRICE_COL = "COALESCE(sp.price_1d, sp.price_4h, sp.price_1h)"

_TRAINING_SQL = f"""  # nosec B608 - SQL uses constants only, values parameterized
    SELECT
        s.id,
        s.event_type,
        s.stance,
        s.time_horizon,
        s.strategy,
        s.subreddit,
        s.trend_score,
        s.confidence,
        s.sarcasm_score,
        s.conviction,
        s.consensus_score,
        s.actionability,
        s.nlp_polarity,
        s.author_karma,
        s.author_age_days,
        s.event_data,
        s.market_data,
        sp.price_at_signal,
        /* Win label */
        CASE
            WHEN s.stance = 'bullish'
                 AND ({_PRICE_COL} - sp.price_at_signal) / sp.price_at_signal > 0.005
            THEN 1
            WHEN s.stance = 'bearish'
                 AND (sp.price_at_signal - {_PRICE_COL}) / sp.price_at_signal > 0.005
            THEN 1
            WHEN s.stance = 'mixed'
                 AND s.strategy IN ('straddle', 'strangle')
                 AND ABS({_PRICE_COL} - sp.price_at_signal) / sp.price_at_signal > 0.015
            THEN 1
            WHEN s.stance = 'mixed'
                 AND s.strategy = 'iron_condor'
                 AND ABS({_PRICE_COL} - sp.price_at_signal) / sp.price_at_signal < 0.010
            THEN 1
            WHEN s.stance = 'mixed'
                 AND s.strategy NOT IN ('straddle', 'strangle', 'iron_condor')
                 AND ABS({_PRICE_COL} - sp.price_at_signal) / sp.price_at_signal > 0.005
            THEN 1
            ELSE 0
        END as is_win,
        /* Loss label */
        CASE
            WHEN s.stance = 'bullish'
                 AND (sp.price_at_signal - {_PRICE_COL}) / sp.price_at_signal > 0.005
            THEN 1
            WHEN s.stance = 'bearish'
                 AND ({_PRICE_COL} - sp.price_at_signal) / sp.price_at_signal > 0.005
            THEN 1
            WHEN s.stance = 'mixed'
                 AND s.strategy IN ('straddle', 'strangle')
                 AND ABS({_PRICE_COL} - sp.price_at_signal) / sp.price_at_signal < 0.010
            THEN 1
            WHEN s.stance = 'mixed'
                 AND s.strategy = 'iron_condor'
                 AND ABS({_PRICE_COL} - sp.price_at_signal) / sp.price_at_signal > 0.015
            THEN 1
            ELSE 0
        END as is_loss
    FROM signal_performance sp
    JOIN signals s ON sp.signal_id = s.id
    WHERE sp.price_at_signal > 0
        AND {_PRICE_COL} IS NOT NULL
        AND s.stance != 'unknown'
"""


# ── Data loading ───────────────────────────────────────────────────────────

async def _load_training_data(
    db_path: str,
) -> Tuple[Optional[Any], Optional[Any], int, int, int]:
    """Query DB for labeled training samples.

    Returns (X, y, n_wins, n_losses, n_skipped) or (None, None, ...) if
    sklearn is not installed.
    """
    if not _SKLEARN_AVAILABLE:
        log.error("scikit-learn not installed — cannot train ML model")
        return None, None, 0, 0, 0

    import aiosqlite

    X_rows: List[List[float]] = []
    y_labels: List[int] = []
    n_skipped = 0

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(_TRAINING_SQL) as cursor:
            async for row in cursor:
                row_dict = dict(row)
                is_win = row_dict.get("is_win", 0)
                is_loss = row_dict.get("is_loss", 0)

                # Skip neutral outcomes (ambiguous labels degrade quality)
                if not is_win and not is_loss:
                    n_skipped += 1
                    continue

                try:
                    features = extract_features_from_row(row_dict)
                    X_rows.append(features)
                    y_labels.append(1 if is_win else 0)
                except Exception as exc:
                    log.debug("Skipping row %s: %s", row_dict.get("id"), exc)
                    n_skipped += 1

    if not X_rows:
        return None, None, 0, 0, n_skipped

    X = np.array(X_rows, dtype=np.float64)
    y = np.array(y_labels, dtype=np.int64)
    n_wins = int(y.sum())
    n_losses = len(y) - n_wins

    return X, y, n_wins, n_losses, n_skipped


def _build_and_train(
    X: Any, y: Any, output_path: str
) -> Tuple[bool, float, Dict[str, float]]:
    """Train a GradientBoosting pipeline, save to disk.

    Returns (success, cv_auc_mean, feature_importances_dict).
    """
    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", GradientBoostingClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.1,
            min_samples_leaf=10,
            subsample=0.8,
            random_state=42,
        )),
    ])

    # Cross-validation
    n_splits = min(5, min(int(y.sum()), len(y) - int(y.sum())))
    if n_splits < 2:
        n_splits = 2

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    scores = cross_val_score(pipeline, X, y, cv=cv, scoring="roc_auc")
    cv_mean = float(scores.mean())
    cv_std = float(scores.std())
    log.info("Cross-val ROC-AUC: %.3f +/- %.3f (%d folds)", cv_mean, cv_std, n_splits)

    # Train on full dataset
    pipeline.fit(X, y)

    # Save model
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(pipeline, f)
    log.info("ML credibility model saved to %s", output_path)

    # Feature importances
    importances = pipeline.named_steps["clf"].feature_importances_
    imp_dict = {}
    for name, imp in sorted(
        zip(FEATURE_NAMES, importances), key=lambda x: -x[1]
    ):
        imp_dict[name] = round(float(imp), 4)
        log.info("  %-25s %.4f", name, imp)

    return True, cv_mean, imp_dict


# ── Public API ─────────────────────────────────────────────────────────────

async def train_model_from_db(
    db_path: str,
    output_path: str,
    min_samples: int = 100,
    min_class_samples: int = 30,
) -> bool:
    """Train (or retrain) the ML model from the database.

    Returns True if a model was successfully trained and saved.
    """
    if not _SKLEARN_AVAILABLE:
        log.warning("scikit-learn not installed — ML training skipped")
        return False

    t0 = time.monotonic()
    log.info("ML training: loading data from %s ...", db_path)

    X, y, n_wins, n_losses, n_skipped = await _load_training_data(db_path)

    if X is None or y is None or len(y) == 0:
        log.info(
            "ML training: no labeled data found (skipped %d neutral). "
            "Heuristic scorer will be used until data accumulates.",
            n_skipped,
        )
        return False

    total = len(y)
    log.info(
        "ML training: %d samples (%d wins, %d losses, %d neutral skipped)",
        total,
        n_wins,
        n_losses,
        n_skipped,
    )

    if total < min_samples:
        log.info(
            "ML training: need %d samples (have %d). Waiting for more data.",
            min_samples,
            total,
        )
        return False

    if n_wins < min_class_samples or n_losses < min_class_samples:
        log.info(
            "ML training: need %d+ in each class (have %d wins, %d losses). "
            "Waiting for more data.",
            min_class_samples,
            n_wins,
            n_losses,
        )
        return False

    success, cv_auc, importances = _build_and_train(X, y, output_path)

    elapsed = time.monotonic() - t0
    if success:
        log.info(
            "ML training complete in %.1fs — ROC-AUC=%.3f, %d features, %d samples",
            elapsed,
            cv_auc,
            len(FEATURE_NAMES),
            total,
        )
    return success


# ── CLI entry point ────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Train ML credibility model from historical signal data"
    )
    parser.add_argument("--db-path", default="storage/rot.db")
    parser.add_argument("--output", default="storage/credibility_model.pkl")
    parser.add_argument("--min-samples", type=int, default=100)
    parser.add_argument("--min-class-samples", type=int, default=30)
    args = parser.parse_args()

    success = asyncio.run(
        train_model_from_db(
            args.db_path,
            args.output,
            min_samples=args.min_samples,
            min_class_samples=args.min_class_samples,
        )
    )
    if not success:
        log.warning("Model was NOT trained. See messages above for reason.")


if __name__ == "__main__":
    main()
