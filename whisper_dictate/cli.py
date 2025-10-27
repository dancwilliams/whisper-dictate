import os, importlib
import sys
from pathlib import Path

def set_cuda_paths():
    venv_base = Path(sys.executable).parent.parent
    nvidia_base_path = venv_base / 'Lib' / 'site-packages' / 'nvidia'
    cuda_path = nvidia_base_path / 'cuda_runtime' / 'bin'
    cublas_path = nvidia_base_path / 'cublas' / 'bin'
    cudnn_path = nvidia_base_path / 'cudnn' / 'bin'
    paths_to_add = [str(cuda_path), str(cublas_path), str(cudnn_path)]
    env_vars = ['CUDA_PATH', 'CUDA_PATH_V12_4', 'PATH']
    
    for env_var in env_vars:
        current_value = os.environ.get(env_var, '')
        new_value = os.pathsep.join(paths_to_add + [current_value] if current_value else paths_to_add)
        os.environ[env_var] = new_value

set_cuda_paths()

import argparse
import ctypes
import ctypes.wintypes
import queue

import threading
import time
from typing import Optional

try:
    import pyautogui
    pyautogui.FAILSAFE = False  # optional: prevents abort if mouse hits screen corner
except Exception:
    pyautogui = None

import numpy as np
import pyperclip
import sounddevice as sd

from faster_whisper import WhisperModel

# NEW: OpenAI-compatible client
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # we will check at runtime

# Defaults
DEFAULT_MODEL = "small"
DEFAULT_DEVICE = "cpu"
DEFAULT_COMPUTE = "int8"  # changed to a CPU-safe default
SAMPLE_RATE = 16000
INPUT_CHANNELS = 1
CHUNK_MS = 50

DEFAULT_LLM_PROMPT = '''
You are a specialized text reformatting assistant. Your ONLY job is to clean up and reformat the user's text input.

CRITICAL INSTRUCTION: Your response must ONLY contain the cleaned text. Nothing else.

WHAT YOU DO:
- Fix grammar, spelling, and punctuation
- Remove speech artifacts ("um", "uh", false starts, repetitions)
- Correct homophones and standardize numbers/dates
- Break large (greater than 20 words) content into paragraphs, aim for 2-5 sentences per paragraph
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
        raise ValueError("Only A–Z keys are supported")

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

def normalize_compute_type(device: str, compute_type: str) -> str:
    ct = compute_type
    if device == "cpu" and "float16" in ct:
        ct = "int8"
    if device == "cuda" and ct in ("int8", "int8_float32", "float32"):
        ct = "float16"
    return ct

# NEW: LLM cleaner
def clean_with_llm(
    raw_text: str,
    endpoint: str,
    model: str,
    api_key: Optional[str],
    prompt: str,
    temperature: float,
    timeout: float = 15.0,
) -> Optional[str]:
    """
    Send raw_text to an OpenAI-compatible chat endpoint for cleanup.
    Returns cleaned text or None on failure.
    """
    if OpenAI is None:
        print("(LLM) openai client not available. Install with: uv add openai")
        return None

    try:
        client = OpenAI(base_url=endpoint, api_key=api_key or "sk-no-key-needed")
        # LM Studio is compatible with /v1/chat/completions
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": raw_text},
            ],
            temperature=temperature,
            timeout=timeout,
        )
        choice = resp.choices[0].message.content.strip() if resp.choices else ""
        return choice or None
    except Exception as e:
        print(f"(LLM) error: {e}")
        return None

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

def stop_recording_and_transcribe(model: WhisperModel, args):
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

    segments, info = model.transcribe(audio, beam_size=5, vad_filter=False, language="en")
    text = "".join(s.text for s in segments).strip()

    if not text:
        print("(silence or no text)")
        return

    cleaned = text
    if args.no_llm is False and args.llm_endpoint and args.llm_model:
        print("(LLM) Cleaning with", args.llm_model, "via", args.llm_endpoint)
        cleaned_try = clean_with_llm(
            text,
            endpoint=args.llm_endpoint,
            model=args.llm_model,
            api_key=args.llm_key,
            prompt=args.llm_prompt,
            temperature=args.llm_temp,
        )
        if cleaned_try:
            cleaned = cleaned_try
        else:
            print("(LLM) Falling back to raw transcription")

    stamp = time.strftime("%H:%M:%S", time.localtime())
    print(f"[{stamp}] {cleaned}")
    try:
        pyperclip.copy(cleaned)
        print("(copied to clipboard)")
        if args.auto_paste:
            if pyautogui is None:
                print("(auto-paste requested, but pyautogui not installed)")
            else:
                # tiny delay so the key-up from your hotkey doesn’t clash with Ctrl+V
                time.sleep(getattr(args, "paste_delay", 0.15))
                try:
                    pyautogui.hotkey("ctrl", "v")
                    print("(pasted into active window)")
                except Exception as e:
                    print(f"(auto-paste failed: {e})")
    except Exception as e:
        print("(clipboard copy failed)", e)

def run(toggle_hotkey, quit_hotkey, model_size, device, compute_type,
        input_device, no_llm, llm_endpoint, llm_model,
        llm_key, llm_prompt, llm_temp, auto_paste, paste_delay):

    if input_device:
        try:
            sd.default.device = (int(input_device), None)
        except ValueError:
            devices = sd.query_devices()
            matches = [i for i, d in enumerate(devices) if input_device.lower() in d["name"].lower()]
            if not matches:
                raise RuntimeError(f"Input device not found: {input_device}")
            sd.default.device = (matches[0], None)

    ct = normalize_compute_type(device, compute_type)
    print(f"Loading Whisper model: {model_size} on {device} ({ct})")
    model = WhisperModel(model_size, device=device, compute_type=ct)
    print("Ready.")
    print(f"Toggle hotkey: {toggle_hotkey}")
    print(f"Quit hotkey:   {quit_hotkey}")
    if no_llm:
        print("(LLM) disabled")
    elif llm_endpoint and llm_model:
        print(f"(LLM) enabled: {llm_model} @ {llm_endpoint}")

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
                        stop_recording_and_transcribe(model, args=arg_holder)  # see below
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
                stop_recording_and_transcribe(model, args=arg_holder)
            except Exception:
                pass

def main():
    p = argparse.ArgumentParser(
        prog="dictate",
        description="Local Whisper dictation with optional LLM cleanup"
    )
    p.add_argument("--toggle", default="CTRL+WIN+G", help="Global hotkey to start/stop recording")
    p.add_argument("--quit", default="CTRL+WIN+X", help="Global hotkey to quit")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Whisper model size (base.en, small, medium, large-v3)")
    p.add_argument("--device", default=DEFAULT_DEVICE, choices=["cpu", "cuda"], help="Inference device")
    p.add_argument("--compute-type", default=DEFAULT_COMPUTE, help="CTranslate2 compute_type")
    p.add_argument("--input-device", default=None, help="Input device index or name substring")

    # Presets
    p.add_argument("--preset", choices=["cpu-fast", "gpu-fast"])
    # LLM cleanup options
    p.add_argument("--no-llm", action="store_true", help="Disable LLM cleanup entirely")
    p.add_argument("--llm-endpoint", default="http://localhost:1234/v1", help="OpenAI-compatible base URL, for example http://localhost:1234/v1")
    p.add_argument("--llm-model", default="openai/gpt-oss-20b", help="Model name served by your endpoint")
    p.add_argument("--llm-key", default="lmstudiokey", help="API key if your endpoint requires one")
    p.add_argument("--llm-prompt", default=DEFAULT_LLM_PROMPT,
                   help="System prompt to control cleanup behavior")
    p.add_argument("--llm-temp", type=float, default=0.1, help="Temperature for the cleanup request")
    p.add_argument("--auto-paste", action="store_true",
               help="After copying to clipboard, send Ctrl+V to the active window")
    p.add_argument("--paste-delay", type=float, default=0.15,
               help="Seconds to wait before sending Ctrl+V when --auto-paste is set")

    args = p.parse_args()

    # presets
    if args.preset == "cpu-fast":
        args.device = "cpu"
        args.compute_type = "int8"
        if args.model == DEFAULT_MODEL:
            args.model = "base.en"
    elif args.preset == "gpu-fast":
        args.device = "cuda"
        args.compute_type = "float16"

    # hold args globally for the hotkey handler
    global arg_holder
    arg_holder = args

    run(
        toggle_hotkey=args.toggle,
        quit_hotkey=args.quit,
        model_size=args.model,
        device=args.device,
        compute_type=args.compute_type,
        input_device=args.input_device,
        no_llm=args.no_llm,
        llm_endpoint=args.llm_endpoint,
        llm_model=args.llm_model,
        llm_key=args.llm_key,
        llm_prompt=args.llm_prompt,
        llm_temp=args.llm_temp,
        auto_paste=args.auto_paste,
        paste_delay=args.paste_delay,
    )

if __name__ == "__main__":
    main()
