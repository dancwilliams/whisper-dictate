"""Hotkey utilities shared by the CLI and GUI."""

from __future__ import annotations

import ctypes

user32 = ctypes.windll.user32
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

VK = {c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


def parse_hotkey_string(combo: str) -> tuple[int, int]:
    """Parse strings like ``"CTRL+WIN+G"`` into Windows modifier + key codes."""

    parts = [part.strip().upper() for part in combo.split("+") if part.strip()]
    if not parts:
        raise ValueError("Empty hotkey string")

    key = parts[-1]
    modifiers = parts[:-1]

    mods = 0
    for token in modifiers:
        if token == "CTRL":
            mods |= MOD_CONTROL
        elif token == "ALT":
            mods |= MOD_ALT
        elif token == "SHIFT":
            mods |= MOD_SHIFT
        elif token == "WIN":
            mods |= MOD_WIN
        else:
            raise ValueError(f"Unknown modifier: {token}")

    if len(key) == 1 and key.isalpha():
        vk = VK[key]
    else:
        raise ValueError("Only A–Z keys are supported")

    return mods, vk
