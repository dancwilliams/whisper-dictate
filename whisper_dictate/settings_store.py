"""Persistent settings storage for whisper-dictate."""

import json
from pathlib import Path
from typing import Any, Dict

SETTINGS_FILE = Path.home() / ".whisper_dictate_settings.json"


def load_settings() -> Dict[str, Any]:
    """Load saved settings from disk, returning an empty dict on failure."""
    try:
        if SETTINGS_FILE.is_file():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover - best effort load
        print(f"(Settings) Could not read saved settings: {e}")
    return {}


def save_settings(settings: Dict[str, Any]) -> bool:
    """Persist settings to disk. Returns True on success, False otherwise."""
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return True
    except Exception as e:  # pragma: no cover - best effort save
        print(f"(Settings) Could not save settings: {e}")
        return False
