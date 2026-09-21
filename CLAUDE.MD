# CLAUDE.MD

This file provides context about the Whisper Dictate project for AI assistants working with this codebase.

## Project Overview

Whisper Dictate is a privacy-first, local speech-to-text and AI cleanup tool for Windows. It uses faster-whisper for offline transcription and can optionally send text to an OpenAI-compatible endpoint for cleanup/rewriting.

**Key Technologies:**
- Python 3.11+
- faster-whisper (SYSTRAN) for local speech-to-text
- OpenAI API client for optional LLM cleanup
- tkinter for GUI
- PyInstaller for creating standalone executables
- CUDA 12.4 + cuDNN 9.5 for GPU acceleration

**Package Manager:** `uv` (Astral's fast Python package manager)

## Code Style and Conventions

### General Guidelines
- Line length: 100 characters (enforced by ruff)
- Python version: 3.11+
- Use type hints where practical (mypy configured but not strict)
- Keep solutions simple and focused - avoid over-engineering
- Don't add features, refactors, or "improvements" beyond what's requested

### Code Organization
- **Module-level organization:** Each module has a single, focused responsibility
- **Settings persistence:** All user settings stored in `~/.whisper_dictate/whisper_dictate_settings.json`
- **Logging:** Centralized in `logging_config.py` - logs to both console and `~/.whisper_dictate/logs/whisper_dictate.log`
- **Configuration:** CUDA paths and defaults in `config.py`

### Naming Conventions
- **Files:** lowercase with underscores (e.g., `app_context.py`)
- **Classes:** PascalCase (e.g., `AudioRecorder`)
- **Functions/variables:** snake_case (e.g., `get_active_context`)
- **Constants:** UPPER_SNAKE_CASE (e.g., `DEFAULT_MODEL`)

### Import Organization
Ruff enforces import sorting with the "I" rule:
1. Standard library imports
2. Third-party imports
3. Local application imports

## Architecture

### Core Modules

| Module | Purpose | Key Functions/Classes |
|--------|---------|----------------------|
| `config.py` | Configuration defaults, CUDA setup | `set_cuda_paths()`, `get_model_choices()`, model/device defaults |
| `app_context.py` | Active window detection (Windows API) | `get_active_context()`, `ActiveContext` |
| `prompt.py` | LLM prompt loading/saving | `load_saved_prompt()`, `write_saved_prompt()` |
| `app_prompts.py` | Per-application prompt resolution | `resolve_app_prompt()`, `normalize_app_prompts()` |
| `app_prompt_dialog.py` | GUI for per-app prompt management | `AppPromptDialog` |
| `audio.py` | Audio recording with sounddevice | `AudioRecorder` (`start()`, `stop()`, `get_buffer()`) |
| `transcription.py` | Whisper model loading and transcription | `load_model()`, `transcribe_audio()` |
| `asr.py` | Recognizer backends and GPU residency | `WhisperBackend`, `CohereBackend`, `Resident`, `load_backend()` |
| `llm_cleanup.py` | LLM text cleanup with OpenAI client | `clean_with_llm()`, `list_llm_models()` |
| `s1.py` | Built-in cleanup with S1-mini (llama.cpp) | `S1Cleaner`, `build_prompt()` |
| `glossary.py` | Glossary persistence, phonetic rules, per-app hotwords | `GlossaryManager`, `GlossaryRule`, `apply_glossary()`, `hotwords_for_app()` |
| `history.py` | Local dictation record and audio pruning | `record()`, `prune_audio()` |
| `glossary_dialog.py` | GUI for glossary management | `GlossaryDialog` |
| `hotkeys.py` | Windows global hotkey registration | `HotkeyManager`, `parse_chord()` |
| `clipboard.py` | Clipboard snapshot/restore (ctypes) | `snapshot()`, `restore()`, `set_text()` |
| `gui_components.py` | Reusable GUI widgets | `PromptDialog`, `StatusIndicator` |
| `logging_config.py` | Centralized logging setup | `setup_logging()` |
| `settings_store.py` | Settings persistence | `load_settings()`, `save_settings()` |
| `gui.py` | Main GUI application | `App`, `main()` |

### Data Flow

1. **User triggers hotkey** → `hotkeys.py` posts event to GUI
2. **GUI starts recording** → `audio.py` captures audio from selected device
3. **Audio transcribed** → `transcription.py` uses faster-whisper model
4. **Glossary applied** (optional) → `glossary.py` normalizes transcript
5. **LLM cleanup** (optional) → `llm_cleanup.py` sends to OpenAI-compatible endpoint
6. **Result displayed**, clipboard snapshotted, text set, pasted with Shift+Insert (`SendInput`), clipboard restored

### Settings Structure

Settings are stored in `~/.whisper_dictate/whisper_dictate_settings.json`:

```json
{
  "model": "small",
  "asr_backend": "whisper",
  "idle_ttl_minutes": 5.0,
  "history_enable": true,
  "history_audio_days": 14,
  "device": "cuda",
  "compute": "float16",
  "input": "",
  "hotkey": "CTRL+SPACE",
  "auto_paste": true,
  "paste_delay": 0.15,
  "restore_delay": 0.6,
  "cleanup_backend": "s1",
  "s1_styling": "semi-casual",
  "s1_structure": "prose",
  "s1_context": "general",
  "llm_endpoint": "http://localhost:1234/v1",
  "llm_model": "openai/gpt-oss-20b",
  "llm_temp": 0.1,
  "llm_debug": false,
  "glossary_enable": true,
  "auto_load_model": false,
  "auto_register_hotkey": false,
  "app_prompts": {
    "winword.exe": [
      {
        "prompt": "Format as professional business text...",
        "window_title_regex": "Quarterly"
      }
    ]
  },
  "recent_processes": ["winword.exe", "notepad.exe"],
  "vad_enabled": false,
  "vad_threshold": 0.5,
  "vad_min_speech_ms": 250,
  "vad_min_silence_ms": 500,
  "vad_speech_pad_ms": 400,
  "compression_ratio_threshold": 2.4,
  "log_prob_threshold": -1.0,
  "no_speech_threshold": 0.6,
  "temperature": 0.0,
  "beam_size": 5,
  "initial_prompt": "",
  "indicator_position": { "x": 100, "y": 100 }
}
```

The API key (`llm_key` in `_save_settings`) is never written to this file;
`settings_store` moves it to Windows Credential Manager. A rule in `app_prompts` may
also carry the S1 style keys (`styling`, `structure`, `context`).

## Testing

### Test Organization
- Tests located in `tests/` directory
- Each module has corresponding `test_*.py` file
- Naming: `test_<module_name>.py`

### Running Tests Locally
```powershell
# Run all tests
make test

# Run all tests with coverage
make test-coverage

# Run specific test file
uv run pytest tests/test_app_context.py

# Run all quality checks (CI equivalent)
make check
```

### Continuous Integration
- CI runs on every push to `main` and all pull requests
- Workflow: `.github/workflows/ci.yml`
- Jobs: lint (ruff), typecheck (mypy), test (pytest on Python 3.11/3.12/3.13)
- All jobs must pass for PR to be considered ready

### Running CI Checks Locally
```powershell
# Run exactly what CI runs
make check

# Or individually
make lint          # Ruff linting
make format-check  # Ruff formatting verification
make typecheck     # Mypy type checking
make test          # Pytest test suite
```

### Test Configuration
- pytest.ini options in `pyproject.toml`
- Coverage target: `whisper_dictate` package
- pytest-mock for mocking Windows APIs and external dependencies
- `test_integration.py` covers context, prompts, glossary and cleanup; `test_gui_pipeline.py` covers the dictation pipeline and delivery

### Mocking Guidelines
- Mock Windows APIs (`ctypes.windll`) in tests for cross-platform compatibility
- Mock `sounddevice`, `whisper`, and OpenAI client for unit tests
- Use `@pytest.fixture` for shared test setup
- Mock file I/O for settings/prompt tests

## Dependencies

### Core Dependencies
- `faster-whisper` — Whisper model inference
- `ctranslate2` — Backend for faster-whisper (transitive; not pinned here)
- `nvidia-*` packages — CUDA runtime and cuDNN
- `openai` — LLM cleanup client
- `sounddevice` — Audio recording
- `clipboard.py` — Clipboard and auto-paste (Shift+Insert), ctypes only; no pyautogui/pyperclip

### Dev Dependencies
Declared in the `dev` [dependency group](https://peps.python.org/pep-0735/), not an extra;
`uv sync` installs it by default (there is no `--all-extras` to pass).
- `pytest`, `pytest-cov`, `pytest-mock` — Testing
- `ruff` — Linting and formatting
- `mypy` — Type checking
- `pyinstaller` — Executable creation

## Common Tasks

### Adding a New Feature
1. Create/update module in `whisper_dictate/`
2. Add corresponding tests in `tests/test_<module>.py`
3. Update settings schema if adding user-configurable options
4. Update GUI if exposing to user
5. Update README.md with usage instructions
6. Run tests: `uv run pytest`

### Modifying GUI
- Main GUI class: `App` in `gui.py`
- Reusable components in `gui_components.py`
- Use tkinter best practices (grid layout, proper event handling)
- Test with Windows scaling/DPI settings

### Adding LLM Statistics
LLM usage is logged with token counts and timing:
```python
logger.info(
    "LLM cleanup completed",
    extra={
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "model": response.model
    }
)
```

### Working with Settings
```python
from whisper_dictate.settings_store import load_settings, save_settings

settings = load_settings()
settings["new_key"] = "new_value"
save_settings(settings)
```

## Building

### Create Standalone EXE
```powershell
# Using Makefile (recommended)
make build-exe

# Direct PyInstaller
uv run pyinstaller packaging/pyinstaller/whisper_dictate_gui.spec --noconfirm
```

Output: `dist/whisper-dictate-gui.exe` (one-file build)

The spec file bundles CUDA DLLs and all dependencies. See `docs/build.md` for details.

## Windows-Specific Considerations

### Windows APIs Used
- `ctypes.windll.user32` — Window management, hotkeys
- `ctypes.windll.kernel32` — Process information
- Native Win32 hotkey registration (VK codes, MOD flags)

### File Paths
- Settings directory: `~/.whisper_dictate/` (expands to `C:\Users\<username>\.whisper_dictate\`)
- Prompt file: `~/.whisper_dictate/whisper_dictate_prompt.txt`
- Glossary: `~/.whisper_dictate/whisper_dictate_glossary.json`
- Logs: `~/.whisper_dictate/logs/whisper_dictate.log`

### Threading
- GUI runs in main thread
- Audio recording in separate thread
- Hotkey callbacks are marshalled to the Tk thread with `after(0, ...)`
- Transcription, cleanup and delivery run on a worker that reads a settings snapshot and never touches Tk

## Troubleshooting Common Issues

### CUDA/cuDNN Issues
- Ensure CUDA 12.4 and cuDNN 9.5 are installed
- `config.py` adds CUDA paths to system PATH
- Use CPU mode (`device="cpu"`, `compute_type="int8"`) as fallback

### Hotkey Not Working
- The keyboard hook and its message pump live on one background thread; Tk work is marshalled back with `after(0, ...)`
- VK codes are Windows-specific; left/right modifier variants collapse to one name
- Changing the chord in Settings -> Automation re-registers when that window closes

### Auto-Paste Not Working
- Ensure GUI doesn't have focus (trigger via hotkey, not button)
- Adjust paste delay if target app is slow
- Check Windows mic privacy settings

## Git Workflow

This project uses a worktree-based workflow:
- Main repository: `C:\Users\Dan Williams\git\whisper-dictate`
- Worktrees: `C:\Users\Dan Williams\.claude-worktrees\whisper-dictate\<branch-name>`
- Main branch: `main`
- Feature branches: descriptive names (e.g., `inspiring-curie`)

When creating PRs, target the `main` branch.

Attribution: none. Commits and PRs carry no AI or assistant attribution. Adopted 2026-09-21; earlier history is left as is.

## Questions or Issues?

Refer to:
- `README.md` — User-facing documentation
- `docs/startup.md` — Running at login, the pill menu, single-instance behaviour
- `docs/build.md` — Build instructions
- Test files in `tests/` — Usage examples
- Module docstrings — Implementation details
