"""Streamlined GUI for whisper-dictate with optional LLM cleanup."""

import ctypes
import threading
import time
import winsound
from collections import deque
from collections.abc import Callable
from itertools import count
from tkinter import (
    END,
    BooleanVar,
    DoubleVar,
    Menu,
    StringVar,
    TclError,
    Text,
    Tk,
    Toplevel,
    messagebox,
    ttk,
)
from typing import Any

import sounddevice as sd

from whisper_dictate import (
    app_context,
    app_prompts,
    asr,
    audio,
    clipboard,
    config,
    glossary,
    history,
    hotkeys,
    llm_cleanup,
    prompt,
    s1,
    settings_store,
    transcription,
)
from whisper_dictate.app_prompt_dialog import AppPromptDialog
from whisper_dictate.config import (
    CLEANUP_BACKENDS,
    DEFAULT_ASR_BACKEND,
    DEFAULT_AUTO_LOAD_MODEL,
    DEFAULT_AUTO_REGISTER_HOTKEY,
    DEFAULT_CLEANUP_BACKEND,
    DEFAULT_COMPUTE,
    DEFAULT_DEVICE,
    DEFAULT_HISTORY_AUDIO_DAYS,
    DEFAULT_HISTORY_ENABLE,
    DEFAULT_IDLE_TTL_MINUTES,
    DEFAULT_LLM_DEBUG,
    DEFAULT_LLM_ENDPOINT,
    DEFAULT_LLM_KEY,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROMPT,
    DEFAULT_LLM_TEMP,
    DEFAULT_MODEL,
    DEVICE_COMPUTE_DEFAULTS,
    MODEL_INFO,
    get_model_choices,
    set_cuda_paths,
)
from whisper_dictate.glossary_dialog import GlossaryDialog
from whisper_dictate.gui_components import PromptDialog, StatusIndicator
from whisper_dictate.logging_config import LOG_FILE, setup_logging

# Set up CUDA paths before importing other modules
set_cuda_paths()

# Set up logging
logger = setup_logging()

ERROR_ALREADY_EXISTS = 183

# A chord held for less than this is a tap: recording locks on and the next press
# ends it. Anything longer is hold-to-talk, ended by the release.
TAP_SECONDS = 0.3

# The cue that says capture is live. Short enough not to bleed into the first word.
BEEP_HZ, BEEP_MS = 880, 60

# How long to wait for a held chord to come up before pasting anyway. Generous:
# holding the keys is the user's business, and a paste under them does nothing.
MODIFIER_WAIT_SECONDS = 5.0

# Every setting that lives in a Tk variable: (settings key, variable, type). It
# drives load, save and the worker's snapshot. int and float are both DoubleVars.
SETTINGS: tuple[tuple[str, str, type], ...] = (
    ("model", "var_model", str),
    ("asr_backend", "var_asr_backend", str),
    ("idle_ttl_minutes", "var_idle_ttl_minutes", float),
    ("history_enable", "var_history_enable", bool),
    ("history_audio_days", "var_history_audio_days", int),
    ("device", "var_device", str),
    ("compute", "var_compute", str),
    ("input", "var_input", str),
    ("hotkey", "var_hotkey", str),
    ("auto_paste", "var_auto_paste", bool),
    ("paste_delay", "var_paste_delay", float),
    ("restore_delay", "var_restore_delay", float),
    ("cleanup_backend", "var_cleanup_backend", str),
    ("s1_styling", "var_s1_styling", str),
    ("s1_structure", "var_s1_structure", str),
    ("s1_context", "var_s1_context", str),
    ("llm_endpoint", "var_llm_endpoint", str),
    ("llm_model", "var_llm_model", str),
    # Never reaches the JSON file: settings_store moves it to the credential manager.
    ("llm_key", "var_llm_key", str),
    ("llm_temp", "var_llm_temp", float),
    ("llm_debug", "var_llm_debug", bool),
    ("glossary_enable", "var_glossary_enable", bool),
    ("auto_load_model", "var_auto_load_model", bool),
    ("auto_register_hotkey", "var_auto_register_hotkey", bool),
    ("vad_enabled", "var_vad_enabled", bool),
    ("vad_threshold", "var_vad_threshold", float),
    ("vad_min_speech_ms", "var_vad_min_speech_ms", int),
    ("vad_min_silence_ms", "var_vad_min_silence_ms", int),
    ("vad_speech_pad_ms", "var_vad_speech_pad_ms", int),
    ("compression_ratio_threshold", "var_compression_ratio_threshold", float),
    ("log_prob_threshold", "var_log_prob_threshold", float),
    ("no_speech_threshold", "var_no_speech_threshold", float),
    ("temperature", "var_temperature", float),
    ("beam_size", "var_beam_size", int),
    ("initial_prompt", "var_initial_prompt", str),
)


class App(Tk):
    """Main application window."""

    RECENT_PROCESSES_MAX = 15

    def __init__(self):
        super().__init__()
        self.title("Whisper Dictate + LLM")
        self.geometry("980x680")
        # Closing the window hides it; the app lives in the pill. Quitting is
        # deliberate, through the pill's menu, so a stray Alt+F4 on a
        # login-launched app does not end dictation for the day.
        self.protocol("WM_DELETE_WINDOW", self.hide_window)

        self._settings_saved = False

        self.option_add("*Font", ("Segoe UI", 10))
        style = ttk.Style(self)
        style.configure("Section.TLabelframe", padding=(12, 10))
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 9, "bold"))

        # Load saved prompt
        self.prompt_content = prompt.load_saved_prompt()
        self.glossary_manager = glossary.load_glossary_manager()
        self.app_prompts: app_prompts.AppPromptMap = {}
        self.recent_processes: deque[dict[str, str | None]] = deque(
            maxlen=self.RECENT_PROCESSES_MAX
        )

        # Recognizer and hotkey manager. The factory reads _asr_config, never
        # the Tk variables: it runs on a loader thread, and touching Tk from
        # there deadlocks whenever the main thread is inside a Tcl callback.
        self._asr_config: tuple[str, str, str, str] = ("", "", "", "")
        self.asr = asr.Resident(self._build_backend, ttl=0.0)
        self.s1 = asr.Resident(s1.S1Cleaner, ttl=0.0)
        self.recorder = audio.AudioRecorder()
        self.hotkey_manager: hotkeys.HotkeyManager | None = None
        self._press_at = 0.0
        self._status_state = "ready"
        self.llm_models: list[str] = []
        self.cmb_llm_model: ttk.Combobox | None = None
        self.btn_llm_refresh: ttk.Button | None = None

        # Secondary windows
        self._speech_window: Toplevel | None = None
        self._advanced_transcription_window: Toplevel | None = None
        self._automation_window: Toplevel | None = None
        self._llm_window: Toplevel | None = None
        self._log_window: Toplevel | None = None
        self._speech_window_traces: list[tuple] = []

        self._build_menus()
        self._build_ui()
        self._setup_status_indicator()
        self._auto_startup()
        # No dialog: the app may be starting hidden at login.
        if settings_store.last_load_error:
            self._set_status(
                "warning", "Settings file was unreadable; using defaults. Backup kept."
            )

        # Launched at login, the app should start out of the way. Only when it
        # is set up to run by itself: otherwise the user has nothing to click.
        if self.var_auto_load_model.get() and self.var_auto_register_hotkey.get():
            self.withdraw()

    def _build_menus(self) -> None:
        """Build application menu bar."""
        menubar = Menu(self)
        edit_menu = Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Prompt...", command=self._open_prompt_dialog)
        edit_menu.add_command(label="Glossary...", command=self._open_glossary_dialog)
        edit_menu.add_command(label="Per-app prompts...", command=self._open_app_prompt_dialog)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        settings_menu = Menu(menubar, tearoff=False)
        settings_menu.add_command(label="Speech recognition...", command=self._open_speech_settings)
        settings_menu.add_command(
            label="Advanced transcription...", command=self._open_advanced_transcription_settings
        )
        settings_menu.add_command(label="LLM cleanup...", command=self._open_llm_settings)
        settings_menu.add_command(label="Automation...", command=self._open_automation_settings)
        settings_menu.add_separator()
        settings_menu.add_command(
            label="Reset status indicator position", command=self._reset_status_indicator
        )
        menubar.add_cascade(label="Settings", menu=settings_menu)

        about_menu = Menu(menubar, tearoff=False)
        about_menu.add_command(label="View logs", command=self._open_log_viewer)
        menubar.add_cascade(label="About", menu=about_menu)

        self.config(menu=menubar)

    def _build_ui(self) -> None:
        """Build the main UI."""
        # Variables
        self.var_model = StringVar(value=DEFAULT_MODEL)
        self.var_asr_backend = StringVar(value=DEFAULT_ASR_BACKEND)
        self.var_idle_ttl_minutes = DoubleVar(value=DEFAULT_IDLE_TTL_MINUTES)
        self.var_history_enable = BooleanVar(value=DEFAULT_HISTORY_ENABLE)
        self.var_history_audio_days = DoubleVar(value=DEFAULT_HISTORY_AUDIO_DAYS)
        self.var_model_display = StringVar(value="")  # For formatted model name in dropdown
        self.var_device = StringVar(value=DEFAULT_DEVICE)
        self.var_compute = StringVar(value=DEFAULT_COMPUTE)
        self.var_input = StringVar(value="")
        self.var_hotkey = StringVar(value="CTRL+SPACE")
        self.var_auto_paste = BooleanVar(value=True)
        self.var_paste_delay = DoubleVar(value=0.15)
        self.var_restore_delay = DoubleVar(value=0.6)

        self.var_cleanup_backend = StringVar(value=DEFAULT_CLEANUP_BACKEND)
        self.var_s1_styling = StringVar(value=s1.DEFAULT_STYLING)
        self.var_s1_structure = StringVar(value=s1.DEFAULT_STRUCTURE)
        self.var_s1_context = StringVar(value=s1.DEFAULT_CONTEXT)
        self.var_llm_endpoint = StringVar(value=DEFAULT_LLM_ENDPOINT)
        self.var_llm_model = StringVar(value=DEFAULT_LLM_MODEL)
        self.var_llm_key = StringVar(value=DEFAULT_LLM_KEY)
        self.var_llm_temp = DoubleVar(value=DEFAULT_LLM_TEMP)
        self.var_llm_debug = BooleanVar(value=DEFAULT_LLM_DEBUG)
        self.var_glossary_enable = BooleanVar(value=True)
        self.var_auto_load_model = BooleanVar(value=DEFAULT_AUTO_LOAD_MODEL)
        self.var_auto_register_hotkey = BooleanVar(value=DEFAULT_AUTO_REGISTER_HOTKEY)

        # Advanced transcription settings
        self.var_vad_enabled = BooleanVar(value=False)  # Disabled by default
        self.var_vad_threshold = DoubleVar(value=0.5)
        self.var_vad_min_speech_ms = DoubleVar(value=250)
        self.var_vad_min_silence_ms = DoubleVar(value=500)
        self.var_vad_speech_pad_ms = DoubleVar(value=400)
        self.var_compression_ratio_threshold = DoubleVar(value=2.4)
        self.var_log_prob_threshold = DoubleVar(value=-1.0)
        self.var_no_speech_threshold = DoubleVar(value=0.6)
        self.var_temperature = DoubleVar(value=0.0)
        self.var_beam_size = DoubleVar(value=5)
        self.var_initial_prompt = StringVar(value="")

        self._indicator_position: tuple[int, int] | None = None

        # A blank Spinbox falls back to the value its variable was created with.
        self._defaults: dict[str, float] = {
            name: getattr(self, name).get() for _, name, cast in SETTINGS if cast in (int, float)
        }

        self._load_settings()
        self._refresh_glossary_cache()

        # Controls
        ctrl = ttk.Frame(self, padding=(12, 0, 12, 12))
        ctrl.pack(fill="x")
        self.btn_load = ttk.Button(ctrl, text="Load model", command=self._load_model)
        self.btn_load.grid(row=0, column=0, padx=(0, 8))
        self.btn_hotkey = ttk.Button(
            ctrl, text="Register hotkey", command=self._register_hotkey, state="disabled"
        )
        self.btn_hotkey.grid(row=0, column=1, padx=(0, 8))
        self.btn_toggle = ttk.Button(
            ctrl, text="Start recording", command=self._toggle_record, state="disabled"
        )
        self.btn_toggle.grid(row=0, column=2, padx=(0, 8))
        self.lbl_status = ttk.Label(ctrl, text="Idle")
        self.lbl_status.grid(row=0, column=3, sticky="w")

        # Transcript box
        out = ttk.Frame(self, padding=8)
        out.pack(fill="both", expand=True)
        ttk.Label(out, text="Transcript").pack(anchor="w")
        self.txt_out = Text(out, wrap="word")
        self.txt_out.pack(fill="both", expand=True)

    def _open_window(self, window_attr: str, title: str, builder, resizable: bool = False) -> None:
        """Open or focus a configuration window."""
        existing = getattr(self, window_attr)
        if existing and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_set()
            return

        window = Toplevel(self)
        window.title(title)
        window.resizable(resizable, resizable)
        setattr(self, window_attr, window)
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_window(window_attr))
        builder(window)

    def _close_window(self, window_attr: str) -> None:
        """Close and clear a configuration window reference."""
        window = getattr(self, window_attr)
        if window and window.winfo_exists():
            window.destroy()
        setattr(self, window_attr, None)
        if window_attr == "_llm_window":
            self.cmb_llm_model = None
            self.btn_llm_refresh = None
            self._capture_s1_style()
        elif window_attr == "_automation_window":
            self._apply_hotkey_change()
            self._apply_idle_ttl()
        elif window_attr == "_speech_window":
            # Clean up trace callbacks to prevent accessing destroyed widgets
            for var, trace_id in self._speech_window_traces:
                try:
                    var.trace_remove("write", trace_id)
                except (ValueError, KeyError):
                    pass
            self._speech_window_traces = []
        # Quit is not the only way out: a kill or a crash must not cost the edit.
        self._save_settings()

    def _open_speech_settings(self) -> None:
        """Open speech recognition settings window."""

        def build(window: Toplevel) -> None:
            frame = ttk.Frame(window, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(1, weight=1)

            backend_combo = ttk.Combobox(
                frame,
                textvariable=self.var_asr_backend,
                values=list(asr.BACKENDS),
                width=12,
                state="readonly",
            )
            backend_combo.bind("<<ComboboxSelected>>", lambda _e: self._reload_backend())
            self._add_labeled_widget(frame, "Recognizer", 0, backend_combo)

            # Device selection (affects the model display below)
            device_combo = ttk.Combobox(
                frame,
                textvariable=self.var_device,
                values=["cpu", "cuda"],
                width=10,
                state="readonly",
            )
            self._add_labeled_widget(frame, "Device", 1, device_combo)

            # Model selection with size info
            model_combo = ttk.Combobox(
                frame, textvariable=self.var_model_display, state="readonly", width=45
            )
            self._add_labeled_widget(frame, "Model (Whisper only)", 2, model_combo)

            # Description label for selected model
            desc_label = ttk.Label(
                frame, text="", wraplength=380, foreground="gray", font=("Segoe UI", 9, "italic")
            )
            desc_label.grid(row=3, column=1, sticky="w", padx=(12, 0), pady=(0, 8))

            # Compute type display (read-only, auto-configured)
            compute_label = ttk.Label(frame, text=f"Compute type: {self.var_compute.get()} (auto)")
            compute_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 4))

            # Input device dropdown
            input_device_names = self._get_input_device_names()
            input_combo = ttk.Combobox(
                frame, textvariable=self.var_input, values=input_device_names, state="readonly"
            )
            self._add_labeled_widget(frame, "Input device", 5, input_combo)

            def update_model_display(*args) -> None:
                """Update model dropdown values when device changes."""
                current_model = self.var_model.get()
                device = self.var_device.get()
                choices = get_model_choices(device)
                display_names = [c[1] for c in choices]
                model_combo.config(values=display_names)

                # Update compute type automatically
                new_compute = DEVICE_COMPUTE_DEFAULTS.get(device, "float16")
                self.var_compute.set(new_compute)
                compute_label.config(text=f"Compute type: {new_compute} (auto)")

                # Maintain selection if model still exists
                for model_id, display in choices:
                    if model_id == current_model:
                        self.var_model_display.set(display)
                        return
                # Default to first model if current not found
                if choices:
                    self.var_model_display.set(choices[0][1])
                    self.var_model.set(choices[0][0])

            def on_model_change(*args) -> None:
                """Update description when model selection changes."""
                display = self.var_model_display.get()
                # Find model_id from display name
                device = self.var_device.get()
                for model_id, disp in get_model_choices(device):
                    if disp == display:
                        self.var_model.set(model_id)
                        info = MODEL_INFO.get(model_id, {})
                        desc = info.get("description", "")
                        speed = info.get("speed", "")
                        if speed:
                            desc = f"Speed: {speed} | {desc}"
                        desc_label.config(text=desc)
                        return

            # Store trace IDs so they can be cleaned up when window closes
            trace_id1 = self.var_model_display.trace_add("write", on_model_change)
            trace_id2 = self.var_device.trace_add("write", update_model_display)
            self._speech_window_traces = [
                (self.var_model_display, trace_id1),
                (self.var_device, trace_id2),
            ]

            # Initialize display
            update_model_display()
            on_model_change()

        self._open_window("_speech_window", "Speech recognition", build)

    def _open_automation_settings(self) -> None:
        """Open automation settings window."""

        def build(window: Toplevel) -> None:
            frame = ttk.Frame(window, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(0, weight=1)

            ttk.Label(frame, text="Hotkey (hold to talk, tap to lock)").grid(
                row=0, column=0, sticky="w"
            )
            ttk.Entry(frame, textvariable=self.var_hotkey, width=16).grid(
                row=1, column=0, sticky="we", pady=(0, 8)
            )
            ttk.Checkbutton(
                frame, text="Auto-paste into active window", variable=self.var_auto_paste
            ).grid(row=2, column=0, sticky="w")

            paste_row = ttk.Frame(frame)
            paste_row.grid(row=3, column=0, sticky="we", pady=(4, 0))
            ttk.Label(paste_row, text="Paste delay (s)").pack(side="left")
            ttk.Spinbox(
                paste_row,
                from_=0.0,
                to=1.0,
                increment=0.05,
                textvariable=self.var_paste_delay,
                width=6,
            ).pack(side="left", padx=(8, 0))
            ttk.Label(paste_row, text="Clipboard restore delay (s)").pack(side="left", padx=(16, 0))
            ttk.Spinbox(
                paste_row,
                from_=0.0,
                to=3.0,
                increment=0.05,
                textvariable=self.var_restore_delay,
                width=6,
            ).pack(side="left", padx=(8, 0))

            ttl_row = ttk.Frame(frame)
            ttl_row.grid(row=4, column=0, sticky="we", pady=(8, 0))
            ttk.Label(ttl_row, text="Unload the model after (minutes idle)").pack(side="left")
            ttk.Spinbox(
                ttl_row,
                from_=0,
                to=120,
                increment=1,
                textvariable=self.var_idle_ttl_minutes,
                width=6,
                command=self._apply_idle_ttl,
            ).pack(side="left", padx=(8, 0))
            ttk.Label(ttl_row, text="0 = never", foreground="gray").pack(side="left", padx=(8, 0))

            ttk.Separator(frame, orient="horizontal").grid(
                row=5, column=0, sticky="we", pady=(12, 8)
            )
            ttk.Label(frame, text="History", font=("Segoe UI", 9, "bold")).grid(
                row=6, column=0, sticky="w"
            )
            ttk.Checkbutton(
                frame,
                text="Keep a local record of every dictation",
                variable=self.var_history_enable,
            ).grid(row=7, column=0, sticky="w", pady=(4, 0))
            hist_row = ttk.Frame(frame)
            hist_row.grid(row=8, column=0, sticky="we")
            ttk.Label(hist_row, text="Keep the audio for (days)").pack(side="left")
            ttk.Spinbox(
                hist_row,
                from_=0,
                to=365,
                increment=1,
                textvariable=self.var_history_audio_days,
                width=6,
            ).pack(side="left", padx=(8, 0))
            ttk.Label(hist_row, text="0 = text only", foreground="gray").pack(
                side="left", padx=(8, 0)
            )
            # The same warning the debug-logging option carries, for the same
            # reason: this writes what you said to disk.
            ttk.Label(
                frame,
                text=(
                    r"Transcripts and recordings are written to ~\.whisper_dictate. "
                    "They never leave this machine, and window titles are never stored."
                ),
                wraplength=420,
                foreground="#b8860b",
            ).grid(row=9, column=0, sticky="w", pady=(4, 0))

            # Auto-startup options
            ttk.Separator(frame, orient="horizontal").grid(
                row=10, column=0, sticky="we", pady=(12, 8)
            )
            ttk.Label(frame, text="Startup", font=("Segoe UI", 9, "bold")).grid(
                row=11, column=0, sticky="w"
            )
            ttk.Checkbutton(
                frame, text="Auto-load model on startup", variable=self.var_auto_load_model
            ).grid(row=12, column=0, sticky="w", pady=(4, 0))
            ttk.Checkbutton(
                frame,
                text="Auto-register hotkey after model loads",
                variable=self.var_auto_register_hotkey,
            ).grid(row=13, column=0, sticky="w")

        self._open_window("_automation_window", "Automation", build)

    def _open_advanced_transcription_settings(self) -> None:
        """Open advanced transcription settings window."""

        def build(window: Toplevel) -> None:
            frame = ttk.Frame(window, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(1, weight=1)

            rows = count()

            def heading(text: str) -> None:
                row = next(rows)
                if row:
                    ttk.Separator(frame, orient="horizontal").grid(
                        row=row, column=0, columnspan=2, sticky="we", pady=(12, 8)
                    )
                    row = next(rows)
                ttk.Label(frame, text=text, font=("Segoe UI", 9, "bold")).grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(0, 8)
                )

            def spinboxes(*specs: tuple[str, DoubleVar, float, float, float]) -> None:
                for label, var, low, high, step in specs:
                    self._add_labeled_widget(
                        frame,
                        label,
                        next(rows),
                        ttk.Spinbox(
                            frame, from_=low, to=high, increment=step, textvariable=var, width=10
                        ),
                    )

            heading("Voice Activity Detection")
            ttk.Checkbutton(frame, text="Enable VAD filtering", variable=self.var_vad_enabled).grid(
                row=next(rows), column=0, columnspan=2, sticky="w"
            )
            spinboxes(
                ("VAD threshold (0.3-0.8)", self.var_vad_threshold, 0.1, 1.0, 0.1),
                ("Min speech duration (ms)", self.var_vad_min_speech_ms, 100, 1000, 50),
                ("Min silence duration (ms)", self.var_vad_min_silence_ms, 100, 2000, 100),
                ("Speech padding (ms)", self.var_vad_speech_pad_ms, 100, 1000, 50),
            )

            heading("Hallucination Prevention")
            spinboxes(
                (
                    "Compression ratio threshold",
                    self.var_compression_ratio_threshold,
                    1.0,
                    5.0,
                    0.1,
                ),
                ("Log probability threshold", self.var_log_prob_threshold, -2.0, 0.0, 0.1),
                ("No speech threshold", self.var_no_speech_threshold, 0.0, 1.0, 0.1),
            )

            heading("Other Settings")
            spinboxes(
                ("Beam size (1-10)", self.var_beam_size, 1, 10, 1),
                ("Temperature (0.0-1.5)", self.var_temperature, 0.0, 1.5, 0.1),
            )

            # Initial prompt
            row = next(rows)
            ttk.Label(frame, text="Initial prompt (optional)").grid(
                row=row, column=0, sticky="nw", pady=4
            )
            initial_prompt_text = Text(frame, height=3, width=40, wrap="word")
            initial_prompt_text.grid(row=row, column=1, sticky="we", pady=4, padx=(12, 0))
            initial_prompt_text.insert("1.0", self.var_initial_prompt.get())

            # Save initial prompt on text change
            def save_initial_prompt(*args):
                self.var_initial_prompt.set(initial_prompt_text.get("1.0", "end-1c"))

            initial_prompt_text.bind("<KeyRelease>", save_initial_prompt)

            # Help text
            ttk.Label(
                frame,
                text="⚠ These are advanced settings. Defaults work well for most users.",
                foreground="#cc6600",
                wraplength=440,
                justify="left",
                font=("Segoe UI", 9, "italic"),
            ).grid(row=next(rows), column=0, columnspan=2, sticky="w", pady=(8, 0))

        self._open_window(
            "_advanced_transcription_window", "Advanced Transcription (Whisper only)", build
        )

    def _open_llm_settings(self) -> None:
        """Open cleanup settings window."""

        def build(window: Toplevel) -> None:
            frame = ttk.Frame(window, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(1, weight=1)

            backend_row = ttk.Frame(frame)
            backend_row.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 8))
            ttk.Label(backend_row, text="Cleanup").pack(side="left")
            ttk.Combobox(
                backend_row,
                textvariable=self.var_cleanup_backend,
                values=list(CLEANUP_BACKENDS),
                width=10,
                state="readonly",
            ).pack(side="left", padx=(8, 0))
            ttk.Label(
                backend_row,
                text="s1 = built in, endpoint = OpenAI compatible",
                foreground="gray",
            ).pack(side="left", padx=(8, 0))

            style_row = ttk.Frame(frame)
            style_row.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 8))
            # The three settings S1-mini's control line accepts; per-app rules
            # override these for a given window.
            for label, var, values in (
                ("Styling", self.var_s1_styling, s1.STYLING),
                ("Structure", self.var_s1_structure, s1.STRUCTURE),
                ("Context", self.var_s1_context, s1.CONTEXT),
            ):
                ttk.Label(style_row, text=label).pack(side="left", padx=(0, 4))
                ttk.Combobox(
                    style_row,
                    textvariable=var,
                    values=list(values),
                    width=12,
                    state="readonly",
                ).pack(side="left", padx=(0, 12))

            ttk.Separator(frame, orient="horizontal").grid(
                row=2, column=0, columnspan=2, sticky="we", pady=(0, 8)
            )
            self._add_labeled_widget(
                frame, "Endpoint", 3, ttk.Entry(frame, textvariable=self.var_llm_endpoint)
            )
            ttk.Label(frame, text="Model").grid(row=4, column=0, sticky="w", pady=4)
            model_row = ttk.Frame(frame)
            model_row.grid(row=4, column=1, sticky="we", pady=4, padx=(12, 0))
            model_row.columnconfigure(0, weight=1)
            self.cmb_llm_model = ttk.Combobox(
                model_row, textvariable=self.var_llm_model, values=self.llm_models
            )
            self.cmb_llm_model.grid(row=0, column=0, sticky="we")
            self.btn_llm_refresh = ttk.Button(
                model_row, text="Refresh", command=self._refresh_llm_models
            )
            self.btn_llm_refresh.grid(row=0, column=1, padx=(8, 0))
            self._add_labeled_widget(
                frame,
                "API key (optional)",
                5,
                ttk.Entry(frame, textvariable=self.var_llm_key, show="•"),
            )
            self._add_labeled_widget(
                frame,
                "Temperature",
                6,
                ttk.Spinbox(
                    frame, from_=0.0, to=1.5, increment=0.1, textvariable=self.var_llm_temp, width=6
                ),
            )
            ttk.Checkbutton(
                frame, text="Log full LLM prompts for debugging", variable=self.var_llm_debug
            ).grid(row=7, column=0, columnspan=2, sticky="w")
            ttk.Label(
                frame,
                text="⚠ Warning: Debug mode logs transcribed speech and prompts to disk",
                foreground="#cc6600",
                wraplength=440,
                justify="left",
                font=("Segoe UI", 9, "italic"),
            ).grid(row=8, column=0, columnspan=2, sticky="w", padx=(20, 0))
            ttk.Checkbutton(
                frame, text="Use glossary before prompt", variable=self.var_glossary_enable
            ).grid(row=9, column=0, columnspan=2, sticky="w")
            ttk.Label(
                frame,
                text=f"Cleanup prompt saved to {prompt.PROMPT_FILE} (Edit → Prompt…)",
                wraplength=440,
                justify="left",
            ).grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 0))
            ttk.Label(
                frame,
                text=f"Glossary saved to {glossary.GLOSSARY_FILE} (Edit → Glossary…)",
                wraplength=440,
                justify="left",
            ).grid(row=11, column=0, columnspan=2, sticky="w")

        self._open_window("_llm_window", "Cleanup", build)

    def _reset_status_indicator(self) -> None:
        """Reset the floating status indicator to its default location."""
        self._indicator_position = None
        if hasattr(self, "indicator"):
            self.indicator.reset_position()
            self._set_status("ready", "Status indicator reset")

    def _open_log_viewer(self) -> None:
        """Open a window to view the current log file."""

        def build(window: Toplevel) -> None:
            # Set a reasonable default size
            window.geometry("900x600")

            frame = ttk.Frame(window, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)

            # Header with controls
            header = ttk.Frame(frame)
            header.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 8))
            header.columnconfigure(0, weight=1)
            ttk.Label(
                header,
                text=f"Logs are written to {LOG_FILE}",
                wraplength=600,
                justify="left",
            ).grid(row=0, column=0, sticky="w")

            # Wrap toggle
            wrap_var = BooleanVar(value=True)
            ttk.Checkbutton(
                header,
                text="Wrap text",
                variable=wrap_var,
                command=lambda: text.configure(wrap="word" if wrap_var.get() else "none"),
            ).grid(row=0, column=1, padx=(12, 0))

            ttk.Button(header, text="Refresh", command=lambda: load_logs()).grid(
                row=0, column=2, padx=(12, 0)
            )

            # Text widget with scrollbars
            text = Text(frame, wrap="word")
            text.grid(row=1, column=0, sticky="nsew")

            # Vertical scrollbar
            vscrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
            vscrollbar.grid(row=1, column=1, sticky="ns")
            text.configure(yscrollcommand=vscrollbar.set)

            # Horizontal scrollbar
            hscrollbar = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
            hscrollbar.grid(row=2, column=0, sticky="ew")
            text.configure(xscrollcommand=hscrollbar.set, state="disabled")

            def load_logs() -> None:
                text.configure(state="normal")
                text.delete("1.0", END)
                try:
                    content = LOG_FILE.read_text(encoding="utf-8")
                except FileNotFoundError:
                    content = "Log file not found."
                except (OSError, UnicodeDecodeError) as e:
                    # OSError: File access errors
                    # UnicodeDecodeError: Invalid UTF-8 encoding
                    content = f"Could not read log file: {e}"
                text.insert("1.0", content)
                text.see("end")
                text.configure(state="disabled")

            load_logs()

        self._open_window("_log_window", "Logs", build, resizable=True)

    def _refresh_llm_models(self) -> None:
        """Fetch available LLM models from the configured endpoint."""
        endpoint = self.var_llm_endpoint.get().strip()
        api_key = self.var_llm_key.get().strip() or None

        if not endpoint:
            messagebox.showerror("LLM models", "Enter an endpoint before fetching models.")
            return

        if self.btn_llm_refresh:
            self.btn_llm_refresh.config(state="disabled")

        def worker() -> None:
            self._set_status("processing", "Fetching LLM models...")
            try:
                models = llm_cleanup.list_llm_models(endpoint, api_key)
            except llm_cleanup.LLMCleanupError as e:
                error_msg = str(e)

                def on_error() -> None:
                    if self.btn_llm_refresh:
                        self.btn_llm_refresh.config(state="normal")
                    self._set_status("warning", "LLM model fetch failed")
                    messagebox.showerror("LLM models", error_msg)

                self.after(0, on_error)
                return

            def on_success() -> None:
                if self.btn_llm_refresh:
                    self.btn_llm_refresh.config(state="normal")
                self.llm_models = models
                if self.cmb_llm_model:
                    self.cmb_llm_model.config(values=self.llm_models)
                if self.llm_models and self.var_llm_model.get().strip() not in self.llm_models:
                    self.var_llm_model.set(self.llm_models[0])
                if self.llm_models:
                    self._set_status("ready", "LLM models updated")
                else:
                    self._set_status("warning", "No models returned")
                    messagebox.showinfo("LLM models", "No models returned by the endpoint.")

            self.after(0, on_success)

        threading.Thread(target=worker, daemon=True).start()

    def _add_labeled_widget(
        self, parent: ttk.Frame, label: str, row: int, widget: ttk.Widget
    ) -> None:
        """Helper to add a labeled widget."""
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", pady=4 if row > 0 else (0, 4)
        )
        widget.grid(row=row, column=1, sticky="we", pady=4 if row > 0 else (0, 4), padx=(12, 0))

    def _setup_status_indicator(self) -> None:
        """Set up the floating status indicator, which is the app's real face."""
        self.indicator = StatusIndicator(
            self,
            initial_position=self._indicator_position,
            menu_items=(
                ("Show window", self.show_window),
                ("Cleanup settings...", self._open_llm_settings),
                ("-", lambda: None),
                ("Quit", self._on_close),
            ),
        )
        self.indicator.show()
        self._set_status("idle", "Idle")

    def show_window(self) -> None:
        """Bring the main window back from hiding."""
        self.deiconify()
        self.lift()
        self.focus_force()

    def hide_window(self) -> None:
        """Hide the main window, leaving the pill and the hotkey working."""
        self.withdraw()

    def _auto_startup(self) -> None:
        """Perform auto-startup tasks based on settings."""
        self.hotwords_by_app = glossary.load_hotwords_by_app()
        if self.var_history_enable.get():
            days = int(self.var_history_audio_days.get())
            threading.Thread(target=history.prune_audio, args=(days,), daemon=True).start()

        # Open and close one input stream now so the first press is not a cold open.
        device_id = self._parse_input_device_id(self.var_input.get().strip())
        threading.Thread(target=self.recorder.prewarm, args=(device_id,), daemon=True).start()

        self._apply_idle_ttl()
        if not self.var_auto_load_model.get():
            return

        # Schedule model loading for after the event loop starts
        self.after(100, lambda: self._load_model(quiet=True))

    def _set_status(self, state: str, message: str) -> None:
        """Update status in both label and indicator."""
        # Recorded on the calling thread, not in the after() callback: the worker
        # reads it back straight away to decide whether a warning is still standing.
        self._status_state = state
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self._set_status, state, message)
            return
        self.lbl_status.config(text=message)
        if hasattr(self, "indicator"):
            self.indicator.update(state, message)
        logger.info(f"Status: {state} - {message}")

    def _refresh_glossary_cache(self) -> None:
        """Load glossary content from disk."""
        self.glossary_manager = glossary.load_glossary_manager()

    def _load_settings(self) -> None:
        """Load saved settings from disk into Tk variables."""
        saved = settings_store.load_settings()
        if not saved:
            return

        self.app_prompts = app_prompts.normalize_app_prompts(saved.get("app_prompts", {}))
        recent = saved.get("recent_processes")
        if isinstance(recent, list):
            for entry in recent:
                if isinstance(entry, str):
                    self._record_recent_process(entry, None)
                    continue

                # Older files carry window titles. Drop them here and the next
                # save takes them off the disk.
                if isinstance(entry, dict):
                    self._record_recent_process(entry.get("process_name"), None)
                    continue

                if isinstance(entry, (list, tuple)) and len(entry) >= 1:
                    self._record_recent_process(entry[0], None)

        # Migrate old integer device ID to new "index: name" format
        input_val = saved.get("input")
        if isinstance(input_val, int) or (isinstance(input_val, str) and input_val.isdigit()):
            device_id = int(input_val)
            saved["input"] = ""
            try:
                devices = sd.query_devices()
                if 0 <= device_id < len(devices):
                    saved["input"] = f"{device_id}: {devices[device_id].get('name', '')}"
            except (sd.PortAudioError, RuntimeError):
                pass

        for key, name, cast in SETTINGS:
            if key not in saved:
                continue
            try:
                getattr(self, name).set(cast(saved[key]))
            except (TypeError, ValueError):
                continue

        # The API key lives in secure storage, not in the JSON settings.
        api_key = settings_store.get_secure_setting("llm_key")
        if api_key:
            self.var_llm_key.set(api_key)

        pos = saved.get("indicator_position")
        if isinstance(pos, dict):
            x, y = pos.get("x"), pos.get("y")
            if isinstance(x, int) and isinstance(y, int):
                self._indicator_position = (x, y)

    def _num(self, name: str) -> float:
        """A blank or half-typed Spinbox raises TclError; fall back, do not crash."""
        try:
            return float(getattr(self, name).get())
        except (TclError, ValueError):
            return self._defaults[name]

    def _read_vars(self) -> dict[str, Any]:
        """Every setting in SETTINGS, read out of Tk. Main thread only."""
        values: dict[str, Any] = {}
        for key, name, cast in SETTINGS:
            if cast is str:
                values[key] = getattr(self, name).get().strip()
            elif cast is bool:
                values[key] = bool(getattr(self, name).get())
            else:
                values[key] = cast(self._num(name))
        return values

    def _save_settings(self) -> None:
        """Persist current settings to disk."""
        settings = self._read_vars()
        settings["compute"] = config.normalize_compute_type(settings["device"], settings["compute"])
        settings["app_prompts"] = self.app_prompts
        # Process names only: a window title can be a document or a subject
        # line, and the Automation window promises those are never stored.
        settings["recent_processes"] = list(
            dict.fromkeys(entry["process_name"] for entry in self.recent_processes)
        )

        if hasattr(self, "indicator"):
            pos = self.indicator.get_position()
            if pos is not None:
                settings["indicator_position"] = {"x": pos[0], "y": pos[1]}

        if not settings_store.save_settings(settings):
            logger.warning("Could not save settings to disk")

    def _on_close(self) -> None:
        """Handle window close event by saving settings then destroying."""
        try:
            self._save_settings()
            # Only a save that happened counts; main() retries the rest.
            self._settings_saved = True
        except (OSError, UnicodeEncodeError, ValueError, TclError) as e:
            # OSError: File write errors
            # UnicodeEncodeError: Invalid character encoding
            # ValueError: Invalid settings data
            # TclError: a Tk variable that would not read
            logger.error(f"Failed to save settings on close: {e}", exc_info=True)
        finally:
            self.destroy()

    def _open_prompt_dialog(self) -> None:
        """Open prompt editing dialog."""
        dialog = PromptDialog(self, self.prompt_content)
        self.wait_window(dialog)
        if dialog.result is not None:
            new_prompt = dialog.result
            if not new_prompt.strip():
                new_prompt = DEFAULT_LLM_PROMPT
            if prompt.write_saved_prompt(new_prompt):
                self.prompt_content = new_prompt
                self._set_status("ready", "Prompt updated")
            else:
                messagebox.showerror("Prompt", f"Could not save prompt to {prompt.PROMPT_FILE}")

    def _open_glossary_dialog(self) -> None:
        """Open glossary editing dialog."""
        dialog = GlossaryDialog(self, self.glossary_manager)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.glossary_manager = dialog.result
            if self.glossary_manager.save():
                self._set_status("ready", "Glossary updated")
            else:
                messagebox.showerror(
                    "Glossary", f"Could not save glossary to {glossary.GLOSSARY_FILE}"
                )

    def _open_app_prompt_dialog(self) -> None:
        """Open application-specific prompt dialog."""
        dialog = AppPromptDialog(
            self,
            self.app_prompts,
            list(self.recent_processes),
        )
        self.wait_window(dialog)
        if dialog.result is not None:
            self.app_prompts = dialog.result
            self._save_settings()

    def _get_input_device_names(self) -> list[str]:
        """Get list of available audio input devices for dropdown.

        Returns:
            List of device names formatted as "index: name"
        """
        try:
            devices = sd.query_devices()
            names = [
                f"{i}: {d.get('name', '')}"
                for i, d in enumerate(devices)
                if d.get("max_input_channels", 0) > 0
            ]
            return names if names else ["No input devices found"]
        except (sd.PortAudioError, RuntimeError) as e:
            # PortAudioError: PortAudio library errors
            # RuntimeError: sounddevice initialization errors
            logger.warning(f"Could not query audio devices: {e}")
            return [f"Error: {e}"]

    def _parse_input_device_id(self, device_string: str) -> int | None:
        """Parse device ID from dropdown selection.

        Args:
            device_string: Device string in format "index: name"

        Returns:
            Device ID as integer, or None if not found/invalid
        """
        if (
            not device_string
            or device_string.startswith("No input")
            or device_string.startswith("Error")
        ):
            return None

        try:
            # Extract device ID from "index: name" format
            device_id = int(device_string.split(":", 1)[0].strip())
            return device_id
        except (ValueError, IndexError):
            logger.warning(f"Could not parse device ID from: {device_string}")
            return None

    def _capture_asr_config(self) -> None:
        """Copy the recognizer settings out of Tk. Main thread only."""
        self._asr_config = (
            self.var_asr_backend.get().strip() or DEFAULT_ASR_BACKEND,
            self.var_model.get().strip(),
            self.var_device.get().strip(),
            self.var_compute.get().strip(),
        )

    def _asr_description(self) -> str:
        """Name the recognizer actually in use.

        The Whisper model setting does not apply to Cohere, which has one fixed
        model, and naming it there reads as though it did.
        """
        backend = self.var_asr_backend.get().strip() or DEFAULT_ASR_BACKEND
        if backend == "whisper":
            return f"Whisper {self.var_model.get().strip()}"
        return f"{backend} {asr.CohereBackend.MODEL_ID}"

    def _build_backend(self):
        """Factory for the Resident. Runs on a loader thread: no Tk in here."""
        backend, model_name, device, compute = self._asr_config
        # Read from the captured config, not Tk: this runs on a loader thread.
        if backend == "whisper":
            logger.info(f"Loading Whisper {model_name} on {device} ({compute})")
        else:
            logger.info(f"Loading {backend} {asr.CohereBackend.MODEL_ID} on {device}")
        return asr.load_backend(
            backend,
            model_name,
            device,
            compute,
            on_warning=lambda m: self._set_status("warning", m),
        )

    def _apply_idle_ttl(self) -> None:
        """Push the TTL setting onto the Resident. 0 minutes means never unload."""
        ttl = max(0.0, self._num("var_idle_ttl_minutes")) * 60.0
        self.asr.ttl = ttl
        self.s1.ttl = ttl
        self._capture_asr_config()
        self._capture_s1_style()

    def _load_model(self, quiet: bool = False) -> None:
        """Warm the recognizer, and report when it is up.

        The recording path no longer waits on this: the hotkey works cold, and
        _on_hotkey_press warms the model while the user is still speaking.
        """
        # Set input device if provided
        device_id = self._parse_input_device_id(self.var_input.get().strip())
        if device_id is not None:
            sd.default.device = (device_id, None)

        self._apply_idle_ttl()
        self._set_status("processing", f"Loading {self._asr_description()}...")
        self.asr.warm()

        def watcher():
            try:
                self.asr.get()
            except (OSError, RuntimeError, ValueError) as e:
                error_msg = str(e)

                def on_error():
                    self._set_status("error", "Model load failed")
                    logger.error(f"Model load failed: {error_msg}", exc_info=True)
                    if not quiet:
                        messagebox.showerror("Model error", error_msg)

                self.after(0, on_error)
                return

            def on_success():
                self._set_status("ready", "Model ready")
                self.btn_load.config(state="disabled")
                self.btn_hotkey.config(state="normal")
                self.btn_toggle.config(state="normal")
                if quiet and self.var_auto_register_hotkey.get():
                    self.after(100, lambda: self._register_hotkey(quiet=True))

            self.after(0, on_success)

        threading.Thread(target=watcher, daemon=True).start()

    def _reload_backend(self) -> None:
        """Drop the resident recognizer so the next press builds the new one."""
        self.asr.release()
        self._capture_asr_config()
        self._apply_idle_ttl()
        self._set_status("ready", f"ASR backend: {self.var_asr_backend.get()}")

    def _register_hotkey(self, quiet: bool = False) -> None:
        """Register the global hotkey.

        Args:
            quiet: Log a failure instead of raising a dialog (the startup caller).
        """
        combo = self.var_hotkey.get().strip()
        try:
            # One manager for the life of the app: a second one would leave the
            # first one's hook installed, and two hooks means two recordings.
            if self.hotkey_manager is None:
                # The hook thread must not touch Tk; marshal every callback.
                self.hotkey_manager = hotkeys.HotkeyManager(
                    lambda: self._post(self._on_hotkey_press),
                    lambda: self._post(self._on_hotkey_release),
                    lambda: self._post(self._on_hotkey_cancel),
                )
            self.hotkey_manager.register(combo)
            self._set_status("ready", f"Ready (hotkey: {combo})")
            self.btn_hotkey.config(state="disabled")
            logger.info(f"Hotkey registered: {combo}")
        except hotkeys.HotkeyError as e:
            self._set_status("warning" if quiet else "error", "Hotkey registration failed")
            logger.warning(f"Hotkey registration failed: {e}")
            if not quiet:
                messagebox.showerror("Hotkey", str(e))

    def _apply_hotkey_change(self) -> None:
        """Re-register after the Automation window edits the chord.

        The entry writes the variable and nothing else, so without this the new
        chord would only take effect on the next launch.
        """
        if not self.hotkey_manager:
            return
        combo = self.var_hotkey.get().strip()
        if combo == self.hotkey_manager.chord_string:
            return
        # register() parses before it unhooks, so a typo leaves the old chord live.
        self._register_hotkey()

    def _post(self, handler: Callable[[], None]) -> None:
        """Hand a hook-thread event to the Tk thread."""
        self.after(0, handler)

    def _on_hotkey_press(self) -> None:
        """Chord went down: start recording, or end a recording locked by a tap."""
        # Load the recognizer while the user speaks; cold, the wait they feel is
        # max(0, load - utterance) rather than the whole load. Settings are read
        # here, on the Tk thread, because the loader thread must not touch Tk.
        self._capture_asr_config()
        self.asr.warm()
        if self.var_cleanup_backend.get().strip() == "s1":
            self._capture_s1_style()
            self.s1.warm()
        if self.recorder.is_recording():
            self._stop_and_transcribe()
            return
        self._press_at = time.monotonic()
        self._start_recording()

    def _on_hotkey_release(self) -> None:
        """Chord came up: transcribe, unless it was a tap, which locks recording on."""
        if not self.recorder.is_recording():
            return
        if time.monotonic() - self._press_at < TAP_SECONDS:
            self._set_status("listening", "Recording (locked) - press again to stop")
            return
        self._stop_and_transcribe()

    def _on_hotkey_cancel(self) -> None:
        """Another key joined the chord: throw the audio away."""
        if not self.recorder.is_recording():
            return
        self.recorder.stop()
        self.recorder.get_buffer()  # discard
        self.btn_toggle.config(text="Start recording")
        self._set_status("ready", "Cancelled")

    def _toggle_record(self) -> None:
        """Toggle recording on/off (the button; the hotkey uses press/release)."""
        if self.recorder.is_recording():
            self._stop_and_transcribe()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        """Open the microphone. The status cue waits for the first block of audio."""
        inp = self.var_input.get().strip()
        device_id = self._parse_input_device_id(inp)

        try:
            self.recorder.start(device_id, on_first_audio=self._on_first_audio)
        except (sd.PortAudioError, RuntimeError, ValueError) as e:
            # PortAudioError: PortAudio device errors
            # RuntimeError: sounddevice initialization errors
            # ValueError: Invalid device ID
            self._set_status("error", "Audio input failed")
            logger.error(f"Audio start failed: {e}", exc_info=True)
            messagebox.showerror("Audio", f"Could not start input:\n{e}")
            return

        self._set_status("processing", "Opening microphone...")
        self.btn_toggle.config(text="Stop and transcribe")

    def _on_first_audio(self) -> None:
        """Runs on the audio thread the instant capture is live."""
        # winsound.Beep blocks for its full duration; never on the audio thread.
        threading.Thread(target=winsound.Beep, args=(BEEP_HZ, BEEP_MS), daemon=True).start()
        self._set_status("listening", "Recording - release to transcribe")

    def _stop_and_transcribe(self) -> None:
        """Close the microphone and hand the buffer to the pipeline."""
        self.recorder.stop()
        self._set_status("transcribing", "Transcribing...")
        self.btn_toggle.config(text="Start recording")
        # Settings are read here, on the Tk thread; the worker gets the copy.
        cfg = self._capture_dictation_config()
        threading.Thread(target=self._transcribe_and_clean, args=(cfg,), daemon=True).start()

    def _capture_dictation_config(self) -> dict[str, Any]:
        """Copy every setting a dictation uses out of Tk. Main thread only."""
        cfg = self._read_vars()
        cfg["initial_prompt"] = cfg["initial_prompt"] or None
        cfg["llm_key"] = cfg["llm_key"] or None
        return cfg

    def _append_transcript(self, text: str) -> None:
        """Add a line to the transcript box. Main thread only."""
        self.txt_out.insert(END, text)
        self.txt_out.see(END)

    def _transcribe_and_clean(self, cfg: dict[str, Any]) -> None:
        """Transcribe audio and optionally clean with LLM.

        Runs on a worker thread: settings come from cfg, and anything that
        touches a widget goes through after().
        """
        audio_data = self.recorder.get_buffer()
        if audio_data is None:
            self._set_status("warning", "No audio captured")
            return

        active_context = app_context.get_active_context()
        if active_context and active_context.process_name:
            self._record_recent_process(active_context.process_name, active_context.window_title)
        prompt_context = app_context.format_context_for_prompt(active_context)
        # ponytail: read without a lock; safe while dialogs replace these objects
        # (app_prompts, glossary_manager, prompt_content) rather than mutate them
        app_prompt = app_prompts.resolve_app_prompt(self.app_prompts, active_context)

        was_cold = not self.asr.is_loaded()
        hotwords = glossary.hotwords_for_app(
            active_context.process_name if active_context else None,
            self.hotwords_by_app,
            self.glossary_manager,
        )
        if hotwords:
            logger.debug(f"Hotwords for this dictation: {len(hotwords)} chars")

        started = time.monotonic()
        try:
            # Build VAD parameters if VAD is enabled
            vad_params = None
            if cfg["vad_enabled"]:
                vad_params = {
                    "threshold": cfg["vad_threshold"],
                    "min_speech_duration_ms": cfg["vad_min_speech_ms"],
                    "min_silence_duration_ms": cfg["vad_min_silence_ms"],
                    "speech_pad_ms": cfg["vad_speech_pad_ms"],
                }

            if not self.asr.is_loaded():
                self._set_status("processing", "Loading model...")
            backend = self.asr.get()
            text = backend.transcribe(
                audio_data,
                hotwords=hotwords,
                beam_size=cfg["beam_size"],
                vad_filter=cfg["vad_enabled"],
                vad_parameters=vad_params,
                compression_ratio_threshold=cfg["compression_ratio_threshold"],
                log_prob_threshold=cfg["log_prob_threshold"],
                no_speech_threshold=cfg["no_speech_threshold"],
                temperature=cfg["temperature"],
                initial_prompt=cfg["initial_prompt"],
            )
        except (transcription.TranscriptionError, OSError, RuntimeError, ValueError) as e:
            self._set_status("error", "Transcription failed")
            logger.error(f"Transcription failed: {e}", exc_info=True)
            self.after(0, messagebox.showerror, "Transcribe", str(e))
            return

        asr_ms = int((time.monotonic() - started) * 1000)

        if not text:
            self._set_status("warning", "No speech detected")
            return

        self._refresh_glossary_cache()
        glossary_enabled = bool(cfg["glossary_enable"] and self.glossary_manager.rules)

        normalized_text = glossary.apply_glossary(
            text, self.glossary_manager if glossary_enabled else None
        )
        final_text = normalized_text

        cleanup_started = time.monotonic()
        cleaned_text: str | None = None
        backend = cfg["cleanup_backend"]
        if backend == "s1":
            cleaned_text = self._clean_with_s1(normalized_text, active_context)
            final_text = cleaned_text or final_text
        elif backend == "endpoint" and cfg["llm_endpoint"] and cfg["llm_model"]:
            self._set_status("processing", "Cleaning with LLM...")
            try:
                cleaned = llm_cleanup.clean_with_llm(
                    raw_text=normalized_text,
                    endpoint=cfg["llm_endpoint"],
                    model=cfg["llm_model"],
                    api_key=cfg["llm_key"],
                    prompt=self.prompt_content or DEFAULT_LLM_PROMPT,
                    glossary=self.glossary_manager if glossary_enabled else None,
                    temperature=cfg["llm_temp"],
                    app_prompt=app_prompt,
                    prompt_context=prompt_context,
                    debug_logging=cfg["llm_debug"],
                )
                if cleaned:
                    cleaned_text = cleaned
                    final_text = cleaned
                    self._set_status("ready", "Cleaned by LLM")
                else:
                    self._set_status("warning", "LLM failed, used raw text")
            except llm_cleanup.LLMCleanupError as e:
                self._set_status("warning", "LLM failed, used raw text")
                logger.warning(f"LLM cleanup failed: {e}")

        cleanup_ms = int((time.monotonic() - cleanup_started) * 1000)

        if glossary_enabled:
            final_text = glossary.apply_glossary(final_text, self.glossary_manager)

        if cfg["history_enable"]:
            history.record(
                raw=text,
                cleaned=cleaned_text,
                final=final_text,
                process_name=active_context.process_name if active_context else None,
                asr_backend=cfg["asr_backend"],
                cleanup_backend=backend,
                asr_ms=asr_ms,
                cleanup_ms=cleanup_ms,
                cold=was_cold,
                audio=audio_data,
                audio_days=cfg["history_audio_days"],
            )

        # Display and copy result
        ts = time.strftime("%H:%M:%S")
        self.after(0, self._append_transcript, f"[{ts}] {final_text}\n")

        self._deliver(final_text, cfg)

        if self._status_state not in {"error", "warning"}:
            self._set_status("ready", "Ready")

    def _capture_s1_style(self) -> None:
        """Copy the global control-line settings out of Tk. Main thread only."""
        self._s1_style = {
            "styling": self.var_s1_styling.get().strip() or s1.DEFAULT_STYLING,
            "structure": self.var_s1_structure.get().strip() or s1.DEFAULT_STRUCTURE,
            "context": self.var_s1_context.get().strip() or s1.DEFAULT_CONTEXT,
        }

    def _s1_style_for(self, context) -> dict[str, str]:
        """The control line for this dictation: the global setting, overridden by
        whatever the matching per-app rule sets."""
        style = dict(getattr(self, "_s1_style", {}))
        if not style:
            style = {
                "styling": s1.DEFAULT_STYLING,
                "structure": s1.DEFAULT_STRUCTURE,
                "context": s1.DEFAULT_CONTEXT,
            }
        style.update(app_prompts.resolve_app_style(self.app_prompts, context))
        return style

    def _clean_with_s1(self, text: str, context) -> str | None:
        """Clean in-process. Returns None when cleanup could not run."""
        if not self.s1.is_loaded():
            self._set_status("processing", "Loading cleanup model...")
        started = time.monotonic()
        try:
            cleaner = self.s1.get()
            cleaned: str | None = cleaner.clean(text, **self._s1_style_for(context))
        except (OSError, RuntimeError, ValueError, ImportError) as e:
            # No cleanup model is a degraded dictation, not a lost one.
            self.after(0, self.var_cleanup_backend.set, "off")
            self._set_status("warning", "Cleanup unavailable; using raw text")
            logger.warning(f"S1 cleanup failed, backend off for this session: {e}")
            return None
        if not cleaned:
            self._set_status("warning", "Cleanup returned nothing, used raw text")
            return None
        logger.info(
            f"S1 cleanup on {'GPU' if cleaner.on_gpu else 'CPU'} "
            f"in {time.monotonic() - started:.2f}s"
        )
        self._set_status("ready", "Cleaned")
        return cleaned

    def _deliver(self, text: str, cfg: dict[str, Any]) -> None:
        """Paste the dictation and give the clipboard back.

        The clipboard is borrowed, not taken: whatever was on it - text, HTML,
        an image, a copied file - goes back once the target app has read ours.
        """
        try:
            saved = clipboard.snapshot()
        except clipboard.ClipboardError as e:
            # Someone else holds it. Better to lose their clipboard than the dictation.
            logger.warning(f"Could not snapshot the clipboard: {e}")
            saved = None

        try:
            clipboard.set_text(text)
        except clipboard.ClipboardError as e:
            # Another app is holding the clipboard open. The text is still in the
            # transcript box, so the dictation is not lost, only undelivered.
            self._set_status("error", "Clipboard locked; text is in the transcript")
            logger.error(f"Clipboard write failed: {e}", exc_info=True)
            return

        # From here the clipboard holds our text: whatever happens, give theirs back.
        try:
            if cfg["auto_paste"]:
                self._wait_for_modifiers_up()
                time.sleep(cfg["paste_delay"])
                # Shift+Insert, not Ctrl+V: it is what the terminal and the commercial
                # dictation apps use.
                if not clipboard.send_paste():
                    self._set_status("error", "Auto-paste failed")
                    logger.error("SendInput refused the paste keystroke")
                elif self._status_state not in {"error", "warning"}:
                    # A cleanup warning outranks the news that the paste landed.
                    self._set_status("ready", "Pasted into active window")
        finally:
            if saved is not None:
                # Give the target app time to read our text before taking it back.
                time.sleep(cfg["restore_delay"])
                try:
                    clipboard.restore(saved)
                except clipboard.ClipboardError as e:
                    logger.warning(f"Could not restore the clipboard: {e}")

    def _wait_for_modifiers_up(self, timeout: float = MODIFIER_WAIT_SECONDS) -> None:
        """Block until every modifier key is released.

        Injecting Shift+Insert while Ctrl or Win is still held sends the target
        app a different shortcut entirely, and nothing pastes. Tap-to-lock is the
        one flow that reaches here with the chord still down - every other path
        ends on the release - so the wait has to outlast a deliberate hold.
        """
        if not self.hotkey_manager:
            return
        deadline = time.monotonic() + timeout
        while not self.hotkey_manager.modifiers_up() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.hotkey_manager.modifiers_up():
            logger.warning(
                f"Modifiers still held after {timeout}s; pasting anyway, it may not land"
            )

    def _record_recent_process(self, process_name: str | None, window_title: str | None) -> None:
        """Track recently seen applications, newest first, one entry per process and title."""
        normalized_process = (process_name or "").strip()
        if not normalized_process:
            return

        normalized_window = (window_title.strip() or None) if window_title else None
        entry = {"process_name": normalized_process, "window_title": normalized_window}
        if entry in self.recent_processes:
            self.recent_processes.remove(entry)
        self.recent_processes.appendleft(entry)


def main() -> None:
    """Main entry point for the GUI application."""
    # Two instances means two keyboard hooks, which means two pastes per dictation.
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\WhisperDictate")
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        logger.info("Another instance is already running; exiting")
        return

    app = App()
    try:
        app.mainloop()
    finally:
        if hasattr(app, "_save_settings") and not getattr(app, "_settings_saved", False):
            try:
                app._save_settings()
                app._settings_saved = True
            except TclError as e:
                # Tk variables outlive destroy(), so this normally works. If one
                # will not read, the hook below still has to come out.
                logger.error(f"Could not save settings on exit: {e}")
        # Cleanup
        if hasattr(app, "hotkey_manager") and app.hotkey_manager:
            app.hotkey_manager.unregister()
        app.recorder.stop()


if __name__ == "__main__":
    main()
