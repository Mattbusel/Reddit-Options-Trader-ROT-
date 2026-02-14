"""Tests for rot.reasoner.ai_summary module.

Tests AI summary generation, LLM fallback, batch processing, and rate limiting.
"""
from __future__ import annotations

import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, Mock, patch

import pytest

from rot.reasoner.ai_summary import (
    _SYSTEM_PROMPT,
    _USER_TEMPLATE,
    _build_heuristic_summary,
    backfill_ai_summaries,
    generate_ai_summary,
)


def _make_signal(
    ticker: str = "TSLA",
    stance: str = "bullish",
    event_type: str = "product_news",
    confidence: float = 0.65,
    **overrides,
) -> Dict[str, Any]:
    """Helper to construct test signal dictionaries."""
    signal = {
        "id": "sig_12345",
        "ticker": ticker,
        "stance": stance,
        "event_type": event_type,
        "confidence": confidence,
        "post_title": "Breaking news about the company",
        "subreddit": "wallstreetbets",
        "trade_idea": {
            "strategy": "bull_call_spread",
            "legs": [],
        },
        "reasoning": {
            "thesis": "Strong product launch expected to drive revenue growth over the next quarter.",
            "catalyst_window": "2-4 weeks",
            "market_expectation": "Market is underpricing the catalyst",
        },
    }
    signal.update(overrides)
    return signal


class TestBuildHeuristicSummary:
    """Test heuristic (rule-based) summary generation."""

    def test_heuristic_summary_with_full_data(self):
        """Full signal data should produce detailed summary."""
        signal = _make_signal()
        result = _build_heuristic_summary(signal)

        assert "Bullish" in result
        assert "$TSLA" in result
        assert "moderate" in result.lower() or "high" in result.lower()

    def test_heuristic_summary_includes_thesis(self):
        """If thesis is available, it should be included (truncated)."""
        signal = _make_signal(
            reasoning={
                "thesis": "This is a very long thesis that should be truncated because it exceeds the maximum length we want to display in the summary for brevity and readability purposes.",
            }
        )
        result = _build_heuristic_summary(signal)

        # Should include truncated thesis
        assert "This is a very long thesis" in result
        assert "..." in result
        # Should not include full thesis
        assert "for brevity and readability purposes" not in result

    def test_heuristic_summary_bullish_stance(self):
        """Bullish stance should be labeled clearly."""
        signal = _make_signal(stance="bullish")
        result = _build_heuristic_summary(signal)

        assert "Bullish" in result

    def test_heuristic_summary_bearish_stance(self):
        """Bearish stance should be labeled clearly."""
        signal = _make_signal(stance="bearish")
        result = _build_heuristic_summary(signal)

        assert "Bearish" in result

    def test_heuristic_summary_mixed_stance(self):
        """Mixed stance should be labeled clearly."""
        signal = _make_signal(stance="mixed")
        result = _build_heuristic_summary(signal)

        assert "Mixed" in result

    def test_heuristic_summary_high_confidence(self):
        """High confidence (>= 0.7) should be labeled."""
        signal = _make_signal(confidence=0.75)
        result = _build_heuristic_summary(signal)

        assert "high" in result.lower()

    def test_heuristic_summary_moderate_confidence(self):
        """Moderate confidence (0.5-0.7) should be labeled."""
        signal = _make_signal(confidence=0.6)
        result = _build_heuristic_summary(signal)

        assert "moderate" in result.lower()

    def test_heuristic_summary_low_confidence(self):
        """Low confidence (< 0.5) should be labeled."""
        signal = _make_signal(confidence=0.3)
        result = _build_heuristic_summary(signal)

        assert "low" in result.lower()

    def test_heuristic_summary_includes_event_type(self):
        """Event type should be incorporated into summary."""
        signal = _make_signal(event_type="earnings_rumor", reasoning={"thesis": ""})
        result = _build_heuristic_summary(signal)

        assert "earnings" in result.lower()

    def test_heuristic_summary_squeeze_chatter(self):
        """Squeeze chatter should be described appropriately."""
        signal = _make_signal(event_type="squeeze_chatter", reasoning={"thesis": ""})
        result = _build_heuristic_summary(signal)

        assert "squeeze" in result.lower()

    def test_heuristic_summary_regulatory_event(self):
        """Regulatory events should be labeled."""
        signal = _make_signal(event_type="regulatory", reasoning={"thesis": ""})
        result = _build_heuristic_summary(signal)

        assert "regulatory" in result.lower()

    def test_heuristic_summary_includes_strategy(self):
        """Strategy should be mentioned if available."""
        signal = _make_signal(
            trade_idea={"strategy": "iron_condor"},
            reasoning={"thesis": ""},
        )
        result = _build_heuristic_summary(signal)

        assert "iron condor" in result.lower()

    def test_heuristic_summary_handles_none_strategy(self):
        """Missing strategy should not break summary."""
        signal = _make_signal(trade_idea={"strategy": "none"}, reasoning={"thesis": ""})
        result = _build_heuristic_summary(signal)

        # Should still produce valid summary
        assert "$TSLA" in result
        assert "bullish" in result.lower()

    def test_heuristic_summary_handles_missing_trade_idea(self):
        """Missing trade_idea should not break summary."""
        signal = _make_signal()
        del signal["trade_idea"]
        result = _build_heuristic_summary(signal)

        assert "$TSLA" in result

    def test_heuristic_summary_handles_non_dict_reasoning(self):
        """Non-dict reasoning should be handled gracefully."""
        signal = _make_signal(reasoning="not a dict")
        result = _build_heuristic_summary(signal)

        # Should fall back to event-based summary
        assert "$TSLA" in result

    def test_heuristic_summary_handles_missing_reasoning(self):
        """Missing reasoning should use event type description."""
        signal = _make_signal()
        del signal["reasoning"]
        result = _build_heuristic_summary(signal)

        assert "$TSLA" in result
        assert "product" in result.lower()


class TestGenerateAISummary:
    """Test AI-powered summary generation."""

    @pytest.mark.asyncio
    async def test_generate_ai_summary_with_platform_key(self):
        """With platform key, should call OpenAI API."""
        with patch("rot.reasoner.ai_summary.os.environ.get") as mock_env:
            mock_env.return_value = "sk-platform-key-1234567890123456789012345678901234567890"

            # Mock the openai module
            mock_openai = Mock()
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_choice = Mock()
            mock_message = Mock()
            mock_message.content = "AI-generated summary about TSLA bullish signal"
            mock_choice.message = mock_message
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.AsyncOpenAI.return_value = mock_client

            with patch.dict(sys.modules, {"openai": mock_openai}):
                signal = _make_signal()
                result = await generate_ai_summary(signal)

                assert result == "AI-generated summary about TSLA bullish signal"
                # Verify API was called
                assert mock_client.chat.completions.create.call_count == 1
                call_kwargs = mock_client.chat.completions.create.call_args[1]
                assert call_kwargs["model"] == "gpt-4o-mini"
                assert call_kwargs["max_tokens"] == 100
                assert call_kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_generate_ai_summary_sends_system_prompt(self):
        """AI summary should send system prompt."""
        with patch("rot.reasoner.ai_summary.os.environ.get") as mock_env:
            mock_env.return_value = "sk-platform-key-1234567890123456789012345678901234567890"

            mock_openai = Mock()
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_choice = Mock()
            mock_message = Mock()
            mock_message.content = "Summary"
            mock_choice.message = mock_message
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.AsyncOpenAI.return_value = mock_client

            with patch.dict(sys.modules, {"openai": mock_openai}):

                signal = _make_signal()
                await generate_ai_summary(signal)

                messages = mock_client.chat.completions.create.call_args[1]["messages"]
                assert len(messages) == 2
                assert messages[0]["role"] == "system"
                assert "financial signal analyst" in messages[0]["content"].lower()

    @pytest.mark.asyncio
    async def test_generate_ai_summary_includes_signal_data(self):
        """User prompt should include signal data."""
        with patch("rot.reasoner.ai_summary.os.environ.get") as mock_env:
            mock_env.return_value = "sk-platform-key-1234567890123456789012345678901234567890"

            mock_openai = Mock()
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_choice = Mock()
            mock_message = Mock()
            mock_message.content = "Summary"
            mock_choice.message = mock_message
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.AsyncOpenAI.return_value = mock_client

            with patch.dict(sys.modules, {"openai": mock_openai}):

                signal = _make_signal(
                    ticker="NVDA",
                    stance="bearish",
                    event_type="regulatory",
                    confidence=0.55,
                )
                await generate_ai_summary(signal)

                messages = mock_client.chat.completions.create.call_args[1]["messages"]
                user_prompt = messages[1]["content"]
                assert "NVDA" in user_prompt
                assert "bearish" in user_prompt
                assert "regulatory" in user_prompt
                assert "55%" in user_prompt or "0.55" in user_prompt

    @pytest.mark.asyncio
    async def test_generate_ai_summary_truncates_long_title(self):
        """Long post titles should be truncated to 200 chars."""
        with patch("rot.reasoner.ai_summary.os.environ.get") as mock_env:
            mock_env.return_value = "sk-platform-key-1234567890123456789012345678901234567890"

            mock_openai = Mock()
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_choice = Mock()
            mock_message = Mock()
            mock_message.content = "Summary"
            mock_choice.message = mock_message
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.AsyncOpenAI.return_value = mock_client

            with patch.dict(sys.modules, {"openai": mock_openai}):

                long_title = "A" * 300
                signal = _make_signal(post_title=long_title)
                await generate_ai_summary(signal)

                messages = mock_client.chat.completions.create.call_args[1]["messages"]
                user_prompt = messages[1]["content"]
                # Should be truncated
                assert "A" * 200 in user_prompt
                # Should not contain full 300 chars
                assert "A" * 250 not in user_prompt

    @pytest.mark.asyncio
    async def test_generate_ai_summary_truncates_response(self):
        """AI response should be truncated to 500 chars max."""
        with patch("rot.reasoner.ai_summary.os.environ.get") as mock_env:
            mock_env.return_value = "sk-platform-key-1234567890123456789012345678901234567890"

            mock_openai = Mock()
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_choice = Mock()
            mock_message = Mock()
            mock_message.content = "X" * 1000
            mock_choice.message = mock_message
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.AsyncOpenAI.return_value = mock_client

            with patch.dict(sys.modules, {"openai": mock_openai}):
                signal = _make_signal()
                result = await generate_ai_summary(signal)

                assert len(result) == 500
                assert result == "X" * 500

    @pytest.mark.asyncio
    async def test_generate_ai_summary_no_platform_key(self):
        """Without platform key, should use heuristic summary."""
        with patch("rot.reasoner.ai_summary.os.environ.get") as mock_env:
            mock_env.return_value = ""

            signal = _make_signal()
            result = await generate_ai_summary(signal)

            # Should fall back to heuristic
            assert "Bullish" in result
            assert "$TSLA" in result

    @pytest.mark.asyncio
    async def test_generate_ai_summary_short_platform_key(self):
        """Short platform key should use heuristic summary."""
        with patch("rot.reasoner.ai_summary.os.environ.get") as mock_env:
            mock_env.return_value = "short"

            signal = _make_signal()
            result = await generate_ai_summary(signal)

            # Should fall back to heuristic
            assert "$TSLA" in result

    @pytest.mark.asyncio
    async def test_generate_ai_summary_openai_import_error(self):
        """Missing openai package should fall back to heuristic."""
        with patch("rot.reasoner.ai_summary.os.environ.get") as mock_env:
            mock_env.return_value = "sk-platform-key-1234567890123456789012345678901234567890"

            # Mock import error
            import sys
            old_modules = sys.modules.copy()
            sys.modules["openai"] = None

            try:
                signal = _make_signal()
                result = await generate_ai_summary(signal)

                # Should fall back to heuristic
                assert "$TSLA" in result
            finally:
                sys.modules.update(old_modules)

    @pytest.mark.asyncio
    async def test_generate_ai_summary_api_error(self):
        """API errors should fall back to heuristic summary."""
        with patch("rot.reasoner.ai_summary.os.environ.get") as mock_env:
            mock_env.return_value = "sk-platform-key-1234567890123456789012345678901234567890"

            mock_openai = Mock()
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("API error")
            )
            mock_openai.AsyncOpenAI.return_value = mock_client

            with patch.dict(sys.modules, {"openai": mock_openai}):
                signal = _make_signal(ticker="AAPL")
                result = await generate_ai_summary(signal)

                # Should fall back to heuristic
                assert "$AAPL" in result

    @pytest.mark.asyncio
    async def test_generate_ai_summary_rate_limit_error(self):
        """Rate limit errors should fall back to heuristic."""
        with patch("rot.reasoner.ai_summary.os.environ.get") as mock_env:
            mock_env.return_value = "sk-platform-key-1234567890123456789012345678901234567890"

            mock_openai = Mock()
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("Rate limit exceeded")
            )
            mock_openai.AsyncOpenAI.return_value = mock_client

            with patch.dict(sys.modules, {"openai": mock_openai}):
                signal = _make_signal()
                result = await generate_ai_summary(signal)

                # Should fall back to heuristic
                assert "$TSLA" in result


class TestBackfillAISummaries:
    """Test batch AI summary generation."""

    @pytest.mark.asyncio
    async def test_backfill_ai_summaries_processes_signals(self):
        """Backfill should generate summaries for pending signals."""
        mock_db = Mock()
        signals = [
            _make_signal(id="sig_1", ticker="AAPL"),
            _make_signal(id="sig_2", ticker="TSLA"),
            _make_signal(id="sig_3", ticker="NVDA"),
        ]
        mock_db.get_signals_needing_ai_summary = AsyncMock(return_value=signals)
        mock_db.set_ai_summary = AsyncMock()

        with patch("rot.reasoner.ai_summary.generate_ai_summary") as mock_gen:
            mock_gen.side_effect = [
                "Summary for AAPL",
                "Summary for TSLA",
                "Summary for NVDA",
            ]

            count = await backfill_ai_summaries(mock_db, limit=30)

            assert count == 3
            assert mock_db.set_ai_summary.call_count == 3

    @pytest.mark.asyncio
    async def test_backfill_ai_summaries_respects_limit(self):
        """Backfill should respect limit parameter."""
        mock_db = Mock()
        mock_db.get_signals_needing_ai_summary = AsyncMock(return_value=[])

        await backfill_ai_summaries(mock_db, limit=10)

        mock_db.get_signals_needing_ai_summary.assert_called_once_with(limit=10)

    @pytest.mark.asyncio
    async def test_backfill_ai_summaries_saves_to_db(self):
        """Generated summaries should be saved to database."""
        mock_db = Mock()
        signal = _make_signal(id="sig_123", ticker="AAPL")
        mock_db.get_signals_needing_ai_summary = AsyncMock(return_value=[signal])
        mock_db.set_ai_summary = AsyncMock()

        with patch("rot.reasoner.ai_summary.generate_ai_summary") as mock_gen:
            mock_gen.return_value = "Generated summary"

            await backfill_ai_summaries(mock_db)

            mock_db.set_ai_summary.assert_called_once_with("sig_123", "Generated summary")

    @pytest.mark.asyncio
    async def test_backfill_ai_summaries_handles_generation_errors(self):
        """Errors during generation should be logged but not break batch."""
        mock_db = Mock()
        signals = [
            _make_signal(id="sig_1", ticker="AAPL"),
            _make_signal(id="sig_2", ticker="TSLA"),  # This one will fail
            _make_signal(id="sig_3", ticker="NVDA"),
        ]
        mock_db.get_signals_needing_ai_summary = AsyncMock(return_value=signals)
        mock_db.set_ai_summary = AsyncMock()

        with patch("rot.reasoner.ai_summary.generate_ai_summary") as mock_gen:
            mock_gen.side_effect = [
                "Summary 1",
                Exception("Generation failed"),
                "Summary 3",
            ]

            count = await backfill_ai_summaries(mock_db)

            # Should have processed 2 successfully (1 and 3)
            assert count == 2
            assert mock_db.set_ai_summary.call_count == 2

    @pytest.mark.asyncio
    async def test_backfill_ai_summaries_skips_empty_summaries(self):
        """Empty summaries should not be saved."""
        mock_db = Mock()
        signal = _make_signal(id="sig_1")
        mock_db.get_signals_needing_ai_summary = AsyncMock(return_value=[signal])
        mock_db.set_ai_summary = AsyncMock()

        with patch("rot.reasoner.ai_summary.generate_ai_summary") as mock_gen:
            mock_gen.return_value = ""

            count = await backfill_ai_summaries(mock_db)

            assert count == 0
            assert mock_db.set_ai_summary.call_count == 0

    @pytest.mark.asyncio
    async def test_backfill_ai_summaries_no_pending_signals(self):
        """No pending signals should return 0 count."""
        mock_db = Mock()
        mock_db.get_signals_needing_ai_summary = AsyncMock(return_value=[])

        count = await backfill_ai_summaries(mock_db)

        assert count == 0

    @pytest.mark.asyncio
    async def test_backfill_ai_summaries_logs_progress(self):
        """Backfill should log progress when summaries are generated."""
        mock_db = Mock()
        signals = [_make_signal(id=f"sig_{i}") for i in range(5)]
        mock_db.get_signals_needing_ai_summary = AsyncMock(return_value=signals)
        mock_db.set_ai_summary = AsyncMock()

        with patch("rot.reasoner.ai_summary.generate_ai_summary") as mock_gen:
            mock_gen.return_value = "Summary"

            with patch("rot.reasoner.ai_summary.log") as mock_log:
                count = await backfill_ai_summaries(mock_db)

                assert count == 5
                # Should log info about generation
                assert mock_log.info.call_count > 0


class TestPromptTemplates:
    """Test prompt templates for AI summary generation."""

    def test_system_prompt_is_concise(self):
        """System prompt should be short to minimize token usage."""
        # Should be under 200 chars for cost efficiency
        assert len(_SYSTEM_PROMPT) < 250
        assert "concise" in _SYSTEM_PROMPT.lower()

    def test_system_prompt_defines_format(self):
        """System prompt should define expected output format."""
        assert "1-2 sentence" in _SYSTEM_PROMPT

    def test_system_prompt_specifies_content(self):
        """System prompt should specify what to include."""
        assert "thesis" in _SYSTEM_PROMPT.lower()
        assert "risk" in _SYSTEM_PROMPT.lower()
        assert "timeframe" in _SYSTEM_PROMPT.lower()

    def test_user_template_has_signal_fields(self):
        """User template should include all signal fields."""
        assert "{ticker}" in _USER_TEMPLATE
        assert "{stance}" in _USER_TEMPLATE
        assert "{event_type}" in _USER_TEMPLATE
        assert "{subreddit}" in _USER_TEMPLATE
        # confidence has format specifier
        assert "confidence" in _USER_TEMPLATE
        assert "{post_title}" in _USER_TEMPLATE
        assert "{strategy}" in _USER_TEMPLATE

    def test_user_template_formats_confidence_as_percentage(self):
        """User template should format confidence as percentage."""
        assert ":.0%" in _USER_TEMPLATE
