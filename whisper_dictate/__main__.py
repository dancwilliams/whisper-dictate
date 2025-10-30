"""Unified entry point for Whisper Dictate."""

from __future__ import annotations

import argparse
from typing import Sequence

from . import environment  # ensure CUDA paths are configured


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m whisper_dictate", add_help=True)
    parser.add_argument(
        "--mode",
        choices=["cli", "gui"],
        default="cli",
        help="Which interface to launch",
    )

    args, remainder = parser.parse_known_args(argv)

    if args.mode == "cli":
        from .cli import main as cli_main

        cli_main(list(remainder))
    else:
        if remainder:
            parser.error("GUI mode does not accept additional arguments")
        from .gui import main as gui_main

        gui_main()


if __name__ == "__main__":
    main()
