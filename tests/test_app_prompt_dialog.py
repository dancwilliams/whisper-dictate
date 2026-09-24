"""Tests for the per-app prompt entry dialog's save-time checks.

These need a real Tk display, so they skip where there is none. The regex
check was covered by hand only until now.
"""

import pytest

tkinter = pytest.importorskip("tkinter")

from whisper_dictate import app_prompt_dialog  # noqa: E402
from whisper_dictate.app_prompt_dialog import AppPromptEntryDialog  # noqa: E402


@pytest.fixture
def root():
    # Same shape as tests/test_gui_components.py: Tk() now and then fails to
    # source its own library files under pytest's fd capture; a retry works.
    for attempt in range(3):
        try:
            window = tkinter.Tk()
            break
        except tkinter.TclError as e:
            if attempt == 2:  # pragma: no cover - headless CI
                pytest.skip(f"no display available: {e}")
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tkinter.TclError:
        pass


@pytest.fixture
def errors(monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        app_prompt_dialog.messagebox, "showerror", lambda _title, message: shown.append(message)
    )
    return shown


def make(root, regex: str) -> AppPromptEntryDialog:
    dialog = AppPromptEntryDialog(root)
    dialog.var_process.set("notepad.exe")
    dialog.txt_prompt.insert("1.0", "Tidy this up.")
    dialog.var_window_regex.set(regex)
    return dialog


class TestSave:
    def test_a_regex_that_will_not_compile_is_refused(self, root, errors):
        dialog = make(root, "(unclosed")

        dialog._on_save()

        assert len(errors) == 1
        assert errors[0].startswith("Window title regex:")
        assert dialog.result is None
        assert dialog.winfo_exists()

    def test_a_pattern_the_old_validator_refused_is_accepted(self, root, errors):
        """(\\w+ )?Report - Word was 'nested repetition' to the deleted heuristic."""
        dialog = make(root, r"(\w+ )?Report - Word")

        dialog._on_save()

        assert errors == []
        assert dialog.result is not None
        assert dialog.result["window_title_regex"] == r"(\w+ )?Report - Word"
        assert not dialog.winfo_exists()
