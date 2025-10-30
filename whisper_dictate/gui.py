"""GUI front-end for Whisper Dictate."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
import time
from typing import Optional

import pyperclip
import sounddevice as sd
from tkinter import BooleanVar, DoubleVar, END, StringVar, Text, Tk, Toplevel, messagebox, ttk

try:
    import pyautogui

    pyautogui.FAILSAFE = False
except Exception:  # pragma: no cover - optional dependency
    pyautogui = None  # type: ignore[assignment]

from faster_whisper import WhisperModel

from . import environment  # ensure CUDA paths are configured
from .audio import AudioRecorder, configure_input_device
from .constants import DEFAULT_COMPUTE, DEFAULT_DEVICE, DEFAULT_LLM_PROMPT, DEFAULT_MODEL
from .hotkeys import WM_HOTKEY, parse_hotkey_string, user32
from .llm import clean_with_llm
from .model_utils import normalize_compute_type


DEFAULT_LLM_ENABLED = False
DEFAULT_LLM_ENDPOINT = "http://localhost:1234/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-20b"
DEFAULT_LLM_KEY = ""
DEFAULT_LLM_TEMP = 0.1

TOGGLE_ID = 1

recorder = AudioRecorder()


class App(Tk):
    def __init__(self):
        super().__init__()
        self.title("Whisper Dictate + LLM")
        self.geometry("980x680")

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        self.var_model = StringVar(value=DEFAULT_MODEL)
        self.var_device = StringVar(value=DEFAULT_DEVICE)
        self.var_compute = StringVar(value=DEFAULT_COMPUTE)
        self.var_input = StringVar(value="")
        self.var_hotkey = StringVar(value="CTRL+WIN+G")
        self.var_auto_paste = BooleanVar(value=False)
        self.var_paste_delay = DoubleVar(value=0.15)

        ttk.Label(top, text="Whisper model").grid(row=0, column=0, sticky="w")
        self.cb_model = ttk.Combobox(
            top,
            textvariable=self.var_model,
            width=18,
            values=["base.en", "small", "medium", "large-v3"],
        )
        self.cb_model.grid(row=1, column=0, padx=(0, 12), sticky="we")

        ttk.Label(top, text="Device").grid(row=0, column=1, sticky="w")
        self.cb_device = ttk.Combobox(top, textvariable=self.var_device, width=10, values=["cpu", "cuda"])
        self.cb_device.grid(row=1, column=1, padx=(0, 12), sticky="we")

        ttk.Label(top, text="Compute").grid(row=0, column=2, sticky="w")
        self.cb_compute = ttk.Combobox(
            top,
            textvariable=self.var_compute,
            width=14,
            values=["int8", "int8_float32", "float32", "float16", "int8_float16"],
        )
        self.cb_compute.grid(row=1, column=2, padx=(0, 12), sticky="we")

        ttk.Label(top, text="Input device (index or name)").grid(row=0, column=3, sticky="w")
        ttk.Entry(top, textvariable=self.var_input, width=28).grid(row=1, column=3, padx=(0, 12), sticky="we")
        ttk.Button(top, text="List inputs", command=self.show_inputs).grid(row=1, column=4, padx=(0, 12))

        ttk.Label(top, text="Toggle hotkey").grid(row=0, column=5, sticky="w")
        ttk.Entry(top, textvariable=self.var_hotkey, width=16).grid(row=1, column=5, padx=(0, 12), sticky="we")

        sep = ttk.Separator(self, orient="horizontal")
        sep.pack(fill="x", pady=(8, 8))

        llm = ttk.Frame(self, padding=8)
        llm.pack(fill="x")

        self.var_llm_enable: BooleanVar = BooleanVar(value=DEFAULT_LLM_ENABLED)
        ttk.Checkbutton(llm, text="Use LLM cleanup (OpenAI compatible)", variable=self.var_llm_enable).grid(row=0, column=0, sticky="w")

        self.var_llm_endpoint = StringVar(value=DEFAULT_LLM_ENDPOINT)
        self.var_llm_model = StringVar(value=DEFAULT_LLM_MODEL)
        self.var_llm_key = StringVar(value=DEFAULT_LLM_KEY)
        self.var_llm_temp: DoubleVar = DoubleVar(value=DEFAULT_LLM_TEMP)

        ttk.Checkbutton(llm, text="Auto-paste into active window", variable=self.var_auto_paste).grid(row=5, column=0, sticky="w", pady=(8, 0))

        ttk.Label(llm, text="Paste delay (s)").grid(row=5, column=1, sticky="e", pady=(8, 0))
        ttk.Spinbox(llm, from_=0.0, to=1.0, increment=0.05, textvariable=self.var_paste_delay, width=6).grid(row=5, column=2, sticky="w", pady=(8, 0))

        ttk.Label(llm, text="Endpoint").grid(row=1, column=0, sticky="w")
        ttk.Entry(llm, textvariable=self.var_llm_endpoint, width=40).grid(row=2, column=0, padx=(0, 12), sticky="we")

        ttk.Label(llm, text="Model").grid(row=1, column=1, sticky="w")
        ttk.Entry(llm, textvariable=self.var_llm_model, width=28).grid(row=2, column=1, padx=(0, 12), sticky="we")

        ttk.Label(llm, text="API key (optional)").grid(row=1, column=2, sticky="w")
        ttk.Entry(llm, textvariable=self.var_llm_key, width=28, show="•").grid(row=2, column=2, padx=(0, 12), sticky="we")

        ttk.Label(llm, text="Temperature").grid(row=1, column=3, sticky="w")
        ttk.Spinbox(llm, from_=0.0, to=1.5, increment=0.1, textvariable=self.var_llm_temp, width=6).grid(row=2, column=3, padx=(0, 12))

        ttk.Label(llm, text="Cleanup prompt").grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.txt_prompt: Text = Text(llm, height=4, wrap="word")
        self.txt_prompt.grid(row=4, column=0, columnspan=4, sticky="we")
        self.txt_prompt.insert(END, DEFAULT_LLM_PROMPT)

        for c in range(6):
            top.grid_columnconfigure(c, weight=1)
        for c in range(4):
            llm.grid_columnconfigure(c, weight=1)

        ctrl = ttk.Frame(self, padding=8)
        ctrl.pack(fill="x")
        self.btn_load = ttk.Button(ctrl, text="Load model", command=self.load_model)
        self.btn_load.grid(row=0, column=0, padx=(0, 8))
        self.btn_hotkey = ttk.Button(ctrl, text="Register hotkey", command=self.register_hotkey, state="disabled")
        self.btn_hotkey.grid(row=0, column=1, padx=(0, 8))
        self.btn_toggle = ttk.Button(ctrl, text="Start recording", command=self.toggle_record, state="disabled")
        self.btn_toggle.grid(row=0, column=2, padx=(0, 8))
        self.lbl_status = ttk.Label(ctrl, text="Idle")
        self.lbl_status.grid(row=0, column=3, sticky="w")

        out = ttk.Frame(self, padding=8)
        out.pack(fill="both", expand=True)
        ttk.Label(out, text="Transcript").pack(anchor="w")
        self.txt_out: Text = Text(out, wrap="word")
        self.txt_out.pack(fill="both", expand=True)

        self.msg_thread: Optional[threading.Thread] = None
        self._hotkey_mods: Optional[int] = None
        self._hotkey_vk: Optional[int] = None
        self._msg_tid: Optional[int] = None

    def show_inputs(self):
        try:
            devices = sd.query_devices()
        except Exception as exc:
            messagebox.showerror("Audio", f"Could not query devices:\n{exc}")
            return
        names = []
        for idx, device in enumerate(devices):
            if device.get("max_input_channels", 0) > 0:
                names.append(f"{idx}: {device.get('name', '')}")
        if not names:
            messagebox.showinfo("Input devices", "No input devices found.")
        else:
            messagebox.showinfo("Input devices", "\n".join(names))

    def load_model(self):
        model_name = self.var_model.get().strip()
        device = self.var_device.get().strip()
        compute = normalize_compute_type(device, self.var_compute.get().strip())

        inp = self.var_input.get().strip()
        if inp:
            try:
                configure_input_device(inp)
            except RuntimeError as exc:
                messagebox.showerror("Input", str(exc))
                return

        try:
            self.lbl_status.config(text=f"Loading {model_name} on {device} ({compute})")
            self.update_idletasks()
            self.model = WhisperModel(model_name, device=device, compute_type=compute)
            self.lbl_status.config(text="Model ready")
            self.btn_load.config(state="disabled")
            self.btn_hotkey.config(state="normal")
            self.btn_toggle.config(state="normal")
        except Exception as exc:
            self.lbl_status.config(text="Idle")
            messagebox.showerror("Model error", str(exc))

    def register_hotkey(self):
        if not hasattr(self, "model"):
            messagebox.showwarning("Hotkey", "Load the model first.")
            return
        combo = self.var_hotkey.get().strip()
        try:
            mods, key = parse_hotkey_string(combo)
        except Exception as exc:
            messagebox.showerror("Hotkey", str(exc))
            return

        self._hotkey_mods = mods
        self._hotkey_vk = key

        if self.msg_thread and self.msg_thread.is_alive():
            try:
                ctypes.windll.user32.PostThreadMessageW(self._msg_tid, 0x0012, 0, 0)
            except Exception:
                pass
            self.msg_thread.join(timeout=0.5)

        self.msg_thread = threading.Thread(target=self.message_pump, daemon=True)
        self.msg_thread.start()

        self.lbl_status.config(text=f"Hotkey set: {combo}")

    def message_pump(self):
        self._msg_tid = ctypes.windll.kernel32.GetCurrentThreadId()

        if not user32.RegisterHotKey(None, TOGGLE_ID, self._hotkey_mods, self._hotkey_vk):
            self.after(0, lambda: messagebox.showerror("Hotkey", "Could not register hotkey. Try a different combo."))
            return

        try:
            msg = ctypes.wintypes.MSG()
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == TOGGLE_ID:
                    self.after(0, self.toggle_record)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, TOGGLE_ID)

    def toggle_record(self):
        if not hasattr(self, "model"):
            return
        if not recorder.is_recording:
            try:
                recorder.start()
            except Exception as exc:
                messagebox.showerror("Audio", f"Could not start input:\n{exc}")
                return
            self.lbl_status.config(text="Recording... press hotkey to stop")
            self.btn_toggle.config(text="Stop and transcribe")
        else:
            audio = recorder.stop()
            self.btn_toggle.config(text="Start recording")
            if audio is None:
                self.lbl_status.config(text="No audio captured")
                return
            self.lbl_status.config(text="Transcribing...")
            threading.Thread(target=self.transcribe_and_maybe_clean, args=(audio,), daemon=True).start()

    def transcribe_and_maybe_clean(self, audio):
        try:
            segments, _ = self.model.transcribe(audio, beam_size=5, vad_filter=False, language="en")
            text = "".join(segment.text for segment in segments).strip()
        except Exception as exc:
            self.lbl_status.config(text="Idle")
            messagebox.showerror("Transcribe", str(exc))
            return

        if not text:
            self.lbl_status.config(text="No speech detected")
            return

        final_text = text
        if self.var_llm_enable.get() and self.var_llm_endpoint.get().strip() and self.var_llm_model.get().strip():
            self.lbl_status.config(text="Cleaning with LLM...")
            prompt = self.txt_prompt.get("1.0", END).strip() or DEFAULT_LLM_PROMPT
            cleaned = clean_with_llm(
                raw_text=text,
                endpoint=self.var_llm_endpoint.get().strip(),
                model=self.var_llm_model.get().strip(),
                api_key=self.var_llm_key.get().strip() or None,
                prompt=prompt,
                temperature=float(self.var_llm_temp.get()),
            )
            if cleaned:
                final_text = cleaned
                self.lbl_status.config(text="Cleaned by LLM")
            else:
                self.lbl_status.config(text="LLM failed, used raw text")

        ts = time.strftime("%H:%M:%S")
        self.txt_out.insert(END, f"[{ts}] {final_text}\n")
        self.txt_out.see(END)
        try:
            pyperclip.copy(final_text)
            if self.var_auto_paste.get():
                if pyautogui is None:
                    self.lbl_status.config(text="pyautogui not installed; cannot auto-paste")
                else:
                    time.sleep(float(self.var_paste_delay.get()))
                    try:
                        pyautogui.hotkey("ctrl", "v")
                        self.lbl_status.config(text="Pasted into active window")
                    except Exception as exc:
                        self.lbl_status.config(text=f"Auto-paste failed: {exc}")
        except Exception:
            pass
        self.lbl_status.config(text="Ready")


def main():
    app = App()
    app.mainloop()
    user32.UnregisterHotKey(None, TOGGLE_ID)


if __name__ == "__main__":
    main()
