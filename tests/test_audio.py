"""Tests for audio recording functionality."""

from unittest.mock import MagicMock, patch

import numpy as np

from whisper_dictate import audio
from whisper_dictate.audio import AudioRecorder


class TestAudioRecorder:
    """Test AudioRecorder class."""

    @patch("whisper_dictate.audio.sd.InputStream")
    def test_start_recording(self, mock_stream_class):
        """Test starting audio recording."""
        mock_stream = MagicMock()
        mock_stream_class.return_value = mock_stream

        recorder = AudioRecorder()
        recorder.start()

        assert recorder.is_recording() is True
        mock_stream.start.assert_called_once()
        mock_stream_class.assert_called_once()

    @patch("whisper_dictate.audio.sd.InputStream")
    def test_stop_recording(self, mock_stream_class):
        """Test stopping audio recording."""
        mock_stream = MagicMock()
        mock_stream_class.return_value = mock_stream

        recorder = AudioRecorder()
        recorder.start()
        recorder.stop()

        assert recorder.is_recording() is False
        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()

    def test_get_buffer_empty(self):
        """Test getting audio buffer when empty."""
        recorder = AudioRecorder()
        result = recorder.get_buffer()
        assert result is None

    def test_get_buffer_with_data(self):
        """Test getting audio buffer with data."""
        recorder = AudioRecorder()

        # Manually add some data to the buffer
        test_data1 = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        test_data2 = np.array([0.4, 0.5], dtype=np.float32)

        with recorder._buffer_lock:
            recorder._audio_buffer.append(test_data1)
            recorder._audio_buffer.append(test_data2)

        result = recorder.get_buffer()

        assert result is not None
        assert len(result) == 5  # Combined length
        assert isinstance(result, np.ndarray)

        # Buffer should be cleared
        assert recorder.get_buffer() is None

    def test_audio_callback_mono(self):
        """Test audio callback with mono input."""
        recorder = AudioRecorder()

        indata_mono = np.array([0.1, 0.2, 0.3])
        recorder._audio_callback(indata_mono, 3, {}, None)

        # Check that data was queued
        assert not recorder._audio_queue.empty()

    def test_audio_callback_stereo(self):
        """Test audio callback with stereo input (should be averaged to mono)."""
        recorder = AudioRecorder()

        indata_stereo = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
        recorder._audio_callback(indata_stereo, 3, {}, None)

        # Check that data was queued
        assert not recorder._audio_queue.empty()
        queued_data = recorder._audio_queue.get_nowait()
        assert len(queued_data) == 3  # Should be mono

    def test_custom_parameters(self):
        """Test creating recorder with custom parameters."""
        recorder = AudioRecorder(sample_rate=44100, channels=2, chunk_ms=100)

        assert recorder.sample_rate == 44100
        assert recorder.channels == 2
        assert recorder.chunk_ms == 100

    @patch("whisper_dictate.audio.sd.InputStream")
    def test_shutdown(self, mock_stream_class):
        """Test shutdown cleanup."""
        mock_stream = MagicMock()
        mock_stream_class.return_value = mock_stream

        recorder = AudioRecorder()
        recorder.start()
        recorder.shutdown()

        assert recorder.is_recording() is False
        assert recorder._stop_recorder.is_set()

    @patch("whisper_dictate.audio.sd.InputStream")
    def test_stop_with_stream_error(self, mock_stream_class):
        """Test that stop handles stream errors gracefully."""
        mock_stream = MagicMock()
        mock_stream.stop.side_effect = RuntimeError("Stream error")
        mock_stream_class.return_value = mock_stream

        recorder = AudioRecorder()
        recorder.start()
        recorder.stop()  # Should not raise

        assert recorder.is_recording() is False


class TestBackwardCompatibility:
    """Test backward compatibility functions."""

    def test_is_recording_initial(self):
        """Test initial recording state via compat function."""
        # Get a fresh recorder instance
        recorder = audio.get_default_recorder()
        recorder.stop()  # Ensure clean state
        assert audio.is_recording() is False

    def test_get_audio_buffer_empty(self):
        """Test getting audio buffer when empty via compat function."""
        recorder = audio.get_default_recorder()
        recorder.stop()  # Ensure clean state
        _ = recorder.get_buffer()  # Clear any existing data

        result = audio.get_audio_buffer()
        assert result is None

    @patch("whisper_dictate.audio.sd.InputStream")
    def test_start_recording_compat(self, mock_stream_class):
        """Test starting audio recording via compat function."""
        mock_stream = MagicMock()
        mock_stream_class.return_value = mock_stream

        audio.start_recording()

        assert audio.is_recording() is True
        mock_stream.start.assert_called_once()

    @patch("whisper_dictate.audio.sd.InputStream")
    def test_stop_recording_compat(self, mock_stream_class):
        """Test stopping audio recording via compat function."""
        mock_stream = MagicMock()
        mock_stream_class.return_value = mock_stream

        audio.start_recording()
        audio.stop_recording()

        assert audio.is_recording() is False
        mock_stream.stop.assert_called_once()

    def test_recorder_loop_compat(self):
        """Test that recorder_loop exists for backward compatibility."""
        # This function should exist but do nothing
        audio.recorder_loop()  # Should not raise
