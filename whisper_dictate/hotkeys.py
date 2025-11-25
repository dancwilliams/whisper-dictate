"""Windows global hotkey management."""

import ctypes
import ctypes.wintypes
import threading
from typing import Callable, Optional

# Windows hotkey constants
_windll = getattr(ctypes, "windll", None)
if _windll and hasattr(_windll, "user32"):
    user32 = _windll.user32
    _kernel32 = _windll.kernel32
    _native_hotkeys_available = True
else:
    user32 = None
    _kernel32 = None
    _native_hotkeys_available = False
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
TOGGLE_ID = 1

VK = {c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


class HotkeyError(Exception):
    """Raised when hotkey registration fails."""


def parse_hotkey_string(s: str) -> tuple[int, int]:
    """
    Parse a hotkey string like 'CTRL+WIN+G' into modifier flags and virtual key code.
    
    Args:
        s: Hotkey string (e.g., "CTRL+WIN+G")
        
    Returns:
        Tuple of (modifier_flags, virtual_key_code)
        
    Raises:
        ValueError: If hotkey string is invalid
    """
    parts = [p.strip().upper() for p in s.split("+") if p.strip()]
    if not parts:
        raise ValueError("Empty hotkey")
    
    key = parts[-1]
    mods_tokens = parts[:-1]
    mods = 0
    
    for m in mods_tokens:
        if m == "CTRL":
            mods |= MOD_CONTROL
        elif m == "ALT":
            mods |= MOD_ALT
        elif m == "SHIFT":
            mods |= MOD_SHIFT
        elif m == "WIN":
            mods |= MOD_WIN
        else:
            raise ValueError(f"Unknown modifier: {m}")
    
    if len(key) == 1 and key.isalpha():
        vk = VK[key]
    else:
        raise ValueError("Only single A..Z keys supported")
    
    return mods, vk


class HotkeyManager:
    """Manages Windows global hotkey registration and message pumping."""
    
    def __init__(self, callback: Callable[[], None]):
        """
        Initialize hotkey manager.
        
        Args:
            callback: Function to call when hotkey is pressed
        """
        self.callback = callback
        self.msg_thread: Optional[threading.Thread] = None
        self._hotkey_mods: Optional[int] = None
        self._hotkey_vk: Optional[int] = None
        self._msg_tid: Optional[int] = None
        self._running = False
        self._registration_event: Optional[threading.Event] = None
        self._registration_error: Optional[str] = None
    
    def register(self, hotkey_string: str) -> None:
        """
        Register a hotkey and start the message pump thread.
        
        Args:
            hotkey_string: Hotkey string (e.g., "CTRL+WIN+G")
            
        Raises:
            HotkeyError: If registration fails
        """
        try:
            mods, key = parse_hotkey_string(hotkey_string)
        except ValueError as e:
            raise HotkeyError(f"Invalid hotkey: {e}") from e
        
        # Store for the worker thread
        self._hotkey_mods = mods
        self._hotkey_vk = key
        
        # If a previous message thread is running, stop it
        if self.msg_thread and self.msg_thread.is_alive():
            try:
                # Post WM_QUIT to that thread to end GetMessageW
                if user32:
                    user32.PostThreadMessageW(self._msg_tid, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
            self.msg_thread.join(timeout=0.5)
        
        if not _native_hotkeys_available:
            raise HotkeyError(
                "Failed to register hotkey: Windows APIs unavailable on this platform."
            )

        # Start a fresh message pump that registers the hotkey in the same thread
        self._running = True
        self._registration_event = threading.Event()
        self._registration_error = None
        self.msg_thread = threading.Thread(target=self._message_pump, daemon=True)
        self.msg_thread.start()

        # Wait for the worker thread to report registration status
        if not self._registration_event.wait(timeout=1.0):
            self._running = False
            raise HotkeyError("Timed out waiting for hotkey registration")

        if self._registration_error:
            self._running = False
            if self.msg_thread:
                self.msg_thread.join(timeout=0.5)
            raise HotkeyError(self._registration_error)
    
    def unregister(self) -> None:
        """Unregister hotkey and stop message pump."""
        self._running = False
        if self._msg_tid and user32:
            try:
                user32.PostThreadMessageW(self._msg_tid, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
        if self.msg_thread:
            self.msg_thread.join(timeout=1.0)
        if user32:
            user32.UnregisterHotKey(None, TOGGLE_ID)
    
    def _message_pump(self) -> None:
        """Windows message pump for hotkey handling (runs in background thread)."""
        # Save this thread's id so we can post WM_QUIT when re-registering
        if not _kernel32 or not user32:
            self._registration_error = (
                "Failed to register hotkey: Windows APIs unavailable on this platform."
            )
            if self._registration_event:
                self._registration_event.set()
            self._running = False
            return

        self._msg_tid = _kernel32.GetCurrentThreadId()

        # Register the hotkey in THIS thread so WM_HOTKEY arrives here
        if not user32.RegisterHotKey(None, TOGGLE_ID, self._hotkey_mods, self._hotkey_vk):
            # Registration failed; signal the waiting register() call
            self._registration_error = "Failed to register hotkey. The combination may already be in use."
            if self._registration_event:
                self._registration_event.set()
            self._running = False
            return

        if self._registration_event:
            self._registration_event.set()
        
        try:
            msg = ctypes.wintypes.MSG()
            while self._running:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0:  # WM_QUIT received
                    break
                if msg.message == WM_HOTKEY and msg.wParam == TOGGLE_ID:
                    # Call callback (caller should handle thread safety)
                    self.callback()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if user32:
                user32.UnregisterHotKey(None, TOGGLE_ID)

