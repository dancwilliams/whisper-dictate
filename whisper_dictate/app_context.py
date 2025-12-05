"""Capture details about the active Windows application for prompt context."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import platform
from dataclasses import dataclass
from pathlib import Path

if platform.system() == "Windows":
    USER32 = ctypes.windll.user32
    KERNEL32 = ctypes.windll.kernel32
else:
    USER32 = None
    KERNEL32 = None


@dataclass(frozen=True)
class ActiveContext:
    """Information about the currently active application."""

    window_title: str | None
    process_name: str | None
    cursor_position: tuple[int, int] | None


def _get_window_title(hwnd: int) -> str | None:
    length = USER32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return None
    buffer = ctypes.create_unicode_buffer(length + 1)
    if USER32.GetWindowTextW(hwnd, buffer, length + 1):
        title = buffer.value.strip()
        return title or None
    return None


def _get_process_name(hwnd: int) -> str | None:
    pid = ctypes.wintypes.DWORD()
    USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process_query_limited_information = 0x1000
    handle = KERNEL32.OpenProcess(process_query_limited_information, False, pid.value)
    if not handle:
        return None

    try:
        size = ctypes.wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if KERNEL32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            path = Path(buffer.value)
            return path.name or None
    finally:
        KERNEL32.CloseHandle(handle)
    return None


def _get_cursor_position() -> tuple[int, int] | None:
    point = ctypes.wintypes.POINT()
    if USER32.GetCursorPos(ctypes.byref(point)):
        return point.x, point.y
    return None


def get_active_context() -> ActiveContext | None:
    """Return information about the active application on Windows."""
    if USER32 is None or KERNEL32 is None:
        return None

    hwnd = USER32.GetForegroundWindow()
    if not hwnd:
        return None

    try:
        return ActiveContext(
            window_title=_get_window_title(hwnd),
            process_name=_get_process_name(hwnd),
            cursor_position=_get_cursor_position(),
        )
    except Exception:
        return None


def format_context_for_prompt(context: ActiveContext | None) -> str | None:
    """Render the context into a short description for prompt conditioning."""
    if context is None:
        return None

    parts: list[str] = []
    if context.process_name and context.window_title:
        parts.append(
            f"Active application: {context.process_name} (window: {context.window_title})."
        )
    elif context.process_name:
        parts.append(f"Active application: {context.process_name}.")
    elif context.window_title:
        parts.append(f"Active window: {context.window_title}.")

    if context.cursor_position:
        x, y = context.cursor_position
        parts.append(f"Cursor position at screen coordinates x={x}, y={y}.")

    return " ".join(parts) if parts else None
