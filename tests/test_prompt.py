"""Tests for prompt management."""

from pathlib import Path
from unittest.mock import patch

from whisper_dictate.prompt import load_saved_prompt, write_saved_prompt


class TestPrompt:
    """Test prompt loading and saving."""

    def test_load_saved_prompt_file_exists(self, tmp_path, monkeypatch):
        """Test loading prompt from existing file."""
        test_prompt = "Test prompt content"
        test_file = tmp_path / ".whisper_dictate_prompt.txt"
        test_file.write_text(test_prompt, encoding="utf-8")

        with patch("whisper_dictate.prompt.PROMPT_FILE", test_file):
            result = load_saved_prompt("default")
            assert result == test_prompt

    def test_load_saved_prompt_file_not_exists(self, monkeypatch):
        """Test loading prompt when file doesn't exist."""
        with patch("whisper_dictate.prompt.PROMPT_FILE", Path("/nonexistent/prompt.txt")):
            result = load_saved_prompt("default")
            assert result == "default"

    def test_load_saved_prompt_empty_file(self, tmp_path, monkeypatch):
        """Test loading prompt from empty file returns default."""
        test_file = tmp_path / ".whisper_dictate_prompt.txt"
        test_file.write_text("   \n  ", encoding="utf-8")

        with patch("whisper_dictate.prompt.PROMPT_FILE", test_file):
            result = load_saved_prompt("default")
            assert result == "default"

    def test_write_saved_prompt_success(self, tmp_path, monkeypatch):
        """Test successfully saving prompt."""
        test_file = tmp_path / ".whisper_dictate_prompt.txt"

        with patch("whisper_dictate.prompt.PROMPT_FILE", test_file):
            result = write_saved_prompt("test prompt")
            assert result is True
            assert test_file.read_text(encoding="utf-8") == "test prompt"

    def test_write_saved_prompt_failure(self, monkeypatch):
        """Test handling of save failure."""
        with patch("whisper_dictate.prompt.PROMPT_FILE", Path("/invalid/path/prompt.txt")):
            with patch("pathlib.Path.write_text", side_effect=PermissionError("Access denied")):
                result = write_saved_prompt("test")
                assert result is False
