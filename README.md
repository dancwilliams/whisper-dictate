# Whisper Dictate

[![CI](https://github.com/dancwilliams/whisper-dictate/actions/workflows/ci.yml/badge.svg)](https://github.com/dancwilliams/whisper-dictate/actions/workflows/ci.yml)

A privacy-first, local **speech-to-text and AI cleanup tool** for Windows.  
It uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) for offline transcription and can optionally send text to a local or remote **OpenAI-compatible endpoint** (such as [Ollama](https://ollama.com/)) for light cleanup or rewriting.  
It supports a **GUI**, global hotkeys, and automatic pasting into the active window.

---

## ✨ Features

- **100% local transcription** — audio never leaves your machine (models are downloaded once from Hugging Face; see [Security & Privacy](#-security--privacy))
- **Secure credential storage** — API keys encrypted in Windows Credential Manager
- **Optional LLM cleanup** via an OpenAI-style endpoint (Ollama, or any OpenAI-compatible server)
- **Glossary injection** to enforce product names, jargon, or key phrases during normalization and LLM cleanup
- **Prompt editor** (Edit → Prompt…) with your changes saved to `~/.whisper_dictate/whisper_dictate_prompt.txt`
- **Per-application prompts** so you can override the cleanup prompt per app or window title (Edit → Per-app prompts…)
- **Glossary editor** (Edit → Glossary…) with add/edit/delete controls, CSV import/export, and entries saved to
  `~/.whisper_dictate/whisper_dictate_glossary.json`
- **Saves your settings** (model, device, hotkey, LLM config, paste delay) to `~/.whisper_dictate/whisper_dictate_settings.json`
- **Advanced transcription settings** including VAD, hallucination prevention, beam size, temperature, and initial prompts
- **Global hotkey** for push-to-talk from any application
- **Auto-paste** into the focused window (`Shift+Insert`), with a configurable delay
- **Fetch available LLM models** from your endpoint directly inside the LLM settings window
- **Floating status indicator** that mirrors the app state (idle, listening, cleaning, etc.)
- **Reset floating status indicator** button if you drag the indicator off screen
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

* Model/device selection with resource requirements displayed for each model
* Auto-configured compute type based on your device (CUDA→float16, CPU→int8)
* Input-device field
* Optional LLM cleanup section (endpoint, model, API key, temperature, and system prompt)
* **Auto-paste** checkbox and delay setting
* Transcript view with timestamped results

Use **Load model**, then **Register hotkey** (e.g., `CTRL+WIN+G`), and press the hotkey anywhere to dictate.
If "Auto-paste" is enabled, the result pastes automatically into the app you were using.

### 3. Configure (optional)

- **Edit → Prompt…** to customize the cleanup prompt (persisted to `~/.whisper_dictate/whisper_dictate_prompt.txt`).
- **Edit → Per-app prompts…** to override the cleanup prompt for specific processes (e.g., `winword.exe`, `notion.exe`).
  Use the **recent apps** dropdown to prefill entries with the last windows you dictated into, and optionally add a window-title
  regex to scope a prompt to a particular document or channel. These rules are persisted to
  `~/.whisper_dictate/whisper_dictate_settings.json`.
- **Edit → Glossary…** to maintain glossary entries (persisted to `~/.whisper_dictate/whisper_dictate_glossary.json`).
- **Settings → Speech recognition…** to pick your device (CPU/CUDA) and model. Models display their size and resource requirements (e.g., "Small (465 MB, ~2 GB VRAM)"), and the optimal compute type is auto-configured based on your device selection.
- **Settings → Advanced transcription…** to fine-tune VAD (Voice Activity Detection), hallucination prevention thresholds, beam size, temperature, and initial prompts. See [docs/transcription-optimization.md](docs/transcription-optimization.md) for detailed guidance.
- **Settings → Automation…** to set the global hotkey, enable auto-paste, and tune the paste delay.
- **Settings → LLM cleanup…** to toggle cleanup, set endpoint/model/API key, refresh available models, and adjust temperature.
  Use **Use glossary before prompt** to normalize transcripts with your glossary and prepend the rules to the LLM system prompt so it honors your terminology.
All settings are saved to `~/.whisper_dictate/whisper_dictate_settings.json` when you close the app.

---

## 🎯 Per-Application Prompts

Per-application prompts let you tailor cleanup instructions to the active app or window:

1. Open **Edit → Per-app prompts…**.
2. Pick a **Recent app** to prefill the process name, or add a process manually.
3. Optionally set a **Window title regex** to target a specific document, chat, or channel.
4. Enter the **Prompt override** for that app/window.

When dictating, Whisper Dictate detects the active process/window and applies the most specific matching prompt before
sending text to the LLM cleanup step. Clear entries to fall back to the global prompt.

---

## 🪄 Auto-Paste Behavior

When the **Auto-paste** checkbox (GUI) is enabled:

1. The final text is copied to the clipboard.
2. After a short delay (default 0.15 s), `Shift + Insert` is sent to the active window, and your previous clipboard is restored.

If you toggle recording from inside Word, Notion, VS Code, or a chat window, the cleaned text appears directly where your cursor is.

> Tip: Trigger the hotkey, don't click the GUI button — clicking steals focus and will paste into the GUI itself.

If you move the floating status indicator off-screen, use **Settings → Reset status indicator position** to snap it back to the
default location.

---

## 📒 Glossary-Driven Cleanup

Use the glossary to keep acronyms, brand names, or domain-specific terms intact during normalization and LLM cleanup:

- Open **Edit → Glossary…** and add entries as trigger/replacement pairs using the glossary manager.
- Each rule supports **Match** (word, phrase, regex), **Case sensitive**, and **Whole words only** to fine-tune how
  replacements are applied. Use **Add**, **Edit**, or **Delete** to maintain the list, or **Import CSV** / **Export CSV** to
  bulk-manage rules. An optional description can remind you why a term matters.
- Entries are saved to `~/.whisper_dictate/whisper_dictate_glossary.json` and loaded automatically on startup.
- In **Settings → LLM cleanup…**, enable **Use glossary before prompt** to apply the glossary to transcripts and prepend the
  rules to the LLM system prompt so it takes priority over the general cleanup prompt.

Glossary usage is optional; turn it off from **Settings → LLM cleanup…** if you only want the standard prompt applied.

---

## 🧩 Project Layout

```
whisper-dictate/
│
├─ whisper_dictate/
│   ├─ __init__.py           # Package initialization
│   ├─ config.py             # Configuration defaults and CUDA setup
│   ├─ app_context.py        # Active-window context (process and title)
│   ├─ prompt.py             # LLM prompt management (load/save)
│   ├─ app_prompts.py        # Per-application prompt resolution helpers
│   ├─ app_prompt_dialog.py  # GUI dialog for managing per-app prompt overrides
│   ├─ audio.py              # Audio recording functionality
│   ├─ transcription.py      # Whisper transcription logic
│   ├─ llm_cleanup.py        # LLM text cleanup functionality
│   ├─ glossary.py           # Glossary persistence used during LLM cleanup
│   ├─ glossary_dialog.py    # GUI dialog for managing glossary rules
│   ├─ hotkeys.py            # Windows global hotkey management
│   ├─ gui_components.py     # Reusable GUI components
│   ├─ logging_config.py     # Centralized logging setup
│   ├─ settings_store.py     # Persistent settings load/save helpers
│   └─ gui.py                # Main GUI application
│
├─ tests/                    # Comprehensive test suite
│   ├─ test_app_context.py
│   ├─ test_app_prompts.py
│   ├─ test_config.py
│   ├─ test_prompt.py
│   ├─ test_hotkeys.py
│   ├─ test_llm_cleanup.py
│   ├─ test_glossary.py
│   ├─ test_transcription.py
│   └─ test_audio.py
│
├─ pyproject.toml
└─ README.md
```

---

## 🧪 Development

`make` is optional. On Windows, `winget install ezwinports.make` provides it. Without it, run what the targets run:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy whisper_dictate
uv run pytest
```

### Running Tests

```powershell
# Run all tests
make test
```

### Code Quality Checks

```powershell
# Run all checks (lint, format, typecheck, test)
make check

# Run individual checks
make lint
make format-check
make typecheck

# Auto-fix issues
make fix
```

### Available Make Targets

Run `make help` to see all available targets.

### Testing

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

## 📚 Documentation

For developers and contributors:

- **[Architecture Documentation](docs/architecture.md)** — System architecture diagrams, data flow, module responsibilities, and design patterns
- **[Starting at Login](docs/startup.md)** — Startup shortcut, the floating pill's menu, and what to check when nothing appears
- **[CLAUDE.md](CLAUDE.md)** — AI assistant context and development guidelines
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Contribution guidelines and coding standards
- **[CHANGELOG.md](CHANGELOG.md)** — Project history and release notes

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

## 🛠 Troubleshooting

| Symptom                      | Cause                           | Fix                                    |
| ---------------------------- | ------------------------------- | -------------------------------------- |
| Hotkey not working           | Registered from wrong thread    | Fixed in latest build; re-register it  |
| `cudnn_ops64_9.dll missing`  | cuDNN not installed             | Install cuDNN v9 and add to PATH       |
| `int8_float16 not supported` | CPU mode only                   | Use `--compute-type int8`              |
| Nothing pastes               | GUI has focus                   | Trigger with hotkey from target window |
| Audio errors                 | Mic blocked by privacy settings | Enable mic access for desktop apps     |

---

## 🔒 Security & Privacy

### Credential Storage
- **API keys are encrypted** using Windows Credential Manager (via `keyring` library)
- Credentials are **tied to your user account** and encrypted by the operating system
- API keys are **never stored in plaintext** JSON files
- **Automatic migration**: Existing plaintext API keys are automatically migrated to secure storage on first run
- **Removing a key**: blank the API key in Settings → LLM cleanup and the app deletes it from Credential Manager. Removing it by hand instead, delete every entry whose target contains `WhisperDictate`: `keyring` sometimes keeps a second one named `llm_api_key@WhisperDictate`

### Debug Mode Warning
- When debug logging is enabled, **transcribed speech, prompts and the active window title are logged to disk**
- Use debug mode only when troubleshooting, not for regular use
- The GUI displays a prominent warning when debug mode is active

### Privacy-First Design
- All transcription happens **100% locally** — your audio is never sent anywhere
- LLM cleanup is optional. The built-in S1-mini cleanup runs locally; endpoint cleanup sends the transcript to the endpoint you configure
- Your data never leaves your machine unless you point endpoint cleanup at a remote server

### Network Use
- **Model downloads**: the first time you use a recognizer or the built-in S1-mini cleanup, its model is downloaded from [Hugging Face](https://huggingface.co/) into `~/.cache/huggingface`. Only the model files come down; nothing of yours goes up.
- **After that**: the Cohere recognizer and S1-mini load straight from the cache and make no network request. faster-whisper asks Hugging Face whether the cached Whisper model is current when a connection is available, and uses the cache when it is not.
- **Cohere recognizer**: the model is gated, so it needs a Hugging Face token in `~/.cache/huggingface/token` for that first download.
- **With no network at all**: everything works once the models are cached, as long as cleanup is off, built-in, or pointed at a local endpoint (such as Ollama).

---

## 📝 Logging

Logs are written to both:
- **Console** (stderr) — for immediate feedback
- **File** (`~/.whisper_dictate/logs/whisper_dictate.log`) — for debugging

Log levels include DEBUG, INFO, WARNING, and ERROR with timestamps and context.

---

**Enjoy local, AI-enhanced dictation — fast, private, and cloud-free.**
