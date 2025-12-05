"""Prompt management for LLM cleanup."""

from pathlib import Path

from whisper_dictate.config import DEFAULT_LLM_PROMPT

PROMPT_FILE = Path.home() / ".whisper_dictate/whisper_dictate_prompt.txt"


def load_saved_prompt(default: str = DEFAULT_LLM_PROMPT) -> str:
    """Load saved prompt from file, or return default if not found."""
    try:
        if PROMPT_FILE.is_file():
            content = PROMPT_FILE.read_text(encoding="utf-8")
            return content if content.strip() else default
    except (OSError, UnicodeDecodeError) as e:
        # OSError: File access errors (permission, not found, etc.)
        # UnicodeDecodeError: Invalid UTF-8 encoding
        print(f"(Prompt) Could not read saved prompt: {e}")
    return default


def write_saved_prompt(prompt: str) -> bool:
    """Save prompt to file. Returns True on success, False otherwise."""
    try:
        PROMPT_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROMPT_FILE.write_text(prompt, encoding="utf-8")
        return True
    except (OSError, UnicodeEncodeError) as e:
        # OSError: File/directory creation or write errors
        # UnicodeEncodeError: Invalid character encoding
        print(f"(Prompt) Could not save prompt: {e}")
        return False

