"""Command-line interface for Whisper Dictate."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import time
from typing import Optional

import pyperclip

try:
    import pyautogui

    pyautogui.FAILSAFE = False
except Exception:  # pragma: no cover - optional dependency
    pyautogui = None  # type: ignore[assignment]

from faster_whisper import WhisperModel

from . import environment  # ensure CUDA paths are available
from .audio import AudioRecorder, configure_input_device
from .constants import DEFAULT_COMPUTE, DEFAULT_DEVICE, DEFAULT_LLM_PROMPT, DEFAULT_MODEL
from .hotkeys import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    WM_HOTKEY,
    parse_hotkey_string,
    user32,
)
from .llm import clean_with_llm
from .model_utils import normalize_compute_type


TOGGLE_ID = 1
QUIT_ID = 2

recorder = AudioRecorder()


def stop_recording_and_transcribe(model: WhisperModel, args: argparse.Namespace) -> None:
    audio = recorder.stop()
    if audio is None:
        print("(no audio captured)")
        return

    print("[REC] Stopped. Transcribing...")

    segments, _ = model.transcribe(audio, beam_size=5, vad_filter=False, language="en")
    text = "".join(segment.text for segment in segments).strip()

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
                time.sleep(getattr(args, "paste_delay", 0.15))
                try:
                    pyautogui.hotkey("ctrl", "v")
                    print("(pasted into active window)")
                except Exception as exc:  # pragma: no cover - UI automation issues
                    print(f"(auto-paste failed: {exc})")
    except Exception as exc:  # pragma: no cover - clipboard exceptions
        print("(clipboard copy failed)", exc)


def start_recording() -> None:
    try:
        recorder.start()
    except Exception as exc:
        print(f"Could not start input device: {exc}")
        return

    print("[REC] Speak now. Press the toggle hotkey again to stop.")


def run(args: argparse.Namespace) -> None:
    configure_input_device(args.input_device)

    ct = normalize_compute_type(args.device, args.compute_type)
    print(f"Loading Whisper model: {args.model} on {args.device} ({ct})")
    model = WhisperModel(args.model, device=args.device, compute_type=ct)
    print("Ready.")
    print(f"Toggle hotkey: {args.toggle}")
    print(f"Quit hotkey:   {args.quit}")
    if args.no_llm:
        print("(LLM) disabled")
    elif args.llm_endpoint and args.llm_model:
        print(f"(LLM) enabled: {args.llm_model} @ {args.llm_endpoint}")

    mods_t, key_t = parse_hotkey_string(args.toggle)
    mods_q, key_q = parse_hotkey_string(args.quit)

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
                    if not recorder.is_recording:
                        start_recording()
                    else:
                        stop_recording_and_transcribe(model, args)
                elif msg.wParam == QUIT_ID:
                    print("Quitting.")
                    break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        user32.UnregisterHotKey(None, TOGGLE_ID)
        user32.UnregisterHotKey(None, QUIT_ID)
        if recorder.is_recording:
            try:
                stop_recording_and_transcribe(model, args)
            except Exception:
                pass


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="dictate",
        description="Local Whisper dictation with optional LLM cleanup",
    )
    parser.add_argument("--toggle", default="CTRL+WIN+G", help="Global hotkey to start/stop recording")
    parser.add_argument("--quit", default="CTRL+WIN+X", help="Global hotkey to quit")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Whisper model size (base.en, small, medium, large-v3)")
    parser.add_argument("--device", default=DEFAULT_DEVICE, choices=["cpu", "cuda"], help="Inference device")
    parser.add_argument("--compute-type", default=DEFAULT_COMPUTE, help="CTranslate2 compute_type")
    parser.add_argument("--input-device", default=None, help="Input device index or name substring")

    parser.add_argument("--preset", choices=["cpu-fast", "gpu-fast"])
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM cleanup entirely")
    parser.add_argument("--llm-endpoint", default="http://localhost:1234/v1", help="OpenAI-compatible base URL")
    parser.add_argument("--llm-model", default="openai/gpt-oss-20b", help="Model name served by your endpoint")
    parser.add_argument("--llm-key", default="lmstudiokey", help="API key if your endpoint requires one")
    parser.add_argument(
        "--llm-prompt",
        default=DEFAULT_LLM_PROMPT,
        help="System prompt to control cleanup behavior",
    )
    parser.add_argument("--llm-temp", type=float, default=0.1, help="Temperature for the cleanup request")
    parser.add_argument(
        "--auto-paste",
        action="store_true",
        help="After copying to clipboard, send Ctrl+V to the active window",
    )
    parser.add_argument(
        "--paste-delay",
        type=float,
        default=0.15,
        help="Seconds to wait before sending Ctrl+V when --auto-paste is set",
    )

    args = parser.parse_args(argv)

    if args.preset == "cpu-fast":
        args.device = "cpu"
        args.compute_type = "int8"
        if args.model == DEFAULT_MODEL:
            args.model = "base.en"
    elif args.preset == "gpu-fast":
        args.device = "cuda"
        args.compute_type = "float16"

    run(args)


if __name__ == "__main__":
    main()
