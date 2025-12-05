"""Tests for configuration module."""


from whisper_dictate.config import (
    DEFAULT_COMPUTE,
    DEFAULT_DEVICE,
    DEFAULT_LLM_ENABLED,
    DEFAULT_LLM_ENDPOINT,
    DEFAULT_LLM_KEY,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMP,
    DEFAULT_MODEL,
    normalize_compute_type,
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

