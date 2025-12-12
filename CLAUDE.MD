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
- **Classes:** PascalCase (e.g., `WhisperDictateGUI`)
- **Functions/variables:** snake_case (e.g., `get_active_window_info`)
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
| `config.py` | Configuration defaults, CUDA setup | `setup_cuda_path()`, model/device defaults |
| `app_context.py` | Active window detection (Windows API) | `get_active_window_info()`, `WindowInfo` |
| `prompt.py` | LLM prompt loading/saving | `load_prompt()`, `save_prompt()` |
| `app_prompts.py` | Per-application prompt resolution | `resolve_prompt()`, `AppPromptEntry` |
| `app_prompt_dialog.py` | GUI for per-app prompt management | `AppPromptDialog` |
| `audio.py` | Audio recording with sounddevice | `record_audio()` |
| `transcription.py` | Whisper model loading and transcription | `load_model()`, `transcribe()` |
| `llm_cleanup.py` | LLM text cleanup with OpenAI client | `cleanup_text()`, `fetch_available_models()` |
| `glossary.py` | Glossary persistence and application | `load_glossary()`, `apply_glossary()`, `GlossaryEntry` |
| `glossary_dialog.py` | GUI for glossary management | `GlossaryDialog` |
| `hotkeys.py` | Windows global hotkey registration | `register_global_hotkey()` |
| `gui_components.py` | Reusable GUI widgets | `LabeledEntry`, `LabeledText` |
| `logging_config.py` | Centralized logging setup | `setup_logging()` |
| `settings_store.py` | Settings persistence | `load_settings()`, `save_settings()` |
| `gui.py` | Main GUI application | `WhisperDictateGUI` |

### Data Flow

1. **User triggers hotkey** → `hotkeys.py` posts event to GUI
2. **GUI starts recording** → `audio.py` captures audio from selected device
3. **Audio transcribed** → `transcription.py` uses faster-whisper model
4. **Glossary applied** (optional) → `glossary.py` normalizes transcript
5. **LLM cleanup** (optional) → `llm_cleanup.py` sends to OpenAI-compatible endpoint
6. **Result displayed** and optionally auto-pasted via `pyautogui`/`pyperclip`

### Settings Structure

Settings are stored in `~/.whisper_dictate/whisper_dictate_settings.json`:

```json
{
  "model": "base",
  "device": "cuda",
  "compute_type": "int8_float16",
  "input_device": null,
  "hotkey": "ctrl+win+g",
  "llm_endpoint": "http://localhost:1234/v1",
  "llm_model": "gpt-3.5-turbo",
  "llm_api_key": "",
  "llm_temperature": 0.7,
  "llm_enabled": false,
  "auto_paste": false,
  "paste_delay": 0.15,
  "use_glossary": false,
  "app_prompts": [
    {
      "process_name": "winword.exe",
      "window_title_pattern": "",
      "prompt": "Format as professional business text..."
    }
  ],
  "floating_indicator": {
    "x": 100,
    "y": 100
  }
}
```

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
- Integration tests cover full pipelines (audio → transcription → LLM → paste)

### Mocking Guidelines
- Mock Windows APIs (`ctypes.windll`) in tests for cross-platform compatibility
- Mock `sounddevice`, `whisper`, and OpenAI client for unit tests
- Use `@pytest.fixture` for shared test setup
- Mock file I/O for settings/prompt tests

## Dependencies

### Core Dependencies
- `faster-whisper` — Whisper model inference
- `ctranslate2` — Backend for faster-whisper
- `nvidia-*` packages — CUDA runtime and cuDNN
- `openai` — LLM cleanup client
- `sounddevice` — Audio recording
- `pyautogui`, `pyperclip` — Auto-paste functionality
- `pillow` — GUI icons/images

### Dev Dependencies
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
- Main GUI class: `WhisperDictateGUI` in `gui.py`
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
USE_UV=1 make build-exe

# Direct PyInstaller
uv run pyinstaller packaging/pyinstaller/whisper_dictate_gui.spec --noconfirm
```

Output: `dist/whisper-dictate-gui/whisper-dictate-gui.exe`

The spec file bundles CUDA DLLs and all dependencies. See `docs/build.md` for details.

## Windows-Specific Considerations

### Windows APIs Used
- `ctypes.windll.user32` — Window management, hotkeys
- `ctypes.windll.kernel32` — Process information
- Native Win32 hotkey registration (VK codes, MOD flags)

### File Paths
- Settings directory: `~/.whisper_dictate/` (expands to `C:\Users\<username>\.whisper_dictate\`)
- Prompt file: `~/.whisper_dictate_prompt.txt`
- Glossary: `~/.whisper_dictate/whisper_dictate_glossary.json`
- Logs: `~/.whisper_dictate/logs/whisper_dictate.log`

### Threading
- GUI runs in main thread
- Audio recording in separate thread
- Hotkey callbacks use thread-safe event posting (`root.event_generate()`)

## Troubleshooting Common Issues

### CUDA/cuDNN Issues
- Ensure CUDA 12.4 and cuDNN 9.5 are installed
- `config.py` adds CUDA paths to system PATH
- Use CPU mode (`device="cpu"`, `compute_type="int8"`) as fallback

### Hotkey Not Working
- Must register from main GUI thread
- VK codes and MOD flags are Windows-specific
- Re-register after changing hotkey string

### Auto-Paste Not Working
- Ensure GUI doesn't have focus (trigger via hotkey, not button)
- Adjust paste delay if target app is slow
- Check Windows mic privacy settings

## Recent Changes

- **LLM usage statistics logging** (commit bdae6c7) — Logs token counts and model info
- **Comprehensive integration tests** (commit 454379e) — Full pipeline testing
- **Windows API tests for app_context** (commit 098390b) — Thorough testing of window detection
- **Recent window titles in app prompt dialog** (commit 9fbb13c) — Prefill recent apps

## Git Workflow

This project uses a worktree-based workflow:
- Main repository: `C:\Users\Dan Williams\git\whisper-dictate`
- Worktrees: `C:\Users\Dan Williams\.claude-worktrees\whisper-dictate\<branch-name>`
- Main branch: `main`
- Feature branches: descriptive names (e.g., `inspiring-curie`)

When creating PRs, target the `main` branch.

## Questions or Issues?

Refer to:
- `README.md` — User-facing documentation
- `docs/build.md` — Build instructions
- Test files in `tests/` — Usage examples
- Module docstrings — Implementation details
