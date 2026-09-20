"""Streamlined GUI for whisper-dictate with optional LLM cleanup."""

import ctypes
import threading
import time
import winsound
from collections import deque
from collections.abc import Callable
from tkinter import END, BooleanVar, DoubleVar, Menu, StringVar, Text, Tk, Toplevel, messagebox, ttk

import sounddevice as sd

from whisper_dictate import (
    app_context,
    app_prompts,
    asr,
    audio,
    clipboard,
    config,
    glossary,
    hotkeys,
    llm_cleanup,
    prompt,
    settings_store,
    transcription,
)
from whisper_dictate.app_prompt_dialog import AppPromptDialog
from whisper_dictate.config import (
    DEFAULT_ASR_BACKEND,
    DEFAULT_AUTO_LOAD_MODEL,
    DEFAULT_AUTO_REGISTER_HOTKEY,
    DEFAULT_COMPUTE,
    DEFAULT_DEVICE,
    DEFAULT_IDLE_TTL_MINUTES,
    DEFAULT_LLM_DEBUG,
    DEFAULT_LLM_ENABLED,
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

# Note: Audio recorder thread is now managed internally by AudioRecorder class


class App(Tk):
    """Main application window."""

    RECENT_PROCESSES_MAX = 15

    def __init__(self):
        super().__init__()
        self.title("Whisper Dictate + LLM")
        self.geometry("980x680")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
        self.hotkey_manager: hotkeys.HotkeyManager | None = None
        self._press_at = 0.0
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
        self.var_model_display = StringVar(value="")  # For formatted model name in dropdown
        self.var_device = StringVar(value=DEFAULT_DEVICE)
        self.var_compute = StringVar(value=DEFAULT_COMPUTE)
        self.var_input = StringVar(value="")
        self.var_hotkey = StringVar(value="CTRL+SPACE")
        self.var_auto_paste = BooleanVar(value=True)
        self.var_paste_delay = DoubleVar(value=0.15)
        self.var_restore_delay = DoubleVar(value=0.6)

        self.var_llm_enable = BooleanVar(value=DEFAULT_LLM_ENABLED)
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
        self.var_word_timestamps = BooleanVar(value=False)
        self.var_temperature = DoubleVar(value=0.0)
        self.var_beam_size = DoubleVar(value=5)
        self.var_initial_prompt = StringVar(value="")

        self._indicator_position: tuple[int, int] | None = None

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

            # Auto-startup options
            ttk.Separator(frame, orient="horizontal").grid(
                row=5, column=0, sticky="we", pady=(12, 8)
            )
            ttk.Label(frame, text="Startup", font=("Segoe UI", 9, "bold")).grid(
                row=6, column=0, sticky="w"
            )
            ttk.Checkbutton(
                frame, text="Auto-load model on startup", variable=self.var_auto_load_model
            ).grid(row=7, column=0, sticky="w", pady=(4, 0))
            ttk.Checkbutton(
                frame,
                text="Auto-register hotkey after model loads",
                variable=self.var_auto_register_hotkey,
            ).grid(row=8, column=0, sticky="w")

        self._open_window("_automation_window", "Automation", build)

    def _open_advanced_transcription_settings(self) -> None:
        """Open advanced transcription settings window."""

        def build(window: Toplevel) -> None:
            frame = ttk.Frame(window, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(1, weight=1)

            row = 0

            # VAD Settings Section
            ttk.Label(frame, text="Voice Activity Detection", font=("Segoe UI", 9, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(0, 8)
            )
            row += 1

            ttk.Checkbutton(frame, text="Enable VAD filtering", variable=self.var_vad_enabled).grid(
                row=row, column=0, columnspan=2, sticky="w"
            )
            row += 1

            self._add_labeled_widget(
                frame,
                "VAD threshold (0.3-0.8)",
                row,
                ttk.Spinbox(
                    frame,
                    from_=0.1,
                    to=1.0,
                    increment=0.1,
                    textvariable=self.var_vad_threshold,
                    width=10,
                ),
            )
            row += 1

            self._add_labeled_widget(
                frame,
                "Min speech duration (ms)",
                row,
                ttk.Spinbox(
                    frame,
                    from_=100,
                    to=1000,
                    increment=50,
                    textvariable=self.var_vad_min_speech_ms,
                    width=10,
                ),
            )
            row += 1

            self._add_labeled_widget(
                frame,
                "Min silence duration (ms)",
                row,
                ttk.Spinbox(
                    frame,
                    from_=100,
                    to=2000,
                    increment=100,
                    textvariable=self.var_vad_min_silence_ms,
                    width=10,
                ),
            )
            row += 1

            self._add_labeled_widget(
                frame,
                "Speech padding (ms)",
                row,
                ttk.Spinbox(
                    frame,
                    from_=100,
                    to=1000,
                    increment=50,
                    textvariable=self.var_vad_speech_pad_ms,
                    width=10,
                ),
            )
            row += 1

            # Separator
            ttk.Separator(frame, orient="horizontal").grid(
                row=row, column=0, columnspan=2, sticky="we", pady=(12, 8)
            )
            row += 1

            # Hallucination Prevention Section
            ttk.Label(frame, text="Hallucination Prevention", font=("Segoe UI", 9, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(0, 8)
            )
            row += 1

            self._add_labeled_widget(
                frame,
                "Compression ratio threshold",
                row,
                ttk.Spinbox(
                    frame,
                    from_=1.0,
                    to=5.0,
                    increment=0.1,
                    textvariable=self.var_compression_ratio_threshold,
                    width=10,
                ),
            )
            row += 1

            self._add_labeled_widget(
                frame,
                "Log probability threshold",
                row,
                ttk.Spinbox(
                    frame,
                    from_=-2.0,
                    to=0.0,
                    increment=0.1,
                    textvariable=self.var_log_prob_threshold,
                    width=10,
                ),
            )
            row += 1

            self._add_labeled_widget(
                frame,
                "No speech threshold",
                row,
                ttk.Spinbox(
                    frame,
                    from_=0.0,
                    to=1.0,
                    increment=0.1,
                    textvariable=self.var_no_speech_threshold,
                    width=10,
                ),
            )
            row += 1

            # Separator
            ttk.Separator(frame, orient="horizontal").grid(
                row=row, column=0, columnspan=2, sticky="we", pady=(12, 8)
            )
            row += 1

            # Other Advanced Settings
            ttk.Label(frame, text="Other Settings", font=("Segoe UI", 9, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(0, 8)
            )
            row += 1

            self._add_labeled_widget(
                frame,
                "Beam size (1-10)",
                row,
                ttk.Spinbox(
                    frame, from_=1, to=10, increment=1, textvariable=self.var_beam_size, width=10
                ),
            )
            row += 1

            self._add_labeled_widget(
                frame,
                "Temperature (0.0-1.5)",
                row,
                ttk.Spinbox(
                    frame,
                    from_=0.0,
                    to=1.5,
                    increment=0.1,
                    textvariable=self.var_temperature,
                    width=10,
                ),
            )
            row += 1

            ttk.Checkbutton(
                frame, text="Enable word timestamps", variable=self.var_word_timestamps
            ).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1

            # Initial prompt
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
            row += 1

            # Help text
            ttk.Label(
                frame,
                text="⚠ These are advanced settings. Defaults work well for most users.",
                foreground="#cc6600",
                wraplength=440,
                justify="left",
                font=("Segoe UI", 9, "italic"),
            ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self._open_window(
            "_advanced_transcription_window", "Advanced Transcription (Whisper only)", build
        )

    def _open_llm_settings(self) -> None:
        """Open LLM cleanup settings window."""

        def build(window: Toplevel) -> None:
            frame = ttk.Frame(window, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(1, weight=1)

            ttk.Checkbutton(
                frame, text="Use LLM cleanup (OpenAI compatible)", variable=self.var_llm_enable
            ).grid(row=0, column=0, sticky="w", columnspan=2)
            self._add_labeled_widget(
                frame, "Endpoint", 1, ttk.Entry(frame, textvariable=self.var_llm_endpoint)
            )
            ttk.Label(frame, text="Model").grid(row=2, column=0, sticky="w", pady=4)
            model_row = ttk.Frame(frame)
            model_row.grid(row=2, column=1, sticky="we", pady=4, padx=(12, 0))
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
                3,
                ttk.Entry(frame, textvariable=self.var_llm_key, show="•"),
            )
            self._add_labeled_widget(
                frame,
                "Temperature",
                4,
                ttk.Spinbox(
                    frame, from_=0.0, to=1.5, increment=0.1, textvariable=self.var_llm_temp, width=6
                ),
            )
            ttk.Checkbutton(
                frame, text="Log full LLM prompts for debugging", variable=self.var_llm_debug
            ).grid(row=5, column=0, columnspan=2, sticky="w")
            ttk.Label(
                frame,
                text="⚠ Warning: Debug mode logs transcribed speech and prompts to disk",
                foreground="#cc6600",
                wraplength=440,
                justify="left",
                font=("Segoe UI", 9, "italic"),
            ).grid(row=6, column=0, columnspan=2, sticky="w", padx=(20, 0))
            ttk.Checkbutton(
                frame, text="Use glossary before prompt", variable=self.var_glossary_enable
            ).grid(row=7, column=0, columnspan=2, sticky="w")
            ttk.Label(
                frame,
                text=f"Cleanup prompt saved to {prompt.PROMPT_FILE} (Edit → Prompt…)",
                wraplength=440,
                justify="left",
            ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
            ttk.Label(
                frame,
                text=f"Glossary saved to {glossary.GLOSSARY_FILE} (Edit → Glossary…)",
                wraplength=440,
                justify="left",
            ).grid(row=9, column=0, columnspan=2, sticky="w")

        self._open_window("_llm_window", "LLM cleanup", build)

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
        """Set up the floating status indicator."""
        self.indicator = StatusIndicator(self, initial_position=self._indicator_position)
        self._set_status("idle", "Idle")

    def _auto_startup(self) -> None:
        """Perform auto-startup tasks based on settings."""
        # Open and close one input stream now so the first press is not a cold open.
        device_id = self._parse_input_device_id(self.var_input.get().strip())
        threading.Thread(target=audio.prewarm, args=(device_id,), daemon=True).start()

        self._apply_idle_ttl()
        if not self.var_auto_load_model.get():
            return

        # Schedule model loading for after the event loop starts
        self.after(100, lambda: self._load_model(quiet=True))

    def _set_status(self, state: str, message: str) -> None:
        """Update status in both label and indicator."""
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

                if isinstance(entry, dict):
                    process = entry.get("process_name")
                    window_title = entry.get("window_title")
                    self._record_recent_process(process, window_title)
                    continue

                if isinstance(entry, (list, tuple)) and len(entry) >= 1:
                    process = entry[0]
                    window_title = entry[1] if len(entry) > 1 else None
                    self._record_recent_process(process, window_title)

        def set_if_present(key, var, cast=None):
            if key not in saved:
                return
            value = saved[key]
            if cast:
                try:
                    value = cast(value)
                except (TypeError, ValueError):
                    return
            var.set(value)

        set_if_present("model", self.var_model, str)
        set_if_present("asr_backend", self.var_asr_backend, str)
        set_if_present("idle_ttl_minutes", self.var_idle_ttl_minutes, float)
        set_if_present("device", self.var_device, str)
        set_if_present("compute", self.var_compute, str)

        # Migrate old integer device ID to new "index: name" format
        if "input" in saved:
            input_val = saved["input"]
            if isinstance(input_val, int) or (isinstance(input_val, str) and input_val.isdigit()):
                # Old format: just a number - convert to "index: name" format
                device_id = int(input_val)
                try:
                    devices = sd.query_devices()
                    if 0 <= device_id < len(devices):
                        device_name = devices[device_id].get("name", "")
                        self.var_input.set(f"{device_id}: {device_name}")
                    else:
                        # Invalid device ID, clear it
                        self.var_input.set("")
                except (sd.PortAudioError, RuntimeError):
                    self.var_input.set("")
            else:
                # Already in new format or empty
                set_if_present("input", self.var_input, str)

        set_if_present("hotkey", self.var_hotkey, str)
        set_if_present("auto_paste", self.var_auto_paste, bool)
        set_if_present("paste_delay", self.var_paste_delay, float)
        set_if_present("restore_delay", self.var_restore_delay, float)
        set_if_present("llm_enable", self.var_llm_enable, bool)
        set_if_present("llm_endpoint", self.var_llm_endpoint, str)
        set_if_present("llm_model", self.var_llm_model, str)
        # Load API key from secure storage (not from JSON settings)
        api_key = settings_store.get_secure_setting("llm_key")
        if api_key:
            self.var_llm_key.set(api_key)
        set_if_present("llm_temp", self.var_llm_temp, float)
        set_if_present("llm_debug", self.var_llm_debug, bool)
        set_if_present("glossary_enable", self.var_glossary_enable, bool)
        set_if_present("auto_load_model", self.var_auto_load_model, bool)
        set_if_present("auto_register_hotkey", self.var_auto_register_hotkey, bool)

        # Load advanced transcription settings
        set_if_present("vad_enabled", self.var_vad_enabled, bool)
        set_if_present("vad_threshold", self.var_vad_threshold, float)
        set_if_present("vad_min_speech_ms", self.var_vad_min_speech_ms, float)
        set_if_present("vad_min_silence_ms", self.var_vad_min_silence_ms, float)
        set_if_present("vad_speech_pad_ms", self.var_vad_speech_pad_ms, float)
        set_if_present("compression_ratio_threshold", self.var_compression_ratio_threshold, float)
        set_if_present("log_prob_threshold", self.var_log_prob_threshold, float)
        set_if_present("no_speech_threshold", self.var_no_speech_threshold, float)
        set_if_present("word_timestamps", self.var_word_timestamps, bool)
        set_if_present("temperature", self.var_temperature, float)
        set_if_present("beam_size", self.var_beam_size, float)
        set_if_present("initial_prompt", self.var_initial_prompt, str)

        pos = saved.get("indicator_position")
        if isinstance(pos, dict):
            x, y = pos.get("x"), pos.get("y")
            if isinstance(x, int) and isinstance(y, int):
                self._indicator_position = (x, y)

    def _save_settings(self) -> None:
        """Persist current settings to disk."""
        settings = {
            "model": self.var_model.get().strip(),
            "asr_backend": self.var_asr_backend.get().strip(),
            "idle_ttl_minutes": float(self.var_idle_ttl_minutes.get()),
            "device": self.var_device.get().strip(),
            "compute": config.normalize_compute_type(
                self.var_device.get().strip(), self.var_compute.get().strip()
            ),
            "input": self.var_input.get().strip(),
            "hotkey": self.var_hotkey.get().strip(),
            "auto_paste": bool(self.var_auto_paste.get()),
            "paste_delay": float(self.var_paste_delay.get()),
            "restore_delay": float(self.var_restore_delay.get()),
            "llm_enable": bool(self.var_llm_enable.get()),
            "llm_endpoint": self.var_llm_endpoint.get().strip(),
            "llm_model": self.var_llm_model.get().strip(),
            "llm_key": self.var_llm_key.get(),
            "llm_temp": float(self.var_llm_temp.get()),
            "llm_debug": bool(self.var_llm_debug.get()),
            "glossary_enable": bool(self.var_glossary_enable.get()),
            "auto_load_model": bool(self.var_auto_load_model.get()),
            "auto_register_hotkey": bool(self.var_auto_register_hotkey.get()),
            "app_prompts": self.app_prompts,
            "recent_processes": [
                {
                    "process_name": entry.get("process_name", ""),
                    "window_title": entry.get("window_title"),
                }
                for entry in self.recent_processes
                if entry.get("process_name")
            ],
            # Advanced transcription settings
            "vad_enabled": bool(self.var_vad_enabled.get()),
            "vad_threshold": float(self.var_vad_threshold.get()),
            "vad_min_speech_ms": float(self.var_vad_min_speech_ms.get()),
            "vad_min_silence_ms": float(self.var_vad_min_silence_ms.get()),
            "vad_speech_pad_ms": float(self.var_vad_speech_pad_ms.get()),
            "compression_ratio_threshold": float(self.var_compression_ratio_threshold.get()),
            "log_prob_threshold": float(self.var_log_prob_threshold.get()),
            "no_speech_threshold": float(self.var_no_speech_threshold.get()),
            "word_timestamps": bool(self.var_word_timestamps.get()),
            "temperature": float(self.var_temperature.get()),
            "beam_size": int(self.var_beam_size.get()),
            "initial_prompt": self.var_initial_prompt.get().strip(),
        }

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
        except (OSError, UnicodeEncodeError, ValueError) as e:
            # OSError: File write errors
            # UnicodeEncodeError: Invalid character encoding
            # ValueError: Invalid settings data
            logger.error(f"Failed to save settings on close: {e}", exc_info=True)
        finally:
            self._settings_saved = True
            self.destroy()

    def _format_recent_processes_for_dialog(self) -> list[dict[str, str | None]]:
        formatted: list[dict[str, str | None]] = []
        for entry in self.recent_processes:
            process = (entry.get("process_name") or "").strip()
            if not process:
                continue
            formatted.append(
                {
                    "process_name": process,
                    "window_title": entry.get("window_title"),
                }
            )
        return formatted

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
            list(self._format_recent_processes_for_dialog()),
        )
        self.wait_window(dialog)
        if dialog.result is not None:
            self.app_prompts = dialog.result

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

    def _build_backend(self):
        """Factory for the Resident. Runs on a loader thread: no Tk in here."""
        backend, model_name, device, compute = self._asr_config
        logger.info(f"Loading ASR backend {backend} ({model_name} on {device}, {compute})")
        return asr.load_backend(
            backend,
            model_name,
            device,
            compute,
            on_warning=lambda m: self._set_status("warning", m),
        )

    def _apply_idle_ttl(self) -> None:
        """Push the TTL setting onto the Resident. 0 minutes means never unload."""
        self.asr.ttl = max(0.0, float(self.var_idle_ttl_minutes.get())) * 60.0
        self._capture_asr_config()

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
        self._set_status("processing", f"Loading {self.var_model.get().strip()}...")
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
        if audio.is_recording():
            self._stop_and_transcribe()
            return
        self._press_at = time.monotonic()
        self._start_recording()

    def _on_hotkey_release(self) -> None:
        """Chord came up: transcribe, unless it was a tap, which locks recording on."""
        if not audio.is_recording():
            return
        if time.monotonic() - self._press_at < TAP_SECONDS:
            self._set_status("listening", "Recording (locked) - press again to stop")
            return
        self._stop_and_transcribe()

    def _on_hotkey_cancel(self) -> None:
        """Another key joined the chord: throw the audio away."""
        if not audio.is_recording():
            return
        audio.stop_recording()
        audio.get_audio_buffer()  # discard
        self.btn_toggle.config(text="Start recording")
        self._set_status("ready", "Cancelled")

    def _toggle_record(self) -> None:
        """Toggle recording on/off (the button; the hotkey uses press/release)."""
        if audio.is_recording():
            self._stop_and_transcribe()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        """Open the microphone. The status cue waits for the first block of audio."""
        inp = self.var_input.get().strip()
        device_id = self._parse_input_device_id(inp)

        try:
            audio.start_recording(device_id, on_first_audio=self._on_first_audio)
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
        audio.stop_recording()
        self._set_status("transcribing", "Transcribing...")
        self.btn_toggle.config(text="Start recording")
        threading.Thread(target=self._transcribe_and_clean, daemon=True).start()

    def _transcribe_and_clean(self) -> None:
        """Transcribe audio and optionally clean with LLM."""
        audio_data = audio.get_audio_buffer()
        if audio_data is None:
            self._set_status("warning", "No audio captured")
            return

        active_context = app_context.get_active_context()
        if active_context and active_context.process_name:
            self._record_recent_process(active_context.process_name, active_context.window_title)
        prompt_context = app_context.format_context_for_prompt(active_context)
        app_prompt = app_prompts.resolve_app_prompt(self.app_prompts, active_context)

        try:
            # Build VAD parameters if VAD is enabled
            vad_params = None
            if self.var_vad_enabled.get():
                vad_params = {
                    "threshold": self.var_vad_threshold.get(),
                    "min_speech_duration_ms": int(self.var_vad_min_speech_ms.get()),
                    "min_silence_duration_ms": int(self.var_vad_min_silence_ms.get()),
                    "speech_pad_ms": int(self.var_vad_speech_pad_ms.get()),
                }

            if not self.asr.is_loaded():
                self._set_status("processing", "Loading model...")
            backend = self.asr.get()
            text = backend.transcribe(
                audio_data,
                hotwords=None,
                beam_size=int(self.var_beam_size.get()),
                vad_filter=self.var_vad_enabled.get(),
                vad_parameters=vad_params,
                compression_ratio_threshold=self.var_compression_ratio_threshold.get(),
                log_prob_threshold=self.var_log_prob_threshold.get(),
                no_speech_threshold=self.var_no_speech_threshold.get(),
                word_timestamps=self.var_word_timestamps.get(),
                temperature=self.var_temperature.get(),
                initial_prompt=self.var_initial_prompt.get().strip() or None,
            )
        except (transcription.TranscriptionError, OSError, RuntimeError, ValueError) as e:
            self._set_status("error", "Transcription failed")
            logger.error(f"Transcription failed: {e}", exc_info=True)
            messagebox.showerror("Transcribe", str(e))
            return

        if not text:
            self._set_status("warning", "No speech detected")
            return

        self._refresh_glossary_cache()
        glossary_enabled = bool(self.var_glossary_enable.get() and self.glossary_manager.rules)

        normalized_text = glossary.apply_glossary(
            text, self.glossary_manager if glossary_enabled else None
        )
        final_text = normalized_text

        # Optionally clean with LLM
        if (
            self.var_llm_enable.get()
            and self.var_llm_endpoint.get().strip()
            and self.var_llm_model.get().strip()
        ):
            self._set_status("processing", "Cleaning with LLM...")
            try:
                cleaned = llm_cleanup.clean_with_llm(
                    raw_text=normalized_text,
                    endpoint=self.var_llm_endpoint.get().strip(),
                    model=self.var_llm_model.get().strip(),
                    api_key=self.var_llm_key.get().strip() or None,
                    prompt=self.prompt_content or DEFAULT_LLM_PROMPT,
                    glossary=self.glossary_manager if glossary_enabled else None,
                    temperature=float(self.var_llm_temp.get()),
                    app_prompt=app_prompt,
                    prompt_context=prompt_context,
                    debug_logging=bool(self.var_llm_debug.get()),
                )
                if cleaned:
                    final_text = cleaned
                    self._set_status("ready", "Cleaned by LLM")
                else:
                    self._set_status("warning", "LLM failed, used raw text")
            except llm_cleanup.LLMCleanupError as e:
                self._set_status("warning", "LLM failed, used raw text")
                logger.warning(f"LLM cleanup failed: {e}")

        if glossary_enabled:
            final_text = glossary.apply_glossary(final_text, self.glossary_manager)

        # Display and copy result
        ts = time.strftime("%H:%M:%S")
        self.txt_out.insert(END, f"[{ts}] {final_text}\n")
        self.txt_out.see(END)

        self._deliver(final_text)

        if getattr(self, "_status_state", "ready") not in {"error", "warning"}:
            self._set_status("ready", "Ready")

    def _deliver(self, text: str) -> None:
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

        if self.var_auto_paste.get():
            self._wait_for_modifiers_up()
            time.sleep(float(self.var_paste_delay.get()))
            # Shift+Insert, not Ctrl+V: it is what the terminal and the commercial
            # dictation apps use.
            if clipboard.send_paste():
                self._set_status("ready", "Pasted into active window")
            else:
                self._set_status("error", "Auto-paste failed")
                logger.error("SendInput refused the paste keystroke")

        if saved is None:
            return
        # Give the target app time to read our text before taking it back.
        time.sleep(float(self.var_restore_delay.get()))
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
        """Track recently seen applications using process and window title."""

        normalized_process = (process_name or "").strip()
        if not normalized_process:
            return

        normalized_window = window_title.strip() if isinstance(window_title, str) else None
        entry = {"process_name": normalized_process, "window_title": normalized_window}

        try:
            self.recent_processes.remove(entry)
        except ValueError:
            for existing in list(self.recent_processes):
                if existing.get("process_name") != normalized_process:
                    continue
                existing_window = existing.get("window_title") or None
                if existing_window == normalized_window:
                    try:
                        self.recent_processes.remove(existing)
                    except ValueError:
                        pass
                    break

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
            app._save_settings()
            app._settings_saved = True
        # Cleanup
        if hasattr(app, "hotkey_manager") and app.hotkey_manager:
            app.hotkey_manager.unregister()
        audio.stop_recording()


if __name__ == "__main__":
    main()
