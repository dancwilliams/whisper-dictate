#!/usr/bin/env python3
"""Fine-tune Whisper on your own corrections.

Phase 2 of the correction-loop plan ships only the paths and the hold-out rule,
which bench_asr.py imports so the benchmark and the trainer never disagree on
which clips are held back. Training itself arrives in phase 3.

    uv run python scripts/finetune_whisper.py --selftest

Stdlib only at import time; everything ML is loaded inside main().
"""

from __future__ import annotations

import argparse
import sys
import zlib
from pathlib import Path

HOME = Path.home() / ".whisper_dictate"
CORRECTIONS = HOME / "corrections.jsonl"
TRAINING = HOME / "training"
MODELS = HOME / "models"


def is_holdout(name: str) -> bool:
    """One clip in five is never trained on. Keyed on the file name so both
    scripts agree and the split does not move as the bank grows."""
    return zlib.crc32(name.encode()) % 5 == 0


def selftest() -> None:
    # bench_asr imports this module for the split; it must not drag torch in.
    assert "torch" not in sys.modules
    assert is_holdout("20261014T051535.wav") == is_holdout("20261014T051535.wav")
    names = [f"2026{i:08d}T120000.wav" for i in range(1000)]
    share = sum(map(is_holdout, names)) / len(names)
    assert 0.15 <= share <= 0.25, share
    print("ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    parser.error("training arrives in phase 3; only --selftest runs today")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
