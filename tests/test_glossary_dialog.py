"""Tests for the glossary rule dialog's save-time checks.

These need a real Tk display, so they skip where there is none. The regex
check was covered by hand only until now.
"""

import pytest

tkinter = pytest.importorskip("tkinter")
ttk = pytest.importorskip("tkinter.ttk")

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


class TestCorrectionDialog:
    def test_find_then_save_returns_ticked_rules(self, root) -> None:
        dialog = glossary_dialog.CorrectionDialog(root, "meet me at valida tech, near git hub")
        dialog.text.delete("1.0", "end")
        dialog.text.insert("1.0", "meet me at ValidaTek, near GitHub")
        dialog._on_find()
        assert [r.replacement for _, r in dialog._choices] == ["ValidaTek", "GitHub"]
        dialog._choices[0][0].set(True)
        dialog._on_save()
        typed, rules, cleanup_wrong = dialog.result
        assert typed == "meet me at ValidaTek, near GitHub"
        assert [(r.trigger, r.replacement) for r in rules] == [("valida tech", "ValidaTek")]
        assert cleanup_wrong is False

    def test_proposed_rules_start_unticked(self, root) -> None:
        dialog = glossary_dialog.CorrectionDialog(root, "valida tech")
        dialog.text.delete("1.0", "end")
        dialog.text.insert("1.0", "ValidaTek")
        dialog._on_find()
        assert dialog._choices and all(not var.get() for var, _ in dialog._choices)
        dialog._on_save()
        assert dialog.result[1] == []

    def test_save_enabled_by_an_edit_without_find(self, root) -> None:
        dialog = glossary_dialog.CorrectionDialog(root, "threat fax")
        assert str(dialog.save_button.cget("state")) == "disabled"
        dialog.text.delete("1.0", "end")
        dialog.text.insert("1.0", "threatfax")
        dialog._on_edit()
        assert str(dialog.save_button.cget("state")) == "normal"
        dialog._on_save()
        assert dialog.result == ("threatfax", [], False)

    def test_unchanged_text_keeps_save_disabled(self, root) -> None:
        dialog = glossary_dialog.CorrectionDialog(root, "nothing to fix")
        dialog._on_edit()
        dialog._on_find()
        assert dialog._choices == []
        assert str(dialog.save_button.cget("state")) == "disabled"
        dialog.destroy()

    def test_shows_final_when_it_differs(self, root) -> None:
        def labels(dialog):
            return [
                str(w.cget("text")) for w in dialog.winfo_children() if isinstance(w, ttk.Label)
            ]

        def ticks(dialog):
            return [w for w in dialog.winfo_children() if isinstance(w, ttk.Checkbutton)]

        differs = glossary_dialog.CorrectionDialog(root, "raw", "Final.")
        assert "Heard by Whisper" in labels(differs)
        assert any(t.startswith("Pasted after cleanup: Final.") for t in labels(differs))
        assert len(ticks(differs)) == 1
        differs.destroy()

        same = glossary_dialog.CorrectionDialog(root, "same", "same")
        assert not any(t.startswith("Pasted after cleanup:") for t in labels(same))
        assert ticks(same) == []
        same.destroy()

    def test_cleanup_tick_alone_enables_save(self, root) -> None:
        dialog = glossary_dialog.CorrectionDialog(root, "heard", "Pasted.")
        dialog.cleanup_wrong.set(True)
        dialog._on_edit()
        assert str(dialog.save_button.cget("state")) == "normal"
        dialog._on_save()
        assert dialog.result == ("heard", [], True)

    def test_shows_and_holds_no_grab_when_parent_hidden(self, root) -> None:
        # Opened from the pill, the main window is withdrawn. A transient
        # dialog with a grab would be invisible and lock the pill menu.
        root.withdraw()
        dialog = glossary_dialog.CorrectionDialog(root, "some text")
        root.update()
        assert dialog.winfo_viewable()
        assert dialog.grab_current() is None
        dialog.destroy()
