# whisper_dictate/gui.py
# GUI dictation with optional LLM cleanup (OpenAI-compatible endpoint, e.g., LM Studio)

import os, importlib
import sys
from pathlib import Path

def set_cuda_paths():
    """Ensure CUDA DLL folders from the embedded Nvidia wheels are on PATH."""

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        nvidia_base_path = Path(sys._MEIPASS) / "nvidia"
    else:
        venv_base = Path(sys.executable).resolve().parent.parent
        nvidia_base_path = venv_base / "Lib" / "site-packages" / "nvidia"

    cuda_dirs = [
        nvidia_base_path / "cuda_runtime" / "bin",
        nvidia_base_path / "cublas" / "bin",
        nvidia_base_path / "cudnn" / "bin",
    ]

    paths_to_add = [str(path) for path in cuda_dirs if path.exists()]
    if not paths_to_add:
        return

    env_vars = ["CUDA_PATH", "CUDA_PATH_V12_4", "PATH"]

    for env_var in env_vars:
        current_value = os.environ.get(env_var, "")
        new_value = os.pathsep.join(paths_to_add + [current_value] if current_value else paths_to_add)
        os.environ[env_var] = new_value

set_cuda_paths()

import ctypes
import ctypes.wintypes
import threading
import time
import queue
from typing import Optional

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except Exception:
    pyautogui = None

import numpy as np
import sounddevice as sd
import pyperclip
from tkinter import Tk, Toplevel, StringVar, BooleanVar, DoubleVar, Text, END
from tkinter import messagebox
from tkinter import ttk

from faster_whisper import WhisperModel

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # will handle gracefully if missing

# ----- Defaults you can tweak -----
SAMPLE_RATE = 16000
INPUT_CHANNELS = 1
CHUNK_MS = 50

DEFAULT_MODEL = "small"          # whisper model: base.en, small, medium, large-v3
DEFAULT_DEVICE = "cuda"           # cpu or cuda
DEFAULT_COMPUTE = "float16"         # good CPU default; GUI will coerce to float16 on cuda

DEFAULT_LLM_ENABLED = True
DEFAULT_LLM_ENDPOINT = "http://localhost:1234/v1"  # LM Studio default
DEFAULT_LLM_MODEL = "openai/gpt-oss-20b"
DEFAULT_LLM_KEY = ""             # LM Studio usually does not require a key
DEFAULT_LLM_PROMPT = '''
You are a specialized text reformatting assistant. Your ONLY job is to clean up and reformat the user's text input.

CRITICAL INSTRUCTION: Your response must ONLY contain the cleaned text. Nothing else.

WHAT YOU DO:
- Fix grammar, spelling, and punctuation
- Remove speech artifacts ("um", "uh", false starts, repetitions)
- Correct homophones and standardize numbers/dates
- Break large (greater than 20 words)  content into paragraphs, aim for 2-5 sentences per paragraph
- Maintain the original tone and intent
- Improve readability by splitting the text into paragraphs or sentences and questions onto new lines
- Replace common emoji descriptions with the emoji itself smiley face -> 🙂
- Keep the speaker’s wording and intent
- Present lists as lists if you able to

WHAT YOU NEVER DO:
- Answer questions (only reformat the question itself)
- Add new content not in the original message
- Provide responses or solutions to requests
- Add greetings, sign-offs, or explanations
- Remove curse words or harsh language.
- Remove names
- Change facts
- Rephrase unless the phrase is hard to read
- Use em dash

WRONG BEHAVIOR - DO NOT DO THIS:
User: "what's the weather like"
Wrong: I don't have access to current weather data, but you can check...
Correct: What's the weather like?

Remember: You are a text editor, NOT a conversational assistant. Only reformat, never respond. Output only the cleaned text with no commentary
'''
DEFAULT_LLM_TEMP = 0.1
# ----------------------------------

# Windows global hotkey plumbing
user32 = ctypes.windll.user32
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
TOGGLE_ID = 1

VK = {c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}

def parse_hotkey_string(s: str):
    """
    Format: 'CTRL+WIN+G' or 'CTRL+ALT+H'
    Only single A..Z keys supported for simplicity.
    """
    parts = [p.strip().upper() for p in s.split("+") if p.strip()]
    if not parts:
        raise ValueError("Empty hotkey")
    key = parts[-1]
    mods_tokens = parts[:-1]
    mods = 0
    for m in mods_tokens:
        if m == "CTRL":
            mods |= MOD_CONTROL
        elif m == "ALT":
            mods |= MOD_ALT
        elif m == "SHIFT":
            mods |= MOD_SHIFT
        elif m == "WIN":
            mods |= MOD_WIN
        else:
            raise ValueError(f"Unknown modifier: {m}")
    if len(key) == 1 and key.isalpha():
        vk = VK[key]
    else:
        raise ValueError("Only single A..Z keys supported")
    return mods, vk

# audio buffers and flags
recording = False
audio_q: "queue.Queue[np.ndarray]" = queue.Queue()
audio_buf = []
buffer_lock = threading.Lock()
stream: Optional[sd.InputStream] = None

def audio_cb(indata, frames, time_info, status):
    if status:
        print("Audio status:", status, file=sys.stderr)
    data = indata if indata.ndim == 1 else np.mean(indata, axis=1)
    audio_q.put_nowait(data.copy())

def recorder_loop():
    while True:
        chunk = audio_q.get()
        with buffer_lock:
            audio_buf.append(chunk)

def normalize_compute_type(device: str, compute_type: str) -> str:
    ct = compute_type
    if device == "cpu" and "float16" in ct:
        ct = "int8"
    if device == "cuda" and ct in ("int8", "int8_float32", "float32"):
        ct = "float16"
    return ct

def clean_with_llm(raw_text: str,
                   endpoint: str,
                   model: str,
                   api_key: Optional[str],
                   prompt: str,
                   temperature: float,
                   timeout: float = 15.0) -> Optional[str]:
    """Send raw_text to an OpenAI-compatible LLM for cleanup. Return cleaned text or None on failure."""
    if not raw_text.strip():
        return ""
    if OpenAI is None:
        print("(LLM) openai client not installed. Run: uv add openai")
        return None
    try:
        client = OpenAI(base_url=endpoint, api_key=api_key or "sk-no-key")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": raw_text},
            ],
            temperature=temperature,
            timeout=timeout,
        )
        if resp.choices:
            text = resp.choices[0].message.content or ""
            return text.strip()
        return None
    except Exception as e:
        print(f"(LLM) error: {e}")
        return None

class App(Tk):
    def __init__(self):
        super().__init__()
        self.title("Whisper Dictate + LLM")
        self.geometry("980x680")

        # ----- Top config frame -----
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        # Whisper config
        self.var_model = StringVar(value=DEFAULT_MODEL)
        self.var_device = StringVar(value=DEFAULT_DEVICE)
        self.var_compute = StringVar(value=DEFAULT_COMPUTE)
        self.var_input = StringVar(value="")
        self.var_hotkey = StringVar(value="CTRL+WIN+G")
        self.var_auto_paste = BooleanVar(value=True)
        self.var_paste_delay = DoubleVar(value=0.15)
        
        ttk.Label(top, text="Whisper model").grid(row=0, column=0, sticky="w")
        self.cb_model = ttk.Combobox(top, textvariable=self.var_model, width=18,
                                     values=["base.en", "small", "medium", "large-v3"])
        self.cb_model.grid(row=1, column=0, padx=(0, 12), sticky="we")

        ttk.Label(top, text="Device").grid(row=0, column=1, sticky="w")
        self.cb_device = ttk.Combobox(top, textvariable=self.var_device, width=10,
                                      values=["cpu", "cuda"])
        self.cb_device.grid(row=1, column=1, padx=(0, 12), sticky="we")

        ttk.Label(top, text="Compute").grid(row=0, column=2, sticky="w")
        self.cb_compute = ttk.Combobox(top, textvariable=self.var_compute, width=14,
                                       values=["int8", "int8_float32", "float32", "float16", "int8_float16"])
        self.cb_compute.grid(row=1, column=2, padx=(0, 12), sticky="we")

        ttk.Label(top, text="Input device (index or name)").grid(row=0, column=3, sticky="w")
        ttk.Entry(top, textvariable=self.var_input, width=28).grid(row=1, column=3, padx=(0, 12), sticky="we")
        ttk.Button(top, text="List inputs", command=self.show_inputs).grid(row=1, column=4, padx=(0, 12))

        ttk.Label(top, text="Toggle hotkey").grid(row=0, column=5, sticky="w")
        ttk.Entry(top, textvariable=self.var_hotkey, width=16).grid(row=1, column=5, padx=(0, 12), sticky="we")

        # LLM config
        sep = ttk.Separator(self, orient="horizontal")
        sep.pack(fill="x", pady=(8, 8))

        llm = ttk.Frame(self, padding=8)
        llm.pack(fill="x")

        self.var_llm_enable: BooleanVar = BooleanVar(value=DEFAULT_LLM_ENABLED)
        ttk.CheckBox = ttk.Checkbutton  # alias for brevity
        ttk.CheckBox(llm, text="Use LLM cleanup (OpenAI compatible)", variable=self.var_llm_enable).grid(row=0, column=0, sticky="w")

        self.var_llm_endpoint = StringVar(value=DEFAULT_LLM_ENDPOINT)
        self.var_llm_model = StringVar(value=DEFAULT_LLM_MODEL)
        self.var_llm_key = StringVar(value=DEFAULT_LLM_KEY)
        self.var_llm_temp: DoubleVar = DoubleVar(value=DEFAULT_LLM_TEMP)

        ttk.Checkbutton(llm, text="Auto-paste into active window", variable=self.var_auto_paste)\
            .grid(row=5, column=0, sticky="w", pady=(8, 0))

        ttk.Label(llm, text="Paste delay (s)").grid(row=5, column=1, sticky="e", pady=(8, 0))
        ttk.Spinbox(llm, from_=0.0, to=1.0, increment=0.05, textvariable=self.var_paste_delay, width=6)\
            .grid(row=5, column=2, sticky="w", pady=(8, 0))

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
            llli = c
            llm.grid_columnconfigure(llli, weight=1)

        # Controls
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

        # Transcript box
        out = ttk.Frame(self, padding=8)
        out.pack(fill="both", expand=True)
        ttk.Label(out, text="Transcript").pack(anchor="w")
        self.txt_out: Text = Text(out, wrap="word")
        self.txt_out.pack(fill="both", expand=True)

        # Background audio collector
        threading.Thread(target=recorder_only_once, args=(), kwargs={}, daemon=True).start()

        # Hotkey message pump thread (created after registration)
        self.msg_thread = None
        self._hotkey_mods = None
        self._hotkey_vk = None
        self._msg_tid = None

    def show_inputs(self):
        try:
            devices = sd.query_devices()
        except Exception as e:
            messagebox.showerror("Audio", f"Could not query devices:\n{e}")
            return
        names = []
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                names.append(f"{i}: {d.get('name','')}")
        if not names:
            messagebox.showinfo("Input devices", "No input devices found.")
        else:
            txt = "\n".join(names)
            Toplevel(self)  # optional to present in a new window
            messagebox.showinfo("Input devices", txt)

    def load_model(self):
        model_name = self.var_model.get().strip()
        device = self.var_device.get().strip()
        compute = normalize_compute_type(device, self.var_compute.get().strip())

        # choose input device if provided
        inp = self.var_input.get().strip()
        if inp:
            try:
                sd.default.device = (int(inp), None)
            except ValueError:
                devs = sd.query_devices()
                matches = [i for i, d in enumerate(devs) if inp.lower() in d["name"].lower()]
                if not matches:
                    messagebox.showerror("Input", f"Input device not found: {inp}")
                    return
                sd.default.device = (matches[0], None)

        try:
            self.lbl_status.config(text=f"Loading {model_name} on {device} ({compute})")
            self.update_idletasks()
            self.model = WhisperModel(model_name, device=device, compute_type=compute)
            self.lbl_status.config(text="Model ready")
            self.btn_load.config(state="disabled")
            self.btn_hotkey.config(state="normal")
            self.btn_toggle.config(state="normal")
        except Exception as e:
            self.lbl_status.config(text="Idle")
            messagebox.showerror("Model error", str(e))

    def register_hotkey(self):
        if not hasattr(self, "model"):
            messagebox.showwarning("Hotkey", "Load the model first.")
            return
        combo = self.var_hotkey.get().strip()
        try:
            mods, key = parse_hotkey_string(combo)
        except Exception as e:
            messagebox.showerror("Hotkey", str(e))
            return
    
        # Store for the worker thread
        self._hotkey_mods = mods
        self._hotkey_vk = key
    
        # If a previous message thread is running, stop it
        if self.msg_thread and self.msg_thread.is_alive():
            try:
                # Post WM_QUIT to that thread to end GetMessageW
                ctypes.windll.user32.PostThreadMessageW(self._msg_tid, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
            self.msg_thread.join(timeout=0.5)
    
        # Start a fresh message pump that registers the hotkey in the same thread
        self.msg_thread = threading.Thread(target=self.message_pump, daemon=True)
        self.msg_thread.start()
    
        self.lbl_status.config(text=f"Hotkey set: {combo}")


    def message_pump(self):
        # Save this thread's id so we can post WM_QUIT when re-registering
        self._msg_tid = ctypes.windll.kernel32.GetCurrentThreadId()
    
        # Register the hotkey in THIS thread so WM_HOTKEY arrives here
        if not user32.RegisterHotKey(None, TOGGLE_ID, self._hotkey_mods, self._hotkey_vk):
            # Report back to the UI thread
            self.after(0, lambda: messagebox.showerror("Hotkey", "Could not register hotkey. Try a different combo."))
            return
    
        try:
            msg = ctypes.wintypes.MSG()
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0:  # WM_QUIT received
                    break
                if msg.message == WM_HOTKEY and msg.wParam == TOGGLE_ID:
                    # Call GUI method on the Tk thread
                    self.after(0, self.toggle_record)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, TOGGLE_ID)
    

    def toggle_record(self):
        global recording, stream, audio_buf
        if not hasattr(self, "model"):
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
                messagebox.showerror("Audio", f"Could not start input:\n{e}")
                return
            recording = True
            self.lbl_status.config(text="Recording... press hotkey to stop")
            self.btn_toggle.config(text="Stop and transcribe")
        else:
            try:
                if stream:
                    stream.stop()
                    stream.close()
            except Exception:
                pass
            stream = None
            recording = False
            self.lbl_status.config(text="Transcribing...")
            self.btn_toggle.config(text="Start recording")
            threading.Thread(target=self.transcribe_and_maybe_clean, daemon=True).start()

    def transcribe_and_maybe_clean(self):
        global audio_buf
        with buffer_lock:
            if not audio_buf:
                self.lbl_status.config(text="No audio captured")
                return
            audio = np.concatenate(audio_buf).astype(np.float32)
        try:
            segs, info = self.model.transcribe(audio, beam_size=5, vad_filter=False, language="en")
            text = "".join(s.text for s in segs).strip()
        except Exception as e:
            self.lbl_status.config(text="Idle")
            messagebox.showerror("Transcribe", str(e))
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
                api_key=(self.var_llm_key.get().strip() or None),
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
                    # brief pause to let the hotkey key-up finish in the target app
                    time.sleep(float(self.var_paste_delay.get()))
                    try:
                        pyautogui.hotkey("ctrl", "v")
                        self.lbl_status.config(text="Pasted into active window")
                    except Exception as e:
                        self.lbl_status.config(text=f"Auto-paste failed: {e}")
        except Exception:
            pass
        self.lbl_status.config(text="Ready")

def recorder_only_once():
    t = threading.Thread(target=recorder_loop, daemon=True)
    t.start()

def main():
    app = App()
    app.mainloop()
    user32.UnregisterHotKey(None, TOGGLE_ID)

if __name__ == "__main__":
    main()
