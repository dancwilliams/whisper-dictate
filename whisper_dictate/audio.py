"""Audio capture utilities shared between CLI and GUI."""

from __future__ import annotations

import queue
import threading
import sys
from typing import Optional

import numpy as np
import sounddevice as sd

from .constants import CHUNK_MS, INPUT_CHANNELS, SAMPLE_RATE


class AudioRecorder:
    """Collect audio chunks on a background thread and expose full buffers."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        input_channels: int = INPUT_CHANNELS,
        chunk_ms: int = CHUNK_MS,
    ) -> None:
        self.sample_rate = sample_rate
        self.input_channels = input_channels
        self.chunk_ms = chunk_ms

        self._audio_q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._audio_buf: list[np.ndarray] = []
        self._buffer_lock = threading.Lock()
        self._stream: Optional[sd.InputStream] = None
        self._recording = False

        threading.Thread(target=self._recorder_loop, daemon=True).start()

    # Public API ---------------------------------------------------------
    def start(self) -> None:
        """Start capturing audio from the default input device."""

        with self._buffer_lock:
            self._audio_buf = []

        blocksize = int(self.sample_rate * (self.chunk_ms / 1000.0))
        self._stream = sd.InputStream(
            channels=self.input_channels,
            samplerate=self.sample_rate,
            dtype="float32",
            callback=self._audio_cb,
            blocksize=blocksize,
        )
        self._stream.start()
        self._recording = True

    def stop(self) -> Optional[np.ndarray]:
        """Stop capturing and return the recorded audio as a float32 array."""

        if not self._recording:
            return None

        assert self._stream is not None
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._recording = False

        with self._buffer_lock:
            if not self._audio_buf:
                return None
            audio = np.concatenate(self._audio_buf).astype(np.float32)
            self._audio_buf = []
            return audio

    @property
    def is_recording(self) -> bool:
        return self._recording

    # Internal helpers ---------------------------------------------------
    def _audio_cb(self, indata, frames, time_info, status) -> None:  # pragma: no cover - callback signature defined by sounddevice
        if status:
            print("Audio status:", status, file=sys.stderr)
        data = indata if indata.ndim == 1 else np.mean(indata, axis=1)
        self._audio_q.put_nowait(data.copy())

    def _recorder_loop(self) -> None:
        while True:
            chunk = self._audio_q.get()
            with self._buffer_lock:
                self._audio_buf.append(chunk)


def configure_input_device(input_device: Optional[str]) -> None:
    """Configure the sounddevice default input according to user preference."""

    if not input_device:
        return

    try:
        sd.default.device = (int(input_device), None)
        return
    except ValueError:
        pass

    devices = sd.query_devices()
    matches = [i for i, device in enumerate(devices) if input_device.lower() in device["name"].lower()]
    if not matches:
        raise RuntimeError(f"Input device not found: {input_device}")

    sd.default.device = (matches[0], None)
