"""Tests for settings_store.py - persistent settings storage."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from whisper_dictate import settings_store
from whisper_dictate.settings_store import (
    SETTINGS_FILE,
    get_secure_setting,
    load_settings,
    save_settings,
)


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """A real settings path, in a directory that does not exist yet."""
    path = tmp_path / "conf" / "whisper_dictate_settings.json"
    monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", path)
    return path


def get_expected_defaults():
    """load_settings holds no defaults of its own; they live in the GUI's Tk variables."""
    return {}


class TestLoadSettings:
    """Tests for load_settings function."""

    def test_load_settings_returns_default_when_file_missing(self, monkeypatch):
        """Test that load_settings returns default dict when file doesn't exist."""
        # Mock SETTINGS_FILE.is_file() to return False
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = False
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == get_expected_defaults()
        mock_path.is_file.assert_called_once()

    def test_load_settings_success_with_valid_json(self, monkeypatch):
        """Test successful loading of valid JSON settings."""
        test_settings = {
            "model": "base",
            "compute_type": "int8",
            "app_prompts": {"vscode": "Write code comments"},
        }

        # Mock SETTINGS_FILE
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = json.dumps(test_settings)
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == test_settings
        mock_path.read_text.assert_called_once_with(encoding="utf-8")

    def test_load_settings_handles_invalid_json(self, monkeypatch, caplog):
        """Test that load_settings returns default dict when JSON is invalid."""
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = "{invalid json content"
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == get_expected_defaults()
        # Verify error was logged
        assert "Could not read saved settings:" in caplog.text

    def test_load_settings_handles_io_error(self, monkeypatch, caplog):
        """Test that load_settings handles I/O errors gracefully."""
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.side_effect = OSError("Permission denied")
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", mock_path)

        result = load_settings()

        assert result == get_expected_defaults()
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

        assert result == get_expected_defaults()

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
    """Tests for save_settings function, against a real file: the write is atomic,
    and that is file system behaviour a mock path cannot show."""

    def test_save_settings_success(self, settings_file):
        test_settings = {
            "model": "base",
            "compute_type": "int8",
            "app_prompts": {"vscode": "Write code"},
        }

        assert save_settings(test_settings) is True

        assert json.loads(settings_file.read_text(encoding="utf-8")) == test_settings
        # The parent directory did not exist; nothing but the settings file is left in it.
        assert [f.name for f in settings_file.parent.iterdir()] == [settings_file.name]

    def test_save_settings_formats_json_with_indent(self, settings_file):
        test_settings = {"model": "base", "nested": {"key": "value"}}

        save_settings(test_settings)

        assert settings_file.read_text(encoding="utf-8") == json.dumps(test_settings, indent=2)

    def test_save_settings_replaces_existing_file(self, settings_file):
        save_settings({"model": "base"})
        save_settings({"model": "small"})

        assert json.loads(settings_file.read_text(encoding="utf-8")) == {"model": "small"}
        assert not settings_file.with_suffix(".json.tmp").exists()

    def test_save_settings_failed_swap_keeps_old_file(self, settings_file, caplog):
        """A save that dies before the swap leaves the previous settings readable."""
        save_settings({"model": "base"})

        with patch(
            "whisper_dictate.settings_store.os.replace", side_effect=OSError("Permission denied")
        ):
            assert save_settings({"model": "small"}) is False

        assert json.loads(settings_file.read_text(encoding="utf-8")) == {"model": "base"}
        assert "Could not save settings:" in caplog.text
        assert "Permission denied" in caplog.text

    def test_save_settings_handles_mkdir_error(self, tmp_path, monkeypatch, caplog):
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("", encoding="utf-8")
        monkeypatch.setattr("whisper_dictate.settings_store.SETTINGS_FILE", blocker / "s.json")

        assert save_settings({"model": "base"}) is False
        assert "Could not save settings:" in caplog.text

    def test_save_settings_with_empty_dict(self, settings_file):
        assert save_settings({}) is True
        assert json.loads(settings_file.read_text(encoding="utf-8")) == {}

    @patch("whisper_dictate.settings_store._store_secure_settings")
    def test_save_settings_stores_secure_settings(self, mock_store, settings_file):
        test_settings = {"model": "base", "llm_key": "my_secret_key"}

        save_settings(test_settings)

        mock_store.assert_called_once_with(test_settings)

    @patch("whisper_dictate.settings_store._store_secure_settings")
    def test_save_settings_excludes_secure_keys_from_json(self, mock_store, settings_file):
        save_settings(
            {"model": "base", "llm_key": "my_secret_key", "llm_endpoint": "http://localhost:1234"}
        )

        saved_data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert saved_data == {"model": "base", "llm_endpoint": "http://localhost:1234"}
        assert "my_secret_key" not in settings_file.read_text(encoding="utf-8")


class TestCorruptSettingsFile:
    """An unreadable file is kept as .bak before defaults take its place."""

    def test_corrupt_file_is_backed_up(self, settings_file, caplog):
        original = b'x{"model": "large-v3", "hotkey": "ctrl+win+g"}'
        settings_file.parent.mkdir(parents=True)
        settings_file.write_bytes(original)
        backup = settings_file.with_suffix(".json.bak")

        assert load_settings() == get_expected_defaults()
        assert settings_store.last_load_error
        assert backup.read_bytes() == original
        assert str(backup) in caplog.text

        # The save that follows overwrites the settings, never the backup.
        assert save_settings({"model": "base"}) is True
        assert backup.read_bytes() == original

    def test_undecodable_file_is_backed_up(self, settings_file):
        original = b"\xff\xfe\x00 not utf-8"
        settings_file.parent.mkdir(parents=True)
        settings_file.write_bytes(original)

        assert load_settings() == get_expected_defaults()
        assert settings_file.with_suffix(".json.bak").read_bytes() == original

    def test_good_load_clears_the_error(self, settings_file):
        settings_file.parent.mkdir(parents=True)
        settings_file.write_text("{broken", encoding="utf-8")
        load_settings()
        settings_file.write_text('{"model": "base"}', encoding="utf-8")

        assert load_settings()["model"] == "base"
        assert settings_store.last_load_error is None


class TestClearedSecureSetting:
    """A blanked API key leaves the credential manager; a partial save does not touch it."""

    @pytest.fixture
    def creds(self, settings_file):
        with patch.multiple(
            "whisper_dictate.settings_store.credentials",
            store_credential=MagicMock(),
            delete_credential=MagicMock(),
        ):
            from whisper_dictate import credentials

            yield credentials

    def test_blank_value_deletes_credential(self, creds):
        save_settings({"model": "base", "llm_key": "  "})

        creds.delete_credential.assert_called_once_with("llm_api_key")
        creds.store_credential.assert_not_called()

    def test_absent_key_does_not_delete(self, creds):
        save_settings({"model": "base"})

        creds.delete_credential.assert_not_called()
        creds.store_credential.assert_not_called()


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


class TestAutoStartupSettings:
    """Tests for auto-startup settings."""

    def test_save_settings_includes_auto_startup_flags(self, settings_file):
        save_settings({"model": "base", "auto_load_model": True, "auto_register_hotkey": False})

        saved_data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert saved_data["auto_load_model"] is True
        assert saved_data["auto_register_hotkey"] is False
