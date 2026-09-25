"""Tests for chord parsing and the keyboard-hook hotkey manager."""

from types import SimpleNamespace

import pytest

import whisper_dictate.hotkeys as hotkeys
from whisper_dictate.hotkeys import Chord, HotkeyError, HotkeyManager, parse_chord

LCTRL, RCTRL = 0xA2, 0xA3
LWIN, RWIN = 0x5B, 0x5C
SPACE = 0x20
RIGHT_ARROW = 0x27


def chord(s: str) -> Chord:
    return Chord(parse_chord(s))


class TestParseChord:
    """Test chord string parsing."""

    def test_modifier_only(self):
        """A chord may be nothing but modifiers - RegisterHotKey could not do this."""
        assert parse_chord("CTRL+WIN") == [{LCTRL, RCTRL}, {LWIN, RWIN}]

    def test_named_key(self):
        """SPACE is spelled out rather than given as a character."""
        assert parse_chord("CTRL+SPACE") == [{LCTRL, RCTRL}, {SPACE}]

    def test_letter_key(self):
        """A single letter still works, for the chord Dan had saved."""
        assert parse_chord("CTRL+WIN+G") == [{LCTRL, RCTRL}, {LWIN, RWIN}, {ord("G")}]

    def test_case_and_whitespace_insensitive(self):
        assert parse_chord(" ctrl + win ") == parse_chord("CTRL+WIN")

    def test_empty(self):
        with pytest.raises(ValueError, match="Empty hotkey"):
            parse_chord("")

    def test_unknown_key(self):
        with pytest.raises(ValueError, match="Unknown key"):
            parse_chord("CTRL+NOPE")


class TestChordFeed:
    """Test the pure key-state tracker."""

    def test_press_when_all_parts_are_down(self):
        c = chord("CTRL+WIN")
        assert c.feed(LCTRL, True) is None
        assert c.feed(LWIN, True) == "press"

    def test_release_of_either_key_releases(self):
        for released in (LCTRL, LWIN):
            c = chord("CTRL+WIN")
            c.feed(LCTRL, True)
            c.feed(LWIN, True)
            assert c.feed(released, False) == "release"

    def test_right_hand_variants_complete_the_chord(self):
        c = chord("CTRL+WIN")
        c.feed(RCTRL, True)
        assert c.feed(LWIN, True) == "press"

    def test_other_key_cancels_and_later_releases_are_silent(self):
        """Ctrl+Win+Right is a virtual-desktop switch, not a dictation."""
        c = chord("CTRL+WIN")
        c.feed(LCTRL, True)
        c.feed(LWIN, True)
        assert c.feed(RIGHT_ARROW, True) == "cancel"
        assert c.feed(RIGHT_ARROW, False) is None
        assert c.feed(LWIN, False) is None
        assert c.feed(LCTRL, False) is None

    def test_chord_only_starts_from_a_clean_state(self):
        """Holding Ctrl+Win+D and releasing D must not start a recording."""
        c = chord("CTRL+WIN")
        c.feed(LCTRL, True)
        c.feed(LWIN, True)  # press
        c.feed(ord("D"), True)  # cancel
        assert c.feed(ord("D"), False) is None

    def test_re_press_after_release_fires_again(self):
        c = chord("CTRL+WIN")
        c.feed(LCTRL, True)
        c.feed(LWIN, True)
        c.feed(LWIN, False)
        assert c.feed(LWIN, True) == "press"

    def test_unrelated_key_before_the_chord_blocks_it(self):
        c = chord("CTRL+WIN")
        c.feed(ord("A"), True)
        c.feed(LCTRL, True)
        assert c.feed(LWIN, True) is None

    def test_resync_forgets_releases_the_lock_screen_ate(self):
        c = chord("CTRL+WIN")
        c.feed(LWIN, True)
        c.feed(ord("L"), True)  # Win+L: both key-ups go to the lock screen
        c.resync(lambda vk: False)
        assert c.feed(LCTRL, True) is None
        assert c.feed(LWIN, True) == "press"

    def test_resync_keeps_keys_still_held(self):
        c = chord("CTRL+WIN")
        c.feed(LCTRL, True)
        c.resync(lambda vk: vk == LCTRL)
        assert c.feed(LWIN, True) == "press"


class TestChordSwallows:
    """Test which keys are eaten rather than passed to the focused app."""

    def test_space_is_swallowed_only_while_ctrl_is_down(self):
        c = chord("CTRL+SPACE")
        assert c.swallows(SPACE) is False
        c.feed(LCTRL, True)
        assert c.swallows(SPACE) is True
        c.feed(LCTRL, False)
        assert c.swallows(SPACE) is False

    def test_modifiers_are_never_swallowed(self):
        """Eating Ctrl or Win would break every other shortcut on the system."""
        c = chord("CTRL+SPACE")
        c.feed(LCTRL, True)
        assert c.swallows(LCTRL) is False

    def test_keys_outside_the_chord_are_never_swallowed(self):
        c = chord("CTRL+SPACE")
        c.feed(LCTRL, True)
        assert c.swallows(ord("A")) is False


class TestHotkeyManager:
    """Test the manager's dispatch and registration."""

    def test_init(self):
        manager = HotkeyManager(lambda: None)
        assert manager.chord is None
        assert manager.msg_thread is None

    def test_invalid_chord(self):
        manager = HotkeyManager(lambda: None)
        with pytest.raises(HotkeyError, match="Invalid hotkey"):
            manager.register("CTRL+NOPE")

    def test_registration_failure_is_propagated(self, monkeypatch):
        """Ensure register() raises when Windows refuses the hook."""
        manager = HotkeyManager(lambda: None)

        failing_user32 = SimpleNamespace(
            SetWindowsHookExW=lambda *_a, **_k: 0,
            UnhookWindowsHookEx=lambda *_a, **_k: None,
            CallNextHookEx=lambda *_a, **_k: 0,
            PostThreadMessageW=lambda *_a, **_k: None,
            GetMessageW=lambda *_a, **_k: 0,
            TranslateMessage=lambda *_a, **_k: None,
            DispatchMessageW=lambda *_a, **_k: None,
        )
        monkeypatch.setattr(hotkeys, "user32", failing_user32)

        with pytest.raises(HotkeyError, match="Failed to install the keyboard hook"):
            manager.register("CTRL+WIN")

    def _keyboard(self, monkeypatch, manager):
        """A fake keyboard: Windows' physical key state, then the hook event."""
        held: set[int] = set()
        monkeypatch.setattr(hotkeys, "key_held", held.__contains__)

        def key(vk, is_down):
            (held.add if is_down else held.discard)(vk)
            manager._handle(vk, is_down)

        return key

    def test_handle_dispatches_press_release_and_cancel(self, monkeypatch):
        events = []
        manager = HotkeyManager(
            lambda: events.append("press"),
            lambda: events.append("release"),
            lambda: events.append("cancel"),
        )
        manager.chord = chord("CTRL+WIN")
        key = self._keyboard(monkeypatch, manager)

        key(LCTRL, True)
        key(LWIN, True)
        key(RIGHT_ARROW, True)
        key(LWIN, False)
        key(LCTRL, False)
        key(LCTRL, True)
        key(LWIN, True)
        key(LWIN, False)

        assert events == ["press", "cancel", "press", "release"]

    def test_handle_resyncs_against_windows_first(self, monkeypatch):
        events = []
        manager = HotkeyManager(lambda: events.append("press"))
        manager.chord = chord("CTRL+WIN")
        key = self._keyboard(monkeypatch, manager)
        manager.chord.down, manager.chord.blocked = {LWIN}, True  # stale, from Win+L

        key(LCTRL, True)
        key(LWIN, True)
        assert events == ["press"]

    def test_optional_callbacks_may_be_omitted(self):
        """A manager with only on_press must not blow up on a release."""
        manager = HotkeyManager(lambda: None)
        manager.chord = chord("CTRL+WIN")
        manager._handle(LCTRL, True)
        manager._handle(LWIN, True)
        manager._handle(LWIN, False)

    def test_register_records_the_live_chord_and_replaces_it(self, monkeypatch):
        """The GUI compares chord_string to spot an edited setting."""
        unhooked = []
        fake_user32 = SimpleNamespace(
            SetWindowsHookExW=lambda *_a, **_k: 4242,
            UnhookWindowsHookEx=lambda hook: unhooked.append(hook),
            CallNextHookEx=lambda *_a, **_k: 0,
            PostThreadMessageW=lambda *_a, **_k: None,
            GetMessageW=lambda *_a, **_k: 0,  # returns WM_QUIT immediately
            TranslateMessage=lambda *_a, **_k: None,
            DispatchMessageW=lambda *_a, **_k: None,
        )
        monkeypatch.setattr(hotkeys, "user32", fake_user32)

        manager = HotkeyManager(lambda: None)
        manager.register("CTRL+SPACE")
        assert manager.chord_string == "CTRL+SPACE"

        # Re-registering must take down the first hook, or both would fire.
        manager.register("CTRL+WIN")
        assert manager.chord_string == "CTRL+WIN"
        manager.unregister()  # joins the pump, so the second unhook has landed
        assert unhooked == [4242, 4242]

    def test_modifiers_up_asks_windows_not_the_tracker(self, monkeypatch):
        """The paste path waits on this before injecting Shift+Insert.

        It reports the physical key state, because that is what Windows folds
        into an injected keystroke - the tracker only knows the chord's own keys.
        """
        manager = HotkeyManager(lambda: None)

        monkeypatch.setattr(hotkeys, "modifiers_held", lambda: False)
        assert manager.modifiers_up() is True

        # A modifier the chord knows nothing about still blocks the paste.
        monkeypatch.setattr(hotkeys, "modifiers_held", lambda: True)
        assert manager.modifiers_up() is False


class TestModifiersHeld:
    """Physical modifier state, read from Windows."""

    def _states(self, monkeypatch, down: set[int]):
        monkeypatch.setattr(
            hotkeys,
            "user32",
            SimpleNamespace(GetAsyncKeyState=lambda vk: -32768 if vk in down else 0),
        )

    def test_false_when_nothing_is_held(self, monkeypatch):
        self._states(monkeypatch, set())
        assert hotkeys.modifiers_held() is False

    def test_true_for_each_modifier(self, monkeypatch):
        for vk in hotkeys.MODIFIER_STATE_VKS:
            self._states(monkeypatch, {vk})
            assert hotkeys.modifiers_held() is True, hex(vk)

    def test_ignores_the_low_bit(self, monkeypatch):
        """GetAsyncKeyState's low bit means 'pressed since last call', not 'down'."""
        monkeypatch.setattr(hotkeys, "user32", SimpleNamespace(GetAsyncKeyState=lambda _vk: 1))
        assert hotkeys.modifiers_held() is False


def test_no_key_codes_are_logged():
    """The hook sees every keystroke on the system; it must stay silent."""
    source = (hotkeys.__file__.replace(".pyc", ".py"),)
    with open(source[0], encoding="utf-8") as fh:
        body = fh.read()
    assert "print(" not in body
    assert "logger" not in body
