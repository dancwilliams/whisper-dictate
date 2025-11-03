# Windows build and release process

This project ships a standalone Windows executable generated with [PyInstaller](https://pyinstaller.org/en/stable/). The build is reproducible either via GitHub Actions or locally. This document explains the moving pieces so future releases stay consistent.

## Overview of the tooling

* **Packaging** – [`packaging/pyinstaller/whisper_dictate_gui.spec`](../packaging/pyinstaller/whisper_dictate_gui.spec) drives the PyInstaller build. It pulls in the GUI entry point, bundles the Tk assets, and collects CUDA DLLs from the `nvidia-*` wheels so the executable runs on machines without CUDA installed.
* **Model prefetch** – [`scripts/prefetch_model.py`](../scripts/prefetch_model.py) warms the Hugging Face cache by instantiating `faster-whisper.WhisperModel`. Prefetching guarantees that PyInstaller has access to the model artifacts during the build and avoids first-run downloads for end users.
* **Developer shortcut** – The project root includes a [`Makefile`](../Makefile) with `prefetch-model` and `build-exe` targets to mirror the automated pipeline.
* **Continuous build** – The GitHub Actions workflow [`build-windows.yml`](../.github/workflows/build-windows.yml) runs on demand to produce a signed `.exe`, store it as an artifact, and (optionally) timestamp the signature.

## Local build steps

1. **Create and activate a Python 3.11 virtual environment.** PyInstaller is listed as a project dependency, so installing the package brings in the build tooling:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   pip install .
   ```
2. **Prefetch the Whisper model.** By default the GUI expects the `small` model. You can override the model size, compute type, or cache location. When `--device cuda` is used the helper automatically switches to `float16` precision to match the GUI defaults:
   ```bash
   make prefetch-model MODEL=small DEVICE=cpu COMPUTE_TYPE=int8_float32
   # or run: python scripts/prefetch_model.py --model small --device cpu --compute-type int8_float32
   ```
   The script prints the resolved cache directory so you can verify the download.
3. **Build the executable.** The PyInstaller spec writes the output to `dist/whisper-dictate-gui/` and includes the GUI icon plus CUDA DLLs. Running the default target produces `whisper-dictate-gui.exe`:
   ```bash
   make build-exe
   # which expands to: pyinstaller packaging/pyinstaller/whisper_dictate_gui.spec --noconfirm
   ```
4. **Code signing (optional).** Use `signtool.exe` on Windows with your `.pfx` certificate and timestamp service:
   ```powershell
   signtool sign /fd sha256 /f path\to\certificate.pfx /p <password> \
     /tr http://timestamp.digicert.com /td sha256 dist\whisper-dictate-gui\whisper-dictate-gui.exe
   ```
5. **Artifacts.** Ship the entire `dist/whisper-dictate-gui/` folder (the executable requires the bundled DLLs).

## Automated GitHub Actions build

Trigger **Build Windows executable** from the *Actions* tab. The workflow accepts three inputs:

| Input | Default | Purpose |
| --- | --- | --- |
| `model` | `small` | Whisper model to prefetch before packaging |
| `device` | `cpu` | Device used during prefetch (use `cuda` on GPU runners) |
| `compute_type` | `int8_float32` | Compute type passed to `WhisperModel` |

Key workflow steps:

1. **Checkout and install** – Uses `actions/setup-python` (3.11) and `pip install .` to grab dependencies including PyInstaller and the CUDA-enabled wheels.
2. **Model prefetch** – Calls `python scripts/prefetch_model.py ...` so the build reuses the cached Whisper weights.
3. **PyInstaller build** – Runs `pyinstaller packaging/pyinstaller/whisper_dictate_gui.spec --noconfirm` to produce `dist/whisper-dictate-gui/`.
4. **Code signing** – If the following repository secrets are defined, the workflow signs the executable and applies an RFC 3161 timestamp:
   * `WINDOWS_SIGNING_CERTIFICATE`: Base64-encoded `.pfx` file.
   * `WINDOWS_SIGNING_PASSWORD`: Password protecting the certificate.
   * `WINDOWS_TIMESTAMP_URL`: Optional timestamp authority URL (leave empty to skip).
5. **Artifact upload** – Publishes the `dist/whisper-dictate-gui/` directory as a workflow artifact named `whisper-dictate-gui`.

## Troubleshooting tips

* If PyInstaller omits a dependency, add it to `hiddenimports` in the spec file.
* When changing CUDA wheel versions, verify the directory layout under `Lib/site-packages/nvidia/` and update the spec helper if necessary.
* Large models (> `medium`) can exceed GitHub’s default runner disk quota; prefer building locally or on a self-hosted runner for those cases.
* Remove cached models with `rmdir /s %USERPROFILE%\.cache\huggingface` (Windows) or `rm -rf ~/.cache/huggingface` (Unix) before retrying a clean build.
