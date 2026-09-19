"""Windows global hotkey management via a low-level keyboard hook.

The Win32 hotkey-registration API cannot express a modifier-only chord and only
ever fires on press, so hold-to-talk is impossible with it. A WH_KEYBOARD_LL hook
sees every key transition instead, which buys both.

The hook sees every keystroke on the system. Nothing here logs, stores or
transmits a key code, and the hook procedure itself does the least possible work:
Windows silently unhooks a low-level hook whose procedure exceeds
LowLevelHooksTimeout (~300 ms).
"""

import ctypes
import ctypes.wintypes
import threading
from collections.abc import Callable
from typing import Any

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10
HC_ACTION = 0

# Left/right variants collapse to one modifier: "CTRL" is satisfied by either Ctrl key.
MODIFIER_VKS = {
    "CTRL": {0xA2, 0xA3},
    "SHIFT": {0xA0, 0xA1},
    "ALT": {0xA4, 0xA5},
    "WIN": {0x5B, 0x5C},
}
NAMED_VKS = {"SPACE": 0x20}
ALL_MODIFIERS: set[int] = set().union(*MODIFIER_VKS.values())


class HotkeyError(Exception):
    """Raised when hotkey registration fails."""


def parse_chord(s: str) -> list[set[int]]:
    """Parse a chord string into one set of acceptable virtual key codes per part.

    'CTRL+WIN' -> [{0xA2, 0xA3}, {0x5B, 0x5C}]; 'CTRL+SPACE' appends {0x20};
    'CTRL+WIN+G' appends {ord('G')}.

    Raises:
        ValueError: If the chord string is empty or names an unknown key.
    """
    parts = [p.strip().upper() for p in s.split("+") if p.strip()]
    if not parts:
        raise ValueError("Empty hotkey")

    groups: list[set[int]] = []
    for part in parts:
        if part in MODIFIER_VKS:
            groups.append(set(MODIFIER_VKS[part]))
        elif part in NAMED_VKS:
            groups.append({NAMED_VKS[part]})
        elif len(part) == 1 and part.isalnum():
            groups.append({ord(part)})
        else:
            raise ValueError(f"Unknown key: {part}")
    return groups


class Chord:
    """Pure key-state tracker. feed() returns 'press', 'release', 'cancel' or None."""

    def __init__(self, groups: list[set[int]]):
        self.groups, self.keys = groups, set().union(*groups)
        self.down: set[int] = set()
        self.active = False
        self.blocked = False

    def feed(self, vk: int, is_down: bool) -> str | None:
        """Record one key transition and report what it did to the chord."""
        (self.down.add if is_down else self.down.discard)(vk)

        if is_down and vk not in self.keys:
            # Someone else's shortcut (Ctrl+Win+Right switches desktop). Stay out
            # of the way until every chord key is released, or releasing the
            # foreign key would leave the chord held and start a recording.
            was_active, self.active, self.blocked = self.active, False, True
            return "cancel" if was_active else None

        if not self.down & self.keys:
            self.blocked = False

        held = all(self.down & g for g in self.groups)
        if held and not self.active and not self.blocked:
            self.active = True
            return "press"
        if not held and self.active:
            self.active = False
            return "release"
        return None

    def swallows(self, vk: int) -> bool:
        """Whether this key should be eaten rather than passed to the focused app.

        Non-modifier chord keys are eaten while the chord's modifiers are down, so
        holding CTRL+SPACE does not auto-repeat spaces into the app underneath.
        """
        return (
            vk in self.keys
            and vk not in ALL_MODIFIERS
            and all(self.down & g for g in self.groups if g <= ALL_MODIFIERS)
        )


# KBDLLHOOKSTRUCT: only vkCode and flags are read.
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    ]


LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)

# Without explicit prototypes ctypes assumes a 32-bit int return and truncates the
# hook handle, so UnhookWindowsHookEx would later fail on a garbage handle.
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    HOOKPROC,
    ctypes.wintypes.HMODULE,
    ctypes.wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = ctypes.wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [ctypes.wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = ctypes.wintypes.BOOL
user32.CallNextHookEx.argtypes = [
    ctypes.wintypes.HHOOK,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.CallNextHookEx.restype = LRESULT
kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = ctypes.wintypes.HMODULE


class HotkeyManager:
    """Owns the keyboard hook and turns key transitions into chord callbacks."""

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ):
        """
        Args:
            on_press: Called when every key of the chord is down.
            on_release: Called when the chord is broken by releasing one of its keys.
            on_cancel: Called when another key is pressed while the chord is held.
        """
        self.on_press = on_press
        self.on_release = on_release
        self.on_cancel = on_cancel
        self.chord: Chord | None = None
        self.chord_string: str | None = None  # what is live, so callers can spot a change
        self.msg_thread: threading.Thread | None = None
        self._hook = None
        self._proc: Any = None  # the CFUNCTYPE object; must outlive the hook
        self._msg_tid: int | None = None
        self._running = False
        self._ready: threading.Event | None = None
        self._error: str | None = None

    def register(self, chord_string: str) -> None:
        """Install the hook for a chord, replacing any chord already registered.

        Raises:
            HotkeyError: If the chord is invalid or the hook cannot be installed.
        """
        try:
            groups = parse_chord(chord_string)
        except ValueError as e:
            raise HotkeyError(f"Invalid hotkey: {e}") from e

        self.unregister()
        self.chord = Chord(groups)
        self.chord_string = chord_string
        self._running = True
        self._ready = threading.Event()
        self._error = None
        self.msg_thread = threading.Thread(target=self._message_pump, daemon=True)
        self.msg_thread.start()

        if not self._ready.wait(timeout=1.0):
            self._running = False
            raise HotkeyError("Timed out waiting for hotkey registration")
        if self._error:
            self._running = False
            self.msg_thread.join(timeout=0.5)
            raise HotkeyError(self._error)

    def unregister(self) -> None:
        """Remove the hook and stop the message pump."""
        self._running = False
        if self._msg_tid:
            try:
                user32.PostThreadMessageW(self._msg_tid, WM_QUIT, 0, 0)
            except (OSError, AttributeError):
                # OSError: Windows API call failed; AttributeError: invalid thread ID
                pass
        if self.msg_thread:
            self.msg_thread.join(timeout=1.0)
            self.msg_thread = None
        self._msg_tid = None

    def modifiers_up(self) -> bool:
        """True when no modifier of the registered chord is currently held.

        The paste path waits on this: injecting Shift+Insert under a held Ctrl or
        Win turns it into a different shortcut in the target app.
        """
        if not self.chord:
            return True
        return not (self.chord.down & ALL_MODIFIERS)

    def _handle(self, vk: int, is_down: bool) -> None:
        """Feed one transition to the chord and dispatch the matching callback."""
        if not self.chord:
            return
        event = self.chord.feed(vk, is_down)
        if event == "press":
            self.on_press()
        elif event == "release" and self.on_release:
            self.on_release()
        elif event == "cancel" and self.on_cancel:
            self.on_cancel()

    def _hook_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        """The low-level hook procedure. Must return fast; does nothing else."""
        swallow = False
        if n_code == HC_ACTION:
            kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            # Ignore our own synthetic keystrokes, or the Shift+Insert we paste
            # with would feed the tracker and cancel the chord.
            if not kb.flags & LLKHF_INJECTED:
                is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                if is_down or w_param in (WM_KEYUP, WM_SYSKEYUP):
                    self._handle(kb.vkCode, is_down)
                    swallow = self.chord is not None and self.chord.swallows(kb.vkCode)
        if swallow:
            return 1
        return int(user32.CallNextHookEx(None, n_code, w_param, l_param))

    def _message_pump(self) -> None:
        """Install the hook and pump messages for it (runs in a background thread)."""
        self._msg_tid = kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._hook_proc)
        self._hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0
        )
        if not self._hook:
            self._error = "Failed to install the keyboard hook."
            self._running = False
            if self._ready:
                self._ready.set()
            return
        if self._ready:
            self._ready.set()

        try:
            msg = ctypes.wintypes.MSG()
            while self._running:
                if user32.GetMessageW(ctypes.byref(msg), None, 0, 0) == 0:
                    break  # WM_QUIT
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._proc = None
