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

    def test_transcribe_audio_with_vad(self):
        """Test transcription with VAD enabled."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Hello world"
        mock_model.transcribe.return_value = ([mock_segment], {})

        audio_data = b"fake audio data"
        result = transcribe_audio(
            mock_model,
            audio_data,
            vad_filter=True,
            vad_parameters={
                "threshold": 0.5,
                "min_speech_duration_ms": 250,
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 400,
            },
        )

        assert result == "Hello world"
        mock_model.transcribe.assert_called_once()
        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["vad_filter"] is True
        assert call_kwargs["vad_parameters"]["threshold"] == 0.5
        assert call_kwargs["vad_parameters"]["min_speech_duration_ms"] == 250

    def test_transcribe_audio_vad_default_parameters(self):
        """Test that VAD uses default parameters when enabled but not specified."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Test"
        mock_model.transcribe.return_value = ([mock_segment], {})

        audio_data = b"fake audio data"
        # Explicitly enable VAD to test default parameters
        result = transcribe_audio(mock_model, audio_data, vad_filter=True)

        assert result == "Test"
        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["vad_filter"] is True
        assert call_kwargs["vad_parameters"] is not None
        assert call_kwargs["vad_parameters"]["threshold"] == 0.5
        assert call_kwargs["vad_parameters"]["min_speech_duration_ms"] == 250
        assert call_kwargs["vad_parameters"]["min_silence_duration_ms"] == 500
        assert call_kwargs["vad_parameters"]["speech_pad_ms"] == 400

    def test_transcribe_audio_vad_disabled_by_default(self):
        """Test that VAD is disabled by default for backward compatibility."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Test"
        mock_model.transcribe.return_value = ([mock_segment], {})

        audio_data = b"fake audio data"
        # Don't specify vad_filter, should default to False
        result = transcribe_audio(mock_model, audio_data)

        assert result == "Test"
        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["vad_filter"] is False

    def test_transcribe_audio_hallucination_prevention(self):
        """Test hallucination prevention thresholds."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Valid text"
        mock_model.transcribe.return_value = ([mock_segment], {})

        result = transcribe_audio(
            mock_model,
            b"audio",
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
        )

        assert result == "Valid text"
        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["compression_ratio_threshold"] == 2.4
        assert call_kwargs["log_prob_threshold"] == -1.0
        assert call_kwargs["no_speech_threshold"] == 0.6

    def test_transcribe_audio_with_initial_prompt(self):
        """Test transcription with initial prompt."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Technical content"
        mock_model.transcribe.return_value = ([mock_segment], {})

        result = transcribe_audio(
            mock_model, b"audio", initial_prompt="Technical discussion about Python and APIs."
        )

        assert result == "Technical content"
        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["initial_prompt"] == "Technical discussion about Python and APIs."

    def test_transcribe_audio_with_temperature(self):
        """Test transcription with temperature parameter."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Test"
        mock_model.transcribe.return_value = ([mock_segment], {})

        result = transcribe_audio(mock_model, b"audio", temperature=0.5)

        assert result == "Test"
        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5

    def test_transcribe_audio_with_word_timestamps(self):
        """Test transcription with word timestamps enabled."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Test"
        mock_model.transcribe.return_value = ([mock_segment], {})

        result = transcribe_audio(mock_model, b"audio", word_timestamps=True)

        assert result == "Test"
        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["word_timestamps"] is True

    def test_transcribe_audio_with_beam_size(self):
        """Test transcription with custom beam size."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Test"
        mock_model.transcribe.return_value = ([mock_segment], {})

        result = transcribe_audio(mock_model, b"audio", beam_size=10)

        assert result == "Test"
        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["beam_size"] == 10

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
