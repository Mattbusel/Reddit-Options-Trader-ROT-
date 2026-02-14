"""Tests for rot.reasoner.reasoner module.

Tests LLM reasoning path, stub fallback, circuit breaker, informational source
handling, and prompt validation.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict
from unittest.mock import AsyncMock, Mock, patch

import pytest

from rot.core.types import Event, Evidence, ReasoningPacket
from rot.reasoner.reasoner import Reasoner


def _make_event(
    entities: list[str] = None,
    event_type: str = "other",
    stance: str = "unknown",
    confidence: float = 0.3,
    **meta_overrides,
) -> Event:
    """Helper to construct test events."""
    if entities is None:
        entities = ["TSLA"]

    meta: Dict[str, Any] = {
        "trend_score": 0.5,
        "features": {"score_rate": 0.1, "comment_rate": 0.2},
        "score": 50,
        "num_comments": 10,
        "upvote_ratio": 0.85,
        "author": "testuser",
        "flair": None,
        "is_crosspost": False,
        "body_excerpt": "Some test content",
        "market": {},
    }
    meta.update(meta_overrides)

    evidence = [
        Evidence(
            post_id="test123",
            permalink="https://reddit.com/r/test/test123",
            subreddit="wallstreetbets",
            excerpt="Test post about TSLA",
        )
    ]

    return Event(
        event_type=event_type,
        entities=entities,
        stance=stance,
        time_horizon="unknown",
        evidence=evidence,
        confidence=confidence,
        meta=meta,
    )


class TestReasonerInitialization:
    """Test Reasoner initialization and API key validation."""

    def test_init_with_valid_api_key(self):
        """Valid API key should initialize LLM client."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_instance = Mock()
            mock_instance.available = True
            mock_client_cls.return_value = mock_instance

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
                model="gpt-4o-mini",
            )

            assert reasoner.llm_available is True
            assert reasoner._llm is mock_instance
            mock_client_cls.assert_called_once()

    def test_init_with_placeholder_api_key(self):
        """Placeholder API keys should be rejected."""
        for placeholder in ["your_api_key", "sk-...", "test", "changeme", ""]:
            reasoner = Reasoner(provider="openai", api_key=placeholder)
            assert reasoner.llm_available is False
            assert reasoner._llm is None

    def test_init_with_short_api_key(self):
        """API keys under 20 chars should be rejected."""
        reasoner = Reasoner(provider="openai", api_key="short")
        assert reasoner.llm_available is False
        assert reasoner._llm is None

    def test_init_with_no_api_key(self):
        """Missing API key should result in no LLM client."""
        reasoner = Reasoner(provider="openai", api_key="")
        assert reasoner.llm_available is False
        assert reasoner._llm is None

    def test_init_with_unavailable_client(self):
        """If LLMClient.available is False, reasoner should disable LLM."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_instance = Mock()
            mock_instance.available = False
            mock_client_cls.return_value = mock_instance

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            assert reasoner.llm_available is False
            assert reasoner._llm is None

    def test_init_with_client_exception(self):
        """If LLMClient init raises, reasoner should disable LLM."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client_cls.side_effect = Exception("API error")

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            assert reasoner.llm_available is False
            assert reasoner._llm is None

    def test_init_passes_all_params_to_client(self):
        """All initialization params should be forwarded to LLMClient."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_instance = Mock()
            mock_instance.available = True
            mock_client_cls.return_value = mock_instance

            Reasoner(
                provider="anthropic",
                api_key="sk-ant-validkey123456789012345678901234567890",
                model="claude-3-haiku-20240307",
                base_url="https://custom.api.com",
                max_tokens=2048,
                temperature=0.7,
            )

            mock_client_cls.assert_called_once_with(
                provider="anthropic",
                api_key="sk-ant-validkey123456789012345678901234567890",
                model="claude-3-haiku-20240307",
                base_url="https://custom.api.com",
                max_tokens=2048,
                temperature=0.7,
            )


class TestReasonerLLMPath:
    """Test LLM reasoning path when LLM is available."""

    def test_llm_reason_sends_system_and_user_prompt(self):
        """LLM reasoning should send both system and user prompts."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.return_value = """{
                "event_type": "product_news",
                "stance": "bullish",
                "time_horizon": "1w",
                "confidence": 0.65,
                "thesis": "New product launch expected to drive revenue",
                "catalyst_window": "within 1 week",
                "market_expectation": "market is underpricing the catalyst",
                "invalidations": ["Product delayed", "Competitor announcement"],
                "recommended_structures": ["bull call spread 5-10% OTM"],
                "risk_notes": ["Earnings in 2 weeks may shift IV"]
            }"""
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            event = _make_event()
            result = reasoner.reason(event)

            # Verify complete() was called
            assert mock_client.complete.call_count == 1
            call_args = mock_client.complete.call_args[0]

            # Verify system prompt
            system_prompt = call_args[0]
            assert "options trading analyst" in system_prompt.lower()
            assert "valid JSON" in system_prompt

            # Verify user prompt
            user_prompt = call_args[1]
            assert "TSLA" in user_prompt
            assert "wallstreetbets" in user_prompt

            # Verify result
            assert isinstance(result, ReasoningPacket)
            assert result.thesis == "New product launch expected to drive revenue"

    def test_llm_reason_parses_json_response(self):
        """LLM response should be parsed into ReasoningPacket."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.return_value = """{
                "event_type": "squeeze_chatter",
                "stance": "bullish",
                "time_horizon": "intraday",
                "confidence": 0.35,
                "thesis": "High short interest could trigger squeeze",
                "catalyst_window": "next trading session",
                "market_expectation": "elevated IV already pricing some risk",
                "invalidations": ["Short interest data is stale", "No volume spike"],
                "recommended_structures": ["OTM calls (lottery ticket)", "defined risk spreads"],
                "risk_notes": ["Pure speculation", "Most squeezes fail"]
            }"""
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            event = _make_event(entities=["GME"])
            result = reasoner.reason(event)

            assert result.thesis == "High short interest could trigger squeeze"
            assert result.catalyst_window == "next trading session"
            assert result.market_expectation == "elevated IV already pricing some risk"
            assert len(result.invalidations) == 2
            assert len(result.recommended_structures) == 2
            assert len(result.risk_notes) == 2
            assert result.raw["confidence"] == 0.35
            assert result.raw["stance"] == "bullish"

    def test_llm_reason_includes_market_data_in_prompt(self):
        """Market data should be included in the user prompt."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.return_value = """{
                "event_type": "other",
                "stance": "bullish",
                "time_horizon": "1w",
                "confidence": 0.5,
                "thesis": "Test",
                "catalyst_window": "unknown",
                "market_expectation": "unclear",
                "invalidations": ["None"],
                "recommended_structures": ["none"],
                "risk_notes": ["Test"]
            }"""
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            market_data = {
                "TSLA": {
                    "last_close": 250.5,
                    "pct_1d": 0.025,
                    "market_cap": 800_000_000_000,
                    "atm_iv": 0.65,
                    "pc_ratio": 1.2,
                }
            }

            event = _make_event(market=market_data)
            reasoner.reason(event)

            # Check that market data appears in user prompt
            user_prompt = mock_client.complete.call_args[0][1]
            assert "250.5" in user_prompt or "250" in user_prompt
            assert "2.5%" in user_prompt or "2.50%" in user_prompt
            assert "65.0%" in user_prompt or "65%" in user_prompt

    def test_llm_reason_includes_nlp_data_in_prompt(self):
        """NLP analysis should be included in the user prompt."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.return_value = """{
                "event_type": "other",
                "stance": "bullish",
                "time_horizon": "1w",
                "confidence": 0.5,
                "thesis": "Test",
                "catalyst_window": "unknown",
                "market_expectation": "unclear",
                "invalidations": ["None"],
                "recommended_structures": ["none"],
                "risk_notes": ["Test"]
            }"""
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            nlp_data = {
                "polarity": 0.8,
                "intensity": 0.9,
                "conviction": 0.75,
                "sarcasm_probability": 0.1,
                "classifications": [("product_news", 0.85), ("bullish", 0.7)],
                "tense": "future",
                "actionability": 0.8,
                "urgency": 0.6,
            }

            event = _make_event(nlp=nlp_data)
            reasoner.reason(event)

            # Check that NLP data appears in user prompt
            user_prompt = mock_client.complete.call_args[0][1]
            assert "NLP Analysis" in user_prompt
            assert "0.80" in user_prompt or "polarity" in user_prompt
            assert "future" in user_prompt

    def test_llm_reason_resets_consecutive_failures_on_success(self):
        """Successful LLM call should reset failure counter."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.return_value = """{
                "event_type": "other",
                "stance": "bullish",
                "time_horizon": "1w",
                "confidence": 0.5,
                "thesis": "Test",
                "catalyst_window": "unknown",
                "market_expectation": "unclear",
                "invalidations": ["None"],
                "recommended_structures": ["none"],
                "risk_notes": ["Test"]
            }"""
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            # Simulate previous failures
            reasoner._consecutive_failures = 2

            event = _make_event()
            reasoner.reason(event)

            # Should reset to 0
            assert reasoner._consecutive_failures == 0

    def test_llm_reason_handles_malformed_json(self):
        """Malformed JSON should trigger fallback to stub reasoning."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.return_value = "This is not JSON at all!"
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            event = _make_event(entities=["AAPL"])
            result = reasoner.reason(event)

            # Should fall back to stub
            assert "Reddit chatter mentions AAPL" in result.thesis
            assert "LLM parse failed" in result.thesis
            assert "error" in result.raw

    def test_llm_reason_handles_incomplete_json(self):
        """Incomplete JSON fields should be handled gracefully."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            # Missing some required fields
            mock_client.complete.return_value = """{
                "stance": "bullish",
                "confidence": 0.6
            }"""
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            event = _make_event()
            result = reasoner.reason(event)

            # Parser should fill in defaults
            assert isinstance(result, ReasoningPacket)
            assert result.thesis is not None
            assert result.catalyst_window is not None


class TestReasonerStubPath:
    """Test stub reasoning fallback when LLM unavailable."""

    def test_stub_reason_when_no_llm(self):
        """When LLM unavailable, should return stub reasoning."""
        reasoner = Reasoner(provider="openai", api_key="")
        assert reasoner.llm_available is False

        event = _make_event(entities=["NVDA", "AMD"])
        result = reasoner.reason(event)

        assert isinstance(result, ReasoningPacket)
        assert "Reddit chatter mentions NVDA, AMD" in result.thesis
        assert result.catalyst_window == "unknown"
        assert result.market_expectation == "unclear; watch implied volatility + liquidity"
        assert len(result.invalidations) > 0
        assert len(result.recommended_structures) > 0
        assert "LLM reasoning not available" in " ".join(result.risk_notes)
        assert result.raw.get("stub") is True

    def test_stub_reason_contains_entities(self):
        """Stub reasoning should mention all entities."""
        reasoner = Reasoner(provider="openai", api_key="")

        event = _make_event(entities=["SPY", "QQQ", "IWM"])
        result = reasoner.reason(event)

        assert "SPY, QQQ, IWM" in result.thesis

    def test_stub_reason_with_no_entities(self):
        """Stub reasoning should handle events with no entities."""
        reasoner = Reasoner(provider="openai", api_key="")

        event = _make_event(entities=[])
        result = reasoner.reason(event)

        assert "unknown tickers" in result.thesis

    def test_stub_provides_conservative_recommendations(self):
        """Stub reasoning should recommend conservative strategies."""
        reasoner = Reasoner(provider="openai", api_key="")

        event = _make_event()
        result = reasoner.reason(event)

        # Should recommend defined-risk strategies
        assert any("debit_spread" in s for s in result.recommended_structures)
        assert any("defined risk" in s for s in result.recommended_structures)


class TestReasonerCircuitBreaker:
    """Test circuit breaker functionality after consecutive failures."""

    def test_circuit_breaker_triggers_after_3_failures(self):
        """After 3 consecutive LLM failures, should disable LLM and use stub."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.side_effect = Exception("API error")
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            event = _make_event()

            # First failure
            result1 = reasoner.reason(event)
            assert reasoner._consecutive_failures == 1
            assert "Reddit chatter" in result1.thesis

            # Second failure
            result2 = reasoner.reason(event)
            assert reasoner._consecutive_failures == 2
            assert "Reddit chatter" in result2.thesis

            # Third failure - should trigger circuit breaker
            result3 = reasoner.reason(event)
            assert reasoner._consecutive_failures == 3
            assert "Reddit chatter" in result3.thesis

            # Fourth call - should use stub without trying LLM
            mock_client.complete.reset_mock()
            result4 = reasoner.reason(event)
            assert "Reddit chatter" in result4.thesis
            # Should NOT have called LLM
            assert mock_client.complete.call_count == 0

    def test_circuit_breaker_logs_warning_on_first_two_failures(self):
        """First two failures should log warnings."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.side_effect = Exception("API error")
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            with patch("rot.reasoner.reasoner.log") as mock_log:
                event = _make_event()

                reasoner.reason(event)
                assert mock_log.warning.call_count == 1
                # Check that warning message includes failure count
                call_args = mock_log.warning.call_args[0]
                assert call_args[0] == "LLM reasoning failed (%d/%d), using fallback: %s"
                assert call_args[1] == 1  # consecutive failures
                assert call_args[2] == 3  # max failures

                reasoner.reason(event)
                assert mock_log.warning.call_count == 2
                call_args = mock_log.warning.call_args[0]
                assert call_args[1] == 2  # consecutive failures
                assert call_args[2] == 3  # max failures

    def test_circuit_breaker_logs_error_on_third_failure(self):
        """Third failure should log error about disabling LLM."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.side_effect = Exception("API error")
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            with patch("rot.reasoner.reasoner.log") as mock_log:
                event = _make_event()

                # Trigger three failures
                reasoner.reason(event)
                reasoner.reason(event)
                reasoner.reason(event)

                # Third failure should log error
                assert mock_log.error.call_count == 1
                assert "disabled after" in str(mock_log.error.call_args).lower()

    def test_circuit_breaker_resets_on_success(self):
        """Successful call should reset circuit breaker."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client_cls.return_value = mock_client

            # First call fails
            mock_client.complete.side_effect = Exception("Temporary error")

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            event = _make_event()
            reasoner.reason(event)
            assert reasoner._consecutive_failures == 1

            # Second call succeeds
            mock_client.complete.side_effect = None
            mock_client.complete.return_value = """{
                "event_type": "other",
                "stance": "bullish",
                "time_horizon": "1w",
                "confidence": 0.5,
                "thesis": "Success",
                "catalyst_window": "unknown",
                "market_expectation": "unclear",
                "invalidations": ["None"],
                "recommended_structures": ["none"],
                "risk_notes": ["Test"]
            }"""

            result = reasoner.reason(event)
            assert reasoner._consecutive_failures == 0
            assert result.thesis == "Success"

    def test_circuit_breaker_handles_network_errors(self):
        """Network errors should trigger circuit breaker."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.side_effect = ConnectionError("Network unreachable")
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            event = _make_event()
            for _ in range(3):
                reasoner.reason(event)

            assert reasoner._consecutive_failures == 3

    def test_circuit_breaker_handles_rate_limit_errors(self):
        """Rate limit errors should trigger circuit breaker."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.side_effect = Exception("Rate limit exceeded")
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            event = _make_event()
            for _ in range(3):
                reasoner.reason(event)

            assert reasoner._consecutive_failures == 3


class TestReasonerInformationalSources:
    """Test handling of informational-only sources (FDA, DoD, pharma RSS).

    Note: The current implementation doesn't have special handling for
    informational sources in the Reasoner itself. This is typically
    handled upstream in the pipeline by skipping the reasoner stage entirely
    for informational sources.
    """

    def test_reasoner_processes_all_events_normally(self):
        """Reasoner processes all events the same way regardless of source."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.return_value = """{
                "event_type": "other",
                "stance": "unknown",
                "time_horizon": "unknown",
                "confidence": 0.3,
                "thesis": "Test",
                "catalyst_window": "unknown",
                "market_expectation": "unclear",
                "invalidations": ["None"],
                "recommended_structures": ["none"],
                "risk_notes": ["Test"]
            }"""
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            # Even if marked as informational, reasoner still processes it
            # (In practice, pipeline skips reasoner for informational sources)
            event = _make_event(informational_only=True)
            result = reasoner.reason(event)

            # Reasoner doesn't check informational_only flag
            assert isinstance(result, ReasoningPacket)

    def test_stub_reasoning_available_for_all_events(self):
        """Stub reasoning works for any event type."""
        reasoner = Reasoner(provider="openai", api_key="")

        event = _make_event(informational_only=True, confidence=0.8)
        result = reasoner.reason(event)

        assert result.raw.get("stub") is True
        assert "Reddit chatter" in result.thesis


class TestReasonerEdgeCases:
    """Test edge cases and error handling."""

    def test_reason_with_empty_evidence(self):
        """Event with no evidence should still work."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.return_value = """{
                "event_type": "other",
                "stance": "unknown",
                "time_horizon": "unknown",
                "confidence": 0.3,
                "thesis": "Test",
                "catalyst_window": "unknown",
                "market_expectation": "unclear",
                "invalidations": ["None"],
                "recommended_structures": ["none"],
                "risk_notes": ["Test"]
            }"""
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            event = dataclasses.replace(_make_event(), evidence=[])
            result = reasoner.reason(event)

            # Should handle gracefully
            assert isinstance(result, ReasoningPacket)
            user_prompt = mock_client.complete.call_args[0][1]
            assert "unknown" in user_prompt.lower()

    def test_reason_with_missing_meta_fields(self):
        """Missing meta fields should use defaults."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.return_value = """{
                "event_type": "other",
                "stance": "unknown",
                "time_horizon": "unknown",
                "confidence": 0.3,
                "thesis": "Test",
                "catalyst_window": "unknown",
                "market_expectation": "unclear",
                "invalidations": ["None"],
                "recommended_structures": ["none"],
                "risk_notes": ["Test"]
            }"""
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            # Event with minimal meta
            event = dataclasses.replace(_make_event(), meta={})
            result = reasoner.reason(event)

            assert isinstance(result, ReasoningPacket)

    def test_reason_with_none_meta(self):
        """None meta should be handled."""
        with patch("rot.reasoner.reasoner.LLMClient") as mock_client_cls:
            mock_client = Mock()
            mock_client.available = True
            mock_client.complete.return_value = """{
                "event_type": "other",
                "stance": "unknown",
                "time_horizon": "unknown",
                "confidence": 0.3,
                "thesis": "Test",
                "catalyst_window": "unknown",
                "market_expectation": "unclear",
                "invalidations": ["None"],
                "recommended_structures": ["none"],
                "risk_notes": ["Test"]
            }"""
            mock_client_cls.return_value = mock_client

            reasoner = Reasoner(
                provider="openai",
                api_key="sk-proj-validkey1234567890123456789012345678901234567890",
            )

            event = dataclasses.replace(_make_event(), meta=None)
            result = reasoner.reason(event)

            assert isinstance(result, ReasoningPacket)

    def test_reason_preserves_original_event(self):
        """Reasoning should not mutate the input event."""
        reasoner = Reasoner(provider="openai", api_key="")

        event = _make_event()
        original_meta = event.meta.copy() if event.meta else {}

        reasoner.reason(event)

        # Event should be unchanged
        assert event.meta == original_meta

    def test_multiple_reasoners_independent(self):
        """Multiple Reasoner instances should be independent."""
        reasoner1 = Reasoner(provider="openai", api_key="")
        reasoner2 = Reasoner(provider="openai", api_key="")

        # Set different failure counts
        reasoner1._consecutive_failures = 2
        reasoner2._consecutive_failures = 0

        assert reasoner1._consecutive_failures == 2
        assert reasoner2._consecutive_failures == 0
