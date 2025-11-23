"""Tests for LLM cleanup functionality."""

from unittest.mock import MagicMock, patch

import pytest

from whisper_dictate.glossary import GlossaryManager, GlossaryRule
from whisper_dictate.llm_cleanup import LLMCleanupError, clean_with_llm


class TestLLMCleanup:
    """Test LLM cleanup functionality."""
    
    def test_clean_with_llm_empty_text(self):
        """Test that empty text returns empty string."""
        with patch("whisper_dictate.llm_cleanup.OpenAI") as mock_openai:
            result = clean_with_llm("", "http://test", "model", None, "prompt", 0.1)
            assert result == ""
            mock_openai.assert_not_called()
    
    def test_clean_with_llm_whitespace_only(self):
        """Test that whitespace-only text returns empty string."""
        with patch("whisper_dictate.llm_cleanup.OpenAI") as mock_openai:
            result = clean_with_llm("   \n  ", "http://test", "model", None, "prompt", 0.1)
            assert result == ""
            mock_openai.assert_not_called()
    
    def test_clean_with_llm_success(self):
        """Test successful LLM cleanup."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Cleaned text"
        mock_client.chat.completions.create.return_value = mock_response
        
        with patch("whisper_dictate.llm_cleanup.OpenAI", return_value=mock_client):
            result = clean_with_llm(
                "raw text", "http://test", "model", "key", "prompt", 0.1
            )
            assert result == "Cleaned text"
            mock_client.chat.completions.create.assert_called_once()
    
    def test_clean_with_llm_no_openai(self):
        """Test that missing OpenAI raises error."""
        with patch("whisper_dictate.llm_cleanup.OpenAI", None):
            with pytest.raises(LLMCleanupError, match="OpenAI client not installed"):
                clean_with_llm("text", "http://test", "model", None, "prompt", 0.1)
    
    def test_clean_with_llm_api_error(self):
        """Test handling of API errors."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")

        with patch("whisper_dictate.llm_cleanup.OpenAI", return_value=mock_client):
            with pytest.raises(LLMCleanupError, match="LLM cleanup failed"):
                clean_with_llm("text", "http://test", "model", None, "prompt", 0.1)
    
    def test_clean_with_llm_empty_response(self):
        """Test handling of empty response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = []
        mock_client.chat.completions.create.return_value = mock_response

        with patch("whisper_dictate.llm_cleanup.OpenAI", return_value=mock_client):
            result = clean_with_llm("text", "http://test", "model", None, "prompt", 0.1)
            assert result is None

    def test_clean_with_llm_includes_glossary(self):
        """Ensure glossary rules are summarized in the system prompt when provided."""
        glossary_manager = GlossaryManager([GlossaryRule(trigger="AppName", replacement="Whisper Dictate")])
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Cleaned text"
        mock_client.chat.completions.create.return_value = mock_response

        with patch("whisper_dictate.llm_cleanup.OpenAI", return_value=mock_client):
            clean_with_llm(
                "raw text",
                "http://test",
                "model",
                None,
                "system prompt",
                0.1,
                glossary=glossary_manager,
                prompt_context=None,
            )

        messages = mock_client.chat.completions.create.call_args[1]["messages"]
        assert messages[0]["role"] == "system"
        assert "AppName → Whisper Dictate" in messages[0]["content"]
        assert messages[0]["content"].startswith("Glossary entries (prioritized):")

    def test_clean_with_llm_includes_app_prompt(self):
        """Application-specific prompt should be appended to the system prompt."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Cleaned text"
        mock_client.chat.completions.create.return_value = mock_response

        with patch("whisper_dictate.llm_cleanup.OpenAI", return_value=mock_client):
            clean_with_llm(
                "raw text",
                "http://test",
                "model",
                None,
                "system prompt",
                0.1,
                app_prompt="App specific",
                prompt_context="Some context",
            )

        messages = mock_client.chat.completions.create.call_args[1]["messages"]
        system_prompt = messages[0]["content"]
        assert "Application-specific instructions" in system_prompt
        assert "App specific" in system_prompt
        assert system_prompt.endswith("Some context")

