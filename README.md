# Whisper Dictate

A privacy-first, local **speech-to-text and AI cleanup tool** for Windows.  
It uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) for offline transcription and can optionally send text to a local or remote **OpenAI-compatible endpoint** (such as [LM Studio](https://lmstudio.ai/)) for light cleanup or rewriting.  
It supports a **GUI**, global hotkeys, and automatic pasting into the active window.

---

## ✨ Features

- **100% local transcription** — no cloud calls
- **Optional LLM cleanup** via an OpenAI-style endpoint (LM Studio, Ollama, etc.)
- **Prompt editor** (Edit → Prompt…) with your changes saved to `~/.whisper_dictate_prompt.txt`
- **Saves your settings** (model, device, hotkey, LLM config, paste delay) to `~/.whisper_dictate/whisper_dictate_settings.json`
- **Global hotkey** for push-to-talk from any application
- **Auto-paste** into the focused window (`Ctrl+V`), with a configurable delay
- **Fetch available LLM models** from your endpoint directly inside the LLM settings window
- **Floating status indicator** that mirrors the app state (idle, listening, cleaning, etc.)
- **GPU or CPU** execution
- **One-command setup** using [`uv`](https://docs.astral.sh/uv/)
- **Comprehensive test suite** with coverage reporting
- **Structured logging** to file and console

---

## 🚀 Quick Start

### 1. Clone and install

```powershell
git clone https://github.com/yourusername/whisper-dictate.git
cd whisper-dictate
uv sync
```

### 2. Run (GUI)

```powershell
uv run dictate-gui
```

The GUI provides:

* Model/device selection
* Input-device field
* Optional LLM cleanup section (endpoint, model, API key, temperature, and system prompt)
* **Auto-paste** checkbox and delay setting
* Transcript view with timestamped results

Use **Load model**, then **Register hotkey** (e.g., `CTRL+WIN+G`), and press the hotkey anywhere to dictate.
If "Auto-paste" is enabled, the result pastes automatically into the app you were using.

### 3. Configure (optional)

- **Edit → Prompt…** to customize the cleanup prompt (persisted to `~/.whisper_dictate_prompt.txt`).
- **Settings → Speech recognition…** to pick model/device, compute type, and input device (use **List…** to view inputs).
- **Settings → Automation…** to set the global hotkey, enable auto-paste, and tune the paste delay.
- **Settings → LLM cleanup…** to toggle cleanup, set endpoint/model/API key, refresh available models, and adjust temperature.
  All settings are saved to `~/.whisper_dictate/whisper_dictate_settings.json` when you close the app.

---

## 🪄 Auto-Paste Behavior

When the **Auto-paste** checkbox (GUI) is enabled:

1. The final text is copied to the clipboard.
2. After a short delay (default 0.15 s), `Ctrl + V` is sent to the active window.

If you toggle recording from inside Word, Notion, VS Code, or a chat window, the cleaned text appears directly where your cursor is.

> Tip: Trigger the hotkey, don't click the GUI button — clicking steals focus and will paste into the GUI itself.

---

## 🧩 Project Layout

```
whisper-dictate/
│
├─ whisper_dictate/
│   ├─ __init__.py           # Package initialization
│   ├─ config.py             # Configuration defaults and CUDA setup
│   ├─ prompt.py             # LLM prompt management (load/save)
│   ├─ audio.py              # Audio recording functionality
│   ├─ transcription.py      # Whisper transcription logic
│   ├─ llm_cleanup.py        # LLM text cleanup functionality
│   ├─ hotkeys.py            # Windows global hotkey management
│   ├─ gui_components.py     # Reusable GUI components
│   ├─ logging_config.py     # Centralized logging setup
│   ├─ settings_store.py     # Persistent settings load/save helpers
│   └─ gui.py                # Main GUI application
│
├─ tests/                    # Comprehensive test suite
│   ├─ test_config.py
│   ├─ test_prompt.py
│   ├─ test_hotkeys.py
│   ├─ test_llm_cleanup.py
│   ├─ test_transcription.py
│   └─ test_audio.py
│
├─ packaging/
│   └─ pyinstaller/
│       └─ whisper_dictate_gui.spec  # PyInstaller build spec
│
├─ pyproject.toml
└─ README.md
```

---

## 🧪 Testing

Run the test suite with coverage:

```powershell
uv sync --dev
uv run pytest
```

Generate HTML coverage report:

```powershell
uv run pytest --cov=whisper_dictate --cov-report=html
```

---

## 🧾 Deployment on Another Machine

```powershell
git clone https://github.com/yourusername/whisper-dictate.git
cd whisper-dictate
uv sync
uv run dictate-gui
```

If you want to freeze dependency versions for reproducibility:

```powershell
uv lock
uv sync --locked
```

---

## 📦 Create an EXE

Build a standalone Windows executable using the PyInstaller spec:

```powershell
# Using the Makefile (recommended)
USE_UV=1 make build-exe

# Or directly with PyInstaller
uv run pyinstaller packaging/pyinstaller/whisper_dictate_gui.spec --noconfirm
```

The executable will be created in `dist/whisper-dictate-gui/` with all required CUDA DLLs bundled. See [`docs/build.md`](docs/build.md) for detailed build instructions.

---

## 🛠 Troubleshooting

| Symptom                      | Cause                           | Fix                                    |
| ---------------------------- | ------------------------------- | -------------------------------------- |
| Hotkey not working           | Registered from wrong thread    | Fixed in latest build; re-register it  |
| `cudnn_ops64_9.dll missing`  | cuDNN not installed             | Install cuDNN v9 and add to PATH       |
| `int8_float16 not supported` | CPU mode only                   | Use `--compute-type int8`              |
| Nothing pastes               | GUI has focus                   | Trigger with hotkey from target window |
| Audio errors                 | Mic blocked by privacy settings | Enable mic access for desktop apps     |

---

## 📝 Logging

Logs are written to both:
- **Console** (stderr) — for immediate feedback
- **File** (`~/.whisper_dictate/logs/whisper_dictate.log`) — for debugging

Log levels include DEBUG, INFO, WARNING, and ERROR with timestamps and context.

---

**Enjoy local, AI-enhanced dictation — fast, private, and cloud-free.**
