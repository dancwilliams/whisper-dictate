"""Glossary management for LLM cleanup."""

from pathlib import Path
from typing import Optional

GLOSSARY_FILE = Path.home() / ".whisper_dictate/whisper_dictate_glossary.txt"


def load_saved_glossary(
    default: str = "", path: Optional[Path] = None
) -> str:
    """Load saved glossary entries from file, or return default if not found."""
    glossary_path = path or GLOSSARY_FILE
    try:
        if glossary_path.is_file():
            content = glossary_path.read_text(encoding="utf-8")
            return content if content.strip() else default
    except Exception as e:  # pragma: no cover - best effort load
        print(f"(Glossary) Could not read saved glossary: {e}")
    return default


def write_saved_glossary(glossary: str, path: Optional[Path] = None) -> bool:
    """Save glossary to file. Returns True on success, False otherwise."""
    glossary_path = path or GLOSSARY_FILE
    try:
        glossary_path.parent.mkdir(parents=True, exist_ok=True)
        glossary_path.write_text(glossary, encoding="utf-8")
        return True
    except Exception as e:  # pragma: no cover - best effort save
        print(f"(Glossary) Could not save glossary: {e}")
        return False
