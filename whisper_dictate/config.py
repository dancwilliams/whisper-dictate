"""Configuration and CUDA path setup for whisper-dictate."""

import os
import sys
from pathlib import Path
from typing import Literal

# Audio defaults
SAMPLE_RATE = 16000
INPUT_CHANNELS = 1
CHUNK_MS = 50

# Whisper defaults
DEFAULT_MODEL = "small"  # whisper model: base.en, small, medium, large-v3
DEFAULT_DEVICE: Literal["cpu", "cuda"] = "cuda"  # cpu or cuda
DEFAULT_COMPUTE = "float16"  # good default; GUI will coerce based on device

# LLM defaults
DEFAULT_LLM_ENABLED = True
DEFAULT_LLM_ENDPOINT = "http://localhost:1234/v1"  # LM Studio default
DEFAULT_LLM_MODEL = "openai/gpt-oss-20b"
DEFAULT_LLM_KEY = ""  # LM Studio usually does not require a key
DEFAULT_LLM_TEMP = 0.1

# Default LLM prompt
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
'''


def set_cuda_paths() -> None:
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


def normalize_compute_type(device: str, compute_type: str) -> str:
    """Normalize compute type based on device capabilities."""
    ct = compute_type
    if device == "cpu" and "float16" in ct:
        ct = "int8"
    if device == "cuda" and ct in ("int8", "int8_float32", "float32"):
        ct = "float16"
    return ct

