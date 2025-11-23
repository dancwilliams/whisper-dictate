"""Tests for per-application prompt resolution."""

from whisper_dictate import app_prompts
from whisper_dictate.app_context import ActiveContext


def _make_context(process: str | None, window: str | None) -> ActiveContext:
    return ActiveContext(window_title=window, process_name=process, cursor_position=None)


def test_resolve_app_prompt_prefers_window_specific_rule():
    prompts = {
        "notepad.exe": [
            {"window_title_regex": "todo", "prompt": "Todo prompt"},
            {"prompt": "Default notepad prompt"},
        ]
    }
    ctx = _make_context("notepad.exe", "My TODO list")

    result = app_prompts.resolve_app_prompt(prompts, ctx)

    assert result == "Todo prompt"


def test_resolve_app_prompt_falls_back_to_process_default():
    prompts = {"word.exe": [{"prompt": "Word prompt"}]}
    ctx = _make_context("word.exe", "Document1 - Word")

    result = app_prompts.resolve_app_prompt(prompts, ctx)

    assert result == "Word prompt"


def test_resolve_app_prompt_returns_none_when_no_match():
    prompts = {"excel.exe": [{"prompt": "Excel prompt"}]}
    ctx = _make_context("notepad.exe", "Untitled - Notepad")

    result = app_prompts.resolve_app_prompt(prompts, ctx)

    assert result is None


def test_resolve_app_prompt_handles_missing_context():
    prompts = {"notepad.exe": [{"prompt": "Default"}]}

    result = app_prompts.resolve_app_prompt(prompts, None)

    assert result is None


def test_resolve_app_prompt_ignores_invalid_regex():
    prompts = {
        "edge.exe": [
            {"window_title_regex": "[", "prompt": "Broken"},
            {"prompt": "Fallback"},
        ]
    }
    ctx = _make_context("edge.exe", "Welcome")

    result = app_prompts.resolve_app_prompt(prompts, ctx)

    assert result == "Fallback"
