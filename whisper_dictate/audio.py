"""Audio recording functionality."""

import logging
import queue
import threading
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from whisper_dictate.config import CHUNK_MS, INPUT_CHANNELS, SAMPLE_RATE

logger = logging.getLogger("whisper_dictate")


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
        self._on_first_audio: Callable[[], None] | None = None

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: dict, status) -> None:
        """Callback for audio input stream."""
        if status:
            logger.warning(f"Audio status: {status}")
        # The first block is the only honest moment to say "listening": the device
        # takes a few hundred ms to open, and a cue before that lies.
        if self._on_first_audio is not None:
            callback, self._on_first_audio = self._on_first_audio, None
            callback()
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
                self._audio_queue.task_done()
            except queue.Empty:
                continue

    def start(
        self, device: int | None = None, on_first_audio: Callable[[], None] | None = None
    ) -> None:
        """
        Start audio recording.

        Args:
            device: Audio input device ID (None for default)
            on_first_audio: Called once, from the audio thread, on the first block
                of this recording - the moment capture is actually live.
        """
        # Clear existing buffer
        with self._buffer_lock:
            self._audio_buffer = []
        self._on_first_audio = on_first_audio

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
        # The stream is closed, so nothing more is coming. Wait for the collector
        # to move what is queued, or get_buffer() misses the end of the utterance.
        # Only while it is alive: join() has no timeout and this is the Tk thread.
        if self._recorder_thread and self._recorder_thread.is_alive():
            self._audio_queue.join()
        self._recording = False

    def prewarm(self, device: int | None = None) -> None:
        """Open and close one input stream so the first real press is not a cold open.

        Measured on this machine: 577 ms to the first callback cold, ~264 ms warm.
        Failure is not worth reporting - the next start() will raise properly.
        """
        try:
            stream = sd.InputStream(
                channels=self.channels,
                samplerate=self.sample_rate,
                dtype="float32",
                device=device,
            )
            stream.close()
        except (sd.PortAudioError, RuntimeError, ValueError):
            pass

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
