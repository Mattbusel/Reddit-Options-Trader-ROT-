"""Tests for rot.social.types — frozen dataclasses for the Social Intelligence Network."""

import time

import pytest

from rot.social.types import (
    ALERT_TYPES,
    OUTCOMES,
    PLATFORMS,
    STANCES,
    AuthorCluster,
    AuthorPrediction,
    AuthorProfile,
    ContrarianSignal,
    ManipulationAlert,
    SentimentPropagation,
)


# ── Module constants ────────────────────────────────────────────────────────


class TestConstants:
    def test_platforms(self):
        assert PLATFORMS == frozenset({"reddit", "stocktwits", "twitter"})

    def test_stances(self):
        assert STANCES == frozenset({"bullish", "bearish", "mixed", "unknown"})

    def test_outcomes(self):
        assert OUTCOMES == frozenset({"win", "loss", "neutral"})

    def test_alert_types(self):
        assert ALERT_TYPES == frozenset(
            {"coordinated_posting", "bot_network", "pump_and_dump"}
        )


# ── AuthorProfile ───────────────────────────────────────────────────────────


class TestAuthorProfile:
    def test_full_creation(self):
        ts = time.time()
        p = AuthorProfile(
            id="ap1",
            platform="reddit",
            username="trader_joe",
            total_signals=100,
            win_count=60,
            loss_count=30,
            accuracy=0.66,
            roi_if_followed=12.5,
            sharpe=1.8,
            reputation_score=75.0,
            stats={"avg_confidence": 0.7},
            first_seen=ts - 3600,
            last_seen=ts,
            updated_at=ts,
        )
        assert p.platform == "reddit"
        assert p.username == "trader_joe"
        assert p.total_signals == 100
        assert p.win_count == 60
        assert p.loss_count == 30
        assert p.accuracy == 0.66
        assert p.roi_if_followed == 12.5
        assert p.sharpe == 1.8
        assert p.reputation_score == 75.0
        assert p.stats == {"avg_confidence": 0.7}

    def test_minimal_creation_defaults(self):
        p = AuthorProfile(id="ap2", platform="twitter", username="fin_guru")
        assert p.total_signals == 0
        assert p.win_count == 0
        assert p.loss_count == 0
        assert p.accuracy is None
        assert p.roi_if_followed is None
        assert p.sharpe is None
        assert p.reputation_score is None
        assert p.stats == {}
        assert p.last_seen is None
        assert p.updated_at is None
        assert p.first_seen > 0  # auto-generated via time.time()

    def test_to_dict(self):
        p = AuthorProfile(
            id="ap3",
            platform="stocktwits",
            username="st_user",
            win_count=5,
            loss_count=3,
        )
        d = p.to_dict()
        assert d["id"] == "ap3"
        assert d["platform"] == "stocktwits"
        assert d["username"] == "st_user"
        assert d["win_count"] == 5
        assert d["loss_count"] == 3
        assert d["total_signals"] == 0
        assert d["accuracy"] is None
        assert isinstance(d["stats"], dict)
        assert "first_seen" in d
        assert "last_seen" in d
        assert "updated_at" in d

    def test_decided_count_property(self):
        p = AuthorProfile(
            id="ap4", platform="reddit", username="u1", win_count=7, loss_count=3
        )
        assert p.decided_count == 10

    def test_computed_accuracy_with_decisions(self):
        p = AuthorProfile(
            id="ap5", platform="reddit", username="u2", win_count=3, loss_count=7
        )
        assert p.computed_accuracy == pytest.approx(0.3)

    def test_computed_accuracy_zero_decisions(self):
        p = AuthorProfile(id="ap6", platform="reddit", username="u3")
        assert p.computed_accuracy is None

    def test_frozen(self):
        p = AuthorProfile(id="ap7", platform="reddit", username="u4")
        with pytest.raises(AttributeError):
            p.username = "changed"  # type: ignore[misc]

    def test_invalid_platform(self):
        with pytest.raises(ValueError, match="Invalid platform"):
            AuthorProfile(id="x", platform="discord", username="u")

    def test_empty_username(self):
        with pytest.raises(ValueError, match="username must be non-empty"):
            AuthorProfile(id="x", platform="reddit", username="")

    def test_negative_total_signals(self):
        with pytest.raises(ValueError, match="total_signals must be >= 0"):
            AuthorProfile(
                id="x", platform="reddit", username="u", total_signals=-1
            )

    def test_negative_win_count(self):
        with pytest.raises(ValueError, match="win_count must be >= 0"):
            AuthorProfile(id="x", platform="reddit", username="u", win_count=-1)

    def test_negative_loss_count(self):
        with pytest.raises(ValueError, match="loss_count must be >= 0"):
            AuthorProfile(id="x", platform="reddit", username="u", loss_count=-1)

    def test_accuracy_out_of_range(self):
        with pytest.raises(ValueError, match="accuracy must be in"):
            AuthorProfile(id="x", platform="reddit", username="u", accuracy=1.5)
        with pytest.raises(ValueError, match="accuracy must be in"):
            AuthorProfile(id="x", platform="reddit", username="u", accuracy=-0.1)

    def test_reputation_score_out_of_range(self):
        with pytest.raises(ValueError, match="reputation_score must be in"):
            AuthorProfile(
                id="x", platform="reddit", username="u", reputation_score=101.0
            )
        with pytest.raises(ValueError, match="reputation_score must be in"):
            AuthorProfile(
                id="x", platform="reddit", username="u", reputation_score=-0.1
            )

    def test_all_platforms_valid(self):
        for plat in PLATFORMS:
            p = AuthorProfile(id="t", platform=plat, username="u")
            assert p.platform == plat


# ── AuthorPrediction ────────────────────────────────────────────────────────


class TestAuthorPrediction:
    def test_full_creation(self):
        ts = time.time()
        p = AuthorPrediction(
            id="pred1",
            author_id="a1",
            ticker="TSLA",
            stance="bullish",
            confidence=0.85,
            signal_id="sig1",
            outcome="win",
            pnl_pct=12.5,
            created_at=ts,
            resolved_at=ts + 3600,
        )
        assert p.id == "pred1"
        assert p.author_id == "a1"
        assert p.ticker == "TSLA"
        assert p.stance == "bullish"
        assert p.confidence == 0.85
        assert p.signal_id == "sig1"
        assert p.outcome == "win"
        assert p.pnl_pct == 12.5

    def test_minimal_creation_defaults(self):
        p = AuthorPrediction(
            id="pred2",
            author_id="a2",
            ticker="AAPL",
            stance="bearish",
            confidence=0.5,
        )
        assert p.signal_id is None
        assert p.outcome is None
        assert p.pnl_pct is None
        assert p.resolved_at is None
        assert p.created_at > 0

    def test_to_dict(self):
        p = AuthorPrediction(
            id="pred3",
            author_id="a3",
            ticker="NVDA",
            stance="mixed",
            confidence=0.3,
            outcome="loss",
        )
        d = p.to_dict()
        assert d["id"] == "pred3"
        assert d["author_id"] == "a3"
        assert d["ticker"] == "NVDA"
        assert d["stance"] == "mixed"
        assert d["confidence"] == 0.3
        assert d["outcome"] == "loss"
        assert "created_at" in d
        assert "resolved_at" in d

    def test_is_resolved_true(self):
        p = AuthorPrediction(
            id="p", author_id="a", ticker="T", stance="bullish",
            confidence=0.5, outcome="win",
        )
        assert p.is_resolved is True

    def test_is_resolved_false(self):
        p = AuthorPrediction(
            id="p", author_id="a", ticker="T", stance="bullish", confidence=0.5
        )
        assert p.is_resolved is False

    def test_is_win(self):
        p = AuthorPrediction(
            id="p", author_id="a", ticker="T", stance="bullish",
            confidence=0.5, outcome="win",
        )
        assert p.is_win is True
        assert p.is_loss is False

    def test_is_loss(self):
        p = AuthorPrediction(
            id="p", author_id="a", ticker="T", stance="bearish",
            confidence=0.5, outcome="loss",
        )
        assert p.is_loss is True
        assert p.is_win is False

    def test_neutral_outcome(self):
        p = AuthorPrediction(
            id="p", author_id="a", ticker="T", stance="unknown",
            confidence=0.5, outcome="neutral",
        )
        assert p.is_resolved is True
        assert p.is_win is False
        assert p.is_loss is False

    def test_frozen(self):
        p = AuthorPrediction(
            id="p", author_id="a", ticker="T", stance="bullish", confidence=0.5
        )
        with pytest.raises(AttributeError):
            p.outcome = "win"  # type: ignore[misc]

    def test_invalid_stance(self):
        with pytest.raises(ValueError, match="Invalid stance"):
            AuthorPrediction(
                id="p", author_id="a", ticker="T", stance="neutral",
                confidence=0.5,
            )

    def test_empty_author_id(self):
        with pytest.raises(ValueError, match="author_id must be non-empty"):
            AuthorPrediction(
                id="p", author_id="", ticker="T", stance="bullish", confidence=0.5
            )

    def test_empty_ticker(self):
        with pytest.raises(ValueError, match="ticker must be non-empty"):
            AuthorPrediction(
                id="p", author_id="a", ticker="", stance="bullish", confidence=0.5
            )

    def test_confidence_out_of_range(self):
        with pytest.raises(ValueError, match="confidence must be in"):
            AuthorPrediction(
                id="p", author_id="a", ticker="T", stance="bullish", confidence=1.1
            )
        with pytest.raises(ValueError, match="confidence must be in"):
            AuthorPrediction(
                id="p", author_id="a", ticker="T", stance="bullish", confidence=-0.1
            )

    def test_invalid_outcome(self):
        with pytest.raises(ValueError, match="Invalid outcome"):
            AuthorPrediction(
                id="p", author_id="a", ticker="T", stance="bullish",
                confidence=0.5, outcome="draw",
            )


# ── ManipulationAlert ───────────────────────────────────────────────────────


class TestManipulationAlert:
    def test_full_creation(self):
        a = ManipulationAlert(
            id="ma1",
            alert_type="pump_and_dump",
            tickers=["TSLA", "GME"],
            authors=["bot1", "bot2"],
            evidence={"correlation": 0.95, "window_minutes": 10},
            severity=85.0,
            resolved=True,
        )
        assert a.alert_type == "pump_and_dump"
        assert a.tickers == ["TSLA", "GME"]
        assert a.authors == ["bot1", "bot2"]
        assert a.severity == 85.0
        assert a.resolved is True

    def test_minimal_creation(self):
        a = ManipulationAlert(
            id="ma2",
            alert_type="bot_network",
            tickers=["AAPL"],
            authors=[],
            evidence={},
            severity=50.0,
        )
        assert a.resolved is False
        assert a.detected_at > 0

    def test_to_dict(self):
        a = ManipulationAlert(
            id="ma3",
            alert_type="coordinated_posting",
            tickers=["SPY"],
            authors=["u1"],
            evidence={"count": 5},
            severity=30.0,
        )
        d = a.to_dict()
        assert d["id"] == "ma3"
        assert d["alert_type"] == "coordinated_posting"
        assert d["tickers"] == ["SPY"]
        assert d["authors"] == ["u1"]
        assert d["evidence"] == {"count": 5}
        assert d["severity"] == 30.0
        assert d["resolved"] is False
        assert "detected_at" in d

    def test_frozen(self):
        a = ManipulationAlert(
            id="ma4", alert_type="pump_and_dump", tickers=["X"],
            authors=[], evidence={}, severity=10.0,
        )
        with pytest.raises(AttributeError):
            a.severity = 99.0  # type: ignore[misc]

    def test_invalid_alert_type(self):
        with pytest.raises(ValueError, match="Invalid alert_type"):
            ManipulationAlert(
                id="x", alert_type="insider_trading", tickers=["T"],
                authors=[], evidence={}, severity=50.0,
            )

    def test_severity_out_of_range(self):
        with pytest.raises(ValueError, match="severity must be in"):
            ManipulationAlert(
                id="x", alert_type="pump_and_dump", tickers=["T"],
                authors=[], evidence={}, severity=101.0,
            )
        with pytest.raises(ValueError, match="severity must be in"):
            ManipulationAlert(
                id="x", alert_type="pump_and_dump", tickers=["T"],
                authors=[], evidence={}, severity=-1.0,
            )

    def test_empty_tickers(self):
        with pytest.raises(ValueError, match="tickers must be non-empty"):
            ManipulationAlert(
                id="x", alert_type="pump_and_dump", tickers=[],
                authors=[], evidence={}, severity=50.0,
            )


# ── SentimentPropagation ───────────────────────────────────────────────────


class TestSentimentPropagation:
    def test_full_creation(self):
        sp = SentimentPropagation(
            id="sp1",
            ticker="TSLA",
            origin_sub="wallstreetbets",
            spread_to="stocks",
            origin_ts=1000.0,
            spread_ts=2000.0,
        )
        assert sp.ticker == "TSLA"
        assert sp.origin_sub == "wallstreetbets"
        assert sp.spread_to == "stocks"
        assert sp.origin_ts == 1000.0
        assert sp.spread_ts == 2000.0

    def test_to_dict_includes_lag(self):
        sp = SentimentPropagation(
            id="sp2",
            ticker="AAPL",
            origin_sub="options",
            spread_to="investing",
            origin_ts=5000.0,
            spread_ts=5300.0,
        )
        d = sp.to_dict()
        assert d["id"] == "sp2"
        assert d["ticker"] == "AAPL"
        assert d["origin_sub"] == "options"
        assert d["spread_to"] == "investing"
        assert d["lag_seconds"] == pytest.approx(300.0)
        assert "detected_at" in d

    def test_lag_seconds_property(self):
        sp = SentimentPropagation(
            id="sp3", ticker="GME", origin_sub="a", spread_to="b",
            origin_ts=100.0, spread_ts=250.0,
        )
        assert sp.lag_seconds == pytest.approx(150.0)

    def test_negative_lag_allowed(self):
        # spread_ts can theoretically be before origin_ts (data quirk)
        sp = SentimentPropagation(
            id="sp4", ticker="SPY", origin_sub="a", spread_to="b",
            origin_ts=500.0, spread_ts=400.0,
        )
        assert sp.lag_seconds == pytest.approx(-100.0)

    def test_frozen(self):
        sp = SentimentPropagation(
            id="sp5", ticker="X", origin_sub="a", spread_to="b",
            origin_ts=0.0, spread_ts=1.0,
        )
        with pytest.raises(AttributeError):
            sp.ticker = "Y"  # type: ignore[misc]

    def test_empty_ticker(self):
        with pytest.raises(ValueError, match="ticker must be non-empty"):
            SentimentPropagation(
                id="x", ticker="", origin_sub="a", spread_to="b",
                origin_ts=0.0, spread_ts=1.0,
            )

    def test_empty_origin_sub(self):
        with pytest.raises(ValueError, match="origin_sub must be non-empty"):
            SentimentPropagation(
                id="x", ticker="T", origin_sub="", spread_to="b",
                origin_ts=0.0, spread_ts=1.0,
            )

    def test_empty_spread_to(self):
        with pytest.raises(ValueError, match="spread_to must be non-empty"):
            SentimentPropagation(
                id="x", ticker="T", origin_sub="a", spread_to="",
                origin_ts=0.0, spread_ts=1.0,
            )

    def test_same_origin_and_spread(self):
        with pytest.raises(ValueError, match="origin_sub and spread_to must differ"):
            SentimentPropagation(
                id="x", ticker="T", origin_sub="wsb", spread_to="wsb",
                origin_ts=0.0, spread_ts=1.0,
            )


# ── AuthorCluster ───────────────────────────────────────────────────────────


class TestAuthorCluster:
    def test_full_creation(self):
        c = AuthorCluster(
            id="cl1",
            authors=["u1", "u2", "u3"],
            similarity_score=0.85,
            common_tickers=["TSLA", "AAPL"],
        )
        assert c.authors == ["u1", "u2", "u3"]
        assert c.similarity_score == 0.85
        assert c.common_tickers == ["TSLA", "AAPL"]
        assert c.detected_at > 0

    def test_to_dict(self):
        c = AuthorCluster(
            id="cl2",
            authors=["a", "b"],
            similarity_score=0.5,
            common_tickers=["SPY"],
        )
        d = c.to_dict()
        assert d["id"] == "cl2"
        assert d["authors"] == ["a", "b"]
        assert d["similarity_score"] == 0.5
        assert d["common_tickers"] == ["SPY"]
        assert "detected_at" in d

    def test_frozen(self):
        c = AuthorCluster(
            id="cl3", authors=["a", "b"], similarity_score=0.5,
            common_tickers=[],
        )
        with pytest.raises(AttributeError):
            c.similarity_score = 0.9  # type: ignore[misc]

    def test_similarity_score_out_of_range(self):
        with pytest.raises(ValueError, match="similarity_score must be in"):
            AuthorCluster(
                id="x", authors=["a", "b"], similarity_score=1.1,
                common_tickers=[],
            )
        with pytest.raises(ValueError, match="similarity_score must be in"):
            AuthorCluster(
                id="x", authors=["a", "b"], similarity_score=-0.01,
                common_tickers=[],
            )

    def test_too_few_authors(self):
        with pytest.raises(ValueError, match="cluster must have at least 2 authors"):
            AuthorCluster(
                id="x", authors=["solo"], similarity_score=0.5,
                common_tickers=[],
            )

    def test_zero_authors(self):
        with pytest.raises(ValueError, match="cluster must have at least 2 authors"):
            AuthorCluster(
                id="x", authors=[], similarity_score=0.5, common_tickers=[],
            )

    def test_boundary_similarity_scores(self):
        c0 = AuthorCluster(
            id="b1", authors=["a", "b"], similarity_score=0.0, common_tickers=[],
        )
        assert c0.similarity_score == 0.0
        c1 = AuthorCluster(
            id="b2", authors=["a", "b"], similarity_score=1.0, common_tickers=[],
        )
        assert c1.similarity_score == 1.0


# ── ContrarianSignal ────────────────────────────────────────────────────────


class TestContrarianSignal:
    def test_full_creation(self):
        cs = ContrarianSignal(
            id="cs1",
            ticker="GME",
            contrarian_stance="bearish",
            consensus_stance="bullish",
            contrarian_authors=["contrarian_1"],
            consensus_author_count=50,
            strength=0.9,
        )
        assert cs.ticker == "GME"
        assert cs.contrarian_stance == "bearish"
        assert cs.consensus_stance == "bullish"
        assert cs.contrarian_authors == ["contrarian_1"]
        assert cs.consensus_author_count == 50
        assert cs.strength == 0.9
        assert cs.detected_at > 0

    def test_to_dict(self):
        cs = ContrarianSignal(
            id="cs2",
            ticker="TSLA",
            contrarian_stance="bullish",
            consensus_stance="bearish",
            contrarian_authors=["a", "b"],
            consensus_author_count=30,
            strength=0.6,
        )
        d = cs.to_dict()
        assert d["id"] == "cs2"
        assert d["ticker"] == "TSLA"
        assert d["contrarian_stance"] == "bullish"
        assert d["consensus_stance"] == "bearish"
        assert d["contrarian_authors"] == ["a", "b"]
        assert d["consensus_author_count"] == 30
        assert d["strength"] == 0.6
        assert "detected_at" in d

    def test_frozen(self):
        cs = ContrarianSignal(
            id="cs3", ticker="T", contrarian_stance="bullish",
            consensus_stance="bearish", contrarian_authors=["x"],
            consensus_author_count=10, strength=0.5,
        )
        with pytest.raises(AttributeError):
            cs.strength = 1.0  # type: ignore[misc]

    def test_invalid_contrarian_stance(self):
        with pytest.raises(ValueError, match="Invalid contrarian_stance"):
            ContrarianSignal(
                id="x", ticker="T", contrarian_stance="neutral",
                consensus_stance="bullish", contrarian_authors=["a"],
                consensus_author_count=10, strength=0.5,
            )

    def test_invalid_consensus_stance(self):
        with pytest.raises(ValueError, match="Invalid consensus_stance"):
            ContrarianSignal(
                id="x", ticker="T", contrarian_stance="bullish",
                consensus_stance="flat", contrarian_authors=["a"],
                consensus_author_count=10, strength=0.5,
            )

    def test_same_stances_rejected(self):
        with pytest.raises(ValueError, match="contrarian_stance and consensus_stance must differ"):
            ContrarianSignal(
                id="x", ticker="T", contrarian_stance="bullish",
                consensus_stance="bullish", contrarian_authors=["a"],
                consensus_author_count=10, strength=0.5,
            )

    def test_strength_out_of_range(self):
        with pytest.raises(ValueError, match="strength must be in"):
            ContrarianSignal(
                id="x", ticker="T", contrarian_stance="bullish",
                consensus_stance="bearish", contrarian_authors=["a"],
                consensus_author_count=10, strength=1.01,
            )

    def test_empty_contrarian_authors(self):
        with pytest.raises(ValueError, match="contrarian_authors must be non-empty"):
            ContrarianSignal(
                id="x", ticker="T", contrarian_stance="bullish",
                consensus_stance="bearish", contrarian_authors=[],
                consensus_author_count=10, strength=0.5,
            )
