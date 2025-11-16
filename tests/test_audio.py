"""Tests for audio recording functionality."""

from unittest.mock import MagicMock, patch

import pytest

from whisper_dictate import audio


class TestAudio:
    """Test audio recording functionality."""
    
    def test_is_recording_initial(self):
        """Test initial recording state."""
        # Reset state
        audio.recording = False
        assert audio.is_recording() is False
    
    def test_get_audio_buffer_empty(self):
        """Test getting audio buffer when empty."""
        with audio.buffer_lock:
            audio.audio_buf.clear()
        
        result = audio.get_audio_buffer()
        assert result is None
    
    @patch("whisper_dictate.audio.sd.InputStream")
    def test_start_recording(self, mock_stream_class):
        """Test starting audio recording."""
        mock_stream = MagicMock()
        mock_stream_class.return_value = mock_stream
        
        audio.recording = False
        audio.start_recording()
        
        assert audio.recording is True
        mock_stream.start.assert_called_once()
        mock_stream_class.assert_called_once()
    
    @patch("whisper_dictate.audio.sd.InputStream")
    def test_stop_recording(self, mock_stream_class):
        """Test stopping audio recording."""
        mock_stream = MagicMock()
        audio.stream = mock_stream
        audio.recording = True
        
        audio.stop_recording()
        
        assert audio.recording is False
        assert audio.stream is None
        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()
    
    def test_audio_callback(self):
        """Test audio callback function."""
        import numpy as np
        
        # Clear queue first
        while not audio.audio_q.empty():
            try:
                audio.audio_q.get_nowait()
            except Exception:
                break
        
        # Test mono input
        indata_mono = np.array([0.1, 0.2, 0.3])
        audio.audio_callback(indata_mono, 3, {}, None)
        
        # Check that data was queued
        assert not audio.audio_q.empty()
        queued_data = audio.audio_q.get_nowait()
        assert len(queued_data) == 3
        
        # Test stereo input (should be averaged)
        indata_stereo = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
        audio.audio_callback(indata_stereo, 3, {}, None)
        
        queued_data = audio.audio_q.get_nowait()
        assert len(queued_data) == 3

