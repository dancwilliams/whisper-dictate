"""Audio recording functionality."""

import queue
import threading

import numpy as np
import sounddevice as sd

from whisper_dictate.config import CHUNK_MS, INPUT_CHANNELS, SAMPLE_RATE


class AudioRecorder:
    """Manages audio recording with background buffering."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        channels: int = INPUT_CHANNELS,
        chunk_ms: float = CHUNK_MS,
    ):
        """
        Initialize the audio recorder.

        Args:
            sample_rate: Sample rate in Hz (default: from config)
            channels: Number of input channels (default: from config)
            chunk_ms: Chunk size in milliseconds (default: from config)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_ms = chunk_ms

        self._recording = False
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._audio_buffer: list[np.ndarray] = []
        self._buffer_lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._recorder_thread: threading.Thread | None = None
        self._stop_recorder = threading.Event()

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: dict, status) -> None:
        """Callback for audio input stream."""
        if status:
            print("Audio status:", status)
        # Convert to mono if necessary
        data = indata if indata.ndim == 1 else np.mean(indata, axis=1)
        self._audio_queue.put_nowait(data.copy())

    def _recorder_loop(self) -> None:
        """Background thread that collects audio chunks from the queue."""
        while not self._stop_recorder.is_set():
            try:
                # Use timeout to allow checking stop flag
                chunk = self._audio_queue.get(timeout=0.1)
                with self._buffer_lock:
                    self._audio_buffer.append(chunk)
            except queue.Empty:
                continue

    def start(self, device: int | None = None) -> None:
        """
        Start audio recording.

        Args:
            device: Audio input device ID (None for default)
        """
        # Clear existing buffer
        with self._buffer_lock:
            self._audio_buffer = []

        # Start recorder thread if not already running
        if self._recorder_thread is None or not self._recorder_thread.is_alive():
            self._stop_recorder.clear()
            self._recorder_thread = threading.Thread(target=self._recorder_loop, daemon=True)
            self._recorder_thread.start()

        # Create and start audio stream
        self._stream = sd.InputStream(
            channels=self.channels,
            samplerate=self.sample_rate,
            dtype="float32",
            callback=self._audio_callback,
            blocksize=int(self.sample_rate * (self.chunk_ms / 1000.0)),
            device=device,
        )
        self._stream.start()
        self._recording = True

    def stop(self) -> None:
        """Stop audio recording."""
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except (sd.PortAudioError, RuntimeError, AttributeError):
                # PortAudioError: PortAudio/sounddevice errors
                # RuntimeError: Stream already closed or invalid state
                # AttributeError: Stream object is invalid
                pass
            self._stream = None
        self._recording = False

    def get_buffer(self) -> np.ndarray | None:
        """
        Get and clear the audio buffer.

        Returns:
            Concatenated audio data, or None if buffer is empty
        """
        with self._buffer_lock:
            if not self._audio_buffer:
                return None
            audio = np.concatenate(self._audio_buffer).astype(np.float32)
            self._audio_buffer.clear()
            return audio

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording

    def shutdown(self) -> None:
        """Shutdown the recorder and cleanup resources."""
        self.stop()
        self._stop_recorder.set()
        if self._recorder_thread and self._recorder_thread.is_alive():
            self._recorder_thread.join(timeout=1.0)


# Global singleton instance for backward compatibility
_default_recorder: AudioRecorder | None = None
_recorder_lock = threading.Lock()


def get_default_recorder() -> AudioRecorder:
    """Get or create the default global audio recorder instance."""
    global _default_recorder
    with _recorder_lock:
        if _default_recorder is None:
            _default_recorder = AudioRecorder()
        return _default_recorder


# Backward compatibility functions
def start_recording(device: int | None = None) -> None:
    """Start audio recording (backward compatibility wrapper)."""
    get_default_recorder().start(device)


def stop_recording() -> None:
    """Stop audio recording (backward compatibility wrapper)."""
    get_default_recorder().stop()


def get_audio_buffer() -> np.ndarray | None:
    """Get and clear audio buffer (backward compatibility wrapper)."""
    return get_default_recorder().get_buffer()


def is_recording() -> bool:
    """Check if recording (backward compatibility wrapper)."""
    return get_default_recorder().is_recording()


def recorder_loop() -> None:
    """Legacy function - recorder thread is now managed internally."""
    # This function is kept for backward compatibility but does nothing
    # The recorder thread is automatically started when recording begins
    pass
