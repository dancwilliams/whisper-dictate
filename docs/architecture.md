# Architecture

This document provides a visual overview of Whisper Dictate's architecture and data flow.

## System Architecture

```mermaid
graph TB
    subgraph "User Interaction"
        User[User]
        Hotkey[Global Hotkey<br/>hotkeys.py]
        GUI[GUI Application<br/>gui.py]
    end

    subgraph "Core Processing Pipeline"
        Audio[Audio Recorder<br/>audio.py]
        Transcription[Whisper Model<br/>transcription.py]
        Glossary[Glossary Application<br/>glossary.py]
        LLM[LLM Cleanup<br/>llm_cleanup.py]
    end

    subgraph "Context & Configuration"
        AppContext[Window Detection<br/>app_context.py]
        AppPrompts[App-Specific Prompts<br/>app_prompts.py]
        Settings[Settings Store<br/>settings_store.py]
        Prompt[Prompt Manager<br/>prompt.py]
    end

    subgraph "External Systems"
        Microphone[Microphone]
        Clipboard[System Clipboard]
        LLMEndpoint[LLM API Endpoint<br/>OpenAI-compatible]
        WindowsAPI[Windows API<br/>Active Window]
    end

    subgraph "Storage"
        SettingsFile[~/.whisper_dictate/<br/>settings.json]
        PromptFile[~/.whisper_dictate/<br/>prompt.txt]
        GlossaryFile[~/.whisper_dictate/<br/>glossary.json]
        LogFile[~/.whisper_dictate/logs/<br/>whisper_dictate.log]
    end

    User -->|Presses| Hotkey
    Hotkey -->|Event| GUI
    GUI -->|Start Recording| Audio
    Audio -->|Capture| Microphone
    Audio -->|Raw Audio| Transcription
    Transcription -->|Text| GUI
    GUI -->|Apply?| Glossary
    Glossary -->|Normalized Text| GUI
    GUI -->|Get Context| AppContext
    AppContext -->|Query| WindowsAPI
    AppContext -->|Window Info| AppPrompts
    AppPrompts -->|Resolve Prompt| Prompt
    GUI -->|Cleanup?| LLM
    LLM -->|API Request| LLMEndpoint
    LLM -->|Cleaned Text| GUI
    GUI -->|Auto Paste?| Clipboard

    Settings -.->|Load| SettingsFile
    Settings -.->|Save| SettingsFile
    Prompt -.->|Load| PromptFile
    Prompt -.->|Save| PromptFile
    Glossary -.->|Load| GlossaryFile
    Glossary -.->|Save| GlossaryFile
    GUI -.->|Logs| LogFile

    style User fill:#e1f5ff
    style Hotkey fill:#fff3cd
    style GUI fill:#fff3cd
    style Audio fill:#d4edda
    style Transcription fill:#d4edda
    style Glossary fill:#d4edda
    style LLM fill:#d4edda
    style Microphone fill:#f8d7da
    style Clipboard fill:#f8d7da
    style LLMEndpoint fill:#f8d7da
    style WindowsAPI fill:#f8d7da
```

## Data Flow

### 1. Recording Trigger
```mermaid
sequenceDiagram
    participant User
    participant Hotkey
    participant GUI
    participant Audio
    participant Mic as Microphone

    User->>Hotkey: Press Ctrl+Win+G
    Hotkey->>GUI: Post hotkey event
    GUI->>Audio: start_recording(device)
    Audio->>Mic: Open audio stream
    loop While recording
        Mic->>Audio: Audio chunks
        Audio->>Audio: Buffer in queue
    end
    User->>Hotkey: Release hotkey
    Hotkey->>GUI: Post hotkey event
    GUI->>Audio: stop_recording()
    Audio->>GUI: Return buffered audio
```

### 2. Transcription Pipeline
```mermaid
sequenceDiagram
    participant GUI
    participant Trans as Transcription
    participant Whisper as faster-whisper
    participant Glos as Glossary
    participant GlosFile as glossary.json

    GUI->>Trans: transcribe(audio, model, device)
    Trans->>Whisper: Load model if needed
    Trans->>Whisper: transcribe(audio)
    Whisper-->>Trans: Raw transcript
    Trans-->>GUI: Transcript text

    alt Glossary enabled
        GUI->>Glos: apply_glossary(text)
        Glos->>GlosFile: Load glossary entries
        GlosFile-->>Glos: Entries list
        loop For each entry
            Glos->>Glos: Replace pattern with value
        end
        Glos-->>GUI: Normalized text
    end
```

### 3. LLM Cleanup (Optional)
```mermaid
sequenceDiagram
    participant GUI
    participant AppCtx as AppContext
    participant AppPr as AppPrompts
    participant Prompt
    participant LLM as LLMCleanup
    participant API as LLM Endpoint

    alt LLM enabled
        GUI->>AppCtx: get_active_window_info()
        AppCtx->>AppCtx: Query Windows API
        AppCtx-->>GUI: WindowInfo(process, title)

        GUI->>AppPr: resolve_prompt(window_info, settings)
        AppPr->>AppPr: Match app-specific prompts
        alt App-specific prompt found
            AppPr-->>GUI: Custom prompt
        else No match
            AppPr->>Prompt: load_prompt()
            Prompt-->>AppPr: Default prompt
            AppPr-->>GUI: Default prompt
        end

        GUI->>LLM: cleanup_text(text, prompt, settings)
        LLM->>API: POST /v1/chat/completions
        API-->>LLM: Cleaned text + usage stats
        LLM-->>GUI: Cleaned text
    end
```

### 4. Output & Paste
```mermaid
sequenceDiagram
    participant GUI
    participant Clipboard
    participant Target as Target Application

    GUI->>GUI: Display result in text widget

    alt Auto-paste enabled
        GUI->>Clipboard: Copy text
        GUI->>GUI: Wait paste_delay
        GUI->>Target: Simulate Ctrl+V
        Target->>Clipboard: Paste content
    end
```

## Module Responsibilities

| Module | Responsibility | External Dependencies |
|--------|----------------|----------------------|
| `config.py` | Configuration defaults, CUDA setup | nvidia-cublas, nvidia-cudnn |
| `app_context.py` | Active window detection (Windows API) | ctypes (windll.user32, windll.kernel32) |
| `prompt.py` | LLM prompt loading/saving | None |
| `app_prompts.py` | Per-application prompt resolution | None |
| `app_prompt_dialog.py` | GUI for per-app prompt management | tkinter |
| `audio.py` | Audio recording with sounddevice | sounddevice, numpy |
| `transcription.py` | Whisper model loading and transcription | faster-whisper, ctranslate2 |
| `llm_cleanup.py` | LLM text cleanup with OpenAI client | openai |
| `glossary.py` | Glossary persistence and application | None |
| `glossary_dialog.py` | GUI for glossary management | tkinter |
| `hotkeys.py` | Windows global hotkey registration | ctypes (windll.user32) |
| `gui_components.py` | Reusable GUI widgets | tkinter |
| `logging_config.py` | Centralized logging setup | logging |
| `settings_store.py` | Settings persistence | json |
| `gui.py` | Main GUI application | tkinter, pyautogui, pyperclip |

## Key Design Patterns

### Singleton Pattern
- **AudioRecorder**: Global instance via `get_default_recorder()` for backward compatibility
- **Whisper Model**: Cached in `transcription.py` to avoid reloading

### Observer Pattern
- **Hotkeys**: Windows message loop posts events to GUI thread
- **Audio Recording**: Background thread queues chunks, main thread retrieves buffer

### Strategy Pattern
- **App-Specific Prompts**: Different prompts for different applications
- **Glossary**: Configurable find/replace patterns

### Separation of Concerns
- **Business Logic**: Separate modules (audio, transcription, llm_cleanup, glossary)
- **GUI**: Orchestration and display only (`gui.py`)
- **Configuration**: Centralized in `settings_store.py` and `config.py`

## Threading Model

```mermaid
graph LR
    MainThread[Main Thread<br/>GUI Event Loop]
    AudioThread[Audio Thread<br/>sounddevice callback]
    RecorderThread[Recorder Thread<br/>buffer management]

    MainThread -->|start_recording| AudioThread
    AudioThread -->|audio chunks| RecorderThread
    RecorderThread -->|buffered data| MainThread
    MainThread -->|stop_recording| RecorderThread
```

- **Main Thread**: GUI event loop (tkinter), hotkey callbacks, transcription, LLM calls
- **Audio Callback Thread**: sounddevice callback (high priority, minimal processing)
- **Recorder Thread**: Buffer management, queue processing (daemon thread)

## File Structure

```
whisper_dictate/
├── config.py                 # Configuration and CUDA setup
├── app_context.py           # Windows API for active window detection
├── prompt.py                # Prompt file I/O
├── app_prompts.py           # App-specific prompt resolution
├── app_prompt_dialog.py     # GUI for app prompts
├── audio.py                 # AudioRecorder class
├── transcription.py         # Whisper model interface
├── llm_cleanup.py           # OpenAI client wrapper
├── glossary.py              # Glossary logic
├── glossary_dialog.py       # GUI for glossary
├── hotkeys.py               # Windows hotkey registration
├── gui_components.py        # Reusable widgets
├── logging_config.py        # Logging configuration
├── settings_store.py        # Settings persistence
└── gui.py                   # Main application

~/.whisper_dictate/
├── whisper_dictate_settings.json   # User settings
├── whisper_dictate_prompt.txt      # Default LLM prompt
├── whisper_dictate_glossary.json   # Glossary entries
└── logs/
    └── whisper_dictate.log          # Application logs
```

## Error Handling Strategy

- **Specific Exceptions**: Each module catches specific exceptions (OSError, ValueError, etc.)
- **Graceful Degradation**: LLM and glossary failures don't block transcription
- **User Feedback**: Errors displayed in GUI status bar and logged
- **Logging**: Comprehensive logging to `~/.whisper_dictate/logs/whisper_dictate.log`

## Performance Considerations

- **Model Caching**: Whisper model loaded once and reused
- **GPU Acceleration**: CUDA 12.4 + cuDNN 9.5 for faster inference
- **Compute Types**: Configurable (int8_float16, float16, int8)
- **Audio Buffering**: Background thread prevents blocking GUI
- **Lazy Loading**: Models loaded on first use, not at startup
