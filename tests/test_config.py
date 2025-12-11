"""Tests for configuration module."""

import os
from unittest.mock import MagicMock, patch

from whisper_dictate.config import (
    DEFAULT_AUTO_LOAD_MODEL,
    DEFAULT_AUTO_REGISTER_HOTKEY,
    DEFAULT_COMPUTE,
    DEFAULT_DEVICE,
    DEFAULT_LLM_ENABLED,
    DEFAULT_LLM_ENDPOINT,
    DEFAULT_LLM_KEY,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMP,
    DEFAULT_MODEL,
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
        assert DEFAULT_LLM_ENABLED is not None
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
    """Test CUDA path configuration."""

    def test_set_cuda_paths_frozen_app(self, tmp_path, monkeypatch):
        """Test CUDA path setup for frozen (PyInstaller) application."""
        # Mock frozen application environment

        mock_sys = MagicMock()
        mock_sys.frozen = True
        mock_sys._MEIPASS = str(tmp_path)
        mock_sys.executable = "/fake/path/python.exe"

        # Create mock CUDA directories
        nvidia_base = tmp_path / "nvidia"
        cuda_runtime_bin = nvidia_base / "cuda_runtime" / "bin"
        cublas_bin = nvidia_base / "cublas" / "bin"
        cudnn_bin = nvidia_base / "cudnn" / "bin"

        cuda_runtime_bin.mkdir(parents=True)
        cublas_bin.mkdir(parents=True)
        cudnn_bin.mkdir(parents=True)

        with patch("whisper_dictate.config.sys", mock_sys):
            # Clear environment variables
            monkeypatch.delenv("CUDA_PATH", raising=False)
            monkeypatch.delenv("CUDA_PATH_V12_4", raising=False)
            original_path = os.environ.get("PATH", "")

            set_cuda_paths()

            # Verify paths were added to environment
            assert "CUDA_PATH" in os.environ
            assert str(cuda_runtime_bin) in os.environ["CUDA_PATH"]
            assert str(cublas_bin) in os.environ["CUDA_PATH"]
            assert str(cudnn_bin) in os.environ["CUDA_PATH"]

            assert "CUDA_PATH_V12_4" in os.environ
            assert str(cuda_runtime_bin) in os.environ["CUDA_PATH_V12_4"]

            assert "PATH" in os.environ
            assert str(cuda_runtime_bin) in os.environ["PATH"]

            # Restore PATH
            os.environ["PATH"] = original_path

    def test_set_cuda_paths_development(self, tmp_path, monkeypatch):
        """Test CUDA path setup for development environment."""

        mock_sys = MagicMock()
        mock_sys.frozen = False
        # Mock sys.executable to point to our temp venv
        venv_python = tmp_path / "venv" / "Scripts" / "python.exe"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()
        mock_sys.executable = str(venv_python)

        # Create mock CUDA directories in venv site-packages
        nvidia_base = tmp_path / "venv" / "Lib" / "site-packages" / "nvidia"
        cuda_runtime_bin = nvidia_base / "cuda_runtime" / "bin"
        cublas_bin = nvidia_base / "cublas" / "bin"
        cudnn_bin = nvidia_base / "cudnn" / "bin"

        cuda_runtime_bin.mkdir(parents=True)
        cublas_bin.mkdir(parents=True)
        cudnn_bin.mkdir(parents=True)

        with patch("whisper_dictate.config.sys", mock_sys):
            # Clear environment variables
            monkeypatch.delenv("CUDA_PATH", raising=False)
            monkeypatch.delenv("CUDA_PATH_V12_4", raising=False)
            original_path = os.environ.get("PATH", "")

            set_cuda_paths()

            # Verify paths were added
            assert "CUDA_PATH" in os.environ
            assert str(cuda_runtime_bin) in os.environ["CUDA_PATH"]

            # Restore PATH
            os.environ["PATH"] = original_path

    def test_set_cuda_paths_no_directories(self, tmp_path, monkeypatch):
        """Test CUDA path setup when directories don't exist."""

        mock_sys = MagicMock()
        mock_sys.frozen = False
        venv_python = tmp_path / "venv" / "Scripts" / "python.exe"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()
        mock_sys.executable = str(venv_python)

        # Don't create CUDA directories

        with patch("whisper_dictate.config.sys", mock_sys):
            original_cuda_path = os.environ.get("CUDA_PATH", "")
            original_path = os.environ.get("PATH", "")

            set_cuda_paths()

            # Environment should be unchanged (or minimally changed)
            # The function should return early if no CUDA paths exist
            # We just verify it doesn't crash

            # Restore environment
            if original_cuda_path:
                os.environ["CUDA_PATH"] = original_cuda_path
            elif "CUDA_PATH" in os.environ:
                del os.environ["CUDA_PATH"]
            os.environ["PATH"] = original_path

    def test_set_cuda_paths_preserves_existing_env(self, tmp_path, monkeypatch):
        """Test that set_cuda_paths preserves existing environment variables."""

        mock_sys = MagicMock()
        mock_sys.frozen = False
        venv_python = tmp_path / "venv" / "Scripts" / "python.exe"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()
        mock_sys.executable = str(venv_python)

        # Create mock CUDA directories
        nvidia_base = tmp_path / "venv" / "Lib" / "site-packages" / "nvidia"
        cuda_runtime_bin = nvidia_base / "cuda_runtime" / "bin"
        cuda_runtime_bin.mkdir(parents=True)

        with patch("whisper_dictate.config.sys", mock_sys):
            # Set existing environment values
            original_cuda = "C:\\existing\\cuda\\path"
            monkeypatch.setenv("CUDA_PATH", original_cuda)
            original_path = os.environ.get("PATH", "")

            set_cuda_paths()

            # Verify original value is preserved
            assert original_cuda in os.environ["CUDA_PATH"]
            # New path should also be present
            assert str(cuda_runtime_bin) in os.environ["CUDA_PATH"]

            # Restore PATH
            os.environ["PATH"] = original_path

