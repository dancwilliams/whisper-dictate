"""Tests for reading back the pasted-into control. No COM: the UI Automation
target is faked, so these run on CI."""

import sys
import threading

import pytest

from whisper_dictate import readback

PASTED = "the cat sat on the mat today"


class TestEditedSpan:
    def test_unchanged_paste_inside_a_longer_field(self):
        field = f"earlier words here {PASTED} and later words"
        assert readback.edited_span(field, PASTED) == PASTED.split()

    def test_middle_word_swapped(self):
        field = f"hello there {PASTED.replace('mat', 'rug')} bye"
        assert readback.edited_span(field, PASTED) == "the cat sat on the rug today".split()

    def test_first_word_swapped_is_included(self):
        assert readback.edited_span("Jon met me today", "John met me today") == [
            "Jon",
            "met",
            "me",
            "today",
        ]

    def test_text_typed_after_the_paste_is_not_in_the_span(self):
        assert readback.edited_span("hello world and more", "hello world") == ["hello", "world"]

    def test_paste_deleted_from_the_field_returns_none(self):
        assert readback.edited_span("something else entirely", "hello world") is None

    def test_rewrite_keeping_two_of_ten_words_returns_none(self):
        pasted = "one two three four five six seven eight nine ten"
        assert readback.edited_span("one two completely different words now", pasted) is None

    def test_common_words_in_a_long_document_do_not_stretch_the_span(self):
        # The paste has one swap, so difflib looks for "mat" and "today" elsewhere
        # and finds them in sentences far from the paste. The SLACK guard drops them.
        filler = " ".join(f"the dog saw the mat today number {i}" for i in range(40))
        field = f"{filler} the cat sat on the rug today {filler}"
        assert readback.edited_span(field, PASTED) == "the cat sat on the rug today".split()

    def test_empty_paste_returns_none(self):
        assert readback.edited_span("anything at all", "   ") is None


class TestMapToRaw:
    def test_swap_lands_on_raw_case_insensitively(self):
        assert (
            readback.map_to_raw("I met jon today.", "I met Jon today.", "I met John today.")
            == "I met John today."
        )

    def test_trigger_missing_from_raw_returns_none(self):
        assert readback.map_to_raw("i saw the guy", "I saw Jon.", "I saw John.") is None

    def test_insertion_only_returns_none(self):
        assert readback.map_to_raw("i met jon", "I met Jon.", "I met Jon again.") is None

    def test_two_swaps_both_land(self):
        assert (
            readback.map_to_raw("jon and sue left", "Jon and Sue left.", "John and Sal left.")
            == "John and Sal left"
        )


class FakeTarget:
    """Scripted reads and focus answers in place of a UI Automation element."""

    def __init__(self, reads, focused=None):
        self.reads = list(reads)
        self.focused = list(focused or [])

    def read(self):
        return self.reads.pop(0) if self.reads else None

    def still_focused(self):
        return self.focused.pop(0) if self.focused else True


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(readback, "POLL_SECONDS", 0)
    monkeypatch.setattr(readback.time, "sleep", lambda s: None)


class TestFind:
    def test_retries_until_the_paste_is_in_the_text(self, monkeypatch, fast):
        fake = FakeTarget([None, f"stuff {PASTED}"])
        monkeypatch.setattr(readback, "_Target", lambda uia, element, iface: fake)
        uia = type("Uia", (), {"GetFocusedElement": lambda self: object()})()
        assert readback._find(uia, None, PASTED) is fake

    def test_gives_up_when_the_paste_never_appears(self, monkeypatch, fast):
        fake = FakeTarget(["not it"] * 5)
        monkeypatch.setattr(readback, "_Target", lambda uia, element, iface: fake)
        uia = type("Uia", (), {"GetFocusedElement": lambda self: object()})()
        assert readback._find(uia, None, PASTED) is None


class TestWatch:
    def test_empty_read_ends_the_watch_and_the_last_snapshot_wins(self, fast):
        edited = PASTED.replace("mat", "rug")
        target = FakeTarget([PASTED, edited, ""])
        assert readback._watch(target, PASTED, threading.Event()) == edited

    def test_unchanged_then_focus_lost_returns_none(self, fast):
        target = FakeTarget([PASTED, PASTED], focused=[True, True, False])
        assert readback._watch(target, PASTED, threading.Event()) is None

    def test_stop_before_the_first_poll_returns_none(self, fast):
        stop = threading.Event()
        stop.set()
        target = FakeTarget([PASTED.replace("mat", "rug")])
        assert readback._watch(target, PASTED, stop) is None


def test_run_off_windows_returns_none_without_comtypes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "comtypes", None)  # any import would raise
    assert readback.run("hello", threading.Event()) is None
