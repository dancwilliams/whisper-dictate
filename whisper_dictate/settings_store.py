"""Persistent settings storage for whisper-dictate."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from whisper_dictate import credentials

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path.home() / ".whisper_dictate/whisper_dictate_settings.json"

# Settings keys that are stored securely, and the credential each one is kept under
SECURE_KEYS = {"llm_key": credentials.LLM_API_KEY}

# Set by load_settings when the file was there but unreadable, so the GUI can say so.
last_load_error: str | None = None


def load_settings() -> dict[str, Any]:
    """Load saved settings from disk. Empty on failure: the defaults are the GUI's.

    Automatically migrates plaintext API keys to secure storage if found.
    """
    global last_load_error
    last_load_error = None
    try:
        if SETTINGS_FILE.is_file():
            settings: dict[str, Any] = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))

            # Migrate plaintext API keys to secure storage
            _migrate_secure_settings(settings)

            return settings
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        # The next save overwrites this file with defaults. Keep what was there.
        backup = SETTINGS_FILE.with_suffix(".json.bak")
        try:
            backup.write_bytes(SETTINGS_FILE.read_bytes())
        except OSError as backup_error:
            logger.error(f"Could not back up unreadable settings: {backup_error}")
        last_load_error = str(e)
        logger.error(f"Could not read saved settings: {e}. Copy kept at {backup}")
    except OSError as e:  # pragma: no cover
        logger.error(f"Could not read saved settings: {e}")
    return {}


def save_settings(settings: dict[str, Any]) -> bool:
    """Persist settings to disk. Returns True on success, False otherwise.

    Secure settings (API keys) are stored in system credential manager
    and removed from the JSON file.
    """
    try:
        # Store secure settings in credential manager
        _store_secure_settings(settings)

        # Create a copy without secure keys for JSON storage
        settings_to_save = {k: v for k, v in settings.items() if k not in SECURE_KEYS}

        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the file and swap it in: a crash mid-write leaves the old
        # settings, not half a file.
        tmp = SETTINGS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings_to_save, indent=2), encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)
        return True
    except (OSError, UnicodeEncodeError, TypeError, ValueError) as e:  # pragma: no cover
        # OSError: File/directory write errors
        # UnicodeEncodeError: Invalid character encoding
        # TypeError: Non-serializable values in settings
        # ValueError: Invalid JSON structure
        logger.error(f"Could not save settings: {e}")
        return False


def _migrate_secure_settings(settings: dict[str, Any]) -> None:
    """Migrate plaintext secure settings to credential manager.

    Args:
        settings: Settings dictionary (modified in-place)
    """
    for key in SECURE_KEYS:
        if key in settings and settings[key]:
            plaintext_value = settings[key]
            if isinstance(plaintext_value, str) and plaintext_value.strip():
                # Attempt migration
                try:
                    if credentials.migrate_from_plaintext(plaintext_value, SECURE_KEYS[key]):
                        # Remove from settings dict after successful migration
                        del settings[key]
                        logger.info(f"Migrated {key} to secure storage")
                except Exception as e:
                    logger.warning(f"Failed to migrate {key}: {e}")


def _store_secure_settings(settings: dict[str, Any]) -> None:
    """Store secure settings in credential manager.

    Args:
        settings: Settings dictionary
    """
    for key in SECURE_KEYS:
        # An absent key is a partial save, not a cleared field: leave it stored.
        value = settings.get(key)
        if not isinstance(value, str):
            continue
        credential_key = SECURE_KEYS[key]
        try:
            if value.strip():
                credentials.store_credential(credential_key, value)
            else:
                credentials.delete_credential(credential_key)
        except (credentials.CredentialStorageError, ValueError) as e:
            logger.warning(f"Failed to update {key} in credential manager: {e}")


def get_secure_setting(key: str) -> str | None:
    """Retrieve a secure setting from credential manager.

    Args:
        key: Settings key (e.g., "llm_key")

    Returns:
        The credential value if found, None otherwise
    """
    if key not in SECURE_KEYS:
        raise ValueError(f"Key '{key}' is not a secure setting")

    try:
        return credentials.retrieve_credential(SECURE_KEYS[key])
    except (credentials.CredentialStorageError, ValueError) as e:
        logger.warning(f"Failed to retrieve {key} from credential manager: {e}")
        return None
