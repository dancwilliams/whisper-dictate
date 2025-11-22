"""Glossary management for LLM cleanup."""

from pathlib import Path

GLOSSARY_FILE = Path.home() / ".whisper_dictate/whisper_dictate_glossary.txt"


def load_saved_glossary(default: str = "") -> str:
    """Load saved glossary entries from file, or return default if not found."""
    try:
        if GLOSSARY_FILE.is_file():
            content = GLOSSARY_FILE.read_text(encoding="utf-8")
            return content if content.strip() else default
    except Exception as e:  # pragma: no cover - best effort load
        print(f"(Glossary) Could not read saved glossary: {e}")
    return default


def write_saved_glossary(glossary: str) -> bool:
    """Save glossary to file. Returns True on success, False otherwise."""
    try:
        GLOSSARY_FILE.parent.mkdir(parents=True, exist_ok=True)
        GLOSSARY_FILE.write_text(glossary, encoding="utf-8")
        return True
    except Exception as e:  # pragma: no cover - best effort save
        print(f"(Glossary) Could not save glossary: {e}")
        return False
