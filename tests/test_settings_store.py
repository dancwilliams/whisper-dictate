"""Tests for settings_store.py - persistent settings storage."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from whisper_dictate.settings_store import (
    SETTINGS_FILE,
    get_secure_setting,
    load_settings,
    save_settings,
)


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

    def test_load_settings_handles_invalid_json(self, monkeypatch, caplog):
        """Test that load_settings returns default dict when JSON is invalid."""
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = "{invalid json content"
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == {"app_prompts": {}}
        # Verify error was logged
        assert "Could not read saved settings:" in caplog.text

    def test_load_settings_handles_io_error(self, monkeypatch, caplog):
        """Test that load_settings handles I/O errors gracefully."""
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.side_effect = OSError("Permission denied")
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == {"app_prompts": {}}
        # Verify error was logged
        assert "Could not read saved settings:" in caplog.text
        assert "Permission denied" in caplog.text

    def test_load_settings_handles_empty_file(self, monkeypatch, capsys):
        """Test that load_settings handles empty file."""
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = ""
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == {"app_prompts": {}}

    @patch("whisper_dictate.settings_store._migrate_secure_settings")
    def test_load_settings_migrates_secure_settings(self, mock_migrate, monkeypatch):
        """Test that load_settings calls migration for secure settings."""
        test_settings = {"model": "base", "llm_key": "plaintext_key"}

        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = json.dumps(test_settings)
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        load_settings()

        mock_migrate.assert_called_once()
        # Verify settings dict was passed
        call_args = mock_migrate.call_args[0][0]
        assert "model" in call_args


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

    @patch("whisper_dictate.settings_store._store_secure_settings")
    def test_save_settings_handles_write_error(self, mock_store, monkeypatch, caplog):
        """Test that save_settings returns False on write error."""
        test_settings = {"model": "base"}

        mock_path = MagicMock(spec=Path)
        mock_parent = MagicMock()
        mock_path.parent = mock_parent
        mock_path.write_text.side_effect = OSError("Permission denied")
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = save_settings(test_settings)

        assert result is False
        # Verify error was logged
        assert "Could not save settings:" in caplog.text
        assert "Permission denied" in caplog.text

    @patch("whisper_dictate.settings_store._store_secure_settings")
    def test_save_settings_handles_mkdir_error(self, mock_store, monkeypatch, caplog):
        """Test that save_settings returns False when directory creation fails."""
        test_settings = {"model": "base"}

        mock_path = MagicMock(spec=Path)
        mock_parent = MagicMock()
        mock_parent.mkdir.side_effect = OSError("Cannot create directory")
        mock_path.parent = mock_parent
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = save_settings(test_settings)

        assert result is False
        # Verify error was logged
        assert "Could not save settings:" in caplog.text
        assert "Cannot create directory" in caplog.text

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


    @patch("whisper_dictate.settings_store._store_secure_settings")
    def test_save_settings_stores_secure_settings(self, mock_store, monkeypatch):
        """Test that save_settings calls secure storage for API keys."""
        test_settings = {"model": "base", "llm_key": "my_secret_key"}

        mock_path = MagicMock(spec=Path)
        mock_parent = MagicMock()
        mock_path.parent = mock_parent
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        save_settings(test_settings)

        mock_store.assert_called_once_with(test_settings)

    def test_save_settings_excludes_secure_keys_from_json(self, monkeypatch):
        """Test that API keys are not written to JSON file."""
        test_settings = {
            "model": "base",
            "llm_key": "my_secret_key",
            "llm_endpoint": "http://localhost:1234"
        }

        mock_path = MagicMock(spec=Path)
        mock_parent = MagicMock()
        mock_path.parent = mock_parent
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        # Mock the credentials module to prevent actual keyring calls
        with patch("whisper_dictate.settings_store._store_secure_settings"):
            save_settings(test_settings)

        # Verify written JSON doesn't contain llm_key
        call_args = mock_path.write_text.call_args
        written_json = call_args[0][0]
        saved_data = json.loads(written_json)

        assert "llm_key" not in saved_data
        assert "model" in saved_data
        assert "llm_endpoint" in saved_data


class TestGetSecureSetting:
    """Tests for get_secure_setting function."""

    @patch("whisper_dictate.settings_store.credentials.retrieve_credential")
    def test_get_secure_setting_success(self, mock_retrieve):
        """Test retrieving a secure setting."""
        mock_retrieve.return_value = "my_api_key"

        result = get_secure_setting("llm_key")

        assert result == "my_api_key"
        mock_retrieve.assert_called_once_with("llm_api_key")

    @patch("whisper_dictate.settings_store.credentials.retrieve_credential")
    def test_get_secure_setting_not_found(self, mock_retrieve):
        """Test retrieving non-existent secure setting returns None."""
        mock_retrieve.return_value = None

        result = get_secure_setting("llm_key")

        assert result is None

    def test_get_secure_setting_invalid_key(self):
        """Test that invalid key raises ValueError."""
        with pytest.raises(ValueError, match="not a secure setting"):
            get_secure_setting("invalid_key")

    @patch("whisper_dictate.settings_store.credentials.retrieve_credential")
    def test_get_secure_setting_handles_errors(self, mock_retrieve):
        """Test that errors during retrieval return None."""
        from whisper_dictate.credentials import CredentialStorageError

        mock_retrieve.side_effect = CredentialStorageError("Backend error")

        result = get_secure_setting("llm_key")

        assert result is None


class TestSettingsFileConstant:
    """Tests for SETTINGS_FILE constant."""

    def test_settings_file_location(self):
        """Test that SETTINGS_FILE points to correct location."""
        expected_path = Path.home() / ".whisper_dictate/whisper_dictate_settings.json"
        assert SETTINGS_FILE == expected_path
        assert SETTINGS_FILE.name == "whisper_dictate_settings.json"
        assert SETTINGS_FILE.parent.name == ".whisper_dictate"
