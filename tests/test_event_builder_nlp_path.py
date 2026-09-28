"""The NLP path of EventBuilder must not fall back to the legacy regex path.

Regression test: _from_candidate_nlp read ``ent.sentiment`` and ``ent.text``,
which ResolvedEntity does not have (its fields are ``sentiment_toward`` and
``symbol``), so every NLP pass raised AttributeError and silently fell back.
"""
from __future__ import annotations

import logging

import pytest

from rot.core.types import Post, ThreadSnapshot, TrendCandidate
from rot.extract.event_builder import EventBuilder
from rot.nlp import NLPEngine
from rot.nlp.types import ResolvedEntity


def _candidate(title: str, body: str) -> TrendCandidate:
    post = Post(
        id="nlp1", created_utc=1700000000, subreddit="options", title=title, selftext=body,
        url="", score=500, num_comments=120, upvote_ratio=0.93, author="tester",
        permalink="/r/options/comments/nlp1/", flair="DD",
    )
    snap = ThreadSnapshot(snapshot_ts=1700000600, post=post)
    return TrendCandidate(key="options:nlp1", window_s=1800, features={"score_rate": 0.3},
                          trend_score=0.9, reason="rate_threshold", snapshot=snap)


def test_resolved_entity_fields_used_by_event_builder():
    names = set(ResolvedEntity.__dataclass_fields__)
    assert {"symbol", "sentiment_toward"} <= names
    assert "sentiment" not in names and "text" not in names


def test_nlp_path_does_not_fall_back(caplog):
    builder = EventBuilder(nlp_engine=NLPEngine())
    c = _candidate("NVDA DD: data center demand still strong",
                   "Deep dive on $NVDA. I think earnings beat. Bullish, buying calls.")
    with caplog.at_level(logging.DEBUG):
        events = builder.from_candidate(c)
    assert "falling back to legacy" not in caplog.text
    assert events and "NVDA" in events[0].entities


def test_nlp_path_ticker_sentiments_keyed_by_symbol():
    builder = EventBuilder(nlp_engine=NLPEngine())
    events = builder._from_candidate_nlp(
        _candidate("Bullish on $NVDA", "Buying $NVDA calls, very bullish into earnings."))
    assert events
    sentiments = events[0].meta.get("ticker_sentiments", {})
    for key, value in sentiments.items():
        assert key.isupper()
        assert value in ("bullish", "bearish")


@pytest.mark.parametrize("body", ["", "no tickers here at all"])
def test_nlp_path_handles_posts_without_tickers(body):
    builder = EventBuilder(nlp_engine=NLPEngine())
    assert builder._from_candidate_nlp(_candidate("General question", body)) == []
