"""Tests for clipboard snapshot, write and restore."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from whisper_dictate import clipboard


class FakeClipboard:
    """A stand-in for the Win32 clipboard, addressed by fake HGLOBAL handles."""

    def __init__(self, contents: dict[int, bytes] | None = None):
        self.contents = dict(contents or {})
        self.handles: dict[int, bytes] = {}
        self.next_handle = 1000
        self.opens = 0
        self.closes = 0
        self.empties = 0
        self.set_calls: list[tuple[int, bytes]] = []
        self.freed: list[int] = []
        self.null_handle_formats: set[int] = set()

    # --- user32 ---
    def OpenClipboard(self, _hwnd):
        self.opens += 1
        return 1

    def CloseClipboard(self):
        self.closes += 1
        return 1

    def EmptyClipboard(self):
        self.empties += 1
        self.contents.clear()
        return 1

    def EnumClipboardFormats(self, fmt):
        order = sorted(self.contents)
        if fmt == 0:
            return order[0] if order else 0
        index = order.index(fmt)
        return order[index + 1] if index + 1 < len(order) else 0

    def GetClipboardData(self, fmt):
        if fmt in self.null_handle_formats:
            return 0  # delay-rendered
        handle = self._handle_for(self.contents[fmt])
        return handle

    def SetClipboardData(self, fmt, handle):
        self.set_calls.append((fmt, self.handles[handle]))
        self.contents[fmt] = self.handles[handle]
        return handle

    def RegisterClipboardFormatW(self, _name):
        return 49814

    # --- kernel32 ---
    def GlobalAlloc(self, _flags, size):
        self.next_handle += 1
        self.handles[self.next_handle] = b"\x00" * size
        return self.next_handle

    def GlobalLock(self, handle):
        return handle  # the "pointer" is the handle; memmove is patched out

    def GlobalUnlock(self, _handle):
        return 1

    def GlobalSize(self, handle):
        return len(self.handles[handle])

    def GlobalFree(self, handle):
        self.freed.append(handle)
        return 0

    def _handle_for(self, data: bytes) -> int:
        self.next_handle += 1
        self.handles[self.next_handle] = data
        return self.next_handle


@pytest.fixture
def fake(monkeypatch):
    """Patch the module's user32/kernel32 and the two ctypes memory calls."""
    fc = FakeClipboard()
    monkeypatch.setattr(clipboard, "user32", fc)
    monkeypatch.setattr(clipboard, "kernel32", fc)
    monkeypatch.setattr(clipboard.ctypes, "string_at", lambda h, _n: fc.handles[h])

    def fake_memmove(dest, src, length):
        fc.handles[dest] = bytes(src[:length])

    monkeypatch.setattr(clipboard.ctypes, "memmove", fake_memmove)
    return fc


class TestSnapshot:
    def test_copies_every_hglobal_format(self, fake):
        fake.contents = {13: b"text", 49814: b"\x00", 0xC004: b"<html>"}
        assert snapshot_formats(fake) == [13, 0xC004, 49814]

    def test_skips_synthesized_and_gdi_formats(self, fake):
        """CF_BITMAP and friends are re-synthesized by Windows, or are not HGLOBALs."""
        fake.contents = {2: b"bmp", 13: b"text", 14: b"emf", 16: b"locale"}
        assert snapshot_formats(fake) == [13]

    def test_skips_null_handles(self, fake):
        """A delay-rendered format would have to be produced by its owner."""
        fake.contents = {13: b"text", 0xC004: b"<html>"}
        fake.null_handle_formats = {0xC004}
        assert snapshot_formats(fake) == [13]

    def test_closes_the_clipboard_when_a_read_raises(self, fake, monkeypatch):
        """Leaving the clipboard open would lock out every other app."""
        fake.contents = {13: b"text"}
        monkeypatch.setattr(
            fake, "GetClipboardData", MagicMock(side_effect=OSError("boom")), raising=False
        )
        with pytest.raises(OSError):
            clipboard.snapshot()
        assert fake.closes == 1

    def test_raises_when_the_clipboard_stays_locked(self, fake, monkeypatch):
        monkeypatch.setattr(fake, "OpenClipboard", lambda _h: 0, raising=False)
        monkeypatch.setattr(clipboard.time, "sleep", lambda _s: None)
        with pytest.raises(clipboard.ClipboardError):
            clipboard.snapshot()


class TestRestore:
    def test_empties_once_then_sets_each_item(self, fake):
        clipboard.restore([(13, b"text"), (0xC004, b"<html>")])
        assert fake.empties == 1
        assert fake.set_calls == [(13, b"text"), (0xC004, b"<html>")]
        assert fake.closes == 1

    def test_empty_snapshot_restores_an_empty_clipboard(self, fake):
        fake.contents = {13: b"stale"}
        clipboard.restore([])
        assert fake.empties == 1
        assert fake.set_calls == []
        assert fake.contents == {}

    def test_refused_handle_is_freed(self, fake, monkeypatch):
        """Otherwise every failed restore leaks the memory it allocated."""
        monkeypatch.setattr(fake, "SetClipboardData", lambda _f, _h: 0, raising=False)
        clipboard.restore([(13, b"text")])
        assert len(fake.freed) == 1


class TestSetText:
    def test_writes_utf16_and_the_history_exclusion(self, fake):
        clipboard.set_text("hi")
        formats = [fmt for fmt, _ in fake.set_calls]
        assert formats == [clipboard.CF_UNICODETEXT, 49814]
        assert fake.set_calls[0][1] == "hi".encode("utf-16-le") + b"\x00\x00"


def snapshot_formats(_fake) -> list[int]:
    return [fmt for fmt, _ in clipboard.snapshot()]


class TestSendPaste:
    """The keystroke that asks the focused app to read the clipboard."""

    def _capture(self, monkeypatch, accepted: int | None = None):
        sent = []

        def fake_send_input(count, array, size):
            sent.append((size, [array[i] for i in range(count)]))
            return count if accepted is None else accepted

        monkeypatch.setattr(
            clipboard.user32,
            "SendInput",
            fake_send_input,
            raising=False,
        )
        return sent

    def test_insert_is_flagged_extended(self, monkeypatch):
        """The bug: without KEYEVENTF_EXTENDEDKEY, Windows reads this as the
        numpad Insert and strips Shift around it, so nothing ever pastes."""
        sent = self._capture(monkeypatch)
        assert clipboard.send_paste() is True

        size, events = sent[0]
        assert size == 40  # short INPUT structs make SendInput a silent no-op
        keys = [(e.ki.wVk, e.ki.dwFlags) for e in events]
        up = clipboard.KEYEVENTF_KEYUP
        ext = clipboard.KEYEVENTF_EXTENDEDKEY
        assert keys == [
            (clipboard.VK_SHIFT, 0),
            (clipboard.VK_INSERT, ext),
            (clipboard.VK_INSERT, ext | up),
            (clipboard.VK_SHIFT, up),
        ]

    def test_reports_a_refused_injection(self, monkeypatch):
        self._capture(monkeypatch, accepted=0)
        assert clipboard.send_paste() is False


@pytest.mark.skipif(sys.platform != "win32", reason="real Win32 clipboard")
class TestRealWindowsRoundTrip:
    @pytest.fixture(autouse=True)
    def preserve_the_developers_clipboard(self):
        """Running the suite must not cost you whatever you had copied."""
        saved = clipboard.snapshot()
        yield
        clipboard.restore(saved)

    def test_snapshot_survives_a_clobber(self):
        """The whole point: a dictation borrows the clipboard and gives it back."""
        original = "original clipboard content ✓"
        clipboard.set_text(original)
        # A second format, to prove more than plain text comes back.
        extra = clipboard.user32.RegisterClipboardFormatW("WhisperDictateTestFormat")
        saved_with_extra = clipboard.snapshot() + [(extra, b"payload\x00")]
        clipboard.restore(saved_with_extra)

        saved = clipboard.snapshot()
        assert any(fmt == extra for fmt, _ in saved)

        clipboard.set_text("the dictation")
        current = dict(clipboard.snapshot())
        assert current[clipboard.CF_UNICODETEXT].decode("utf-16-le").rstrip("\x00") == (
            "the dictation"
        )

        clipboard.restore(saved)
        restored = dict(clipboard.snapshot())
        assert restored[clipboard.CF_UNICODETEXT].decode("utf-16-le").rstrip("\x00") == original
        assert restored[extra] == b"payload\x00"

    def test_set_text_marks_the_content_excluded_from_history(self):
        clipboard.set_text("not for Win+V")
        marker = clipboard.user32.RegisterClipboardFormatW(clipboard.EXCLUDE_FROM_HISTORY)
        assert any(fmt == marker for fmt, _ in clipboard.snapshot())


@pytest.mark.skipif(sys.platform != "win32", reason="real Win32 clipboard")
def test_open_retries_before_giving_up(monkeypatch):
    """A busy clipboard is normal; giving up on the first refusal is not."""
    attempts = []
    monkeypatch.setattr(
        clipboard,
        "user32",
        SimpleNamespace(OpenClipboard=lambda _h: attempts.append(1) or 0),
    )
    monkeypatch.setattr(clipboard.time, "sleep", lambda _s: None)
    with pytest.raises(clipboard.ClipboardError):
        clipboard._open(retries=5)
    assert len(attempts) == 5
