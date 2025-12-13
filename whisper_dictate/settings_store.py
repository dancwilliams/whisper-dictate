"""Persistent settings storage for whisper-dictate."""

import json
import logging
from pathlib import Path
from typing import Any

from whisper_dictate import credentials

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path.home() / ".whisper_dictate/whisper_dictate_settings.json"

# Settings keys that should be stored securely
SECURE_KEYS = {"llm_key"}


def load_settings() -> dict[str, Any]:
    """Load saved settings from disk, returning defaults on failure.

    Automatically migrates plaintext API keys to secure storage if found.
    """
    # Default advanced transcription settings
    defaults = {
        "app_prompts": {},
        "vad_enabled": False,  # Disabled by default for backward compatibility
        "vad_threshold": 0.5,
        "vad_min_speech_ms": 250,
        "vad_min_silence_ms": 500,
        "vad_speech_pad_ms": 400,
        "compression_ratio_threshold": 2.4,
        "log_prob_threshold": -1.0,
        "no_speech_threshold": 0.6,
        "word_timestamps": False,
        "temperature": 0.0,
        "beam_size": 5,
        "initial_prompt": "",
    }

    try:
        if SETTINGS_FILE.is_file():
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))

            # Merge with defaults (preserve existing, add missing)
            for key, value in defaults.items():
                if key not in settings:
                    settings[key] = value

            # Migrate plaintext API keys to secure storage
            _migrate_secure_settings(settings)

            return settings
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:  # pragma: no cover
        # OSError: File access errors
        # UnicodeDecodeError: Invalid UTF-8 encoding
        # JSONDecodeError: Invalid JSON format
        logger.error(f"Could not read saved settings: {e}")
    return defaults


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
        SETTINGS_FILE.write_text(json.dumps(settings_to_save, indent=2), encoding="utf-8")
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
                    credential_key = _get_credential_key(key)
                    if credentials.migrate_from_plaintext(plaintext_value, credential_key):
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
        if key in settings and settings[key]:
            value = settings[key]
            if isinstance(value, str) and value.strip():
                try:
                    credential_key = _get_credential_key(key)
                    credentials.store_credential(credential_key, value)
                except (credentials.CredentialStorageError, ValueError) as e:
                    logger.warning(f"Failed to store {key} in credential manager: {e}")


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
        credential_key = _get_credential_key(key)
        return credentials.retrieve_credential(credential_key)
    except (credentials.CredentialStorageError, ValueError) as e:
        logger.warning(f"Failed to retrieve {key} from credential manager: {e}")
        return None


def _get_credential_key(settings_key: str) -> str:
    """Convert settings key to credential key.

    Args:
        settings_key: Settings key (e.g., "llm_key")

    Returns:
        Credential key for keyring storage (e.g., "llm_api_key")
    """
    # Map settings keys to credential keys
    key_mapping = {
        "llm_key": credentials.LLM_API_KEY,
    }
    return key_mapping.get(settings_key, settings_key)
