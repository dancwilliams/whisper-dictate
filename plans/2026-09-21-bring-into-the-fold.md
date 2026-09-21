# Bring whisper-dictate into the fold — Implementation Plan

Written against `main` at `1974cd4`. Source: `advisor-plans/intake-2026-09-21.md` (the
intake report) and `standards.md` as ruled on 2026-09-21 (dan-skills 1.2.20).

## Overview

The intake found one tier 1 blocker, nine tier 2 deviations, seven confirmed bugs and
about 330 lines that can go. This plan clears all of it in six phases, one PR each, in
the order the report's section 7 gives: make the typecheck gate real, put tests under
`gui.py`, fix the small bugs, fix the data-loss and threading bugs, bring docs and repo
settings into line, then delete.

## Ground rules for the implementer

- `uv` for everything: `uv run pytest`, `uv run ruff check .`, `uv run mypy whisper_dictate`. Never bare `python`, `pip` or `pytest`.
- CI excludes the heavy ML wheels. Locally the `.venv` has them; do not run `uv sync` with different groups and leave the venv changed.
- One branch and one PR per phase, targeting `main`. `main` stays green after every merge. Do not start a phase until the previous PR is merged.
- No AI attribution in commits or PR text. Commits are GPG-signed; if signing fails, stop and tell Dan to cache the key. Never `--no-gpg-sign`.
- Windows-only app. Tests mock Win32, `sounddevice`, the recognizer and the OpenAI client. Keep it that way.
- Match the code around you. `gui.py` comments explain why, not what; keep that register.
- Line numbers below are from `1974cd4`. If a line has moved, find the quoted code, do not trust the number.
- One GitHub settings change (branch protection, Phase 1 step 4) is outward-facing. Show Dan the exact command and wait for a yes before running it. Dependabot needs no settings change; it is a committed file.

## Current State Analysis

Measured on 2026-09-21 with `uv run --no-sync` in the existing `.venv`:

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | pass |
| `mypy whisper_dictate` | **15 errors in 8 files** |
| `pytest` | 342 passed, 1 skipped, 51% coverage; `gui.py`, `app_prompt_dialog.py`, `glossary_dialog.py` at 0% |
| CI on `main` | green, because `ci.yml:54` sets `continue-on-error: true` on the mypy job |
| Python 3.13, throwaway venv | locked deps install, 341 passed, 2 skipped |
| Python 3.14, throwaway venv | locked deps install, **collection fails** in `tests/test_llm_debug_logging.py` (`TypeError: _eval_type() got an unexpected...`) |

### Key Discoveries

- `make check` runs `typecheck` with no escape (`Makefile:46-50`), so it fails locally while CI is green. `CLAUDE.MD` calls it "exactly what CI runs".
- `gui.py:1603` reads `self._status_state`. Nothing assigns it (one grep hit in the repo). `_set_status` (`gui.py:974-982`) stores no state.
- A blank `DoubleVar` raises `tkinter.TclError`, which is not a `ValueError` or `OSError` (reproduced). `_on_close` (`gui.py:1157`) catches only `OSError, UnicodeEncodeError, ValueError`, and its `finally` marks settings saved.
- `_deliver` (`gui.py:1651-1691`) reads `var_paste_delay` at `:1675` and `var_restore_delay` at `:1687`, after `clipboard.set_text` at `:1665`, with no `try/finally` around `restore`.
- The fix pattern for the threading bug is already in the file: `_capture_asr_config` and `_capture_s1_style` (`gui.py:1606-1612`) copy Tk values on the main thread for a worker to use. The rule is stated at `gui.py:108-110`.
- `_transcribe_and_clean` runs on a thread (`gui.py:1471`) and reads 20-odd Tk variables (`:1499-1521`, `:1536`, `:1545-1564`, `:1581-1593`), calls `messagebox.showerror` (`:1526`), writes `txt_out` (`:1598-1599`), and `_clean_with_s1` sets `var_cleanup_backend` (`:1637`).
- `settings_store._store_secure_settings` (`settings_store.py:113-121`) skips empty values; `credentials.delete_credential` (`credentials.py:89`) has no caller outside tests.
- Settings are saved from two places only: `_on_close` (`gui.py:1156`) and the `finally` after `mainloop` (`gui.py:1750-1751`). `save_settings` writes in place (`settings_store.py:75`); `load_settings` returns defaults on a parse error (`settings_store.py:53-58`), and the next save overwrites the real file.
- `gui.py:1122-1129` persists `window_title` for each recent process; the UI at `gui.py:463-464` says "window titles are never stored". The titles feed the per-app prompt dialog's prefill (`app_prompt_dialog.py:66-69`).
- Automation window: the "History" heading is gridded at `row=11` (`gui.py:436-438`) and the "Startup" heading at `row=6` (`gui.py:474-476`). They are swapped; History's controls sit at rows 7-9 and Startup's at 12+.
- `tests/test_settings_store.py` replaces `SETTINGS_FILE` with a `MagicMock` path and asserts on `write_text`. An atomic write changes what those tests must assert.
- CI check names, needed for branch protection: `Lint (ruff)`, `Type checking (mypy)`, `Test (Python 3.11)`, `Test (Python 3.12)`. `build-windows.yml` is `workflow_dispatch` only and is not a required check.

## Desired End State

`/repo-intake quick` on the merged result reports: no tier 1 blocker, no tier 2 FAIL,
and B1-B7 gone. Concretely:

- `make check` passes locally and means the same thing as CI. The mypy job blocks.
- CI tests 3.11, 3.12 and 3.13. `main` requires those checks and refuses force-push and deletion.
- `gui.py`'s dictation pipeline has tests, and the worker thread reads no Tk variable and touches no widget.
- A failed delivery stays visible. The clipboard is restored on every path. Settings survive a crash, a blank field and a corrupt file. A cleared API key is gone from the keyring. Window titles are not written to disk.
- Docs say what the code does. uv is the only documented install path. The README names the Hugging Face download.
- `pillow`, the dead functions and the leftover files are gone.

## What We're NOT Doing

- **Not removing the ReDoS guard** on per-app window-title regexes (`app_prompts.py:128-239`). It is a security measure; the report recommends against the cut.
- **Not collapsing the audio queue and collector thread** (`audio.py`) into a direct append. It changes the real-time path and has no test to protect it.
- **Not chasing the ten unconfirmed leads** in report section 4 (Resident race, overlapping dictations, hook timeout, double hooks, last audio chunk, loader `ImportError`, OpenAI retries, unbounded `history.jsonl`, `print` under `pythonw`). If a fix here touches one, note it in the PR; do not expand scope.
- Not adding a numeric coverage floor (standards 2.7: none).
- Not making mypy strict (standards 2.6: non-strict).
- Not adding Python 3.14 to the matrix. It fails at collection today; that is a dependency problem, not this plan's.
- Not rewriting git history for old attribution trailers (standards 2.15 is forward-only).
- Not splitting `gui.py` into modules. Phase 2 extracts only what tests need.
- Not adding repo hooks or a regulated-data gate (standards 1.3, 2.16: N/A here).

## Implementation Approach

Verification first. Phase 1 makes the existing gate honest, so every later PR is checked
by lint, format, types and tests on three Pythons. Phase 2 puts characterization tests
under the pipeline before anything risky changes it. Bugs then go smallest-first. Docs
come after the code they describe has stopped moving, and deletions go last so they are
made against tested code.

The threading fix (B6) and the worker half of the blank-field bug (B2) are one change: a
settings snapshot taken on the Tk thread and handed to the worker. Once the worker reads
a plain dict, it cannot raise `TclError` and cannot touch Tk.

---

## Phase 1: Make the typecheck gate real

Branch: `fix/mypy-gate`. Clears standards 1.5 and 2.6, and 2.8.

### Changes Required

#### 1. Fix the 15 mypy errors

No behaviour change in any of these.

| Site | Fix |
|---|---|
| `glossary.py:240`, `glossary_dialog.py:294` | `match_type` arrives as `str`. Narrow it: if the value is in `typing.get_args(MatchType)` use `cast(MatchType, value)`, else `"phrase"`. One small helper in `glossary.py` next to `MatchType` (`glossary.py:14`), used at both sites. |
| `app_context.py:15-16` | Annotate once above the `if`: `USER32: ctypes.WinDLL \| None` and `KERNEL32: ctypes.WinDLL \| None`. If mypy then complains at the call sites, those functions already return early off-Windows; add the `assert USER32 is not None` the early return implies rather than restructuring. |
| `gui_components.py:43` | `self.result` is inferred as `None`. Declare `self.result: str \| None = None` where it is first assigned in `PromptDialog.__init__`. |
| `glossary_dialog.py:20`, `:191`; `app_prompt_dialog.py:17`, `:220`; `gui_components.py:11` | Dialog parents are typed `tk.Tk` but receive a `Toplevel`. Change the annotation to `tk.Misc`. Clears `glossary_dialog.py:118`, `:129` and `app_prompt_dialog.py:171`, `:190`. |
| `settings_store.py:52` | `settings: dict[str, Any] = json.loads(...)` at `:42`. |
| `llm_cleanup.py:127` | Type `messages` as `list[ChatCompletionMessageParam]` (import under `TYPE_CHECKING` from `openai.types.chat`). If the overload still does not resolve because of `stream_options`, use one `# type: ignore[call-overload]` with a comment naming the openai version it was seen on. |
| `app_prompt_dialog.py:30` | `_prepare_recent_entries` takes `list[str \| dict[str, str \| None]]`; `list` is invariant. Change the parameter to `Sequence[str \| dict[str, str \| None]]` (`:139`). |
| `app_prompt_dialog.py:69` | `label` is `str \| None`. `label = entry["process_name"] or ""` at `:66`. |
| `app_prompt_dialog.py:170` | `initial = initial or None` rebinds a `dict[str, str]`. Annotate `initial: dict[str, str] \| None` at its first assignment. |
| `gui.py:1649` | `cleaned: str \| None = cleaner.clean(...)` at `:1634`. |

#### 2. CI
**File**: `.github/workflows/ci.yml`
- Delete `continue-on-error: true` (`:54`).
- Matrix (`:62`): `["3.11", "3.12", "3.13"]`.

#### 3. Docs that this makes true
**File**: `CLAUDE.MD` — the line at `:151` already says 3.11/3.12/3.13; leave it. Nothing else here; the docs pass is Phase 5.

#### 4. Branch protection (standards 2.17) — after this PR is merged and green
Show Dan this and wait for a yes:

```bash
gh api -X PUT repos/dancwilliams/whisper-dictate/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["Lint (ruff)", "Type checking (mypy)", "Test (Python 3.11)", "Test (Python 3.12)", "Test (Python 3.13)"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
```

`enforce_admins: false` keeps Dan able to merge his own PRs; no reviewers are required on a solo repo.

### Success Criteria

#### Automated Verification:
- [x] `uv run mypy whisper_dictate` exits 0
- [x] `make check` exits 0 (run as its four commands: `make` is not installed on the Windows dev box)
- [x] `uv run pytest` — 343 passed, 1 skipped
- [x] `git grep -n "continue-on-error" .github/` returns nothing
- [x] CI on the PR shows five checks, all green, including `Test (Python 3.13)` (PR #62)
- [x] After step 4: `gh api repos/dancwilliams/whisper-dictate/branches/main/protection -q '.required_status_checks.contexts | length'` prints `5`

#### Manual Verification:
- [ ] The app launches and a dictation pastes (nothing here should change behaviour; this is the smoke test for the annotations)
- [ ] Dan confirms the branch protection command before it runs

**Implementation Note**: pause here for Dan's confirmation before Phase 2.

---

## Phase 2: Tests under the dictation pipeline

Branch: `test/gui-pipeline`. Clears standards 2.7. Characterization tests: they pin what
the code does today, including B1 and B2, so the later fixes flip a known assertion
instead of changing untested code.

### Changes Required

#### 1. A Tk-free harness
**File**: `tests/test_gui_pipeline.py` (new)

`import whisper_dictate.gui` runs `set_cuda_paths()` and `setup_logging()` at import
(`gui.py:58-61`). Both are safe to run in tests; if either proves not to be on CI, patch
them in a module-level fixture rather than moving them.

Build the app without Tk: `app = gui.App.__new__(gui.App)`, then set only the attributes
the method under test reads, using `MagicMock` for `var_*` (`.get.return_value = ...`),
`txt_out`, `btn_toggle`, `lbl_status`, `indicator`, `hotkey_manager`, and real objects for
`recent_processes` (a `deque`) and `app_prompts`. Patch `gui.audio`, `gui.clipboard`,
`gui.app_context`, `gui.history`, `gui.llm_cleanup`, `gui.time.sleep`, `gui.messagebox`.
One fixture, `make_app()`, returns the wired object. No Tk display is needed, so these
run on CI unlike `test_gui_components.py`.

#### 2. The tests

| Test | Pins |
|---|---|
| `_deliver` happy path | order is `snapshot`, `set_text`, `send_paste`, `restore(saved)` |
| `_deliver` when `set_text` raises `ClipboardError` | status is `error`, no paste, no restore attempted (nothing was overwritten) |
| `_deliver` when `snapshot` raises | text still set and pasted, `restore` not called |
| `_deliver` when `send_paste` returns `False` | status `error`, `restore` still called |
| `_deliver` when the delay variable raises `TclError` | **today: propagates and `restore` is never called.** Mark `xfail(strict=True, reason="B2, fixed in phase 4")` asserting the desired behaviour (restore called) |
| `_transcribe_and_clean`, no audio | status `warning`, nothing delivered |
| `_transcribe_and_clean`, empty transcript | status `warning`, nothing delivered |
| `_transcribe_and_clean`, endpoint cleanup raises `LLMCleanupError` | raw text delivered; **desired: final status stays `warning`.** `xfail(strict=True, reason="B1, fixed in phase 3")` |
| `_transcribe_and_clean`, transcription raises `RuntimeError` | status `error`, `messagebox.showerror` called, nothing delivered |
| hotkey press/release under `TAP_SECONDS` | recording stays on, status "locked" |
| hotkey press/release over `TAP_SECONDS` | `_stop_and_transcribe` called |
| `_on_hotkey_cancel` while recording | buffer discarded, status "Cancelled" |
| `_record_recent_process` | dedupes on process plus title, newest first, capped at `RECENT_PROCESSES_MAX` |
| `_on_close` when `_save_settings` raises `TclError` | **desired: `_settings_saved` stays False.** `xfail(strict=True, reason="B2, fixed in phase 4")` |

`strict=True` matters: when a later phase fixes the bug, the xfail turns into a failure
until the marker is removed, so the fix cannot land without the test being switched on.

### Success Criteria

#### Automated Verification:
- [x] `uv run pytest tests/test_gui_pipeline.py -v` — 13 passed, 3 xfailed
- [x] `uv run pytest` coverage line for `whisper_dictate\gui.py` is above 0% (21%) and `_deliver` / `_transcribe_and_clean` lines appear as covered
- [x] `make check` exits 0 (run as its four commands)
- [x] No test in the new file creates a `Tk()` (grep the file for `Tk(`)

#### Manual Verification:
- [ ] None. No production code changes in this phase.

---

## Phase 3: Small bugs

Branch: `fix/small-bugs`. B1, B3, B5, B7. Independent of each other; one commit each.

### Changes Required

#### 1. B1 — warnings survive to the end of a dictation
**File**: `whisper_dictate/gui.py`
- In `_set_status`, main-thread branch (`:979`): `self._status_state = state`.
- In `__init__` beside `_press_at` (`:115`): `self._status_state = "ready"`, and replace the `getattr(self, "_status_state", "ready")` at `:1603` with the plain attribute.
- At the top of `_transcribe_and_clean`: nothing to reset. `_stop_and_transcribe` already sets `transcribing` (`:1469`), which overwrites the previous dictation's state.
- The "Pasted into active window" status at `:1679` is `ready`, so a paste after an LLM warning would clear the warning. Keep the warning: only set the pasted status when `self._status_state not in {"error", "warning"}`.
- Remove the B1 `xfail` from Phase 2.

#### 2. B3 — a cleared API key is deleted
**File**: `whisper_dictate/settings_store.py`, `_store_secure_settings` (`:107-121`)
- When `key in settings` and the value is a blank string, call `credentials.delete_credential(credential_key)`; catch `CredentialStorageError` and log a warning. When the key is absent from the dict, do nothing (a partial save must not delete).
- Check `credentials.delete_credential` (`credentials.py:89-114`) for how it treats "not found"; the tests at `tests/test_credentials.py:113` show it is tolerated. If it raises instead, catch it here.
**File**: `tests/test_settings_store.py` — two cases: blank value deletes; absent key does not.

#### 3. B5 — window titles are not written to disk
**File**: `whisper_dictate/gui.py`
- `_save_settings` (`:1122-1129`): save `"recent_processes": [e["process_name"] for e in self.recent_processes]`, de-duplicated in order. In-memory entries keep their titles for the session, so the per-app dialog still prefills titles for windows dictated into since launch.
- `_load_settings` (`:995-1011`) already accepts a list of strings, and accepts the old dict form. Keep the dict branch so an existing settings file loads, but pass `None` for the title so old titles are dropped from memory too; the next save removes them from disk.
- The sentence at `gui.py:463-464` is now true. Leave it.
**File**: `tests/test_gui_pipeline.py` — `_save_settings` writes no `window_title` key (assert on the dict handed to `settings_store.save_settings`).

#### 4. B7 — headings
**File**: `whisper_dictate/gui.py` — "History" heading `row=11` to `row=6` (`:437`); "Startup" heading `row=6` to `row=11` (`:475`).

### Success Criteria

#### Automated Verification:
- [x] `uv run pytest` passes with the B1 xfail marker removed (360 passed, 1 skipped, 2 xfailed)
- [x] `git grep -n "_status_state" whisper_dictate/` shows an assignment, not only the read
- [x] `git grep -n "delete_credential" whisper_dictate/` shows a caller in `settings_store.py`
- [x] `make check` exits 0 (run as its four commands)

#### Manual Verification:
- [x] Settings → Automation: "History" sits above the history controls, "Startup" above the startup controls
- [x] With Notepad's clipboard held by another app (or the endpoint unreachable with cleanup on), the pill stays amber/red after the dictation instead of going green
- [x] Enter an API key, quit, relaunch: key is there. Blank it, quit, relaunch: field is empty, and `cmdkey /list` (or Credential Manager) no longer shows the entry
- [x] Dictate into two apps, quit, open `%USERPROFILE%\.whisper_dictate\whisper_dictate_settings.json`: `recent_processes` is a list of process names with no titles

**Implementation Note**: pause here for Dan's confirmation before Phase 4.

---

## Phase 4: Data-loss bugs and the threading rule

Branch: `fix/pipeline-safety`. B2, B4, B6. This is the risky phase; Phase 2's tests are
the net.

### Changes Required

#### 1. B6 and the worker half of B2 — snapshot settings on the Tk thread
**File**: `whisper_dictate/gui.py`
- Add `_capture_dictation_config(self) -> dict[str, Any]`, modelled on `_capture_s1_style` (`:1606`). It reads every Tk variable `_transcribe_and_clean`, `_clean_with_s1` and `_deliver` use today, through one safe getter:

```python
def _num(self, var, default: float) -> float:
    """A blank or half-typed Spinbox raises TclError; fall back, do not crash."""
    try:
        return float(var.get())
    except (TclError, ValueError):
        return default
```

  Defaults are the values the variables are created with (`gui.py:171-208`), not new numbers. Import `TclError` from `tkinter`.
- `_stop_and_transcribe` (`:1466`) runs on the Tk thread: call `_capture_dictation_config()` there and pass the dict to the worker: `threading.Thread(target=self._transcribe_and_clean, args=(cfg,), daemon=True)`.
- `_transcribe_and_clean(self, cfg)`, `_clean_with_s1(..., cfg)` and `_deliver(text, cfg)` read `cfg[...]` only. No `self.var_*` access remains in any of the three.
- Widget and dialog work from the worker goes through `self.after(0, ...)`:
  - `messagebox.showerror("Transcribe", ...)` (`:1526`)
  - `self.txt_out.insert` / `.see` (`:1598-1599`) — one small `_append_transcript(text)` method, called via `after`
  - `self.var_cleanup_backend.set("off")` (`:1637`)
- `_record_recent_process` (`:1482`) touches only a `deque`; it may stay on the worker.
- Known ceiling, to be marked in the code: `self.glossary_manager`, `self.app_prompts` and `self.prompt_content` are plain Python objects replaced (not mutated) by the dialogs on the Tk thread, so the worker sees either the old or the new object. Add `# ponytail: read without a lock; safe while dialogs replace these objects rather than mutate them`.

#### 2. B2 — clipboard always restored
**File**: `whisper_dictate/gui.py`, `_deliver`
- Everything after a successful `set_text` goes in `try:`, with the restore in `finally:` (skipped when `saved is None`). The restore delay sleep stays inside the `finally` before `restore`, so the target app still has time to read the text.

#### 3. B2 — Quit does not lose settings
**File**: `whisper_dictate/gui.py`
- `_save_settings` (`:1092-1143`): use `_num` for every numeric variable, so a blank field saves its default instead of raising.
- `_on_close` (`:1153-1164`): add `TclError` to the except clause, and set `_settings_saved = True` only when `_save_settings` returned without raising, so the fallback in `main()` (`:1750`) still gets its chance.

#### 4. B4 — settings survive a crash and a corrupt file
**File**: `whisper_dictate/settings_store.py`
- `save_settings` (`:75`): write to `SETTINGS_FILE.with_suffix(".json.tmp")`, then `os.replace(tmp, SETTINGS_FILE)`.
- `load_settings` (`:53-58`): on `JSONDecodeError` or `UnicodeDecodeError`, copy the bad file to `SETTINGS_FILE.with_suffix(".json.bak")` before returning defaults, and log at error level with the `.bak` path. Return a flag the GUI can see: add a module-level `last_load_error: str | None`.
**File**: `whisper_dictate/gui.py`
- After `_load_settings` in `_build_ui`, if `settings_store.last_load_error` is set, show it once through `_set_status("warning", "Settings file was unreadable; using defaults. Backup kept.")`. No dialog: the app may be starting hidden at login.
- Save when the user finishes editing, not only on Quit: call `self._save_settings()` at the end of `_close_window` (`:254`) and after a non-`None` result in `_open_app_prompt_dialog` (`:1215`). The prompt and glossary dialogs already write their own files (`:1188`, `:1200`).
**File**: `tests/test_settings_store.py`
- The existing save tests assert `write_text` on a `MagicMock` path. Rewrite the save tests against a real `tmp_path` file (monkeypatch `SETTINGS_FILE` to `tmp_path / "s.json"`); assert the file content and that no `.tmp` is left behind.
- New: a corrupt file produces a `.bak` with the original bytes, `load_settings` returns defaults, and a following `save_settings` does not touch the `.bak`.

#### 5. Docs that this makes true
**File**: `docs/architecture.md:224-234` — the threading section: main thread runs Tk and receives hook events via `after`; transcription, cleanup and delivery run on a worker that reads a settings snapshot and never touches Tk.

#### 6. Remove the two B2 `xfail` markers from Phase 2.

### Success Criteria

#### Automated Verification:
- [x] `uv run pytest` passes with no `xfail` left in `tests/test_gui_pipeline.py` (`git grep -n xfail tests/test_gui_pipeline.py` returns nothing) — 369 passed, 1 skipped
- [x] A test asserts the worker path reads no Tk variable: build the app with every `var_*` as a `MagicMock` whose `.get` raises, call `_transcribe_and_clean(cfg)`, and it completes
- [x] `git grep -nE "self\.var_\w+\.(get|set)\(" whisper_dictate/gui.py` shows no hit inside `_transcribe_and_clean`, `_clean_with_s1` or `_deliver`
- [x] `make check` exits 0 (run as its four commands)

#### Manual Verification:
- [x] Settings → Automation: clear "Paste delay" and leave it blank. Copy a sentence to the clipboard, dictate into Notepad: the dictation pastes, and a moment later Ctrl+V pastes the original sentence
- [x] With that field still blank, change the hotkey, then Quit from the pill. Relaunch: the new hotkey is there, paste delay is back to 0.15
- [x] Change a per-app prompt, close the dialog, kill the process from Task Manager. Relaunch: the prompt is there
- [x] Quit. Put a stray `x` at the top of the settings JSON. Launch: status shows the unreadable-settings warning, a `.json.bak` sits beside the file with the `x` in it. Quit and relaunch: still running on defaults, `.bak` unchanged
- [x] Open Edit → Prompt (modal), press the hotkey and dictate while it is open: the app does not hang
- [x] Ten dictations in a row into Notepad, alternating hold and tap-lock: all paste, none hangs

**Implementation Note**: pause here for Dan's confirmation before Phase 5.

---

## Phase 5: Docs and repo hygiene

Branch: `chore/standards`. Clears standards 2.1, 2.12, 2.15, 2.18, 2.19, 2.24, 1.1.

### Changes Required

#### 1. uv is the only documented path (2.1)
- `CONTRIBUTING.md:57-58`: delete the "Or if you don't have uv, use pip" lines. `:67-68`: delete the "Using standard Python" variant.
- `docs/build.md:18-23`: delete the venv-plus-pip alternative and the sentence introducing it.
- Grep for stragglers: `git grep -nE "pip install|python -m (venv|pip)" -- '*.md'`.

#### 2. `CLAUDE.MD` matches the code (2.12)
- Settings example: replace with the real keys. Take them from `_save_settings` as it stands after Phase 4; do not hand-copy from this plan. Known wrong today: `llm_api_key`, `use_glossary`, `compute_type`, `floating_indicator`, `llm_enabled`, and `app_prompts` shown as a list with `window_title_pattern` (it is a map keyed by process name with `window_title_regex`).
- Main GUI class is `App`, not `WhisperDictateGUI` (two places).
- Prompt file path: `~/.whisper_dictate/whisper_dictate_prompt.txt` (`prompt.py:7`).
- "Integration tests cover full pipelines (audio → transcription → LLM → paste)": reword to what is true after Phase 2. `test_integration.py` covers context, prompts, glossary and cleanup; `test_gui_pipeline.py` covers the dictation pipeline and delivery.
- "All jobs must pass": now true; leave it.
- Remove the pillow line from Dependencies (step 5).
- Check every name in the module table against the code: `git grep -n "def parse_hotkey_string\|class HotkeyManager\|class StatusIndicator\|class PromptDialog"` and fix what does not exist.
- "Recent Changes" lists commits from 2025; replace with nothing. `git log` is the record.

#### 3. Attribution policy (2.15)
**File**: `CLAUDE.MD`, under "Git Workflow": "Attribution: none. Commits and PRs carry no AI or assistant attribution. Adopted 2026-09-21; earlier history is left as is."

#### 4. README names its network use (2.24)
**File**: `README.md`, near `:13` and `:291`: keep "transcription is local"; add that the first use of a model downloads it from Hugging Face into `~/.cache/huggingface`, that nothing is downloaded after that (`asr.py:61`, `s1.py:59` try the cache first), and that the Cohere recognizer needs a Hugging Face token (`asr.py:44`). State what works with no network at all: everything, once the models are cached and cleanup is off or local.

#### 5. Dependencies (2.19)
**File**: `pyproject.toml`
- Remove `"pillow>=12.0.0"` (`:19`). Nothing imports it: `git grep -nE "PIL|[Pp]illow|PhotoImage|iconbitmap|iconphoto" -- '*.py' '*.spec'` is empty. Run `uv lock`.
- `ctranslate2>=4.8.2` (`:12`) is never imported. Find why it is pinned: `git log -S"ctranslate2" --format="%h %ad %s" --date=short -- pyproject.toml`. If the commit gives a reason (a cuDNN 9 floor is likely), put it in a comment above the line, in the style of the librosa comment at `:38-40`. If no commit gives one, remove the pin, run `uv lock`, and check the resolved `ctranslate2` version did not drop below 4.8.2; if it did, restore the pin with the comment "floor: faster-whisper alone resolves lower".
- After the pillow removal, build once: `USE_UV=1 make build-exe`. The spec sets the icon through PyInstaller; confirm the exe still has its icon.

#### 6. Dependabot (2.18)
**File**: `.github/dependabot.yml` (new)

```yaml
version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/"
    schedule: { interval: "weekly" }
    groups:
      python: { patterns: ["*"] }
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly" }
    groups:
      actions: { patterns: ["*"] }
```

#### 7. Secret scan (1.1)
- Dan installs gitleaks once: `winget install gitleaks`.
- Run `gitleaks detect --source . --redact -v` (tree and history). Expected: no leaks; the intake's grep of HEAD and history found none. If it reports anything, stop: do not paste the value anywhere, tell Dan the `file:line` and credential type, and rotation comes before any history surgery.

### Success Criteria

#### Automated Verification:
- [x] `git grep -nE "pip install|python -m (venv|pip)" -- '*.md'` returns nothing (outside `plans/`, `advisor-plans/` and `research/`, which quote the old text)
- [x] `git grep -n "WhisperDictateGUI\|llm_api_key\|use_glossary\|floating_indicator\|window_title_pattern" -- CLAUDE.MD` returns nothing
- [x] `git grep -n -i "pillow" -- pyproject.toml CLAUDE.MD` returns nothing; `uv lock --check` exits 0
- [x] `git grep -n -i "hugging" README.md` returns at least one line
- [x] `gitleaks detect --source . --redact` exits 0 (130 commits, no leaks)
- [x] `make check` exits 0 (run as its four commands); CI green (PR #66, five checks)

#### Manual Verification:
- [x] `dist/whisper-dictate-gui.exe` (one-file build) launches and shows its icon — built 2026-09-21, PyInstaller exit 0
- [ ] A week after merge, one grouped Dependabot PR has appeared (or `gh api repos/dancwilliams/whisper-dictate/dependabot/alerts` responds, showing the ecosystem is recognised)
- [x] Dan reads the new README paragraph and agrees it is what he wants users told

---

## Phase 6: Deletions

Branch: `chore/deletions`. Report section 5, items 1-14, minus the two exclusions. One
commit per item so any one can be reverted. Before deleting any symbol, re-run the grep
given; this plan's greps are from `1974cd4`.

### Changes Required

| # | Cut | Where | Check before cutting |
|---|---|---|---|
| 1 | Nine near-identical spinbox blocks become one table and one loop | `gui.py:509-661` | Open the window before and after; every control present, same order, same ranges |
| 2 | Module singleton and six wrappers in `audio.py`; `gui.py` holds `self.recorder = audio.AudioRecorder()` and calls methods. Delete the stale note at `gui.py:76` | `audio.py:158-204`; callers `gui.py:965`, `:1410-1475`, `:1756` | `git grep -n "audio\.\(start_recording\|stop_recording\|get_audio_buffer\|is_recording\|prewarm\|recorder_loop\)"`; update `tests/test_audio.py:167-212` and the Phase 2 patches |
| 3 | One `SETTINGS = [(key, var_name, cast), ...]` table drives both load and save | `gui.py:1024-1084`, `:1094-1143` | Round-trip test: save, load into a fresh app, every value equal. Keep `_num` from Phase 4 |
| 4 | Recent-process entries normalised once, in `_record_recent_process`; delete `_format_recent_processes_for_dialog` and the re-filter in the dialog | `gui.py:1166-1178`, `:1721-1733`; `app_prompt_dialog.py:139-155` | Phase 2's `_record_recent_process` test |
| 5 | `load_saved_glossary`, `write_saved_glossary`, `to_legacy_text` | `glossary.py:427-454`, `:360-368` | `git grep -n "load_saved_glossary\|write_saved_glossary\|to_legacy_text" -- whisper_dictate scripts packaging` shows definitions only; delete their tests (`tests/test_glossary.py:14-48`) |
| 6 | `is_credential_stored`; the one-entry `_get_credential_key` map (use `credentials.LLM_API_KEY`); the duplicated `except KeyringError` / `except Exception` pairs | `credentials.py:140`, `:48-54`, `:80-86`, `:108-114`; `settings_store.py:144-157` | `delete_credential` now has a caller (Phase 3); keep it |
| 7 | Advanced-transcription defaults kept in one place, the Tk variables | `settings_store.py:23-47`; `transcription.py:59-66` | `tests/test_settings_store.py` asserts these defaults; update it. Confirm no caller passes `vad_filter=True` without parameters: `git grep -n "vad_filter=True" whisper_dictate/` |
| 8 | `word_timestamps` (checkbox, variable, setting, parameter) and the `condition_on_previous_text` parameter | `gui.py:205`, `:663-666`, `:1081`, `:1139`, `:1519`; `settings_store.py:34`; `transcription.py:25-28`, `:44-47`, `:77-80`; `asr.py` backends' `transcribe` signatures | An old settings file with `word_timestamps` still loads (unknown keys are ignored by `set_if_present`) |
| 9 | Cursor coordinates in the LLM prompt | `app_context.py:25`, `:58-62`, `:78`, `:103-105`; 34 references in `tests/test_app_context.py` | The rest of `format_context_for_prompt` output is unchanged |
| 10 | Optional-import guard around `openai`, and the unused `glossary: str` branch | `llm_cleanup.py:8-11`, `:36-37`, `:86-92`; `tests/test_llm_cleanup.py:63` patches `OpenAI` to `None` | `openai` is a hard dependency (`pyproject.toml:18`) |
| 11 | `DEFAULT_LLM_ENABLED` and its wrong comment | `config.py:19-20`; `tests/test_config.py:11`, `:34` | `git grep -n "llm_enabled\|DEFAULT_LLM_ENABLED" -- '*.py'` |
| 12 | Makefile: the `USE_UV` toggle (always 1) and the coverage flags `addopts` already applies | `Makefile:2-11`, `:25-27` | `make check` and `make build-exe` still work; update `docs/build.md:27` and `README.md:255` if they say `USE_UV=1` |
| 13 | `commit.txt`; `scripts/prefetch_model.py`; `assets/whisper_dictate_cli.ico` and `.png` | repo root, `scripts/`, `assets/` | `git grep -n "prefetch\|commit.txt\|whisper_dictate_cli"` shows no reference. The spec globs `whisper_dictate_gui.*` only |

Three single-caller wrappers from the report (`clone_rules`, `modifiers_up`,
`reset_position`) are left alone: 15 lines, and `modifiers_up` reads better at its call
site than `not modifiers_held()`.

### Success Criteria

#### Automated Verification:
- [ ] `make check` exits 0 before every commit in this phase, not only at the end
- [ ] `wc -l whisper_dictate/*.py | tail -1` is at least 250 lines below the 5,667 measured at `1974cd4`
- [ ] Coverage for `gui.py` has not dropped from its Phase 4 figure
- [ ] `git ls-files commit.txt scripts/prefetch_model.py` prints nothing

#### Manual Verification:
- [ ] Settings → Advanced transcription: every control from before is there except "Word timestamps", and changing beam size then relaunching keeps the value
- [ ] Every settings window: change one value in each, quit, relaunch, all four kept
- [ ] A dictation with endpoint cleanup on still cleans; check the debug log shows the prompt without a cursor-position line
- [ ] `make build-exe` produces a working exe
- [ ] Run `/repo-intake quick`: no tier 1 blocker, no tier 2 FAIL, B1-B7 not reported

---

## Testing Strategy

### Unit Tests
- Phase 2 adds `tests/test_gui_pipeline.py`, the first tests to import `whisper_dictate.gui`. Built on `App.__new__` and mocks, so they need no display and run on CI.
- Phases 3 and 4 flip three `xfail(strict=True)` markers from Phase 2. A fix cannot merge with its test still marked.
- Phase 4 moves the settings save tests from `MagicMock` paths to real files under `tmp_path`, because the thing under test is now the file system behaviour.

### Integration Tests
- `tests/test_integration.py` is unchanged until Phase 6 item 9 removes cursor coordinates from its expected prompts.

### Manual Testing
- Each phase lists its own steps. The ones that matter most are Phase 4's: blank field plus clipboard, kill-without-Quit, corrupt file, hotkey during a modal dialog.
- Per Dan's standing preference, the implementer sets each manual test up (corrupts a copy of the settings file, holds the clipboard open with a small script, and so on) and hands over exact steps, rather than describing the test.

## Performance Considerations

- The settings snapshot is some 25 `var.get()` calls on the Tk thread per dictation. Negligible beside the microphone close that already happens there.
- Saving on every settings-window close is one small JSON write. `os.replace` is atomic on NTFS.
- Removing `word_timestamps` can only make transcription faster.

## Migration Notes

- Old settings files keep loading. Unknown keys (`word_timestamps`, a dict-form `recent_processes` with titles) are ignored or down-converted on load, and gone after the next save.
- A user whose file is already corrupt gets a `.bak` on first launch after Phase 4 instead of a silent reset.
- A stored API key stays stored; only an explicit blank deletes it.
- Branch protection changes how Dan merges: PRs need green checks. Direct pushes to `main` that skip CI stop working for non-admins; `enforce_admins` is off, so Dan can still push in an emergency.

## References

- Intake report: `advisor-plans/intake-2026-09-21.md`
- Standards: `dan-skills:repo-intake` → `standards.md` (rules 1.1, 1.5, 2.1, 2.6-2.8, 2.12, 2.15, 2.17-2.19, 2.24)
- Threading rule and the snapshot pattern to copy: `gui.py:108-110`, `gui.py:1606-1612`
- Existing GUI test that needs a display, for contrast: `tests/test_gui_components.py:17-31`
- Previous plan, for house style: `plans/2026-09-18-modernize-whisper-dictate.md`
