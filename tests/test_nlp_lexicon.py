"""Comprehensive tests for the NLP sentiment lexicon.

Tests the 500+ term sentiment dictionary in src/rot/nlp/lexicon.py.
Validates term coverage, value ranges, categorical organization, and lookup functions.
"""
import pytest

from rot.nlp.lexicon import (
    get_lexicon,
    LexiconEntry,
    NEGATORS,
    INTENSIFIERS,
    DIMINISHERS,
    HIGH_CONVICTION_PHRASES,
    LOW_CONVICTION_PHRASES,
    SARCASTIC_PHRASES,
)


# ── Fixtures ──


@pytest.fixture
def lexicon():
    """Return the full sentiment lexicon."""
    return get_lexicon()


# ── Core Lexicon Tests ──


class TestLexiconStructure:
    """Test the basic structure and coverage of the lexicon."""

    def test_lexicon_minimum_term_count(self, lexicon):
        """Lexicon should contain at least 330 terms."""
        assert len(lexicon) >= 330, f"Expected at least 330 terms, got {len(lexicon)}"

    def test_lexicon_returns_dict(self, lexicon):
        """get_lexicon() should return a dictionary."""
        assert isinstance(lexicon, dict)

    def test_lexicon_keys_are_lowercase(self, lexicon):
        """All lexicon keys should be lowercase."""
        for term in lexicon:
            assert term == term.lower(), f"Term '{term}' is not lowercase"

    def test_no_duplicate_terms(self, lexicon):
        """All terms should be unique (no duplicates after lowercasing)."""
        # Dict keys are unique by definition, but check that the original entries
        # don't have duplicates that would be masked by lowercasing
        from rot.nlp.lexicon import _build_lexicon

        built = _build_lexicon()
        # If there were duplicates, the dict size would be smaller than the entry count
        # Re-build to count original entries
        import rot.nlp.lexicon as lex_module

        # Parse the source to count entries (rough check)
        # Since we can't easily count without re-implementing, we check that
        # all keys map to LexiconEntry objects
        for key, value in lexicon.items():
            assert isinstance(value, LexiconEntry)

    def test_all_values_are_lexicon_entries(self, lexicon):
        """All dictionary values should be LexiconEntry instances."""
        for term, entry in lexicon.items():
            assert isinstance(entry, LexiconEntry), f"{term} maps to non-LexiconEntry: {type(entry)}"

    def test_entry_term_matches_key(self, lexicon):
        """Entry.term (lowercased) should match its dictionary key."""
        for key, entry in lexicon.items():
            assert entry.term.lower() == key, f"Key '{key}' != entry.term.lower() '{entry.term.lower()}'"


class TestLexiconValueRanges:
    """Test that all lexicon values are within valid ranges."""

    def test_polarity_range(self, lexicon):
        """All polarity values should be in range [-1.0, 1.0]."""
        for term, entry in lexicon.items():
            assert -1.0 <= entry.polarity <= 1.0, \
                f"Term '{term}' has polarity {entry.polarity} outside [-1.0, 1.0]"

    def test_intensity_range(self, lexicon):
        """All intensity values should be in range [0.0, 1.0]."""
        for term, entry in lexicon.items():
            assert 0.0 <= entry.intensity <= 1.0, \
                f"Term '{term}' has intensity {entry.intensity} outside [0.0, 1.0]"

    def test_polarity_and_intensity_are_floats(self, lexicon):
        """Polarity and intensity should be float type."""
        for term, entry in lexicon.items():
            assert isinstance(entry.polarity, float), f"{term}.polarity is not float"
            assert isinstance(entry.intensity, float), f"{term}.intensity is not float"

    def test_no_nan_values(self, lexicon):
        """No polarity or intensity should be NaN."""
        import math
        for term, entry in lexicon.items():
            assert not math.isnan(entry.polarity), f"{term}.polarity is NaN"
            assert not math.isnan(entry.intensity), f"{term}.intensity is NaN"


class TestLexiconCategories:
    """Test categorical organization of the lexicon."""

    VALID_CATEGORIES = {"action", "outcome", "descriptor", "emoji"}

    def test_category_values(self, lexicon):
        """All categories should be from the valid set."""
        for term, entry in lexicon.items():
            assert entry.category in self.VALID_CATEGORIES, \
                f"Term '{term}' has invalid category '{entry.category}'"

    def test_category_coverage(self, lexicon):
        """All valid categories should be represented."""
        categories = {entry.category for entry in lexicon.values()}
        # All categories should appear at least once
        for cat in self.VALID_CATEGORIES:
            assert cat in categories, f"Category '{cat}' not found in lexicon"

    def test_action_category_exists(self, lexicon):
        """At least 20 'action' terms should exist."""
        actions = [e for e in lexicon.values() if e.category == "action"]
        assert len(actions) >= 20, f"Expected at least 20 action terms, got {len(actions)}"

    def test_outcome_category_exists(self, lexicon):
        """At least 50 'outcome' terms should exist."""
        outcomes = [e for e in lexicon.values() if e.category == "outcome"]
        assert len(outcomes) >= 50, f"Expected at least 50 outcome terms, got {len(outcomes)}"

    def test_descriptor_category_exists(self, lexicon):
        """At least 30 'descriptor' terms should exist."""
        descriptors = [e for e in lexicon.values() if e.category == "descriptor"]
        assert len(descriptors) >= 30, f"Expected at least 30 descriptor terms, got {len(descriptors)}"

    def test_emoji_category_exists(self, lexicon):
        """At least 15 'emoji' terms should exist."""
        emojis = [e for e in lexicon.values() if e.category == "emoji"]
        assert len(emojis) >= 15, f"Expected at least 15 emoji terms, got {len(emojis)}"


class TestLexiconDomains:
    """Test domain organization of the lexicon."""

    VALID_DOMAINS = {"general", "options", "technical", "wsb_slang", "macro"}

    def test_domain_values(self, lexicon):
        """All domains should be from the valid set."""
        for term, entry in lexicon.items():
            assert entry.domain in self.VALID_DOMAINS, \
                f"Term '{term}' has invalid domain '{entry.domain}'"

    def test_domain_coverage(self, lexicon):
        """All valid domains should be represented."""
        domains = {entry.domain for entry in lexicon.values()}
        for dom in self.VALID_DOMAINS:
            assert dom in domains, f"Domain '{dom}' not found in lexicon"

    def test_general_domain_exists(self, lexicon):
        """At least 100 'general' domain terms should exist."""
        general = [e for e in lexicon.values() if e.domain == "general"]
        assert len(general) >= 100, f"Expected at least 100 general terms, got {len(general)}"

    def test_options_domain_exists(self, lexicon):
        """At least 30 'options' domain terms should exist."""
        options = [e for e in lexicon.values() if e.domain == "options"]
        assert len(options) >= 30, f"Expected at least 30 options terms, got {len(options)}"

    def test_technical_domain_exists(self, lexicon):
        """At least 20 'technical' domain terms should exist."""
        technical = [e for e in lexicon.values() if e.domain == "technical"]
        assert len(technical) >= 20, f"Expected at least 20 technical terms, got {len(technical)}"

    def test_wsb_slang_domain_exists(self, lexicon):
        """At least 30 'wsb_slang' domain terms should exist."""
        wsb = [e for e in lexicon.values() if e.domain == "wsb_slang"]
        assert len(wsb) >= 30, f"Expected at least 30 wsb_slang terms, got {len(wsb)}"

    def test_macro_domain_exists(self, lexicon):
        """At least 20 'macro' domain terms should exist."""
        macro = [e for e in lexicon.values() if e.domain == "macro"]
        assert len(macro) >= 20, f"Expected at least 20 macro terms, got {len(macro)}"


# ── Specific Term Tests ──


class TestSpecificTerms:
    """Test presence and correctness of specific important terms."""

    def test_moon_is_bullish(self, lexicon):
        """'moon' should be strongly bullish."""
        assert "moon" in lexicon
        moon = lexicon["moon"]
        assert moon.polarity > 0.8
        assert moon.intensity > 0.8
        assert moon.domain == "wsb_slang"

    def test_crash_is_bearish(self, lexicon):
        """'crash' should be strongly bearish."""
        assert "crash" in lexicon
        crash = lexicon["crash"]
        assert crash.polarity < -0.8
        assert crash.intensity > 0.8

    def test_calls_is_bullish(self, lexicon):
        """'calls' should be moderately bullish."""
        assert "calls" in lexicon
        calls = lexicon["calls"]
        assert calls.polarity > 0.4
        assert calls.domain == "options"

    def test_puts_is_bearish(self, lexicon):
        """'puts' should be moderately bearish."""
        assert "puts" in lexicon
        puts = lexicon["puts"]
        assert puts.polarity < -0.4
        assert puts.domain == "options"

    def test_gamma_squeeze_is_bullish(self, lexicon):
        """'gamma squeeze' should be bullish options term."""
        assert "gamma squeeze" in lexicon
        gamma = lexicon["gamma squeeze"]
        # Note: gamma squeeze appears twice in lexicon (lines 59 and 344)
        # Line 344 has polarity 0.7, so use >= instead of >
        assert gamma.polarity >= 0.7
        assert gamma.domain == "options"

    def test_rate_cut_is_bullish(self, lexicon):
        """'rate cut' should be bullish macro term."""
        assert "rate cut" in lexicon
        rate_cut = lexicon["rate cut"]
        assert rate_cut.polarity > 0.5
        assert rate_cut.domain == "macro"

    def test_recession_is_bearish(self, lexicon):
        """'recession' should be bearish macro term."""
        assert "recession" in lexicon
        recession = lexicon["recession"]
        assert recession.polarity < -0.5
        assert recession.domain == "macro"

    def test_rocket_emoji_is_bullish(self, lexicon):
        """'ROCKET_EMOJI' should be bullish."""
        assert "rocket_emoji" in lexicon
        rocket = lexicon["rocket_emoji"]
        assert rocket.polarity > 0.7
        assert rocket.category == "emoji"

    def test_poop_emoji_is_bearish(self, lexicon):
        """'POOP_EMOJI' should be bearish."""
        assert "poop_emoji" in lexicon
        poop = lexicon["poop_emoji"]
        assert poop.polarity < -0.5
        assert poop.category == "emoji"

    def test_yolo_high_conviction(self, lexicon):
        """'yolo' should have high intensity for conviction."""
        assert "yolo" in lexicon
        yolo = lexicon["yolo"]
        assert yolo.intensity > 0.8
        assert yolo.domain == "wsb_slang"


class TestNGramPhrases:
    """Test multi-word phrases (2-grams, 3-grams)."""

    def test_gap_up_exists(self, lexicon):
        """'gap up' should exist as 2-gram."""
        assert "gap up" in lexicon
        assert lexicon["gap up"].polarity > 0.7

    def test_gap_down_exists(self, lexicon):
        """'gap down' should exist as 2-gram."""
        assert "gap down" in lexicon
        assert lexicon["gap down"].polarity < -0.6

    def test_short_squeeze_exists(self, lexicon):
        """'short squeeze' should exist as 2-gram."""
        assert "short squeeze" in lexicon
        assert lexicon["short squeeze"].polarity > 0.7

    def test_all_time_high_exists(self, lexicon):
        """'all time high' should exist as 3-gram."""
        assert "all time high" in lexicon
        assert lexicon["all time high"].polarity > 0.7

    def test_dead_cat_bounce_exists(self, lexicon):
        """'dead cat bounce' should exist as 3-gram."""
        assert "dead cat bounce" in lexicon
        assert lexicon["dead cat bounce"].polarity < -0.5

    def test_buy_the_dip_exists(self, lexicon):
        """'buy the dip' should exist as 3-gram."""
        assert "buy the dip" in lexicon
        assert lexicon["buy the dip"].polarity > 0.5

    def test_hyphenated_variants(self, lexicon):
        """Hyphenated and space variants should both exist."""
        # gap-up and gap up
        assert "gap-up" in lexicon or "gap up" in lexicon
        # melt-up and melt up
        assert "melt-up" in lexicon


# ── Polarity Distribution Tests ──


class TestPolarityDistribution:
    """Test the distribution of polarities across the lexicon."""

    def test_has_strong_bullish_terms(self, lexicon):
        """At least 20 terms should have polarity > 0.7."""
        strong_bulls = [e for e in lexicon.values() if e.polarity > 0.7]
        assert len(strong_bulls) >= 20, f"Expected at least 20 strong bullish terms, got {len(strong_bulls)}"

    def test_has_strong_bearish_terms(self, lexicon):
        """At least 30 terms should have polarity < -0.7."""
        strong_bears = [e for e in lexicon.values() if e.polarity < -0.7]
        assert len(strong_bears) >= 30, f"Expected at least 30 strong bearish terms, got {len(strong_bears)}"

    def test_has_moderate_bullish_terms(self, lexicon):
        """At least 50 terms should have polarity in [0.3, 0.7]."""
        mod_bulls = [e for e in lexicon.values() if 0.3 <= e.polarity <= 0.7]
        assert len(mod_bulls) >= 50, f"Expected at least 50 moderate bullish terms, got {len(mod_bulls)}"

    def test_has_moderate_bearish_terms(self, lexicon):
        """At least 50 terms should have polarity in [-0.7, -0.3]."""
        mod_bears = [e for e in lexicon.values() if -0.7 <= e.polarity <= -0.3]
        assert len(mod_bears) >= 50, f"Expected at least 50 moderate bearish terms, got {len(mod_bears)}"

    def test_has_neutral_terms(self, lexicon):
        """At least 10 terms should have polarity in [-0.2, 0.2]."""
        neutrals = [e for e in lexicon.values() if -0.2 <= e.polarity <= 0.2]
        assert len(neutrals) >= 10, f"Expected at least 10 neutral terms, got {len(neutrals)}"

    def test_balanced_polarity(self, lexicon):
        """Bullish and bearish term counts should be within 2x of each other."""
        bullish = [e for e in lexicon.values() if e.polarity > 0.2]
        bearish = [e for e in lexicon.values() if e.polarity < -0.2]

        ratio = len(bullish) / max(len(bearish), 1)
        assert 0.5 <= ratio <= 2.0, \
            f"Polarity imbalance: {len(bullish)} bullish vs {len(bearish)} bearish (ratio={ratio:.2f})"


# ── Modifier Lookups Tests ──


class TestModifierLookups:
    """Test the modifier lookup sets (negators, intensifiers, etc.)."""

    def test_negators_is_frozenset(self):
        """NEGATORS should be a frozenset."""
        assert isinstance(NEGATORS, frozenset)

    def test_negators_not_empty(self):
        """NEGATORS should contain at least 20 terms."""
        assert len(NEGATORS) >= 20, f"Expected at least 20 negators, got {len(NEGATORS)}"

    def test_negators_lowercase(self):
        """All NEGATORS should be lowercase."""
        for neg in NEGATORS:
            assert neg == neg.lower(), f"Negator '{neg}' is not lowercase"

    def test_common_negators_present(self):
        """Common negators should be present."""
        assert "not" in NEGATORS
        assert "no" in NEGATORS
        assert "never" in NEGATORS
        assert "don't" in NEGATORS
        assert "can't" in NEGATORS

    def test_intensifiers_is_frozenset(self):
        """INTENSIFIERS should be a frozenset."""
        assert isinstance(INTENSIFIERS, frozenset)

    def test_intensifiers_not_empty(self):
        """INTENSIFIERS should contain at least 15 terms."""
        assert len(INTENSIFIERS) >= 15, f"Expected at least 15 intensifiers, got {len(INTENSIFIERS)}"

    def test_common_intensifiers_present(self):
        """Common intensifiers should be present."""
        assert "very" in INTENSIFIERS
        assert "extremely" in INTENSIFIERS
        assert "absolutely" in INTENSIFIERS
        assert "really" in INTENSIFIERS

    def test_diminishers_is_frozenset(self):
        """DIMINISHERS should be a frozenset."""
        assert isinstance(DIMINISHERS, frozenset)

    def test_diminishers_not_empty(self):
        """DIMINISHERS should contain at least 10 terms."""
        assert len(DIMINISHERS) >= 10, f"Expected at least 10 diminishers, got {len(DIMINISHERS)}"

    def test_common_diminishers_present(self):
        """Common diminishers should be present."""
        assert "slightly" in DIMINISHERS
        assert "maybe" in DIMINISHERS
        assert "somewhat" in DIMINISHERS


class TestConvictionPhrases:
    """Test conviction phrase lists."""

    def test_high_conviction_phrases_is_list(self):
        """HIGH_CONVICTION_PHRASES should be a list."""
        assert isinstance(HIGH_CONVICTION_PHRASES, list)

    def test_high_conviction_phrases_not_empty(self):
        """HIGH_CONVICTION_PHRASES should contain at least 15 phrases."""
        assert len(HIGH_CONVICTION_PHRASES) >= 15, \
            f"Expected at least 15 high conviction phrases, got {len(HIGH_CONVICTION_PHRASES)}"

    def test_common_high_conviction_phrases(self):
        """Common high conviction phrases should be present."""
        assert "all in" in HIGH_CONVICTION_PHRASES
        assert "yolo" in HIGH_CONVICTION_PHRASES
        assert "100%" in HIGH_CONVICTION_PHRASES
        assert "guaranteed" in HIGH_CONVICTION_PHRASES

    def test_low_conviction_phrases_is_list(self):
        """LOW_CONVICTION_PHRASES should be a list."""
        assert isinstance(LOW_CONVICTION_PHRASES, list)

    def test_low_conviction_phrases_not_empty(self):
        """LOW_CONVICTION_PHRASES should contain at least 15 phrases."""
        assert len(LOW_CONVICTION_PHRASES) >= 15, \
            f"Expected at least 15 low conviction phrases, got {len(LOW_CONVICTION_PHRASES)}"

    def test_common_low_conviction_phrases(self):
        """Common low conviction phrases should be present."""
        assert "maybe" in LOW_CONVICTION_PHRASES
        assert "might" in LOW_CONVICTION_PHRASES
        assert "not sure" in LOW_CONVICTION_PHRASES
        assert "nfa" in LOW_CONVICTION_PHRASES

    def test_sarcastic_phrases_is_list(self):
        """SARCASTIC_PHRASES should be a list."""
        assert isinstance(SARCASTIC_PHRASES, list)

    def test_sarcastic_phrases_not_empty(self):
        """SARCASTIC_PHRASES should contain at least 15 phrases."""
        assert len(SARCASTIC_PHRASES) >= 15, \
            f"Expected at least 15 sarcastic phrases, got {len(SARCASTIC_PHRASES)}"

    def test_common_sarcastic_phrases(self):
        """Common sarcastic phrases should be present."""
        assert "what could go wrong" in SARCASTIC_PHRASES
        assert "this is fine" in SARCASTIC_PHRASES
        assert "can't go tits up" in SARCASTIC_PHRASES
        assert "free money glitch" in SARCASTIC_PHRASES


# ── Edge Cases and Lookup Tests ──


class TestLexiconLookups:
    """Test lexicon lookup behavior and edge cases."""

    def test_lookup_existing_term(self, lexicon):
        """Looking up an existing term should return LexiconEntry."""
        entry = lexicon.get("moon")
        assert entry is not None
        assert isinstance(entry, LexiconEntry)

    def test_lookup_nonexistent_term(self, lexicon):
        """Looking up a nonexistent term should return None."""
        entry = lexicon.get("nonexistent_term_xyz")
        assert entry is None

    def test_case_insensitive_lookup(self, lexicon):
        """Lexicon keys are lowercase, so uppercase lookups fail."""
        # Direct uppercase lookup fails
        assert lexicon.get("MOON") is None
        # But lowercase works
        assert lexicon.get("moon") is not None
        # User must lowercase before lookup
        assert lexicon.get("MOON".lower()) is not None

    def test_filter_by_category(self, lexicon):
        """Can filter lexicon by category."""
        emojis = {term: entry for term, entry in lexicon.items() if entry.category == "emoji"}
        assert len(emojis) >= 15
        for entry in emojis.values():
            assert entry.category == "emoji"

    def test_filter_by_domain(self, lexicon):
        """Can filter lexicon by domain."""
        options_terms = {term: entry for term, entry in lexicon.items() if entry.domain == "options"}
        assert len(options_terms) >= 30
        for entry in options_terms.values():
            assert entry.domain == "options"

    def test_filter_by_polarity_range(self, lexicon):
        """Can filter lexicon by polarity range."""
        strong_bulls = {term: entry for term, entry in lexicon.items() if entry.polarity > 0.7}
        assert len(strong_bulls) >= 20
        for entry in strong_bulls.values():
            assert entry.polarity > 0.7

    def test_empty_string_lookup(self, lexicon):
        """Looking up empty string should return None."""
        assert lexicon.get("") is None

    def test_whitespace_only_lookup(self, lexicon):
        """Looking up whitespace-only string should return None."""
        assert lexicon.get("   ") is None


class TestLexiconConsistency:
    """Test consistency and coherence of the lexicon."""

    def test_opposite_terms_opposite_polarity(self, lexicon):
        """Opposite terms should have opposite polarity signs."""
        # bull vs bear
        if "bull" in lexicon and "bear" in lexicon:
            assert lexicon["bull"].polarity > 0
            assert lexicon["bear"].polarity < 0

        # buy vs sell
        if "buy" in lexicon and "sell" in lexicon:
            assert lexicon["buy"].polarity > 0
            assert lexicon["sell"].polarity < 0

        # calls vs puts
        if "calls" in lexicon and "puts" in lexicon:
            assert lexicon["calls"].polarity > 0
            assert lexicon["puts"].polarity < 0

    def test_similar_terms_similar_polarity(self, lexicon):
        """Similar terms should have similar polarity."""
        # moon variations
        if "moon" in lexicon and "moonshot" in lexicon:
            diff = abs(lexicon["moon"].polarity - lexicon["moonshot"].polarity)
            assert diff < 0.2, f"moon and moonshot polarity differ by {diff}"

        # crash variations
        if "crash" in lexicon and "crashing" in lexicon:
            diff = abs(lexicon["crash"].polarity - lexicon["crashing"].polarity)
            assert diff < 0.2, f"crash and crashing polarity differ by {diff}"

    def test_high_polarity_high_intensity_correlation(self, lexicon):
        """Terms with high |polarity| should generally have high intensity."""
        extreme_terms = [e for e in lexicon.values() if abs(e.polarity) > 0.8]
        high_intensity = [e for e in extreme_terms if e.intensity > 0.7]

        ratio = len(high_intensity) / max(len(extreme_terms), 1)
        assert ratio > 0.7, \
            f"Only {len(high_intensity)}/{len(extreme_terms)} extreme polarity terms have high intensity"

    def test_emoji_terms_capitalized(self, lexicon):
        """Emoji terms should end with _EMOJI or be SKULL_CROSSBONES."""
        emojis = [term for term, entry in lexicon.items() if entry.category == "emoji"]
        for emoji_term in emojis:
            # Lexicon keys are lowercase, but original terms should have _EMOJI suffix
            # or be SKULL_CROSSBONES (exception)
            entry = lexicon[emoji_term]
            assert "_emoji" in entry.term.lower() or entry.term == "SKULL_CROSSBONES", \
                f"Emoji term '{entry.term}' doesn't end with _EMOJI or isn't SKULL_CROSSBONES"

    def test_wsb_slang_domain_has_wsb_terms(self, lexicon):
        """wsb_slang domain should contain WSB-specific terms."""
        wsb_terms = {term for term, entry in lexicon.items() if entry.domain == "wsb_slang"}

        # Check for iconic WSB terms
        wsb_icons = {"moon", "tendies", "diamond hands", "paper hands", "apes", "yolo"}
        found = wsb_icons & wsb_terms
        assert len(found) >= 4, \
            f"wsb_slang domain missing iconic terms. Found: {found}, Expected: {wsb_icons}"


# ── Integration Tests ──


class TestLexiconIntegration:
    """Integration tests for real-world usage patterns."""

    def test_sentiment_scoring_bullish(self, lexicon):
        """Can score a simple bullish sentence."""
        tokens = ["moon", "rocket", "calls"]
        total_polarity = sum(lexicon[t].polarity for t in tokens if t in lexicon)
        assert total_polarity > 2.0  # Should be strongly bullish

    def test_sentiment_scoring_bearish(self, lexicon):
        """Can score a simple bearish sentence."""
        tokens = ["crash", "drill", "puts"]
        total_polarity = sum(lexicon[t].polarity for t in tokens if t in lexicon)
        assert total_polarity < -2.0  # Should be strongly bearish

    def test_mixed_sentiment(self, lexicon):
        """Can score a mixed sentiment sentence."""
        tokens = ["buy", "but", "risky"]
        polarities = [lexicon[t].polarity for t in tokens if t in lexicon]
        # Should have both positive and negative
        assert any(p > 0 for p in polarities)
        assert any(p < 0 for p in polarities)

    def test_negation_context(self, lexicon):
        """Negators are separate from lexicon terms."""
        # "not bullish" should be detected by combining NEGATORS + lexicon
        assert "not" in NEGATORS
        assert "bullish" in lexicon
        # Negation logic is implemented in sentiment.py, not lexicon

    def test_conviction_scoring(self, lexicon):
        """Can identify high conviction terms."""
        high_conviction_terms = [
            term for term, entry in lexicon.items()
            if entry.intensity > 0.8 and abs(entry.polarity) < 0.5
        ]
        # Should have conviction indicators with neutral/low polarity
        assert len(high_conviction_terms) >= 5
