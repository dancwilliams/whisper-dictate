"""Tests for configuration module."""

import os
from unittest.mock import MagicMock, patch

from whisper_dictate.config import (
    DEFAULT_AUTO_LOAD_MODEL,
    DEFAULT_AUTO_REGISTER_HOTKEY,
    DEFAULT_COMPUTE,
    DEFAULT_DEVICE,
    DEFAULT_LLM_ENDPOINT,
    DEFAULT_LLM_KEY,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMP,
    DEFAULT_MODEL,
    DEVICE_COMPUTE_DEFAULTS,
    MODEL_INFO,
    get_model_choices,
    get_model_display_name,
    normalize_compute_type,
    set_cuda_paths,
)


class TestConfig:
    """Test configuration defaults and functions."""

    def test_defaults_exist(self):
        """Test that all default values are defined."""
        assert DEFAULT_MODEL is not None
        assert DEFAULT_DEVICE in ("cpu", "cuda")
        assert DEFAULT_COMPUTE is not None
        assert DEFAULT_LLM_ENDPOINT is not None
        assert DEFAULT_LLM_MODEL is not None
        assert DEFAULT_LLM_KEY is not None
        assert DEFAULT_LLM_TEMP is not None

    def test_normalize_compute_type_cpu(self):
        """Test compute type normalization for CPU."""
        assert normalize_compute_type("cpu", "float16") == "int8"
        assert normalize_compute_type("cpu", "int8") == "int8"
        assert normalize_compute_type("cpu", "float32") == "float32"

    def test_normalize_compute_type_cuda(self):
        """Test compute type normalization for CUDA."""
        assert normalize_compute_type("cuda", "int8") == "float16"
        assert normalize_compute_type("cuda", "int8_float32") == "float16"
        assert normalize_compute_type("cuda", "float32") == "float16"
        assert normalize_compute_type("cuda", "float16") == "float16"
        assert normalize_compute_type("cuda", "int8_float16") == "int8_float16"

    def test_auto_startup_defaults(self):
        """Test that auto-startup defaults are defined and False by default."""
        assert DEFAULT_AUTO_LOAD_MODEL is False
        assert DEFAULT_AUTO_REGISTER_HOTKEY is False


class TestSetCudaPaths:
    """Test CUDA path configuration.

    The contract: every CUDA directory from the nvidia wheels goes on PATH and
    is registered with os.add_dll_directory. CUDA_PATH is set only when it would
    name a real toolkit root - one with both bin and lib - because consumers
    append to it. llama-cpp-python does add_dll_directory on CUDA_PATH/bin and
    CUDA_PATH/lib at import and raises if either is missing, so a list of
    directories there, or a root without lib, stops it loading at all.
    """

    def _wheel_layout(self, base):
        for part in ("cuda_runtime", "cublas", "cudnn"):
            (base / part / "bin").mkdir(parents=True)
        return base

    def _dev_sys(self, tmp_path):
        mock_sys = MagicMock()
        venv_python = tmp_path / "venv" / "Scripts" / "python.exe"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()
        mock_sys.executable = str(venv_python)
        return mock_sys

    def test_development_layout(self, tmp_path, monkeypatch):
        base = self._wheel_layout(tmp_path / "venv" / "Lib" / "site-packages" / "nvidia")
        original_path = os.environ.get("PATH", "")
        with patch("whisper_dictate.config.sys", self._dev_sys(tmp_path)):
            monkeypatch.delenv("CUDA_PATH", raising=False)
            with patch("whisper_dictate.config.os.add_dll_directory"):
                set_cuda_paths()
            assert str(base / "cublas" / "bin") in os.environ["PATH"]
        os.environ["PATH"] = original_path

    def test_cuda_path_is_left_alone_for_the_wheel_layout(self, tmp_path, monkeypatch):
        """The pip wheels have no toolkit root: cuda_runtime ships bin, not lib."""
        self._wheel_layout(tmp_path / "venv" / "Lib" / "site-packages" / "nvidia")
        original_path = os.environ.get("PATH", "")
        with patch("whisper_dictate.config.sys", self._dev_sys(tmp_path)):
            monkeypatch.delenv("CUDA_PATH", raising=False)
            with patch("whisper_dictate.config.os.add_dll_directory"):
                set_cuda_paths()
            assert "CUDA_PATH" not in os.environ
        os.environ["PATH"] = original_path

    def test_cuda_path_names_a_real_toolkit_root(self, tmp_path, monkeypatch):
        base = self._wheel_layout(tmp_path / "venv" / "Lib" / "site-packages" / "nvidia")
        (base / "cuda_runtime" / "lib").mkdir()  # now it looks like a toolkit
        original_path = os.environ.get("PATH", "")
        with patch("whisper_dictate.config.sys", self._dev_sys(tmp_path)):
            monkeypatch.delenv("CUDA_PATH", raising=False)
            with patch("whisper_dictate.config.os.add_dll_directory"):
                set_cuda_paths()
            # One directory, not a list: os.add_dll_directory would reject a list.
            assert os.environ["CUDA_PATH"] == str(base / "cuda_runtime")
            assert os.pathsep not in os.environ["CUDA_PATH"]
            assert os.environ["CUDA_PATH_V12_4"] == str(base / "cuda_runtime")
        monkeypatch.delenv("CUDA_PATH", raising=False)
        monkeypatch.delenv("CUDA_PATH_V12_4", raising=False)
        os.environ["PATH"] = original_path

    def test_existing_path_is_preserved(self, tmp_path, monkeypatch):
        self._wheel_layout(tmp_path / "venv" / "Lib" / "site-packages" / "nvidia")
        with patch("whisper_dictate.config.sys", self._dev_sys(tmp_path)):
            monkeypatch.setenv("PATH", r"C:\somewhere\else")
            with patch("whisper_dictate.config.os.add_dll_directory"):
                set_cuda_paths()
            assert r"C:\somewhere\else" in os.environ["PATH"]

    def test_no_nvidia_directories_is_a_no_op(self, tmp_path, monkeypatch):
        with patch("whisper_dictate.config.sys", self._dev_sys(tmp_path)):
            monkeypatch.delenv("CUDA_PATH", raising=False)
            with patch("whisper_dictate.config.os.add_dll_directory") as add:
                set_cuda_paths()
            add.assert_not_called()
            assert "CUDA_PATH" not in os.environ


class TestModelInfo:
    """Tests for MODEL_INFO and related functions."""

    def test_model_info_contains_expected_models(self):
        """MODEL_INFO should contain all supported models."""
        expected_models = ["tiny.en", "base.en", "small", "medium", "large-v3", "large-v3-turbo"]
        for model in expected_models:
            assert model in MODEL_INFO

    def test_model_info_has_required_fields(self):
        """Each model entry should have required fields."""
        required_fields = ["display_name", "disk_mb", "vram_gb", "ram_gb", "speed", "description"]
        for model_id, info in MODEL_INFO.items():
            for field in required_fields:
                assert field in info, f"Model {model_id} missing field {field}"

    def test_get_model_display_name_cuda(self):
        """Display name for CUDA should show VRAM."""
        name = get_model_display_name("small", "cuda")
        assert "Small" in name
        assert "VRAM" in name
        assert "465 MB" in name or "0.5 GB" in name  # disk size

    def test_get_model_display_name_cpu(self):
        """Display name for CPU should show RAM."""
        name = get_model_display_name("small", "cpu")
        assert "Small" in name
        assert "RAM" in name

    def test_get_model_display_name_unknown_model(self):
        """Unknown model should return model_id unchanged."""
        name = get_model_display_name("unknown-model", "cuda")
        assert name == "unknown-model"

    def test_get_model_choices_returns_all_models(self):
        """get_model_choices should return all models."""
        choices = get_model_choices("cuda")
        assert len(choices) == len(MODEL_INFO)
        for model_id, display in choices:
            assert model_id in MODEL_INFO
            assert display != model_id  # Should be formatted

    def test_device_compute_defaults(self):
        """DEVICE_COMPUTE_DEFAULTS should have entries for cpu and cuda."""
        assert "cpu" in DEVICE_COMPUTE_DEFAULTS
        assert "cuda" in DEVICE_COMPUTE_DEFAULTS
        assert DEVICE_COMPUTE_DEFAULTS["cpu"] == "int8"
        assert DEVICE_COMPUTE_DEFAULTS["cuda"] == "float16"
