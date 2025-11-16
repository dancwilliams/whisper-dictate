"""Audio recording functionality."""

import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from whisper_dictate.config import CHUNK_MS, INPUT_CHANNELS, SAMPLE_RATE

# Global audio state
recording = False
audio_q: queue.Queue[np.ndarray] = queue.Queue()
audio_buf: list[np.ndarray] = []
buffer_lock = threading.Lock()
stream: Optional[sd.InputStream] = None


def audio_callback(indata: np.ndarray, frames: int, time_info: dict, status) -> None:
    """Callback for audio input stream."""
    if status:
        print("Audio status:", status)
    data = indata if indata.ndim == 1 else np.mean(indata, axis=1)
    audio_q.put_nowait(data.copy())


def recorder_loop() -> None:
    """Background thread that collects audio chunks from the queue."""
    while True:
        chunk = audio_q.get()
        with buffer_lock:
            audio_buf.append(chunk)


def start_recording(device: Optional[int] = None) -> None:
    """Start audio recording stream."""
    global stream, recording, audio_buf
    
    with buffer_lock:
        audio_buf = []
    
    stream = sd.InputStream(
        channels=INPUT_CHANNELS,
        samplerate=SAMPLE_RATE,
        dtype="float32",
        callback=audio_callback,
        blocksize=int(SAMPLE_RATE * (CHUNK_MS / 1000.0)),
        device=device,
    )
    stream.start()
    recording = True


def stop_recording() -> None:
    """Stop audio recording stream."""
    global stream, recording
    
    if stream:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        stream = None
    recording = False


def get_audio_buffer() -> Optional[np.ndarray]:
    """Get and clear the audio buffer. Returns None if empty."""
    with buffer_lock:
        if not audio_buf:
            return None
        audio = np.concatenate(audio_buf).astype(np.float32)
        audio_buf.clear()
        return audio


def is_recording() -> bool:
    """Check if currently recording."""
    return recording

