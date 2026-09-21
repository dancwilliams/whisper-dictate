"""Tests for audio recording functionality."""

import threading
from unittest.mock import MagicMock, patch

import numpy as np

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

    @patch("whisper_dictate.audio.sd.InputStream")
    def test_on_first_audio_fires_once_per_recording(self, mock_stream_class):
        """The cue must fire on the first block and not again mid-recording."""
        mock_stream_class.return_value = MagicMock()
        fired = []
        recorder = AudioRecorder()

        recorder.start(on_first_audio=lambda: fired.append(1))
        block = np.array([0.1, 0.2, 0.3])
        recorder._audio_callback(block, 3, {}, None)
        recorder._audio_callback(block, 3, {}, None)
        assert fired == [1]

        # A second recording gets its own cue.
        recorder.start(on_first_audio=lambda: fired.append(2))
        recorder._audio_callback(block, 3, {}, None)
        assert fired == [1, 2]

    @patch("whisper_dictate.audio.sd.InputStream")
    def test_start_without_callback_is_silent(self, mock_stream_class):
        """A recording started from the button passes no cue; the callback must cope."""
        mock_stream_class.return_value = MagicMock()
        recorder = AudioRecorder()
        recorder.start()
        recorder._audio_callback(np.array([0.1]), 1, {}, None)

    @patch("whisper_dictate.audio.sd.InputStream")
    def test_prewarm_opens_and_closes_a_stream(self, mock_stream_class):
        """Startup pays the cold-open cost so the first real press does not."""
        mock_stream = MagicMock()
        mock_stream_class.return_value = mock_stream

        AudioRecorder().prewarm()

        mock_stream_class.assert_called_once()
        mock_stream.close.assert_called_once()

    @patch("whisper_dictate.audio.sd.InputStream", side_effect=RuntimeError("no device"))
    def test_prewarm_swallows_failures(self, _mock_stream_class):
        """A missing microphone at startup is the next start()'s problem to report."""
        AudioRecorder().prewarm()

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

    @patch("whisper_dictate.audio.sd.InputStream")
    def test_stop_waits_for_the_collector(self, mock_stream_class):
        """The worker reads the buffer straight after stop(): the tail must be in it."""
        mock_stream_class.return_value = MagicMock()
        recorder = AudioRecorder()
        recorder.start()
        block = np.array([0.1, 0.2, 0.3])

        # Hold the collector off the buffer so the blocks are still queued at stop().
        recorder._buffer_lock.acquire()
        for _ in range(3):
            recorder._audio_callback(block, len(block), {}, None)
        threading.Timer(0.05, recorder._buffer_lock.release).start()
        recorder.stop()

        assert recorder._audio_queue.unfinished_tasks == 0
        assert len(recorder.get_buffer()) == 3 * len(block)
