import argparse
import ctypes
import ctypes.wintypes
import queue
import sys
import threading
import time

import numpy as np
import pyperclip
import sounddevice as sd
from faster_whisper import WhisperModel

# Default config (can be overridden by CLI)
DEFAULT_MODEL = "small"            # try "base.en" for faster starts on CPU
DEFAULT_DEVICE = "cpu"             # "cpu" or "cuda"
DEFAULT_COMPUTE = "int8_float32"   # "int8_float32" good on CPU; try "float16" on GPU
SAMPLE_RATE = 16000
INPUT_CHANNELS = 1
CHUNK_MS = 50

# Windows hotkey constants
user32 = ctypes.windll.user32
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

VK = {c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}

TOGGLE_ID = 1
QUIT_ID = 2

recording = False
audio_q = queue.Queue()
audio_buf = []
buffer_lock = threading.Lock()
stream = None

def parse_hotkey_string(s: str):
    """
    Format example: 'CTRL+WIN+G' or 'CTRL+ALT+H'
    The last token is the key, earlier tokens are modifiers.
    """
    parts = [p.strip().upper() for p in s.split("+") if p.strip()]
    if not parts:
        raise ValueError("Empty hotkey string")
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
        raise ValueError("Only A–Z keys are supported in this minimal example")

    return mods, vk

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

def start_recording():
    global stream, recording, audio_buf
    with buffer_lock:
        audio_buf = []
    stream = sd.InputStream(
        channels=INPUT_CHANNELS,
        samplerate=SAMPLE_RATE,
        dtype="float32",
        callback=audio_cb,
        blocksize=int(SAMPLE_RATE * (CHUNK_MS / 1000.0)),
    )
    stream.start()
    recording = True
    print("[REC] Speak now. Press the toggle hotkey again to stop.")

def stop_recording_and_transcribe(model: WhisperModel):
    global stream, recording
    if stream:
        stream.stop()
        stream.close()
        stream = None
    recording = False
    print("[REC] Stopped. Transcribing...")

    with buffer_lock:
        if not audio_buf:
            print("(no audio captured)")
            return
        audio = np.concatenate(audio_buf).astype(np.float32)

    segments, info = model.transcribe(
        audio, beam_size=5, vad_filter=False, language="en"
    )
    text = "".join(s.text for s in segments).strip()
    if text:
        stamp = time.strftime("%H:%M:%S", time.localtime())
        print(f"[{stamp}] {text}")
        try:
            pyperclip.copy(text)
            print("(copied to clipboard)")
        except Exception as e:
            print("(clipboard copy failed)", e)
    else:
        print("(silence or no text)")

def run(toggle_hotkey: str, quit_hotkey: str, model_size: str,
        device: str, compute_type: str, input_device: str | None):
    if input_device:
        # Accept numeric index or case-insensitive name match
        try:
            sd.default.device = (int(input_device), None)
        except ValueError:
            # name lookup
            devices = sd.query_devices()
            matches = [i for i, d in enumerate(devices) if input_device.lower() in d["name"].lower()]
            if not matches:
                raise RuntimeError(f"Input device not found: {input_device}")
            sd.default.device = (matches[0], None)

    print(f"Loading Whisper model: {model_size} on {device} ({compute_type})")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    print("Ready.")
    print(f"Toggle hotkey: {toggle_hotkey}")
    print(f"Quit hotkey:   {quit_hotkey}")

    t = threading.Thread(target=recorder_loop, daemon=True)
    t.start()

    mods_t, key_t = parse_hotkey_string(toggle_hotkey)
    mods_q, key_q = parse_hotkey_string(quit_hotkey)

    if not user32.RegisterHotKey(None, TOGGLE_ID, mods_t, key_t):
        print("Could not register toggle hotkey. Try a different combo.")
        return
    if not user32.RegisterHotKey(None, QUIT_ID, mods_q, key_q):
        print("Could not register quit hotkey. Try a different combo.")
        user32.UnregisterHotKey(None, TOGGLE_ID)
        return

    try:
        msg = ctypes.wintypes.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0:
                break
            if msg.message == WM_HOTKEY:
                if msg.wParam == TOGGLE_ID:
                    if not recording:
                        start_recording()
                    else:
                        stop_recording_and_transcribe(model)
                elif msg.wParam == QUIT_ID:
                    print("Quitting.")
                    break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        user32.UnregisterHotKey(None, TOGGLE_ID)
        user32.UnregisterHotKey(None, QUIT_ID)
        if recording:
            try:
                stop_recording_and_transcribe(model)
            except Exception:
                pass

def main():
    p = argparse.ArgumentParser(
        prog="dictate",
        description="Local Whisper dictation with a global hotkey on Windows"
    )
    p.add_argument("--toggle", default="CTRL+WIN+G",
                   help="Global hotkey to start/stop recording, for example CTRL+WIN+G")
    p.add_argument("--quit", default="CTRL+WIN+X",
                   help="Global hotkey to quit, for example CTRL+WIN+X")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help="Whisper model size, for example base.en, small, medium")
    p.add_argument("--device", default=DEFAULT_DEVICE, choices=["cpu", "cuda"],
                   help="Inference device")
    p.add_argument("--compute-type", default=DEFAULT_COMPUTE,
                   help="faster-whisper compute_type, for example int8_float16, int8, float16")
    p.add_argument("--input-device", default=None,
                   help="Input device index or substring of device name")
    args = p.parse_args()

    run(
        toggle_hotkey=args.toggle,
        quit_hotkey=args.quit,
        model_size=args.model,
        device=args.device,
        compute_type=args.compute_type,
        input_device=args.input_device,
    )

if __name__ == "__main__":
    main()
