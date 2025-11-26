"""Tests for settings_store.py - persistent settings storage."""

import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from whisper_dictate.settings_store import SETTINGS_FILE, load_settings, save_settings


class TestLoadSettings:
    """Tests for load_settings function."""

    def test_load_settings_returns_default_when_file_missing(self, monkeypatch):
        """Test that load_settings returns default dict when file doesn't exist."""
        # Mock SETTINGS_FILE.is_file() to return False
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = False
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == {"app_prompts": {}}
        mock_path.is_file.assert_called_once()

    def test_load_settings_success_with_valid_json(self, monkeypatch):
        """Test successful loading of valid JSON settings."""
        test_settings = {
            "model": "base",
            "compute_type": "int8",
            "app_prompts": {"vscode": "Write code comments"}
        }

        # Mock SETTINGS_FILE
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = json.dumps(test_settings)
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == test_settings
        mock_path.read_text.assert_called_once_with(encoding="utf-8")

    def test_load_settings_adds_app_prompts_key_if_missing(self, monkeypatch):
        """Test that load_settings adds app_prompts key if not present in loaded settings."""
        test_settings = {"model": "base", "compute_type": "int8"}

        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = json.dumps(test_settings)
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert "app_prompts" in result
        assert result["app_prompts"] == {}
        assert result["model"] == "base"
        assert result["compute_type"] == "int8"

    def test_load_settings_handles_invalid_json(self, monkeypatch, capsys):
        """Test that load_settings returns default dict when JSON is invalid."""
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = "{invalid json content"
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == {"app_prompts": {}}
        # Verify error was printed
        captured = capsys.readouterr()
        assert "(Settings) Could not read saved settings:" in captured.out

    def test_load_settings_handles_io_error(self, monkeypatch, capsys):
        """Test that load_settings handles I/O errors gracefully."""
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.side_effect = IOError("Permission denied")
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == {"app_prompts": {}}
        captured = capsys.readouterr()
        assert "(Settings) Could not read saved settings:" in captured.out
        assert "Permission denied" in captured.out

    def test_load_settings_handles_empty_file(self, monkeypatch, capsys):
        """Test that load_settings handles empty file."""
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = ""
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == {"app_prompts": {}}
        captured = capsys.readouterr()
        assert "(Settings) Could not read saved settings:" in captured.out


class TestSaveSettings:
    """Tests for save_settings function."""

    def test_save_settings_success(self, monkeypatch):
        """Test successful saving of settings."""
        test_settings = {
            "model": "base",
            "compute_type": "int8",
            "app_prompts": {"vscode": "Write code"}
        }

        mock_path = MagicMock(spec=Path)
        mock_parent = MagicMock()
        mock_path.parent = mock_parent
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = save_settings(test_settings)

        assert result is True
        mock_parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_path.write_text.assert_called_once()

        # Verify the JSON was properly formatted
        call_args = mock_path.write_text.call_args
        written_json = call_args[0][0]
        assert json.loads(written_json) == test_settings
        assert call_args[1] == {"encoding": "utf-8"}

    def test_save_settings_creates_parent_directory(self, monkeypatch):
        """Test that save_settings creates parent directory if it doesn't exist."""
        test_settings = {"model": "base"}

        mock_path = MagicMock(spec=Path)
        mock_parent = MagicMock()
        mock_path.parent = mock_parent
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        save_settings(test_settings)

        # Verify mkdir was called with correct parameters
        mock_parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_save_settings_formats_json_with_indent(self, monkeypatch):
        """Test that save_settings formats JSON with 2-space indentation."""
        test_settings = {"model": "base", "nested": {"key": "value"}}

        mock_path = MagicMock(spec=Path)
        mock_parent = MagicMock()
        mock_path.parent = mock_parent
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        save_settings(test_settings)

        # Verify JSON formatting
        call_args = mock_path.write_text.call_args
        written_json = call_args[0][0]
        expected_json = json.dumps(test_settings, indent=2)
        assert written_json == expected_json

    def test_save_settings_handles_write_error(self, monkeypatch, capsys):
        """Test that save_settings returns False on write error."""
        test_settings = {"model": "base"}

        mock_path = MagicMock(spec=Path)
        mock_parent = MagicMock()
        mock_path.parent = mock_parent
        mock_path.write_text.side_effect = IOError("Permission denied")
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = save_settings(test_settings)

        assert result is False
        captured = capsys.readouterr()
        assert "(Settings) Could not save settings:" in captured.out
        assert "Permission denied" in captured.out

    def test_save_settings_handles_mkdir_error(self, monkeypatch, capsys):
        """Test that save_settings returns False when directory creation fails."""
        test_settings = {"model": "base"}

        mock_path = MagicMock(spec=Path)
        mock_parent = MagicMock()
        mock_parent.mkdir.side_effect = OSError("Cannot create directory")
        mock_path.parent = mock_parent
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = save_settings(test_settings)

        assert result is False
        captured = capsys.readouterr()
        assert "(Settings) Could not save settings:" in captured.out
        assert "Cannot create directory" in captured.out

    def test_save_settings_with_empty_dict(self, monkeypatch):
        """Test saving empty settings dictionary."""
        test_settings = {}

        mock_path = MagicMock(spec=Path)
        mock_parent = MagicMock()
        mock_path.parent = mock_parent
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = save_settings(test_settings)

        assert result is True
        call_args = mock_path.write_text.call_args
        written_json = call_args[0][0]
        assert json.loads(written_json) == {}


class TestSettingsFileConstant:
    """Tests for SETTINGS_FILE constant."""

    def test_settings_file_location(self):
        """Test that SETTINGS_FILE points to correct location."""
        expected_path = Path.home() / ".whisper_dictate/whisper_dictate_settings.json"
        assert SETTINGS_FILE == expected_path
        assert SETTINGS_FILE.name == "whisper_dictate_settings.json"
        assert SETTINGS_FILE.parent.name == ".whisper_dictate"
