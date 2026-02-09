from __future__ import annotations

from rot.extract.event_builder import EventBuilder


class TestExtractEntities:
    def setup_method(self):
        self.builder = EventBuilder()

    def test_explicit_dollar_ticker(self):
        entities = self.builder.extract_entities("$TSLA calls printing", "")
        assert "TSLA" in entities

    def test_bare_ticker(self):
        entities = self.builder.extract_entities("AAPL is looking good", "")
        assert "AAPL" in entities

    def test_filters_non_equity_tokens(self):
        entities = self.builder.extract_entities("AI and CEO of WSB think GDP is up", "")
        assert "AI" not in entities
        assert "CEO" not in entities
        assert "WSB" not in entities
        assert "GDP" not in entities

    def test_alias_mapping(self):
        entities = self.builder.extract_entities("Closed SPXW $6875C", "")
        assert "^GSPC" in entities

    def test_max_five_entities(self):
        entities = self.builder.extract_entities(
            "$AAPL $TSLA $GOOGL $MSFT $AMZN $META $NVDA", ""
        )
        assert len(entities) <= 5

    def test_deduplication(self):
        entities = self.builder.extract_entities("$TSLA TSLA $TSLA", "")
        assert entities.count("TSLA") == 1

    def test_single_char_filtered(self):
        entities = self.builder.extract_entities("$A is cheap", "")
        assert "A" not in entities


class TestEventClassification:
    def setup_method(self):
        self.builder = EventBuilder()

    def test_earnings_detection(self):
        assert self.builder._classify_event_type("TSLA earnings report tomorrow") == "earnings_rumor"

    def test_squeeze_detection(self):
        assert self.builder._classify_event_type("GME short interest at 140%") == "squeeze_chatter"

    def test_regulatory_detection(self):
        assert self.builder._classify_event_type("FDA approval for MRNA vaccine") == "regulatory"

    def test_product_news_detection(self):
        assert self.builder._classify_event_type("AAPL launching new product") == "product_news"

    def test_macro_detection(self):
        assert self.builder._classify_event_type("CPI data coming in hot") == "macro"

    def test_other_fallback(self):
        assert self.builder._classify_event_type("random discussion about stuff") == "other"


class TestStanceDetection:
    def setup_method(self):
        self.builder = EventBuilder()

    def test_bullish(self):
        assert self.builder._detect_stance("TSLA to the moon! Buying calls") == "bullish"

    def test_bearish(self):
        assert self.builder._detect_stance("SPY is going to crash. Buying puts") == "bearish"

    def test_mixed(self):
        assert self.builder._detect_stance("Could moon or crash, buying calls and puts") == "mixed"

    def test_unknown(self):
        assert self.builder._detect_stance("Just a normal discussion") == "unknown"


class TestHorizonDetection:
    def setup_method(self):
        self.builder = EventBuilder()

    def test_intraday(self):
        assert self.builder._detect_horizon("0DTE calls expiring today") == "intraday"

    def test_weekly(self):
        assert self.builder._detect_horizon("Buying weeklies for friday") == "1w"

    def test_earnings(self):
        assert self.builder._detect_horizon("Playing the earnings report") == "earnings"

    def test_unknown(self):
        assert self.builder._detect_horizon("Long term hold") == "unknown"


class TestFromCandidate:
    def setup_method(self):
        self.builder = EventBuilder()

    def test_creates_event_with_tickers(self, sample_candidate):
        events = self.builder.from_candidate(sample_candidate)
        assert len(events) == 1
        ev = events[0]
        assert "TSLA" in ev.entities
        assert ev.event_type == "earnings_rumor"
        assert ev.stance == "bullish"
        assert ev.confidence > 0

    def test_returns_empty_for_no_tickers(self, sample_candidate):
        # Create a candidate with no tickers
        from rot.core.types import Post, ThreadSnapshot, TrendCandidate
        post = Post(
            id="xyz",
            created_utc=1700000000,
            subreddit="wallstreetbets",
            title="What are your moves tomorrow?",
            selftext="",
            url="",
            score=100,
            num_comments=50,
            upvote_ratio=0.9,
            author="test",
            permalink="",
        )
        snap = ThreadSnapshot(snapshot_ts=1700000100, post=post)
        c = TrendCandidate(
            key="test:xyz", window_s=1800,
            features={}, trend_score=0.5, reason="test", snapshot=snap,
        )
        events = self.builder.from_candidate(c)
        assert events == []

    def test_includes_post_metadata(self, sample_candidate):
        events = self.builder.from_candidate(sample_candidate)
        ev = events[0]
        assert "score" in ev.meta
        assert "num_comments" in ev.meta
        assert "flair" in ev.meta
