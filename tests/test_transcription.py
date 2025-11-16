"""Tests for transcription functionality."""

from unittest.mock import MagicMock, patch

import pytest

from whisper_dictate.transcription import TranscriptionError, load_model, transcribe_audio


class TestTranscription:
    """Test transcription functionality."""
    
    def test_transcribe_audio_success(self):
        """Test successful transcription."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Hello world"
        mock_model.transcribe.return_value = ([mock_segment], {})
        
        audio_data = b"fake audio data"
        result = transcribe_audio(mock_model, audio_data)
        
        assert result == "Hello world"
        mock_model.transcribe.assert_called_once()
    
    def test_transcribe_audio_multiple_segments(self):
        """Test transcription with multiple segments."""
        mock_model = MagicMock()
        mock_segments = [
            MagicMock(text="Hello"),
            MagicMock(text=" world"),
            MagicMock(text="!"),
        ]
        mock_model.transcribe.return_value = (mock_segments, {})
        
        audio_data = b"fake audio data"
        result = transcribe_audio(mock_model, audio_data)
        
        assert result == "Hello world!"
    
    def test_transcribe_audio_empty_result(self):
        """Test transcription with empty result."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], {})
        
        audio_data = b"fake audio data"
        result = transcribe_audio(mock_model, audio_data)
        
        assert result == ""
    
    def test_transcribe_audio_error(self):
        """Test transcription error handling."""
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("Transcription failed")
        
        audio_data = b"fake audio data"
        with pytest.raises(TranscriptionError, match="Transcription failed"):
            transcribe_audio(mock_model, audio_data)
    
    @patch("whisper_dictate.transcription.WhisperModel")
    @patch("whisper_dictate.transcription.normalize_compute_type")
    def test_load_model(self, mock_normalize, mock_whisper_model):
        """Test model loading."""
        mock_normalize.return_value = "float16"
        mock_model_instance = MagicMock()
        mock_whisper_model.return_value = mock_model_instance
        
        result = load_model("small", "cuda", "float16")
        
        assert result == mock_model_instance
        mock_normalize.assert_called_once_with("cuda", "float16")
        mock_whisper_model.assert_called_once_with("small", device="cuda", compute_type="float16")

