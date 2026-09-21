"""Speech recognition backends and their residency on the GPU.

Two recognizers behind one `transcribe(audio, hotwords=None, **kwargs)` call, and
a `Resident` that loads either one lazily and frees it again after an idle
period - the GPU is shared with Ollama, Higgs and ComfyUI, so holding weights
for the life of the process is not neighbourly.

torch and transformers are imported inside CohereBackend, not at module import,
so a machine without them still runs the Whisper path.
"""

from __future__ import annotations

import gc
import logging
import sys
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

from whisper_dictate import transcription

logger = logging.getLogger("whisper_dictate")

SAMPLE_RATE = 16000
BACKENDS = ("whisper", "cohere")


class WhisperBackend:
    """faster-whisper. Supports hotword biasing."""

    def __init__(self, model_name: str, device: str, compute_type: str):
        self.model = transcription.load_model(model_name, device, compute_type)

    def transcribe(self, audio: np.ndarray, hotwords: str | None = None, **kwargs: Any) -> str:
        return transcription.transcribe_audio(self.model, audio, hotwords=hotwords, **kwargs)


class CohereBackend:
    """CohereLabs/cohere-transcribe-03-2026.

    Gated: needs a Hugging Face token in ~/.cache/huggingface/token. There is no
    documented vocabulary biasing API, so hotwords are ignored.
    """

    MODEL_ID = "CohereLabs/cohere-transcribe-03-2026"

    def __init__(self, device: str = "cuda"):
        import torch
        from transformers import AutoProcessor, CohereAsrForConditionalGeneration

        self._torch = torch
        self.device = device
        # Load from the local cache first. transformers otherwise asks Hugging
        # Face for metadata on every load, cached or not, so a flaky connection
        # downgrades the recognizer - measured, as an httpx.RemoteProtocolError.
        # Only reach for the network when the weights are genuinely not here.
        try:
            self.processor = AutoProcessor.from_pretrained(self.MODEL_ID, local_files_only=True)
            model = CohereAsrForConditionalGeneration.from_pretrained(
                self.MODEL_ID, dtype=torch.bfloat16, local_files_only=True
            )
        except OSError:
            logger.info("Cohere weights are not cached; downloading")
            self.processor = AutoProcessor.from_pretrained(self.MODEL_ID)
            model = CohereAsrForConditionalGeneration.from_pretrained(
                self.MODEL_ID, dtype=torch.bfloat16
            )
        self.model = model.to(device).eval()  # type: ignore[arg-type]

    def _place(self, value: Any) -> Any:
        if not hasattr(value, "to"):
            return value
        # Float features must match the model dtype; token ids must stay integral.
        if value.is_floating_point():
            return value.to(self.device, self._torch.bfloat16)
        return value.to(self.device)

    def transcribe(self, audio: np.ndarray, hotwords: str | None = None, **_: Any) -> str:
        inputs = self.processor(audio, "en", sampling_rate=SAMPLE_RATE, return_tensors="pt")
        inputs = {k: self._place(v) for k, v in inputs.items()}
        with self._torch.inference_mode():
            ids = self.model.generate(**inputs, max_new_tokens=448)
        return str(self.processor.batch_decode(ids, skip_special_tokens=True)[0]).strip()


def load_backend(
    name: str,
    model_name: str,
    device: str,
    compute_type: str,
    on_warning: Callable[[str], None] | None = None,
) -> WhisperBackend | CohereBackend:
    """Build a backend, falling back to the other one if it cannot be had.

    A missing torch, a revoked HF token or a CUDA refusal should cost the user a
    warning and a different recognizer, not a dictation.
    """

    def warn(message: str) -> None:
        logger.warning(message)
        if on_warning:
            on_warning(message)

    if name == "cohere":
        try:
            return CohereBackend(device if device != "cpu" else "cpu")
        except (ImportError, OSError, RuntimeError, ValueError) as e:
            # The type alone says nothing: OSError covers a missing token, a
            # locked cache and a full disk alike.
            logger.warning("Cohere backend failed to load", exc_info=True)
            warn(f"Cohere unavailable ({type(e).__name__}: {e}); using Whisper"[:200])
    elif name != "whisper":
        warn(f"Unknown ASR backend {name!r}; using Whisper")
    return WhisperBackend(model_name, device, compute_type)


class Resident:
    """Holds one lazily loaded object and frees it after `ttl` seconds idle.

    Used for both the recognizer and the cleanup model: each is several GB on a
    GPU shared with other tenants, and most of the day neither is wanted.

    Every release() bumps a generation; a load that finishes under a different
    generation from the one it started in is discarded and built again.
    """

    def __init__(self, factory: Callable[[], Any], ttl: float):
        self.factory = factory
        self.ttl = ttl
        self._lock = threading.Lock()
        self._settled = threading.Event()
        self._obj: Any = None
        self._loading = False
        self._generation = 0
        self._error: BaseException | None = None
        self._timer: threading.Timer | None = None

    def is_loaded(self) -> bool:
        with self._lock:
            return self._obj is not None

    def warm(self) -> None:
        """Start loading on a thread if cold. Returns immediately.

        Called on the hotkey press so the model loads while the user is still
        speaking: the perceived wait is max(0, load - utterance).
        """
        with self._lock:
            if self._obj is not None or self._loading:
                return
            self._loading = True
            self._error = None
            self._settled.clear()
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        while True:
            with self._lock:
                generation = self._generation
            error: BaseException | None = None
            obj: Any = None
            try:
                obj = self.factory()
            except BaseException as e:  # reported to whoever calls get()
                error = e
            with self._lock:
                if generation == self._generation:
                    self._obj, self._error, self._loading = obj, error, False
                    break
            # Released while we were building: what we hold was made from settings
            # that have since changed. Drop it and build again.
            del obj
            _free_gpu_memory()
        self._settled.set()
        if error is None:
            self._restart_timer()

    def get(self) -> Any:
        """Block until the object is loaded, and reset the idle timer.

        Raises:
            Whatever the factory raised.
        """
        while True:
            self.warm()
            self._settled.wait()
            with self._lock:
                error, obj = self._error, self._obj
            if error is not None:
                raise error
            if obj is not None:
                break
            # Released between the wait and the lock; go round and load again.
        self._restart_timer()
        return obj

    def release(self) -> None:
        """Drop the object now."""
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            had = self._obj is not None
            self._obj = None
            self._generation += 1
            # Only a load in flight will set the event again. With none, leave it
            # set: a get() already waiting wakes, finds nothing, and reloads.
            if self._loading:
                self._settled.clear()
        if had:
            _free_gpu_memory()

    def _restart_timer(self) -> None:
        if not self.ttl:  # 0 means never unload
            return
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.ttl, self._expire)
            self._timer.daemon = True
            self._timer.start()

    def _expire(self) -> None:
        logger.info(f"Releasing {self.factory} after {self.ttl}s idle")
        self.release()


def _free_gpu_memory() -> None:
    """Return the weights to the GPU. The CUDA context itself stays for the life
    of the process - a few hundred MB that no amount of collecting recovers."""
    gc.collect()
    torch = sys.modules.get("torch")  # never import torch just to free memory
    if torch is not None:
        try:
            torch.cuda.empty_cache()
        except (RuntimeError, AssertionError):
            pass
