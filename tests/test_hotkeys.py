"""Tests for hotkey parsing and management."""

from types import SimpleNamespace

import pytest

import whisper_dictate.hotkeys as hotkeys
from whisper_dictate.hotkeys import HotkeyError, HotkeyManager, parse_hotkey_string


class TestHotkeyParsing:
    """Test hotkey string parsing."""

    def test_parse_simple_hotkey(self):
        """Test parsing a simple hotkey."""
        mods, vk = parse_hotkey_string("CTRL+G")
        assert mods == 0x0002  # MOD_CONTROL
        assert vk == ord("G")

    def test_parse_complex_hotkey(self):
        """Test parsing a complex hotkey."""
        mods, vk = parse_hotkey_string("CTRL+WIN+SHIFT+A")
        assert mods == (0x0002 | 0x0008 | 0x0004)  # MOD_CONTROL | MOD_WIN | MOD_SHIFT
        assert vk == ord("A")

    def test_parse_empty_hotkey(self):
        """Test parsing empty hotkey raises error."""
        with pytest.raises(ValueError, match="Empty hotkey"):
            parse_hotkey_string("")

    def test_parse_invalid_modifier(self):
        """Test parsing invalid modifier raises error."""
        with pytest.raises(ValueError, match="Unknown modifier"):
            parse_hotkey_string("INVALID+G")

    def test_parse_invalid_key(self):
        """Test parsing invalid key raises error."""
        with pytest.raises(ValueError, match="Only single A..Z keys supported"):
            parse_hotkey_string("CTRL+1")

    def test_parse_case_insensitive(self):
        """Test that parsing is case insensitive."""
        mods1, vk1 = parse_hotkey_string("ctrl+win+g")
        mods2, vk2 = parse_hotkey_string("CTRL+WIN+G")
        assert mods1 == mods2
        assert vk1 == vk2

    def test_parse_whitespace_handling(self):
        """Test that whitespace is handled correctly."""
        mods1, vk1 = parse_hotkey_string("CTRL+WIN+G")
        mods2, vk2 = parse_hotkey_string(" CTRL + WIN + G ")
        assert mods1 == mods2
        assert vk1 == vk2


class TestHotkeyManager:
    """Test HotkeyManager class."""

    def test_hotkey_manager_init(self):
        """Test HotkeyManager initialization."""
        callback_called = []

        def callback():
            callback_called.append(True)

        manager = HotkeyManager(callback)
        assert manager.callback == callback
        assert manager.msg_thread is None
        assert manager._hotkey_mods is None
        assert manager._hotkey_vk is None

    def test_hotkey_manager_invalid_hotkey(self):
        """Test registering invalid hotkey raises error."""
        manager = HotkeyManager(lambda: None)
        with pytest.raises(HotkeyError):
            manager.register("INVALID")

    def test_hotkey_registration_failure_is_propagated(self, monkeypatch):
        """Ensure register() raises when the OS refuses the hotkey."""

        manager = HotkeyManager(lambda: None)

        failing_user32 = SimpleNamespace(
            RegisterHotKey=lambda *_args, **_kwargs: 0,
            UnregisterHotKey=lambda *_args, **_kwargs: None,
            GetMessageW=lambda *_args, **_kwargs: 0,
            TranslateMessage=lambda *_args, **_kwargs: None,
            DispatchMessageW=lambda *_args, **_kwargs: None,
        )

        monkeypatch.setattr(hotkeys, "user32", failing_user32)

        with pytest.raises(HotkeyError, match="Failed to register hotkey"):
            manager.register("CTRL+G")
