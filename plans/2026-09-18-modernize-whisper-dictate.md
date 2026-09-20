# Modernize whisper-dictate Implementation Plan

Revision 2 — 2026-09-18, after the grill. Supersedes revision 1 entirely.

## Overview

Bring whisper-dictate back as the daily dictation tool on the Windows workstation, replacing Wispr Flow (renews **2026-12-06**) and Superwhisper. The delivery layer — hotkey, clipboard, paste — is fixed before any model is swapped, because every dictation touches it and it is where both commercial apps were found wanting. The ASR model is chosen by a benchmark on Dan's own recorded speech, not by leaderboard.

**Clock:** parity gate = Phases 1–4 accepted. Cutover (Phase 5) target **2026-11-22**, two weeks before renewal. If the gate is not passed by 2026-11-22, switch Flow to monthly billing before 2026-12-06 and keep going.

## Ground rules for the implementer

- **Work in the Windows clone, Windows-native Claude Code:** `C:\Users\Dan Williams\git\whisper-dictate`, branches/worktrees per `CLAUDE.MD`. Every risky line here is Windows-only (keyboard hook, clipboard, CUDA wheels); run the real code, not just mocks. The WSL clone (`~/git/whisper-dictate`) was 11 commits behind when revision 1 was written and is not a working copy.
- **Line references below are against `origin/feature/optimize-transcription` (`1e431c8`)** — i.e. `main` (`ce4b65f`) after Phase 0's merge. Re-grep before editing; the numbers are anchors, not guarantees.
- **Wispr Flow is installed and its push-to-talk is LCtrl+LWin.** Until cutover, whisper-dictate must not use any chord containing LCtrl+LWin (the saved `CTRL+WIN+G` trips Flow's PTT too). Dev chord: **`CTRL+SPACE`**.
- **Safety controls are Dan's decisions.** If Microsoft Defender (real-time protection is on; no SentinelOne agent on this box) flags the keyboard hook, stop and report. Never add an exclusion, never disable protection.
- The keyboard hook sees every keystroke system-wide. It must never log, store, or transmit key codes.
- `bws` exists only in WSL (`/usr/local/bin/bws`), not on the Windows PATH. Secret handoffs run from a WSL terminal.
- Ponytail rules: no abstraction with one implementation, shortest working diff, deletion over addition, `ponytail:` comments on deliberate ceilings, one runnable check per piece of non-trivial logic.

## Current State Analysis

**Pipeline** (`gui.py:1217-1330` `_transcribe_and_clean`): hotkey toggles recording (`gui.py:1187-1215`) → whole buffer to faster-whisper with VAD/threshold kwargs (`gui.py:1241-1253`) → glossary (`:1267`) → optional OpenAI-compatible cleanup (`:1273-1299`) → glossary again (`:1302`) → `pyperclip.copy` (`:1310`) + `pyautogui.hotkey("ctrl","v")` (`:1317`).

| Problem | Where | Consequence |
|---|---|---|
| Clipboard overwritten, never restored | `gui.py:1310`; no snapshot anywhere | Every dictation destroys the clipboard — text, HTML, image, file. Flow restores every format in 556 ms; Superwhisper restores plain text only. |
| Hotkey needs a letter; toggle only | `hotkeys.py:60` `"Only single A..Z keys supported"`; `RegisterHotKey` at `hotkeys.py:152`; `gui.py:1187` | Modifier-only chord impossible; no hold-to-talk. |
| Paste via Ctrl+V | `gui.py:1317` | Both commercial apps use Shift+Insert; the VS Code terminal keybinding added 2026-09-17 targets it. |
| Mic opened on press | `audio.py:78-87` | Measured on this machine (Speakerphone (MX Brio), MME): first audio callback 577 ms after a cold press, ~264 ms warm. Hold-to-talk clips the first word. |
| Status shows "listening" before audio flows | `gui.py:1207` fires right after `start_recording()` returns | The cue lies by ~245 ms. |
| Cleanup only via HTTP endpoint | `llm_cleanup.py:48-198` | Needs a server; Ollama misfiles S1-mini output into `reasoning` with empty `content`; `llm_cleanup.py:143-148` reads only `delta.content`. |
| Models resident for process lifetime | `gui.py:91`, `:812`, `:1150` | No way to release the GPU to Ollama/Higgs/ComfyUI. |
| No `hotwords` to Whisper | `transcription.py:14-81` (has `initial_prompt`, not `hotwords`) | Vocabulary never reaches the recognizer. faster-whisper truncates hotwords at `max_length // 2` (~220 tokens). |
| Glossary exact-match only | `glossary.py:57-78` | Each misrecognition variant needs its own rule. |
| No dictation history; `llm_debug` is **on** in the live settings | 692 KB `logs\whisper_dictate.log` | An accidental transcript archive in the worst format. |
| Closing the window quits; no single-instance guard | `gui.py:73` → `_on_close` (`:1026`) | A login-launched app dies on an accidental close; two launches = two hooks = double paste. |
| Duplicate load/register paths | `_load_model` (`:1135`, blocks the UI) vs `_auto_load_model_task` (`:796`, threaded); `_register_hotkey` (`:1164`) vs `_auto_register_hotkey_task` (`:842`) | Every hotkey/model change must be made twice. |
| Stale deps | `pyproject.toml:7-22` | `ctranslate2` 4.6.0→4.8.2, `faster-whisper` 1.2.0→1.2.1, `openai` →3.16, `pyinstaller` is a runtime dep (`:19`). CI pins uv `0.4.4` and syncs `--all-extras` (`ci.yml:20,27,45,52,72,79`). |

**Already true, do not rebuild:** auto-load + auto-register on startup (PR #48; `gui.py:788-861`; on in Dan's settings), CI with ruff/mypy/pytest on `windows-latest` py3.11+3.12 (PR #50), `large-v3-turbo` in `MODEL_INFO` (`config.py:68`) and selected in Dan's settings, VAD + hallucination thresholds + `initial_prompt` (the branch Phase 0 merges). CUDA loads on the RTX 5090 with the current 12.4 pins (proven 2026-09-18).

### Key Discoveries

- **Both models liked in Superwhisper are Apache-2.0 open weights.** [CohereLabs/cohere-transcribe-03-2026](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026): 2B conformer, transformers ≥ 5.4.0, `CohereAsrForConditionalGeneration`, numpy 16 kHz input, auto-chunks, **gated**, **no documented vocabulary biasing**, open discussion "Garbage output from transcribe method" (#28). [superwhisper/s1-mini-GGUF](https://huggingface.co/superwhisper/s1-mini-GGUF): `s1-mini-q4_k_m.gguf`, 462 MB, not gated.
- **S1-mini's contract is fixed**: one system sentence; control line `[Styling: casual|semi-casual|semi-formal|formal] [Structure: prose|lists] [Context: general|email]`; greedy; thinking disabled by hard-coding the assistant turn as `<think>\n\n</think>\n\n`. Any other system text → one token, blank (measured). On the working path: 0.14–0.26 s, 400+ tok/s on the 5090.
- **Benchmark corpus exists:** `C:\Users\Dan Williams\wispr-flow-export\audio\` — 200 WAVs (16 kHz mono 16-bit), 41.1 min, p50 8.3 s, max 96 s; `history.jsonl` maps `audio_file` → `asrText`/`formattedText`/`editedText`; 138 have `editedText`, 122 actually edited. `editedText` sometimes contains unrelated typing — filter rows by token-sequence similarity ≥ 0.5 (as `scripts/mine_wispr_history.py` does).
- **Usage shape** (4,250 Flow dictations, 338 days, ~12.6/day): length p50 8.3 s, p90 27.4 s, p99 58.6 s. Cold-start rate by idle TTL: 5 min 35.5%, 15 min 21.0%, 30 min 14.8%, 60 min 10.0%.
- **Reload cost:** `WhisperModel("small")` → CUDA 0.44 s warm (1.06 s first; 1.15 s import). Cohere via torch: unmeasured — the benchmark reports it.
- **GPU is shared:** 32.6 GB, 7.6 GB used at idle by desktop apps; Ollama `KEEP_ALIVE=5m`, `MAX_LOADED_MODELS=2`, largest models 19.9–23.9 GB; Higgs 11.5 GB with a 300 s TTL.
- **Metaphone on real mined pairs** (`jellyfish`): 9 of 12 match; `Trey Fax` (`TRFKS`) does **not** match `threatfax` (`0RTFKS`). Every false-positive collision was a code of ≤ 4 symbols (`Claude`=`KLT` also hits cloud/clod; `Said` hits sad/seed/side; `DISA`=`TS` hits "does"). Codes of 5+ symbols were all distinctive (sample: 12 pairs, ~25 probe words).
- **Wheels exist for cp311 Windows:** `torch-2.11.0+cu128` (`download.pytorch.org/whl/cu128`), `llama_cpp_python-0.3.35-py3-none-win_amd64` (`abetlen.github.io/llama-cpp-python/whl/cu130`, also `cu124`), `transformers` 5.17.0.
- **Unverified risk:** torch cu128 ships cuDNN 9 DLLs; ctranslate2 loads cuDNN 9 by the same filenames from the nvidia wheels via `config.set_cuda_paths` (`config.py:126-151`). Whichever loads first may win. Phase 3 settles it before anything is built on it.
- **One user.** Repo: 0 stars, 0 forks, 0 issues, 0 releases, all 51 PRs by Dan. No settings migration code, no installer, no signing.

## Desired End State

Hold **Ctrl+Win**, hear a beep when capture is live, speak, release. About a second later the cleaned text lands at the cursor via Shift+Insert and the previous clipboard — including an image — is back. ASR and cleanup run in-process on the 5090, load in parallel with the recording when cold, and release the GPU after 5 idle minutes. The app starts at login, lives as a floating pill, and cannot be double-launched or accidentally closed. Domain terms come out right via the glossary (exact + opt-in phonetic) and, on a Whisper backend, per-app hotwords. Every dictation is logged locally as text, with 14 days of audio. Wispr Flow is gone before 2026-12-06.

## What We're NOT Doing

- No PyInstaller EXE. `packaging/pyinstaller/*.spec`, `build-windows.yml`, `docs/build.md` stay untouched for a future second user.
- No GUI redesign, no system-tray dependency (`pystray`).
- No streaming/partial transcription.
- No "learn from edits" watcher.
- No Parakeet (cancelled 2025-12-13 for NeMo/MSVC reasons — see `research/` after the Phase 0 merge).
- No Python 3.12+ locally (CI's 3.12 matrix leg stays as-is).
- No deletion of the OpenAI-compatible endpoint path; it becomes the second cleanup backend.
- No settings migration logic. One user, one settings file; new keys take defaults.
- No string-layer glossary rules for ordinary English words (`traffic`, `cloud`).
- No always-open microphone, no pre-roll buffer.
- No changes to Ollama or anything on the media server. (LM Studio is no longer in use on this machine; Ollama only.)

---

## Phase 0: Revive

### Overview
Merge the dangling branch, refresh dependencies (except CUDA), fix the dev/runtime split and CI, land the miner and this plan, prune and import the mined glossary, turn debug logging off.

### Changes Required

#### 1. Merge `feature/optimize-transcription`
Fast-forward `main` to `origin/feature/optimize-transcription` (`1e431c8`; sits directly on `ce4b65f`). Run the suite before and after. Delete the remote branch after merge.

#### 2. Land the miner and the plan
`scripts/mine_wispr_history.py` and `plans/2026-09-18-modernize-whisper-dictate.md` are untracked files copied into the Windows clone. Commit both. Amend the miner in the same PR:
- `risky()` also rejects a rule whose trigger is a common English word — ship a small inline stoplist seeded with the known offenders (`traffic`, `cloud`, `nuke`, `test`, `skills`, `gun`) plus `FILLERS`. `ponytail: hand-kept stoplist; swap for a word-frequency list if review noise persists.`
- Emit `snippets.csv` rows into `glossary.csv` as exact rules (a snippet is a glossary rule with a long distinctive trigger).
- `--selftest` gains asserts for both.

#### 3. Dependencies
**File**: `pyproject.toml`
```toml
dependencies = [
    "ctranslate2>=4.8.2",
    "faster-whisper>=1.2.1",
    "keyring>=25.7.0",
    "numpy>=2.3.4",
    "nvidia-cublas-cu12==12.4.5.8",        # unchanged: CUDA pins are decided in Phase 3 with torch
    "nvidia-cuda-nvrtc-cu12==12.4.127",
    "nvidia-cuda-runtime-cu12==12.4.127",
    "nvidia-cudnn-cu12==9.5.0.50",
    "openai>=3.16",
    "pillow>=12.0.0",
    "pyautogui>=0.9.54",
    "pyperclip>=1.11.0",
    "sounddevice>=0.5.6",
]

[dependency-groups]
dev = ["pytest>=8.0.0", "pytest-cov>=4.1.0", "pytest-mock>=3.12.0", "ruff>=0.1.0", "mypy>=1.8.0", "pyinstaller>=6.22"]
```
Remove `[project.optional-dependencies]` (`:24-31`) and `pyinstaller` from runtime (`:19`). `uv lock --upgrade`, `uv sync`. `openai` 3.x: `llm_cleanup.py:125-139` uses `chat.completions.create(stream=True, stream_options=...)` and `models.list()`; if `tests/test_llm_cleanup.py` passes, no code change.

#### 4. CI
**File**: `.github/workflows/ci.yml`
Drop the `version: "0.4.4"` pin (three places) and replace `uv sync --frozen --all-extras` with `uv sync --frozen` (dependency groups install by default). `build-windows.yml`: same two edits only.

#### 5. Docs drift
**File**: `CLAUDE.MD` — the module table names functions that do not exist. Correct to `get_active_context`, `clean_with_llm`, `HotkeyManager`, `App`; note dependency groups.

#### 6. Dan, manually
- Prune `C:\Users\Dan Williams\wispr-flow-export\mined\glossary.csv`: **delete `traffic → Traefik` and `Cloud → Claude`** (they rewrite ordinary speech), plus the changes of mind (`their→his`, `picard→EPCOT`, `Daniel→Damon`, `Toast→Timmy`, `Antonio→Austin`). Judge `Nuke→Nuc`, `Saeed→Said`, `Devin→Devon` by: would I ever say the left side and mean it?
- Import: Edit → Glossary… → Import CSV (merges into the 9 existing rules via `upsert_rule`, `glossary.py:148`).
- Settings → LLM cleanup → untick "Log full LLM prompts for debugging". Delete `~\.whisper_dictate\logs\whisper_dictate.log` if you don't want the accidental archive.

### Success Criteria

#### Automated Verification:
- [x] `git merge --ff-only origin/feature/optimize-transcription` succeeds
- [x] `uv lock --upgrade` and `uv sync` succeed
- [x] `uv run pytest` passes
- [x] `uv run ruff check .` and `uv run ruff format --check .` clean
- [x] `uv run python scripts/mine_wispr_history.py --selftest` prints `selftest ok`
- [x] CI green on the PR (all four jobs)
- [x] `uv run python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cuda', compute_type='float16'); print('cuda OK')"` prints `cuda OK`

#### Manual Verification:
- [x] `uv run dictate-gui` auto-loads `large-v3-turbo` and auto-registers the hotkey as before
- [x] Glossary dialog shows the imported rules; no rule has `traffic` or `cloud` as a trigger
- [x] `llm_debug` is `false` in `~\.whisper_dictate\whisper_dictate_settings.json` after closing the app

**Implementation Note**: pause for manual confirmation before Phase 1.

---

## Phase 1: Hold-to-talk hotkey

### Overview
Replace `RegisterHotKey` with a `WH_KEYBOARD_LL` hook: modifier-only chords, press/release/cancel events, hold-to-talk with tap-to-lock, a truthful ready beep, and a single-instance guard. Dev chord `CTRL+SPACE`.

### Changes Required

#### 1. Chord state machine (pure) + hook
**File**: `whisper_dictate/hotkeys.py` (rewrite, 177 lines)

```python
WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104

# Left/right variants collapse to one modifier
MODIFIER_VKS = {"CTRL": {0xA2, 0xA3}, "SHIFT": {0xA0, 0xA1}, "ALT": {0xA4, 0xA5}, "WIN": {0x5B, 0x5C}}
NAMED_VKS = {"SPACE": 0x20}
ALL_MODIFIERS = set().union(*MODIFIER_VKS.values())


def parse_chord(s: str) -> list[set[int]]:
    """'CTRL+WIN' -> [{0xA2,0xA3},{0x5B,0x5C}]; 'CTRL+SPACE' appends {0x20}; 'CTRL+WIN+G' appends {ord('G')}."""


class Chord:
    """Pure key-state tracker. feed() returns 'press', 'release', 'cancel' or None."""

    def __init__(self, groups: list[set[int]]):
        self.groups, self.keys = groups, set().union(*groups)
        self.down: set[int] = set()
        self.active = False

    def feed(self, vk: int, is_down: bool) -> str | None:
        (self.down.add if is_down else self.down.discard)(vk)
        if self.active and is_down and vk not in self.keys:
            self.active = False            # Ctrl+Win+Arrow etc.: not ours
            return "cancel"
        held = all(self.down & g for g in self.groups)
        if held and not self.active and self.down <= self.keys:
            self.active = True
            return "press"
        if not held and self.active:
            self.active = False
            return "release"
        return None

    def swallows(self, vk: int) -> bool:
        """Non-modifier chord keys are eaten while the modifiers are down, so SPACE does not auto-repeat into the app."""
        return vk in self.keys and vk not in ALL_MODIFIERS and all(
            self.down & g for g in self.groups if g <= ALL_MODIFIERS)
```

`self.down <= self.keys` on press means a chord only starts from a clean state — holding Ctrl+Win+D does not start a recording when D is released.

`HotkeyManager(on_press, on_release, on_cancel)`: `register(chord)` starts a daemon thread → `SetWindowsHookExW(WH_KEYBOARD_LL, proc, kernel32.GetModuleHandleW(None), 0)` + `GetMessageW` pump. The proc reads `KBDLLHOOKSTRUCT.vkCode`, **ignores injected events** (`flags & LLKHF_INJECTED`, so our own Shift+Insert never feeds the tracker), calls `chord.feed`, dispatches the callback, returns `1` if `chord.swallows(vk)` else `CallNextHookEx(...)`. The proc does nothing else — Windows silently removes a low-level hook that exceeds `LowLevelHooksTimeout` (~300 ms). Keep the `CFUNCTYPE` object on `self`. `unregister()`: post `WM_QUIT` (pattern at `hotkeys.py:132-144`) + `UnhookWindowsHookEx`. `modifiers_up() -> bool` exposes `not (chord.down & ALL_MODIFIERS)` for Phase 2. **No key code is ever logged.**

#### 2. Press / release / cancel in the GUI
**File**: `whisper_dictate/gui.py`
Replace `_toggle_record` (`:1187-1215`) with `_start_recording()` / `_stop_and_transcribe()` (bodies unchanged) and:

```python
TAP_SECONDS = 0.3

def _on_hotkey_press(self):
    if audio.is_recording():               # locked by an earlier tap
        return self._stop_and_transcribe()
    self._press_at = time.monotonic()
    self._start_recording()

def _on_hotkey_release(self):
    if not audio.is_recording():
        return
    if time.monotonic() - self._press_at < TAP_SECONDS:
        return self._set_status("listening", "Recording (locked) — press again to stop")
    self._stop_and_transcribe()

def _on_hotkey_cancel(self):
    audio.stop_recording(); audio.get_audio_buffer()      # discard
    self._set_status("ready", "Cancelled")
```

Collapse the duplicates while here: `_register_hotkey` (`:1164`) and `_auto_register_hotkey_task` (`:842`) become one method with a `quiet: bool` flag; all three callbacks marshal with `self.after(0, ...)` as `:1175` does. The "Start recording" button toggles via the same two helpers. Default `var_hotkey` (`:146`) → `"CTRL+SPACE"`; the Automation window label (`:338`) → "Hotkey (hold to talk, tap to lock)".

#### 3. Truthful ready cue + pre-warm
**File**: `whisper_dictate/audio.py`
`AudioRecorder.start(device, on_first_audio=None)`: `_audio_callback` (`:41-47`) invokes `on_first_audio` once per recording, on the first block. `gui._start_recording` passes a callback that (a) sets status "listening" — move it off `:1207` — and (b) plays the beep: `winsound.Beep(880, 60)` on a throwaway thread (stdlib, blocking call). At startup, open and close one `InputStream` (removes the measured 334 ms cold open).

Beep bleed is a known risk (speakerphone mic). Do not trim audio. If the acceptance test shows junk leading tokens, zero the samples in the span the beep played (its start time and 60 ms length are known) and re-test.

#### 4. Single-instance guard
**File**: `whisper_dictate/gui.py:1359` `main()`
`kernel32.CreateMutexW(None, False, "Local\\WhisperDictate")`; if `GetLastError() == ERROR_ALREADY_EXISTS` → exit 0 silently.

#### 5. Tests
**File**: `tests/test_hotkeys.py` (rewrite): `parse_chord` cases (modifier-only, `CTRL+SPACE`, letter, empty, unknown); `Chord.feed` sequences — LCtrl then LWin → press; release either → release; RCtrl+LWin completes; Ctrl+Win then Right-arrow → cancel, and the later releases produce nothing; Ctrl+Win+D held then D released → no press; `CTRL+SPACE`: `swallows(0x20)` true only while Ctrl is down; re-press after release fires again. `tests/test_audio.py`: `on_first_audio` fires exactly once per `start()`.

### Success Criteria

#### Automated Verification:
- [x] `uv run pytest tests/test_hotkeys.py tests/test_audio.py` pass
- [x] `uv run pytest`, `uv run ruff check .` clean
- [x] `git grep -n RegisterHotKey whisper_dictate/` returns nothing
- [x] `git grep -n "vk" whisper_dictate/hotkeys.py | grep -i "log\|print"` returns nothing

#### Manual Verification:
- [x] With Wispr Flow running: hold Ctrl+Space in Notepad → beep → speak → release → text pastes; Flow does not activate
- [x] No spaces are inserted and VS Code does not open IntelliSense while the chord is held
- [x] Tap Ctrl+Space (< 0.3 s) → locked; tap again → pastes
- [x] Hold Ctrl+Space, press another key → "Cancelled", nothing pastes
- [x] Ten dictations started by speaking "one two three" the instant the beep sounds: "one" present every time; **raw ASR (before glossary/cleanup) has no junk leading token** in any of the ten
- [x] Hold the chord 60 s → hook survives; next dictation works
- [x] Launch a second instance → it exits; still exactly one paste per dictation
- [x] **No Microsoft Defender detection** (Windows Security → Protection history). If there is one: stop, report, change nothing.

**Implementation Note**: pause for manual confirmation before Phase 2.

---

## Phase 2: Clipboard fidelity and Shift+Insert

### Overview
Snapshot every HGLOBAL clipboard format, write the dictation, wait for modifiers up, paste with Shift+Insert, restore. Proven with the `GetClipboardSequenceNumber` watcher from the Superwhisper investigation.

### Changes Required

#### 1. Clipboard module
**File**: `whisper_dictate/clipboard.py` (new, ~90 lines, ctypes only)

```python
CF_UNICODETEXT = 13
# Synthesized by Windows from other formats, or GDI handles rather than HGLOBAL memory.
SKIP = {2, 3, 7, 14, 16, 0x0081, 0x0082, 0x0083, 0x008E}  # BITMAP, METAFILEPICT, OEMTEXT, ENHMETAFILE, LOCALE, DSP*

def snapshot() -> list[tuple[int, bytes]]: ...
def restore(items: list[tuple[int, bytes]]) -> None: ...
def set_text(text: str) -> None: ...
```
`snapshot`: `OpenClipboard(None)` with ≤ 10 retries × 20 ms; `EnumClipboardFormats`; skip `SKIP`; `GetClipboardData` NULL → skip (delay-rendered); `GlobalLock`/`GlobalSize`/`ctypes.string_at`/`GlobalUnlock`; `CloseClipboard` in `finally`. `restore`: open, `EmptyClipboard`, per item `GlobalAlloc(GMEM_MOVEABLE)` + `memmove` + `SetClipboardData` (free the handle only on failure). An empty snapshot restores to an empty clipboard. `set_text` also sets the registered format `ExcludeClipboardContentFromMonitorProcessing` so Win+V history is not filled with dictations. Set `argtypes`/`restype` on every call — 64-bit handles truncate otherwise.

`ponytail: HGLOBAL formats only; CF_BITMAP/ENHMETAFILE are re-synthesized by Windows from DIB/DIBV5. Copy GDI handles only if a trace shows a real loss.`

#### 2. Paste path
**File**: `whisper_dictate/gui.py:1309-1327`
```python
saved = clipboard.snapshot()
clipboard.set_text(final_text)
if self.var_auto_paste.get():
    deadline = time.monotonic() + 1.0
    while not self.hotkey_manager.modifiers_up() and time.monotonic() < deadline:
        time.sleep(0.01)                       # never inject Shift+Insert under a held Ctrl/Win
    time.sleep(float(self.var_paste_delay.get()))
    pyautogui.hotkey("shift", "insert")
time.sleep(float(self.var_restore_delay.get()))
clipboard.restore(saved)
```
Remove `pyperclip` (`gui.py:16`, `:1324`, `pyproject.toml`). New setting `restore_delay`, default `0.6` (Flow measured 0.556 s), in the Automation window (`:330-374`) and beside `paste_delay` in load/save (`:939`, `:984`).

#### 3. Tests
**File**: `tests/test_clipboard.py` (new; mock `ctypes.windll` as `tests/test_app_context.py` does): skips `SKIP` and NULL handles; `restore` = one `EmptyClipboard` then one `SetClipboardData` per item; `CloseClipboard` runs when `GetClipboardData` raises. Because this session runs on Windows, also add one **real** round-trip test marked `@pytest.mark.skipif(sys.platform != "win32")`: set text + a registered format, snapshot, clobber, restore, compare.

### Success Criteria

#### Automated Verification:
- [x] `uv run pytest tests/test_clipboard.py` passes, including the real round-trip on Windows
- [x] `uv run pytest`, `uv run ruff check .` clean
- [x] `git grep -n pyperclip` returns nothing outside `uv.lock` history

#### Manual Verification (with `clipwatch.ps1` from the Superwhisper investigation doc: `pwsh -sta -NoProfile -File clipwatch.ps1`):
- [x] Image copied from a browser → dictate into Discord → trace shows the image format list back within ~0.6 s; Ctrl+V in Paint pastes it
- [x] Rich text from a web page → dictate into Teams → `HTML Format` in the restored list; paste into Word keeps formatting
- [x] File copied in Explorer → dictate → Ctrl+V elsewhere pastes the file
- [x] Empty clipboard → dictate → no error
- [x] Dictate into the VS Code terminal under Claude Code → text lands
- [x] Tap-to-lock, second tap held down for a full second → the paste still lands as plain text (modifier wait works)
- [x] Win+V history does not show the dictation

**Implementation Note**: pause for manual confirmation before Phase 3.

---

## Phase 3: ASR chosen by benchmark, with idle-unload

### Overview
Benchmark three candidates on Dan's own 200 clips. The winner becomes the primary backend, the runner-up the fallback. Models load in parallel with recording and unload after 5 idle minutes.

### Changes Required

#### 1. HF access (Dan, once)
Accept the terms at https://huggingface.co/CohereLabs/cohere-transcribe-03-2026 in a browser. Then from a **WSL** terminal (where `bws` and `jq` live; find the id with `bws secret list`) write the token straight into the Windows HF cache — nothing is displayed, nothing prompts:

```bash
bws secret get <HF_TOKEN secret id> -o json | jq -rj .value > "/mnt/c/Users/Dan Williams/.cache/huggingface/token"
```

#### 2. Dependencies
**File**: `pyproject.toml` — ML libraries in their own group, installed by default locally, excluded in CI:

```toml
[dependency-groups]
ml = ["torch", "transformers>=5.4.0", "huggingface-hub"]

[tool.uv]
package = true
default-groups = ["dev", "ml"]

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cu128", marker = "sys_platform == 'win32'" }]
```
`ci.yml`: `uv sync --frozen --no-group ml` (four places). Tests mock these libraries; accepted cost: CI cannot catch mock drift — the Windows-native session exercises the real libraries. No `accelerate` (load with `.to("cuda")`, `dtype=torch.bfloat16`); no `soundfile`/`librosa` (`audio.py` yields 16 kHz float32).

#### 3. CUDA coexistence test (do this first)
One process: `import torch; torch.zeros(1).cuda()` then `WhisperModel("small", device="cuda")` and transcribe one WAV; then the reverse import order in a fresh process. If either crashes on cuDNN/cuBLAS DLLs: try the nvidia wheel bump (`cublas 12.9.2.10`, `cuda-runtime 12.9.79`, `nvrtc 12.9.86`, `cudnn 9.26.0.51`, and `CUDA_PATH_V12_9` at `config.py:144`), then try dropping the nvidia wheels and pointing `set_cuda_paths` at `torch\lib`. Record what worked in CHANGELOG. If nothing works, the two backends cannot share a process: the loser of the benchmark is dropped instead of kept as fallback.

#### 4. Benchmark
**File**: `scripts/bench_asr.py` (new; stdlib + numpy + the ML group)
Candidates: `cohere`, `whisper large-v3-turbo`, `whisper large-v3-turbo + hotwords` (hotwords = `mined/hotwords.txt`, budgeted to 800 chars). For all 200 WAVs (read with `wave`, scale int16 → float32):
- **Reference** per clip: `editedText` if present and token-similarity to `formattedText` ≥ 0.5, else `formattedText`. Normalize both sides (lowercase, strip punctuation).
- **WER**: word-level edit distance / reference length (10-line stdlib DP).
- **Domain-term recall**: of the terms in `mined/hotwords.txt` that occur in a reference, the fraction present in the hypothesis.
- **Latency** per clip (p50/p90), **peak VRAM**, **cold reload time** (fresh load → first result), **garbage count** (empty output, or any 4-gram repeated ≥ 4 times).
Output: a markdown table to stdout and `research/asr-benchmark-2026.md`, plus per-clip CSV for eyeballing.

**Decision rule** (applied by Dan reading the table): lowest WER wins unless another candidate is within 1.0 WER point *and* has better domain-term recall or a cold reload more than 3 s faster — reload is weighted because 35.5% of dictations start cold at a 5-minute TTL. Any candidate with garbage output on > 2 clips is disqualified. Winner = primary; runner-up = fallback (subject to step 3).

#### 5. Backends + residency
**File**: `whisper_dictate/asr.py` (new, ~110 lines)

```python
class WhisperBackend:
    def __init__(self, model_name, device, compute_type): self.model = transcription.load_model(...)
    def transcribe(self, audio, hotwords=None, **whisper_kwargs) -> str:
        return transcription.transcribe_audio(self.model, audio, hotwords=hotwords, **whisper_kwargs)

class CohereBackend:
    MODEL_ID = "CohereLabs/cohere-transcribe-03-2026"
    def __init__(self, device="cuda"):           # torch/transformers imported here, not at module top
        ...AutoProcessor / CohereAsrForConditionalGeneration, dtype=torch.bfloat16, .to(device).eval()
    def transcribe(self, audio, hotwords=None, **_) -> str:      # no biasing API: hotwords ignored
        ...processor(audio, sampling_rate=16000, return_tensors="pt", language="en") → generate(max_new_tokens=448) → decode

class Resident:
    """Holds one lazily loaded object; frees it after ttl seconds idle."""
    def __init__(self, factory, ttl): ...
    def warm(self) -> None:        # start loading on a thread if cold; returns immediately
    def get(self):                 # blocks until loaded; resets the idle timer
    def _expire(self):             # threading.Timer → del obj, gc.collect(), torch.cuda.empty_cache() if torch is loaded
```
`Resident` is reused unchanged for S1-mini in Phase 4 (two real users, so it earns being a class). `load_backend(name)` falls back to the other backend on `ImportError`/`OSError`/`RuntimeError` with a status-bar warning.

`transcription.py:14` gains `hotwords: str | None = None`, passed through at `:62-76`.

#### 6. GUI wiring
**File**: `whisper_dictate/gui.py`
- `self.model` (`:91`) → `self.asr = Resident(lambda: asr.load_backend(...), ttl=self.var_idle_ttl.get()*60)`.
- `_on_hotkey_press` calls `self.asr.warm()` **before** `_start_recording()` — the model loads while Dan speaks; perceived wait = `max(0, load − utterance)`.
- `_transcribe_and_clean` (`:1241-1253`): `self.asr.get().transcribe(audio_data, hotwords=None, **whisper_kwargs)`; status "Loading model…" only if `get()` actually blocks.
- Collapse `_load_model` (`:1135`) and `_auto_load_model_task` (`:796`) into one threaded loader; startup calls `warm()`. The `if not self.model` gates (`:843`, `:1166`, `:1189`) go — the hotkey no longer depends on a loaded model.
- Settings: `asr_backend` (`"cohere"`/`"whisper"`, default = benchmark winner), `idle_ttl_minutes` (default `5`; `0` = never unload). Speech settings window (`:236`) gets the backend combobox; Automation window the TTL spinbox. The advanced-transcription window (`:376`) applies to the Whisper backend only — say so in its title.

#### 7. Tests
**File**: `tests/test_asr.py` (new): `load_backend("cohere")` with the import patched to raise → `WhisperBackend` + warning; `CohereBackend.transcribe` with mocked processor/model; `WhisperBackend` forwards `hotwords` and kwargs; `Resident`: `warm()` then `get()` returns the object, second `get()` does not reload, expiry (tiny ttl) drops it and the next `get()` reloads, `warm()` during a load does not start a second one. `tests/test_transcription.py`: `hotwords` reaches `model.transcribe`.

### Success Criteria

#### Automated Verification:
- [x] Step 3's coexistence script exits 0 in both import orders (or the documented fallback is recorded)
- [x] `uv run python scripts/bench_asr.py` completes over 200 clips and writes `research/asr-benchmark-2026.md`
- [x] `uv run pytest tests/test_asr.py`; full suite and ruff clean
- [x] CI green with `--no-group ml`

#### Manual Verification:
- [x] Dan reads the benchmark table and names primary + fallback; the choice and the numbers go in the PR description
- [x] Live dictation on the primary backend works; switching `asr_backend` works without restart
- [x] Wait 6 minutes idle → `nvidia-smi` shows the model's VRAM released; next press: beep is immediate, text arrives after the load with no lost audio
- [x] A 2-second utterance on a cold model: measure press-to-paste and record it (this is the worst case the 5-minute TTL buys)
- [x] With the HF token file removed → falls back with a warning, no crash

**Implementation Note**: pause for manual confirmation before Phase 4.

---

## Phase 4: Built-in S1-mini cleanup

### Overview
S1-mini in-process via `llama-cpp-python`, prompt built by hand so no template layer can misfile the output; same `Resident` lifecycle; endpoint path kept as the alternative.

### Changes Required

#### 1. Dependencies
**File**: `pyproject.toml` — add `"llama-cpp-python>=0.3.35"` to the `ml` group:
```toml
[[tool.uv.index]]
name = "llama-cu130"
url = "https://abetlen.github.io/llama-cpp-python/whl/cu130"
explicit = true

[tool.uv.sources]
llama-cpp-python = [{ index = "llama-cu130", marker = "sys_platform == 'win32'" }]
```
If the cu130 wheel fails to import (DLL load), try `whl/cu124`, then `whl/cpu`. CPU is an accepted outcome; record which one landed.

#### 2. Cleaner
**File**: `whisper_dictate/s1.py` (new, ~60 lines)
```python
S1_REPO, S1_FILE = "superwhisper/s1-mini-GGUF", "s1-mini-q4_k_m.gguf"
S1_SYSTEM = ("You are a text normalizer for speech-to-text transcripts. The input begins with a "
             "control line specifying the styling, structure, and context settings; clean the "
             "transcript to match those settings and output only the cleaned text.")
STYLING = ("casual", "semi-casual", "semi-formal", "formal")
STRUCTURE = ("prose", "lists")
CONTEXT = ("general", "email")

def build_prompt(text, styling, structure, context) -> str:
    # The empty think block is the documented way to disable thinking. Any other system
    # text makes the model emit one token and stop (measured 2026-09-18).
    return (f"<|im_start|>system\n{S1_SYSTEM}<|im_end|>\n"
            f"<|im_start|>user\n[Styling: {styling}] [Structure: {structure}] [Context: {context}]\n"
            f"{text}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")

class S1Cleaner:
    def __init__(self):                       # llama_cpp / huggingface_hub imported here
        path = hf_hub_download(S1_REPO, S1_FILE)
        try:    self.llm, self.on_gpu = Llama(path, n_gpu_layers=-1, n_ctx=4096, verbose=False), True
        except Exception: self.llm, self.on_gpu = Llama(path, n_gpu_layers=0, n_ctx=4096, verbose=False), False
    def clean(self, text, styling="semi-casual", structure="prose", context="general") -> str:
        out = self.llm(build_prompt(text, styling, structure, context),
                       max_tokens=len(text) // 2 + 64, temperature=0, stop=["<|im_end|>"])
        return out["choices"][0]["text"].strip()
```
`ponytail: inputs over ~1000 tokens are not chunked; p99 dictation is 59 s ≈ 200 tokens, max ever 197 s ≈ 650. Add sentence chunking if one is ever cut off.`

#### 3. Backend selection
**File**: `whisper_dictate/gui.py:1273-1299`
Setting `cleanup_backend` ∈ `{"s1","endpoint","off"}`, default **`"s1"`** (no migration from `llm_enable`; Dan's is `false` and he wants cleanup). `self.s1 = Resident(S1Cleaner, ttl=...)`, warmed on press alongside the ASR. In `_transcribe_and_clean`:
```python
if backend == "s1":
    final_text = self.s1.get().clean(normalized_text, **self._s1_style_for(active_context))
elif backend == "endpoint":
    ...existing clean_with_llm call, unchanged...
```
Load failure → warning + `"off"` for the session. The glossary pre/post passes (`:1267`, `:1302`) stay. The LLM window (`:583`) is retitled "Cleanup" and gets the backend combobox plus three comboboxes for the global `s1_styling` / `s1_structure` / `s1_context`.

#### 4. Per-app control line
**File**: `whisper_dictate/app_prompts.py`, `app_prompt_dialog.py`
A rule (`app_prompts.py:15-16`) may carry `styling`/`structure`/`context` beside `prompt`. `normalize_app_prompts` (`:30-66`) keeps them when valid; new `resolve_app_style(app_prompts, context) -> dict` mirrors `resolve_app_prompt`'s matching order (`:216-243`) and returns only the keys the matching rule sets. The dialog gets three comboboxes. `entries_to_rules` (`:85`) currently drops entries with an empty `prompt` — relax to "prompt or any style key".

#### 5. Tests
**File**: `tests/test_s1.py` (new): `build_prompt` byte-for-byte against a literal (this exact string is the contract that broke on Ollama); `clean` with `Llama` mocked; GPU-init failure → `n_gpu_layers=0`; `resolve_app_style` per-app + fallback. `tests/test_app_prompts.py`: style keys survive normalize → entries → rules. `tests/test_integration.py:324` full-workflow test gains an `s1` variant.

### Success Criteria

#### Automated Verification:
- [x] `uv sync` installs a llama wheel without compiling
- [x] `uv run pytest tests/test_s1.py`; full suite and ruff clean
- [x] `uv run python -c "from whisper_dictate.s1 import S1Cleaner; print(S1Cleaner().clean('so um i need to like send the the report by uh friday no wait make that thursday','semi-formal','prose','general'))"` prints `So I need to send the report by Thursday.`

#### Manual Verification:
- [x] With Ollama stopped, a dictation is cleaned; the log line says GPU or CPU and the latency (GPU ≈ 0.3 s; CPU ≤ 1.5 s for an email-length dictation)
- [x] Rule for `olk.exe`/`outlook.exe` with `context=email` → greeting/sign-off shape in Outlook, not in Notepad
- [x] `cleanup_backend=endpoint` still works against a general model
- [x] After 6 idle minutes both models are gone from `nvidia-smi`; record the combined resident footprint while warm
- [x] One timing of a 20 GB+ Ollama model with whisper-dictate warm vs. unloaded, recorded in the PR

**Parity gate: Phases 1–4 accepted by Dan — reached 2026-09-19**, two months ahead of the 2026-11-22 target and well before the 2026-12-06 renewal.

---

## Phase 5: App presence and cutover

### Overview
Make it behave like an app, then replace Wispr Flow.

### Changes Required

#### 1. The pill is the app
**File**: `whisper_dictate/gui_components.py:45-192`, `gui.py`
`StatusIndicator` gets a right-click (`<Button-3>`) `tkinter.Menu`: Show window · Cleanup settings · Quit. It already binds left-drag (`:91`) and double-click reset (`:94`). Main window: `self.withdraw()` at the end of `__init__` (`gui.py:108`) when `auto_load_model` is on; `WM_DELETE_WINDOW` (`:73`) → `withdraw()` instead of `_on_close`; Quit in the menu calls `_on_close` (`:1026`), which still saves settings. The indicator must be shown at startup rather than on first status update (`gui_components.py:177-186` deiconifies lazily).

#### 2. Startup shortcut
`docs/startup.md` + a three-line PowerShell snippet that creates `whisper-dictate.lnk` in `shell:startup` targeting `uv run --no-sync pythonw -m whisper_dictate.gui` with the repo as working directory. `pythonw` = no console. Confirm `python -m whisper_dictate.gui` works (`gui.py:1374` has the `__main__` guard).

#### 3. Cutover (Dan, one sitting)
1. Quit Wispr Flow; disable its autostart (Task Manager → Startup apps).
2. Automation settings → hotkey `CTRL+WIN`. Restart whisper-dictate.
3. Run the Startup shortcut snippet; sign out and in to prove it.
4. Dogfood for two weeks with Flow still paid for. Request a server-side data export from Wispr before closing the account (open item from 2026-09-17).
5. Cancel Flow before **2026-12-06**. If the parity gate was not reached by 2026-11-22, switch Flow to monthly instead and continue.

### Success Criteria

#### Automated Verification:
- [x] `uv run pytest`, `uv run ruff check .` clean
- [x] `uv run pythonw -m whisper_dictate.gui` starts with no console window

#### Manual Verification:
- [ ] After sign-in: only the pill is visible; Ctrl+Win dictation works; no main window, no console
- [ ] Right-click pill → Show window / Quit work; closing the main window hides it and dictation keeps working
- [ ] Start whisper-dictate manually while it is running → nothing changes, one paste per dictation
- [ ] Ctrl+Win+→ switches virtual desktop and produces "Cancelled", not a locked recording
- [ ] Lone Win tap still opens Start
- [ ] Wispr Flow is not running after a reboot

---

## Phase 6: Vocabulary and history

### Overview
Phonetic glossary rules where they are safe, hotwords where the backend supports them, and a local history that feeds the next round of mining and the next benchmark.

### Changes Required

**Measured 2026-09-19 on the 198-clip corpus, with Dan's 32 live rules:** the
glossary lifts domain-term recall from 86.7% to 91.2% (98 -> 103 of 113),
rescuing 4 clips and breaking none, and it alters the text of only 5 clips in
198. It beats hotwords on every axis - higher recall than the 400-char budget's
90.3%, at no cost to the word error rate. S1-mini cleanup preserved every
glossary fix across all 85 clips containing a domain term, so the second
glossary pass is currently a no-op; it stays as cheap insurance.

#### 1. Phonetic rules, opt-in, 5+ symbol codes
**File**: `whisper_dictate/glossary.py`, `glossary_dialog.py`; add `jellyfish` to runtime deps
`MatchType` (`glossary.py:14`) gains `"phonetic"`. A phonetic rule is valid only if `len(metaphone(trigger_without_spaces)) >= 5`; `GlossaryRule` validation and the dialog refuse shorter ones with the reason ("code `KLT` is too short — it would also match cloud, clod"). `apply` (`:225-235`): regex rules first as today, then phonetic: tokenize with the miner's word regex, slide a window of 1..3 tokens, compare `metaphone("".join(window))` to each phonetic rule's cached code, replace the window. `ponytail: single Metaphone code, exact equality — 'Trey Fax' (TRFKS) will not match threatfax (0RTFKS); add an exact rule for such variants rather than loosening the match.`

#### 2. Hotwords on a Whisper backend
**File**: `whisper_dictate/gui.py`, `glossary.py`
**Decided 2026-09-19 (see `research/asr-benchmark-2026.md`): hotwords stay off globally** - 400 chars cost ~63 extra word errors to rescue 4 domain terms, and 57% of dictations contain no domain term at all. Per-app only, budget 400 chars.

When the active backend is Whisper: `hotwords` = per-app list from `~/.whisper_dictate/hotwords_by_app.json` (keyed by process stem; Dan copies `mined/hotwords_by_app.json` there once), else `hotwords.txt`, plus glossary replacement strings, trimmed to 800 chars (move the miner's `budget()` into `glossary.py`). `initial_prompt` (setting, `gui.py:1252`) and hotwords share Whisper's prompt context; log the final string length once per dictation at DEBUG. Cohere ignores hotwords.

#### 3. History: text forever, 14 days of audio
**File**: `whisper_dictate/history.py` (new, ~40 lines), `gui.py`
Append one JSON line per dictation to `~/.whisper_dictate/history.jsonl`: `ts`, `app` (**process name only — no window title, no URL**), `asr_backend`, `cleanup_backend`, `raw`, `cleaned`, `final`, `asr_ms`, `cleanup_ms`, `cold`, `audio_file`. Save the clip as 16-bit WAV (`wave`, stdlib) to `~/.whisper_dictate/audio/<ts>.wav`; at startup delete WAVs older than 14 days (text lines stay; their `audio_file` simply dangles). Settings `history_enable` (default true) and `history_audio_days` (default 14, 0 = no audio), with the same privacy wording as the debug-log warning (`gui.py` LLM window). `scripts/bench_asr.py` gains `--history` to benchmark against this archive instead of the Flow export.

#### 4. Tests
`tests/test_glossary.py`: `threat fax`/`Threat Fox`/`thread fax` → `threatfax` from one phonetic rule; a rule for `Claude` is rejected as phonetic; ordinary words untouched; regex rules run first. `tests/test_history.py`: one append is valid JSONL with no `title` key; disabled writes nothing; pruning removes only old WAVs.

### Success Criteria

#### Automated Verification:
- [ ] `uv run pytest`, `uv run ruff check .` clean
- [ ] `uv run python -c "from jellyfish import metaphone as m; assert m('threatfax')==m('threatfox')==m('threadfax')=='0RTFKS'; assert m('treyfax')!='0RTFKS'; print('ok')"`

#### Manual Verification:
- [ ] One phonetic rule `threatfax` fixes "threat fax" and "Threat Fox"; the dialog refuses to make `Claude` phonetic
- [ ] On a Whisper backend, the log shows the per-app hotword string; "Traefik" in the Claude window transcribes without a glossary rule
- [ ] `history.jsonl` grows one line per dictation with no window titles; a WAV appears per dictation; a WAV back-dated 15 days disappears on next launch

---

## Testing Strategy

- **Pure logic first, tested without Windows:** `Chord.feed`/`swallows`, `parse_chord`, `build_prompt` (byte-exact), clipboard format filter, `Resident`, phonetic validation/apply, `resolve_app_style`, history append/prune, benchmark WER function.
- **Heavy/OS modules lazy-imported and mocked at the import site**, following `tests/test_app_context.py` and `patch("whisper_dictate.llm_cleanup.OpenAI")`.
- **Real-Windows tests where cheap:** clipboard round-trip (`skipif` non-win32). CI runs on `windows-latest`, so it executes there too.
- **Integration:** extend `tests/test_integration.py:324` with `s1` and mocked-ASR-backend variants.
- **Manual per phase:** the checklists above, run by the Windows-native session where it can (it can launch the app and read logs) and by Dan where a human ear, eye or microphone is needed.

## Performance Considerations

- Targets: release-to-paste ≤ 1.5 s for a 10 s utterance, warm. Cold: beep immediate, no audio lost, wait = `max(0, load − utterance)`.
- The `WH_KEYBOARD_LL` proc must always return in well under 300 ms: set update + `after(0)`, nothing else.
- Idle TTL 5 min ⇒ ~4.5 cold starts/day (35.5% of dictations); reload time is a scored benchmark criterion for that reason.
- Unloading frees weights, not the CUDA context (a few hundred MB stays for the process lifetime).

## Settings added

`restore_delay` (0.6), `asr_backend` (benchmark winner), `idle_ttl_minutes` (5), `cleanup_backend` ("s1"), `s1_styling` ("semi-casual"), `s1_structure` ("prose"), `s1_context` ("general"), `history_enable` (true), `history_audio_days` (14). All optional with defaults; `set_if_present` (`gui.py:902`) tolerates their absence. `hotkey` default `"CTRL+SPACE"` until cutover, then `"CTRL+WIN"`. Rollback per phase = revert the PR; nothing migrates data destructively.

## References

- Pipeline: `gui.py:1217-1330`; paste: `:1309-1327`; hotkey: `:1164-1185`, `:842-861`, `hotkeys.py:65-177`; model load: `:1135-1162`, `:796-840`; settings load/save: `:877-1024`; mic: `audio.py:41-87`
- Whisper hotwords: `faster_whisper/transcribe.py` — `hotwords` parameter of `transcribe`, truncation in `get_prompt` (`max_length // 2`)
- Prior research merged in Phase 0: `research/phase2-investigation-summary.md`, `docs/transcription-optimization.md`
- Miner and outputs: `scripts/mine_wispr_history.py`; `C:\Users\Dan Williams\wispr-flow-export\mined\`
- Superwhisper clipboard investigation (method, `clipwatch.ps1`, Flow's 556 ms trace): Claude Docs artifact `88f3abeb-9d65-4de2-b185-806497dd525d`
- Flow's shortcut map (LCtrl+LWin = `ptt`): `%APPDATA%\Wispr Flow\config.json` → `prefs.user.shortcuts`
- Model cards: https://huggingface.co/CohereLabs/cohere-transcribe-03-2026 · https://huggingface.co/superwhisper/s1-mini · https://huggingface.co/superwhisper/s1-mini-GGUF
- Wheels: https://download.pytorch.org/whl/cu128/torch/ · https://abetlen.github.io/llama-cpp-python/whl/cu130/llama-cpp-python/
- AutoMem: `41e5d84a` (grill decisions), `4fe9736c` (measurements), `13d04057` (open weights), `a97c5e3a`/`4f7471ef` (S1-mini on Ollama), `3fbe1394` (vocabulary architecture), `298b8675` (repo gaps)
