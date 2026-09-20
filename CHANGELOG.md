# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Selectable ASR backend with idle unloading (`asr.py`)
  - `WhisperBackend` (faster-whisper, supports hotwords) and `CohereBackend`
    (CohereLabs/cohere-transcribe-03-2026, gated, no vocabulary biasing)
  - `Resident` loads either lazily, warms on the hotkey press so the model loads
    while you speak, and frees the GPU after `idle_ttl_minutes` (default 5)
  - Measured release on an RTX 5090: Whisper holds 2.26 GB and returns 2.25 GB;
    Cohere holds 4.71 GB and returns 4.56 GB. The remainder is the CUDA context,
    which stays for the life of the process.
  - `load_backend` falls back to Whisper with a warning on ImportError, OSError
    (a missing or revoked Hugging Face token) or a CUDA refusal
- `hotwords` passed through `transcription.transcribe_audio` to faster-whisper
- `scripts/bench_asr.py`: WER, domain-term recall, latency, VRAM, cold reload and
  garbage rate over the Wispr Flow export. Results in
  `research/asr-benchmark-2026.md`

### Verified
- **torch cu128 and ctranslate2 coexist in one process, in either import order.**
  The open risk was that both load cuDNN 9 and cuBLAS by the same DLL names and
  whichever loaded first would win. Tested on this machine with
  `torch 2.11.0+cu128` and `ctranslate2 4.8.2` against the nvidia cuDNN 9.5
  wheels: `import torch; torch.zeros(1).cuda()` then a CUDA `WhisperModel`
  transcribe, and the reverse order in a fresh process. Both exit 0, so no
  wheel bump or `CUDA_PATH` change was needed and both backends can share the
  process.

- Comprehensive test coverage improvements (#41)
  - Added tests for CUDA path configuration
  - Added tests for app prompt normalization and conversion functions
  - Increased `config.py` coverage to 100% (from 66%)
  - Increased `app_prompts.py` coverage to 99% (from 41%)
- Privacy warning for debug logging mode in GUI (#40)
  - Added prominent warning label when debug mode is enabled
  - Warns users that debug mode logs transcribed speech and prompts to disk
- Architecture documentation (#43)
  - Added comprehensive architecture diagram using Mermaid
  - Documented data flow through the system
  - Sequence diagrams for recording, transcription, LLM cleanup, and paste flows
  - Module responsibilities and design patterns
  - Threading model visualization
- **Secure API key storage** (#45) ⭐ **SECURITY IMPROVEMENT**
  - API keys now encrypted using Windows Credential Manager via `keyring` library
  - Automatic migration of plaintext API keys on first run
  - API keys no longer stored in plaintext JSON settings file
  - New `credentials.py` module for secure credential management
  - Comprehensive test coverage (87% for credentials module)

### Changed
- Improved error handling across the codebase (#40)
  - Replaced broad `except Exception` with specific exception types
  - Added inline comments documenting exception types
  - Better error diagnostics in 9 modules
- Refactored audio module to class-based design (#42)
  - Converted global variable pattern to `AudioRecorder` class
  - Improved encapsulation and thread management
  - Maintained backward compatibility with wrapper functions
  - Improved performance and responsiveness
- GUI improvements (#44)
  - "Register hotkey" button now greys out after successful registration (similar to "Load model")
  - Provides clearer visual feedback that hotkey is active
- **Settings storage improvements** (#45)
  - Replaced `print()` statements with proper `logger` calls
  - Secure settings automatically excluded from JSON file
  - Better error messages and logging

### Security
- **CRITICAL**: API keys now stored securely in Windows Credential Manager instead of plaintext JSON (#45)
  - Protects against credential theft from disk
  - Encryption tied to user account
  - Automatic migration for existing users
- **CRITICAL**: ReDoS (Regular Expression Denial of Service) protection for app-specific prompts (#46)
  - Regex complexity validation blocks patterns with excessive nesting
  - Timeout protection prevents infinite regex matching
  - Maximum regex length limit (500 characters)
  - Safe regex matching with automatic validation
  - Comprehensive logging of blocked patterns

## [0.1.0] - 2025-01-XX

### Added
- Initial release of Whisper Dictate
- Local speech-to-text using faster-whisper (SYSTRAN)
- Optional LLM cleanup via OpenAI-compatible endpoints
- Privacy-first, offline transcription
- CUDA 12.4 + cuDNN 9.5 support for GPU acceleration
- Global hotkey support for Windows
- Customizable glossary system for text normalization
- Application-specific prompts with window title pattern matching
- Auto-paste functionality with configurable delay
- Comprehensive logging with rotating file handler
- Settings persistence in JSON format
- GUI with status indicator and log viewer

### Features

#### Core Functionality
- **Local Transcription**: Powered by faster-whisper for offline, privacy-focused speech-to-text
- **LLM Integration**: Optional text cleanup via OpenAI-compatible API endpoints
- **Glossary System**: Define custom word replacements with regex, case-sensitivity, and word boundary options
- **App-Specific Prompts**: Tailor LLM behavior based on active application and window title
- **Hotkey Control**: Register global Windows hotkeys for hands-free operation
- **Auto-Paste**: Automatically paste transcribed text into active applications

#### User Interface
- **Modern GUI**: Clean tkinter interface with tabbed settings
- **Status Indicator**: Floating window showing current transcription state
- **Log Viewer**: Built-in log file viewer with auto-refresh
- **Device Selection**: Choose audio input device from dropdown
- **Model Management**: Select and load Whisper models with device/compute type control

#### Technical Features
- **CUDA Support**: Automatic CUDA path configuration for GPU acceleration
- **Settings Persistence**: JSON-based settings storage in user directory
- **Error Handling**: Graceful degradation with informative error messages
- **Logging**: Comprehensive logging with file rotation and debug mode
- **Integration Tests**: Full pipeline testing from audio to LLM cleanup
- **Type Annotations**: Modern Python 3.10+ type hints throughout

#### Documentation
- Comprehensive `CLAUDE.MD` for AI assistant context
- Detailed `README.md` with setup and usage instructions
- Build documentation in `docs/build.md`
- Inline code documentation and docstrings

### Dependencies
- Python 3.11+
- faster-whisper >= 1.2.0
- ctranslate2 >= 4.6.0
- nvidia-cublas-cu12 == 12.4.5.8
- nvidia-cuda-nvrtc-cu12 == 12.4.127
- nvidia-cuda-runtime-cu12 == 12.4.127
- nvidia-cudnn-cu12 == 9.5.0.50
- openai >= 1.40
- sounddevice >= 0.5.3
- pyautogui >= 0.9.54
- pyperclip >= 1.11.0
- pillow >= 12.0.0
- pyinstaller >= 6.16.0 (for building executables)

### Development Tools
- pytest + pytest-cov + pytest-mock for testing
- ruff for linting and formatting
- mypy for type checking
- uv for fast package management

[Unreleased]: https://github.com/dancwilliams/whisper-dictate/compare/v0.1.0...HEAD
