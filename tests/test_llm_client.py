"""Tests for rot.reasoner.llm_client module.

Tests provider selection, request formatting, error handling, response parsing,
and timeout configuration.

Note: openai and anthropic are imported inside LLMClient.__init__, so we need
to mock them using sys.modules patching.
"""
from __future__ import annotations

import sys
from unittest.mock import Mock, patch

import pytest

from rot.reasoner.llm_client import LLMClient


class TestLLMClientInitialization:
    """Test LLMClient initialization for different providers."""

    def test_init_openai_provider(self):
        """OpenAI provider should initialize openai.OpenAI client."""
        mock_openai = Mock()
        mock_client_instance = Mock()
        mock_openai.OpenAI.return_value = mock_client_instance

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(
                provider="openai",
                api_key="sk-test123",
                model="gpt-4o-mini",
            )

            assert client.provider == "openai"
            assert client.model == "gpt-4o-mini"
            assert client.available is True
            mock_openai.OpenAI.assert_called_once_with(api_key="sk-test123")

    def test_init_openai_with_custom_base_url(self):
        """OpenAI provider with custom base_url should pass it through."""
        mock_openai = Mock()
        mock_client_instance = Mock()
        mock_openai.OpenAI.return_value = mock_client_instance

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(
                provider="openai",
                api_key="sk-test123",
                base_url="https://custom.openai.proxy.com/v1",
            )

            assert client.available is True
            mock_openai.OpenAI.assert_called_once_with(
                api_key="sk-test123",
                base_url="https://custom.openai.proxy.com/v1",
            )

    def test_init_deepseek_provider(self):
        """DeepSeek provider should use DeepSeek base URL."""
        mock_openai = Mock()
        mock_client_instance = Mock()
        mock_openai.OpenAI.return_value = mock_client_instance

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(
                provider="deepseek",
                api_key="sk-deepseek123",
                model="deepseek-chat",
            )

            assert client.provider == "deepseek"
            assert client.available is True
            mock_openai.OpenAI.assert_called_once_with(
                api_key="sk-deepseek123",
                base_url="https://api.deepseek.com/v1",
            )

    def test_init_deepseek_respects_custom_base_url(self):
        """DeepSeek with explicit base_url should use that instead of default."""
        mock_openai = Mock()
        mock_client_instance = Mock()
        mock_openai.OpenAI.return_value = mock_client_instance

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(
                provider="deepseek",
                api_key="sk-deepseek123",
                base_url="https://custom.deepseek.com/v1",
            )

            mock_openai.OpenAI.assert_called_once_with(
                api_key="sk-deepseek123",
                base_url="https://custom.deepseek.com/v1",
            )

    def test_init_anthropic_provider(self):
        """Anthropic provider should initialize anthropic.Anthropic client."""
        mock_anthropic = Mock()
        mock_client_instance = Mock()
        mock_anthropic.Anthropic.return_value = mock_client_instance

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            client = LLMClient(
                provider="anthropic",
                api_key="sk-ant-test123",
                model="claude-3-haiku-20240307",
            )

            assert client.provider == "anthropic"
            assert client.model == "claude-3-haiku-20240307"
            assert client.available is True
            mock_anthropic.Anthropic.assert_called_once_with(api_key="sk-ant-test123")

    def test_init_stores_max_tokens_and_temperature(self):
        """Initialization should store max_tokens and temperature."""
        mock_openai = Mock()
        mock_openai.OpenAI.return_value = Mock()

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(
                provider="openai",
                api_key="sk-test123",
                max_tokens=2048,
                temperature=0.7,
            )

            assert client.max_tokens == 2048
            assert client.temperature == 0.7

    def test_init_uses_defaults(self):
        """Initialization should use default values when not specified."""
        mock_openai = Mock()
        mock_openai.OpenAI.return_value = Mock()

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(
                provider="openai",
                api_key="sk-test123",
            )

            assert client.model == "gpt-4o-mini"
            assert client.max_tokens == 1024
            assert client.temperature == 0.3

    def test_init_openai_import_error(self):
        """Missing openai package should make client unavailable."""
        # Simulate import error by removing from sys.modules and making import fail
        mock_openai = Mock()
        mock_openai.side_effect = ImportError("No module named 'openai'")

        with patch.dict(sys.modules, {"openai": mock_openai}, clear=False):
            with patch("builtins.__import__", side_effect=ImportError):
                client = LLMClient(provider="openai", api_key="sk-test123")

                assert client.available is False
                assert client._client is None

    def test_init_anthropic_import_error(self):
        """Missing anthropic package should make client unavailable."""
        mock_anthropic = Mock()
        mock_anthropic.side_effect = ImportError("No module named 'anthropic'")

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}, clear=False):
            with patch("builtins.__import__", side_effect=ImportError):
                client = LLMClient(provider="anthropic", api_key="sk-ant-test123")

                assert client.available is False
                assert client._client is None


class TestLLMClientComplete:
    """Test complete() method for generating responses."""

    def test_complete_openai_success(self):
        """OpenAI complete() should format request and return response."""
        mock_openai = Mock()
        mock_client = Mock()
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = "This is the LLM response"
        mock_response.choices = [Mock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_client

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(
                provider="openai",
                api_key="sk-test123",
                model="gpt-4o-mini",
                max_tokens=512,
                temperature=0.5,
            )

            result = client.complete("System prompt here", "User prompt here")

            assert result == "This is the LLM response"
            mock_client.chat.completions.create.assert_called_once_with(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "System prompt here"},
                    {"role": "user", "content": "User prompt here"},
                ],
                max_tokens=512,
                temperature=0.5,
            )

    def test_complete_openai_empty_response(self):
        """OpenAI with None content should return empty string."""
        mock_openai = Mock()
        mock_client = Mock()
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = None
        mock_response.choices = [Mock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_client

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(provider="openai", api_key="sk-test123")
            result = client.complete("System", "User")

            assert result == ""

    def test_complete_deepseek_success(self):
        """DeepSeek uses OpenAI-compatible API."""
        mock_openai = Mock()
        mock_client = Mock()
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = "DeepSeek response"
        mock_response.choices = [Mock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_client

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(
                provider="deepseek",
                api_key="sk-deepseek123",
                model="deepseek-chat",
            )

            result = client.complete("System", "User")

            assert result == "DeepSeek response"
            assert mock_client.chat.completions.create.call_count == 1

    def test_complete_anthropic_success(self):
        """Anthropic complete() should use messages.create API."""
        mock_anthropic = Mock()
        mock_client = Mock()
        mock_response = Mock()
        mock_content_block = Mock()
        mock_content_block.text = "Claude response"
        mock_response.content = [mock_content_block]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            client = LLMClient(
                provider="anthropic",
                api_key="sk-ant-test123",
                model="claude-3-haiku-20240307",
                max_tokens=1024,
                temperature=0.3,
            )

            result = client.complete("System prompt", "User prompt")

            assert result == "Claude response"
            mock_client.messages.create.assert_called_once_with(
                model="claude-3-haiku-20240307",
                system="System prompt",
                messages=[{"role": "user", "content": "User prompt"}],
                max_tokens=1024,
                temperature=0.3,
            )

    def test_complete_anthropic_empty_content(self):
        """Anthropic with empty content list should return empty string."""
        mock_anthropic = Mock()
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = []
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            client = LLMClient(provider="anthropic", api_key="sk-ant-test123")
            result = client.complete("System", "User")

            assert result == ""

    def test_complete_without_client_raises_error(self):
        """Calling complete() when client unavailable should raise RuntimeError."""
        # Create a client with no underlying SDK
        client = LLMClient.__new__(LLMClient)
        client._client = None

        with pytest.raises(RuntimeError, match="LLM client not initialized"):
            client.complete("System", "User")

    def test_complete_unknown_provider_raises_error(self):
        """Unknown provider should raise ValueError."""
        mock_openai = Mock()
        mock_openai.OpenAI.return_value = Mock()

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(provider="openai", api_key="sk-test123")
            # Manually set invalid provider to test error path
            client.provider = "unknown_provider"

            with pytest.raises(ValueError, match="Unknown provider"):
                client.complete("System", "User")


class TestLLMClientErrorHandling:
    """Test error handling for API failures."""

    def test_complete_handles_generic_exception(self):
        """Generic exceptions should propagate."""
        mock_openai = Mock()
        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        mock_openai.OpenAI.return_value = mock_client

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(provider="openai", api_key="sk-test123")

            with pytest.raises(Exception, match="API error"):
                client.complete("System", "User")

    def test_complete_handles_connection_error(self):
        """Connection errors should propagate."""
        mock_openai = Mock()
        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = ConnectionError("Network unreachable")
        mock_openai.OpenAI.return_value = mock_client

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(provider="openai", api_key="sk-test123")

            with pytest.raises(ConnectionError):
                client.complete("System", "User")


class TestLLMClientResponseParsing:
    """Test response parsing edge cases."""

    def test_complete_handles_multiline_response(self):
        """Multiline responses should be preserved."""
        mock_openai = Mock()
        mock_client = Mock()
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = "Line 1\nLine 2\nLine 3"
        mock_response.choices = [Mock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_client

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(provider="openai", api_key="sk-test123")
            result = client.complete("System", "User")

            assert result == "Line 1\nLine 2\nLine 3"

    def test_complete_handles_json_response(self):
        """JSON responses should be returned as-is."""
        mock_openai = Mock()
        mock_client = Mock()
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = '{"key": "value", "nested": {"a": 1}}'
        mock_response.choices = [Mock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_client

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(provider="openai", api_key="sk-test123")
            result = client.complete("System", "User")

            assert result == '{"key": "value", "nested": {"a": 1}}'

    def test_complete_handles_unicode_response(self):
        """Unicode characters should be preserved."""
        mock_openai = Mock()
        mock_client = Mock()
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = "Test with émojis: 🚀📈💰"
        mock_response.choices = [Mock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_client

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(provider="openai", api_key="sk-test123")
            result = client.complete("System", "User")

            assert result == "Test with émojis: 🚀📈💰"


class TestLLMClientConfiguration:
    """Test configuration and parameter handling."""

    def test_different_temperatures(self):
        """Different temperature values should be passed through."""
        for temp in [0.0, 0.3, 0.7, 1.0]:
            mock_openai = Mock()
            mock_client = Mock()
            mock_response = Mock()
            mock_message = Mock()
            mock_message.content = "Response"
            mock_response.choices = [Mock(message=mock_message)]
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.OpenAI.return_value = mock_client

            with patch.dict(sys.modules, {"openai": mock_openai}):
                client = LLMClient(
                    provider="openai",
                    api_key="sk-test123",
                    temperature=temp,
                )
                client.complete("System", "User")

                call_kwargs = mock_client.chat.completions.create.call_args[1]
                assert call_kwargs["temperature"] == temp

    def test_different_max_tokens(self):
        """Different max_tokens values should be passed through."""
        for tokens in [100, 512, 1024, 4096]:
            mock_openai = Mock()
            mock_client = Mock()
            mock_response = Mock()
            mock_message = Mock()
            mock_message.content = "Response"
            mock_response.choices = [Mock(message=mock_message)]
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.OpenAI.return_value = mock_client

            with patch.dict(sys.modules, {"openai": mock_openai}):
                client = LLMClient(
                    provider="openai",
                    api_key="sk-test123",
                    max_tokens=tokens,
                )
                client.complete("System", "User")

                call_kwargs = mock_client.chat.completions.create.call_args[1]
                assert call_kwargs["max_tokens"] == tokens

    def test_different_models(self):
        """Different model names should be passed through."""
        models = ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"]
        for model in models:
            mock_openai = Mock()
            mock_client = Mock()
            mock_response = Mock()
            mock_message = Mock()
            mock_message.content = "Response"
            mock_response.choices = [Mock(message=mock_message)]
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.OpenAI.return_value = mock_client

            with patch.dict(sys.modules, {"openai": mock_openai}):
                client = LLMClient(
                    provider="openai",
                    api_key="sk-test123",
                    model=model,
                )
                client.complete("System", "User")

                call_kwargs = mock_client.chat.completions.create.call_args[1]
                assert call_kwargs["model"] == model


class TestLLMClientAvailableProperty:
    """Test available property behavior."""

    def test_available_true_when_client_initialized(self):
        """available should be True when client is initialized."""
        mock_openai = Mock()
        mock_openai.OpenAI.return_value = Mock()

        with patch.dict(sys.modules, {"openai": mock_openai}):
            client = LLMClient(provider="openai", api_key="sk-test123")
            assert client.available is True

    def test_available_false_when_no_client(self):
        """available should be False when _client is None."""
        client = LLMClient.__new__(LLMClient)
        client._client = None
        assert client.available is False
