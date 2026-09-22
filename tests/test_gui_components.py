"""Tests for the floating status indicator.

These need a real Tk display, so they skip where there is none. They exist
because two user-visible bugs got through without them: the pill could not be
dragged, and quitting from its menu ended in a traceback.
"""

from types import SimpleNamespace

import pytest

tkinter = pytest.importorskip("tkinter")

from whisper_dictate.gui_components import StatusIndicator  # noqa: E402


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

        indicator.update("listening", "Recording - release to transcribe")
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
        assert x > root.winfo_screenwidth() // 2
        assert indicator.get_position() is None

    def test_the_pill_is_kept_on_screen(self, root):
        indicator = StatusIndicator(root, initial_position=(200, 200))
        indicator.show()
        root.update()

        drag(indicator, (205, 205), (99999, 99999))
        root.update()

        x, y = position(indicator)
        assert 0 <= x <= root.winfo_screenwidth()
        assert 0 <= y <= root.winfo_screenheight()


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
