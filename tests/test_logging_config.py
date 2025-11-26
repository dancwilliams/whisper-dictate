"""Tests for logging_config.py - logging setup and configuration."""

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Need to patch before importing to prevent directory creation at module level
with patch("whisper_dictate.logging_config.Path.mkdir"):
    from whisper_dictate.logging_config import LOG_DIR, LOG_FILE, setup_logging


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_creates_logger_with_default_level(self):
        """Test that setup_logging creates a logger with INFO level by default."""
        with patch("whisper_dictate.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock(spec=logging.Logger)
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            with patch("whisper_dictate.logging_config.logging.FileHandler"):
                logger = setup_logging()

            assert logger == mock_logger
            mock_get_logger.assert_called_once_with("whisper_dictate")
            mock_logger.setLevel.assert_called_once_with(logging.INFO)

    def test_setup_logging_respects_custom_level(self):
        """Test that setup_logging accepts custom logging level."""
        with patch("whisper_dictate.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock(spec=logging.Logger)
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            with patch("whisper_dictate.logging_config.logging.FileHandler"):
                setup_logging(level=logging.DEBUG)

            mock_logger.setLevel.assert_called_once_with(logging.DEBUG)

    def test_setup_logging_adds_console_handler(self):
        """Test that setup_logging adds a console handler to stderr."""
        with patch("whisper_dictate.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock(spec=logging.Logger)
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            with patch("whisper_dictate.logging_config.logging.StreamHandler") as mock_stream:
                with patch("whisper_dictate.logging_config.logging.FileHandler"):
                    mock_console_handler = MagicMock()
                    mock_stream.return_value = mock_console_handler

                    setup_logging(level=logging.WARNING)

                    # Verify StreamHandler was created with stderr
                    mock_stream.assert_called_once_with(sys.stderr)

                    # Verify handler was configured with correct level
                    mock_console_handler.setLevel.assert_called_once_with(logging.WARNING)

                    # Verify formatter was set
                    assert mock_console_handler.setFormatter.called
                    formatter = mock_console_handler.setFormatter.call_args[0][0]
                    assert isinstance(formatter, logging.Formatter)

                    # Verify handler was added to logger
                    mock_logger.addHandler.assert_any_call(mock_console_handler)

    def test_setup_logging_adds_file_handler(self):
        """Test that setup_logging adds a file handler with DEBUG level."""
        with patch("whisper_dictate.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock(spec=logging.Logger)
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            with patch("whisper_dictate.logging_config.logging.FileHandler") as mock_file:
                mock_file_handler = MagicMock()
                mock_file.return_value = mock_file_handler

                setup_logging()

                # Verify FileHandler was created with correct path and encoding
                mock_file.assert_called_once_with(LOG_FILE, encoding="utf-8")

                # Verify file handler always uses DEBUG level
                mock_file_handler.setLevel.assert_called_once_with(logging.DEBUG)

                # Verify formatter was set
                assert mock_file_handler.setFormatter.called
                formatter = mock_file_handler.setFormatter.call_args[0][0]
                assert isinstance(formatter, logging.Formatter)

                # Verify handler was added to logger
                mock_logger.addHandler.assert_any_call(mock_file_handler)

    def test_setup_logging_console_formatter_format(self):
        """Test that console handler uses correct formatter with short time format."""
        with patch("whisper_dictate.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock(spec=logging.Logger)
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            with patch("whisper_dictate.logging_config.logging.StreamHandler") as mock_stream:
                with patch("whisper_dictate.logging_config.logging.FileHandler"):
                    mock_console_handler = MagicMock()
                    mock_stream.return_value = mock_console_handler

                    setup_logging()

                    # Get the formatter that was set
                    formatter_call = mock_console_handler.setFormatter.call_args[0][0]
                    assert isinstance(formatter_call, logging.Formatter)
                    assert formatter_call._fmt == "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                    assert formatter_call.datefmt == "%H:%M:%S"

    def test_setup_logging_file_formatter_format(self):
        """Test that file handler uses detailed formatter with full timestamp."""
        with patch("whisper_dictate.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock(spec=logging.Logger)
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            with patch("whisper_dictate.logging_config.logging.FileHandler") as mock_file:
                mock_file_handler = MagicMock()
                mock_file.return_value = mock_file_handler

                setup_logging()

                # Get the formatter that was set
                formatter_call = mock_file_handler.setFormatter.call_args[0][0]
                assert isinstance(formatter_call, logging.Formatter)
                expected_fmt = "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
                assert formatter_call._fmt == expected_fmt
                assert formatter_call.datefmt == "%Y-%m-%d %H:%M:%S"

    def test_setup_logging_skips_handlers_if_already_configured(self):
        """Test that setup_logging returns early if logger already has handlers."""
        with patch("whisper_dictate.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock(spec=logging.Logger)
            existing_handler = MagicMock()
            mock_logger.handlers = [existing_handler]
            mock_get_logger.return_value = mock_logger

            with patch("whisper_dictate.logging_config.logging.StreamHandler") as mock_stream:
                with patch("whisper_dictate.logging_config.logging.FileHandler") as mock_file:
                    logger = setup_logging()

                    assert logger == mock_logger
                    mock_logger.setLevel.assert_called_once()

                    # Verify no new handlers were created
                    mock_stream.assert_not_called()
                    mock_file.assert_not_called()
                    mock_logger.addHandler.assert_not_called()

    def test_setup_logging_handles_file_handler_error(self):
        """Test that setup_logging handles file handler creation errors gracefully."""
        with patch("whisper_dictate.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock(spec=logging.Logger)
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            with patch("whisper_dictate.logging_config.logging.FileHandler") as mock_file:
                # Simulate file handler creation failure
                mock_file.side_effect = PermissionError("Permission denied")

                with patch("whisper_dictate.logging_config.logging.StreamHandler"):
                    logger = setup_logging()

                    # Logger should still be returned
                    assert logger == mock_logger

                    # Warning should have been logged
                    mock_logger.warning.assert_called_once()
                    warning_msg = mock_logger.warning.call_args[0][0]
                    assert "Could not set up file logging" in warning_msg
                    assert "Permission denied" in warning_msg

    def test_setup_logging_handles_file_handler_io_error(self):
        """Test that setup_logging handles I/O errors when creating file handler."""
        with patch("whisper_dictate.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock(spec=logging.Logger)
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            with patch("whisper_dictate.logging_config.logging.FileHandler") as mock_file:
                # Simulate I/O error
                mock_file.side_effect = IOError("Disk full")

                with patch("whisper_dictate.logging_config.logging.StreamHandler"):
                    logger = setup_logging()

                    # Logger should still be returned with console handler
                    assert logger == mock_logger

                    # Warning should have been logged
                    mock_logger.warning.assert_called_once()
                    warning_msg = mock_logger.warning.call_args[0][0]
                    assert "Could not set up file logging" in warning_msg

    def test_setup_logging_adds_both_handlers_in_correct_order(self):
        """Test that setup_logging adds console handler first, then file handler."""
        with patch("whisper_dictate.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock(spec=logging.Logger)
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            with patch("whisper_dictate.logging_config.logging.StreamHandler") as mock_stream:
                with patch("whisper_dictate.logging_config.logging.FileHandler") as mock_file:
                    mock_console_handler = MagicMock()
                    mock_file_handler = MagicMock()
                    mock_stream.return_value = mock_console_handler
                    mock_file.return_value = mock_file_handler

                    setup_logging()

                    # Verify both handlers were added in order
                    assert mock_logger.addHandler.call_count == 2
                    calls = mock_logger.addHandler.call_args_list
                    assert calls[0] == call(mock_console_handler)
                    assert calls[1] == call(mock_file_handler)


class TestLoggingConstants:
    """Tests for logging configuration constants."""

    def test_log_dir_location(self):
        """Test that LOG_DIR points to correct location."""
        expected_dir = Path.home() / ".whisper_dictate" / "logs"
        assert LOG_DIR == expected_dir

    def test_log_file_location(self):
        """Test that LOG_FILE points to correct location."""
        expected_file = Path.home() / ".whisper_dictate" / "logs" / "whisper_dictate.log"
        assert LOG_FILE == expected_file
        assert LOG_FILE.name == "whisper_dictate.log"
        assert LOG_FILE.parent == LOG_DIR
