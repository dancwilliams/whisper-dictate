"""Configuration and CUDA path setup for whisper-dictate."""

import os
import sys
from pathlib import Path
from typing import Literal, TypedDict

# Audio defaults
SAMPLE_RATE = 16000
INPUT_CHANNELS = 1
CHUNK_MS = 50

# Whisper defaults
DEFAULT_MODEL = "small"  # whisper model: base.en, small, medium, large-v3
DEFAULT_DEVICE: Literal["cpu", "cuda"] = "cuda"  # cpu or cuda
DEFAULT_COMPUTE = "float16"  # good default; GUI will coerce based on device

# LLM defaults
DEFAULT_LLM_ENDPOINT = "http://localhost:1234/v1"  # LM Studio default
DEFAULT_LLM_MODEL = "openai/gpt-oss-20b"
DEFAULT_LLM_KEY = ""  # LM Studio usually does not require a key
DEFAULT_LLM_TEMP = 0.1
DEFAULT_LLM_DEBUG = False

# Auto-startup defaults
DEFAULT_AUTO_LOAD_MODEL = False
DEFAULT_AUTO_REGISTER_HOTKEY = False

# Chosen by scripts/bench_asr.py over 200 of Dan's own dictations; see
# research/asr-benchmark-2026.md. Whisper won on word error rate, cold reload
# and VRAM. Cohere is the fallback when Whisper cannot be loaded.
DEFAULT_ASR_BACKEND = "whisper"

# Minutes idle before the recognizer is unloaded and the GPU handed back.
# 0 means never. At 5 minutes about 35% of dictations start cold, which the
# warm-on-press in the GUI is there to hide.
DEFAULT_IDLE_TTL_MINUTES = 5.0

# Cleanup runs in-process on S1-mini by default; "endpoint" is the
# OpenAI-compatible path, "off" leaves the transcript as the recognizer wrote it.
DEFAULT_CLEANUP_BACKEND = "s1"
CLEANUP_BACKENDS = ("s1", "endpoint", "off")

# Every dictation is recorded locally as text: it is what the next round of
# glossary mining and the next recognizer benchmark run on. The audio expires,
# because it is the part worth expiring. 0 days keeps no audio at all.
DEFAULT_HISTORY_ENABLE = True
DEFAULT_HISTORY_AUDIO_DAYS = 14.0

# Default LLM prompt
DEFAULT_LLM_PROMPT = """
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
- Keep the speaker's wording and intent
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

Remember: You are a text editor, NOT a conversational assistant. Only reformat, never respond. Output only the cleaned text with no commentary
"""


class ModelInfo(TypedDict):
    display_name: str
    disk_mb: int
    vram_gb: int
    ram_gb: float
    speed: str
    description: str


# Model metadata for UI display
# Sizes are approximate and based on faster-whisper/CTranslate2 format
MODEL_INFO: dict[str, ModelInfo] = {
    "tiny.en": {
        "display_name": "Tiny (English)",
        "disk_mb": 75,
        "vram_gb": 1,
        "ram_gb": 0.4,
        "speed": "10x",
        "description": "Fastest, lowest accuracy. Good for quick drafts.",
    },
    "base.en": {
        "display_name": "Base (English)",
        "disk_mb": 145,
        "vram_gb": 1,
        "ram_gb": 0.5,
        "speed": "7x",
        "description": "Fast with decent accuracy. Good default for English.",
    },
    "small": {
        "display_name": "Small",
        "disk_mb": 465,
        "vram_gb": 2,
        "ram_gb": 1,
        "speed": "4x",
        "description": "Balanced speed and accuracy. Supports all languages.",
    },
    "medium": {
        "display_name": "Medium",
        "disk_mb": 1500,
        "vram_gb": 5,
        "ram_gb": 2.5,
        "speed": "2x",
        "description": "High accuracy, slower. Requires decent GPU.",
    },
    "large-v3": {
        "display_name": "Large v3",
        "disk_mb": 3000,
        "vram_gb": 10,
        "ram_gb": 4,
        "speed": "1x",
        "description": "Best accuracy, slowest. Requires powerful GPU.",
    },
    "large-v3-turbo": {
        "display_name": "Large v3 Turbo",
        "disk_mb": 1600,
        "vram_gb": 6,
        "ram_gb": 3,
        "speed": "3x",
        "description": "Near large-v3 accuracy at medium speed.",
    },
}

# Recommended compute types per device
DEVICE_COMPUTE_DEFAULTS: dict[str, str] = {
    "cpu": "int8",
    "cuda": "float16",
}


# add_dll_directory handles are kept alive here; letting one be collected
# unregisters its directory.
_dll_directories: list[object] = []


def set_cuda_paths() -> None:
    """Ensure CUDA DLL folders from the embedded Nvidia wheels are on PATH."""
    venv_base = Path(sys.executable).resolve().parent.parent
    nvidia_base_path = venv_base / "Lib" / "site-packages" / "nvidia"

    cuda_dirs = [
        nvidia_base_path / "cuda_runtime" / "bin",
        nvidia_base_path / "cublas" / "bin",
    ]

    paths_to_add = [str(path) for path in cuda_dirs if path.exists()]
    if not paths_to_add:
        return

    current_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(
        paths_to_add + [current_path] if current_path else paths_to_add
    )

    # CUDA_PATH names one toolkit root, and consumers append to it:
    # llama-cpp-python does add_dll_directory on both CUDA_PATH/bin and
    # CUDA_PATH/lib at import, and raises if either is missing. The pip wheels
    # have no such root - cuda_runtime ships bin and include only - so point
    # CUDA_PATH at a directory only when it really is a toolkit, and otherwise
    # leave it alone. The DLLs are found through the search directories below.
    runtime_root = nvidia_base_path / "cuda_runtime"
    if (runtime_root / "bin").is_dir() and (runtime_root / "lib").is_dir():
        os.environ["CUDA_PATH"] = str(runtime_root)
        os.environ["CUDA_PATH_V12_4"] = str(runtime_root)

    # Under safe DLL search mode Windows resolves a ctypes-loaded library's
    # dependencies from directories registered here, not from PATH. The handles
    # must outlive the call: dropping one removes the directory again.
    for path in paths_to_add:
        try:
            _dll_directories.append(os.add_dll_directory(path))
        except OSError:  # pragma: no cover - a directory that vanished
            pass


def normalize_compute_type(device: str, compute_type: str) -> str:
    """Normalize compute type based on device capabilities."""
    ct = compute_type
    if device == "cpu" and "float16" in ct:
        ct = "int8"
    if device == "cuda" and ct in ("int8", "int8_float32", "float32"):
        ct = "float16"
    return ct


def get_model_display_name(model_id: str, device: str) -> str:
    """Get formatted display name with resource requirements for model dropdown."""
    info = MODEL_INFO.get(model_id)
    if info is None:
        return model_id

    req = f"~{info['vram_gb']} GB VRAM" if device == "cuda" else f"~{info['ram_gb']} GB RAM"
    disk_mb = info["disk_mb"]
    disk_str = f"{disk_mb / 1000:.1f} GB" if disk_mb >= 1000 else f"{disk_mb} MB"
    return f"{info['display_name']} ({disk_str}, {req})"


def get_model_choices(device: str) -> list[tuple[str, str]]:
    """Get list of (model_id, display_name) tuples for dropdown."""
    return [(model_id, get_model_display_name(model_id, device)) for model_id in MODEL_INFO.keys()]
