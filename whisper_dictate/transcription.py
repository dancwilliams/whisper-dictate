"""Whisper transcription functionality."""

from typing import Any

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
    vad_parameters: dict[str, Any] | None = None,
    compression_ratio_threshold: float = 2.4,
    log_prob_threshold: float = -1.0,
    no_speech_threshold: float = 0.6,
    word_timestamps: bool = False,
    temperature: float | list[float] = 0.0,
    initial_prompt: str | None = None,
    condition_on_previous_text: bool = True,
) -> str:
    """
    Transcribe audio using Whisper model with VAD and hallucination prevention.

    Args:
        model: Loaded WhisperModel instance
        audio: Audio data as numpy array or compatible format
        beam_size: Beam size for decoding (default: 5)
        language: Language code (default: "en")
        vad_filter: Whether to use VAD filtering (default: False)
        vad_parameters: Custom VAD parameters (default: optimal settings)
        compression_ratio_threshold: Detect repetitive hallucinations (default: 2.4)
        log_prob_threshold: Filter low-confidence segments (default: -1.0)
        no_speech_threshold: Detect silence/non-speech (default: 0.6)
        word_timestamps: Enable word-level timestamps (default: False)
        temperature: Temperature for sampling (default: 0.0 for deterministic)
        initial_prompt: Optional prompt for context/style
        condition_on_previous_text: Use previous text for context (default: True)

    Returns:
        Transcribed text

    Raises:
        TranscriptionError: If transcription fails
    """
    try:
        # Default VAD parameters if not provided
        if vad_filter and vad_parameters is None:
            vad_parameters = {
                "threshold": 0.5,
                "min_speech_duration_ms": 250,
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 400,
            }

        segments, info = model.transcribe(
            audio,
            beam_size=beam_size,
            vad_filter=vad_filter,
            vad_parameters=vad_parameters,
            language=language,
            compression_ratio_threshold=compression_ratio_threshold,
            log_prob_threshold=log_prob_threshold,
            no_speech_threshold=no_speech_threshold,
            word_timestamps=word_timestamps,
            temperature=temperature,
            initial_prompt=initial_prompt,
            condition_on_previous_text=condition_on_previous_text,
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
