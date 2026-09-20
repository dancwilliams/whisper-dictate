"""Tests for the ASR backends and GPU residency."""

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from whisper_dictate import asr
from whisper_dictate.asr import CohereBackend, Resident, WhisperBackend, load_backend


class TestWhisperBackend:
    @patch("whisper_dictate.asr.transcription")
    def test_forwards_hotwords_and_kwargs(self, mock_transcription):
        mock_transcription.transcribe_audio.return_value = "hello"
        backend = WhisperBackend("large-v3-turbo", "cuda", "float16")
        audio = np.zeros(16000, dtype=np.float32)

        assert backend.transcribe(audio, hotwords="Traefik", beam_size=3) == "hello"

        _args, kwargs = mock_transcription.transcribe_audio.call_args
        assert kwargs["hotwords"] == "Traefik"
        assert kwargs["beam_size"] == 3


class TestCohereBackend:
    def _install(self, monkeypatch, generated="the transcript"):
        """Stand in for torch and transformers at the import site."""
        torch = MagicMock()
        torch.bfloat16 = "bfloat16"

        processor = MagicMock()
        feature = MagicMock()
        feature.is_floating_point.return_value = True
        feature.to.return_value = "features-on-cuda"
        processor.return_value = {"input_features": feature}
        processor.batch_decode.return_value = [f"  {generated}  "]

        transformers = MagicMock()
        transformers.AutoProcessor.from_pretrained.return_value = processor
        model = transformers.CohereAsrForConditionalGeneration.from_pretrained.return_value
        model.to.return_value.eval.return_value = MagicMock()

        monkeypatch.setitem(__import__("sys").modules, "torch", torch)
        monkeypatch.setitem(__import__("sys").modules, "transformers", transformers)
        return torch, processor, feature

    def test_transcribes_and_strips(self, monkeypatch):
        _torch, processor, _feature = self._install(monkeypatch)
        backend = CohereBackend()
        assert backend.transcribe(np.zeros(16000, dtype=np.float32)) == "the transcript"
        # The processor takes the language positionally; without it, it raises.
        args, kwargs = processor.call_args
        assert args[1] == "en"
        assert kwargs["sampling_rate"] == 16000

    def test_float_features_are_cast_to_the_model_dtype(self, monkeypatch):
        """Float32 features into a bfloat16 model raise inside conv2d."""
        torch, _processor, feature = self._install(monkeypatch)
        CohereBackend().transcribe(np.zeros(16000, dtype=np.float32))
        feature.to.assert_called_once_with("cuda", torch.bfloat16)

    def test_integer_inputs_keep_their_dtype(self, monkeypatch):
        _torch, processor, _feature = self._install(monkeypatch)
        ids = MagicMock()
        ids.is_floating_point.return_value = False
        processor.return_value = {"input_ids": ids}
        CohereBackend().transcribe(np.zeros(16000, dtype=np.float32))
        ids.to.assert_called_once_with("cuda")

    def test_hotwords_are_ignored(self, monkeypatch):
        """The model has no vocabulary biasing API; accepting the argument and
        dropping it keeps one call signature across backends."""
        self._install(monkeypatch)
        backend = CohereBackend()
        assert backend.transcribe(np.zeros(10, dtype=np.float32), hotwords="Traefik") == (
            "the transcript"
        )


class TestLoadBackend:
    @patch("whisper_dictate.asr.WhisperBackend")
    def test_cohere_import_failure_falls_back_with_a_warning(self, mock_whisper, monkeypatch):
        monkeypatch.setattr(asr, "CohereBackend", MagicMock(side_effect=ImportError("no torch")))
        warnings = []
        result = load_backend(
            "cohere", "large-v3-turbo", "cuda", "float16", on_warning=warnings.append
        )
        assert result is mock_whisper.return_value
        assert warnings and "Cohere" in warnings[0]

    @patch("whisper_dictate.asr.WhisperBackend")
    def test_missing_token_is_an_oserror_and_falls_back(self, mock_whisper, monkeypatch):
        monkeypatch.setattr(asr, "CohereBackend", MagicMock(side_effect=OSError("gated")))
        warnings = []
        load_backend("cohere", "large-v3-turbo", "cuda", "float16", on_warning=warnings.append)
        assert warnings and "Cohere" in warnings[0]
        mock_whisper.assert_called_once()

    @patch("whisper_dictate.asr.WhisperBackend")
    def test_unknown_backend_warns_and_uses_whisper(self, mock_whisper):
        warnings = []
        load_backend("parakeet", "large-v3-turbo", "cuda", "float16", on_warning=warnings.append)
        assert warnings and "Unknown" in warnings[0]
        mock_whisper.assert_called_once()

    @patch("whisper_dictate.asr.WhisperBackend")
    def test_whisper_is_built_with_the_given_settings(self, mock_whisper):
        load_backend("whisper", "small", "cpu", "int8")
        mock_whisper.assert_called_once_with("small", "cpu", "int8")


class TestResident:
    def test_warm_then_get_returns_the_object(self):
        resident = Resident(lambda: "model", ttl=0)
        resident.warm()
        assert resident.get() == "model"

    def test_second_get_does_not_reload(self):
        calls = []
        resident = Resident(lambda: calls.append(1) or "model", ttl=0)
        resident.get()
        resident.get()
        assert len(calls) == 1

    def test_warm_during_a_load_does_not_start_a_second(self):
        calls = []
        started = threading.Event()

        def slow():
            calls.append(1)
            started.set()
            time.sleep(0.2)
            return "model"

        resident = Resident(slow, ttl=0)
        resident.warm()
        started.wait(1.0)
        resident.warm()
        resident.warm()
        assert resident.get() == "model"
        assert len(calls) == 1

    def test_expiry_drops_it_and_the_next_get_reloads(self):
        calls = []
        resident = Resident(lambda: calls.append(1) or "model", ttl=0.05)
        resident.get()
        assert resident.is_loaded() is True

        deadline = time.monotonic() + 2.0
        while resident.is_loaded() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert resident.is_loaded() is False

        assert resident.get() == "model"
        assert len(calls) == 2

    def test_ttl_zero_never_expires(self):
        resident = Resident(lambda: "model", ttl=0)
        resident.get()
        time.sleep(0.1)
        assert resident.is_loaded() is True

    def test_get_raises_what_the_factory_raised(self):
        resident = Resident(MagicMock(side_effect=RuntimeError("no CUDA")), ttl=0)
        with pytest.raises(RuntimeError, match="no CUDA"):
            resident.get()

    def test_a_failed_load_can_be_retried(self):
        """A transient CUDA failure must not poison the rest of the session."""
        outcomes = [RuntimeError("busy"), "model"]

        def factory():
            result = outcomes.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        resident = Resident(factory, ttl=0)
        with pytest.raises(RuntimeError):
            resident.get()
        resident.release()
        assert resident.get() == "model"

    def test_release_is_safe_when_nothing_is_loaded(self):
        Resident(lambda: "model", ttl=0).release()

    @patch("whisper_dictate.asr._free_gpu_memory")
    def test_release_frees_gpu_memory_only_when_something_was_held(self, mock_free):
        resident = Resident(lambda: "model", ttl=0)
        resident.release()
        mock_free.assert_not_called()

        resident.get()
        resident.release()
        mock_free.assert_called_once()


def test_free_gpu_memory_does_not_import_torch(monkeypatch):
    """Freeing memory must not drag torch into a process running Whisper only."""
    import sys

    monkeypatch.delitem(sys.modules, "torch", raising=False)
    asr._free_gpu_memory()
    assert "torch" not in sys.modules
