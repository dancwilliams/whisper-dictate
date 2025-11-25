import re

from whisper_dictate import app_prompt_dialog


class FakeListbox:
    def __init__(self, selection):
        self.selection = selection

    def curselection(self):
        return () if self.selection is None else (self.selection,)


class DummyEntryDialog:
    last_initial = None

    def __init__(self, parent, entry):
        DummyEntryDialog.last_initial = entry
        self.result = entry

    def wait_window(self):
        return None


def test_prepare_recent_entries_and_labels():
    dialog = app_prompt_dialog.AppPromptDialog.__new__(app_prompt_dialog.AppPromptDialog)
    dialog._recent_entries = []

    dialog._prepare_recent_entries(
        [
            " chrome.exe ",
            {"process_name": "slack.exe", "window_title": "Daily sync"},
            {"process_name": "", "window_title": "ignored"},
            {"process_name": "obs64.exe", "window_title": None},
        ]
    )

    labels = []
    for entry in dialog._recent_entries:
        label = entry["process_name"]
        if entry.get("window_title"):
            label = f"{label} — {entry['window_title']}"
        labels.append(label)

    assert labels == ["chrome.exe", "slack.exe — Daily sync", "obs64.exe"]


def test_add_from_recent_prefills_window_regex(monkeypatch):
    dialog = app_prompt_dialog.AppPromptDialog.__new__(app_prompt_dialog.AppPromptDialog)
    dialog.entries = []
    dialog._recent_entries = [
        {"process_name": "chrome.exe", "window_title": None},
        {"process_name": "slack.exe", "window_title": "Daily standup"},
    ]
    dialog.lst_recent = FakeListbox(selection=1)
    dialog._refresh_tree = lambda: None

    monkeypatch.setattr(app_prompt_dialog, "AppPromptEntryDialog", DummyEntryDialog)

    dialog._on_add_from_recent()

    assert DummyEntryDialog.last_initial == {
        "process_name": "slack.exe",
        "window_title_regex": f"^{re.escape('Daily standup')}$",
    }
    assert dialog.entries[-1] == DummyEntryDialog.last_initial


def test_add_from_recent_skips_window_regex_when_missing(monkeypatch):
    dialog = app_prompt_dialog.AppPromptDialog.__new__(app_prompt_dialog.AppPromptDialog)
    dialog.entries = []
    dialog._recent_entries = [
        {"process_name": "chrome.exe", "window_title": None},
        {"process_name": "notepad.exe", "window_title": None},
    ]
    dialog.lst_recent = FakeListbox(selection=0)
    dialog._refresh_tree = lambda: None

    monkeypatch.setattr(app_prompt_dialog, "AppPromptEntryDialog", DummyEntryDialog)

    dialog._on_add_from_recent()

    assert DummyEntryDialog.last_initial == {"process_name": "chrome.exe"}
    assert dialog.entries[-1] == DummyEntryDialog.last_initial
