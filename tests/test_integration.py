"""Integration tests for whisper-dictate full pipeline workflows.

These tests verify that components work together correctly end-to-end.
"""

from unittest.mock import MagicMock, patch

from whisper_dictate import app_context, app_prompts
from whisper_dictate.glossary import GlossaryManager, GlossaryRule
from whisper_dictate.llm_cleanup import clean_with_llm

# Test constants
TEST_BASE_PROMPT = "Clean up this transcribed text."
TEST_ENDPOINT = "http://localhost:1234/v1"
TEST_MODEL = "local-model"
TEST_API_KEY = "not-needed"
TEST_TEMPERATURE = 0.7


def create_streaming_response(content: str):
    """Helper to create a streaming response mock."""
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = content
    mock_chunk.usage = MagicMock()
    mock_chunk.usage.prompt_tokens = 10
    mock_chunk.usage.completion_tokens = 5
    mock_chunk.usage.total_tokens = 15
    return iter([mock_chunk])


class TestTranscriptionToLLMPipeline:
    """Test the full pipeline from audio to cleaned text."""

    def test_transcription_with_llm_cleanup_and_glossary(self):
        """Test full pipeline: transcription → LLM cleanup → glossary injection."""
        # Setup: Create a glossary with test rules
        glossary = GlossaryManager(
            [
                GlossaryRule(trigger="whisper dictate", replacement="Whisper-Dictate"),
                GlossaryRule(trigger="ai", replacement="AI", match_type="word"),
            ]
        )

        with patch("whisper_dictate.llm_cleanup.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = create_streaming_response(
                "Testing whisper dictate with ai technology"
            )

            # Simulate transcribed text
            transcribed_text = "testing whisper dictate with ai technology"

            # Run through LLM cleanup
            result = clean_with_llm(
                raw_text=transcribed_text,
                endpoint=TEST_ENDPOINT,
                model=TEST_MODEL,
                api_key=TEST_API_KEY,
                prompt=TEST_BASE_PROMPT,
                temperature=TEST_TEMPERATURE,
                glossary=glossary,
            )

        # Verify glossary was injected into system prompt
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        system_content = " ".join(msg["content"] for msg in messages if msg["role"] == "system")
        assert "whisper dictate → Whisper-Dictate" in system_content
        assert "ai → AI" in system_content

        # Return LLM output as-is (glossary not applied to output)
        assert result == "Testing whisper dictate with ai technology"

    def test_empty_transcription_skips_llm(self):
        """Test that empty/whitespace transcription doesn't call LLM."""
        glossary = GlossaryManager([])

        with patch("whisper_dictate.llm_cleanup.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            result = clean_with_llm(
                raw_text="   ",
                endpoint=TEST_ENDPOINT,
                model=TEST_MODEL,
                api_key=TEST_API_KEY,
                prompt=TEST_BASE_PROMPT,
                temperature=TEST_TEMPERATURE,
                glossary=glossary,
            )

        # Verify LLM was not called
        mock_client.chat.completions.create.assert_not_called()
        assert result == ""


class TestAppContextToLLMPipeline:
    """Test the pipeline from app context detection to LLM cleanup."""

    def test_app_context_injects_into_llm_prompt(self):
        """Test that active app context is injected into LLM prompt."""
        # Create a context
        context = app_context.ActiveContext(
            window_title="Document1.txt - Notepad",
            process_name="notepad.exe",
            cursor_position=(100, 200),
        )

        # Format it for prompt
        context_string = app_context.format_context_for_prompt(context)
        assert context_string is not None
        assert "notepad.exe" in context_string

        with patch("whisper_dictate.llm_cleanup.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = create_streaming_response(
                "Cleaned text for notepad"
            )

            result = clean_with_llm(
                raw_text="raw text",
                endpoint=TEST_ENDPOINT,
                model=TEST_MODEL,
                api_key=TEST_API_KEY,
                prompt=TEST_BASE_PROMPT,
                temperature=TEST_TEMPERATURE,
                prompt_context=context_string,
            )

        # Verify the context was included in the prompt
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]

        # Find the system message that should contain the context
        system_messages = [msg for msg in messages if msg["role"] == "system"]
        assert len(system_messages) > 0

        # Check that context was injected
        system_content = " ".join(msg["content"] for msg in system_messages)
        assert "notepad.exe" in system_content

        assert result == "Cleaned text for notepad"


class TestAppPromptResolutionPipeline:
    """Test app-specific prompt resolution and LLM integration."""

    def test_app_specific_prompt_injection(self):
        """Test that app-specific prompts are resolved and injected into LLM."""
        # Setup app prompts (normalized format)
        app_prompt_map = {
            "vscode.exe": [{"prompt": "You are editing code. Format as proper code syntax."}],
            "notepad.exe": [{"prompt": "You are editing plain text. Keep formatting simple."}],
        }

        # Test with VSCode context
        context = app_context.ActiveContext(
            window_title="main.py - Visual Studio Code",
            process_name="vscode.exe",
            cursor_position=None,
        )

        # Resolve the app prompt
        resolved_prompt = app_prompts.resolve_app_prompt(
            app_prompts=app_prompt_map,
            context=context,
        )

        assert resolved_prompt == "You are editing code. Format as proper code syntax."

        with patch("whisper_dictate.llm_cleanup.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = create_streaming_response(
                "def main():\n    pass"
            )

            result = clean_with_llm(
                raw_text="define main function",
                endpoint=TEST_ENDPOINT,
                model=TEST_MODEL,
                api_key=TEST_API_KEY,
                prompt=TEST_BASE_PROMPT,
                temperature=TEST_TEMPERATURE,
                app_prompt=resolved_prompt,
            )

        # Verify app-specific prompt was included
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        system_content = " ".join(msg["content"] for msg in messages if msg["role"] == "system")

        assert "editing code" in system_content
        assert result == "def main():\n    pass"

    def test_window_title_regex_matching(self):
        """Test that window title regex patterns work correctly."""
        app_prompt_map = {
            "chrome.exe": [
                {
                    "prompt": "You are composing email.",
                    "window_title_regex": ".*Gmail.*",
                },
                {
                    "prompt": "You are in a web browser.",
                },
            ]
        }

        # Test with Gmail window
        context = app_context.ActiveContext(
            window_title="Gmail - Google Chrome",
            process_name="chrome.exe",
            cursor_position=None,
        )

        resolved = app_prompts.resolve_app_prompt(
            app_prompts=app_prompt_map,
            context=context,
        )

        # Should match the Gmail-specific prompt
        assert resolved == "You are composing email."

        # Test with non-Gmail Chrome window
        context2 = app_context.ActiveContext(
            window_title="Stack Overflow - Google Chrome",
            process_name="chrome.exe",
            cursor_position=None,
        )

        resolved2 = app_prompts.resolve_app_prompt(
            app_prompts=app_prompt_map,
            context=context2,
        )

        # Should fall back to general browser prompt
        assert resolved2 == "You are in a web browser."


class TestGlossaryWithLLMIntegration:
    """Test glossary application with LLM cleanup."""

    def test_glossary_injected_into_llm_prompt(self):
        """Test that glossary rules are injected into LLM prompt."""
        glossary = GlossaryManager(
            [
                GlossaryRule(trigger="open ai", replacement="OpenAI"),
                GlossaryRule(trigger="gpt", replacement="GPT", match_type="word"),
            ]
        )

        with patch("whisper_dictate.llm_cleanup.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            # LLM returns text (glossary guides LLM but isn't applied to output)
            mock_client.chat.completions.create.return_value = create_streaming_response(
                "We use open ai and gpt models"
            )

            result = clean_with_llm(
                raw_text="we use open ai and gpt models",
                endpoint=TEST_ENDPOINT,
                model=TEST_MODEL,
                api_key=TEST_API_KEY,
                prompt=TEST_BASE_PROMPT,
                temperature=TEST_TEMPERATURE,
                glossary=glossary,
            )

        # Verify glossary was injected into system prompt
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        system_content = " ".join(msg["content"] for msg in messages if msg["role"] == "system")
        assert "open ai → OpenAI" in system_content
        assert "gpt → GPT" in system_content

        # LLM output returned as-is
        assert result == "We use open ai and gpt models"

    def test_glossary_injected_into_llm_system_prompt(self):
        """Test that glossary rules are included in LLM system prompt."""
        glossary = GlossaryManager(
            [
                GlossaryRule(trigger="usa", replacement="USA", match_type="word"),
                GlossaryRule(trigger="api", replacement="API", match_type="word"),
            ]
        )

        with patch("whisper_dictate.llm_cleanup.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = create_streaming_response(
                "The USA uses the API"
            )

            clean_with_llm(
                raw_text="the usa uses the api",
                endpoint=TEST_ENDPOINT,
                model=TEST_MODEL,
                api_key=TEST_API_KEY,
                prompt=TEST_BASE_PROMPT,
                temperature=TEST_TEMPERATURE,
                glossary=glossary,
            )

        # Verify glossary was mentioned in system prompt
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        system_content = " ".join(msg["content"] for msg in messages if msg["role"] == "system")

        assert "usa → USA" in system_content
        assert "api → API" in system_content


class TestEndToEndWorkflow:
    """Test complete end-to-end workflows combining multiple components."""

    def test_full_workflow_with_all_features(self):
        """Test complete workflow: context + app prompt + glossary + LLM."""
        # Setup all components
        context = app_context.ActiveContext(
            window_title="README.md - VSCode",
            process_name="vscode.exe",
            cursor_position=(500, 300),
        )

        app_prompt_map = {
            "vscode.exe": [{"prompt": "Format as markdown documentation."}],
        }

        glossary = GlossaryManager(
            [
                GlossaryRule(trigger="whisper dictate", replacement="Whisper-Dictate"),
                GlossaryRule(trigger="llm", replacement="LLM", match_type="word"),
            ]
        )

        # Resolve app prompt
        app_prompt = app_prompts.resolve_app_prompt(
            app_prompts=app_prompt_map,
            context=context,
        )
        assert app_prompt == "Format as markdown documentation."

        # Format context
        context_str = app_context.format_context_for_prompt(context)
        assert "vscode.exe" in context_str

        with patch("whisper_dictate.llm_cleanup.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = create_streaming_response(
                "# whisper dictate\n\nThis llm integration is powerful."
            )

            # Run full pipeline
            result = clean_with_llm(
                raw_text="whisper dictate llm integration is powerful",
                endpoint=TEST_ENDPOINT,
                model=TEST_MODEL,
                api_key=TEST_API_KEY,
                prompt=TEST_BASE_PROMPT,
                temperature=TEST_TEMPERATURE,
                prompt_context=context_str,
                app_prompt=app_prompt,
                glossary=glossary,
            )

        # Verify all context was included in LLM prompt
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        system_content = " ".join(msg["content"] for msg in messages if msg["role"] == "system")

        assert "vscode.exe" in system_content  # Context included
        assert "markdown documentation" in system_content  # App prompt included
        assert "whisper dictate → Whisper-Dictate" in system_content  # Glossary included

        # LLM output returned as-is (glossary guides LLM but isn't applied to output)
        assert result == "# whisper dictate\n\nThis llm integration is powerful."

    def test_workflow_with_missing_components(self):
        """Test that workflow works when optional components are missing."""
        # No context, no app prompt, no glossary
        with patch("whisper_dictate.llm_cleanup.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = create_streaming_response(
                "Clean text output"
            )

            result = clean_with_llm(
                raw_text="raw input text",
                endpoint=TEST_ENDPOINT,
                model=TEST_MODEL,
                api_key=TEST_API_KEY,
                prompt=TEST_BASE_PROMPT,
                temperature=TEST_TEMPERATURE,
                # All optional parameters omitted
            )

        # Should still work with minimal configuration
        assert result == "Clean text output"

        # Verify LLM was called with basic prompt only
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        assert len(messages) >= 1  # At least the base system message
