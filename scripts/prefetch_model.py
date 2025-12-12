#!/usr/bin/env python3
"""Download and cache Whisper models ahead of packaging builds."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="small",
        help="Model size or path understood by faster-whisper (default: small)",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["cpu", "cuda"],
        help="Device used when instantiating the model to trigger the download.",
    )
    parser.add_argument(
        "--compute-type",
        dest="compute_type",
        default="int8_float32",
        help="Compute type hint passed to WhisperModel (default: int8_float32).",
    )
    parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        type=Path,
        help="Optional directory where the model cache should be stored.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - runtime safeguard
        print("faster-whisper must be installed before downloading models", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 1

    download_options = None
    if args.cache_dir:
        download_options = {"download_dir": str(args.cache_dir)}
        args.cache_dir.mkdir(parents=True, exist_ok=True)

    compute_type = args.compute_type
    if args.device == "cuda" and compute_type == "int8_float32":
        compute_type = "float16"
        print("Adjusting compute type to float16 for CUDA prefetches.")

    print(
        f"Prefetching model '{args.model}' (device={args.device}, compute_type={compute_type})..."
    )
    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=compute_type,
        download_options=download_options,
    )

    # Access model attributes to ensure the weights are materialised on disk.
    _ = getattr(model, "model_size", None)
    model_dir = getattr(model, "model_dir", None)
    if model_dir:
        print("Model ready at:", model_dir)
    else:
        print("Model downloaded (model_dir attribute unavailable on this version).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
