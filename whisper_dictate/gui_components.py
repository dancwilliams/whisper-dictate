"""Reusable GUI components for whisper-dictate."""

import ctypes
import ctypes.wintypes
import platform
import tkinter.font as tkfont
from collections.abc import Callable, Sequence
from functools import partial
from tkinter import END, Canvas, Menu, Misc, TclError, Text, Tk, Toplevel, ttk

MONITOR_DEFAULTTONEAREST = 2


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
    ]


USER32: ctypes.WinDLL | None
if platform.system() == "Windows":
    USER32 = ctypes.windll.user32
    # POINT goes by value; without argtypes ctypes passes it wrong on 64-bit.
    USER32.MonitorFromPoint.argtypes = [ctypes.wintypes.POINT, ctypes.wintypes.DWORD]
    USER32.MonitorFromPoint.restype = ctypes.wintypes.HMONITOR
    USER32.GetMonitorInfoW.argtypes = [ctypes.wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    USER32.GetMonitorInfoW.restype = ctypes.wintypes.BOOL
else:
    USER32 = None


def work_area(master: Tk, x: int, y: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the usable desktop on the monitor nearest (x, y).

    winfo_screenwidth() is the primary monitor only, so a pill on a second
    monitor was clamped back onto the first on every status update. rcWork
    excludes the taskbar. Tk and Win32 share one coordinate space, the
    system-DPI space both see after main()'s SetProcessDPIAware(); a 100 %
    secondary appears scaled by the primary's factor to both. Do not convert.
    """
    if USER32 is not None:
        monitor = USER32.MonitorFromPoint(ctypes.wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST)
        info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
        if monitor and USER32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcWork
            return r.left, r.top, r.right, r.bottom
    return 0, 0, master.winfo_screenwidth(), master.winfo_screenheight()


def px(widget: Misc, points: float) -> int:
    """Pixels for a distance given in points, at this display's density.

    For the options Tk insists are integers: window geometry and Treeview column
    widths. Everything else takes "9p" directly.
    """
    return round(widget.winfo_fpixels(f"{points}p"))


# Keyed out by -transparentcolor so the window is the capsule's shape and
# nothing else. No visible element may use this colour.
KEY = "#010203"

THEMES = {
    "light": {"fill": "#f3f3f3", "edge": "#c8c8c8", "text": "#1b1b1b"},
    "dark": {"fill": "#2b2b2b", "edge": "#3f3f3f", "text": "#f0f0f0"},
}


def _apps_use_light_theme() -> bool:
    """Windows' app theme. Light when off Windows or when the key is unreadable."""
    if platform.system() != "Windows":
        return True
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except OSError:
        return True


class PromptDialog(Toplevel):
    """Dialog for editing the LLM cleanup prompt."""

    def __init__(self, parent: Tk | Toplevel, prompt: str):
        super().__init__(parent)
        self.title("Edit Cleanup Prompt")
        self.transient(parent)
        self.grab_set()
        self.result: str | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.txt_prompt = Text(self, height=16, wrap="word")
        self.txt_prompt.grid(
            row=0, column=0, columnspan=2, sticky="nsew", padx="9p", pady=("9p", "4.5p")
        )
        self.txt_prompt.insert("1.0", prompt)
        self.txt_prompt.focus_set()

        btns = ttk.Frame(self)
        btns.grid(row=1, column=0, columnspan=2, pady=(0, "9p"))
        ttk.Button(btns, text="Cancel", command=self.on_cancel).grid(
            row=0, column=0, padx=(0, "6p")
        )
        ttk.Button(btns, text="Save", command=self.on_save).grid(row=0, column=1)

        self.bind("<Escape>", lambda event: self.on_cancel())
        self.bind("<Control-s>", lambda event: self.on_save())
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def on_cancel(self) -> None:
        """Cancel dialog without saving."""
        self.result = None
        self.destroy()

    def on_save(self) -> None:
        """Save prompt and close dialog."""
        text = self.txt_prompt.get("1.0", END).rstrip()
        self.result = text
        self.destroy()


class StatusIndicator:
    """Small floating indicator that reflects the app's status, draggable and always on top."""

    COLORS = {
        "idle": "#6c757d",
        "ready": "#198754",
        "listening": "#0d6efd",
        "transcribing": "#6610f2",
        "processing": "#fd7e14",
        "warning": "#ffc107",
        "error": "#dc3545",
    }
    MAX_CHARS = 32
    MARGIN_PT = 18
    PAD_Y_PT = 6

    def __init__(
        self,
        master: Tk,
        initial_position: tuple[int, int] | None = None,
        menu_items: Sequence[tuple[str, Callable[[], None]]] | None = None,
    ):
        """
        Args:
            menu_items: (label, command) pairs for the right-click menu; "-" is a
                separator. With the main window hidden this menu is the only way
                to reach the app.
        """
        self.master = master
        self.window = Toplevel(master)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.resizable(False, False)

        # Remember last known position
        self.user_position: tuple[int, int] | None = initial_position

        # Track drag state
        self._dragging = False
        self._drag_offset = (0, 0)

        # One canvas drawing a capsule, over a window background that Windows
        # keys out: the pill is its own shape, not a grey box. Sizes come from
        # the font so a DPI change scales the capsule with the text.
        font = tkfont.nametofont("TkDefaultFont")
        line = font.metrics("linespace")
        height = line + 2 * px(self.window, self.PAD_Y_PT)
        radius = height // 2
        dot = max(8, line * 2 // 3)
        # Fixed width: a pill that grew with the message moved its right edge,
        # and near a screen edge the clamp then jerked it about.
        width = radius + dot + font.measure("0") * self.MAX_CHARS + radius

        self.window.configure(background=KEY)
        try:
            self.window.attributes("-transparentcolor", KEY)
        except TclError:  # pragma: no cover - not Windows; a square pill, still usable
            pass
        self.canvas = Canvas(
            self.window, width=width, height=height, bg=KEY, highlightthickness=0, borderwidth=0
        )
        self.canvas.pack()

        # The fill as two ovals and a rectangle, the edge as two arcs and two
        # lines: no seams, and the 1 px edge hides the 1-bit stair-step that
        # -transparentcolor leaves on the corners.
        y0, y1 = 1, height - 2
        left = (1, y0, height - 2, y1)
        right = (width - height + 1, y0, width - 2, y1)
        self._fill = [
            self.canvas.create_oval(*left, outline=""),
            self.canvas.create_oval(*right, outline=""),
            self.canvas.create_rectangle(radius, y0, width - radius, y1, outline=""),
        ]
        self._edge = [
            self.canvas.create_arc(*left, start=90, extent=180, style="arc"),
            self.canvas.create_arc(*right, start=270, extent=180, style="arc"),
            self.canvas.create_line(radius, y0, width - radius, y0),
            self.canvas.create_line(radius, y1, width - radius, y1),
        ]
        cy = height / 2
        self.dot_oval = self.canvas.create_oval(
            radius - dot / 2,
            cy - dot / 2,
            radius + dot / 2,
            cy + dot / 2,
            fill=self.COLORS["idle"],
            outline="",
        )
        self.text = self.canvas.create_text(
            radius + dot, cy, anchor="w", text="Idle", font="TkDefaultFont"
        )
        self._theme: str | None = None
        self._follow_theme()

        # Reposition when master changes size or placement
        master.bind("<Configure>", self._reposition, add="+")

        # Bind mouse events to allow dragging from anywhere on the small UI
        for w in (self.window, self.canvas):
            w.bind("<ButtonPress-1>", self._start_drag, add="+")
            w.bind("<B1-Motion>", self._on_drag, add="+")
            w.bind("<ButtonRelease-1>", self._end_drag, add="+")
            w.bind("<Double-Button-1>", self._reset_position, add="+")

        self.menu: Menu | None = None
        if menu_items:
            self.menu = Menu(self.window, tearoff=False)
            for label, command in menu_items:
                if label == "-":
                    self.menu.add_separator()
                else:
                    # Run the command after tk_popup returns. Quit destroys the
                    # interpreter, and doing that while the menu is still posted
                    # unwinds into a dead Tk.
                    self.menu.add_command(label=label, command=partial(self._defer, command))
            for w in (self.window, self.canvas):
                w.bind("<Button-3>", self._show_menu, add="+")

        # Keep the floating window pinned above everything else
        self.window.after(1500, self._ensure_topmost)

    def _defer(self, command: Callable[[], None]) -> None:
        """Run a menu command once the menu has closed."""
        self.window.after(0, command)

    def _show_menu(self, event) -> None:
        """Open the right-click menu at the pointer."""
        if self.menu is None:
            return
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        except TclError:
            # A right-click that lands as the app is going away, or a Quit that
            # destroyed the interpreter while the menu was still posted.
            return
        finally:
            try:
                self.menu.grab_release()
            except TclError:
                pass

    def _start_drag(self, event) -> None:
        """Start dragging the indicator."""
        wx = self.window.winfo_x()
        wy = self.window.winfo_y()
        self._drag_offset = (event.x_root - wx, event.y_root - wy)
        self._dragging = True

    def _on_drag(self, event) -> None:
        """Handle dragging motion."""
        if not self._dragging:
            return
        x = int(event.x_root - self._drag_offset[0])
        y = int(event.y_root - self._drag_offset[1])

        # Keep fully on the monitor under the pointer, so it follows a drag
        # across monitors instead of stopping at the primary's edge.
        left, top, right, bottom = work_area(self.master, event.x_root, event.y_root)
        self.window.update_idletasks()
        ww = self.window.winfo_width()
        wh = self.window.winfo_height()
        x = max(left, min(x, right - ww))
        y = max(top, min(y, bottom - wh))

        self.window.geometry(f"+{x}+{y}")

        # Remember that the user moved it
        self.user_position = (x, y)

    def _end_drag(self, event) -> None:
        """End dragging."""
        self._dragging = False

    def _reset_position(self, event=None) -> None:
        """Reset position to default (bottom-right)."""
        self.user_position = None
        self._reposition()

    def _reposition(self, event=None) -> None:
        """Reposition the indicator window.

        Position is honoured even while the window is hidden - Tk remembers the
        geometry and applies it on map. Gating this on winfo_viewable() left the
        pill at 0,0 when it was deiconified moments earlier, because the map had
        not been processed yet.
        """
        if not self.window.winfo_exists():
            return

        self.window.update_idletasks()

        window_w = self.window.winfo_width()
        window_h = self.window.winfo_height()

        # If user has placed it, respect that unless actively dragging
        if self.user_position is not None and not self._dragging:
            x, y = self.user_position
            left, top, right, bottom = work_area(self.master, int(x), int(y))
            x = max(left, min(int(x), right - window_w))
            y = max(top, min(int(y), bottom - window_h))
        else:
            # (0, 0) is always on the primary; rcWork already clears the taskbar.
            _left, _top, right, bottom = work_area(self.master, 0, 0)
            margin = px(self.window, self.MARGIN_PT)
            x = right - window_w - margin
            y = bottom - window_h - margin

        self.window.geometry(f"+{int(x)}+{int(y)}")
        # Flush the move before touching z-order: geometry() only *requests* a
        # position, and lift() acts on where the window actually is, discarding
        # the pending request.
        self.window.update_idletasks()
        self._raise()

    def _raise(self) -> None:
        """Keep the pill above everything without moving it.

        Setting -topmost on a window that already has it snaps it back to
        wherever Windows last placed it, which undid every drag and every
        reposition. Only assert it when it has actually been lost.
        """
        self.window.lift()
        try:
            if not self.window.attributes("-topmost"):
                self.window.attributes("-topmost", True)
        except TclError:  # pragma: no cover - window going away
            pass

    def _ensure_topmost(self) -> None:
        """Re-assert topmost state on an interval, and follow the Windows theme."""
        if not self.window.winfo_exists():
            return
        self._raise()
        self._follow_theme()
        self.window.after(3000, self._ensure_topmost)

    def _follow_theme(self) -> None:
        """Match Windows' light or dark app theme, live.

        Read on the topmost timer, which already ticks every 3 s: a pill that
        stays light on a desktop that just went dark looks broken, and a
        registry read costs nothing.
        """
        name = "light" if _apps_use_light_theme() else "dark"
        if name == self._theme:
            return
        self._theme = name
        theme = THEMES[name]
        for item in self._fill:
            self.canvas.itemconfigure(item, fill=theme["fill"])
        for item in self._edge:
            # A line's colour is its fill; an arc's is its outline.
            if self.canvas.type(item) == "line":
                self.canvas.itemconfigure(item, fill=theme["edge"])
            else:
                self.canvas.itemconfigure(item, outline=theme["edge"])
        self.canvas.itemconfigure(self.text, fill=theme["text"])

    def show(self) -> None:
        """Make the indicator visible.

        Called at startup rather than waiting for the first status change: with
        the main window hidden the pill is the whole app, and an app you cannot
        see has not started as far as the user is concerned.
        """
        # Place it before mapping it. Geometry set between deiconify() and the
        # map being processed is discarded, which left the pill at 0,0.
        self.window.update_idletasks()
        self._reposition()
        if not self.window.winfo_viewable():
            self.window.deiconify()

    def update(self, state: str, message: str) -> None:
        """Update the indicator with new state and message."""
        color = self.COLORS.get(state, self.COLORS["idle"])
        self.canvas.itemconfigure(self.dot_oval, fill=color)
        limit = self.MAX_CHARS
        display = message if len(message) <= limit else message[: limit - 1] + "…"
        self.canvas.itemconfigure(self.text, text=display)
        if not self.window.winfo_viewable():
            self.window.deiconify()
        self.window.update_idletasks()
        self._reposition()

    def get_position(self) -> tuple[int, int] | None:
        """Return the user-chosen position for persistence."""
        if self.user_position is None:
            return None
        return int(self.user_position[0]), int(self.user_position[1])
