"""Characterization tests for the dictation pipeline in gui.py.

The app is built with App.__new__, so no Tk interpreter and no display: every
Tk variable and widget the method under test touches is a MagicMock.
"""

import threading
import time
from collections import deque
from tkinter import TclError
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from whisper_dictate import clipboard, gui, llm_cleanup

AUDIO = np.zeros(1600, dtype=np.float32)

VAR_DEFAULTS = {
    "var_model": "small",
    "var_asr_backend": "whisper",
    "var_idle_ttl_minutes": 5.0,
    "var_history_enable": False,
    "var_history_audio_days": 0,
    "var_device": "cuda",
    "var_compute": "float16",
    "var_input": "",
    "var_hotkey": "CTRL+SPACE",
    "var_auto_paste": True,
    "var_paste_delay": 0.15,
    "var_restore_delay": 0.6,
    "var_cleanup_backend": "off",
    "var_s1_styling": "semi-casual",
    "var_s1_structure": "prose",
    "var_s1_context": "general",
    "var_llm_endpoint": "http://localhost:11434/v1",
    "var_llm_model": "some-model",
    "var_llm_key": "",
    "var_llm_temp": 0.1,
    "var_llm_debug": False,
    "var_glossary_enable": False,
    "var_auto_load_model": False,
    "var_auto_register_hotkey": False,
    "var_vad_enabled": False,
    "var_vad_threshold": 0.5,
    "var_vad_min_speech_ms": 250,
    "var_vad_min_silence_ms": 500,
    "var_vad_speech_pad_ms": 400,
    "var_compression_ratio_threshold": 2.4,
    "var_log_prob_threshold": -1.0,
    "var_no_speech_threshold": 0.6,
    "var_temperature": 0.0,
    "var_beam_size": 5,
    "var_initial_prompt": "",
}


@pytest.fixture
def mods(mocker):
    """The modules the pipeline reaches out through, mocked."""
    m = MagicMock()
    for name in ("clipboard", "app_context", "history", "llm_cleanup", "glossary"):
        mocker.patch.object(gui, name, getattr(m, name))
    m.messagebox = mocker.patch.object(gui, "messagebox")
    mocker.patch.object(gui.time, "sleep")
    # The except clauses need real exception classes, not mocks.
    m.clipboard.ClipboardError = clipboard.ClipboardError
    m.llm_cleanup.LLMCleanupError = llm_cleanup.LLMCleanupError

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
        # The worker hands widget work to after(); run it on the spot.
        app.after = MagicMock(side_effect=lambda _ms, fn, *args: fn(*args))
        app.asr = MagicMock()
        app.asr.get.return_value.transcribe.return_value = "hello world"
        app.s1 = MagicMock()
        app.recorder = MagicMock()
        app.recorder.get_buffer.return_value = AUDIO
        app.recent_processes = deque(maxlen=gui.App.RECENT_PROCESSES_MAX)
        app.app_prompts = {}
        app.hotwords_by_app = {}
        app.glossary_manager = mods.glossary.load_glossary_manager.return_value
        app.prompt_content = ""
        app._press_at = 0.0
        app._status_state = "ready"
        app._deliver_lock = threading.Lock()
        app._settings_saved = False
        app._defaults = {
            name: VAR_DEFAULTS[name] for _, name, cast in gui.SETTINGS if cast in (int, float)
        }
        return app

    return _make


def run(app) -> None:
    """One dictation, the way _stop_and_transcribe starts it."""
    app._transcribe_and_clean(app._capture_dictation_config())


def states(app) -> list[str]:
    return [call.args[0] for call in app.indicator.update.call_args_list]


def messages(app) -> list[str]:
    return [call.args[1] for call in app.indicator.update.call_args_list]


class TestDeliver:
    def test_happy_path_order(self, make_app, mods):
        app = make_app()
        app._deliver("hi", app._capture_dictation_config())

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
        app._deliver("hi", app._capture_dictation_config())

        assert states(app)[-1] == "error"
        mods.clipboard.send_paste.assert_not_called()
        # Nothing was overwritten, so there is nothing to put back.
        mods.clipboard.restore.assert_not_called()

    def test_snapshot_fails(self, make_app, mods):
        mods.clipboard.snapshot.side_effect = clipboard.ClipboardError("locked")
        app = make_app()
        app._deliver("hi", app._capture_dictation_config())

        mods.clipboard.set_text.assert_called_once_with("hi")
        mods.clipboard.send_paste.assert_called_once()
        mods.clipboard.restore.assert_not_called()

    def test_paste_refused_still_restores(self, make_app, mods):
        mods.clipboard.send_paste.return_value = False
        app = make_app()
        app._deliver("hi", app._capture_dictation_config())

        assert states(app)[-1] == "error"
        mods.clipboard.restore.assert_called_once_with("SAVED")

    def test_blank_delay_field_still_restores(self, make_app, mods):
        app = make_app()
        app.var_paste_delay.get.side_effect = TclError('expected floating-point number but got ""')
        cfg = app._capture_dictation_config()
        app._deliver("hi", cfg)

        assert cfg["paste_delay"] == 0.15
        mods.clipboard.send_paste.assert_called_once()
        mods.clipboard.restore.assert_called_once_with("SAVED")

    def test_paste_raising_still_restores(self, make_app, mods):
        mods.clipboard.send_paste.side_effect = OSError("SendInput blew up")
        app = make_app()
        with pytest.raises(OSError):
            app._deliver("hi", app._capture_dictation_config())

        mods.clipboard.restore.assert_called_once_with("SAVED")

    def test_two_deliveries_do_not_interleave(self, make_app, mods):
        app = make_app()
        # Off the main thread _set_status re-posts itself through after(), which
        # the harness runs on the spot: it would recurse for ever.
        app._set_status = MagicMock()
        cfg = app._capture_dictation_config()
        in_paste, go = threading.Event(), threading.Event()

        def paste():
            in_paste.set()
            go.wait(2.0)
            return True

        mods.clipboard.send_paste.side_effect = paste
        a = threading.Thread(target=app._deliver, args=("A", cfg))
        a.start()
        assert in_paste.wait(2.0)
        b = threading.Thread(target=app._deliver, args=("B", cfg))
        b.start()
        b.join(0.1)  # B must be parked on the lock, not snapshotting A's text
        assert [c[0] for c in mods.clipboard.mock_calls].count("snapshot") == 1
        go.set()
        a.join(2.0)
        b.join(2.0)
        assert [c[0] for c in mods.clipboard.mock_calls] == [
            "snapshot",
            "set_text",
            "send_paste",
            "restore",
        ] * 2


class TestTranscribeAndClean:
    def test_no_audio(self, make_app, mods):
        app = make_app()
        app.recorder.get_buffer.return_value = None
        run(app)

        assert states(app) == ["warning"]
        mods.clipboard.set_text.assert_not_called()

    def test_empty_transcript(self, make_app, mods):
        app = make_app()
        app.asr.get.return_value.transcribe.return_value = ""
        run(app)

        assert states(app)[-1] == "warning"
        mods.clipboard.set_text.assert_not_called()

    def test_happy_path_delivers_transcript(self, make_app, mods):
        app = make_app()
        run(app)

        mods.clipboard.set_text.assert_called_once_with("hello world")
        assert "hello world" in app.txt_out.insert.call_args.args[1]
        assert states(app)[-1] == "ready"

    def test_endpoint_failure_delivers_raw_text(self, make_app, mods):
        mods.llm_cleanup.clean_with_llm.side_effect = llm_cleanup.LLMCleanupError("down")
        app = make_app(var_cleanup_backend="endpoint")
        run(app)

        assert "warning" in states(app)
        mods.clipboard.set_text.assert_called_once_with("hello world")

    def test_endpoint_failure_warning_survives(self, make_app, mods):
        mods.llm_cleanup.clean_with_llm.side_effect = llm_cleanup.LLMCleanupError("down")
        app = make_app(var_cleanup_backend="endpoint")
        run(app)

        assert states(app)[-1] == "warning"

    def test_worker_reads_no_tk_variable(self, make_app, mods):
        app = make_app(var_cleanup_backend="endpoint", var_history_enable=True)
        mods.llm_cleanup.clean_with_llm.return_value = "Hello, world."
        cfg = app._capture_dictation_config()
        for name in VAR_DEFAULTS:
            var = getattr(app, name)
            var.get.side_effect = TclError("read from the worker thread")
            var.set.side_effect = TclError("written from the worker thread")
        app._transcribe_and_clean(cfg)

        mods.clipboard.set_text.assert_called_once_with("Hello, world.")
        mods.history.record.assert_called_once()
        mods.clipboard.restore.assert_called_once_with("SAVED")

    def test_s1_failure_turns_cleanup_off_through_after(self, make_app, mods):
        app = make_app(var_cleanup_backend="s1")
        app.s1.get.side_effect = RuntimeError("no model")
        run(app)

        app.after.assert_any_call(0, app.var_cleanup_backend.set, "off")
        mods.clipboard.set_text.assert_called_once_with("hello world")

    def test_transcription_error(self, make_app, mods):
        app = make_app()
        app.asr.get.return_value.transcribe.side_effect = RuntimeError("boom")
        run(app)

        assert states(app)[-1] == "error"
        mods.messagebox.showerror.assert_called_once()
        mods.clipboard.set_text.assert_not_called()

    def test_worker_reports_an_unexpected_error(self, make_app, mods):
        """Anything escaping the thread would leave the pill on "Transcribing..."."""
        app = make_app()
        app._transcribe_and_clean = MagicMock(side_effect=AttributeError("boom"))
        app._dictation_worker({})

        assert states(app)[-1] == "error"


class TestSpeechWindowClose:
    @pytest.fixture
    def app(self, make_app):
        def _make(**var_overrides):
            app = make_app(**var_overrides)
            app._speech_window = None
            app._speech_window_traces = []
            app._asr_config = ("whisper", "small", "cuda", "float16")
            app._save_settings = MagicMock()
            return app

        return _make

    def test_a_changed_model_releases_the_recognizer(self, app):
        app = app(var_model="large-v3")
        app._close_window("_speech_window")

        app.asr.release.assert_called_once()
        assert messages(app)[-1] == "Recognizer: Whisper large-v3"

    def test_nothing_changed_keeps_the_recognizer(self, app):
        app = app()
        app._close_window("_speech_window")

        app.asr.release.assert_not_called()


class TestHotkey:
    @pytest.mark.parametrize(("held", "warned"), [(0.2, True), (0.01, False)])
    def test_a_slow_post_is_logged(self, held, warned, make_app, mocker, caplog):
        """Windows drops the hook at 300 ms; the log must say when we get close."""
        app = make_app()
        clock = [0.0]
        # gui's own reference only: pytest times tests with the real clock.
        mocker.patch.object(gui, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
        app.after = MagicMock(side_effect=lambda *_: clock.__setitem__(0, clock[0] + held))

        with caplog.at_level("WARNING", logger="whisper_dictate"):
            app._post(app._on_hotkey_press)

        assert ("Hotkey press callback held the hook thread for 200 ms" in caplog.text) is warned

    def test_tap_locks_recording(self, make_app, mods):
        app = make_app()
        app.recorder.is_recording.return_value = True
        app._stop_and_transcribe = MagicMock()
        app._press_at = time.monotonic()
        app._on_hotkey_release()

        app._stop_and_transcribe.assert_not_called()
        app.recorder.stop.assert_not_called()
        assert "locked" in messages(app)[-1]

    def test_hold_transcribes_on_release(self, make_app, mods):
        app = make_app()
        app.recorder.is_recording.return_value = True
        app._stop_and_transcribe = MagicMock()
        app._press_at = time.monotonic() - gui.TAP_SECONDS - 1
        app._on_hotkey_release()

        app._stop_and_transcribe.assert_called_once()

    def test_cancel_discards_buffer(self, make_app, mods):
        app = make_app()
        app.recorder.is_recording.return_value = True
        app._on_hotkey_cancel()

        app.recorder.stop.assert_called_once()
        app.recorder.get_buffer.assert_called_once()
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

    def test_save_writes_process_names_without_titles(self, make_app, mocker):
        store = mocker.patch.object(gui, "settings_store")
        app = make_app()
        app.indicator.get_position.return_value = None
        app._record_recent_process("a.exe", "Quarterly results - Word")
        app._record_recent_process("b.exe", "two")
        app._record_recent_process("a.exe", "other title")
        app._save_settings()

        saved = store.save_settings.call_args.args[0]
        assert saved["recent_processes"] == ["a.exe", "b.exe"]
        assert "window_title" not in repr(saved)


class TestOnClose:
    def test_failed_save_is_not_marked_saved(self, make_app):
        app = make_app()
        app._save_settings = MagicMock(side_effect=TclError("blank field"))
        app.destroy = MagicMock()
        app._on_close()

        assert app._settings_saved is False
        app.destroy.assert_called_once()

    def test_good_save_is_marked_saved(self, make_app):
        app = make_app()
        app._save_settings = MagicMock()
        app.destroy = MagicMock()
        app._on_close()

        assert app._settings_saved is True
        app.destroy.assert_called_once()

    def test_blank_numeric_field_saves_its_default(self, make_app, mocker):
        store = mocker.patch.object(gui, "settings_store")
        app = make_app()
        app.indicator.get_position.return_value = None
        app.var_paste_delay.get.side_effect = TclError('expected floating-point number but got ""')
        app._save_settings()

        saved = store.save_settings.call_args.args[0]
        assert saved["paste_delay"] == 0.15
        assert saved["restore_delay"] == 0.6


class TestSettingsTable:
    def test_every_variable_is_in_the_table(self):
        assert {name for _, name, _ in gui.SETTINGS} == set(VAR_DEFAULTS)

    def test_round_trip(self, make_app, mocker):
        store = mocker.patch.object(gui, "settings_store")
        store.get_secure_setting.return_value = None
        app = make_app(var_beam_size=3, var_hotkey=" CTRL+ALT+D ", var_vad_enabled=True)
        app.indicator.get_position.return_value = (10, 20)
        app._save_settings()

        saved = store.save_settings.call_args.args[0]
        assert saved["hotkey"] == "CTRL+ALT+D"
        store.load_settings.return_value = saved
        fresh = make_app()
        fresh._load_settings()

        for key, name, _cast in gui.SETTINGS:
            getattr(fresh, name).set.assert_called_once_with(saved[key])
        assert fresh._indicator_position == (10, 20)
