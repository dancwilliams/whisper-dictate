# Whisper Dictate

A lightweight, privacy-first **local dictation tool** for Windows built in Python.  
It uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) to run OpenAI’s Whisper speech recognition models locally and integrates a global hotkey so you can talk, transcribe, and paste text anywhere — without sending audio to the cloud.

---

## ✨ Features
- **Local only** — no network calls or cloud APIs  
- **Global hotkey** to start/stop dictation from any app  
- **Clipboard copy** so recognized text is ready to paste  
- **GUI and CLI** modes 
- **GPU or CPU support** with automatic configuration  
- **Simple installation** using [`uv`](https://docs.astral.sh/uv/) for environment management  

---

## 🚀 Quick Start

### 1. Clone the repo
```powershell
git clone https://github.com/yourusername/whisper-dictate.git
cd whisper-dictate
```

### 2. Sync dependencies
```powershell
uv sync
```

🖥️ Run (CLI mode)
```powershell
uv run dictate
```

You should see:
```yaml
Toggle hotkey: CTRL+WIN+G
Quit hotkey:   CTRL+WIN+X
Loading Whisper model: small on cpu (int8)
Ready.
```

Press Ctrl + Win + G to start/stop recording and Ctrl + Win + X to quit.
The recognized text prints to the console and is also copied to your clipboard.

🪟 Run (GUI mode)

A Tkinter-based GUI is included for easier control.
```powershell
uv run dictate-gui
```

- Click Load model to initialize the engine.
- Click Register hotkey (e.g., CTRL+WIN+G) to enable global dictation.
- Use the Start recording button or the hotkey to record and transcribe.
- Transcripts appear in the text box and copy to the clipboard automatically.

⚙️ Options

You can override any defaults using command-line flags:
```powershell
uv run dictate --help
```

Common examples:

```powershell
# Use a smaller English-only model (faster start)
uv run dictate --model base.en

# Force CPU mode with optimized int8 compute type
uv run dictate --device cpu --compute-type int8

# Use your NVIDIA GPU with float16 acceleration
uv run dictate --device cuda --compute-type float16

# Choose a specific microphone
uv run dictate --input-device "USB PnP Sound Device"

# Change hotkeys
uv run dictate --toggle CTRL+WIN+T --quit CTRL+WIN+Q
```

💻 GPU Acceleration (Optional)

If your system has a supported NVIDIA GPU:

Install CUDA 12.x and cuDNN v9.x (for example, CUDA 12.5 + cuDNN 9.4).

Add the cuDNN bin folder (containing cudnn_ops64_9.dll) to your system PATH.

Run:
```powershell
uv run dictate --device cuda --compute-type float16
```

Tested successfully with:

- RTX 5090 using CUDA 12.5 + cuDNN v9.4
- GeForce MX550 using CUDA 12.4 runtime

If `nvcc` is missing, that’s fine — only the runtime DLLs are required.

🧠 Presets

Two convenient presets are built in:
```powershell
# Fastest on CPU
uv run dictate --preset cpu-fast

# Fastest on GPU
uv run dictate --preset gpu-fast
```

🔊 Tips

If audio fails to start, open Settings → Privacy & Security → Microphone and make sure desktop apps are allowed.

- To suppress the Hugging Face symlink warning on Windows:
```powershell
setx HF_HUB_DISABLE_SYMLINKS_WARNING 1
```

- To limit CPU thread usage:
```powershell
setx OMP_NUM_THREADS 4
setx MKL_NUM_THREADS 4
```

🧩 Project Structure
```markdown
whisper-dictate/
│
├─ whisper_dictate/
│   ├─ __init__.py
│   └─ cli.py
│   └─ gui.py
│
├─ pyproject.toml
└─ README.md
```

📦 Updating or reinstalling

On a new machine, just run:
```powershell
git clone https://github.com/yourusername/whisper-dictate.git
cd whisper-dictate
uv sync
uv run dictate
```

If you want to freeze dependency versions for reproducibility:
```powershell
uv lock
```

Then later use:
```powershell
uv sync --locked
```

🧾 Deployment on Another Machine
```powershell
git clone https://github.com/yourusername/whisper-dictate.git
cd whisper-dictate
uv sync
uv run dictate         # CLI
uv run dictate-gui     # GUI
```

To lock dependency versions:
```powershell
uv lock
uv sync --locked
```

🛠 Troubleshooting

| Symptom                              | Likely Cause                           | Fix                                               |
| ------------------------------------ | -------------------------------------- | ------------------------------------------------- |
| `Could not register quit hotkey`     | That combo is reserved by Windows      | Use `--quit CTRL+WIN+X` or another combination    |
| `Could not locate cudnn_ops64_9.dll` | CUDA/cuDNN runtime not found           | Install cuDNN v9 and add its `bin` folder to PATH |
| `int8_float16 not supported`         | CPU cannot run that mixed mode         | Use `--compute-type int8` or `int8_float32`       |
| `Device unavailable`                 | Microphone blocked by privacy settings | Enable mic access for desktop apps                |

🧾 License

MIT License © 2025 Dan C Williams