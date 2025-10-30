"""Unified entry point for Whisper Dictate."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import environment  # ensure CUDA paths are configured


def main(argv: Sequence[str] | None = None) -> None:
    raw_args = list(argv) if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="python -m whisper_dictate",
        description="Launch the Whisper Dictate CLI or GUI interface.",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(
        "--mode",
        choices=["cli", "gui"],
        default="cli",
        help="Which interface to launch (defaults to cli)",
    )
    parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        dest="show_help",
        help="Show this help message and exit",
    )

    args, remainder = parser.parse_known_args(raw_args)

    if args.mode == "cli":
        from .cli import main as cli_main

        if args.show_help:
            cli_main(["--help"])
            return

        cli_main(list(remainder))
        return

    # GUI mode ---------------------------------------------------------
    if args.show_help:
        parser.print_help()
        print("\nGUI mode does not accept additional arguments.")
        return

    if remainder:
        parser.error(
            "GUI mode does not accept additional arguments: " + " ".join(remainder)
        )

    from .gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
