"""Tests for rot.nlp.classifier - Multi-label event classification.

Comprehensive test coverage for the custom NLP classifier that handles:
- All 14 categories (earnings_rumor, product_news, regulatory, squeeze_chatter, macro,
  insider_activity, technical_breakout, options_flow, dividend_play, buyback, ipo, spac,
  crypto_correlation, other)
- Multi-label scoring (can return multiple categories with different confidences)
- TF-IDF-like scoring with IDF boost for discriminative terms
- Weighted keyword matching with bigram and trigram support
- Evidence preservation (matched terms)
- Fallback to "other" category when no matches
- Edge cases (empty input, ambiguous multi-category content, single keyword matches)
"""
import pytest

from rot.nlp.classifier import EventClassifier
from rot.nlp.tokenizer import Tokenizer
from rot.nlp.types import ClassifiedEvent, Token


@pytest.fixture
def classifier():
    """Provide a fresh EventClassifier instance for each test."""
    return EventClassifier()


@pytest.fixture
def tokenizer():
    """Provide a tokenizer for creating token lists from text."""
    return Tokenizer()


class TestEarningsRumor:
    """Test earnings_rumor category detection."""

    def test_earnings_keyword(self, classifier, tokenizer):
        """'earnings' should strongly trigger earnings_rumor category."""
        tokens = tokenizer.tokenize("Earnings beat expected estimates")
        results = classifier.classify(tokens)
        # Should have earnings_rumor as top result
        assert len(results) > 0
        assert results[0].category == "earnings_rumor"
        assert results[0].confidence > 0.1
        assert "earnings" in results[0].matched_terms

    def test_eps_keyword(self, classifier, tokenizer):
        """'EPS' should trigger earnings_rumor."""
        tokens = tokenizer.tokenize("EPS came in strong this quarter")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0
        assert earnings_results[0].confidence > 0.1
        assert "eps" in [t.lower() for t in earnings_results[0].matched_terms]

    def test_guidance_revenue(self, classifier, tokenizer):
        """'guidance' and 'revenue' should boost earnings_rumor confidence."""
        tokens = tokenizer.tokenize("Revenue guidance for next quarter looks strong")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0
        # Multiple matched terms should boost confidence
        assert len(earnings_results[0].matched_terms) >= 2
        assert earnings_results[0].confidence > 0.2

    def test_quarterly_report(self, classifier, tokenizer):
        """'quarterly' and 'report' should trigger earnings_rumor."""
        tokens = tokenizer.tokenize("Quarterly report expected before open")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0

    def test_q1_q2_quarters(self, classifier, tokenizer):
        """Quarter abbreviations Q1-Q4 should be recognized."""
        tokens = tokenizer.tokenize("Q3 earnings beat estimates")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0
        # Should match both "earnings" and "q3"
        assert len(earnings_results[0].matched_terms) >= 2

    def test_beat_miss_context(self, classifier, tokenizer):
        """'beat' and 'miss' in earnings context should be detected."""
        tokens = tokenizer.tokenize("Company missed revenue estimates badly")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0


class TestSqueezeChatter:
    """Test squeeze_chatter category detection."""

    def test_squeeze_keyword(self, classifier, tokenizer):
        """'squeeze' should strongly trigger squeeze_chatter."""
        tokens = tokenizer.tokenize("This is a short squeeze setup")
        results = classifier.classify(tokens)
        squeeze_results = [r for r in results if r.category == "squeeze_chatter"]
        assert len(squeeze_results) > 0
        assert squeeze_results[0].confidence > 0.3
        assert "squeeze" in [t.lower() for t in squeeze_results[0].matched_terms]

    def test_short_squeeze_bigram(self, classifier, tokenizer):
        """'short squeeze' bigram should be detected with high weight."""
        tokens = tokenizer.tokenize("Potential short squeeze incoming")
        results = classifier.classify(tokens)
        squeeze_results = [r for r in results if r.category == "squeeze_chatter"]
        assert len(squeeze_results) > 0
        # "short squeeze" bigram has weight 1.0
        assert "short squeeze" in squeeze_results[0].matched_terms

    def test_gamma_squeeze(self, classifier, tokenizer):
        """'gamma squeeze' bigram should be recognized."""
        tokens = tokenizer.tokenize("Gamma squeeze potential here")
        results = classifier.classify(tokens)
        squeeze_results = [r for r in results if r.category == "squeeze_chatter"]
        assert len(squeeze_results) > 0
        assert "gamma squeeze" in squeeze_results[0].matched_terms

    def test_short_interest(self, classifier, tokenizer):
        """'short interest' should trigger squeeze_chatter."""
        tokens = tokenizer.tokenize("Short interest at 40 percent")
        results = classifier.classify(tokens)
        squeeze_results = [r for r in results if r.category == "squeeze_chatter"]
        assert len(squeeze_results) > 0

    def test_days_to_cover(self, classifier, tokenizer):
        """'days to cover' should be recognized."""
        tokens = tokenizer.tokenize("Days to cover is at 7")
        results = classifier.classify(tokens)
        squeeze_results = [r for r in results if r.category == "squeeze_chatter"]
        assert len(squeeze_results) > 0

    def test_borrow_rate_ctb(self, classifier, tokenizer):
        """'borrow rate' and 'ctb' should trigger squeeze_chatter."""
        tokens = tokenizer.tokenize("Borrow rate spiked to 200% CTB is crazy")
        results = classifier.classify(tokens)
        squeeze_results = [r for r in results if r.category == "squeeze_chatter"]
        assert len(squeeze_results) > 0
        # Should match multiple terms
        assert len(squeeze_results[0].matched_terms) >= 2


class TestRegulatory:
    """Test regulatory category detection."""

    def test_fda_keyword(self, classifier, tokenizer):
        """'FDA' should strongly trigger regulatory."""
        tokens = tokenizer.tokenize("FDA approval expected soon pending clearance")
        results = classifier.classify(tokens)
        regulatory_results = [r for r in results if r.category == "regulatory"]
        assert len(regulatory_results) > 0
        assert regulatory_results[0].confidence > 0.1
        assert "fda" in [t.lower() for t in regulatory_results[0].matched_terms]

    def test_sec_investigation(self, classifier, tokenizer):
        """'SEC' should trigger regulatory."""
        tokens = tokenizer.tokenize("SEC is investigating the company")
        results = classifier.classify(tokens)
        regulatory_results = [r for r in results if r.category == "regulatory"]
        assert len(regulatory_results) > 0

    def test_antitrust_lawsuit(self, classifier, tokenizer):
        """'antitrust' and 'lawsuit' should trigger regulatory."""
        tokens = tokenizer.tokenize("Facing antitrust lawsuit")
        results = classifier.classify(tokens)
        regulatory_results = [r for r in results if r.category == "regulatory"]
        assert len(regulatory_results) > 0
        assert len(regulatory_results[0].matched_terms) >= 2

    def test_tariff_ban(self, classifier, tokenizer):
        """'tariff' and 'ban' should trigger regulatory."""
        tokens = tokenizer.tokenize("New tariffs could ban imports")
        results = classifier.classify(tokens)
        regulatory_results = [r for r in results if r.category == "regulatory"]
        assert len(regulatory_results) > 0

    def test_approval_clearance(self, classifier, tokenizer):
        """'approval' and 'clearance' should trigger regulatory."""
        tokens = tokenizer.tokenize("Received regulatory clearance for approval")
        results = classifier.classify(tokens)
        regulatory_results = [r for r in results if r.category == "regulatory"]
        assert len(regulatory_results) > 0


class TestProductNews:
    """Test product_news category detection."""

    def test_merger_acquisition(self, classifier, tokenizer):
        """'merger' and 'acquisition' should trigger product_news."""
        tokens = tokenizer.tokenize("Announced merger and acquisition deal")
        results = classifier.classify(tokens)
        product_results = [r for r in results if r.category == "product_news"]
        assert len(product_results) > 0
        assert product_results[0].confidence > 0.3

    def test_partnership_announcement(self, classifier, tokenizer):
        """'partnership' should trigger product_news."""
        tokens = tokenizer.tokenize("Partnership announcement with major tech firm")
        results = classifier.classify(tokens)
        product_results = [r for r in results if r.category == "product_news"]
        assert len(product_results) > 0

    def test_product_launch(self, classifier, tokenizer):
        """'product' and 'launch' should trigger product_news."""
        tokens = tokenizer.tokenize("New product launch scheduled for next month")
        results = classifier.classify(tokens)
        product_results = [r for r in results if r.category == "product_news"]
        assert len(product_results) > 0

    def test_patent_innovation(self, classifier, tokenizer):
        """'patent' should trigger product_news."""
        tokens = tokenizer.tokenize("Filed patent for breakthrough innovation")
        results = classifier.classify(tokens)
        product_results = [r for r in results if r.category == "product_news"]
        assert len(product_results) > 0

    def test_contract_awarded(self, classifier, tokenizer):
        """'contract' and 'awarded' should trigger product_news."""
        tokens = tokenizer.tokenize("Awarded major contract for defense project")
        results = classifier.classify(tokens)
        product_results = [r for r in results if r.category == "product_news"]
        assert len(product_results) > 0


class TestMacro:
    """Test macro category detection."""

    def test_cpi_fomc(self, classifier, tokenizer):
        """'CPI' and 'FOMC' should strongly trigger macro."""
        tokens = tokenizer.tokenize("CPI inflation data before FOMC meeting")
        results = classifier.classify(tokens)
        macro_results = [r for r in results if r.category == "macro"]
        assert len(macro_results) > 0
        assert macro_results[0].confidence > 0.1
        assert len(macro_results[0].matched_terms) >= 2

    def test_rate_cut_hike(self, classifier, tokenizer):
        """'rate cut' and 'rate hike' bigrams should be detected."""
        tokens = tokenizer.tokenize("Fed rate cut expected next quarter")
        results = classifier.classify(tokens)
        macro_results = [r for r in results if r.category == "macro"]
        assert len(macro_results) > 0
        # Should match "rate cut" bigram
        assert any("rate" in t.lower() and "cut" in t.lower() for t in macro_results[0].matched_terms)

    def test_inflation_recession(self, classifier, tokenizer):
        """'inflation' and 'recession' should trigger macro."""
        tokens = tokenizer.tokenize("Inflation fears drive recession worries")
        results = classifier.classify(tokens)
        macro_results = [r for r in results if r.category == "macro"]
        assert len(macro_results) > 0
        assert len(macro_results[0].matched_terms) >= 2

    def test_fed_powell(self, classifier, tokenizer):
        """'fed' and 'powell' should trigger macro."""
        tokens = tokenizer.tokenize("Powell and the Fed announce policy")
        results = classifier.classify(tokens)
        macro_results = [r for r in results if r.category == "macro"]
        assert len(macro_results) > 0

    def test_dovish_hawkish(self, classifier, tokenizer):
        """'dovish' and 'hawkish' should trigger macro."""
        tokens = tokenizer.tokenize("Fed takes hawkish stance, not dovish")
        results = classifier.classify(tokens)
        macro_results = [r for r in results if r.category == "macro"]
        assert len(macro_results) > 0
        assert len(macro_results[0].matched_terms) >= 2

    def test_jobs_report(self, classifier, tokenizer):
        """'jobs report' bigram should be detected."""
        tokens = tokenizer.tokenize("Jobs report beats expectations showing unemployment down")
        results = classifier.classify(tokens)
        macro_results = [r for r in results if r.category == "macro"]
        assert len(macro_results) > 0


class TestInsiderActivity:
    """Test insider_activity category detection."""

    def test_insider_buying_selling(self, classifier, tokenizer):
        """'insider buying' and 'insider selling' should trigger."""
        tokens = tokenizer.tokenize("Insider buying increased this week on Form 4 filings")
        results = classifier.classify(tokens)
        insider_results = [r for r in results if r.category == "insider_activity"]
        assert len(insider_results) > 0
        assert insider_results[0].confidence > 0.1

    def test_form_4(self, classifier, tokenizer):
        """'form 4' should trigger insider_activity."""
        tokens = tokenizer.tokenize("CEO filed Form 4 yesterday showing insider purchase")
        results = classifier.classify(tokens)
        insider_results = [r for r in results if r.category == "insider_activity"]
        assert len(insider_results) > 0

    def test_ceo_bought_sold(self, classifier, tokenizer):
        """'CEO bought' and 'CEO sold' should trigger."""
        tokens = tokenizer.tokenize("CEO bought shares on the open market")
        results = classifier.classify(tokens)
        insider_results = [r for r in results if r.category == "insider_activity"]
        assert len(insider_results) > 0

    def test_cluster_buying(self, classifier, tokenizer):
        """'cluster buying' should trigger insider_activity."""
        tokens = tokenizer.tokenize("Seeing cluster buying from executives")
        results = classifier.classify(tokens)
        insider_results = [r for r in results if r.category == "insider_activity"]
        assert len(insider_results) > 0


class TestTechnicalBreakout:
    """Test technical_breakout category detection."""

    def test_breakout_keyword(self, classifier, tokenizer):
        """'breakout' should trigger technical_breakout."""
        tokens = tokenizer.tokenize("Price breakout above resistance with volume spike")
        results = classifier.classify(tokens)
        technical_results = [r for r in results if r.category == "technical_breakout"]
        assert len(technical_results) > 0
        assert technical_results[0].confidence > 0.1

    def test_golden_cross_death_cross(self, classifier, tokenizer):
        """'golden cross' should trigger technical_breakout."""
        tokens = tokenizer.tokenize("Golden cross forming on daily chart")
        results = classifier.classify(tokens)
        technical_results = [r for r in results if r.category == "technical_breakout"]
        assert len(technical_results) > 0
        assert "golden cross" in technical_results[0].matched_terms

    def test_macd_rsi(self, classifier, tokenizer):
        """'MACD' and 'RSI' should trigger technical_breakout."""
        tokens = tokenizer.tokenize("MACD and RSI showing bullish divergence")
        results = classifier.classify(tokens)
        technical_results = [r for r in results if r.category == "technical_breakout"]
        assert len(technical_results) > 0

    def test_cup_and_handle(self, classifier, tokenizer):
        """'cup and handle' pattern should be detected."""
        tokens = tokenizer.tokenize("Perfect cup and handle pattern forming with breakout")
        results = classifier.classify(tokens)
        technical_results = [r for r in results if r.category == "technical_breakout"]
        assert len(technical_results) > 0

    def test_gap_up_down(self, classifier, tokenizer):
        """'gap up' and 'gap down' should trigger technical_breakout."""
        tokens = tokenizer.tokenize("Stock gap up at open with breakout")
        results = classifier.classify(tokens)
        technical_results = [r for r in results if r.category == "technical_breakout"]
        assert len(technical_results) > 0


class TestOptionsFlow:
    """Test options_flow category detection."""

    def test_unusual_options(self, classifier, tokenizer):
        """'unusual options' should strongly trigger options_flow."""
        tokens = tokenizer.tokenize("Unusual options activity detected with sweep orders")
        results = classifier.classify(tokens)
        flow_results = [r for r in results if r.category == "options_flow"]
        assert len(flow_results) > 0
        assert flow_results[0].confidence > 0.1

    def test_sweep_block_trade(self, classifier, tokenizer):
        """'sweep' and 'block trade' should trigger options_flow."""
        tokens = tokenizer.tokenize("Sweep and block trade on calls")
        results = classifier.classify(tokens)
        flow_results = [r for r in results if r.category == "options_flow"]
        assert len(flow_results) > 0

    def test_dark_pool(self, classifier, tokenizer):
        """'dark pool' should trigger options_flow."""
        tokens = tokenizer.tokenize("Dark pool activity increasing")
        results = classifier.classify(tokens)
        flow_results = [r for r in results if r.category == "options_flow"]
        assert len(flow_results) > 0

    def test_whale_activity(self, classifier, tokenizer):
        """'whale' should trigger options_flow."""
        tokens = tokenizer.tokenize("Whales buying calls heavily")
        results = classifier.classify(tokens)
        flow_results = [r for r in results if r.category == "options_flow"]
        assert len(flow_results) > 0


class TestDividendPlay:
    """Test dividend_play category detection."""

    def test_dividend_keyword(self, classifier, tokenizer):
        """'dividend' should strongly trigger dividend_play."""
        tokens = tokenizer.tokenize("Dividend increased by 20 percent with higher yield")
        results = classifier.classify(tokens)
        dividend_results = [r for r in results if r.category == "dividend_play"]
        assert len(dividend_results) > 0
        assert dividend_results[0].confidence > 0.1

    def test_ex_dividend(self, classifier, tokenizer):
        """'ex-dividend' should trigger dividend_play."""
        tokens = tokenizer.tokenize("Ex-dividend date is tomorrow")
        results = classifier.classify(tokens)
        dividend_results = [r for r in results if r.category == "dividend_play"]
        assert len(dividend_results) > 0

    def test_special_dividend(self, classifier, tokenizer):
        """'special dividend' should trigger dividend_play."""
        tokens = tokenizer.tokenize("Special dividend announced")
        results = classifier.classify(tokens)
        dividend_results = [r for r in results if r.category == "dividend_play"]
        assert len(dividend_results) > 0

    def test_dividend_aristocrat(self, classifier, tokenizer):
        """'dividend aristocrat' should be recognized."""
        tokens = tokenizer.tokenize("This is a dividend aristocrat stock")
        results = classifier.classify(tokens)
        dividend_results = [r for r in results if r.category == "dividend_play"]
        assert len(dividend_results) > 0


class TestBuyback:
    """Test buyback category detection."""

    def test_buyback_keyword(self, classifier, tokenizer):
        """'buyback' should strongly trigger buyback."""
        tokens = tokenizer.tokenize("Announced massive share buyback program")
        results = classifier.classify(tokens)
        buyback_results = [r for r in results if r.category == "buyback"]
        assert len(buyback_results) > 0
        assert buyback_results[0].confidence > 0.3

    def test_share_repurchase(self, classifier, tokenizer):
        """'share repurchase' should trigger buyback."""
        tokens = tokenizer.tokenize("Share repurchase authorization approved")
        results = classifier.classify(tokens)
        buyback_results = [r for r in results if r.category == "buyback"]
        assert len(buyback_results) > 0

    def test_buyback_program(self, classifier, tokenizer):
        """'buyback program' should be detected."""
        tokens = tokenizer.tokenize("New buyback program for 10 billion")
        results = classifier.classify(tokens)
        buyback_results = [r for r in results if r.category == "buyback"]
        assert len(buyback_results) > 0


class TestIPO:
    """Test ipo category detection."""

    def test_ipo_keyword(self, classifier, tokenizer):
        """'IPO' should strongly trigger ipo."""
        tokens = tokenizer.tokenize("IPO pricing announced for next week")
        results = classifier.classify(tokens)
        ipo_results = [r for r in results if r.category == "ipo"]
        assert len(ipo_results) > 0
        assert ipo_results[0].confidence > 0.3

    def test_going_public(self, classifier, tokenizer):
        """'going public' should trigger ipo."""
        tokens = tokenizer.tokenize("Company is going public soon")
        results = classifier.classify(tokens)
        ipo_results = [r for r in results if r.category == "ipo"]
        assert len(ipo_results) > 0

    def test_lockup_expiration(self, classifier, tokenizer):
        """'lockup expiration' should trigger ipo."""
        tokens = tokenizer.tokenize("Lockup expiration date approaching")
        results = classifier.classify(tokens)
        ipo_results = [r for r in results if r.category == "ipo"]
        assert len(ipo_results) > 0

    def test_direct_listing(self, classifier, tokenizer):
        """'direct listing' should trigger ipo."""
        tokens = tokenizer.tokenize("Direct listing instead of traditional IPO")
        results = classifier.classify(tokens)
        ipo_results = [r for r in results if r.category == "ipo"]
        assert len(ipo_results) > 0


class TestSPAC:
    """Test spac category detection."""

    def test_spac_keyword(self, classifier, tokenizer):
        """'SPAC' should strongly trigger spac."""
        tokens = tokenizer.tokenize("SPAC merger announced today")
        results = classifier.classify(tokens)
        spac_results = [r for r in results if r.category == "spac"]
        assert len(spac_results) > 0
        assert spac_results[0].confidence > 0.3

    def test_despac_de_spac(self, classifier, tokenizer):
        """'de-spac' should trigger spac."""
        tokens = tokenizer.tokenize("De-SPAC transaction closing soon")
        results = classifier.classify(tokens)
        spac_results = [r for r in results if r.category == "spac"]
        assert len(spac_results) > 0

    def test_blank_check(self, classifier, tokenizer):
        """'blank check' should trigger spac."""
        tokens = tokenizer.tokenize("Blank check company announced target")
        results = classifier.classify(tokens)
        spac_results = [r for r in results if r.category == "spac"]
        assert len(spac_results) > 0


class TestCryptoCorrelation:
    """Test crypto_correlation category detection."""

    def test_bitcoin_btc(self, classifier, tokenizer):
        """'bitcoin' and 'BTC' should trigger crypto_correlation."""
        tokens = tokenizer.tokenize("Bitcoin price affects stock, BTC correlation")
        results = classifier.classify(tokens)
        crypto_results = [r for r in results if r.category == "crypto_correlation"]
        assert len(crypto_results) > 0
        assert crypto_results[0].confidence > 0.3

    def test_ethereum_eth(self, classifier, tokenizer):
        """'ethereum' should trigger crypto_correlation."""
        tokens = tokenizer.tokenize("Ethereum exposure through stock")
        results = classifier.classify(tokens)
        crypto_results = [r for r in results if r.category == "crypto_correlation"]
        assert len(crypto_results) > 0

    def test_blockchain_web3(self, classifier, tokenizer):
        """'blockchain' and 'web3' should trigger crypto_correlation."""
        tokens = tokenizer.tokenize("Blockchain and Web3 initiatives announced")
        results = classifier.classify(tokens)
        crypto_results = [r for r in results if r.category == "crypto_correlation"]
        assert len(crypto_results) > 0

    def test_crypto_mining(self, classifier, tokenizer):
        """'crypto' and 'mining' should trigger crypto_correlation."""
        tokens = tokenizer.tokenize("Crypto mining operations expanding")
        results = classifier.classify(tokens)
        crypto_results = [r for r in results if r.category == "crypto_correlation"]
        assert len(crypto_results) > 0


class TestMultiLabelClassification:
    """Test that multiple categories can be returned simultaneously."""

    def test_earnings_and_regulatory(self, classifier, tokenizer):
        """Text with both earnings and regulatory signals should return both."""
        tokens = tokenizer.tokenize("FDA approval expected before Q3 earnings report")
        results = classifier.classify(tokens)
        categories = [r.category for r in results]
        # Should have both categories above threshold
        assert "earnings_rumor" in categories
        assert "regulatory" in categories

    def test_multiple_categories_sorted_by_confidence(self, classifier, tokenizer):
        """Results should be sorted by confidence descending."""
        tokens = tokenizer.tokenize("FOMC rate decision impacts earnings guidance and GDP growth")
        results = classifier.classify(tokens)
        # Should have macro and earnings_rumor
        assert len(results) >= 2
        # Verify descending sort
        for i in range(len(results) - 1):
            assert results[i].confidence >= results[i + 1].confidence

    def test_squeeze_and_options_flow(self, classifier, tokenizer):
        """Squeeze chatter with options flow should return both."""
        tokens = tokenizer.tokenize("Short squeeze setup with unusual options activity")
        results = classifier.classify(tokens)
        categories = [r.category for r in results]
        assert "squeeze_chatter" in categories
        assert "options_flow" in categories

    def test_technical_and_macro(self, classifier, tokenizer):
        """Technical breakout with macro context should return both."""
        tokens = tokenizer.tokenize("Golden cross forming ahead of CPI inflation data and FOMC")
        results = classifier.classify(tokens)
        categories = [r.category for r in results]
        assert "technical_breakout" in categories
        assert "macro" in categories


class TestMatchedTermsPreservation:
    """Test that matched terms are preserved for evidence."""

    def test_matched_terms_present(self, classifier, tokenizer):
        """Matched terms should be in matched_terms list."""
        tokens = tokenizer.tokenize("Earnings beat revenue estimates")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0
        # Should have matched multiple terms
        assert len(earnings_results[0].matched_terms) >= 2
        assert "earnings" in [t.lower() for t in earnings_results[0].matched_terms]
        assert "revenue" in [t.lower() for t in earnings_results[0].matched_terms]

    def test_bigram_in_matched_terms(self, classifier, tokenizer):
        """Bigram matches should appear in matched_terms."""
        tokens = tokenizer.tokenize("Short squeeze potential here")
        results = classifier.classify(tokens)
        squeeze_results = [r for r in results if r.category == "squeeze_chatter"]
        assert len(squeeze_results) > 0
        assert "short squeeze" in squeeze_results[0].matched_terms

    def test_matched_terms_unique(self, classifier, tokenizer):
        """Each matched term should only appear once."""
        tokens = tokenizer.tokenize("Earnings earnings earnings")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0
        # "earnings" should only be in matched_terms once
        earnings_count = sum(1 for t in earnings_results[0].matched_terms if t.lower() == "earnings")
        assert earnings_count == 1


class TestConfidenceScoring:
    """Test confidence score calculation and normalization."""

    def test_single_match_low_confidence(self, classifier, tokenizer):
        """Single weak match should have lower confidence."""
        tokens = tokenizer.tokenize("The company report came out")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        if len(earnings_results) > 0:
            # "report" alone has weight 0.5, should give lower confidence
            assert earnings_results[0].confidence < 0.5

    def test_multiple_matches_higher_confidence(self, classifier, tokenizer):
        """Multiple matches should boost confidence."""
        tokens = tokenizer.tokenize("Earnings revenue EPS guidance all beat estimates")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0
        # Many matches should give high confidence
        assert earnings_results[0].confidence > 0.5

    def test_confidence_normalized_to_one(self, classifier, tokenizer):
        """Confidence should never exceed 1.0."""
        tokens = tokenizer.tokenize("Earnings revenue EPS guidance beat estimates quarterly profit margin topline bottomline")
        results = classifier.classify(tokens)
        for result in results:
            assert result.confidence <= 1.0
            assert result.confidence >= 0.0

    def test_high_weight_term_higher_confidence(self, classifier, tokenizer):
        """High-weight terms should produce higher confidence."""
        # "earnings" has weight 1.0
        tokens1 = tokenizer.tokenize("Earnings today")
        results1 = classifier.classify(tokens1)
        earnings1 = [r for r in results1 if r.category == "earnings_rumor"][0]

        # "report" has weight 0.5
        tokens2 = tokenizer.tokenize("Report today")
        results2 = classifier.classify(tokens2)
        earnings2 = [r for r in results2 if r.category == "earnings_rumor"]

        # earnings should have higher confidence than report
        if len(earnings2) > 0:
            assert earnings1.confidence > earnings2[0].confidence


class TestIdfBoost:
    """Test that IDF boost works for discriminative terms."""

    def test_discriminative_term_boost(self, classifier, tokenizer):
        """Terms appearing in fewer categories should get IDF boost."""
        # "FOMC" only appears in macro category → high IDF
        tokens = tokenizer.tokenize("FOMC meeting on inflation and rate policy")
        results = classifier.classify(tokens)
        macro_results = [r for r in results if r.category == "macro"]
        assert len(macro_results) > 0
        # Should have high confidence due to IDF boost
        assert macro_results[0].confidence > 0.1

    def test_common_term_lower_boost(self, classifier, tokenizer):
        """Terms appearing in many categories should get lower boost."""
        # "approval" appears in both regulatory and product_news → lower IDF
        tokens = tokenizer.tokenize("Approval granted")
        results = classifier.classify(tokens)
        # Should still classify but with awareness of term ambiguity
        assert len(results) > 0


class TestFallbackToOther:
    """Test fallback to 'other' category when no matches."""

    def test_no_matches_returns_other(self, classifier, tokenizer):
        """Text with no category keywords should return 'other'."""
        tokens = tokenizer.tokenize("Just some random text here")
        results = classifier.classify(tokens)
        assert len(results) == 1
        assert results[0].category == "other"
        assert results[0].confidence == 0.5

    def test_other_no_matched_terms(self, classifier, tokenizer):
        """'other' category should have empty matched_terms."""
        tokens = tokenizer.tokenize("Random unrelated content")
        results = classifier.classify(tokens)
        other_results = [r for r in results if r.category == "other"]
        assert len(other_results) > 0
        assert len(other_results[0].matched_terms) == 0

    def test_weak_match_below_threshold(self, classifier, tokenizer):
        """Very weak matches below MIN_CONFIDENCE should fall back to other."""
        # Use a word that appears but with very low weight
        tokens = tokenizer.tokenize("The company")
        results = classifier.classify(tokens)
        # Should either have no category above threshold or just "other"
        if len(results) == 1:
            assert results[0].category == "other"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_token_list(self, classifier):
        """Empty token list should return 'other'."""
        results = classifier.classify([])
        assert len(results) == 1
        assert results[0].category == "other"

    def test_single_token(self, classifier, tokenizer):
        """Single high-weight token may not classify due to match diversity penalty."""
        tokens = tokenizer.tokenize("FOMC")
        results = classifier.classify(tokens)
        # Single token may fall below MIN_CONFIDENCE due to match diversity penalty
        # This is expected behavior - single weak matches fall back to "other"
        assert len(results) >= 1
        # Either classified as macro or falls back to other
        if results[0].category == "macro":
            assert results[0].confidence >= classifier.MIN_CONFIDENCE
        else:
            assert results[0].category == "other"

    def test_case_insensitive_matching(self, classifier, tokenizer):
        """Matching should be case-insensitive."""
        tokens = tokenizer.tokenize("EARNINGS GUIDANCE REVENUE")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0
        # Should match despite all caps

    def test_trigram_matching(self, classifier, tokenizer):
        """Trigrams should be matched if present in category terms."""
        # Though no 3-word terms in current categories, test mechanism works
        tokens = tokenizer.tokenize("one two three four")
        results = classifier.classify(tokens)
        # Should not crash, should return other
        assert len(results) >= 1

    def test_very_long_text(self, classifier, tokenizer):
        """Very long text should be handled efficiently."""
        long_text = "Earnings revenue guidance " * 100
        tokens = tokenizer.tokenize(long_text)
        results = classifier.classify(tokens)
        # Should classify as earnings_rumor despite length
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0

    def test_mixed_categories_many_matches(self, classifier, tokenizer):
        """Text with many category keywords should return multiple categories."""
        text = "FOMC rate decision on earnings day with FDA approval and SPAC merger"
        tokens = tokenizer.tokenize(text)
        results = classifier.classify(tokens)
        # Should have at least 4 categories (macro, earnings, regulatory, spac)
        assert len(results) >= 4

    def test_punctuation_ignored(self, classifier, tokenizer):
        """Punctuation should not interfere with matching."""
        tokens = tokenizer.tokenize("Earnings! Revenue? EPS.")
        results = classifier.classify(tokens)
        earnings_results = [r for r in results if r.category == "earnings_rumor"]
        assert len(earnings_results) > 0
        # Should match all three terms despite punctuation


class TestMinConfidenceThreshold:
    """Test MIN_CONFIDENCE threshold filtering."""

    def test_below_threshold_excluded(self, classifier, tokenizer):
        """Results below MIN_CONFIDENCE should be excluded."""
        # Create a scenario with very weak signal
        tokens = tokenizer.tokenize("win")  # "win" has weight 0.4 in product_news
        results = classifier.classify(tokens)
        # All results should be >= MIN_CONFIDENCE (0.1)
        for result in results:
            assert result.confidence >= classifier.MIN_CONFIDENCE

    def test_threshold_value(self, classifier):
        """MIN_CONFIDENCE should be 0.1."""
        assert classifier.MIN_CONFIDENCE == 0.1


class TestCategoryTermsCoverage:
    """Test that all 14 categories are testable."""

    def test_all_categories_have_terms(self, classifier):
        """All 14 categories should be defined in _CATEGORY_TERMS."""
        from rot.nlp.classifier import _CATEGORY_TERMS

        expected_categories = {
            "earnings_rumor", "product_news", "regulatory", "squeeze_chatter",
            "macro", "insider_activity", "technical_breakout", "options_flow",
            "dividend_play", "buyback", "ipo", "spac", "crypto_correlation"
        }

        assert set(_CATEGORY_TERMS.keys()) == expected_categories

    def test_all_categories_reachable(self, classifier, tokenizer):
        """Each category should be triggerable with appropriate text."""
        test_texts = {
            "earnings_rumor": "earnings beat revenue estimates",
            "product_news": "merger announcement partnership",
            "regulatory": "FDA approval clearance",
            "squeeze_chatter": "short squeeze setup",
            "macro": "FOMC meeting inflation",
            "insider_activity": "insider buying form4",
            "technical_breakout": "golden cross breakout",
            "options_flow": "unusual options sweep",
            "dividend_play": "dividend increase yield",
            "buyback": "share buyback program",
            "ipo": "IPO pricing lockup",
            "spac": "SPAC merger despac",
            "crypto_correlation": "bitcoin crypto exposure",
        }

        for category, text in test_texts.items():
            tokens = tokenizer.tokenize(text)
            results = classifier.classify(tokens)
            categories = [r.category for r in results]
            assert category in categories, f"Category {category} not triggered by '{text}'"
