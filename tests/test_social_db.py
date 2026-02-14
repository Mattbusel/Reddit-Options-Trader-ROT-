"""Tests for social intelligence database operations."""

from __future__ import annotations

import json
import time
import uuid

import pytest

from rot.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    """Create a temporary database with schema."""
    db_path = str(tmp_path / "test_social.db")
    d = Database(db_path=db_path)
    await d.connect()
    yield d
    await d.close()


# -- Helpers ----------------------------------------------------------


def _make_author_profile(
    platform: str = "reddit",
    username: str = "test_user",
    total_signals: int = 50,
    win_count: int = 30,
    loss_count: int = 20,
    accuracy: float = 0.60,
    roi_if_followed: float = 12.5,
    sharpe: float = 1.2,
    reputation_score: float = 75.0,
    stats: dict | None = None,
    id: str | None = None,
) -> dict:
    return {
        "id": id or uuid.uuid4().hex[:16],
        "platform": platform,
        "username": username,
        "total_signals": total_signals,
        "win_count": win_count,
        "loss_count": loss_count,
        "accuracy": accuracy,
        "roi_if_followed": roi_if_followed,
        "sharpe": sharpe,
        "reputation_score": reputation_score,
        "stats": stats or {"avg_confidence": 0.65, "best_ticker": "TSLA"},
    }


def _make_prediction(
    author_id: str = "author-001",
    ticker: str = "AAPL",
    stance: str = "bullish",
    confidence: float = 0.7,
    signal_id: str | None = "sig-001",
    outcome: str | None = None,
    pnl_pct: float | None = None,
    created_at: float | None = None,
    resolved_at: float | None = None,
    id: str | None = None,
) -> dict:
    return {
        "id": id or uuid.uuid4().hex[:16],
        "author_id": author_id,
        "signal_id": signal_id,
        "ticker": ticker,
        "stance": stance,
        "confidence": confidence,
        "outcome": outcome,
        "pnl_pct": pnl_pct,
        "created_at": created_at or time.time(),
        "resolved_at": resolved_at,
    }


def _make_manipulation_alert(
    alert_type: str = "coordinated_pump",
    tickers: list | None = None,
    authors: list | None = None,
    evidence: dict | None = None,
    severity: float = 0.8,
    resolved: bool = False,
    detected_at: float | None = None,
    id: str | None = None,
) -> dict:
    return {
        "id": id or uuid.uuid4().hex[:16],
        "alert_type": alert_type,
        "tickers": tickers or ["GME", "AMC"],
        "authors": authors or ["user_a", "user_b"],
        "evidence": evidence or {"post_count": 15, "timeframe": "2h"},
        "severity": severity,
        "resolved": resolved,
        "detected_at": detected_at or time.time(),
    }


def _make_propagation(
    ticker: str = "TSLA",
    origin_sub: str = "wallstreetbets",
    spread_to: str = "stocks",
    origin_ts: float | None = None,
    spread_ts: float | None = None,
    lag_seconds: float | None = None,
    detected_at: float | None = None,
    id: str | None = None,
) -> dict:
    now = time.time()
    ots = origin_ts or now - 600
    sts = spread_ts or now
    return {
        "id": id or uuid.uuid4().hex[:16],
        "ticker": ticker,
        "origin_sub": origin_sub,
        "spread_to": spread_to,
        "origin_ts": ots,
        "spread_ts": sts,
        "lag_seconds": lag_seconds if lag_seconds is not None else (sts - ots),
        "detected_at": detected_at or now,
    }


def _make_cluster(
    authors: list | None = None,
    similarity_score: float = 0.85,
    common_tickers: list | None = None,
    detected_at: float | None = None,
    id: str | None = None,
) -> dict:
    return {
        "id": id or uuid.uuid4().hex[:16],
        "authors": authors or ["user_x", "user_y", "user_z"],
        "similarity_score": similarity_score,
        "common_tickers": common_tickers or ["SPY", "QQQ"],
        "detected_at": detected_at or time.time(),
    }


# -- save_author_profile ----------------------------------------------


class TestSaveAuthorProfile:
    """Tests for author profile upsert."""

    @pytest.mark.asyncio
    async def test_save_returns_id(self, db):
        profile = _make_author_profile()
        returned_id = await db.save_author_profile(profile)
        assert returned_id == profile["id"]

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, db):
        profile = _make_author_profile(
            platform="reddit", username="deep_value_dan",
            total_signals=100, win_count=65, loss_count=35,
            accuracy=0.65, roi_if_followed=18.3, sharpe=1.5,
            reputation_score=88.0,
        )
        pid = await db.save_author_profile(profile)
        result = await db.get_author_profile(pid)
        assert result is not None
        assert result["platform"] == "reddit"
        assert result["username"] == "deep_value_dan"
        assert result["total_signals"] == 100
        assert result["win_count"] == 65
        assert result["loss_count"] == 35
        assert result["accuracy"] == 0.65
        assert result["roi_if_followed"] == 18.3
        assert result["sharpe"] == 1.5
        assert result["reputation_score"] == 88.0

    @pytest.mark.asyncio
    async def test_upsert_overwrites(self, db):
        """INSERT OR REPLACE: saving same ID updates the record."""
        fixed_id = uuid.uuid4().hex[:16]
        p1 = _make_author_profile(id=fixed_id, username="old_name", reputation_score=50.0)
        await db.save_author_profile(p1)
        p2 = _make_author_profile(id=fixed_id, username="new_name", reputation_score=90.0)
        await db.save_author_profile(p2)
        result = await db.get_author_profile(fixed_id)
        assert result["username"] == "new_name"
        assert result["reputation_score"] == 90.0

    @pytest.mark.asyncio
    async def test_stats_json_round_trip(self, db):
        stats = {"avg_confidence": 0.72, "sectors": ["tech", "energy"], "streak": 5}
        profile = _make_author_profile(stats=stats)
        pid = await db.save_author_profile(profile)
        result = await db.get_author_profile(pid)
        assert result["stats"]["avg_confidence"] == 0.72
        assert result["stats"]["sectors"] == ["tech", "energy"]
        assert result["stats"]["streak"] == 5

    @pytest.mark.asyncio
    async def test_generates_id_if_missing(self, db):
        profile = _make_author_profile()
        del profile["id"]
        pid = await db.save_author_profile(profile)
        assert pid  # non-empty
        result = await db.get_author_profile(pid)
        assert result is not None


# -- get_author_profile ------------------------------------------------


class TestGetAuthorProfile:
    """Tests for author profile retrieval by id."""

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self, db):
        result = await db.get_author_profile("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_retrieves_by_id(self, db):
        profile = _make_author_profile(username="finder_test")
        pid = await db.save_author_profile(profile)
        result = await db.get_author_profile(pid)
        assert result["username"] == "finder_test"

    @pytest.mark.asyncio
    async def test_stats_parsed_as_dict(self, db):
        profile = _make_author_profile(stats={"key": "value"})
        pid = await db.save_author_profile(profile)
        result = await db.get_author_profile(pid)
        assert isinstance(result["stats"], dict)
        assert result["stats"]["key"] == "value"


# -- get_author_profile_by_username ------------------------------------


class TestGetAuthorProfileByUsername:
    """Tests for author profile retrieval by platform + username."""

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self, db):
        result = await db.get_author_profile_by_username("reddit", "ghost_user")
        assert result is None

    @pytest.mark.asyncio
    async def test_finds_by_platform_and_username(self, db):
        profile = _make_author_profile(platform="twitter", username="options_guru")
        await db.save_author_profile(profile)
        result = await db.get_author_profile_by_username("twitter", "options_guru")
        assert result is not None
        assert result["platform"] == "twitter"
        assert result["username"] == "options_guru"

    @pytest.mark.asyncio
    async def test_platform_mismatch_returns_none(self, db):
        profile = _make_author_profile(platform="reddit", username="shared_name")
        await db.save_author_profile(profile)
        result = await db.get_author_profile_by_username("twitter", "shared_name")
        assert result is None


# -- get_author_leaderboard --------------------------------------------


class TestGetAuthorLeaderboard:
    """Tests for author leaderboard query."""

    @pytest.mark.asyncio
    async def test_empty_leaderboard(self, db):
        results = await db.get_author_leaderboard()
        assert results == []

    @pytest.mark.asyncio
    async def test_min_predictions_filter(self, db):
        """Only authors with win_count + loss_count >= min_predictions appear."""
        # 5 + 3 = 8 total predictions
        p_low = _make_author_profile(username="low", win_count=5, loss_count=3, reputation_score=90.0)
        # 20 + 15 = 35 total predictions
        p_high = _make_author_profile(username="high", win_count=20, loss_count=15, reputation_score=80.0)
        await db.save_author_profile(p_low)
        await db.save_author_profile(p_high)
        results = await db.get_author_leaderboard(min_predictions=10)
        assert len(results) == 1
        assert results[0]["username"] == "high"

    @pytest.mark.asyncio
    async def test_ordering_by_reputation(self, db):
        for i, rep in enumerate([50.0, 90.0, 70.0]):
            p = _make_author_profile(
                username=f"user_{i}", reputation_score=rep,
                win_count=20, loss_count=10,
            )
            await db.save_author_profile(p)
        results = await db.get_author_leaderboard(min_predictions=5)
        scores = [r["reputation_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_pagination(self, db):
        for i in range(10):
            p = _make_author_profile(
                username=f"user_{i}", reputation_score=float(100 - i),
                win_count=20, loss_count=10,
            )
            await db.save_author_profile(p)
        page1 = await db.get_author_leaderboard(limit=3, offset=0, min_predictions=5)
        page2 = await db.get_author_leaderboard(limit=3, offset=3, min_predictions=5)
        assert len(page1) == 3
        assert len(page2) == 3
        # No overlap between pages
        names1 = {r["username"] for r in page1}
        names2 = {r["username"] for r in page2}
        assert names1.isdisjoint(names2)


# -- record_author_prediction -----------------------------------------


class TestRecordAuthorPrediction:
    """Tests for saving author predictions."""

    @pytest.mark.asyncio
    async def test_save_returns_id(self, db):
        pred = _make_prediction()
        pid = await db.record_author_prediction(pred)
        assert pid == pred["id"]

    @pytest.mark.asyncio
    async def test_save_generates_id_if_missing(self, db):
        pred = _make_prediction()
        del pred["id"]
        pid = await db.record_author_prediction(pred)
        assert pid  # non-empty generated id

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, db):
        pred = _make_prediction(
            author_id="auth-42", ticker="NVDA", stance="bearish",
            confidence=0.85, signal_id="sig-42",
        )
        pid = await db.record_author_prediction(pred)
        results = await db.get_author_predictions("auth-42")
        assert len(results) == 1
        r = results[0]
        assert r["id"] == pid
        assert r["ticker"] == "NVDA"
        assert r["stance"] == "bearish"
        assert r["confidence"] == 0.85
        assert r["signal_id"] == "sig-42"
        assert r["outcome"] is None


# -- resolve_author_prediction -----------------------------------------


class TestResolveAuthorPrediction:
    """Tests for resolving pending predictions."""

    @pytest.mark.asyncio
    async def test_resolve_updates_outcome(self, db):
        pred = _make_prediction(author_id="auth-r1")
        pid = await db.record_author_prediction(pred)
        await db.resolve_author_prediction(pid, outcome="win", pnl_pct=5.3)
        results = await db.get_author_predictions("auth-r1")
        assert len(results) == 1
        assert results[0]["outcome"] == "win"
        assert results[0]["pnl_pct"] == 5.3
        assert results[0]["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_resolve_only_null_outcome(self, db):
        """Should not overwrite an already-resolved prediction."""
        pred = _make_prediction(author_id="auth-r2")
        pid = await db.record_author_prediction(pred)
        await db.resolve_author_prediction(pid, outcome="win", pnl_pct=3.0)
        # Second resolve should be a no-op (outcome IS NULL check fails)
        await db.resolve_author_prediction(pid, outcome="loss", pnl_pct=-5.0)
        results = await db.get_author_predictions("auth-r2")
        assert results[0]["outcome"] == "win"
        assert results[0]["pnl_pct"] == 3.0


# -- get_author_predictions --------------------------------------------


class TestGetAuthorPredictions:
    """Tests for retrieving predictions by author."""

    @pytest.mark.asyncio
    async def test_empty_results(self, db):
        results = await db.get_author_predictions("nonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_filters_by_author_id(self, db):
        await db.record_author_prediction(_make_prediction(author_id="a1", ticker="SPY"))
        await db.record_author_prediction(_make_prediction(author_id="a2", ticker="QQQ"))
        await db.record_author_prediction(_make_prediction(author_id="a1", ticker="AAPL"))
        results = await db.get_author_predictions("a1")
        assert len(results) == 2
        assert all(r["author_id"] == "a1" for r in results)

    @pytest.mark.asyncio
    async def test_ordered_newest_first(self, db):
        t1 = time.time() - 300
        t2 = time.time()
        await db.record_author_prediction(_make_prediction(author_id="ord", ticker="OLD", created_at=t1))
        await db.record_author_prediction(_make_prediction(author_id="ord", ticker="NEW", created_at=t2))
        results = await db.get_author_predictions("ord")
        assert results[0]["ticker"] == "NEW"

    @pytest.mark.asyncio
    async def test_limit(self, db):
        for i in range(10):
            await db.record_author_prediction(
                _make_prediction(author_id="lim", ticker=f"T{i}")
            )
        results = await db.get_author_predictions("lim", limit=3)
        assert len(results) == 3


# -- get_pending_predictions -------------------------------------------


class TestGetPendingPredictions:
    """Tests for retrieving unresolved predictions past a minimum age."""

    @pytest.mark.asyncio
    async def test_empty_when_none(self, db):
        results = await db.get_pending_predictions()
        assert results == []

    @pytest.mark.asyncio
    async def test_filters_unresolved_only(self, db):
        # Resolved prediction -- should not appear
        pred_resolved = _make_prediction(
            author_id="p1", outcome="win", pnl_pct=2.0,
            created_at=time.time() - 7200,
        )
        await db.record_author_prediction(pred_resolved)
        # Unresolved prediction old enough
        pred_pending = _make_prediction(
            author_id="p2", created_at=time.time() - 7200,
        )
        await db.record_author_prediction(pred_pending)
        results = await db.get_pending_predictions(min_age_hours=1)
        assert len(results) == 1
        assert results[0]["author_id"] == "p2"

    @pytest.mark.asyncio
    async def test_min_age_hours_filter(self, db):
        # Created 30 minutes ago -- too recent for 1h filter
        recent = _make_prediction(author_id="recent", created_at=time.time() - 1800)
        # Created 3 hours ago -- old enough
        old = _make_prediction(author_id="old", created_at=time.time() - 10800)
        await db.record_author_prediction(recent)
        await db.record_author_prediction(old)
        results = await db.get_pending_predictions(min_age_hours=1)
        assert len(results) == 1
        assert results[0]["author_id"] == "old"


# -- save_manipulation_alert -------------------------------------------


class TestSaveManipulationAlert:
    """Tests for saving manipulation alerts."""

    @pytest.mark.asyncio
    async def test_save_returns_id(self, db):
        alert = _make_manipulation_alert()
        aid = await db.save_manipulation_alert(alert)
        assert aid == alert["id"]

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, db):
        alert = _make_manipulation_alert(
            alert_type="wash_trading",
            tickers=["PLTR"],
            authors=["bot_1", "bot_2", "bot_3"],
            severity=0.95,
        )
        await db.save_manipulation_alert(alert)
        results = await db.get_manipulation_alerts()
        assert len(results) == 1
        r = results[0]
        assert r["alert_type"] == "wash_trading"
        assert r["tickers"] == ["PLTR"]
        assert r["authors"] == ["bot_1", "bot_2", "bot_3"]
        assert r["severity"] == 0.95
        assert r["resolved"] is False

    @pytest.mark.asyncio
    async def test_evidence_json_round_trip(self, db):
        evidence = {"posts": 25, "accounts": 3, "pattern": "copy-paste"}
        alert = _make_manipulation_alert(evidence=evidence)
        await db.save_manipulation_alert(alert)
        results = await db.get_manipulation_alerts()
        assert results[0]["evidence"]["posts"] == 25
        assert results[0]["evidence"]["pattern"] == "copy-paste"

    @pytest.mark.asyncio
    async def test_save_resolved_alert(self, db):
        alert = _make_manipulation_alert(resolved=True)
        await db.save_manipulation_alert(alert)
        results = await db.get_manipulation_alerts(resolved=True)
        assert len(results) == 1
        assert results[0]["resolved"] is True


# -- get_manipulation_alerts -------------------------------------------


class TestGetManipulationAlerts:
    """Tests for filtered manipulation alert queries."""

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        results = await db.get_manipulation_alerts()
        assert results == []

    @pytest.mark.asyncio
    async def test_filter_by_resolved_false(self, db):
        await db.save_manipulation_alert(_make_manipulation_alert(resolved=False))
        await db.save_manipulation_alert(_make_manipulation_alert(resolved=True))
        results = await db.get_manipulation_alerts(resolved=False)
        assert len(results) == 1
        assert results[0]["resolved"] is False

    @pytest.mark.asyncio
    async def test_filter_by_resolved_true(self, db):
        await db.save_manipulation_alert(_make_manipulation_alert(resolved=False))
        await db.save_manipulation_alert(_make_manipulation_alert(resolved=True))
        results = await db.get_manipulation_alerts(resolved=True)
        assert len(results) == 1
        assert results[0]["resolved"] is True

    @pytest.mark.asyncio
    async def test_filter_by_hours(self, db):
        old = _make_manipulation_alert(detected_at=time.time() - 7200)  # 2h ago
        recent = _make_manipulation_alert(detected_at=time.time())
        await db.save_manipulation_alert(old)
        await db.save_manipulation_alert(recent)
        results = await db.get_manipulation_alerts(hours=1.0)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_limit(self, db):
        for _ in range(10):
            await db.save_manipulation_alert(_make_manipulation_alert())
        results = await db.get_manipulation_alerts(limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_ordered_newest_first(self, db):
        t1 = time.time() - 600
        t2 = time.time()
        await db.save_manipulation_alert(_make_manipulation_alert(detected_at=t1))
        await db.save_manipulation_alert(_make_manipulation_alert(detected_at=t2))
        results = await db.get_manipulation_alerts()
        assert results[0]["detected_at"] >= results[1]["detected_at"]


# -- record_sentiment_propagation --------------------------------------


class TestRecordSentimentPropagation:
    """Tests for saving sentiment propagation events."""

    @pytest.mark.asyncio
    async def test_save_returns_id(self, db):
        prop = _make_propagation()
        pid = await db.record_sentiment_propagation(prop)
        assert pid == prop["id"]

    @pytest.mark.asyncio
    async def test_save_with_lag_seconds(self, db):
        prop = _make_propagation(
            ticker="AAPL", origin_sub="wallstreetbets", spread_to="options",
            origin_ts=1000.0, spread_ts=1600.0, lag_seconds=600.0,
        )
        await db.record_sentiment_propagation(prop)
        results = await db.get_propagation_timeline("AAPL", hours=999999)
        assert len(results) == 1
        assert results[0]["lag_seconds"] == 600.0
        assert results[0]["origin_sub"] == "wallstreetbets"
        assert results[0]["spread_to"] == "options"

    @pytest.mark.asyncio
    async def test_generates_id_if_missing(self, db):
        prop = _make_propagation()
        del prop["id"]
        pid = await db.record_sentiment_propagation(prop)
        assert pid  # non-empty


# -- get_propagation_timeline ------------------------------------------


class TestGetPropagationTimeline:
    """Tests for propagation timeline queries."""

    @pytest.mark.asyncio
    async def test_empty_timeline(self, db):
        results = await db.get_propagation_timeline("AAPL")
        assert results == []

    @pytest.mark.asyncio
    async def test_filters_by_ticker(self, db):
        await db.record_sentiment_propagation(_make_propagation(ticker="TSLA"))
        await db.record_sentiment_propagation(_make_propagation(ticker="AAPL"))
        results = await db.get_propagation_timeline("TSLA", hours=999999)
        assert len(results) == 1
        assert results[0]["ticker"] == "TSLA"

    @pytest.mark.asyncio
    async def test_hours_filter(self, db):
        now = time.time()
        old = _make_propagation(ticker="SPY", origin_ts=now - 200000, spread_ts=now - 199000, detected_at=now)
        recent = _make_propagation(ticker="SPY", origin_ts=now - 100, spread_ts=now, detected_at=now)
        await db.record_sentiment_propagation(old)
        await db.record_sentiment_propagation(recent)
        # Only recent should appear with a tight hours window
        results = await db.get_propagation_timeline("SPY", hours=1.0)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_ordered_by_origin_ts_asc(self, db):
        now = time.time()
        await db.record_sentiment_propagation(
            _make_propagation(ticker="SPY", origin_ts=now - 100, spread_ts=now - 50)
        )
        await db.record_sentiment_propagation(
            _make_propagation(ticker="SPY", origin_ts=now - 300, spread_ts=now - 200)
        )
        results = await db.get_propagation_timeline("SPY", hours=999999)
        assert results[0]["origin_ts"] < results[1]["origin_ts"]


# -- get_leading_sources -----------------------------------------------


class TestGetLeadingSources:
    """Tests for leading source aggregation."""

    @pytest.mark.asyncio
    async def test_empty_sources(self, db):
        results = await db.get_leading_sources()
        assert results == []

    @pytest.mark.asyncio
    async def test_counts_by_origin_sub(self, db):
        await db.record_sentiment_propagation(_make_propagation(origin_sub="wsb"))
        await db.record_sentiment_propagation(_make_propagation(origin_sub="wsb"))
        await db.record_sentiment_propagation(_make_propagation(origin_sub="stocks"))
        results = await db.get_leading_sources(hours=999999)
        assert len(results) == 2
        # wsb has count=2, should be first
        assert results[0]["origin_sub"] == "wsb"
        assert results[0]["lead_count"] == 2
        assert results[1]["origin_sub"] == "stocks"
        assert results[1]["lead_count"] == 1

    @pytest.mark.asyncio
    async def test_hours_filter(self, db):
        old_ts = time.time() - 200000
        await db.record_sentiment_propagation(
            _make_propagation(origin_sub="old_sub", origin_ts=old_ts, spread_ts=old_ts + 100)
        )
        await db.record_sentiment_propagation(
            _make_propagation(origin_sub="recent_sub")
        )
        results = await db.get_leading_sources(hours=1.0)
        assert len(results) == 1
        assert results[0]["origin_sub"] == "recent_sub"


# -- save_author_cluster -----------------------------------------------


class TestSaveAuthorCluster:
    """Tests for author cluster persistence."""

    @pytest.mark.asyncio
    async def test_save_returns_id(self, db):
        cluster = _make_cluster()
        cid = await db.save_author_cluster(cluster)
        assert cid == cluster["id"]

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, db):
        cluster = _make_cluster(
            authors=["alpha", "beta", "gamma"],
            similarity_score=0.92,
            common_tickers=["TSLA", "NVDA"],
        )
        await db.save_author_cluster(cluster)
        results = await db.get_author_clusters(min_similarity=0.5)
        assert len(results) == 1
        r = results[0]
        assert r["authors"] == ["alpha", "beta", "gamma"]
        assert r["similarity_score"] == 0.92
        assert r["common_tickers"] == ["TSLA", "NVDA"]

    @pytest.mark.asyncio
    async def test_json_arrays_round_trip(self, db):
        cluster = _make_cluster(
            authors=["a", "b"],
            common_tickers=["SPY", "QQQ", "IWM"],
        )
        await db.save_author_cluster(cluster)
        results = await db.get_author_clusters(min_similarity=0.0)
        assert isinstance(results[0]["authors"], list)
        assert isinstance(results[0]["common_tickers"], list)
        assert len(results[0]["common_tickers"]) == 3

    @pytest.mark.asyncio
    async def test_generates_id_if_missing(self, db):
        cluster = _make_cluster()
        del cluster["id"]
        cid = await db.save_author_cluster(cluster)
        assert cid  # non-empty


# -- get_author_clusters -----------------------------------------------


class TestGetAuthorClusters:
    """Tests for author cluster queries."""

    @pytest.mark.asyncio
    async def test_empty_clusters(self, db):
        results = await db.get_author_clusters()
        assert results == []

    @pytest.mark.asyncio
    async def test_min_similarity_filter(self, db):
        await db.save_author_cluster(_make_cluster(similarity_score=0.3))
        await db.save_author_cluster(_make_cluster(similarity_score=0.7))
        await db.save_author_cluster(_make_cluster(similarity_score=0.9))
        results = await db.get_author_clusters(min_similarity=0.5)
        assert len(results) == 2
        assert all(r["similarity_score"] >= 0.5 for r in results)

    @pytest.mark.asyncio
    async def test_ordered_by_similarity_desc(self, db):
        await db.save_author_cluster(_make_cluster(similarity_score=0.6))
        await db.save_author_cluster(_make_cluster(similarity_score=0.95))
        await db.save_author_cluster(_make_cluster(similarity_score=0.8))
        results = await db.get_author_clusters(min_similarity=0.0)
        scores = [r["similarity_score"] for r in results]
        assert scores == sorted(scores, reverse=True)


# -- purge_old_social_data ---------------------------------------------


class TestPurgeOldSocialData:
    """Tests for social intelligence data cleanup."""

    @pytest.mark.asyncio
    async def test_purge_nothing(self, db):
        count = await db.purge_old_social_data(keep_days=180)
        assert count == 0

    @pytest.mark.asyncio
    async def test_purge_nothing_when_recent(self, db):
        await db.record_author_prediction(_make_prediction(author_id="a1"))
        await db.save_manipulation_alert(_make_manipulation_alert())
        await db.record_sentiment_propagation(_make_propagation())
        await db.save_author_cluster(_make_cluster())
        count = await db.purge_old_social_data(keep_days=180)
        assert count == 0

    @pytest.mark.asyncio
    async def test_purge_old_predictions(self, db):
        old_time = time.time() - (200 * 86400)  # 200 days ago
        await db.record_author_prediction(
            _make_prediction(author_id="old", created_at=old_time)
        )
        await db.record_author_prediction(
            _make_prediction(author_id="new", created_at=time.time())
        )
        count = await db.purge_old_social_data(keep_days=180)
        assert count >= 1
        # Only new prediction remains
        remaining = await db.get_author_predictions("old")
        assert len(remaining) == 0
        remaining_new = await db.get_author_predictions("new")
        assert len(remaining_new) == 1

    @pytest.mark.asyncio
    async def test_purge_old_alerts(self, db):
        old_time = time.time() - (200 * 86400)
        await db.save_manipulation_alert(_make_manipulation_alert(detected_at=old_time))
        await db.save_manipulation_alert(_make_manipulation_alert(detected_at=time.time()))
        count = await db.purge_old_social_data(keep_days=180)
        assert count >= 1
        remaining = await db.get_manipulation_alerts()
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_purge_old_propagation(self, db):
        old_time = time.time() - (200 * 86400)
        await db.record_sentiment_propagation(
            _make_propagation(ticker="SPY", detected_at=old_time)
        )
        await db.record_sentiment_propagation(
            _make_propagation(ticker="AAPL", detected_at=time.time())
        )
        count = await db.purge_old_social_data(keep_days=180)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_purge_old_clusters(self, db):
        old_time = time.time() - (200 * 86400)
        await db.save_author_cluster(_make_cluster(detected_at=old_time))
        await db.save_author_cluster(_make_cluster(detected_at=time.time()))
        count = await db.purge_old_social_data(keep_days=180)
        assert count >= 1
        remaining = await db.get_author_clusters(min_similarity=0.0)
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_purge_all_tables_at_once(self, db):
        old_time = time.time() - (200 * 86400)
        await db.record_author_prediction(
            _make_prediction(author_id="a", created_at=old_time)
        )
        await db.save_manipulation_alert(_make_manipulation_alert(detected_at=old_time))
        await db.record_sentiment_propagation(
            _make_propagation(detected_at=old_time)
        )
        await db.save_author_cluster(_make_cluster(detected_at=old_time))
        count = await db.purge_old_social_data(keep_days=180)
        assert count == 4

    @pytest.mark.asyncio
    async def test_purge_custom_keep_days(self, db):
        t_100d = time.time() - (100 * 86400)  # 100 days ago
        await db.record_author_prediction(
            _make_prediction(author_id="mid", created_at=t_100d)
        )
        # keep_days=180 should NOT purge 100-day-old data
        count_180 = await db.purge_old_social_data(keep_days=180)
        assert count_180 == 0
        # keep_days=90 SHOULD purge 100-day-old data
        count_90 = await db.purge_old_social_data(keep_days=90)
        assert count_90 == 1
