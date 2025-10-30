"""Environment helpers shared by CLI and GUI entry points."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def set_cuda_paths() -> None:
    """Ensure CUDA DLL folders from embedded Nvidia wheels are on PATH."""

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        nvidia_base_path = Path(sys._MEIPASS) / "nvidia"
    else:
        venv_base = Path(sys.executable).resolve().parent.parent
        nvidia_base_path = venv_base / "Lib" / "site-packages" / "nvidia"

    cuda_dirs = [
        nvidia_base_path / "cuda_runtime" / "bin",
        nvidia_base_path / "cublas" / "bin",
        nvidia_base_path / "cudnn" / "bin",
    ]

    paths_to_add = [str(path) for path in cuda_dirs if path.exists()]
    if not paths_to_add:
        return

    env_vars = ["CUDA_PATH", "CUDA_PATH_V12_4", "PATH"]
    for env_var in env_vars:
        current_value = os.environ.get(env_var, "")
        new_value = os.pathsep.join(paths_to_add + [current_value] if current_value else paths_to_add)
        os.environ[env_var] = new_value


# Run on import so every interface benefits.
set_cuda_paths()
