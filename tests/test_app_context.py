"""Tests for app_context.py - Active window detection and context formatting."""

from unittest.mock import MagicMock

import pytest

from whisper_dictate import app_context


class TestActiveContext:
    """Tests for ActiveContext dataclass."""

    def test_active_context_creation(self):
        """Test creating ActiveContext with all fields."""
        ctx = app_context.ActiveContext(
            window_title="Test Window",
            process_name="test.exe",
            cursor_position=(100, 200)
        )

        assert ctx.window_title == "Test Window"
        assert ctx.process_name == "test.exe"
        assert ctx.cursor_position == (100, 200)

    def test_active_context_with_none_values(self):
        """Test creating ActiveContext with None values."""
        ctx = app_context.ActiveContext(
            window_title=None,
            process_name=None,
            cursor_position=None
        )

        assert ctx.window_title is None
        assert ctx.process_name is None
        assert ctx.cursor_position is None

    def test_active_context_is_frozen(self):
        """Test that ActiveContext is immutable (frozen dataclass)."""
        ctx = app_context.ActiveContext(
            window_title="Test",
            process_name="test.exe",
            cursor_position=(0, 0)
        )

        with pytest.raises(AttributeError):
            ctx.window_title = "Modified"


class TestFormatContextForPrompt:
    """Tests for format_context_for_prompt function."""

    def test_format_context_with_all_fields(self):
        """Test formatting context with all fields present."""
        ctx = app_context.ActiveContext(
            window_title="Document - Word",
            process_name="winword.exe",
            cursor_position=(120, 340),
        )

        fragment = app_context.format_context_for_prompt(ctx)

        assert fragment
        assert "Active application: winword.exe" in fragment
        assert "window: Document - Word" in fragment
        assert "Cursor position at screen coordinates x=120, y=340" in fragment

    def test_format_context_with_process_only(self):
        """Test formatting context with only process name."""
        ctx = app_context.ActiveContext(
            window_title=None,
            process_name="notepad.exe",
            cursor_position=None,
        )

        fragment = app_context.format_context_for_prompt(ctx)

        assert fragment == "Active application: notepad.exe."

    def test_format_context_with_window_only(self):
        """Test formatting context with only window title."""
        ctx = app_context.ActiveContext(
            window_title="Untitled - Notepad",
            process_name=None,
            cursor_position=None,
        )

        fragment = app_context.format_context_for_prompt(ctx)

        assert fragment == "Active window: Untitled - Notepad."

    def test_format_context_with_cursor_only(self):
        """Test formatting context with only cursor position."""
        ctx = app_context.ActiveContext(
            window_title=None,
            process_name=None,
            cursor_position=(500, 600),
        )

        fragment = app_context.format_context_for_prompt(ctx)

        assert fragment == "Cursor position at screen coordinates x=500, y=600."

    def test_format_context_returns_none_for_none_input(self):
        """Test that None input returns None."""
        fragment = app_context.format_context_for_prompt(None)

        assert fragment is None

    def test_format_context_returns_none_for_empty_context(self):
        """Test that context with all None fields returns None."""
        ctx = app_context.ActiveContext(
            window_title=None,
            process_name=None,
            cursor_position=None,
        )

        fragment = app_context.format_context_for_prompt(ctx)

        assert fragment is None


class TestGetActiveContextNonWindows:
    """Tests for get_active_context on non-Windows platforms."""

    def test_get_active_context_no_windows(self, monkeypatch):
        """Test that get_active_context returns None on non-Windows platforms."""
        monkeypatch.setattr(app_context.platform, "system", lambda: "Linux")
        monkeypatch.setattr(app_context, "USER32", None)
        monkeypatch.setattr(app_context, "KERNEL32", None)

        assert app_context.get_active_context() is None


class TestGetActiveContextWindows:
    """Tests for get_active_context on Windows platform with mocked APIs."""

    def test_get_active_context_success(self, monkeypatch):
        """Test successful retrieval of active context on Windows."""
        # Mock Windows API
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()

        # Mock GetForegroundWindow to return a valid hwnd
        mock_user32.GetForegroundWindow.return_value = 12345

        # Mock GetCursorPos
        def mock_get_cursor_pos(point_ref):
            point_ref.contents.x = 100
            point_ref.contents.y = 200
            return True
        mock_user32.GetCursorPos.side_effect = mock_get_cursor_pos

        monkeypatch.setattr(app_context, "USER32", mock_user32)
        monkeypatch.setattr(app_context, "KERNEL32", mock_kernel32)

        # Mock the helper functions
        monkeypatch.setattr(app_context, "_get_window_title", lambda hwnd: "Test Window")
        monkeypatch.setattr(app_context, "_get_process_name", lambda hwnd: "test.exe")
        monkeypatch.setattr(app_context, "_get_cursor_position", lambda: (100, 200))

        result = app_context.get_active_context()

        assert result is not None
        assert result.window_title == "Test Window"
        assert result.process_name == "test.exe"
        assert result.cursor_position == (100, 200)

    def test_get_active_context_no_foreground_window(self, monkeypatch):
        """Test that None is returned when no foreground window exists."""
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()

        # Mock GetForegroundWindow to return 0 (no window)
        mock_user32.GetForegroundWindow.return_value = 0

        monkeypatch.setattr(app_context, "USER32", mock_user32)
        monkeypatch.setattr(app_context, "KERNEL32", mock_kernel32)

        result = app_context.get_active_context()

        assert result is None

    def test_get_active_context_exception_handling(self, monkeypatch):
        """Test that exceptions are caught and None is returned."""
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()

        mock_user32.GetForegroundWindow.return_value = 12345

        monkeypatch.setattr(app_context, "USER32", mock_user32)
        monkeypatch.setattr(app_context, "KERNEL32", mock_kernel32)

        # Mock helper to raise exception
        def raise_error(hwnd):
            raise RuntimeError("API call failed")
        monkeypatch.setattr(app_context, "_get_window_title", raise_error)

        result = app_context.get_active_context()

        assert result is None


class TestGetWindowTitle:
    """Tests for _get_window_title helper function."""

    def test_get_window_title_success(self, monkeypatch):
        """Test successful window title retrieval."""
        mock_user32 = MagicMock()
        test_title = "Notepad - Untitled"

        # Mock GetWindowTextLengthW to return title length
        mock_user32.GetWindowTextLengthW.return_value = len(test_title)

        # Mock GetWindowTextW to populate buffer
        def mock_get_window_text(hwnd, buffer, max_count):
            for i, char in enumerate(test_title):
                buffer[i] = char
            buffer[len(test_title)] = '\0'
            return len(test_title)

        mock_user32.GetWindowTextW.side_effect = mock_get_window_text

        monkeypatch.setattr(app_context, "USER32", mock_user32)

        result = app_context._get_window_title(12345)

        assert result == test_title

    def test_get_window_title_empty_title(self, monkeypatch):
        """Test that empty title returns None."""
        mock_user32 = MagicMock()

        # Mock GetWindowTextLengthW to return 0
        mock_user32.GetWindowTextLengthW.return_value = 0

        monkeypatch.setattr(app_context, "USER32", mock_user32)

        result = app_context._get_window_title(12345)

        assert result is None

    def test_get_window_title_whitespace_only(self, monkeypatch):
        """Test that whitespace-only title returns None."""
        mock_user32 = MagicMock()

        mock_user32.GetWindowTextLengthW.return_value = 3

        def mock_get_window_text(hwnd, buffer, max_count):
            for i, char in enumerate("   "):
                buffer[i] = char
            buffer[3] = '\0'
            return 3

        mock_user32.GetWindowTextW.side_effect = mock_get_window_text

        monkeypatch.setattr(app_context, "USER32", mock_user32)

        result = app_context._get_window_title(12345)

        assert result is None

    def test_get_window_title_api_failure(self, monkeypatch):
        """Test that API failure returns None."""
        mock_user32 = MagicMock()

        mock_user32.GetWindowTextLengthW.return_value = 10
        mock_user32.GetWindowTextW.return_value = 0  # Failure

        monkeypatch.setattr(app_context, "USER32", mock_user32)

        result = app_context._get_window_title(12345)

        assert result is None


class TestGetProcessName:
    """Tests for _get_process_name helper function."""

    def test_get_process_name_success(self, monkeypatch):
        """Test successful process name retrieval."""
        from pathlib import PureWindowsPath

        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()

        # Mock GetWindowThreadProcessId - set the PID value directly
        def mock_get_thread_id(hwnd, pid_ref):
            # Access the underlying ctypes structure and set its value
            pid_ref._obj.value = 1234
            return 1

        mock_user32.GetWindowThreadProcessId.side_effect = mock_get_thread_id

        # Mock OpenProcess to return valid handle
        mock_kernel32.OpenProcess.return_value = 99999

        # Mock QueryFullProcessImageNameW
        def mock_query_name(handle, flags, buffer, size_ref):
            test_path = r"C:\Windows\System32\notepad.exe"
            for i, char in enumerate(test_path):
                buffer[i] = char
            buffer[len(test_path)] = '\0'
            return True

        mock_kernel32.QueryFullProcessImageNameW.side_effect = mock_query_name

        # Patch Path to use PureWindowsPath so it handles Windows paths correctly on Linux
        monkeypatch.setattr("whisper_dictate.app_context.Path", PureWindowsPath)
        monkeypatch.setattr(app_context, "USER32", mock_user32)
        monkeypatch.setattr(app_context, "KERNEL32", mock_kernel32)

        result = app_context._get_process_name(12345)

        assert result == "notepad.exe"
        # Verify CloseHandle was called
        mock_kernel32.CloseHandle.assert_called_once_with(99999)

    def test_get_process_name_open_process_fails(self, monkeypatch):
        """Test that None is returned when OpenProcess fails."""
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()

        def mock_get_thread_id(hwnd, pid_ref):
            pid_ref._obj.value = 1234
            return 1

        mock_user32.GetWindowThreadProcessId.side_effect = mock_get_thread_id

        # Mock OpenProcess to return 0 (failure)
        mock_kernel32.OpenProcess.return_value = 0

        monkeypatch.setattr(app_context, "USER32", mock_user32)
        monkeypatch.setattr(app_context, "KERNEL32", mock_kernel32)

        result = app_context._get_process_name(12345)

        assert result is None

    def test_get_process_name_query_fails(self, monkeypatch):
        """Test that None is returned when QueryFullProcessImageNameW fails."""
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()

        def mock_get_thread_id(hwnd, pid_ref):
            pid_ref._obj.value = 1234
            return 1

        mock_user32.GetWindowThreadProcessId.side_effect = mock_get_thread_id
        mock_kernel32.OpenProcess.return_value = 99999
        mock_kernel32.QueryFullProcessImageNameW.return_value = False  # Failure

        monkeypatch.setattr(app_context, "USER32", mock_user32)
        monkeypatch.setattr(app_context, "KERNEL32", mock_kernel32)

        result = app_context._get_process_name(12345)

        assert result is None
        # Verify CloseHandle was still called
        mock_kernel32.CloseHandle.assert_called_once_with(99999)


class TestGetCursorPosition:
    """Tests for _get_cursor_position helper function."""

    def test_get_cursor_position_success(self, monkeypatch):
        """Test successful cursor position retrieval."""
        mock_user32 = MagicMock()

        def mock_get_cursor_pos(point_ref):
            # Simulate setting the POINT structure
            point_ref._obj.x = 150
            point_ref._obj.y = 250
            return True

        mock_user32.GetCursorPos.side_effect = mock_get_cursor_pos

        monkeypatch.setattr(app_context, "USER32", mock_user32)

        result = app_context._get_cursor_position()

        assert result == (150, 250)

    def test_get_cursor_position_api_failure(self, monkeypatch):
        """Test that None is returned when GetCursorPos fails."""
        mock_user32 = MagicMock()
        mock_user32.GetCursorPos.return_value = False  # Failure

        monkeypatch.setattr(app_context, "USER32", mock_user32)

        result = app_context._get_cursor_position()

        assert result is None
