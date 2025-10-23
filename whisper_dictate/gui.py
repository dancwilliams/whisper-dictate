import threading
import queue
import time
import ctypes
import ctypes.wintypes
import sys
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import sounddevice as sd
import pyperclip
from faster_whisper import WhisperModel

# Defaults shared with the CLI
DEFAULT_MODEL = "small"
DEFAULT_DEVICE = "cpu"          # use "cuda" if your GPU stack is set up
DEFAULT_COMPUTE = "int8_float16"
SAMPLE_RATE = 16000
INPUT_CHANNELS = 1
CHUNK_MS = 50

# Global hotkey (Windows)
user32 = ctypes.windll.user32
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
VK = {c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
TOGGLE_ID = 1
QUIT_ID = 2  # not used in GUI, but reserved

recording = False
audio_q = queue.Queue()
audio_buf = []
buffer_lock = threading.Lock()
stream = None

def parse_hotkey_string(s: str):
    parts = [p.strip().upper() for p in s.split("+") if p.strip()]
    if not parts:
        raise ValueError("Empty hotkey string")
    key = parts[-1]
    mods_tokens = parts[:-1]
    mods = 0
    for m in mods_tokens:
        if m == "CTRL": mods |= MOD_CONTROL
        elif m == "ALT": mods |= MOD_ALT
        elif m == "SHIFT": mods |= MOD_SHIFT
        elif m == "WIN": mods |= MOD_WIN
        else: raise ValueError(f"Unknown modifier: {m}")
    if len(key) == 1 and key.isalpha():
        vk = VK[key]
    else:
        raise ValueError("Only A–Z keys supported")
    return mods, vk

def audio_cb(indata, frames, time_info, status):
    if status:
        print("Audio status:", status, file=sys.stderr)
    data = indata if indata.ndim == 1 else np.mean(indata, axis=1)
    try:
        audio_q.put_nowait(data.copy())
    except queue.Full:
        pass

def recorder_loop():
    while True:
        chunk = audio_q.get()
        with buffer_lock:
            audio_buf.append(chunk)

class DictateGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Whisper Dictate")
        self.geometry("720x520")
        self.minsize(640, 480)

        # Model settings frame
        frm = ttk.LabelFrame(self, text="Settings")
        frm.pack(fill="x", padx=10, pady=8)

        ttk.Label(frm, text="Model").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        self.model_cb = ttk.Combobox(frm, textvariable=self.model_var, state="readonly",
                                     values=["base.en", "small", "medium", "large-v3"])
        self.model_cb.grid(row=0, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(frm, text="Device").grid(row=0, column=2, padx=6, pady=6, sticky="w")
        self.device_var = tk.StringVar(value=DEFAULT_DEVICE)
        self.device_cb = ttk.Combobox(frm, textvariable=self.device_var, state="readonly",
                                      values=["cpu", "cuda"])
        self.device_cb.grid(row=0, column=3, padx=6, pady=6, sticky="w")

        ttk.Label(frm, text="Compute").grid(row=0, column=4, padx=6, pady=6, sticky="w")
        self.compute_var = tk.StringVar(value=DEFAULT_COMPUTE)
        self.compute_cb = ttk.Combobox(frm, textvariable=self.compute_var, state="readonly",
                                       values=["int8", "int8_float32", "int8_float16", "float16", "float32"])
        self.compute_cb.grid(row=0, column=5, padx=6, pady=6, sticky="w")

        ttk.Label(frm, text="Input device").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        self.input_var = tk.StringVar(value="")
        self.input_entry = ttk.Entry(frm, textvariable=self.input_var, width=28)
        self.input_entry.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ttk.Button(frm, text="List devices", command=self.show_devices).grid(row=1, column=2, padx=6, pady=6, sticky="w")

        ttk.Label(frm, text="Toggle hotkey").grid(row=1, column=3, padx=6, pady=6, sticky="w")
        self.hotkey_var = tk.StringVar(value="CTRL+WIN+G")
        self.hotkey_entry = ttk.Entry(frm, textvariable=self.hotkey_var, width=18)
        self.hotkey_entry.grid(row=1, column=4, padx=6, pady=6, sticky="w")

        self.copy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Copy to clipboard", variable=self.copy_var).grid(row=1, column=5, padx=6, pady=6, sticky="w")

        for i in range(6):
            frm.grid_columnconfigure(i, weight=1)

        # Controls
        cfrm = ttk.Frame(self)
        cfrm.pack(fill="x", padx=10, pady=6)
        self.start_btn = ttk.Button(cfrm, text="Load model", command=self.load_model)
        self.start_btn.pack(side="left", padx=6)
        self.reg_btn = ttk.Button(cfrm, text="Register hotkey", command=self.register_hotkey, state="disabled")
        self.reg_btn.pack(side="left", padx=6)
        self.tog_btn = ttk.Button(cfrm, text="Start recording", command=self.toggle_record, state="disabled")
        self.tog_btn.pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(cfrm, textvariable=self.status_var).pack(side="right", padx=6)

        # Transcript
        tfrm = ttk.LabelFrame(self, text="Transcript")
        tfrm.pack(fill="both", expand=True, padx=10, pady=8)
        self.text = tk.Text(tfrm, wrap="word", height=18)
        self.text.pack(fill="both", expand=True)

        # Internal
        self.model = None
        self.hotkey_registered = False

        # Background thread to drain audio queue into buffer
        t = threading.Thread(target=recorder_loop, daemon=True)
        t.start()

        # Windows message pump in a thread to catch WM_HOTKEY
        self.msg_thread = None
        self.after(250, self._heartbeat)

    def _heartbeat(self):
        # Keep UI responsive, update status if needed
        self.after(250, self._heartbeat)

    def show_devices(self):
        try:
            devices = sd.query_devices()
        except Exception as e:
            messagebox.showerror("Audio", f"Could not query devices:\n{e}")
            return
        lines = []
        for idx, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                lines.append(f"{idx}: {d['name']}")
        messagebox.showinfo("Input devices", "\n".join(lines) if lines else "No input devices found.")

    def load_model(self):
        model_name = self.model_var.get().strip()
        device = self.device_var.get().strip()
        compute = self.compute_var.get().strip()

        # Guard compute types by device
        ct = compute
        if device == "cpu" and "float16" in ct:
            ct = "int8"  # safe default for CPU
        if device == "cuda" and ct in ("int8", "int8_float32", "float32"):
            ct = "float16"

        try:
            # Select input device if provided
            inp = self.input_var.get().strip()
            if inp:
                try:
                    sd.default.device = (int(inp), None)
                except ValueError:
                    devs = sd.query_devices()
                    matches = [i for i, d in enumerate(devs) if inp.lower() in d["name"].lower()]
                    if not matches:
                        raise RuntimeError(f"Input device not found: {inp}")
                    sd.default.device = (matches[0], None)

            self.status_var.set(f"Loading model {model_name} on {device} ({ct})")
            self.update_idletasks()
            self.model = WhisperModel(model_name, device=device, compute_type=ct)
            self.status_var.set("Model ready")
            self.start_btn.config(state="disabled")
            self.reg_btn.config(state="normal")
            self.tog_btn.config(state="normal")
        except Exception as e:
            self.status_var.set("Idle")
            messagebox.showerror("Model error", str(e))

    def register_hotkey(self):
        if not self.model:
            messagebox.showwarning("Hotkey", "Load the model first.")
            return
        combo = self.hotkey_var.get().strip()
        try:
            mods_t, key_t = parse_hotkey_string(combo)
        except Exception as e:
            messagebox.showerror("Hotkey", str(e))
            return

        # Unregister if changing
        user32.UnregisterHotKey(None, TOGGLE_ID)

        ok = user32.RegisterHotKey(None, TOGGLE_ID, mods_t, key_t)
        if not ok:
            messagebox.showerror("Hotkey", "Could not register hotkey. Try a different combo.")
            return
        self.hotkey_registered = True
        self.status_var.set(f"Hotkey registered: {combo}")
        if not self.msg_thread:
            self.msg_thread = threading.Thread(target=self.message_pump, daemon=True)
            self.msg_thread.start()

    def message_pump(self):
        msg = ctypes.wintypes.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0:
                break
            if msg.message == WM_HOTKEY and msg.wParam == TOGGLE_ID:
                self.safe_toggle_from_hotkey()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def safe_toggle_from_hotkey(self):
        self.after(0, self.toggle_record)

    def toggle_record(self):
        global recording, stream, audio_buf
        if not self.model:
            return
        if not recording:
            with buffer_lock:
                audio_buf = []
            try:
                stream = sd.InputStream(
                    channels=INPUT_CHANNELS,
                    samplerate=SAMPLE_RATE,
                    dtype="float32",
                    callback=audio_cb,
                    blocksize=int(SAMPLE_RATE * (CHUNK_MS / 1000.0)),
                )
                stream.start()
            except Exception as e:
                messagebox.showerror("Audio", f"Could not start input stream:\n{e}")
                return
            recording = True
            self.status_var.set("Recording... press hotkey or button to stop")
            self.tog_btn.config(text="Stop and transcribe")
        else:
            try:
                if stream:
                    stream.stop()
                    stream.close()
            except Exception:
                pass
            stream = None
            recording = False
            self.status_var.set("Transcribing...")
            self.tog_btn.config(text="Start recording")
            threading.Thread(target=self._transcribe_current, daemon=True).start()

    def _transcribe_current(self):
        global audio_buf
        with buffer_lock:
            if not audio_buf:
                self.status_var.set("No audio captured")
                return
            audio = np.concatenate(audio_buf).astype(np.float32)
        try:
            segs, info = self.model.transcribe(audio, beam_size=5, vad_filter=False, language="en")
            text = "".join(s.text for s in segs).strip()
        except Exception as e:
            self.status_var.set("Idle")
            messagebox.showerror("Transcribe", str(e))
            return
        if text:
            ts = time.strftime("%H:%M:%S")
            self.text.insert("end", f"[{ts}] {text}\n")
            self.text.see("end")
            if self.copy_var.get():
                try:
                    pyperclip.copy(text)
                except Exception:
                    pass
            self.status_var.set("Ready")
        else:
            self.status_var.set("No speech detected")

def main():
    app = DictateGUI()
    app.mainloop()
    # Cleanup hotkey
    user32.UnregisterHotKey(None, TOGGLE_ID)

if __name__ == "__main__":
    main()
