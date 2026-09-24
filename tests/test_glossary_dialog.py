"""Tests for the glossary rule dialog's save-time checks.

These need a real Tk display, so they skip where there is none. The regex
check was covered by hand only until now.
"""

import pytest

tkinter = pytest.importorskip("tkinter")

from whisper_dictate import glossary_dialog  # noqa: E402
from whisper_dictate.glossary_dialog import GlossaryRuleDialog  # noqa: E402


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
        glossary_dialog.messagebox, "showerror", lambda _title, message: shown.append(message)
    )
    return shown


def make(root, trigger: str) -> GlossaryRuleDialog:
    dialog = GlossaryRuleDialog(root)
    dialog.var_match_type.set("regex")
    dialog.var_trigger.set(trigger)
    dialog.var_replacement.set("GPT-4")
    return dialog


class TestSave:
    def test_a_regex_that_will_not_compile_is_refused(self, root, errors):
        dialog = make(root, "(unclosed")

        dialog._on_save()

        assert len(errors) == 1
        assert errors[0].startswith("Not a valid regular expression:")
        assert dialog.result is None
        assert dialog.winfo_exists()

    def test_a_valid_regex_is_saved(self, root, errors):
        dialog = make(root, r"gpt-?4")

        dialog._on_save()

        assert errors == []
        assert dialog.result is not None
        assert dialog.result.trigger == r"gpt-?4"
        assert dialog.result.match_type == "regex"
        assert not dialog.winfo_exists()
