"""Streamlined GUI for whisper-dictate with optional LLM cleanup."""

import threading
import time
from pathlib import Path
from typing import Optional

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except ImportError:
    pyautogui = None

import pyperclip
import sounddevice as sd
from faster_whisper import WhisperModel
from tkinter import Tk, StringVar, BooleanVar, DoubleVar, Text, END, Menu, Toplevel
from tkinter import messagebox
from tkinter import ttk

from whisper_dictate import (
    app_context,
    audio,
    config,
    glossary,
    hotkeys,
    llm_cleanup,
    prompt,
    settings_store,
    transcription,
)
from whisper_dictate.config import (
    DEFAULT_COMPUTE,
    DEFAULT_DEVICE,
    DEFAULT_LLM_ENABLED,
    DEFAULT_LLM_ENDPOINT,
    DEFAULT_LLM_KEY,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROMPT,
    DEFAULT_LLM_TEMP,
    DEFAULT_LLM_DEBUG,
    DEFAULT_MODEL,
    set_cuda_paths,
)
from whisper_dictate.gui_components import PromptDialog, StatusIndicator
from whisper_dictate.logging_config import setup_logging

# Set up CUDA paths before importing other modules
set_cuda_paths()

# Set up logging
logger = setup_logging()

# Start audio recorder thread
threading.Thread(target=audio.recorder_loop, daemon=True).start()


class App(Tk):
    """Main application window."""
    
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
        self.glossary_content = ""

        # Model and hotkey manager
        self.model: Optional[WhisperModel] = None
        self.hotkey_manager: Optional[hotkeys.HotkeyManager] = None
        self.llm_models: list[str] = []
        self.cmb_llm_model: Optional[ttk.Combobox] = None
        self.btn_llm_refresh: Optional[ttk.Button] = None

        # Secondary windows
        self._speech_window: Optional[Toplevel] = None
        self._automation_window: Optional[Toplevel] = None
        self._llm_window: Optional[Toplevel] = None

        self._build_menus()
        self._build_ui()
        self._setup_status_indicator()

    def _build_menus(self) -> None:
        """Build application menu bar."""
        menubar = Menu(self)
        edit_menu = Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Prompt...", command=self._open_prompt_dialog)
        edit_menu.add_command(label="Glossary...", command=self._open_glossary_dialog)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        settings_menu = Menu(menubar, tearoff=False)
        settings_menu.add_command(label="Speech recognition...", command=self._open_speech_settings)
        settings_menu.add_command(label="LLM cleanup...", command=self._open_llm_settings)
        settings_menu.add_command(label="Automation...", command=self._open_automation_settings)
        menubar.add_cascade(label="Settings", menu=settings_menu)

        self.config(menu=menubar)

    def _build_ui(self) -> None:
        """Build the main UI."""
        # Variables
        self.var_model = StringVar(value=DEFAULT_MODEL)
        self.var_device = StringVar(value=DEFAULT_DEVICE)
        self.var_compute = StringVar(value=DEFAULT_COMPUTE)
        self.var_input = StringVar(value="")
        self.var_hotkey = StringVar(value="CTRL+WIN+G")
        self.var_auto_paste = BooleanVar(value=True)
        self.var_paste_delay = DoubleVar(value=0.15)

        self.var_llm_enable = BooleanVar(value=DEFAULT_LLM_ENABLED)
        self.var_llm_endpoint = StringVar(value=DEFAULT_LLM_ENDPOINT)
        self.var_llm_model = StringVar(value=DEFAULT_LLM_MODEL)
        self.var_llm_key = StringVar(value=DEFAULT_LLM_KEY)
        self.var_llm_temp = DoubleVar(value=DEFAULT_LLM_TEMP)
        self.var_llm_debug = BooleanVar(value=DEFAULT_LLM_DEBUG)
        self.var_glossary_enable = BooleanVar(value=True)
        self.var_glossary_path = StringVar(value=str(glossary.GLOSSARY_FILE))

        self._load_settings()
        self._refresh_glossary_cache()

        # Controls
        ctrl = ttk.Frame(self, padding=(12, 0, 12, 12))
        ctrl.pack(fill="x")
        self.btn_load = ttk.Button(ctrl, text="Load model", command=self._load_model)
        self.btn_load.grid(row=0, column=0, padx=(0, 8))
        self.btn_hotkey = ttk.Button(ctrl, text="Register hotkey", command=self._register_hotkey, state="disabled")
        self.btn_hotkey.grid(row=0, column=1, padx=(0, 8))
        self.btn_toggle = ttk.Button(ctrl, text="Start recording", command=self._toggle_record, state="disabled")
        self.btn_toggle.grid(row=0, column=2, padx=(0, 8))
        self.lbl_status = ttk.Label(ctrl, text="Idle")
        self.lbl_status.grid(row=0, column=3, sticky="w")

        # Transcript box
        out = ttk.Frame(self, padding=8)
        out.pack(fill="both", expand=True)
        ttk.Label(out, text="Transcript").pack(anchor="w")
        self.txt_out = Text(out, wrap="word")
        self.txt_out.pack(fill="both", expand=True)

    def _open_window(self, window_attr: str, title: str, builder) -> None:
        """Open or focus a configuration window."""
        existing = getattr(self, window_attr)
        if existing and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_set()
            return

        window = Toplevel(self)
        window.title(title)
        window.resizable(False, False)
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

    def _open_speech_settings(self) -> None:
        """Open speech recognition settings window."""

        def build(window: Toplevel) -> None:
            frame = ttk.Frame(window, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(1, weight=1)

            self._add_labeled_widget(frame, "Model", 0, ttk.Combobox(
                frame, textvariable=self.var_model,
                values=["base.en", "small", "medium", "large-v3"], width=18
            ))
            self._add_labeled_widget(frame, "Device", 1, ttk.Combobox(
                frame, textvariable=self.var_device, values=["cpu", "cuda"], width=10
            ))
            self._add_labeled_widget(frame, "Compute", 2, ttk.Combobox(
                frame, textvariable=self.var_compute,
                values=["int8", "int8_float32", "float32", "float16", "int8_float16"], width=14
            ))

            input_row = ttk.Frame(frame)
            input_row.grid(row=3, column=1, sticky="we", pady=4)
            input_row.columnconfigure(0, weight=1)
            ttk.Label(frame, text="Input device").grid(row=3, column=0, sticky="w", pady=4)
            ttk.Entry(input_row, textvariable=self.var_input).grid(row=0, column=0, sticky="we")
            ttk.Button(input_row, text="List…", command=self._show_inputs).grid(row=0, column=1, padx=(8, 0))

        self._open_window("_speech_window", "Speech recognition", build)

    def _open_automation_settings(self) -> None:
        """Open automation settings window."""

        def build(window: Toplevel) -> None:
            frame = ttk.Frame(window, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(0, weight=1)

            ttk.Label(frame, text="Toggle hotkey").grid(row=0, column=0, sticky="w")
            ttk.Entry(frame, textvariable=self.var_hotkey, width=16).grid(row=1, column=0, sticky="we", pady=(0, 8))
            ttk.Checkbutton(
                frame, text="Auto-paste into active window", variable=self.var_auto_paste
            ).grid(row=2, column=0, sticky="w")

            paste_row = ttk.Frame(frame)
            paste_row.grid(row=3, column=0, sticky="we", pady=(4, 0))
            ttk.Label(paste_row, text="Paste delay (s)").pack(side="left")
            ttk.Spinbox(
                paste_row, from_=0.0, to=1.0, increment=0.05,
                textvariable=self.var_paste_delay, width=6
            ).pack(side="left", padx=(8, 0))

        self._open_window("_automation_window", "Automation", build)

    def _open_llm_settings(self) -> None:
        """Open LLM cleanup settings window."""

        def build(window: Toplevel) -> None:
            frame = ttk.Frame(window, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(1, weight=1)

            ttk.Checkbutton(
                frame, text="Use LLM cleanup (OpenAI compatible)", variable=self.var_llm_enable
            ).grid(row=0, column=0, sticky="w", columnspan=2)
            self._add_labeled_widget(frame, "Endpoint", 1, ttk.Entry(frame, textvariable=self.var_llm_endpoint))
            ttk.Label(frame, text="Model").grid(row=2, column=0, sticky="w", pady=4)
            model_row = ttk.Frame(frame)
            model_row.grid(row=2, column=1, sticky="we", pady=4, padx=(12, 0))
            model_row.columnconfigure(0, weight=1)
            self.cmb_llm_model = ttk.Combobox(
                model_row, textvariable=self.var_llm_model, values=self.llm_models
            )
            self.cmb_llm_model.grid(row=0, column=0, sticky="we")
            self.btn_llm_refresh = ttk.Button(model_row, text="Refresh", command=self._refresh_llm_models)
            self.btn_llm_refresh.grid(row=0, column=1, padx=(8, 0))
            self._add_labeled_widget(
                frame, "API key (optional)", 3,
                ttk.Entry(frame, textvariable=self.var_llm_key, show="•")
            )
            self._add_labeled_widget(
                frame, "Temperature", 4,
                ttk.Spinbox(frame, from_=0.0, to=1.5, increment=0.1, textvariable=self.var_llm_temp, width=6)
            )
            ttk.Checkbutton(
                frame, text="Log full LLM prompts for debugging", variable=self.var_llm_debug
            ).grid(row=5, column=0, columnspan=2, sticky="w")
            ttk.Checkbutton(
                frame, text="Use glossary before prompt", variable=self.var_glossary_enable
            ).grid(row=6, column=0, columnspan=2, sticky="w")
            self._add_labeled_widget(
                frame, "Glossary file", 7, ttk.Entry(frame, textvariable=self.var_glossary_path)
            )
            ttk.Label(
                frame, text=f"Cleanup prompt saved to {prompt.PROMPT_FILE} (Edit → Prompt…)",
                wraplength=440, justify="left"
            ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
            ttk.Label(
                frame,
                text=f"Glossary saved to {self.var_glossary_path.get()} (Edit → Glossary…)",
                wraplength=440,
                justify="left",
            ).grid(row=9, column=0, columnspan=2, sticky="w")

        self._open_window("_llm_window", "LLM cleanup", build)

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
                def on_error() -> None:
                    if self.btn_llm_refresh:
                        self.btn_llm_refresh.config(state="normal")
                    self._set_status("warning", "LLM model fetch failed")
                    messagebox.showerror("LLM models", str(e))

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

    def _add_labeled_widget(self, parent: ttk.Frame, label: str, row: int, widget: ttk.Widget) -> None:
        """Helper to add a labeled widget."""
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4 if row > 0 else (0, 4))
        widget.grid(row=row, column=1, sticky="we", pady=4 if row > 0 else (0, 4), padx=(12, 0))

    def _setup_status_indicator(self) -> None:
        """Set up the floating status indicator."""
        self.indicator = StatusIndicator(self)
        self._set_status("idle", "Idle")

    def _set_status(self, state: str, message: str) -> None:
        """Update status in both label and indicator."""
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self._set_status, state, message)
            return
        self.lbl_status.config(text=message)
        if hasattr(self, "indicator"):
            self.indicator.update(state, message)
        logger.info(f"Status: {state} - {message}")

    def _get_glossary_path(self) -> Path:
        """Return the configured glossary path, expanding user directories."""
        path_str = self.var_glossary_path.get().strip()
        return Path(path_str).expanduser() if path_str else glossary.GLOSSARY_FILE

    def _refresh_glossary_cache(self) -> None:
        """Load glossary content from disk according to the configured path."""
        self.glossary_content = glossary.load_saved_glossary(
            path=self._get_glossary_path()
        )

    def _load_settings(self) -> None:
        """Load saved settings from disk into Tk variables."""
        saved = settings_store.load_settings()
        if not saved:
            return

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
        set_if_present("device", self.var_device, str)
        set_if_present("compute", self.var_compute, str)
        set_if_present("input", self.var_input, str)
        set_if_present("hotkey", self.var_hotkey, str)
        set_if_present("auto_paste", self.var_auto_paste, bool)
        set_if_present("paste_delay", self.var_paste_delay, float)
        set_if_present("llm_enable", self.var_llm_enable, bool)
        set_if_present("llm_endpoint", self.var_llm_endpoint, str)
        set_if_present("llm_model", self.var_llm_model, str)
        set_if_present("llm_key", self.var_llm_key, str)
        set_if_present("llm_temp", self.var_llm_temp, float)
        set_if_present("llm_debug", self.var_llm_debug, bool)
        set_if_present("glossary_enable", self.var_glossary_enable, bool)
        set_if_present("glossary_path", self.var_glossary_path, str)

    def _save_settings(self) -> None:
        """Persist current settings to disk."""
        settings = {
            "model": self.var_model.get().strip(),
            "device": self.var_device.get().strip(),
            "compute": config.normalize_compute_type(
                self.var_device.get().strip(), self.var_compute.get().strip()
            ),
            "input": self.var_input.get().strip(),
            "hotkey": self.var_hotkey.get().strip(),
            "auto_paste": bool(self.var_auto_paste.get()),
            "paste_delay": float(self.var_paste_delay.get()),
            "llm_enable": bool(self.var_llm_enable.get()),
            "llm_endpoint": self.var_llm_endpoint.get().strip(),
            "llm_model": self.var_llm_model.get().strip(),
            "llm_key": self.var_llm_key.get(),
            "llm_temp": float(self.var_llm_temp.get()),
            "llm_debug": bool(self.var_llm_debug.get()),
            "glossary_enable": bool(self.var_glossary_enable.get()),
            "glossary_path": self.var_glossary_path.get().strip(),
        }
        if not settings_store.save_settings(settings):
            logger.warning("Could not save settings to disk")

    def _on_close(self) -> None:
        """Handle window close event by saving settings then destroying."""
        try:
            self._save_settings()
        except Exception as e:
            logger.error(f"Failed to save settings on close: {e}", exc_info=True)
        finally:
            self._settings_saved = True
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
        path = self._get_glossary_path()
        current = glossary.load_saved_glossary(path=path)
        dialog = PromptDialog(self, current)
        dialog.title("Edit Glossary")
        self.wait_window(dialog)
        if dialog.result is not None:
            if glossary.write_saved_glossary(dialog.result, path=path):
                self.glossary_content = dialog.result
                self.var_glossary_path.set(str(path))
                self._set_status("ready", "Glossary updated")
            else:
                messagebox.showerror("Glossary", f"Could not save glossary to {path}")

    def _show_inputs(self) -> None:
        """Show available audio input devices."""
        try:
            devices = sd.query_devices()
        except Exception as e:
            messagebox.showerror("Audio", f"Could not query devices:\n{e}")
            return
        names = [f"{i}: {d.get('name', '')}" for i, d in enumerate(devices) if d.get("max_input_channels", 0) > 0]
        if not names:
            messagebox.showinfo("Input devices", "No input devices found.")
        else:
            messagebox.showinfo("Input devices", "\n".join(names))

    def _load_model(self) -> None:
        """Load the Whisper model."""
        model_name = self.var_model.get().strip()
        device = self.var_device.get().strip()
        compute = self.var_compute.get().strip()

        # Set input device if provided
        inp = self.var_input.get().strip()
        device_id = None
        if inp:
            try:
                device_id = int(inp)
            except ValueError:
                devs = sd.query_devices()
                matches = [i for i, d in enumerate(devs) if inp.lower() in d["name"].lower()]
                if not matches:
                    messagebox.showerror("Input", f"Input device not found: {inp}")
                    return
                device_id = matches[0]
            sd.default.device = (device_id, None)

        try:
            self._set_status("processing", f"Loading {model_name} on {device} ({compute})")
            self.update_idletasks()
            self.model = transcription.load_model(model_name, device, compute)
            self._set_status("ready", "Model ready")
            self.btn_load.config(state="disabled")
            self.btn_hotkey.config(state="normal")
            self.btn_toggle.config(state="normal")
            logger.info(f"Model loaded: {model_name} on {device} ({compute})")
        except Exception as e:
            self._set_status("error", "Model load failed")
            logger.error(f"Model load failed: {e}", exc_info=True)
            messagebox.showerror("Model error", str(e))

    def _register_hotkey(self) -> None:
        """Register the global hotkey."""
        if not self.model:
            self._set_status("warning", "Load the model first")
            messagebox.showwarning("Hotkey", "Load the model first.")
            return
        
        combo = self.var_hotkey.get().strip()
        try:
            # Wrap callback to ensure it runs on main thread
            def hotkey_callback():
                self.after(0, self._toggle_record)
            
            self.hotkey_manager = hotkeys.HotkeyManager(hotkey_callback)
            self.hotkey_manager.register(combo)
            self._set_status("ready", f"Hotkey set: {combo}")
            logger.info(f"Hotkey registered: {combo}")
        except hotkeys.HotkeyError as e:
            self._set_status("error", "Invalid hotkey")
            logger.error(f"Hotkey registration failed: {e}")
            messagebox.showerror("Hotkey", str(e))

    def _toggle_record(self) -> None:
        """Toggle recording on/off."""
        if not self.model:
            return
        
        if not audio.is_recording():
            # Start recording
            inp = self.var_input.get().strip()
            device_id = None
            if inp:
                try:
                    device_id = int(inp)
                except ValueError:
                    devs = sd.query_devices()
                    matches = [i for i, d in enumerate(devs) if inp.lower() in d["name"].lower()]
                    if matches:
                        device_id = matches[0]
            
            try:
                audio.start_recording(device_id)
            except Exception as e:
                self._set_status("error", "Audio input failed")
                logger.error(f"Audio start failed: {e}", exc_info=True)
                messagebox.showerror("Audio", f"Could not start input:\n{e}")
                return
            
            self._set_status("listening", "Recording... press hotkey to stop")
            self.btn_toggle.config(text="Stop and transcribe")
        else:
            # Stop recording and transcribe
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

        prompt_context = app_context.format_context_for_prompt(
            app_context.get_active_context()
        )

        try:
            text = transcription.transcribe_audio(self.model, audio_data)
        except transcription.TranscriptionError as e:
            self._set_status("error", "Transcription failed")
            logger.error(f"Transcription failed: {e}", exc_info=True)
            messagebox.showerror("Transcribe", str(e))
            return

        if not text:
            self._set_status("warning", "No speech detected")
            return

        final_text = text

        # Optionally clean with LLM
        if (self.var_llm_enable.get() and
            self.var_llm_endpoint.get().strip() and
            self.var_llm_model.get().strip()):
            self._refresh_glossary_cache()
            self._set_status("processing", "Cleaning with LLM...")
            try:
                cleaned = llm_cleanup.clean_with_llm(
                    raw_text=text,
                    endpoint=self.var_llm_endpoint.get().strip(),
                    model=self.var_llm_model.get().strip(),
                    api_key=self.var_llm_key.get().strip() or None,
                    prompt=self.prompt_content or DEFAULT_LLM_PROMPT,
                    glossary=self.glossary_content if self.var_glossary_enable.get() else None,
                    temperature=float(self.var_llm_temp.get()),
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

        # Display and copy result
        ts = time.strftime("%H:%M:%S")
        self.txt_out.insert(END, f"[{ts}] {final_text}\n")
        self.txt_out.see(END)
        
        try:
            pyperclip.copy(final_text)
            if self.var_auto_paste.get():
                if pyautogui is None:
                    self._set_status("warning", "pyautogui not installed; cannot auto-paste")
                else:
                    time.sleep(float(self.var_paste_delay.get()))
                    try:
                        pyautogui.hotkey("ctrl", "v")
                        self._set_status("ready", "Pasted into active window")
                    except Exception as e:
                        self._set_status("error", f"Auto-paste failed: {e}")
                        logger.error(f"Auto-paste failed: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Clipboard copy failed: {e}", exc_info=True)
        
        if getattr(self, "_status_state", "ready") not in {"error", "warning"}:
            self._set_status("ready", "Ready")


def main() -> None:
    """Main entry point for the GUI application."""
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
