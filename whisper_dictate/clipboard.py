"""Clipboard snapshot, write and restore, and asking the focused app to paste.

Every dictation has to put text on the clipboard to paste it, which destroys
whatever was there - text, HTML, an image, a copied file. So the clipboard is
snapshotted first and put back afterwards.

Only HGLOBAL formats are copied. Windows synthesizes CF_BITMAP and CF_ENHMETAFILE
from the DIB formats that do get copied, and CF_OEMTEXT/CF_TEXT from
CF_UNICODETEXT, so the list below loses nothing in practice.

ponytail: HGLOBAL formats only; CF_BITMAP/ENHMETAFILE are re-synthesized by
Windows from DIB/DIBV5. Copy GDI handles only if a trace shows a real loss.
"""

import ctypes
import ctypes.wintypes
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# Synthesized by Windows from other formats, or GDI handles rather than HGLOBAL
# memory: BITMAP, METAFILEPICT, OEMTEXT, ENHMETAFILE, LOCALE, DSP*.
SKIP = {2, 3, 7, 14, 16, 0x0081, 0x0082, 0x0083, 0x008E}

# Win+V clipboard history would otherwise fill up with dictations.
EXCLUDE_FROM_HISTORY = "ExcludeClipboardContentFromMonitorProcessing"

# 64-bit handles truncate to garbage without these.
user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
user32.OpenClipboard.restype = ctypes.wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = ctypes.wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
user32.EnumClipboardFormats.argtypes = [ctypes.wintypes.UINT]
user32.EnumClipboardFormats.restype = ctypes.wintypes.UINT
user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
user32.GetClipboardData.restype = ctypes.wintypes.HANDLE
user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
user32.SetClipboardData.restype = ctypes.wintypes.HANDLE
user32.RegisterClipboardFormatW.argtypes = [ctypes.wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = ctypes.wintypes.UINT
kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
kernel32.GlobalSize.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalFree.restype = ctypes.wintypes.HGLOBAL


class ClipboardError(Exception):
    """Raised when the clipboard cannot be opened."""


def _open(retries: int = 10, delay: float = 0.02) -> None:
    """Open the clipboard, waiting out whoever else has it.

    Raises:
        ClipboardError: If the clipboard stays locked.
    """
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return
        time.sleep(delay)
    raise ClipboardError("Could not open the clipboard")


def _read_handle(handle: int) -> bytes | None:
    """Copy the bytes behind an HGLOBAL, or None if it cannot be locked."""
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        return None
    try:
        return ctypes.string_at(pointer, kernel32.GlobalSize(handle))
    finally:
        kernel32.GlobalUnlock(handle)


def snapshot() -> list[tuple[int, bytes]]:
    """Copy every HGLOBAL format currently on the clipboard.

    Returns:
        (format_id, bytes) pairs, in the clipboard's own priority order.
    """
    items: list[tuple[int, bytes]] = []
    _open()
    try:
        fmt = user32.EnumClipboardFormats(0)
        while fmt:
            if fmt not in SKIP:
                handle = user32.GetClipboardData(fmt)
                # NULL means delay-rendered: the owner would have to produce it,
                # and asking can hang. Let it go.
                if handle:
                    data = _read_handle(handle)
                    if data is not None:
                        items.append((fmt, data))
            fmt = user32.EnumClipboardFormats(fmt)
    finally:
        user32.CloseClipboard()
    return items


def _put(fmt: int, data: bytes) -> None:
    """Place one format on an already-open, already-emptied clipboard."""
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data) or 1)
    if not handle:
        return
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        return
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    # On success the clipboard owns the handle; only free it if it was refused.
    if not user32.SetClipboardData(fmt, handle):
        kernel32.GlobalFree(handle)


def restore(items: list[tuple[int, bytes]]) -> None:
    """Put a snapshot back. An empty snapshot restores an empty clipboard."""
    _open()
    try:
        user32.EmptyClipboard()
        for fmt, data in items:
            _put(fmt, data)
    finally:
        user32.CloseClipboard()


VK_SHIFT, VK_INSERT = 0x10, 0x2D
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    """Never filled in; it is what gives INPUT its real size (40 bytes on x64).

    A union sized to KEYBDINPUT alone makes SendInput return 0 and do nothing.
    """

    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    ]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.wintypes.DWORD), ("u", _U)]


user32.SendInput.argtypes = [ctypes.wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
user32.SendInput.restype = ctypes.wintypes.UINT


def _key(vk: int, up: bool, extended: bool) -> _INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    return _INPUT(
        type=INPUT_KEYBOARD,
        ki=_KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None),
    )


def send_paste() -> bool:
    """Press Shift+Insert in the focused window.

    Insert must carry KEYEVENTF_EXTENDEDKEY. Without it Windows reads the
    keystroke as the *numpad* Insert, and with NumLock on it then strips the
    Shift around the keypress - the app receives a bare Insert, which toggles
    overwrite mode instead of pasting. This is what pyautogui's hotkey() did,
    and why nothing ever arrived.

    Returns:
        True if Windows accepted all four events.
    """
    events = [
        _key(VK_SHIFT, up=False, extended=False),
        _key(VK_INSERT, up=False, extended=True),
        _key(VK_INSERT, up=True, extended=True),
        _key(VK_SHIFT, up=True, extended=False),
    ]
    array = (_INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
    return int(sent) == len(events)


def set_text(text: str) -> None:
    """Replace the clipboard with one string, kept out of Win+V history."""
    _open()
    try:
        user32.EmptyClipboard()
        _put(CF_UNICODETEXT, text.encode("utf-16-le") + b"\x00\x00")
        marker = user32.RegisterClipboardFormatW(EXCLUDE_FROM_HISTORY)
        if marker:
            _put(marker, b"\x00")
    finally:
        user32.CloseClipboard()
