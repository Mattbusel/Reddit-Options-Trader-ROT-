"""Feature extraction for ML credibility scoring.

Produces a fixed-length 32-float feature vector from either a live Event object
(for inference) or a database row dict (for training).  Both paths produce
identical vectors for the same underlying signal.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List

from rot.core.types import Event

# ── Categorical encodings (ordinal) ────────────────────────────────────────

EVENT_TYPE_MAP: Dict[str, int] = {
    "earnings_rumor": 0,
    "product_news": 1,
    "regulatory": 2,
    "squeeze_chatter": 3,
    "macro": 4,
    "other": 5,
}

STANCE_MAP: Dict[str, int] = {
    "bullish": 0,
    "bearish": 1,
    "mixed": 2,
    "unknown": 3,
}

HORIZON_MAP: Dict[str, int] = {
    "intraday": 0,
    "1w": 1,
    "earnings": 2,
    "longer": 3,
    "unknown": 4,
}

# Subreddit quality weights (mirrors scorer.py _SUBREDDIT_WEIGHTS)
_SUBREDDIT_QUALITY: Dict[str, float] = {
    "wallstreetbets": -0.10,
    "wallstreetbetsogs": -0.05,
    "shortsqueeze": -0.10,
    "pennystocks": -0.10,
    "stocks": 0.0,
    "options": 0.05,
    "investing": 0.05,
    "stockmarket": 0.0,
    "thetagang": 0.05,
    "valueinvesting": 0.05,
}

# ── Feature names (fixed order) ───────────────────────────────────────────

FEATURE_NAMES: List[str] = [
    # Post metadata (0-6)
    "post_score",
    "num_comments",
    "upvote_ratio",
    "is_crosspost",
    "body_length",
    "entity_count",
    "comment_to_score_ratio",
    # Trend (7-9)
    "trend_score",
    "score_rate",
    "comment_rate",
    # NLP (10-19)
    "nlp_polarity",
    "nlp_intensity",
    "nlp_conviction",
    "nlp_sarcasm_prob",
    "nlp_actionability",
    "nlp_urgency",
    "nlp_thread_consensus",
    "nlp_thread_agreement",
    "nlp_contrarian",
    "nlp_has_data",
    # Market (20-24)
    "market_cap_log",
    "pct_1d",
    "atm_iv",
    "pc_ratio",
    "volume_ratio",
    # Author (25-26)
    "author_karma_log",
    "author_age_days",
    # Categorical (27-31)
    "event_type_idx",
    "stance_idx",
    "horizon_idx",
    "is_rss",
    "subreddit_quality",
]

NUM_FEATURES = len(FEATURE_NAMES)  # 32


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce a value to float, returning *default* on failure."""
    if val is None:
        return default
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_log10(val: Any, default: float = 0.0) -> float:
    """Return log10(val) or *default* when val is non-positive or invalid."""
    v = _safe_float(val, 0.0)
    if v <= 0:
        return default
    return math.log10(v)


def _get_primary_market(meta: Dict[str, Any], entities: List[str]) -> Dict[str, Any]:
    """Return market data dict for the first entity, or empty dict."""
    market = meta.get("market") or {}
    if not market:
        return {}
    # Try first entity
    if entities:
        data = market.get(entities[0])
        if data:
            return data
    # Fall back to first available key
    for val in market.values():
        if isinstance(val, dict):
            return val
    return {}


# ── Public API ─────────────────────────────────────────────────────────────

def extract_features_from_event(event: Event) -> List[float]:
    """Extract 32 features from a live Event object (inference path).

    Returns a list of exactly NUM_FEATURES floats in the order defined by
    FEATURE_NAMES.
    """
    meta = event.meta or {}
    nlp = meta.get("nlp") or {}
    features_dict = meta.get("features") or {}
    mkt = _get_primary_market(meta, event.entities)

    subreddit = ""
    if event.evidence:
        subreddit = (event.evidence[0].subreddit or "").lower()

    score = _safe_float(meta.get("score"), 0.0)
    num_comments = _safe_float(meta.get("num_comments"), 0.0)

    return [
        # Post metadata (0-6)
        score,
        num_comments,
        _safe_float(meta.get("upvote_ratio"), 0.5),
        1.0 if meta.get("is_crosspost") else 0.0,
        float(len(meta.get("body_excerpt", "") or "")),
        float(len(event.entities)),
        num_comments / max(score, 1.0),
        # Trend (7-9)
        _safe_float(meta.get("trend_score"), 0.0),
        _safe_float(features_dict.get("score_rate"), 0.0),
        _safe_float(features_dict.get("comment_rate"), 0.0),
        # NLP (10-19)
        _safe_float(nlp.get("polarity"), 0.0),
        _safe_float(nlp.get("intensity"), 0.0),
        _safe_float(nlp.get("conviction"), 0.5),
        _safe_float(nlp.get("sarcasm_probability"), 0.0),
        _safe_float(nlp.get("actionability"), 0.5),
        _safe_float(nlp.get("urgency"), 0.0),
        _safe_float(nlp.get("thread_consensus"), 0.0),
        _safe_float(nlp.get("thread_agreement_with_op"), 0.0),
        1.0 if nlp.get("contrarian_detected") else 0.0,
        1.0 if nlp else 0.0,
        # Market (20-24)
        _safe_log10(mkt.get("market_cap"), 0.0),
        _safe_float(mkt.get("pct_1d"), 0.0),
        _safe_float(mkt.get("atm_iv"), 0.0),
        _safe_float(mkt.get("pc_ratio"), 0.0),
        (
            _safe_float(mkt.get("volume"), 0.0)
            / max(_safe_float(mkt.get("avg_volume"), 1.0), 1.0)
        ),
        # Author (25-26)
        _safe_log10(max(_safe_float(meta.get("author_karma"), 0.0), 1.0)),
        _safe_float(meta.get("author_age_days"), 0.0),
        # Categorical (27-31)
        float(EVENT_TYPE_MAP.get(event.event_type, 5)),
        float(STANCE_MAP.get(event.stance, 3)),
        float(HORIZON_MAP.get(event.time_horizon, 4)),
        1.0 if meta.get("flair") == "rss" else 0.0,
        float(_SUBREDDIT_QUALITY.get(subreddit, 0.0)),
    ]


def extract_features_from_row(row: Dict[str, Any]) -> List[float]:
    """Extract 32 features from a database row dict (training path).

    The row is expected to have columns from the signals table plus parsed
    JSON blobs for event_data and market_data.
    """
    # Parse JSON blobs if they're still strings
    event_data = row.get("event_data") or "{}"
    if isinstance(event_data, str):
        try:
            event_data = json.loads(event_data)
        except (json.JSONDecodeError, TypeError):
            event_data = {}

    market_data_raw = row.get("market_data") or "{}"
    if isinstance(market_data_raw, str):
        try:
            market_data_raw = json.loads(market_data_raw)
        except (json.JSONDecodeError, TypeError):
            market_data_raw = {}

    meta = event_data.get("meta") or {}
    nlp = meta.get("nlp") or {}
    features_dict = meta.get("features") or {}

    # Get primary market data
    entities = event_data.get("entities") or []
    mkt: Dict[str, Any] = {}
    if market_data_raw:
        if entities:
            mkt = market_data_raw.get(entities[0]) or {}
        if not mkt:
            for val in market_data_raw.values():
                if isinstance(val, dict):
                    mkt = val
                    break

    # Subreddit from evidence or direct column
    subreddit = (row.get("subreddit") or "").lower()
    if not subreddit:
        evidence = event_data.get("evidence") or []
        if evidence and isinstance(evidence[0], dict):
            subreddit = (evidence[0].get("subreddit") or "").lower()

    score = _safe_float(meta.get("score") or row.get("score_val"), 0.0)
    num_comments = _safe_float(
        meta.get("num_comments") or row.get("num_comments_val"), 0.0
    )

    # NLP: prefer dedicated columns (always populated), fall back to meta
    nlp_polarity = _safe_float(
        row.get("nlp_polarity") if row.get("nlp_polarity") else nlp.get("polarity"),
        0.0,
    )
    nlp_conviction = _safe_float(
        row.get("conviction") if row.get("conviction") else nlp.get("conviction"),
        0.5,
    )
    nlp_sarcasm = _safe_float(
        row.get("sarcasm_score")
        if row.get("sarcasm_score")
        else nlp.get("sarcasm_probability"),
        0.0,
    )
    nlp_actionability = _safe_float(
        row.get("actionability")
        if row.get("actionability")
        else nlp.get("actionability"),
        0.5,
    )
    nlp_consensus = _safe_float(
        row.get("consensus_score")
        if row.get("consensus_score")
        else nlp.get("thread_consensus"),
        0.0,
    )

    body_excerpt = meta.get("body_excerpt") or ""
    entity_count = float(len(entities))

    event_type = row.get("event_type") or event_data.get("event_type") or "other"
    stance = row.get("stance") or event_data.get("stance") or "unknown"
    horizon = (
        row.get("time_horizon") or event_data.get("time_horizon") or "unknown"
    )

    author_karma = _safe_float(
        row.get("author_karma") or meta.get("author_karma"), 0.0
    )
    author_age = _safe_float(
        row.get("author_age_days") or meta.get("author_age_days"), 0.0
    )

    flair = meta.get("flair") or ""

    return [
        # Post metadata (0-6)
        score,
        num_comments,
        _safe_float(meta.get("upvote_ratio") or row.get("upvote_ratio_val"), 0.5),
        1.0 if meta.get("is_crosspost") else 0.0,
        float(len(body_excerpt)),
        entity_count,
        num_comments / max(score, 1.0),
        # Trend (7-9)
        _safe_float(row.get("trend_score") or meta.get("trend_score"), 0.0),
        _safe_float(features_dict.get("score_rate"), 0.0),
        _safe_float(features_dict.get("comment_rate"), 0.0),
        # NLP (10-19)
        nlp_polarity,
        _safe_float(nlp.get("intensity"), 0.0),
        nlp_conviction,
        nlp_sarcasm,
        nlp_actionability,
        _safe_float(nlp.get("urgency"), 0.0),
        nlp_consensus,
        _safe_float(nlp.get("thread_agreement_with_op"), 0.0),
        1.0 if nlp.get("contrarian_detected") else 0.0,
        1.0 if nlp else 0.0,
        # Market (20-24)
        _safe_log10(mkt.get("market_cap"), 0.0),
        _safe_float(mkt.get("pct_1d"), 0.0),
        _safe_float(mkt.get("atm_iv"), 0.0),
        _safe_float(mkt.get("pc_ratio"), 0.0),
        (
            _safe_float(mkt.get("volume"), 0.0)
            / max(_safe_float(mkt.get("avg_volume"), 1.0), 1.0)
        ),
        # Author (25-26)
        _safe_log10(max(author_karma, 1.0)),
        author_age,
        # Categorical (27-31)
        float(EVENT_TYPE_MAP.get(event_type, 5)),
        float(STANCE_MAP.get(stance, 3)),
        float(HORIZON_MAP.get(horizon, 4)),
        1.0 if flair == "rss" else 0.0,
        float(_SUBREDDIT_QUALITY.get(subreddit, 0.0)),
    ]
