"""Model-related helpers shared between interfaces."""

from __future__ import annotations


def normalize_compute_type(device: str, compute_type: str) -> str:
    """Keep compute types compatible with the selected device."""

    ct = compute_type
    if device == "cpu" and "float16" in ct:
        ct = "int8"
    if device == "cuda" and ct in ("int8", "int8_float32", "float32"):
        ct = "float16"
    return ct
