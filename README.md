Perfect — here’s an updated `README.md` reflecting everything your project now does, including:

* Whisper dictation (CLI + GUI)
* Optional LLM cleanup through an OpenAI-compatible endpoint (like LM Studio)
* Auto-paste directly into the active window
* Clear, concise setup for any new machine

---

````markdown
# Whisper Dictate

A privacy-first, local **speech-to-text and AI cleanup tool** for Windows.  
It uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) for offline transcription and can optionally send text to a local or remote **OpenAI-compatible endpoint** (such as [LM Studio](https://lmstudio.ai/)) for light cleanup or rewriting.  
It supports both a **CLI** and a **GUI**, global hotkeys, and automatic pasting into the active window.

---

## ✨ Features

- **100 % local transcription** — no cloud calls  
- **Optional LLM cleanup** via an OpenAI-style endpoint (LM Studio, Ollama, etc.)  
- **Global hotkey** for push-to-talk from any application  
- **Auto-paste** into the focused window (`Ctrl+V`)  
- **GUI and CLI** modes  
- **GPU or CPU** execution  
- **One-command setup** using [`uv`](https://docs.astral.sh/uv/)  

---

## 🚀 Quick Start

### 1. Clone and install

```powershell
git clone https://github.com/yourusername/whisper-dictate.git
cd whisper-dictate
uv sync
````

### 2. Run (CLI)

```powershell
uv run dictate
```

Default behavior:

```
Toggle hotkey: CTRL+WIN+G
Quit hotkey:   CTRL+WIN+X
Loading Whisper model: small on cpu (int8)
Ready.
```

Speak, press **Ctrl + Win + G** again to stop, and the text will appear in the console and on the clipboard.

---

## 🪟 Run (GUI)

```powershell
uv run dictate-gui
```

The GUI adds:

* Model/device selection
* Input-device field
* Optional LLM cleanup section (endpoint, model, API key, temperature, and system prompt)
* **Auto-paste** checkbox and delay setting
* Transcript view with timestamped results

Use **Load model**, then **Register hotkey** (e.g., `CTRL+WIN+G`), and press the hotkey anywhere to dictate.
If “Auto-paste” is enabled, the result pastes automatically into the app you were using.

---

## ⚙️ CLI Options

```powershell
uv run dictate --help
```

Common examples:

```powershell
# Basic CPU dictation
uv run dictate --preset cpu-fast

# Use GPU
uv run dictate --preset gpu-fast

# Clean up text through a local LM Studio server
uv run dictate --preset cpu-fast `
  --llm-endpoint http://localhost:1234/v1 `
  --llm-model "Llama-3.1-8B-Instruct"

# Auto-paste into the active window
uv run dictate --auto-paste
```

All cleanup options are optional; omit them for raw Whisper output.

---

## 🧠 LLM Cleanup Details

Whisper Dictate can post-process text using any OpenAI-compatible endpoint.

Example (LM Studio defaults):

```powershell
--llm-endpoint http://localhost:1234/v1
--llm-model "Llama-3.1-8B-Instruct"
--llm-prompt "You are a writing assistant. Clean up the user's dictated text for grammar, punctuation, and capitalization without changing meaning."
```

If your endpoint needs an API key:

```powershell
--llm-key sk-yourkey
```

---

## 💻 GPU Acceleration (Optional)

1. Install **CUDA 12.x** and **cuDNN v9.x** (for example, CUDA 12.5 + cuDNN 9.4).
2. Ensure `cudnn_ops64_9.dll` is in your PATH.
3. Run:

   ```powershell
   uv run dictate --device cuda --compute-type float16
   ```
4. Check that the log shows `on cuda (float16)`.

---

## 🪄 Auto-Paste Behavior

When `--auto-paste` (CLI) or the **Auto-paste** checkbox (GUI) is enabled:

1. The final text is copied to the clipboard.
2. After a short delay (default 0.15 s), `Ctrl + V` is sent to the active window.

If you toggle recording from inside Word, Notion, VS Code, or a chat window, the cleaned text appears directly where your cursor is.

> Tip: Trigger the hotkey, don’t click the GUI button — clicking steals focus and will paste into the GUI itself.

---

## 🧩 Project Layout

```
whisper-dictate/
│
├─ whisper_dictate/
│   ├─ __init__.py
│   ├─ cli.py         # CLI with optional LLM and auto-paste
│   └─ gui.py         # Tkinter GUI with LLM + auto-paste
│
├─ pyproject.toml
└─ README.md
```

---

## 🧾 Deployment on Another Machine

```powershell
git clone https://github.com/yourusername/whisper-dictate.git
cd whisper-dictate
uv sync
uv run dictate-gui     # or uv run dictate
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

**Enjoy local, AI-enhanced dictation — fast, private, and cloud-free.**
