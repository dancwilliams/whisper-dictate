"""Persistent settings storage for whisper-dictate."""

import json
from pathlib import Path
from typing import Any

SETTINGS_FILE = Path.home() / ".whisper_dictate/whisper_dictate_settings.json"


def load_settings() -> dict[str, Any]:
    """Load saved settings from disk, returning an empty dict on failure."""
    try:
        if SETTINGS_FILE.is_file():
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if "app_prompts" not in settings:
                settings["app_prompts"] = {}
            return settings
    except Exception as e:  # pragma: no cover - best effort load
        print(f"(Settings) Could not read saved settings: {e}")
    return {"app_prompts": {}}


def save_settings(settings: dict[str, Any]) -> bool:
    """Persist settings to disk. Returns True on success, False otherwise."""
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return True
    except Exception as e:  # pragma: no cover - best effort save
        print(f"(Settings) Could not save settings: {e}")
        return False
