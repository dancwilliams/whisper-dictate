"""Tests for the floating status indicator.

These need a real Tk display, so they skip where there is none. They exist
because two user-visible bugs got through without them: the pill could not be
dragged, and quitting from its menu ended in a traceback.
"""

import sys
from types import SimpleNamespace

import pytest

tkinter = pytest.importorskip("tkinter")

from whisper_dictate import gui_components  # noqa: E402
from whisper_dictate.gui_components import StatusIndicator, work_area  # noqa: E402

# Two monitors: the second is to the right and taller, reaching above y=0,
# like the dev box. The primary's work area stops short of the screen (taskbar).
PRIMARY = (0, 0, 1600, 860)
SECONDARY = (1800, -100, 2600, 900)


def fake_work_area(_master, x, y):
    return SECONDARY if x >= 1700 else PRIMARY


@pytest.fixture(autouse=True)
def monitors(monkeypatch):
    # Real monitor layouts differ between the dev box and CI; the geometry
    # tests need one answer.
    monkeypatch.setattr(gui_components, "work_area", fake_work_area)


@pytest.fixture
def root():
    # Under pytest's fd capture Tk() now and then fails to source its own
    # library files (init.tcl, ttk/spinbox.tcl) and raises; a second try works.
    # Measured on the dev box: 2 of 8 runs with --capture=fd, 0 of 16 without.
    # With no display at all every try fails, and that is the skip.
    for attempt in range(3):
        try:
            window = tkinter.Tk()
            break
        except tkinter.TclError as e:
            if attempt == 2:  # pragma: no cover - headless CI
                pytest.skip(f"no display available: {e}")
    # Withdrawn, as the app leaves it once it is running by itself. The pill
    # misbehaved only in this state, which is why the fixture reproduces it.
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tkinter.TclError:
        pass


def position(indicator) -> tuple[int, int]:
    geometry = indicator.window.geometry()
    _size, x, y = geometry.split("+")
    return int(x), int(y)


def drag(indicator, from_xy, to_xy):
    indicator._start_drag(SimpleNamespace(x_root=from_xy[0], y_root=from_xy[1]))
    indicator._on_drag(SimpleNamespace(x_root=to_xy[0], y_root=to_xy[1]))
    indicator._end_drag(SimpleNamespace())


class TestDragging:
    def test_a_drag_moves_the_pill(self, root):
        """It stuck at 0,0: geometry() only requests a move, and the lift and
        -topmost calls that followed discarded the request."""
        indicator = StatusIndicator(root, initial_position=(200, 200))
        indicator.show()
        root.update()

        drag(indicator, (205, 205), (900, 700))
        root.update()

        assert position(indicator) == (895, 695)
        assert indicator.get_position() == (895, 695)

    def test_the_position_survives_the_topmost_timer(self, root):
        """_ensure_topmost runs every three seconds and used to fling it back."""
        indicator = StatusIndicator(root, initial_position=(200, 200))
        indicator.show()
        root.update()
        drag(indicator, (205, 205), (800, 600))
        root.update()

        indicator._raise()
        indicator._raise()
        root.update()

        assert position(indicator) == (795, 595)

    def test_the_position_survives_a_status_update(self, root):
        indicator = StatusIndicator(root, initial_position=(200, 200))
        indicator.show()
        root.update()
        drag(indicator, (205, 205), (800, 600))
        root.update()

        indicator.update("listening", "Recording; release to stop")
        root.update()

        assert position(indicator) == (795, 595)

    def test_a_saved_position_is_honoured_at_startup(self, root):
        indicator = StatusIndicator(root, initial_position=(321, 123))
        indicator.show()
        root.update()
        assert position(indicator) == (321, 123)

    def test_double_click_resets_to_the_default_corner(self, root):
        indicator = StatusIndicator(root, initial_position=(200, 200))
        indicator.show()
        root.update()
        drag(indicator, (205, 205), (800, 600))
        root.update()

        indicator._reset_position()
        root.update()

        x, y = position(indicator)
        assert x > PRIMARY[2] // 2
        assert indicator.get_position() is None

    def test_the_default_corner_clears_the_taskbar(self, root):
        """It sat a guessed 96 px up; rcWork says where the taskbar really is."""
        indicator = StatusIndicator(root)
        indicator.show()
        root.update()

        x, y = position(indicator)
        assert x + indicator.window.winfo_width() == PRIMARY[2] - StatusIndicator.MARGIN
        assert y + indicator.window.winfo_height() == PRIMARY[3] - StatusIndicator.MARGIN

    def test_the_pill_is_kept_on_screen(self, root):
        indicator = StatusIndicator(root, initial_position=(200, 200))
        indicator.show()
        root.update()

        drag(indicator, (205, 205), (1650, 99999))
        root.update()

        x, y = position(indicator)
        assert x + indicator.window.winfo_width() <= PRIMARY[2]
        assert y + indicator.window.winfo_height() <= PRIMARY[3]

    def test_a_drag_follows_the_pointer_onto_a_second_monitor(self, root):
        """It stopped at the primary's edge: winfo_screenwidth() is one monitor."""
        indicator = StatusIndicator(root, initial_position=(200, 200))
        indicator.show()
        root.update()

        drag(indicator, (205, 205), (2105, 5))
        root.update()

        assert position(indicator) == (2100, 0)

    def test_a_saved_position_on_a_second_monitor_is_honoured(self, root):
        """Saved on the second monitor, it came back on the first at startup and
        after every status change."""
        indicator = StatusIndicator(root, initial_position=(2100, 0))
        indicator.show()
        root.update()
        assert position(indicator) == (2100, 0)

        indicator.update("listening", "Recording; release to stop")
        root.update()
        assert position(indicator) == (2100, 0)

    def test_a_negative_y_on_a_tall_monitor_is_allowed(self, root):
        indicator = StatusIndicator(root, initial_position=(2100, -50))
        indicator.show()
        root.update()
        assert position(indicator) == (2100, -50)

    def test_a_clamped_position_is_not_persisted(self, root):
        """Saved on a monitor that is unplugged today, it is shown on the
        nearest edge but keeps its saved spot for when the monitor is back."""
        indicator = StatusIndicator(root, initial_position=(3000, 0))
        indicator.show()
        root.update()

        x, _y = position(indicator)
        assert x + indicator.window.winfo_width() <= SECONDARY[2]
        assert indicator.get_position() == (3000, 0)


class TestSize:
    def test_the_pill_does_not_resize_between_messages(self, root):
        """Growing with the message moved the right edge, and the clamp then
        jerked the pill about whenever it sat near a screen edge."""
        indicator = StatusIndicator(root)
        indicator.show()
        indicator.update("ready", "Idle")
        root.update()
        idle = indicator.window.winfo_width()

        indicator.update("listening", "Clipboard locked; see transcript")
        root.update()

        assert indicator.window.winfo_width() == idle

    def test_long_messages_are_truncated(self, root):
        indicator = StatusIndicator(root)
        indicator.update("ready", "x" * 60)
        shown = indicator.label.cget("text")
        assert len(shown) == StatusIndicator.MAX_CHARS
        assert shown.endswith("…")


@pytest.mark.skipif(sys.platform != "win32", reason="real Win32 monitor query")
def test_work_area_of_the_primary_monitor(root, monkeypatch):
    # The autouse fixture patched the module attribute; this imported name is
    # the real function. (0, 0) is always on the primary, whose work area is
    # within the screen Tk reports and shorter than it wherever a taskbar is.
    left, top, right, bottom = work_area(root, 0, 0)
    assert (left, top) == (0, 0)
    assert 0 < right <= root.winfo_screenwidth()
    assert 0 < bottom <= root.winfo_screenheight()


class TestMenu:
    def test_commands_run_after_the_menu_closes(self, root):
        """Quit destroys the interpreter. Doing that while the menu is still
        posted unwinds into a dead Tk and raises out of tk_popup."""
        calls = []
        indicator = StatusIndicator(root, menu_items=(("Quit", lambda: calls.append("quit")),))
        indicator.show()
        root.update()

        indicator.menu.invoke(0)
        assert calls == []  # deferred

        root.update()
        assert calls == ["quit"]

    def test_quit_destroys_without_a_traceback(self, root):
        indicator = StatusIndicator(root, menu_items=(("Quit", root.destroy),))
        indicator.show()
        root.update()

        indicator.menu.invoke(0)
        root.update()  # the deferred destroy runs here, and must not raise

    def test_a_right_click_after_destroy_is_silent(self, root):
        indicator = StatusIndicator(root, menu_items=(("Quit", root.destroy),))
        indicator.show()
        root.update()
        root.destroy()

        indicator._show_menu(SimpleNamespace(x_root=10, y_root=10))

    def test_separators_are_separators(self, root):
        indicator = StatusIndicator(
            root, menu_items=(("Show window", lambda: None), ("-", lambda: None))
        )
        assert indicator.menu.type(1) == "separator"

    def test_no_menu_without_items(self, root):
        assert StatusIndicator(root).menu is None
