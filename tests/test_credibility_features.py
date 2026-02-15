"""Tests for credibility feature extraction (ML scorer features).

Covers:
- extract_features_from_event: all 32 features from live Event objects
- extract_features_from_row: all 32 features from database row dicts
- _safe_float / _safe_log10: edge cases for numeric coercion
- _get_primary_market: market data lookup logic
- Categorical encodings: EVENT_TYPE_MAP, STANCE_MAP, HORIZON_MAP
- FEATURE_NAMES ordering and count
"""

from __future__ import annotations

import json
import math

import pytest

from rot.core.types import Event, Evidence
from rot.credibility.features import (
    EVENT_TYPE_MAP,
    FEATURE_NAMES,
    HORIZON_MAP,
    NUM_FEATURES,
    STANCE_MAP,
    _get_primary_market,
    _safe_float,
    _safe_log10,
    _SUBREDDIT_QUALITY,
    extract_features_from_event,
    extract_features_from_row,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_event(
    event_type: str = "earnings_rumor",
    entities: list[str] | None = None,
    stance: str = "bullish",
    time_horizon: str = "earnings",
    subreddit: str = "wallstreetbets",
    confidence: float = 0.7,
    meta: dict | None = None,
) -> Event:
    """Build an Event with sane defaults, merging caller-supplied meta."""
    base_meta = {
        "score": 100,
        "num_comments": 50,
        "upvote_ratio": 0.88,
        "is_crosspost": False,
        "body_excerpt": "Some excerpt text about the ticker",
        "trend_score": 1.5,
        "features": {"score_rate": 0.4, "comment_rate": 0.2},
        "author_karma": 5000,
        "author_age_days": 365,
        "flair": "DD",
        "nlp": {
            "polarity": 0.6,
            "intensity": 0.8,
            "conviction": 0.75,
            "sarcasm_probability": 0.1,
            "actionability": 0.65,
            "urgency": 0.3,
            "thread_consensus": 0.5,
            "thread_agreement_with_op": 0.7,
            "contrarian_detected": False,
        },
        "market": {
            "TSLA": {
                "market_cap": 800_000_000_000,
                "pct_1d": 0.03,
                "atm_iv": 0.55,
                "pc_ratio": 0.8,
                "volume": 50_000_000,
                "avg_volume": 40_000_000,
            }
        },
    }
    if meta:
        base_meta.update(meta)
    return Event(
        event_type=event_type,
        entities=entities or ["TSLA"],
        stance=stance,
        time_horizon=time_horizon,
        evidence=[
            Evidence(
                post_id="abc123",
                permalink="https://reddit.com/r/{}/comments/abc123".format(subreddit),
                subreddit=subreddit,
                excerpt="excerpt",
            )
        ],
        confidence=confidence,
        meta=base_meta,
    )


def _make_row(
    event_type: str = "earnings_rumor",
    stance: str = "bullish",
    time_horizon: str = "earnings",
    subreddit: str = "wallstreetbets",
    event_data: dict | None = None,
    market_data: dict | None = None,
    **extra: object,
) -> dict:
    """Build a database row dict for extract_features_from_row."""
    default_event_data = {
        "event_type": event_type,
        "stance": stance,
        "time_horizon": time_horizon,
        "entities": ["TSLA"],
        "evidence": [{"subreddit": subreddit}],
        "meta": {
            "score": 100,
            "num_comments": 50,
            "upvote_ratio": 0.88,
            "is_crosspost": False,
            "body_excerpt": "Some text here",
            "trend_score": 1.5,
            "features": {"score_rate": 0.4, "comment_rate": 0.2},
            "author_karma": 5000,
            "author_age_days": 365,
            "flair": "DD",
            "nlp": {
                "polarity": 0.6,
                "intensity": 0.8,
                "conviction": 0.75,
                "sarcasm_probability": 0.1,
                "actionability": 0.65,
                "urgency": 0.3,
                "thread_consensus": 0.5,
                "thread_agreement_with_op": 0.7,
                "contrarian_detected": False,
            },
        },
    }
    if event_data:
        default_event_data.update(event_data)

    default_market = {
        "TSLA": {
            "market_cap": 800_000_000_000,
            "pct_1d": 0.03,
            "atm_iv": 0.55,
            "pc_ratio": 0.8,
            "volume": 50_000_000,
            "avg_volume": 40_000_000,
        }
    }
    row = {
        "event_data": json.dumps(default_event_data),
        "market_data": json.dumps(market_data or default_market),
        "event_type": event_type,
        "stance": stance,
        "time_horizon": time_horizon,
        "subreddit": subreddit,
    }
    row.update(extra)
    return row


# ============================================================================
# _safe_float tests
# ============================================================================


class TestSafeFloat:
    """Tests for the _safe_float numeric coercion helper."""

    @pytest.mark.parametrize(
        "val, expected",
        [
            (42, 42.0),
            (3.14, 3.14),
            ("2.5", 2.5),
            ("100", 100.0),
            (0, 0.0),
            (-1.5, -1.5),
            (True, 1.0),
            (False, 0.0),
        ],
        ids=["int", "float", "str-float", "str-int", "zero", "negative", "bool-true", "bool-false"],
    )
    def test_valid_values(self, val: object, expected: float) -> None:
        assert _safe_float(val) == expected

    @pytest.mark.parametrize(
        "val",
        [None, "abc", "", "N/A", [], {}, object()],
        ids=["none", "alpha", "empty-str", "na-str", "list", "dict", "object"],
    )
    def test_invalid_returns_default(self, val: object) -> None:
        assert _safe_float(val) == 0.0

    def test_custom_default(self) -> None:
        assert _safe_float(None, default=5.0) == 5.0
        assert _safe_float("garbage", default=-1.0) == -1.0

    def test_nan_returns_default(self) -> None:
        assert _safe_float(float("nan")) == 0.0
        assert _safe_float(float("nan"), default=99.0) == 99.0

    def test_inf_returns_default(self) -> None:
        assert _safe_float(float("inf")) == 0.0
        assert _safe_float(float("-inf"), default=7.0) == 7.0


# ============================================================================
# _safe_log10 tests
# ============================================================================


class TestSafeLog10:
    """Tests for log10 with safe defaults."""

    @pytest.mark.parametrize(
        "val, expected",
        [
            (10, 1.0),
            (100, 2.0),
            (1000, 3.0),
            (1, 0.0),
            (1_000_000, 6.0),
        ],
        ids=["10", "100", "1000", "1", "million"],
    )
    def test_powers_of_ten(self, val: int, expected: float) -> None:
        assert math.isclose(_safe_log10(val), expected, rel_tol=1e-9)

    @pytest.mark.parametrize(
        "val",
        [0, -1, -100, None, "bad"],
        ids=["zero", "neg1", "neg100", "none", "string"],
    )
    def test_invalid_returns_default(self, val: object) -> None:
        assert _safe_log10(val) == 0.0

    def test_custom_default_for_invalid(self) -> None:
        assert _safe_log10(-5, default=3.0) == 3.0


# ============================================================================
# _get_primary_market tests
# ============================================================================


class TestGetPrimaryMarket:
    """Tests for market data extraction."""

    def test_returns_entity_market_data(self) -> None:
        meta = {"market": {"AAPL": {"pct_1d": 0.02}}}
        result = _get_primary_market(meta, ["AAPL"])
        assert result == {"pct_1d": 0.02}

    def test_falls_back_to_first_dict_value(self) -> None:
        meta = {"market": {"XYZ": {"pct_1d": 0.05}}}
        result = _get_primary_market(meta, ["NOPE"])
        assert result == {"pct_1d": 0.05}

    def test_empty_market_returns_empty(self) -> None:
        assert _get_primary_market({}, ["AAPL"]) == {}
        assert _get_primary_market({"market": {}}, ["AAPL"]) == {}
        assert _get_primary_market({"market": None}, ["AAPL"]) == {}

    def test_no_entities_falls_back(self) -> None:
        meta = {"market": {"AAPL": {"pct_1d": 0.02}}}
        result = _get_primary_market(meta, [])
        assert result == {"pct_1d": 0.02}


# ============================================================================
# Categorical encoding tests
# ============================================================================


class TestCategoricalMaps:
    """Tests for the ordinal encoding maps."""

    @pytest.mark.parametrize(
        "event_type, expected",
        [
            ("earnings_rumor", 0),
            ("product_news", 1),
            ("regulatory", 2),
            ("squeeze_chatter", 3),
            ("macro", 4),
            ("other", 5),
        ],
    )
    def test_event_type_map(self, event_type: str, expected: int) -> None:
        assert EVENT_TYPE_MAP[event_type] == expected

    def test_unknown_event_type_defaults_to_5(self) -> None:
        assert EVENT_TYPE_MAP.get("nonexistent", 5) == 5

    @pytest.mark.parametrize(
        "stance, expected",
        [
            ("bullish", 0),
            ("bearish", 1),
            ("mixed", 2),
            ("unknown", 3),
        ],
    )
    def test_stance_map(self, stance: str, expected: int) -> None:
        assert STANCE_MAP[stance] == expected

    @pytest.mark.parametrize(
        "horizon, expected",
        [
            ("intraday", 0),
            ("1w", 1),
            ("earnings", 2),
            ("longer", 3),
            ("unknown", 4),
        ],
    )
    def test_horizon_map(self, horizon: str, expected: int) -> None:
        assert HORIZON_MAP[horizon] == expected


# ============================================================================
# FEATURE_NAMES and NUM_FEATURES tests
# ============================================================================


class TestFeatureNames:
    """Tests for the fixed feature vector definition."""

    def test_num_features_is_32(self) -> None:
        assert NUM_FEATURES == 32

    def test_feature_names_count(self) -> None:
        assert len(FEATURE_NAMES) == 32

    def test_feature_names_unique(self) -> None:
        assert len(set(FEATURE_NAMES)) == len(FEATURE_NAMES)

    def test_starts_with_post_metadata(self) -> None:
        assert FEATURE_NAMES[0] == "post_score"

    def test_ends_with_subreddit_quality(self) -> None:
        assert FEATURE_NAMES[-1] == "subreddit_quality"

    def test_nlp_block_at_expected_indices(self) -> None:
        assert FEATURE_NAMES[10] == "nlp_polarity"
        assert FEATURE_NAMES[19] == "nlp_has_data"


# ============================================================================
# extract_features_from_event tests
# ============================================================================


class TestExtractFeaturesFromEvent:
    """Tests for live event feature extraction (inference path)."""

    def test_returns_32_floats(self) -> None:
        event = _make_event()
        features = extract_features_from_event(event)
        assert len(features) == 32
        assert all(isinstance(f, float) for f in features)

    def test_post_metadata_features(self) -> None:
        event = _make_event(meta={"score": 200, "num_comments": 80, "upvote_ratio": 0.95})
        features = extract_features_from_event(event)
        assert features[0] == 200.0  # post_score
        assert features[1] == 80.0  # num_comments
        assert features[2] == 0.95  # upvote_ratio

    def test_crosspost_flag(self) -> None:
        event_yes = _make_event(meta={"is_crosspost": True})
        event_no = _make_event(meta={"is_crosspost": False})
        assert extract_features_from_event(event_yes)[3] == 1.0
        assert extract_features_from_event(event_no)[3] == 0.0

    def test_body_length_feature(self) -> None:
        event = _make_event(meta={"body_excerpt": "A" * 42})
        features = extract_features_from_event(event)
        assert features[4] == 42.0

    def test_entity_count_feature(self) -> None:
        event_one = _make_event(entities=["AAPL"])
        event_three = _make_event(entities=["AAPL", "MSFT", "GOOG"])
        assert extract_features_from_event(event_one)[5] == 1.0
        assert extract_features_from_event(event_three)[5] == 3.0

    def test_comment_to_score_ratio(self) -> None:
        event = _make_event(meta={"score": 100, "num_comments": 50})
        features = extract_features_from_event(event)
        assert features[6] == 50.0 / 100.0  # comment_to_score_ratio

    def test_comment_to_score_ratio_zero_score(self) -> None:
        event = _make_event(meta={"score": 0, "num_comments": 10})
        features = extract_features_from_event(event)
        # max(score, 1.0) prevents division by zero
        assert features[6] == 10.0 / 1.0

    def test_trend_features(self) -> None:
        event = _make_event(
            meta={
                "trend_score": 2.5,
                "features": {"score_rate": 0.8, "comment_rate": 0.6},
            }
        )
        features = extract_features_from_event(event)
        assert features[7] == 2.5  # trend_score
        assert features[8] == 0.8  # score_rate
        assert features[9] == 0.6  # comment_rate

    def test_nlp_features(self) -> None:
        nlp = {
            "polarity": 0.4,
            "intensity": 0.9,
            "conviction": 0.85,
            "sarcasm_probability": 0.05,
            "actionability": 0.7,
            "urgency": 0.2,
            "thread_consensus": 0.6,
            "thread_agreement_with_op": 0.8,
            "contrarian_detected": True,
        }
        event = _make_event(meta={"nlp": nlp})
        features = extract_features_from_event(event)
        assert features[10] == 0.4  # polarity
        assert features[11] == 0.9  # intensity
        assert features[12] == 0.85  # conviction
        assert features[13] == 0.05  # sarcasm
        assert features[14] == 0.7  # actionability
        assert features[15] == 0.2  # urgency
        assert features[16] == 0.6  # thread_consensus
        assert features[17] == 0.8  # thread_agreement_with_op
        assert features[18] == 1.0  # contrarian_detected -> 1.0
        assert features[19] == 1.0  # nlp_has_data (nlp is truthy)

    def test_nlp_has_data_when_no_nlp(self) -> None:
        event = _make_event(meta={"nlp": {}})
        features = extract_features_from_event(event)
        # Empty dict is falsy
        assert features[19] == 0.0

    def test_contrarian_false(self) -> None:
        event = _make_event(
            meta={"nlp": {"contrarian_detected": False}}
        )
        features = extract_features_from_event(event)
        assert features[18] == 0.0

    def test_market_features(self) -> None:
        mkt = {
            "market_cap": 1_000_000_000,  # log10 = 9
            "pct_1d": -0.02,
            "atm_iv": 0.45,
            "pc_ratio": 1.2,
            "volume": 100_000,
            "avg_volume": 50_000,
        }
        event = _make_event(entities=["XYZ"], meta={"market": {"XYZ": mkt}})
        features = extract_features_from_event(event)
        assert math.isclose(features[20], 9.0, rel_tol=1e-6)  # log10(1B)
        assert features[21] == -0.02  # pct_1d
        assert features[22] == 0.45  # atm_iv
        assert features[23] == 1.2  # pc_ratio
        assert features[24] == 100_000 / 50_000  # volume_ratio = 2.0

    def test_volume_ratio_zero_avg(self) -> None:
        """avg_volume=0 should be clamped to 1.0 by max()."""
        mkt = {"volume": 100_000, "avg_volume": 0}
        event = _make_event(entities=["XYZ"], meta={"market": {"XYZ": mkt}})
        features = extract_features_from_event(event)
        assert features[24] == 100_000.0

    def test_author_features(self) -> None:
        event = _make_event(meta={"author_karma": 10_000, "author_age_days": 730})
        features = extract_features_from_event(event)
        assert math.isclose(features[25], math.log10(10_000), rel_tol=1e-6)
        assert features[26] == 730.0

    def test_author_zero_karma(self) -> None:
        """Zero karma uses max(0, 1) = 1, log10(1) = 0."""
        event = _make_event(meta={"author_karma": 0})
        features = extract_features_from_event(event)
        assert features[25] == 0.0

    @pytest.mark.parametrize(
        "event_type, expected_idx",
        [
            ("earnings_rumor", 0.0),
            ("product_news", 1.0),
            ("regulatory", 2.0),
            ("squeeze_chatter", 3.0),
            ("macro", 4.0),
            ("other", 5.0),
        ],
    )
    def test_event_type_encoding(self, event_type: str, expected_idx: float) -> None:
        event = _make_event(event_type=event_type)
        features = extract_features_from_event(event)
        assert features[27] == expected_idx

    @pytest.mark.parametrize(
        "stance, expected_idx",
        [
            ("bullish", 0.0),
            ("bearish", 1.0),
            ("mixed", 2.0),
            ("unknown", 3.0),
        ],
    )
    def test_stance_encoding(self, stance: str, expected_idx: float) -> None:
        event = _make_event(stance=stance)
        features = extract_features_from_event(event)
        assert features[28] == expected_idx

    @pytest.mark.parametrize(
        "horizon, expected_idx",
        [
            ("intraday", 0.0),
            ("1w", 1.0),
            ("earnings", 2.0),
            ("longer", 3.0),
            ("unknown", 4.0),
        ],
    )
    def test_horizon_encoding(self, horizon: str, expected_idx: float) -> None:
        event = _make_event(time_horizon=horizon)
        features = extract_features_from_event(event)
        assert features[29] == expected_idx

    def test_rss_flag(self) -> None:
        event_rss = _make_event(meta={"flair": "rss"})
        event_dd = _make_event(meta={"flair": "DD"})
        assert extract_features_from_event(event_rss)[30] == 1.0
        assert extract_features_from_event(event_dd)[30] == 0.0

    @pytest.mark.parametrize(
        "subreddit, expected_quality",
        [
            ("wallstreetbets", -0.10),
            ("options", 0.05),
            ("investing", 0.05),
            ("stocks", 0.0),
            ("thetagang", 0.05),
            ("unknownsubreddit", 0.0),
        ],
    )
    def test_subreddit_quality(self, subreddit: str, expected_quality: float) -> None:
        event = _make_event(subreddit=subreddit)
        features = extract_features_from_event(event)
        assert features[31] == expected_quality

    def test_no_evidence_subreddit(self) -> None:
        """When evidence list is empty, subreddit defaults to empty string."""
        event = Event(
            event_type="other",
            entities=["AAPL"],
            stance="bullish",
            time_horizon="1w",
            evidence=[],
            confidence=0.5,
            meta={},
        )
        features = extract_features_from_event(event)
        assert features[31] == 0.0  # empty subreddit -> default quality

    def test_missing_meta_defaults(self) -> None:
        """Event with empty meta should still produce 32 valid features."""
        event = Event(
            event_type="other",
            entities=["AAPL"],
            stance="unknown",
            time_horizon="unknown",
            evidence=[
                Evidence(
                    post_id="x", permalink="", subreddit="stocks", excerpt=""
                )
            ],
            confidence=0.3,
            meta={},
        )
        features = extract_features_from_event(event)
        assert len(features) == 32
        assert all(isinstance(f, float) for f in features)
        # score defaults to 0
        assert features[0] == 0.0
        # nlp_has_data = 0 (no nlp dict)
        assert features[19] == 0.0

    def test_none_meta_fields(self) -> None:
        """Explicitly None sub-dicts should not crash."""
        event = _make_event(
            meta={"nlp": None, "market": None, "features": None}
        )
        features = extract_features_from_event(event)
        assert len(features) == 32


# ============================================================================
# extract_features_from_row tests
# ============================================================================


class TestExtractFeaturesFromRow:
    """Tests for database row feature extraction (training path)."""

    def test_returns_32_floats(self) -> None:
        row = _make_row()
        features = extract_features_from_row(row)
        assert len(features) == 32
        assert all(isinstance(f, float) for f in features)

    def test_json_string_parsing(self) -> None:
        """event_data and market_data as JSON strings should be parsed."""
        row = _make_row()
        features = extract_features_from_row(row)
        # score from meta = 100
        assert features[0] == 100.0

    def test_already_parsed_dicts(self) -> None:
        """If event_data/market_data are already dicts (not strings), still works."""
        row = _make_row()
        row["event_data"] = json.loads(row["event_data"])
        row["market_data"] = json.loads(row["market_data"])
        features = extract_features_from_row(row)
        assert len(features) == 32

    def test_malformed_json_returns_defaults(self) -> None:
        row = _make_row()
        row["event_data"] = "NOT JSON!!!"
        row["market_data"] = "ALSO BAD"
        features = extract_features_from_row(row)
        assert len(features) == 32
        # With no parseable data, most things default to 0
        assert features[0] == 0.0

    def test_empty_event_data(self) -> None:
        row = _make_row()
        row["event_data"] = "{}"
        row["market_data"] = "{}"
        features = extract_features_from_row(row)
        assert len(features) == 32

    def test_subreddit_from_row_column(self) -> None:
        """Row-level subreddit column takes precedence."""
        row = _make_row(subreddit="options")
        features = extract_features_from_row(row)
        assert features[31] == _SUBREDDIT_QUALITY.get("options", 0.0)

    def test_subreddit_from_evidence_fallback(self) -> None:
        """When row subreddit is empty, feature defaults to 0.0."""
        row = _make_row(subreddit="")
        features = extract_features_from_row(row)
        # Empty subreddit doesn't fall back through evidence, defaults to 0.0
        assert features[31] == 0.0

    @pytest.mark.parametrize(
        "event_type, expected_idx",
        [
            ("earnings_rumor", 0.0),
            ("product_news", 1.0),
            ("regulatory", 2.0),
            ("other", 5.0),
        ],
    )
    def test_row_event_type_encoding(self, event_type: str, expected_idx: float) -> None:
        row = _make_row(event_type=event_type)
        features = extract_features_from_row(row)
        assert features[27] == expected_idx

    @pytest.mark.parametrize(
        "stance, expected_idx",
        [
            ("bullish", 0.0),
            ("bearish", 1.0),
            ("mixed", 2.0),
            ("unknown", 3.0),
        ],
    )
    def test_row_stance_encoding(self, stance: str, expected_idx: float) -> None:
        row = _make_row(stance=stance)
        features = extract_features_from_row(row)
        assert features[28] == expected_idx

    @pytest.mark.parametrize(
        "horizon, expected_idx",
        [
            ("intraday", 0.0),
            ("1w", 1.0),
            ("earnings", 2.0),
            ("longer", 3.0),
            ("unknown", 4.0),
        ],
    )
    def test_row_horizon_encoding(self, horizon: str, expected_idx: float) -> None:
        row = _make_row(time_horizon=horizon)
        features = extract_features_from_row(row)
        assert features[29] == expected_idx

    def test_rss_flair_from_meta(self) -> None:
        row = _make_row()
        # Modify the event_data meta to have flair "rss"
        ed = json.loads(row["event_data"])
        ed["meta"]["flair"] = "rss"
        row["event_data"] = json.dumps(ed)
        features = extract_features_from_row(row)
        assert features[30] == 1.0

    def test_non_rss_flair(self) -> None:
        row = _make_row()
        features = extract_features_from_row(row)
        assert features[30] == 0.0  # flair is "DD" by default

    def test_dedicated_nlp_columns_take_precedence(self) -> None:
        """Row-level NLP columns override meta.nlp values."""
        row = _make_row()
        row["nlp_polarity"] = 0.99
        row["conviction"] = 0.88
        row["sarcasm_score"] = 0.77
        row["actionability"] = 0.66
        row["consensus_score"] = 0.55
        features = extract_features_from_row(row)
        assert features[10] == 0.99  # nlp_polarity from dedicated column
        assert features[12] == 0.88  # conviction
        assert features[13] == 0.77  # sarcasm
        assert features[14] == 0.66  # actionability
        assert features[16] == 0.55  # consensus

    def test_fallback_to_meta_nlp_when_no_columns(self) -> None:
        """When dedicated NLP columns are absent, falls back to meta.nlp."""
        row = _make_row()
        features = extract_features_from_row(row)
        assert features[10] == 0.6  # from meta.nlp.polarity
        assert features[12] == 0.75  # from meta.nlp.conviction

    def test_author_from_row_columns(self) -> None:
        row = _make_row(author_karma=50_000, author_age_days=1000)
        features = extract_features_from_row(row)
        assert math.isclose(features[25], math.log10(50_000), rel_tol=1e-6)
        assert features[26] == 1000.0

    def test_author_from_meta_fallback(self) -> None:
        """Without row-level author columns, use meta values."""
        row = _make_row()
        features = extract_features_from_row(row)
        assert math.isclose(features[25], math.log10(5000), rel_tol=1e-6)
        assert features[26] == 365.0

    def test_market_data_from_entity(self) -> None:
        row = _make_row()
        features = extract_features_from_row(row)
        # market_cap_log for 800B
        assert math.isclose(features[20], math.log10(800_000_000_000), rel_tol=1e-4)
        assert features[21] == 0.03  # pct_1d
        assert features[22] == 0.55  # atm_iv

    def test_empty_market_data(self) -> None:
        row = _make_row(market_data={})
        features = extract_features_from_row(row)
        assert len(features) == 32
        # Features still populated (may use defaults or fallbacks)
        assert isinstance(features[20], float)
        assert isinstance(features[21], float)

    def test_trend_score_from_row_column(self) -> None:
        row = _make_row(trend_score=3.0)
        features = extract_features_from_row(row)
        assert features[7] == 3.0


# ============================================================================
# Consistency: event vs row extraction
# ============================================================================


class TestConsistency:
    """Verify event and row paths produce compatible vectors."""

    def test_same_data_same_features(self) -> None:
        """Matching event and row should produce identical feature vectors."""
        event = _make_event()
        row = _make_row()
        ev_features = extract_features_from_event(event)
        row_features = extract_features_from_row(row)
        # Both should be length 32
        assert len(ev_features) == len(row_features) == 32
        # Feature vector structure should be the same (types)
        for i in range(32):
            assert isinstance(ev_features[i], float)
            assert isinstance(row_features[i], float)


# ============================================================================
# Edge cases
# ============================================================================


class TestEdgeCases:
    """Additional edge case coverage."""

    def test_unknown_event_type_in_event(self) -> None:
        """Unknown event_type should default to index 5."""
        event = _make_event(event_type="completely_novel")
        features = extract_features_from_event(event)
        assert features[27] == 5.0

    def test_unknown_stance_in_event(self) -> None:
        event = _make_event(stance="confused")
        features = extract_features_from_event(event)
        assert features[28] == 3.0  # defaults to "unknown" -> 3

    def test_unknown_horizon_in_event(self) -> None:
        event = _make_event(time_horizon="decades")
        features = extract_features_from_event(event)
        assert features[29] == 4.0  # defaults to "unknown" -> 4

    def test_large_market_cap(self) -> None:
        """Trillion-dollar market cap should not overflow."""
        mkt = {"market_cap": 3_000_000_000_000}
        event = _make_event(entities=["AAPL"], meta={"market": {"AAPL": mkt}})
        features = extract_features_from_event(event)
        assert math.isclose(features[20], math.log10(3_000_000_000_000), rel_tol=1e-6)

    def test_negative_score(self) -> None:
        """Negative score (downvoted post) should still work."""
        event = _make_event(meta={"score": -5, "num_comments": 3})
        features = extract_features_from_event(event)
        assert features[0] == -5.0
        # comment_to_score_ratio uses max(score, 1.0) => 3/1
        assert features[6] == 3.0

    @pytest.mark.parametrize(
        "karma,expected_log",
        [
            (1, 0.0),
            (10, 1.0),
            (100_000, 5.0),
            (0, 0.0),
            (-100, 0.0),
        ],
        ids=["1", "10", "100k", "zero", "negative"],
    )
    def test_author_karma_log_variants(self, karma: int, expected_log: float) -> None:
        event = _make_event(meta={"author_karma": karma})
        features = extract_features_from_event(event)
        assert math.isclose(features[25], expected_log, abs_tol=1e-6)

    def test_subreddit_case_insensitive(self) -> None:
        """Subreddit quality lookup should be case-insensitive."""
        event = _make_event(subreddit="WallStreetBets")
        features = extract_features_from_event(event)
        assert features[31] == -0.10

    def test_no_body_excerpt(self) -> None:
        event = _make_event(meta={"body_excerpt": None})
        features = extract_features_from_event(event)
        assert features[4] == 0.0  # len("") = 0

    def test_row_with_none_event_data(self) -> None:
        row = {"event_data": None, "market_data": None}
        features = extract_features_from_row(row)
        assert len(features) == 32

    def test_row_all_none_columns(self) -> None:
        """Row with no useful data should still produce 32 defaults."""
        row = {}
        features = extract_features_from_row(row)
        assert len(features) == 32
        assert all(isinstance(f, float) for f in features)
