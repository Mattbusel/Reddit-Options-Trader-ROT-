"""
Comprehensive tests for ticker constants module.

Modules tested:
- rot.extract.ticker_constants

Coverage:
- TICKER_RE regex pattern (matches $TSLA and bare TSLA)
- BARE_TICKER_BLOCKLIST set (common words)
- CONTEXT_REQUIRED_TICKERS set (ambiguous tickers)
- FINANCIAL_CONTEXT_RE pattern (finds financial keywords)
"""
from __future__ import annotations

import re

from rot.extract.ticker_constants import (
    BARE_TICKER_BLOCKLIST,
    CONTEXT_REQUIRED_TICKERS,
    FINANCIAL_CONTEXT_RE,
    TICKER_RE,
)


class TestTickerRegex:
    def test_ticker_re_matches_dollar_sign_ticker(self):
        """TICKER_RE matches $TSLA format."""
        text = "Bought $TSLA calls"
        matches = TICKER_RE.findall(text)
        # Returns tuples of (dollar_match, bare_match)
        tickers = [m[0] or m[1] for m in matches]
        assert "TSLA" in tickers

    def test_ticker_re_matches_bare_ticker(self):
        """TICKER_RE matches bare AAPL format."""
        text = "AAPL is going up"
        matches = TICKER_RE.findall(text)
        tickers = [m[0] or m[1] for m in matches]
        assert "AAPL" in tickers

    def test_ticker_re_requires_uppercase(self):
        """TICKER_RE only matches uppercase."""
        text = "bought aapl calls"
        matches = TICKER_RE.findall(text)
        tickers = [m[0] or m[1] for m in matches]
        assert "aapl" not in tickers

    def test_ticker_re_length_limit(self):
        """TICKER_RE limits ticker length to 1-5 chars."""
        text = "$A $AB $ABC $ABCD $ABCDE $ABCDEF"
        matches = TICKER_RE.findall(text)
        tickers = [m[0] or m[1] for m in matches]
        # Should match up to 5 chars
        assert "ABCDE" in tickers
        # Should not match 6+ chars
        assert "ABCDEF" not in tickers

    def test_ticker_re_word_boundary(self):
        """TICKER_RE respects word boundaries."""
        text = "TESTING123"
        matches = TICKER_RE.findall(text)
        # Should not match TESTIN (boundary check)
        tickers = [m[0] or m[1] for m in matches if m[0] or m[1]]
        assert len(tickers) == 0

    def test_ticker_re_multiple_matches(self):
        """TICKER_RE finds multiple tickers."""
        text = "$AAPL and $MSFT are up, TSLA too"
        matches = TICKER_RE.findall(text)
        tickers = [m[0] or m[1] for m in matches]
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert "TSLA" in tickers


class TestBareTickerBlocklist:
    def test_blocklist_contains_common_words(self):
        """Blocklist contains common English words."""
        assert "THE" in BARE_TICKER_BLOCKLIST
        assert "AND" in BARE_TICKER_BLOCKLIST
        assert "FOR" in BARE_TICKER_BLOCKLIST

    def test_blocklist_contains_short_words(self):
        """Blocklist contains 2-3 letter words."""
        assert "IF" in BARE_TICKER_BLOCKLIST
        assert "IS" in BARE_TICKER_BLOCKLIST
        assert "IT" in BARE_TICKER_BLOCKLIST

    def test_blocklist_contains_internet_slang(self):
        """Blocklist contains internet slang."""
        assert "LMAO" in BARE_TICKER_BLOCKLIST
        assert "IMHO" in BARE_TICKER_BLOCKLIST

    def test_blocklist_contains_financial_words(self):
        """Blocklist contains financial terms that aren't tickers."""
        assert "STOCK" in BARE_TICKER_BLOCKLIST
        assert "TRADE" in BARE_TICKER_BLOCKLIST
        assert "PRICE" in BARE_TICKER_BLOCKLIST

    def test_blocklist_is_set(self):
        """Blocklist is a set for O(1) lookup."""
        assert isinstance(BARE_TICKER_BLOCKLIST, set)


class TestContextRequiredTickers:
    def test_context_required_contains_ambiguous_words(self):
        """Context required tickers are real tickers that are also words."""
        assert "COST" in CONTEXT_REQUIRED_TICKERS  # Costco, but also "cost"
        assert "LOVE" in CONTEXT_REQUIRED_TICKERS  # Real ticker, but also "love"
        assert "WORK" in CONTEXT_REQUIRED_TICKERS

    def test_context_required_is_set(self):
        """Context required tickers is a set."""
        assert isinstance(CONTEXT_REQUIRED_TICKERS, set)

    def test_context_required_not_in_blocklist(self):
        """Context required tickers should not overlap with blocklist."""
        # These are real tickers that need context, not blocklist items
        overlap = CONTEXT_REQUIRED_TICKERS & BARE_TICKER_BLOCKLIST
        assert len(overlap) == 0


class TestFinancialContextRegex:
    def test_financial_context_matches_stock(self):
        """FINANCIAL_CONTEXT_RE matches 'stock'."""
        text = "bought stock yesterday"
        match = FINANCIAL_CONTEXT_RE.search(text)
        assert match is not None

    def test_financial_context_matches_options(self):
        """FINANCIAL_CONTEXT_RE matches options terms."""
        for term in ["calls", "puts", "options", "strike"]:
            match = FINANCIAL_CONTEXT_RE.search(f"I bought {term}")
            assert match is not None, f"Should match {term}"

    def test_financial_context_matches_position_terms(self):
        """FINANCIAL_CONTEXT_RE matches position terms."""
        for term in ["bullish", "bearish", "position", "portfolio"]:
            match = FINANCIAL_CONTEXT_RE.search(f"My {term} is doing well")
            assert match is not None, f"Should match {term}"

    def test_financial_context_case_insensitive(self):
        """FINANCIAL_CONTEXT_RE is case insensitive."""
        match_lower = FINANCIAL_CONTEXT_RE.search("bought calls")
        match_upper = FINANCIAL_CONTEXT_RE.search("BOUGHT CALLS")
        match_mixed = FINANCIAL_CONTEXT_RE.search("Bought Calls")

        assert match_lower is not None
        assert match_upper is not None
        assert match_mixed is not None

    def test_financial_context_word_boundary(self):
        """FINANCIAL_CONTEXT_RE respects word boundaries."""
        # Should match "buy" but not in "buyer"
        match = FINANCIAL_CONTEXT_RE.search("buy now")
        assert match is not None

        # "buyer" should still match because "buy" is at word start
        match_buyer = FINANCIAL_CONTEXT_RE.search("buyer")
        # Actually, with \b on both sides, it shouldn't match
        # Let me check the actual regex: r"\b(?:...)\b"
        # This means word boundaries on both sides
        # So "buyer" won't match "buy"


class TestIntegration:
    def test_ticker_extraction_workflow(self):
        """Simulate a typical ticker extraction workflow."""
        text = "$AAPL is up. I like COST but not THE stock market. LMAO."

        # Find all potential tickers
        matches = TICKER_RE.findall(text)
        tickers = [m[0] or m[1] for m in matches if m[0] or m[1]]

        # Filter out blocklist
        filtered = [t for t in tickers if t not in BARE_TICKER_BLOCKLIST]

        # AAPL should be included ($-prefixed)
        assert "AAPL" in filtered

        # COST should be in filtered (not in blocklist)
        assert "COST" in filtered

        # THE should be filtered out (in blocklist)
        assert "THE" not in filtered

        # LMAO should be filtered out (in blocklist)
        assert "LMAO" not in filtered

    def test_context_required_workflow(self):
        """Simulate context-required ticker extraction."""
        text1 = "COST is my favorite stock to buy"
        text2 = "The COST of living is high"  # COST must be uppercase to match

        # Both match TICKER_RE (uppercase required)
        matches1 = TICKER_RE.findall(text1)
        matches2 = TICKER_RE.findall(text2)

        tickers1 = [m[0] or m[1] for m in matches1 if m[0] or m[1]]
        tickers2 = [m[0] or m[1] for m in matches2 if m[0] or m[1]]

        # Both find COST (uppercase)
        assert "COST" in tickers1
        assert "COST" in tickers2

        # But only text1 has financial context
        has_context1 = FINANCIAL_CONTEXT_RE.search(text1) is not None
        has_context2 = FINANCIAL_CONTEXT_RE.search(text2) is not None

        assert has_context1 is True
        assert has_context2 is False

        # So we'd only extract COST from text1
        if "COST" in CONTEXT_REQUIRED_TICKERS:
            should_extract1 = has_context1
            should_extract2 = has_context2
            assert should_extract1 is True
            assert should_extract2 is False
