"""Reusable GUI components for whisper-dictate."""

from collections.abc import Callable, Sequence
from functools import partial
from tkinter import END, Canvas, Menu, TclError, Text, Tk, Toplevel, ttk


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
        self.txt_prompt.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=12, pady=(12, 6))
        self.txt_prompt.insert("1.0", prompt)
        self.txt_prompt.focus_set()

        btns = ttk.Frame(self)
        btns.grid(row=1, column=0, columnspan=2, pady=(0, 12))
        ttk.Button(btns, text="Cancel", command=self.on_cancel).grid(row=0, column=0, padx=(0, 8))
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

        frame = ttk.Frame(self.window, padding=(8, 6))
        frame.pack()

        bg = self.window.cget("background")
        self.dot = Canvas(frame, width=14, height=14, highlightthickness=0, bg=bg, borderwidth=0)
        self.dot.grid(row=0, column=0, padx=(0, 6))
        self.dot_oval = self.dot.create_oval(2, 2, 12, 12, fill=self.COLORS["idle"], outline="")

        self.label = ttk.Label(frame, text="Idle", anchor="w")
        self.label.grid(row=0, column=1, sticky="w")

        frame.columnconfigure(1, weight=1)

        # Reposition when master changes size or placement
        master.bind("<Configure>", self._reposition, add="+")

        # Bind mouse events to allow dragging from anywhere on the small UI
        for w in (self.window, frame, self.label, self.dot):
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
            for w in (self.window, frame, self.label, self.dot):
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

        # Keep fully on the nearest screen
        sw = self.master.winfo_screenwidth()
        sh = self.master.winfo_screenheight()
        self.window.update_idletasks()
        ww = self.window.winfo_width()
        wh = self.window.winfo_height()
        x = max(0, min(x, sw - ww))
        y = max(0, min(y, sh - wh))

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

        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()
        window_w = self.window.winfo_width()
        window_h = self.window.winfo_height()

        # If user has placed it, respect that unless actively dragging
        if self.user_position is not None and not self._dragging:
            x, y = self.user_position
            x = max(0, min(int(x), screen_w - window_w))
            y = max(0, min(int(y), screen_h - window_h))
        else:
            margin_x = 24
            margin_y = 96
            x = screen_w - window_w - margin_x
            y = screen_h - window_h - margin_y

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
        """Re-assert topmost state on an interval."""
        if not self.window.winfo_exists():
            return
        self._raise()
        self.window.after(3000, self._ensure_topmost)

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
        self.dot.itemconfigure(self.dot_oval, fill=color)
        display = message if len(message) <= 40 else message[:37] + "…"
        self.label.config(text=display)
        if not self.window.winfo_viewable():
            self.window.deiconify()
        self.window.update_idletasks()
        self._reposition()

    def get_position(self) -> tuple[int, int] | None:
        """Return the user-chosen position for persistence."""
        if self.user_position is None:
            return None
        return int(self.user_position[0]), int(self.user_position[1])
