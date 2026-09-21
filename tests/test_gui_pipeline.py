"""Characterization tests for the dictation pipeline in gui.py.

The app is built with App.__new__, so no Tk interpreter and no display: every
Tk variable and widget the method under test touches is a MagicMock.
"""

import contextlib
import time
from collections import deque
from tkinter import TclError
from unittest.mock import MagicMock

import numpy as np
import pytest

from whisper_dictate import clipboard, gui, llm_cleanup

AUDIO = np.zeros(1600, dtype=np.float32)

VAR_DEFAULTS = {
    "var_vad_enabled": False,
    "var_vad_threshold": 0.5,
    "var_vad_min_speech_ms": 250,
    "var_vad_min_silence_ms": 500,
    "var_vad_speech_pad_ms": 400,
    "var_beam_size": 5,
    "var_compression_ratio_threshold": 2.4,
    "var_log_prob_threshold": -1.0,
    "var_no_speech_threshold": 0.6,
    "var_word_timestamps": False,
    "var_temperature": 0.0,
    "var_initial_prompt": "",
    "var_glossary_enable": False,
    "var_cleanup_backend": "off",
    "var_llm_endpoint": "http://localhost:11434/v1",
    "var_llm_model": "some-model",
    "var_llm_key": "",
    "var_llm_temp": 0.1,
    "var_llm_debug": False,
    "var_history_enable": False,
    "var_history_audio_days": 0,
    "var_asr_backend": "whisper",
    "var_auto_paste": True,
    "var_paste_delay": 0.15,
    "var_restore_delay": 0.6,
}


@pytest.fixture
def mods(mocker):
    """The modules the pipeline reaches out through, mocked."""
    m = MagicMock()
    for name in ("audio", "clipboard", "app_context", "history", "llm_cleanup", "glossary"):
        mocker.patch.object(gui, name, getattr(m, name))
    m.messagebox = mocker.patch.object(gui, "messagebox")
    mocker.patch.object(gui.time, "sleep")
    # The except clauses need real exception classes, not mocks.
    m.clipboard.ClipboardError = clipboard.ClipboardError
    m.llm_cleanup.LLMCleanupError = llm_cleanup.LLMCleanupError

    m.audio.get_audio_buffer.return_value = AUDIO
    m.app_context.get_active_context.return_value = None
    m.glossary.hotwords_for_app.return_value = ""
    m.glossary.apply_glossary.side_effect = lambda text, _manager: text
    m.glossary.load_glossary_manager.return_value.rules = []
    m.clipboard.snapshot.return_value = "SAVED"
    m.clipboard.send_paste.return_value = True
    return m


@pytest.fixture
def make_app(mods):
    def _make(**var_overrides):
        app = gui.App.__new__(gui.App)
        # Tk.__getattr__ falls through to self.tk; None makes a missing
        # attribute an AttributeError instead of infinite recursion.
        app.tk = None
        for name, value in {**VAR_DEFAULTS, **var_overrides}.items():
            var = MagicMock()
            var.get.return_value = value
            setattr(app, name, var)
        for widget in ("txt_out", "btn_toggle", "lbl_status", "indicator", "hotkey_manager"):
            setattr(app, widget, MagicMock())
        app.after = MagicMock()
        app.asr = MagicMock()
        app.asr.get.return_value.transcribe.return_value = "hello world"
        app.s1 = MagicMock()
        app.recent_processes = deque(maxlen=gui.App.RECENT_PROCESSES_MAX)
        app.app_prompts = {}
        app.hotwords_by_app = {}
        app.glossary_manager = mods.glossary.load_glossary_manager.return_value
        app.prompt_content = ""
        app._press_at = 0.0
        app._status_state = "ready"
        app._settings_saved = False
        return app

    return _make


def states(app) -> list[str]:
    return [call.args[0] for call in app.indicator.update.call_args_list]


def messages(app) -> list[str]:
    return [call.args[1] for call in app.indicator.update.call_args_list]


class TestDeliver:
    def test_happy_path_order(self, make_app, mods):
        app = make_app()
        app._deliver("hi")

        assert [c[0] for c in mods.clipboard.mock_calls] == [
            "snapshot",
            "set_text",
            "send_paste",
            "restore",
        ]
        mods.clipboard.set_text.assert_called_once_with("hi")
        mods.clipboard.restore.assert_called_once_with("SAVED")

    def test_set_text_fails(self, make_app, mods):
        mods.clipboard.set_text.side_effect = clipboard.ClipboardError("locked")
        app = make_app()
        app._deliver("hi")

        assert states(app)[-1] == "error"
        mods.clipboard.send_paste.assert_not_called()
        # Nothing was overwritten, so there is nothing to put back.
        mods.clipboard.restore.assert_not_called()

    def test_snapshot_fails(self, make_app, mods):
        mods.clipboard.snapshot.side_effect = clipboard.ClipboardError("locked")
        app = make_app()
        app._deliver("hi")

        mods.clipboard.set_text.assert_called_once_with("hi")
        mods.clipboard.send_paste.assert_called_once()
        mods.clipboard.restore.assert_not_called()

    def test_paste_refused_still_restores(self, make_app, mods):
        mods.clipboard.send_paste.return_value = False
        app = make_app()
        app._deliver("hi")

        assert states(app)[-1] == "error"
        mods.clipboard.restore.assert_called_once_with("SAVED")

    @pytest.mark.xfail(strict=True, reason="B2, fixed in phase 4")
    def test_blank_delay_field_still_restores(self, make_app, mods):
        app = make_app()
        app.var_paste_delay.get.side_effect = TclError('expected floating-point number but got ""')
        with contextlib.suppress(TclError):
            app._deliver("hi")

        mods.clipboard.restore.assert_called_once_with("SAVED")


class TestTranscribeAndClean:
    def test_no_audio(self, make_app, mods):
        mods.audio.get_audio_buffer.return_value = None
        app = make_app()
        app._transcribe_and_clean()

        assert states(app) == ["warning"]
        mods.clipboard.set_text.assert_not_called()

    def test_empty_transcript(self, make_app, mods):
        app = make_app()
        app.asr.get.return_value.transcribe.return_value = ""
        app._transcribe_and_clean()

        assert states(app)[-1] == "warning"
        mods.clipboard.set_text.assert_not_called()

    def test_happy_path_delivers_transcript(self, make_app, mods):
        app = make_app()
        app._transcribe_and_clean()

        mods.clipboard.set_text.assert_called_once_with("hello world")
        assert "hello world" in app.txt_out.insert.call_args.args[1]
        assert states(app)[-1] == "ready"

    def test_endpoint_failure_delivers_raw_text(self, make_app, mods):
        mods.llm_cleanup.clean_with_llm.side_effect = llm_cleanup.LLMCleanupError("down")
        app = make_app(var_cleanup_backend="endpoint")
        app._transcribe_and_clean()

        assert "warning" in states(app)
        mods.clipboard.set_text.assert_called_once_with("hello world")

    def test_endpoint_failure_warning_survives(self, make_app, mods):
        mods.llm_cleanup.clean_with_llm.side_effect = llm_cleanup.LLMCleanupError("down")
        app = make_app(var_cleanup_backend="endpoint")
        app._transcribe_and_clean()

        assert states(app)[-1] == "warning"

    def test_transcription_error(self, make_app, mods):
        app = make_app()
        app.asr.get.return_value.transcribe.side_effect = RuntimeError("boom")
        app._transcribe_and_clean()

        assert states(app)[-1] == "error"
        mods.messagebox.showerror.assert_called_once()
        mods.clipboard.set_text.assert_not_called()


class TestHotkey:
    def test_tap_locks_recording(self, make_app, mods):
        mods.audio.is_recording.return_value = True
        app = make_app()
        app._stop_and_transcribe = MagicMock()
        app._press_at = time.monotonic()
        app._on_hotkey_release()

        app._stop_and_transcribe.assert_not_called()
        mods.audio.stop_recording.assert_not_called()
        assert "locked" in messages(app)[-1]

    def test_hold_transcribes_on_release(self, make_app, mods):
        mods.audio.is_recording.return_value = True
        app = make_app()
        app._stop_and_transcribe = MagicMock()
        app._press_at = time.monotonic() - gui.TAP_SECONDS - 1
        app._on_hotkey_release()

        app._stop_and_transcribe.assert_called_once()

    def test_cancel_discards_buffer(self, make_app, mods):
        mods.audio.is_recording.return_value = True
        app = make_app()
        app._on_hotkey_cancel()

        mods.audio.stop_recording.assert_called_once()
        mods.audio.get_audio_buffer.assert_called_once()
        assert messages(app)[-1] == "Cancelled"
        mods.clipboard.set_text.assert_not_called()


class TestRecentProcesses:
    def test_dedupes_newest_first_and_caps(self, make_app):
        app = make_app()
        app._record_recent_process("a.exe", "one")
        app._record_recent_process("b.exe", "two")
        app._record_recent_process("a.exe", "other title")
        app._record_recent_process(" a.exe ", " one ")  # same entry again, moves to front
        app._record_recent_process("", "ignored")

        assert list(app.recent_processes) == [
            {"process_name": "a.exe", "window_title": "one"},
            {"process_name": "a.exe", "window_title": "other title"},
            {"process_name": "b.exe", "window_title": "two"},
        ]

        for i in range(gui.App.RECENT_PROCESSES_MAX + 5):
            app._record_recent_process(f"p{i}.exe", None)
        assert len(app.recent_processes) == gui.App.RECENT_PROCESSES_MAX
        assert app.recent_processes[0]["process_name"] == f"p{gui.App.RECENT_PROCESSES_MAX + 4}.exe"


class TestOnClose:
    @pytest.mark.xfail(strict=True, reason="B2, fixed in phase 4")
    def test_failed_save_is_not_marked_saved(self, make_app):
        app = make_app()
        app._save_settings = MagicMock(side_effect=TclError("blank field"))
        app.destroy = MagicMock()
        with contextlib.suppress(TclError):
            app._on_close()

        assert app._settings_saved is False
        app.destroy.assert_called_once()
