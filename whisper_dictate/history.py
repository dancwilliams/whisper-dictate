"""Local record of what was dictated.

One JSON line per dictation, and the audio beside it for a fortnight. The text
is what the next round of glossary mining and the next recognizer benchmark run
on; the audio is what makes a benchmark possible at all, and it is the part
worth expiring.

Privacy: the process name is recorded, never the window title and never a URL.
A window title is the document you had open, the message you were reading, the
site you were on - none of which is needed to improve a recognizer.
"""

from __future__ import annotations

import json
import logging
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("whisper_dictate")

HISTORY_DIR = Path.home() / ".whisper_dictate"
HISTORY_FILE = HISTORY_DIR / "history.jsonl"
AUDIO_DIR = HISTORY_DIR / "audio"

SAMPLE_RATE = 16000
DEFAULT_AUDIO_DAYS = 14


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%S")


def save_audio(
    audio: np.ndarray, stamp: str | None = None, audio_dir: Path | None = None
) -> str | None:
    """Write the clip as 16-bit mono WAV. Returns the file name, or None."""
    audio_dir = audio_dir or AUDIO_DIR
    stamp = stamp or _stamp()
    name = f"{stamp}.wav"
    try:
        audio_dir.mkdir(parents=True, exist_ok=True)
        samples = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
        with wave.open(str(audio_dir / name), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(SAMPLE_RATE)
            fh.writeframes((samples * 32767.0).astype("<i2").tobytes())
        return name
    except (OSError, ValueError) as e:
        logger.warning(f"Could not save dictation audio: {e}")
        return None


def append(entry: dict[str, Any], path: Path | None = None) -> bool:
    """Append one dictation to the history file.

    Raises nothing: losing the record must never cost the dictation.
    """
    path = path or HISTORY_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Could not write dictation history: {e}")
        return False


def record(
    *,
    raw: str,
    cleaned: str | None,
    final: str,
    process_name: str | None,
    asr_backend: str,
    cleanup_backend: str,
    asr_ms: int,
    cleanup_ms: int,
    cold: bool,
    audio: np.ndarray | None = None,
    audio_days: int = DEFAULT_AUDIO_DAYS,
    path: Path | None = None,
    audio_dir: Path | None = None,
) -> dict[str, Any]:
    """Record one dictation, with its audio when audio is being kept."""
    stamp = _stamp()
    audio_file = None
    if audio is not None and audio_days > 0:
        audio_file = save_audio(audio, stamp, audio_dir)

    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        # Process name only. No window title, no URL.
        "app": process_name or "",
        "asr_backend": asr_backend,
        "cleanup_backend": cleanup_backend,
        "raw": raw,
        "cleaned": cleaned,
        "final": final,
        "asr_ms": asr_ms,
        "cleanup_ms": cleanup_ms,
        "cold": cold,
        "audio_file": audio_file,
    }
    append(entry, path)
    return entry


def prune_audio(days: int = DEFAULT_AUDIO_DAYS, audio_dir: Path | None = None) -> int:
    """Delete WAVs older than `days`. The text lines stay, and their audio_file
    simply dangles - a transcript is worth keeping long after the recording.

    Returns:
        How many files were deleted.
    """
    audio_dir = audio_dir or AUDIO_DIR
    if days <= 0 or not audio_dir.is_dir():
        return 0

    cutoff = time.time() - days * 86400
    removed = 0
    for wav in audio_dir.glob("*.wav"):
        try:
            if wav.stat().st_mtime < cutoff:
                wav.unlink()
                removed += 1
        except OSError as e:  # pragma: no cover - a file that vanished
            logger.debug(f"Could not prune {wav.name}: {e}")
    if removed:
        logger.info(f"Pruned {removed} dictation recordings older than {days} days")
    return removed
