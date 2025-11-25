import json
import sys
import types
import ctypes
from collections import deque

import pytest

ctypes.windll = types.SimpleNamespace(
    user32=types.SimpleNamespace(
        RegisterHotKey=lambda *args, **kwargs: True,
        UnregisterHotKey=lambda *args, **kwargs: True,
        GetMessageW=lambda *args, **kwargs: 0,
        TranslateMessage=lambda *args, **kwargs: None,
        DispatchMessageW=lambda *args, **kwargs: None,
        PostThreadMessageW=lambda *args, **kwargs: True,
        MessageBoxW=lambda *args, **kwargs: 0,
    )
)

sys.modules.setdefault(
    "pyautogui", types.SimpleNamespace(FAILSAFE=False, hotkey=lambda *args, **kwargs: None)
)
sys.modules.setdefault("pyperclip", types.SimpleNamespace(copy=lambda text: None))
sys.modules.setdefault(
    "sounddevice",
    types.SimpleNamespace(InputStream=object, query_devices=lambda: [], default=types.SimpleNamespace()),
)
sys.modules.setdefault("faster_whisper", types.SimpleNamespace(WhisperModel=object))
sys.modules.setdefault(
    "numpy", types.SimpleNamespace(mean=lambda array, axis=None: array, ndarray=object)
)

from whisper_dictate import gui, settings_store


class DummyVar:
    def __init__(self, value=None):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


def _make_app():
    app = gui.App.__new__(gui.App)
    app.recent_processes = deque(maxlen=gui.App.RECENT_PROCESSES_MAX)
    app.app_prompts = {}
    app._indicator_position = None
    app.indicator = types.SimpleNamespace(get_position=lambda: None)
    for name in (
        "var_model",
        "var_device",
        "var_compute",
        "var_input",
        "var_hotkey",
        "var_auto_paste",
        "var_paste_delay",
        "var_llm_enable",
        "var_llm_endpoint",
        "var_llm_model",
        "var_llm_key",
        "var_llm_temp",
        "var_llm_debug",
        "var_glossary_enable",
    ):
        setattr(app, name, DummyVar())
    app._record_recent_process = gui.App._record_recent_process.__get__(app, gui.App)
    return app


def test_load_settings_handles_mixed_recent_entries(monkeypatch):
    saved = {
        "model": "medium",
        "recent_processes": [
            "chrome.exe",
            {"process_name": " paint.exe ", "window_title": " Canvas "},
            ("obs64.exe", "Streaming"),
            ["vim.exe"],
            {"process_name": "", "window_title": "Ignored"},
        ],
        "glossary_enable": False,
    }

    app = _make_app()
    monkeypatch.setattr(settings_store, "load_settings", lambda: json.loads(json.dumps(saved)))

    app._load_settings()

    assert list(app.recent_processes) == [
        {"process_name": "vim.exe", "window_title": None},
        {"process_name": "obs64.exe", "window_title": "Streaming"},
        {"process_name": "paint.exe", "window_title": "Canvas"},
        {"process_name": "chrome.exe", "window_title": None},
    ]
    assert app.var_model.get() == "medium"
    assert app.var_glossary_enable.get() is False


def test_save_settings_formats_recent_entries(monkeypatch):
    app = _make_app()
    app.var_model.set("small")
    app.var_device.set("cuda")
    app.var_compute.set("float16")
    app.var_input.set("Mic 1")
    app.var_hotkey.set("CTRL+WIN+G")
    app.var_auto_paste.set(True)
    app.var_paste_delay.set(0.25)
    app.var_llm_enable.set(True)
    app.var_llm_endpoint.set("http://localhost:8000")
    app.var_llm_model.set("gpt-test")
    app.var_llm_key.set("abc123")
    app.var_llm_temp.set(0.5)
    app.var_llm_debug.set(False)
    app.var_glossary_enable.set(True)
    app.app_prompts = {"chrome.exe": [{"prompt": "Hello"}]}
    app.recent_processes = deque(
        [
            {"process_name": "chrome.exe", "window_title": None},
            {"process_name": "edge.exe", "window_title": "Docs"},
        ],
        maxlen=gui.App.RECENT_PROCESSES_MAX,
    )

    captured = {}

    def fake_save(settings):
        captured["settings"] = settings
        return True

    monkeypatch.setattr(settings_store, "save_settings", fake_save)

    app._save_settings()

    assert captured["settings"]["recent_processes"] == [
        {"process_name": "chrome.exe", "window_title": None},
        {"process_name": "edge.exe", "window_title": "Docs"},
    ]
    assert captured["settings"]["app_prompts"] == {"chrome.exe": [{"prompt": "Hello"}]}
    assert captured["settings"]["model"] == "small"
