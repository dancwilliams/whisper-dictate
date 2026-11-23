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

    def test_a_half_deleted_word_is_not_a_swap(self):
        """Seen in Teams: a poll mid-backspace banked "rewrite" -> "rewrit"."""
        assert readback.map_to_raw("a rewrite", "A rewrite.", "A rewrit") is None
        assert readback.map_to_raw("a rewrite", "A rewrite.", "A write") is None

    def test_a_longer_word_is_still_a_swap(self):
        assert readback.map_to_raw("one test", "One test.", "One tests.") == "one tests"

    def test_two_swaps_both_land(self):
        assert (
            readback.map_to_raw("jon and sue left", "Jon and Sue left.", "John and Sal left.")
            == "John and Sal left"
        )

    def test_backslash_in_edited_word_is_literal(self):
        assert (
            readback.map_to_raw("open path now", "Open path now.", r"Open C:\new\1 now.")
            == r"open C:\new\1 now"
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
        monkeypatch.setattr(readback, "_focused", lambda uia, iface: fake)
        assert readback._find(None, None, PASTED) is fake

    def test_gives_up_when_the_paste_never_appears(self, monkeypatch, fast):
        fake = FakeTarget(["not it"] * 5)
        monkeypatch.setattr(readback, "_focused", lambda uia, iface: fake)
        assert readback._find(None, None, PASTED) is None


class TestFocused:
    """UIA stand-ins: GetCurrentPattern returns a null pointer whose
    QueryInterface raises, as the real client does for an unsupported pattern."""

    class Null:
        def QueryInterface(self, iface):
            raise ValueError("NULL COM pointer access")

    class Pattern:
        def QueryInterface(self, iface):
            return self

    class Element:
        def __init__(self, readable, inner=None):
            self.readable, self.inner = readable, inner

        def GetCurrentPattern(self, pid):
            return TestFocused.Pattern() if self.readable else TestFocused.Null()

        def FindFirst(self, scope, cond):
            return self.inner

    def _uia(self, focused):
        return type(
            "Uia",
            (),
            {
                "GetFocusedElement": lambda self: focused,
                "CreatePropertyCondition": lambda self, pid, value: (pid, value),
            },
        )()

    def test_readable_focus_is_used_as_is(self):
        element = self.Element(readable=True)
        assert readback._focused(self._uia(element), None).element is element

    def test_unreadable_host_pane_yields_its_focused_descendant(self):
        inner = self.Element(readable=True)
        host = self.Element(readable=False, inner=inner)
        assert readback._focused(self._uia(host), None).element is inner

    def test_unreadable_pane_with_nothing_inside_stays(self):
        host = self.Element(readable=False)
        assert readback._focused(self._uia(host), None).element is host


class TestWatch:
    def test_empty_read_ends_the_watch_and_the_settled_snapshot_wins(self, fast):
        edited = PASTED.replace("mat", "rug")
        target = FakeTarget([PASTED, edited, edited, ""])
        assert readback._watch(target, PASTED, threading.Event()) == edited

    def test_a_span_seen_once_is_mid_keystroke_and_does_not_count(self, fast):
        """Backspacing through the paste: each poll sees a shorter word, then
        the paste is gone. None of those partial words may be banked."""
        target = FakeTarget([PASTED, PASTED.replace("today", "toda"), "x", "x"])
        assert readback._watch(target, PASTED, threading.Event()) is None

    def test_unchanged_then_focus_lost_returns_none(self, fast):
        target = FakeTarget([PASTED, PASTED], focused=[True, True, False])
        assert readback._watch(target, PASTED, threading.Event()) is None

    def test_stop_before_the_first_poll_returns_none(self, fast):
        stop = threading.Event()
        stop.set()
        target = FakeTarget([PASTED.replace("mat", "rug")])
        assert readback._watch(target, PASTED, stop) is None

    def test_paste_gone_twice_ends_the_watch(self, fast):
        """Teams shows a placeholder after Send, so the box never reads as empty."""
        edited = PASTED.replace("mat", "rug")
        target = FakeTarget([edited, edited, "Type a message", "Type a message", PASTED])
        assert readback._watch(target, PASTED, threading.Event()) == edited
        assert target.reads == [PASTED]  # the fifth read never happened

    def test_one_miss_is_mid_edit_and_the_watch_goes_on(self, fast):
        edited = PASTED.replace("mat", "rug")
        target = FakeTarget([PASTED, "the cat", edited, edited, ""])
        assert readback._watch(target, PASTED, threading.Event()) == edited


class TestStillFocused:
    def _target(self, has_focus, own_pid, focused_pid):
        element = type("E", (), {"CurrentHasKeyboardFocus": has_focus, "CurrentProcessId": own_pid})
        focused = type("F", (), {"CurrentProcessId": focused_pid})
        uia = type("Uia", (), {"GetFocusedElement": lambda self: focused})()
        target = readback._Target.__new__(readback._Target)
        target.uia, target.element = uia, element
        return target

    def test_focused_node_in_the_foreground_process(self):
        assert self._target(True, 7, 7).still_focused() is True

    def test_focused_node_in_a_background_window_is_not_focused(self):
        """Chromium keeps reporting its focused node after the window loses focus."""
        assert self._target(True, 7, 9).still_focused() is False

    def test_focus_moved_within_the_process(self):
        assert self._target(False, 7, 7).still_focused() is False


def test_run_off_windows_returns_none_without_comtypes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "comtypes", None)  # any import would raise
    assert readback.run("hello", threading.Event()) is None


def test_run_skips_a_terminal_without_comtypes(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "comtypes", None)  # any import would raise
    with caplog.at_level("INFO", logger="whisper_dictate"):
        assert readback.run("hello", threading.Event(), "WindowsTerminal.exe") is None
    assert "Read-back: WindowsTerminal.exe not readable" in caplog.text


OBJECT = chr(0xFFFC)  # what Chromium reports for an embedded object


@pytest.mark.parametrize(
    ("before", "space"),
    [
        (None, False),
        ("", False),
        ("\n", False),
        (". ", False),
        ("d ", False),
        ("(", False),
        ('"', False),
        ("\n" + OBJECT, False),
        ("d.", True),
        ("d,", True),
        ("lo", True),
    ],
)
def test_needs_space(before, space):
    assert readback.needs_space(before) is space


class FakeRange:
    """A text range over `text` with the caret (or selection) at [start, end)."""

    def __init__(self, text, start, end):
        self.text, self.start, self.end = text, start, end

    def Clone(self):
        return FakeRange(self.text, self.start, self.end)

    def _get(self, endpoint):
        return self.start if endpoint == readback.ENDPOINT_START else self.end

    def MoveEndpointByRange(self, endpoint, other, other_endpoint):
        if endpoint == readback.ENDPOINT_START:
            self.start = other._get(other_endpoint)
        else:
            self.end = other._get(other_endpoint)

    def MoveEndpointByUnit(self, endpoint, unit, count):
        assert (endpoint, unit) == (readback.ENDPOINT_START, readback.UNIT_CHARACTER)
        self.start = max(0, self.start + count)  # like Chromium, may leave the field

    def CompareEndpoints(self, endpoint, other, other_endpoint):
        return self._get(endpoint) - other._get(other_endpoint)

    def GetText(self, limit):
        return self.text[self.start : self.end][:limit]


class TestCaretReads:
    @pytest.fixture
    def focus(self, monkeypatch):
        """Point the reads at a fake control; returns a setter for its selection."""
        com = type("Com", (), {"CoInitialize": staticmethod(lambda: None)})
        com.CoUninitialize = staticmethod(lambda: None)
        monkeypatch.setitem(sys.modules, "comtypes", com)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(readback, "_client", lambda: (None, None))
        holder = {}

        def set_focus(ranges, has_text=True, field=None):
            pattern = type("P", (), {})()
            pattern.DocumentRange = field or FakeRange("", 0, 0)
            pattern.GetSelection = lambda: type(
                "Arr", (), {"Length": len(ranges), "GetElement": lambda self, i: ranges[i]}
            )()
            target = type("T", (), {"text": pattern if has_text else None})()
            holder["target"] = target

        monkeypatch.setattr(readback, "_focused", lambda uia, iface: holder["target"])
        return set_focus

    def test_two_characters_ahead_of_the_caret(self, focus):
        focus([FakeRange("Hello there.", 12, 12)])
        assert readback.before_caret() == "e."

    def test_caret_at_the_start_of_the_field(self, focus):
        focus([FakeRange("Hello", 0, 0)])
        assert readback.before_caret() == ""

    def test_caret_read_uses_the_selection_start(self, focus):
        focus([FakeRange("ab cd ef", 3, 5)])
        assert readback.before_caret() == "b "

    def test_empty_field_does_not_read_the_page_before_it(self, focus):
        page = "Type a message"  # Teams: the field starts where the page text ends
        focus([FakeRange(page, 14, 14)], field=FakeRange(page, 14, 14))
        assert readback.before_caret() == ""

    def test_one_character_into_the_field(self, focus):
        page = "outside" + "a"
        focus([FakeRange(page, 8, 8)], field=FakeRange(page, 7, 8))
        assert readback.before_caret() == "a"

    def test_value_only_control_has_no_caret(self, focus):
        focus([FakeRange("x", 1, 1)], has_text=False)
        assert readback.before_caret() is None
        assert readback.selection() is None

    def test_no_selection_ranges(self, focus):
        focus([])
        assert readback.before_caret() is None

    def test_selection_text(self, focus):
        focus([FakeRange("keep this part", 5, 9)])
        assert readback.selection() == "this"

    def test_empty_or_oversized_selection_is_none(self, focus):
        focus([FakeRange("abc", 1, 1)])
        assert readback.selection() is None
        focus([FakeRange("x" * 50, 0, 50)])
        assert readback.selection(limit=10) is None

    def test_com_error_is_none(self, focus, monkeypatch):
        def boom():
            raise OSError("COM gone")

        monkeypatch.setattr(readback, "_client", boom)
        assert readback.before_caret() is None
