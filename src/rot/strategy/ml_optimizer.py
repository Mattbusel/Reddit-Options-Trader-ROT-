"""ML-powered strategy optimizer for the Strategy Builder.

Uses scikit-learn GradientBoostingClassifier to discover which signal features
best predict wins, then auto-generates StrategyRule objects from feature
importance rankings.  Integrates with the BacktestEngine so that generated
strategies can be immediately validated against historical signal data.

Feature extraction mirrors and extends the 32-feature credibility vector from
``rot.credibility.features`` with additional temporal and market-structure
features (50+ total) specifically tuned for strategy rule generation.
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rot.strategy.types import StrategyRule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional sklearn — graceful degradation if not installed
# ---------------------------------------------------------------------------

try:
    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score

    _HAS_SKLEARN = True
except ImportError:  # pragma: no cover
    _HAS_SKLEARN = False
    logger.warning(
        "scikit-learn/numpy not installed — MLStrategyOptimizer will return "
        "empty results.  Install with: pip install scikit-learn numpy"
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EVENT_TYPES = [
    "earnings_rumor",
    "product_news",
    "regulatory",
    "squeeze_chatter",
    "macro",
    "other",
]

_TOP_SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "options",
    "investing",
    "thetagang",
]

_STANCE_ENCODE: Dict[str, float] = {
    "bullish": 1.0,
    "bearish": -1.0,
    "mixed": 0.0,
    "unknown": 0.0,
}

_HORIZON_ENCODE: Dict[str, float] = {
    "intraday": 1.0,
    "1w": 2.0,
    "earnings": 3.0,
    "longer": 4.0,
    "unknown": 0.0,
}

_MARKET_CAP_THRESHOLDS = [
    (2e9, "small"),
    (10e9, "mid"),
    (200e9, "large"),
    (float("inf"), "mega"),
]
"""Buckets: <2B = small, <10B = mid, <200B = large, >=200B = mega."""

# ---------------------------------------------------------------------------
# Feature name registry (fixed order, 52 features)
# ---------------------------------------------------------------------------

FEATURE_NAMES: List[str] = [
    # Numeric core (0-2)
    "confidence",
    "trend_score",
    "quality_score",
    # Stance (3)
    "stance_encoded",
    # Event-type one-hot (4-9)
    "evt_earnings_rumor",
    "evt_product_news",
    "evt_regulatory",
    "evt_squeeze_chatter",
    "evt_macro",
    "evt_other",
    # Subreddit one-hot (10-15)
    "sub_wallstreetbets",
    "sub_stocks",
    "sub_options",
    "sub_investing",
    "sub_thetagang",
    "sub_other",
    # Horizon (16)
    "horizon_encoded",
    # Market data (17-21)
    "price_change_pct",
    "market_cap_bucket",
    "iv",
    "put_call_ratio",
    "market_cap_log",
    # NLP features (22-26)
    "nlp_polarity",
    "nlp_conviction",
    "nlp_sarcasm_prob",
    "nlp_actionability",
    "nlp_consensus_score",
    # Post metadata (27-30)
    "post_score_log",
    "num_comments_log",
    "upvote_ratio",
    "body_length_bucket",
    # Temporal (31-32)
    "hour_of_day",
    "day_of_week",
    # Extended NLP (33-36)
    "nlp_intensity",
    "nlp_urgency",
    "nlp_thread_agreement",
    "nlp_contrarian",
    # Extended post (37-39)
    "entity_count",
    "is_crosspost",
    "comment_score_ratio",
    # Trend detail (40-41)
    "score_rate",
    "comment_rate",
    # Author (42-44)
    "author_karma_log",
    "author_age_days",
    "author_age_bucket",
    # Source flags (45-46)
    "is_rss",
    "is_stocktwits",
    # Market structure (47-49)
    "volume_ratio",
    "cap_bucket_small",
    "cap_bucket_mega",
    # Interactions (50-51)
    "confidence_x_conviction",
    "trend_x_consensus",
]

NUM_FEATURES = len(FEATURE_NAMES)  # 52


# ---------------------------------------------------------------------------
# Feature-to-rule mapping metadata
# ---------------------------------------------------------------------------

@dataclass
class _FeatureMeta:
    """Metadata for translating a feature back into a StrategyRule."""

    name: str
    rule_field: str
    rule_type: str  # "numeric_gte", "numeric_lte", "categorical_eq", "categorical_in", "skip"
    signal_path: str = ""  # dot-delimited path in signal dict


# Mapping from feature name to how it becomes a rule.
# Only features that make meaningful rules are included.
_FEATURE_TO_RULE: Dict[str, _FeatureMeta] = {
    "confidence": _FeatureMeta("confidence", "confidence", "numeric_gte"),
    "trend_score": _FeatureMeta("trend_score", "trend_score", "numeric_gte"),
    "quality_score": _FeatureMeta("quality_score", "quality_score", "numeric_gte"),
    "stance_encoded": _FeatureMeta("stance_encoded", "stance", "categorical_eq"),
    "horizon_encoded": _FeatureMeta("horizon_encoded", "time_horizon", "categorical_eq"),
    "nlp_polarity": _FeatureMeta("nlp_polarity", "nlp_polarity", "numeric_gte"),
    "nlp_conviction": _FeatureMeta("nlp_conviction", "nlp_conviction", "numeric_gte"),
    "nlp_sarcasm_prob": _FeatureMeta("nlp_sarcasm_prob", "nlp_sarcasm_prob", "numeric_lte"),
    "nlp_actionability": _FeatureMeta("nlp_actionability", "nlp_actionability", "numeric_gte"),
    "nlp_consensus_score": _FeatureMeta("nlp_consensus_score", "nlp_consensus_score", "numeric_gte"),
    "upvote_ratio": _FeatureMeta("upvote_ratio", "upvote_ratio", "numeric_gte"),
    "iv": _FeatureMeta("iv", "iv", "numeric_gte"),
    "put_call_ratio": _FeatureMeta("put_call_ratio", "put_call_ratio", "numeric_lte"),
    "post_score_log": _FeatureMeta("post_score_log", "post_score", "numeric_gte"),
    "author_karma_log": _FeatureMeta("author_karma_log", "author_karma", "numeric_gte"),
    "entity_count": _FeatureMeta("entity_count", "entity_count", "numeric_lte"),
    "price_change_pct": _FeatureMeta("price_change_pct", "price_change_pct", "numeric_gte"),
    "nlp_intensity": _FeatureMeta("nlp_intensity", "nlp_intensity", "numeric_gte"),
    "nlp_urgency": _FeatureMeta("nlp_urgency", "nlp_urgency", "numeric_gte"),
    "confidence_x_conviction": _FeatureMeta(
        "confidence_x_conviction", "confidence", "numeric_gte",
    ),
}

# Event types and subreddits get categorical-in rules when important
for _et in _EVENT_TYPES:
    _key = f"evt_{_et}"
    _FEATURE_TO_RULE[_key] = _FeatureMeta(_key, "event_type", "categorical_in")

for _sub in _TOP_SUBREDDITS:
    _key = f"sub_{_sub}"
    _FEATURE_TO_RULE[_key] = _FeatureMeta(_key, "subreddit", "categorical_in")

_FEATURE_TO_RULE["sub_other"] = _FeatureMeta("sub_other", "subreddit", "skip")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce to float, returning *default* on failure or non-finite."""
    if val is None:
        return default
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_log(val: Any, default: float = 0.0) -> float:
    """Return log10(val) clamping non-positive to *default*."""
    v = _safe_float(val, 0.0)
    if v <= 0:
        return default
    return math.log10(v)


def _parse_json_field(raw: Any) -> Dict[str, Any]:
    """Parse a JSON string or pass through a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _get_market_data(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Extract primary ticker market data dict from a signal."""
    md_raw = _parse_json_field(signal.get("market_data"))
    if not md_raw:
        return {}
    ticker = signal.get("ticker", "")
    if ticker and ticker in md_raw and isinstance(md_raw[ticker], dict):
        return md_raw[ticker]
    # Fallback: first dict value
    for v in md_raw.values():
        if isinstance(v, dict):
            return v
    return {}


def _get_nlp_data(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Extract NLP dict from event_data.meta.nlp."""
    ed = _parse_json_field(signal.get("event_data"))
    meta = ed.get("meta") or {}
    return meta.get("nlp") or {}


def _get_meta(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Extract meta dict from event_data."""
    ed = _parse_json_field(signal.get("event_data"))
    return ed.get("meta") or {}


def _get_features_dict(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Extract features sub-dict from event_data.meta.features."""
    meta = _get_meta(signal)
    return meta.get("features") or {}


def _market_cap_bucket(cap: float) -> float:
    """Encode market cap as ordinal bucket: 0=unknown, 1=small, 2=mid, 3=large, 4=mega."""
    if cap <= 0:
        return 0.0
    for i, (threshold, _label) in enumerate(_MARKET_CAP_THRESHOLDS, start=1):
        if cap < threshold:
            return float(i)
    return 4.0  # mega


def _body_length_bucket(length: float) -> float:
    """Encode body length as ordinal: 0=none, 1=short(<100), 2=medium(<500), 3=long."""
    if length <= 0:
        return 0.0
    if length < 100:
        return 1.0
    if length < 500:
        return 2.0
    return 3.0


# ---------------------------------------------------------------------------
# MLStrategyOptimizer
# ---------------------------------------------------------------------------

class MLStrategyOptimizer:
    """ML-powered strategy optimizer.

    Uses a GradientBoostingClassifier to learn which signal features predict
    winning trades, then translates the most important features into
    ``StrategyRule`` objects that can be used by the Strategy Builder.

    Parameters
    ----------
    min_signals:
        Minimum number of labelled (win/loss) signals required before
        training.  If fewer signals are available, ``train()`` returns
        an empty result dict.
    """

    def __init__(self, min_signals: int = 200) -> None:
        self.min_signals = max(10, min_signals)
        self._model: Any = None  # GradientBoostingClassifier once trained
        self._is_trained: bool = False
        self._feature_names: List[str] = list(FEATURE_NAMES)
        self._training_stats: Dict[str, Any] = {}
        # Cached per-feature medians for winning signals (used in rule gen)
        self._win_medians: Dict[str, float] = {}
        self._win_features: Optional[Any] = None  # numpy array of winning features
        self._loss_features: Optional[Any] = None  # numpy array of losing features

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_trained(self) -> bool:
        """Whether the model has been trained successfully."""
        return self._is_trained

    @property
    def feature_names(self) -> List[str]:
        """Ordered list of feature names (length == NUM_FEATURES)."""
        return list(self._feature_names)

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    def _extract_features(self, signal: Dict[str, Any]) -> List[float]:
        """Extract a fixed-length feature vector from a signal dict.

        The signal dict is expected to come from the database (e.g.
        ``get_backtest_signals()``), with JSON-encoded ``event_data``
        and ``market_data`` blobs.

        Returns
        -------
        list[float]
            Exactly ``NUM_FEATURES`` floats.  Missing values are padded
            with 0.0.
        """
        nlp = _get_nlp_data(signal)
        meta = _get_meta(signal)
        mkt = _get_market_data(signal)
        feat = _get_features_dict(signal)

        confidence = _safe_float(signal.get("confidence"), 0.0)
        trend_score = _safe_float(signal.get("trend_score") or meta.get("trend_score"), 0.0)
        quality_score = _safe_float(signal.get("quality_score"), 0.0)

        stance = signal.get("stance", "unknown")
        stance_enc = _STANCE_ENCODE.get(stance, 0.0)

        event_type = signal.get("event_type", "other")
        evt_onehot = [1.0 if event_type == et else 0.0 for et in _EVENT_TYPES]

        subreddit = (signal.get("subreddit") or "").lower()
        sub_onehot = [1.0 if subreddit == s else 0.0 for s in _TOP_SUBREDDITS]
        sub_other = 1.0 if subreddit and subreddit not in _TOP_SUBREDDITS else 0.0

        horizon = signal.get("time_horizon") or "unknown"
        horizon_enc = _HORIZON_ENCODE.get(horizon, 0.0)

        # Market data
        pct_1d = _safe_float(mkt.get("pct_1d"), 0.0)
        market_cap = _safe_float(mkt.get("market_cap"), 0.0)
        cap_bucket = _market_cap_bucket(market_cap)
        iv_val = _safe_float(mkt.get("atm_iv"), 0.0)
        pc_ratio = _safe_float(mkt.get("pc_ratio"), 0.0)
        cap_log = _safe_log(market_cap, 0.0)

        # NLP
        polarity = _safe_float(nlp.get("polarity"), 0.0)
        conviction = _safe_float(nlp.get("conviction"), 0.5)
        sarcasm = _safe_float(nlp.get("sarcasm_probability"), 0.0)
        actionability = _safe_float(nlp.get("actionability"), 0.5)
        consensus = _safe_float(nlp.get("thread_consensus"), 0.0)

        # Post metadata
        post_score = _safe_float(meta.get("score") or signal.get("score_val"), 0.0)
        num_comments = _safe_float(meta.get("num_comments") or signal.get("num_comments_val"), 0.0)
        upvote = _safe_float(meta.get("upvote_ratio"), 0.5)
        body_excerpt = meta.get("body_excerpt") or ""
        body_len = float(len(body_excerpt))
        body_bucket = _body_length_bucket(body_len)

        # Temporal
        created_at = _safe_float(signal.get("created_at"), 0.0)
        hour = 0.0
        dow = 0.0
        if created_at > 0:
            try:
                import datetime
                dt = datetime.datetime.fromtimestamp(created_at, tz=datetime.timezone.utc)
                hour = float(dt.hour)
                dow = float(dt.weekday())
            except (OSError, ValueError, OverflowError):
                pass

        # Extended NLP
        intensity = _safe_float(nlp.get("intensity"), 0.0)
        urgency = _safe_float(nlp.get("urgency"), 0.0)
        thread_agree = _safe_float(nlp.get("thread_agreement_with_op"), 0.0)
        contrarian = 1.0 if nlp.get("contrarian_detected") else 0.0

        # Extended post
        ed = _parse_json_field(signal.get("event_data"))
        entities = ed.get("entities") or []
        entity_count = float(len(entities))
        is_crosspost = 1.0 if meta.get("is_crosspost") else 0.0
        comment_score_ratio = num_comments / max(post_score, 1.0)

        # Trend detail
        score_rate = _safe_float(feat.get("score_rate"), 0.0)
        comment_rate = _safe_float(feat.get("comment_rate"), 0.0)

        # Author
        author_karma = _safe_float(meta.get("author_karma"), 0.0)
        author_karma_l = _safe_log(max(author_karma, 1.0), 0.0)
        author_age = _safe_float(meta.get("author_age_days"), 0.0)
        author_age_bucket = 0.0
        if author_age > 365:
            author_age_bucket = 3.0
        elif author_age > 90:
            author_age_bucket = 2.0
        elif author_age > 30:
            author_age_bucket = 1.0

        # Source flags
        flair = meta.get("flair") or ""
        is_rss = 1.0 if flair == "rss" else 0.0
        is_stocktwits = 1.0 if flair == "stocktwits" else 0.0

        # Market structure
        volume = _safe_float(mkt.get("volume"), 0.0)
        avg_volume = _safe_float(mkt.get("avg_volume"), 1.0)
        volume_ratio = volume / max(avg_volume, 1.0)
        cap_bucket_small = 1.0 if cap_bucket == 1.0 else 0.0
        cap_bucket_mega = 1.0 if cap_bucket == 4.0 else 0.0

        # Interaction features
        conf_x_conv = confidence * conviction
        trend_x_cons = trend_score * consensus

        # Assemble in FEATURE_NAMES order
        return [
            # Numeric core (0-2)
            confidence,
            trend_score,
            quality_score,
            # Stance (3)
            stance_enc,
            # Event-type one-hot (4-9)
            *evt_onehot,
            # Subreddit one-hot (10-15)
            *sub_onehot,
            sub_other,
            # Horizon (16)
            horizon_enc,
            # Market data (17-21)
            pct_1d,
            cap_bucket,
            iv_val,
            pc_ratio,
            cap_log,
            # NLP features (22-26)
            polarity,
            conviction,
            sarcasm,
            actionability,
            consensus,
            # Post metadata (27-30)
            _safe_log(max(post_score, 1.0), 0.0),
            _safe_log(max(num_comments, 1.0), 0.0),
            upvote,
            body_bucket,
            # Temporal (31-32)
            hour,
            dow,
            # Extended NLP (33-36)
            intensity,
            urgency,
            thread_agree,
            contrarian,
            # Extended post (37-39)
            entity_count,
            is_crosspost,
            comment_score_ratio,
            # Trend detail (40-41)
            score_rate,
            comment_rate,
            # Author (42-44)
            author_karma_l,
            author_age,
            author_age_bucket,
            # Source flags (45-46)
            is_rss,
            is_stocktwits,
            # Market structure (47-49)
            volume_ratio,
            cap_bucket_small,
            cap_bucket_mega,
            # Interactions (50-51)
            conf_x_conv,
            trend_x_cons,
        ]

    # ------------------------------------------------------------------
    # Labelling
    # ------------------------------------------------------------------

    def _label_signals(
        self,
        signals: List[Dict[str, Any]],
    ) -> Tuple[List[List[float]], List[int]]:
        """Extract features and binary labels from resolved signals.

        Only signals with ``price_at_signal`` and ``price_1d`` (or fallback
        price columns) and a directional stance (bullish/bearish) are
        included.

        Win/loss mirrors ``_WIN_CASE_SQL`` in ``database.py``:
          - bullish + price_1d > price_at_signal  -> win (1)
          - bearish + price_1d < price_at_signal  -> win (1)
          - otherwise                              -> loss (0)

        Returns
        -------
        tuple[list[list[float]], list[int]]
            (feature_matrix, labels) where feature_matrix is a list of
            NUM_FEATURES-length float lists and labels are 0/1 ints.
        """
        features: List[List[float]] = []
        labels: List[int] = []

        for sig in signals:
            stance = sig.get("stance", "unknown")
            if stance not in ("bullish", "bearish"):
                continue

            entry = _safe_float(sig.get("price_at_signal"))
            if entry <= 0:
                continue

            # Resolve exit price: prefer price_1d, fall back to price_4h, price_1h
            exit_price = _safe_float(sig.get("price_1d"))
            if exit_price <= 0:
                exit_price = _safe_float(sig.get("price_4h"))
            if exit_price <= 0:
                exit_price = _safe_float(sig.get("price_1h"))
            if exit_price <= 0:
                continue

            # Determine win/loss
            if stance == "bullish":
                is_win = exit_price > entry
            else:  # bearish
                is_win = exit_price < entry

            try:
                feat_vec = self._extract_features(sig)
            except Exception:
                logger.debug("Feature extraction failed for signal %s", sig.get("signal_id", "?"))
                continue

            if len(feat_vec) != NUM_FEATURES:
                logger.debug(
                    "Feature vector length mismatch: got %d, expected %d",
                    len(feat_vec),
                    NUM_FEATURES,
                )
                continue

            features.append(feat_vec)
            labels.append(1 if is_win else 0)

        return features, labels

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Train the GradientBoosting model on resolved signals.

        Parameters
        ----------
        signals:
            List of signal dicts with price performance data (from
            ``database.get_backtest_signals()`` or similar).

        Returns
        -------
        dict
            Training summary with keys: ``accuracy``, ``accuracy_std``,
            ``feature_importances`` (sorted list of (name, importance)),
            ``n_samples``, ``n_features``, ``n_wins``, ``n_losses``,
            ``trained``.  If training cannot proceed (not enough data,
            sklearn missing), ``trained`` is ``False``.
        """
        if not _HAS_SKLEARN:
            logger.warning("sklearn not available; cannot train ML strategy optimizer")
            return {"trained": False, "reason": "sklearn_not_installed"}

        features_list, labels = self._label_signals(signals)

        if len(features_list) < self.min_signals:
            logger.info(
                "Not enough labelled signals for training: have %d, need %d",
                len(features_list),
                self.min_signals,
            )
            return {
                "trained": False,
                "reason": "insufficient_data",
                "n_samples": len(features_list),
                "min_required": self.min_signals,
            }

        n_wins = sum(labels)
        n_losses = len(labels) - n_wins

        # Need at least 10 samples in each class for meaningful training
        if n_wins < 10 or n_losses < 10:
            logger.info(
                "Class imbalance too severe: %d wins, %d losses (need >=10 each)",
                n_wins,
                n_losses,
            )
            return {
                "trained": False,
                "reason": "class_imbalance",
                "n_wins": n_wins,
                "n_losses": n_losses,
            }

        X = np.array(features_list, dtype=np.float64)
        y = np.array(labels, dtype=np.int32)

        # Replace any remaining NaN/inf with 0
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        # Build classifier
        model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            min_samples_split=10,
            min_samples_leaf=5,
            subsample=0.8,
            random_state=42,
        )

        # 5-fold cross-validation for accuracy estimate
        n_folds = min(5, min(n_wins, n_losses))
        if n_folds < 2:
            n_folds = 2

        try:
            cv_scores = cross_val_score(model, X, y, cv=n_folds, scoring="accuracy")
            cv_mean = float(np.mean(cv_scores))
            cv_std = float(np.std(cv_scores))
        except Exception as exc:
            logger.warning("Cross-validation failed: %s", exc)
            cv_mean = 0.0
            cv_std = 0.0

        # Train on full dataset
        try:
            model.fit(X, y)
        except Exception as exc:
            logger.error("Model training failed: %s", exc)
            return {"trained": False, "reason": f"training_error: {exc}"}

        self._model = model
        self._is_trained = True

        # Cache feature importances
        importances = model.feature_importances_
        sorted_imp = sorted(
            zip(self._feature_names, importances.tolist()),
            key=lambda t: t[1],
            reverse=True,
        )

        # Cache win/loss feature arrays for rule generation
        win_mask = y == 1
        self._win_features = X[win_mask]
        self._loss_features = X[~win_mask]

        # Compute per-feature medians for winning signals
        self._win_medians = {}
        for i, name in enumerate(self._feature_names):
            win_vals = self._win_features[:, i]
            if len(win_vals) > 0:
                self._win_medians[name] = float(np.median(win_vals))
            else:
                self._win_medians[name] = 0.0

        self._training_stats = {
            "trained": True,
            "accuracy": round(cv_mean, 4),
            "accuracy_std": round(cv_std, 4),
            "feature_importances": [(n, round(v, 6)) for n, v in sorted_imp],
            "n_samples": len(labels),
            "n_features": NUM_FEATURES,
            "n_wins": n_wins,
            "n_losses": n_losses,
            "trained_at": time.time(),
        }

        logger.info(
            "ML Strategy Optimizer trained: accuracy=%.3f +/- %.3f on %d signals (%d wins, %d losses)",
            cv_mean,
            cv_std,
            len(labels),
            n_wins,
            n_losses,
        )

        return dict(self._training_stats)

    # ------------------------------------------------------------------
    # Feature importance
    # ------------------------------------------------------------------

    def get_feature_importance(self) -> List[Tuple[str, float]]:
        """Return sorted (name, importance) pairs from the trained model.

        Returns
        -------
        list[tuple[str, float]]
            Feature names and their importance scores, sorted descending.
            Empty list if the model has not been trained.
        """
        if not self._is_trained or self._model is None:
            return []

        if not _HAS_SKLEARN:
            return []

        importances = self._model.feature_importances_
        pairs = list(zip(self._feature_names, importances.tolist()))
        pairs.sort(key=lambda t: t[1], reverse=True)
        return [(name, round(imp, 6)) for name, imp in pairs]

    # ------------------------------------------------------------------
    # Rule generation
    # ------------------------------------------------------------------

    def generate_rules(self, top_n: int = 5) -> List[StrategyRule]:
        """Generate StrategyRule objects from the most important features.

        For each of the ``top_n`` most important features that can be
        expressed as a rule:

        - **Numeric features** (confidence, trend_score, polarity, etc.):
          Use the median value among *winning* signals as a threshold.
          High-is-good features get ``gte`` rules; high-is-bad features
          (sarcasm, entity_count) get ``lte`` rules.

        - **Categorical features** (event_type, stance): Determine which
          category value is most predictive of wins and generate an ``eq``
          or ``in`` rule.

        Parameters
        ----------
        top_n:
            Maximum number of rules to generate.

        Returns
        -------
        list[StrategyRule]
            Up to ``top_n`` rules.  May return fewer if some features
            cannot be meaningfully converted to rules.
        """
        if not self._is_trained or self._model is None:
            logger.info("Model not trained — cannot generate rules")
            return []

        if not _HAS_SKLEARN:
            return []

        importances = self.get_feature_importance()
        rules: List[StrategyRule] = []
        seen_fields: set[str] = set()

        for feat_name, imp in importances:
            if len(rules) >= top_n:
                break

            if imp < 0.005:
                # Feature has negligible importance — skip
                continue

            meta = _FEATURE_TO_RULE.get(feat_name)
            if meta is None or meta.rule_type == "skip":
                continue

            # Avoid duplicate rules on the same target field
            if meta.rule_field in seen_fields:
                continue

            rule = self._feature_to_rule(feat_name, meta)
            if rule is not None:
                rules.append(rule)
                seen_fields.add(meta.rule_field)

        return rules

    def _feature_to_rule(
        self,
        feat_name: str,
        meta: _FeatureMeta,
    ) -> Optional[StrategyRule]:
        """Convert a single important feature into a StrategyRule."""
        try:
            feat_idx = self._feature_names.index(feat_name)
        except ValueError:
            return None

        if meta.rule_type == "numeric_gte":
            threshold = self._win_medians.get(feat_name, 0.0)
            # Round for readability
            threshold = round(threshold, 3)
            return StrategyRule(
                field=meta.rule_field,
                operator="gte",
                value=threshold,
            )

        elif meta.rule_type == "numeric_lte":
            threshold = self._win_medians.get(feat_name, 0.0)
            threshold = round(threshold, 3)
            return StrategyRule(
                field=meta.rule_field,
                operator="lte",
                value=threshold,
            )

        elif meta.rule_type == "categorical_eq":
            # Find which category value wins most among winning signals
            best_value = self._find_best_categorical(feat_name, meta.rule_field)
            if best_value is not None:
                return StrategyRule(
                    field=meta.rule_field,
                    operator="eq",
                    value=best_value,
                )
            return None

        elif meta.rule_type == "categorical_in":
            # For one-hot features (event_type, subreddit), check if this
            # category is associated with wins
            best_value = self._resolve_onehot_value(feat_name)
            if best_value is not None:
                return StrategyRule(
                    field=meta.rule_field,
                    operator="eq",
                    value=best_value,
                )
            return None

        return None

    def _find_best_categorical(
        self,
        feat_name: str,
        rule_field: str,
    ) -> Optional[str]:
        """Find the most predictive categorical value for a feature."""
        if self._win_features is None or self._loss_features is None:
            return None

        try:
            feat_idx = self._feature_names.index(feat_name)
        except ValueError:
            return None

        if rule_field == "stance":
            # stance_encoded: 1.0=bullish, -1.0=bearish
            win_vals = self._win_features[:, feat_idx]
            median_val = float(np.median(win_vals))
            if median_val > 0:
                return "bullish"
            elif median_val < 0:
                return "bearish"
            return None

        elif rule_field == "time_horizon":
            # horizon_encoded: 1=intraday, 2=1w, 3=earnings, 4=longer
            win_vals = self._win_features[:, feat_idx]
            mode_val = float(np.median(win_vals))
            reverse_map = {1.0: "intraday", 2.0: "1w", 3.0: "earnings", 4.0: "longer"}
            # Find closest match
            closest = min(reverse_map.keys(), key=lambda k: abs(k - mode_val))
            return reverse_map.get(closest)

        return None

    def _resolve_onehot_value(self, feat_name: str) -> Optional[str]:
        """Map a one-hot feature name back to its category value.

        E.g. ``evt_earnings_rumor`` -> ``"earnings_rumor"``,
        ``sub_wallstreetbets`` -> ``"wallstreetbets"``.

        Only returns the value if the feature is positively associated
        with wins (median among winners > 0.5).
        """
        if self._win_features is None:
            return None

        try:
            feat_idx = self._feature_names.index(feat_name)
        except ValueError:
            return None

        win_mean = float(np.mean(self._win_features[:, feat_idx]))
        if win_mean < 0.1:
            # This category barely appears in wins — not a useful rule
            return None

        # Strip prefix to get category value
        if feat_name.startswith("evt_"):
            return feat_name[4:]
        elif feat_name.startswith("sub_"):
            return feat_name[4:]
        return None

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict_win_probability(self, signal: Dict[str, Any]) -> float:
        """Predict the probability of a signal being a win.

        Parameters
        ----------
        signal:
            A signal dict (same format as training data).

        Returns
        -------
        float
            Probability of win (0.0-1.0).  Returns 0.5 if the model
            is not trained.
        """
        if not self._is_trained or self._model is None or not _HAS_SKLEARN:
            return 0.5

        try:
            features = self._extract_features(signal)
            X = np.array([features], dtype=np.float64)
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            proba = self._model.predict_proba(X)
            # Class 1 (win) probability
            win_idx = list(self._model.classes_).index(1) if 1 in self._model.classes_ else -1
            if win_idx >= 0:
                return float(proba[0][win_idx])
            return 0.5
        except Exception as exc:
            logger.debug("Prediction failed: %s", exc)
            return 0.5

    def predict_batch(
        self,
        signals: List[Dict[str, Any]],
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Predict win probabilities for a batch of signals.

        Returns
        -------
        list[tuple[dict, float]]
            Each tuple is (signal_dict, win_probability).
        """
        if not self._is_trained or self._model is None or not _HAS_SKLEARN:
            return [(s, 0.5) for s in signals]

        results: List[Tuple[Dict[str, Any], float]] = []
        feature_matrix: List[List[float]] = []
        valid_indices: List[int] = []

        for i, sig in enumerate(signals):
            try:
                features = self._extract_features(sig)
                feature_matrix.append(features)
                valid_indices.append(i)
            except Exception:
                pass

        if not feature_matrix:
            return [(s, 0.5) for s in signals]

        try:
            X = np.array(feature_matrix, dtype=np.float64)
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            probas = self._model.predict_proba(X)
            win_idx = list(self._model.classes_).index(1) if 1 in self._model.classes_ else -1
        except Exception as exc:
            logger.debug("Batch prediction failed: %s", exc)
            return [(s, 0.5) for s in signals]

        # Build result list preserving original order
        proba_map: Dict[int, float] = {}
        for j, orig_idx in enumerate(valid_indices):
            if win_idx >= 0:
                proba_map[orig_idx] = float(probas[j][win_idx])
            else:
                proba_map[orig_idx] = 0.5

        for i, sig in enumerate(signals):
            results.append((sig, proba_map.get(i, 0.5)))

        return results

    # ------------------------------------------------------------------
    # Full optimization pipeline
    # ------------------------------------------------------------------

    def optimize(
        self,
        signals: List[Dict[str, Any]],
        backtest_signals: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Full ML optimization pipeline.

        1. Train the model on ``signals``
        2. Extract feature importances
        3. Generate strategy rules from top features
        4. Optionally backtest the generated rules against
           ``backtest_signals`` (or ``signals`` if not provided)

        Parameters
        ----------
        signals:
            Resolved signals with price performance data for training.
        backtest_signals:
            Optional separate set of signals for backtesting the
            generated rules.  If ``None``, skips backtesting.

        Returns
        -------
        dict
            Combined result with keys: ``model_accuracy``,
            ``model_accuracy_std``, ``feature_importances``,
            ``generated_rules`` (list of rule dicts),
            ``n_rules``, ``n_training_signals``,
            ``backtest_result`` (BacktestResult.to_dict() or None),
            ``elapsed_s``.
        """
        start = time.time()

        result: Dict[str, Any] = {
            "model_accuracy": 0.0,
            "model_accuracy_std": 0.0,
            "feature_importances": [],
            "generated_rules": [],
            "n_rules": 0,
            "n_training_signals": len(signals),
            "backtest_result": None,
            "elapsed_s": 0.0,
        }

        # Step 1: Train
        train_result = self.train(signals)
        if not train_result.get("trained", False):
            result["train_error"] = train_result.get("reason", "unknown")
            result["elapsed_s"] = round(time.time() - start, 3)
            return result

        result["model_accuracy"] = train_result.get("accuracy", 0.0)
        result["model_accuracy_std"] = train_result.get("accuracy_std", 0.0)

        # Step 2: Feature importances
        importances = self.get_feature_importance()
        result["feature_importances"] = importances[:20]  # top 20 for readability

        # Step 3: Generate rules
        rules = self.generate_rules(top_n=5)
        result["generated_rules"] = [r.to_dict() for r in rules]
        result["n_rules"] = len(rules)

        # Step 4: Backtest (optional)
        if backtest_signals is not None and rules:
            bt_result = self._backtest_rules(rules, backtest_signals)
            if bt_result is not None:
                result["backtest_result"] = bt_result

        result["elapsed_s"] = round(time.time() - start, 3)

        logger.info(
            "ML optimization complete: accuracy=%.3f, %d rules generated in %.1fs",
            result["model_accuracy"],
            result["n_rules"],
            result["elapsed_s"],
        )

        return result

    def _backtest_rules(
        self,
        rules: List[StrategyRule],
        signals: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Backtest the generated rules against a signal set.

        Filters signals through the rules, then runs the BacktestEngine
        on matching signals.

        Returns
        -------
        dict or None
            BacktestResult as dict, or None if backtest fails.
        """
        try:
            from rot.backtest.config import BacktestConfig
            from rot.backtest.engine import BacktestEngine
        except ImportError:
            logger.debug("Backtest engine not available for ML optimizer")
            return None

        # Filter signals that match all rules
        matching = self._apply_rules(rules, signals)
        if len(matching) < 5:
            logger.info(
                "Only %d signals match generated rules — skipping backtest",
                len(matching),
            )
            return {
                "skipped": True,
                "reason": "insufficient_matching_signals",
                "matching_count": len(matching),
                "total_count": len(signals),
            }

        config = BacktestConfig(
            starting_capital=10_000.0,
            position_size_mode="fixed_pct",
            position_size_pct=5.0,
            days=365,
        )

        try:
            engine = BacktestEngine()
            result = engine.run(matching, config)
            return result.to_dict()
        except Exception as exc:
            logger.warning("Backtest of ML-generated rules failed: %s", exc)
            return {"skipped": True, "reason": f"backtest_error: {exc}"}

    def _apply_rules(
        self,
        rules: List[StrategyRule],
        signals: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Filter signals through a list of rules (AND logic).

        Each rule is checked against the signal dict's top-level keys
        and nested NLP/meta fields.
        """
        matching: List[Dict[str, Any]] = []
        for sig in signals:
            if self._signal_matches_rules(sig, rules):
                matching.append(sig)
        return matching

    def _signal_matches_rules(
        self,
        signal: Dict[str, Any],
        rules: List[StrategyRule],
    ) -> bool:
        """Check if a signal dict passes all rules (AND logic)."""
        for rule in rules:
            val = self._resolve_signal_value(signal, rule.field)
            if not self._evaluate_rule(val, rule.operator, rule.value):
                return False
        return True

    def _resolve_signal_value(
        self,
        signal: Dict[str, Any],
        field: str,
    ) -> Any:
        """Resolve a rule field to a value from the signal dict.

        Checks top-level keys first, then NLP data, then meta.
        """
        # Direct top-level fields
        if field in signal:
            return signal[field]

        # NLP fields (prefixed with nlp_)
        if field.startswith("nlp_"):
            nlp = _get_nlp_data(signal)
            nlp_key = field[4:]  # strip nlp_ prefix
            if nlp_key in nlp:
                return nlp[nlp_key]
            # Try alternate naming
            alt_keys = {
                "polarity": "polarity",
                "conviction": "conviction",
                "sarcasm_prob": "sarcasm_probability",
                "actionability": "actionability",
                "consensus_score": "thread_consensus",
                "intensity": "intensity",
                "urgency": "urgency",
            }
            alt = alt_keys.get(nlp_key)
            if alt and alt in nlp:
                return nlp[alt]

        # Meta fields
        meta = _get_meta(signal)
        if field in meta:
            return meta[field]

        # Market data fields
        mkt = _get_market_data(signal)
        if field in mkt:
            return mkt[field]

        return None

    @staticmethod
    def _evaluate_rule(val: Any, operator: str, target: Any) -> bool:
        """Evaluate a single rule comparison."""
        if val is None:
            # Missing data: only pass if operator is "neq"
            return operator == "neq"

        try:
            if operator == "gt":
                return float(val) > float(target)
            elif operator == "lt":
                return float(val) < float(target)
            elif operator == "gte":
                return float(val) >= float(target)
            elif operator == "lte":
                return float(val) <= float(target)
            elif operator == "eq":
                return str(val).lower() == str(target).lower()
            elif operator == "neq":
                return str(val).lower() != str(target).lower()
            elif operator == "in":
                if isinstance(target, (list, tuple)):
                    return str(val).lower() in [str(t).lower() for t in target]
                return str(val).lower() == str(target).lower()
        except (TypeError, ValueError):
            return False

        return False

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def get_training_stats(self) -> Dict[str, Any]:
        """Return the most recent training stats, or empty dict."""
        return dict(self._training_stats)

    def get_model_summary(self) -> Dict[str, Any]:
        """Return a human-readable summary of the trained model."""
        if not self._is_trained:
            return {"status": "not_trained"}

        stats = self._training_stats
        top_features = self.get_feature_importance()[:10]

        return {
            "status": "trained",
            "accuracy": stats.get("accuracy", 0.0),
            "accuracy_std": stats.get("accuracy_std", 0.0),
            "n_samples": stats.get("n_samples", 0),
            "n_wins": stats.get("n_wins", 0),
            "n_losses": stats.get("n_losses", 0),
            "n_features": NUM_FEATURES,
            "top_features": top_features,
            "trained_at": stats.get("trained_at", 0.0),
        }
