"""Whisper transcription functionality."""

from faster_whisper import WhisperModel

from whisper_dictate.config import normalize_compute_type


class TranscriptionError(Exception):
    """Raised when transcription fails."""


def transcribe_audio(
    model: WhisperModel,
    audio: bytes | memoryview,
    beam_size: int = 5,
    language: str = "en",
    vad_filter: bool = False,
) -> str:
    """
    Transcribe audio using Whisper model.

    Args:
        model: Loaded WhisperModel instance
        audio: Audio data as numpy array or compatible format
        beam_size: Beam size for decoding
        language: Language code (default: "en")
        vad_filter: Whether to use VAD filtering

    Returns:
        Transcribed text

    Raises:
        TranscriptionError: If transcription fails
    """
    try:
        segments, info = model.transcribe(
            audio,
            beam_size=beam_size,
            vad_filter=vad_filter,
            language=language,
        )
        text = "".join(s.text for s in segments).strip()
        return text
    except Exception as e:
        raise TranscriptionError(f"Transcription failed: {e}") from e


def load_model(
    model_name: str,
    device: str,
    compute_type: str,
) -> WhisperModel:
    """
    Load a Whisper model with normalized compute type.

    Args:
        model_name: Model name (e.g., "small", "medium", "large-v3")
        device: Device ("cpu" or "cuda")
        compute_type: Compute type (will be normalized based on device)

    Returns:
        Loaded WhisperModel instance
    """
    normalized_compute = normalize_compute_type(device, compute_type)
    return WhisperModel(model_name, device=device, compute_type=normalized_compute)
