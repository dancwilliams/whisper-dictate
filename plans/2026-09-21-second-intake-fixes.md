# Second intake fixes — Implementation Plan

Written against `main` at `a91c9e9`. Source: `advisor-plans/intake-2026-09-21-2.md` (the
second intake report) and `standards.md` (dan-skills 1.2.20). House style and ground rules
follow `plans/2026-09-21-bring-into-the-fold.md`.

## Overview

The second intake found no tier 1 blocker, one narrow tier 2 deviation (2.12: the docs
give `make` commands and never say how to get `make` on Windows), seven bugs (N1 to N7),
one lead that needs a measurement, a short deletion list, and a known defect in the
one-file exe. This plan clears all of it in five phases, one PR each.

Two decisions were made with Dan before writing:

- **Exe and S1:** try bundling `llama_cpp\lib`, time-boxed to one build. If it does not work first time, document the limit instead.
- **`scripts/mine_wispr_history.py` stays.** The 2026-09-18 plan cites it.

## Ground rules for the implementer

- `uv` for everything: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy whisper_dictate`. `make` is not installed on this machine; run the four commands.
- CI excludes the heavy ML wheels (`--no-group ml`). Locally the `.venv` has them; do not re-sync with different groups and leave the venv changed.
- One branch and one PR per phase, targeting `main`. `main` requires five green checks. Do not start a phase until the previous PR is merged.
- No AI attribution in commits or PR text. Commits are GPG-signed; if signing fails, stop and tell Dan to cache the key. Never `--no-gpg-sign`.
- Windows-only app. Tests mock Win32, `sounddevice`, the recognizer and the OpenAI client.
- Match the code around you. Comments explain why, not what.
- Line numbers are from `a91c9e9`. If a line has moved, find the quoted code.
- Add a `CHANGELOG.md` entry under `[Unreleased]` → `### Fixed` for each user-visible fix (N1 to N4, N6), in the register already there.

## Current State Analysis

Measured on 2026-09-21 with `uv run --no-sync`:

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` / `mypy whisper_dictate` | all exit 0 |
| `pytest` | 355 passed, 1 skipped, 63% |
| CI on `main` | green |
| `make` | not installed: `command -v make` exit 1, `Get-Command make` finds nothing |

### Key Discoveries

- **The Resident cannot be told its object is stale.** `release()` (`asr.py:183-193`) drops a loaded object but ignores a load in flight; `_load` (`asr.py:155-166`) installs whatever the factory returns; `warm()` (`asr.py:141-153`) returns early when anything is loaded. N1, N2 and N5 all come from this.
- The only `asr.release()` call is in `_reload_backend` (`gui.py:1215-1220`), bound only to the Recognizer combo (`gui.py:357`). The speech-window branch of `_close_window` (`gui.py:331-338`) removes traces and nothing else. The Whisper model and the device are therefore ignored while a model is resident.
- `_build_backend` reads `self._asr_config` when it starts (`gui.py:1151`), so a load restarted after a settings change picks up the new values with no further wiring.
- `get()` (`asr.py:168-181`) has two windows against the idle timer: before `_settled.wait()` it can block until the next press; after it, it can return `None`. `None.transcribe` raises `AttributeError`, which the worker's `except` (`gui.py:1409`) does not list, and the worker has no last-resort handler.
- Each dictation runs on its own thread (`gui.py:1340`). `_deliver` (`gui.py:1534-1576`) takes no lock. The only locks in the package are `asr.py:130` and `audio.py:37`.
- `OpenAI(base_url=..., api_key=...)` at `llm_cleanup.py:38` and `:112` sets no `max_retries`. The SDK default is 2 (`.venv/Lib/site-packages/openai/_constants.py:8`). Cleanup timeout is 15 s (`llm_cleanup.py:57`), so a hung endpoint costs 45 s.
- The audio callback queues blocks (`audio.py:54`); a collector thread moves them into the buffer (`audio.py:56-65`). `stop()` (`audio.py:101-113`) closes the stream and returns; the worker calls `get_buffer()` at once (`gui.py:1360`). Nothing waits for the queue to empty.
- `audio.py:46` is `print("Audio status:", status)`. The app runs under `pythonw.exe` (`docs/startup.md:16`), where `print` does nothing. `audio.py` has no logger; the house pattern is `logger = logging.getLogger("whisper_dictate")` (`history.py:24`, `s1.py:20`).
- Hook callbacks call `self.after(0, handler)` from the hook thread (`hotkeys.py:250-255` via `gui.py:1263-1265`). A cross-thread Tk call waits for the main thread. Windows drops a low-level hook that overruns `LowLevelHooksTimeout` (300 ms by default). `hotkeys.py` has no logger and no timing.
- The test harness builds the app with `App.__new__` (`tests/test_gui_pipeline.py:79-112`), so any attribute added in `App.__init__` must also be set in `make_app`. The harness patches `gui.time.sleep`, which is `time.sleep` for the whole process: tests in that file must not rely on a real `time.sleep`.
- `tests/test_asr.py:115-198` is `TestResident`; `test_warm_during_a_load_does_not_start_a_second` (`:128`) is the pattern for a slow factory with an `Event`.
- The spec collects dynamic libs only from `nvidia.*` (`whisper_dictate_gui.spec:21-33`). `llama_cpp` loads `llama.dll`, `ggml*.dll` from its own `lib\` folder (`.venv/Lib/site-packages/llama_cpp/lib`), which PyInstaller's import analysis does not pick up.
- The build workflow syncs with `--no-group ml` (`build-windows.yml:36`), so a CI-built exe never contains `llama_cpp` at all. `docs/build.md:38` says `uv sync --frozen --python 3.11`, without the flag.
- `set_cuda_paths` already handles the frozen case (`config.py:152-160`) and sets `CUDA_PATH` for llama-cpp-python's own `add_dll_directory` (`config.py:173-175`), so the CUDA DLLs `ggml-cuda.dll` needs are reachable in the exe.
- `make` appears in `README.md:176-194`, `:255`; `CONTRIBUTING.md:158-161`, `:206`, `:218-225`; `docs/build.md:19-24`; and the Testing and Building sections of `CLAUDE.MD`. `README.md:255-258` and `docs/build.md:21-23` already show the uv form beside `make build-exe`; the test and check blocks do not.

## Desired End State

`/repo-intake quick` on the merged result reports no tier 1 blocker, no tier 2 FAIL, and
N1 to N7 gone. Concretely:

- Every documented command either runs on a stock Windows dev box with uv, or sits beside a line saying how to get `make`.
- Changing the Whisper model, the device or the recognizer takes effect on the next dictation, whether a model is loaded, loading, or neither.
- A dictation can never end with the pill stuck on "Transcribing...".
- Two dictations finishing together leave the user's original clipboard in place.
- A hung cleanup endpoint costs one timeout.
- The last block of audio always reaches the recognizer. Audio overflows show up in the log.
- The log says when a hotkey callback held the hook thread too long.
- CI runs the suite once per Python.
- The locally built exe runs S1 cleanup, or the README says it does not.

## What We're NOT Doing

- **Not replacing the Makefile.** Standards 2.9 wants one command; it stays. The docs gain the prerequisite and the uv equivalents.
- **Not collapsing the audio queue and collector thread.** Still ruled out by the previous plan. N6 is fixed inside that design.
- **Not moving hotkey events onto a queue yet.** Phase 3 adds the measurement. The queue change is written down at the end of Phase 3 and happens only if the measurement says so.
- **Not re-enabling the "Load model" button after a release** (`gui.py:1205`). The hotkey warms the model; the button is a convenience.
- Not deleting `scripts/mine_wispr_history.py`.
- Not touching the regex guard question (`app_prompts.py` guards user regexes, `glossary.py` does not). Not re-read by the intake; out of scope.
- Not shrinking the exe or deciding whether torch and transformers belong in it.
- Not adding Python 3.14 to the matrix.

## Implementation Approach

Docs first, because that one line is the whole distance to "in the fold". Then the
Resident, as one change with its tests, because three bugs share it. Then the small
independent fixes. Deletions after the code they touch has stopped moving: Phase 3's
audio fix and Phase 4's `shutdown` deletion both edit the collector loop, in that order.
The exe goes last because it needs a long build and may end in a docs sentence.

---

## Phase 1: Docs say how to run the checks

Branch: `docs/make-prereq`. Clears standards 2.12.

### Changes Required

#### 1. Name the prerequisite and give the equivalents
Before writing a package name into the docs, confirm it: `winget search --id ezwinports.make`. If that id does not resolve, use whichever GNU Make package `winget search make` lists and say which in the PR.

**File**: `README.md`, the Development section (`:169-194`). Add once, above "Running Tests":

> `make` is optional. On Windows, `winget install ezwinports.make` provides it. Without it, run what the targets run:

and a PowerShell block with the four commands `make check` expands to (`Makefile:38-39`):

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy whisper_dictate
uv run pytest
```

**File**: `CONTRIBUTING.md` — the same two sentences and block above "Running Tests" (`:154`). Leave the `make` lines that follow.
**File**: `CLAUDE.MD` — in "Running Tests Locally", one line: "`make` is not installed on the Windows dev box; each target is one `uv run` command, see the `Makefile`." Leave the rest.
**File**: `docs/build.md:19-24` already shows the uv form. No change.

#### 2. The debug-logging warning names the window title
**File**: `whisper_dictate/gui.py:724`. The prompt carries the active window title (`app_context.py:85-93`) and debug logging writes the prompt to the log (`llm_cleanup.py:102-109`). New text: `"⚠ Warning: Debug mode logs transcribed speech, prompts and the active window title to disk"`.

### Success Criteria

#### Automated Verification:
- [x] `git grep -n "ezwinports.make\|uv run ruff format --check" -- README.md CONTRIBUTING.md` shows both files
- [x] `git grep -n "window title to disk" whisper_dictate/gui.py` shows one line
- [x] The four check commands exit 0

#### Manual Verification:
- [x] Dan reads the README paragraph and agrees with the wording
- [x] Settings → LLM cleanup: the warning fits on the window without clipping

---

## Phase 2: The Resident knows when it is stale

Branch: `fix/resident-staleness`. N1, N2, N5, and the worker's last-resort handler.

### Changes Required

#### 1. Tests first
**File**: `tests/test_asr.py`, in `TestResident`. Model the slow factory on `test_warm_during_a_load_does_not_start_a_second` (`:128-144`). Use `threading.Event`, not sleeps, to hold a factory open.

| Test | Asserts |
|---|---|
| release during a load | A factory that blocks on an event and returns a counter value. `warm()`, wait until the factory has started, `release()`, let the factory finish. `get()` returns the **second** build, the factory ran twice, and `_free_gpu_memory` was called for the discarded one |
| release during a load, then the load fails | First build raises after `release()`; `get()` still returns the second build rather than raising the stale error |
| get after a release that lands between warm and wait | Patch `resident.warm` with a wrapper that calls the real `warm`, then calls `resident.release()` once. `get()` returns the object (a reload), and does not block: run it on a thread and `join(timeout=2.0)`, then assert the thread is dead |
| get never returns None | Patch `resident._settled.wait` with a wrapper that calls the real wait, then `release()` once. `get()` returns the object, not `None` |

Run them and see the first, third and fourth fail before touching `asr.py`.

#### 2. A generation counter
**File**: `whisper_dictate/asr.py`, class `Resident`.

- `__init__`: `self._generation = 0`.
- `release()`: inside the lock, `self._generation += 1`. Leave `_loading` alone: a load in flight keeps running and `_load` deals with it.
- `_load()` becomes a loop:

```python
def _load(self) -> None:
    while True:
        with self._lock:
            generation = self._generation
        error: BaseException | None = None
        obj: Any = None
        try:
            obj = self.factory()
        except BaseException as e:  # reported to whoever calls get()
            error = e
        with self._lock:
            if generation == self._generation:
                self._obj, self._error, self._loading = obj, error, False
                break
        # Released while we were building: what we hold was made from settings
        # that have since changed. Drop it and build again.
        del obj
        _free_gpu_memory()
    self._settled.set()
    if error is None:
        self._restart_timer()
```

- `get()` loops until the lock shows a result:

```python
def get(self) -> Any:
    while True:
        self.warm()
        self._settled.wait()
        with self._lock:
            error, obj = self._error, self._obj
        if error is not None:
            raise error
        if obj is not None:
            break
        # Released between the wait and the lock; go round and load again.
    self._restart_timer()
    return obj
```

  One more line is needed for the third test: `release()` clears `_settled` while nothing is loading, so a `get()` that has passed `warm()` would wait forever. In `release()`, clear `_settled` only when a load is in flight (`if self._loading: self._settled.clear()`); otherwise leave it set, so the waiter wakes, sees `obj is None`, and goes round the loop, where `warm()` starts the reload and clears the event itself (`asr.py:152`).
- Update the class docstring with one sentence on the generation rule.

#### 3. N1 — the speech window applies what it changed
**File**: `whisper_dictate/gui.py`, `_close_window`, the `_speech_window` branch (`:331-338`), after the trace cleanup:

```python
            # The model and device only reach the recognizer through a release.
            before = self._asr_config
            self._capture_asr_config()
            if self._asr_config != before:
                self._reload_backend()
```

`_asr_config` is always set by then: `_auto_startup` calls `_apply_idle_ttl` (`gui.py:915`), which captures it (`:1170`).

**File**: `whisper_dictate/gui.py`, `_reload_backend` (`:1220`): the status names the backend only. Use the existing helper: `self._set_status("ready", f"Recognizer: {self._asr_description()}")`.

Keep the combo binding at `:357`. It releases at once; the close path then finds nothing changed and does nothing.

**File**: `tests/test_gui_pipeline.py` — two tests on `_close_window("_speech_window")`, with `app._speech_window = None`, `app._speech_window_traces = []`, `app._asr_config = ("whisper", "small", "cuda", "float16")` and `app._save_settings = MagicMock()`:
- `var_model` now returns `"large-v3"`: `app.asr.release` called once.
- nothing changed: `app.asr.release` not called.

#### 4. The worker cannot die silently
**File**: `whisper_dictate/gui.py`

```python
    def _dictation_worker(self, cfg: dict[str, Any]) -> None:
        """Thread target. Nothing escapes: an unhandled error would leave the
        pill on "Transcribing..." for good."""
        try:
            self._transcribe_and_clean(cfg)
        except Exception as e:
            logger.error(f"Dictation failed: {e}", exc_info=True)
            self._set_status("error", "Dictation failed; see the log")
```

`_stop_and_transcribe` (`:1340`) targets `self._dictation_worker`. `_transcribe_and_clean` is unchanged, so the existing tests, which call it directly, still pin its behaviour.

**File**: `tests/test_gui_pipeline.py` — `app._transcribe_and_clean = MagicMock(side_effect=AttributeError("boom"))`; `app._dictation_worker({})` returns, and `states(app)[-1] == "error"`.

### Success Criteria

#### Automated Verification:
- [x] The four new `TestResident` tests fail on `a91c9e9` and pass after step 2 (say so in the PR)
- [x] `uv run pytest tests/test_asr.py tests/test_gui_pipeline.py -v` passes
- [x] `git grep -n "_generation" whisper_dictate/asr.py` shows the counter read in `_load` and bumped in `release`
- [x] The four check commands exit 0; CI green

#### Manual Verification:
- [x] Load `small`. Settings → Speech recognition: pick `large-v3`, close. The status reads "Recognizer: Whisper large-v3". Dictate: the log shows "Loading Whisper large-v3" and the dictation pastes
- [x] Turn on auto-load, relaunch, and inside the load switch the recognizer to Cohere (or back). After the load settles, dictate: the log shows the recognizer chosen last, not the one that was loading
- [x] Set idle TTL to 0.1 minutes. Dictate, wait ten seconds, dictate again, five times: every dictation pastes, the pill never sticks

**Implementation Note**: pause here for Dan's confirmation before Phase 3.

---

## Phase 3: Delivery, cleanup, audio, and the hook timer

Branch: `fix/delivery-races`. N3, N4, N6, N7 and the measurement. Independent; one commit each.

### Changes Required

#### 1. N3 — one delivery at a time
**File**: `whisper_dictate/gui.py`
- `__init__`, beside `_status_state` (`:170`): `self._deliver_lock = threading.Lock()`.
- `_deliver` (`:1534`): the whole body goes under `with self._deliver_lock:`, from the snapshot to the end of the `finally`. Add to the docstring: borrowing is only safe one borrower at a time, or the second saves the first one's dictation as the user's clipboard.

**File**: `tests/test_gui_pipeline.py`
- `make_app`: `app._deliver_lock = threading.Lock()`.
- New test in `TestDeliver`. `time.sleep` is patched in this file, so hold thread A with events:

```python
    def test_two_deliveries_do_not_interleave(self, make_app, mods):
        app = make_app()
        cfg = app._capture_dictation_config()
        in_paste, go = threading.Event(), threading.Event()

        def paste():
            in_paste.set()
            go.wait(2.0)
            return True

        mods.clipboard.send_paste.side_effect = paste
        a = threading.Thread(target=app._deliver, args=("A", cfg))
        a.start()
        assert in_paste.wait(2.0)
        b = threading.Thread(target=app._deliver, args=("B", cfg))
        b.start()
        b.join(0.1)  # B must be parked on the lock, not snapshotting A's text
        assert [c[0] for c in mods.clipboard.mock_calls].count("snapshot") == 1
        go.set()
        a.join(2.0)
        b.join(2.0)
        assert [c[0] for c in mods.clipboard.mock_calls] == [
            "snapshot", "set_text", "send_paste", "restore",
        ] * 2
```

#### 2. N4 — no silent retries
**File**: `whisper_dictate/llm_cleanup.py:38` and `:112`: add `max_retries=0` to both `OpenAI(...)` calls, with one comment at `:112`: the SDK retries twice by default, which turns a 15 s timeout into 45 s of "Cleaning with LLM...".
**File**: `tests/test_llm_cleanup.py` — in an existing test that patches `whisper_dictate.llm_cleanup.OpenAI` and reaches the constructor, assert `mock_openai.call_args.kwargs["max_retries"] == 0`. One for each function.

#### 3. N6 — `stop()` waits for the collector
**File**: `whisper_dictate/audio.py`
- `_recorder_loop` (`:56-65`): call `self._audio_queue.task_done()` after the append, inside the `try`.
- `stop()` (`:101-113`): after the stream is closed and before `self._recording = False`:

```python
        # The stream is closed, so nothing more is coming. Wait for the collector
        # to move what is queued, or get_buffer() misses the end of the utterance.
        if self._recorder_thread and self._recorder_thread.is_alive():
            self._audio_queue.join()
```

  The `is_alive()` guard matters: `Queue.join()` has no timeout and this runs on the Tk thread.

**File**: `tests/test_audio.py` — with `sd.InputStream` patched as the other tests do: `start()`, acquire `recorder._buffer_lock`, feed three blocks through `recorder._audio_callback(block, len(block), {}, None)`, release the lock from a `threading.Timer(0.05, ...)`, call `stop()`. Assert `recorder._audio_queue.unfinished_tasks == 0` and `len(recorder.get_buffer()) == 3 * len(block)`.

#### 4. N7 — overflows reach the log
**File**: `whisper_dictate/audio.py`: `import logging`; `logger = logging.getLogger("whisper_dictate")` under the imports; `:46` becomes `logger.warning(f"Audio status: {status}")`.
**File**: `tests/test_audio.py` — call `_audio_callback` with a truthy `status` and assert on `caplog`. This covers the one uncovered line in the module.

#### 5. Measure the hook
**File**: `whisper_dictate/hotkeys.py`
- `import logging`, `import time`; `logger = logging.getLogger("whisper_dictate")`; constant `SLOW_CALLBACK_SECONDS = 0.1` with a comment: Windows drops a low-level hook that overruns `LowLevelHooksTimeout`, 300 ms by default, and the callbacks wait on the Tk thread.
- `_handle` (`:245-255`): take `time.perf_counter()` before dispatch; after it, if an event fired and the elapsed time is over the constant, `logger.warning(f"Hotkey {event} callback held the hook thread for {elapsed * 1000:.0f} ms")`.

**File**: `tests/test_hotkeys.py` — beside `test_handle_dispatches_press_release_and_cancel` (`:153`): an `on_press` that advances a patched `hotkeys.time.perf_counter` by 0.2 s produces the warning (`caplog`); a fast one does not.

**As built (deviation).** `hotkeys.py` was left alone. `test_no_key_codes_are_logged` (`tests/test_hotkeys.py:261`) asserts the word `logger` does not appear in that module: the hook sees every keystroke, and the module is kept free of logging on purpose. The timing went into `gui._post` instead, the one place all three callbacks wait on Tk, as `SLOW_HOOK_POST_SECONDS`; the test is `test_a_slow_post_is_logged` in `tests/test_gui_pipeline.py`. The log text is as written above, so the rule below holds.

The `print(` criterion also caught four prints this section does not name, in `glossary.py` and `prompt.py`. Same defect under `pythonw.exe`; they are `logger.error` now.

**The rule for what happens next.** After a normal day's use including one cold start, run `Select-String "held the hook thread" $env:USERPROFILE\.whisper_dictate\logs\whisper_dictate.log`. No lines: the lead is closed; leave the warning in. Any line at 250 ms or more, or the hotkey stops responding: open a follow-up to make the hook callbacks `queue.Queue.put_nowait` and have Tk drain the queue from a 10 ms `after` loop, so the hook thread never waits on Tk. That change is not part of this plan.

### Success Criteria

#### Automated Verification:
- [x] `uv run pytest tests/test_gui_pipeline.py tests/test_audio.py tests/test_llm_cleanup.py tests/test_hotkeys.py -v` passes
- [x] `git grep -n "max_retries=0" whisper_dictate/llm_cleanup.py` shows two lines
- [x] `git grep -n "print(" whisper_dictate/` returns nothing
- [x] Coverage for `whisper_dictate\audio.py` is 100%
- [x] The four check commands exit 0; CI green

#### Manual Verification:
- [x] Copy a sentence. With endpoint cleanup on, dictate a long sentence and straight after it a two-word one, so they finish close together. Both paste, in order, and Ctrl+V afterwards pastes the original sentence
- [x] Point the endpoint at a port nothing listens on, dictate: the raw text pastes within a couple of seconds. (A hung endpoint is hard to stage; the unit test carries that case)
- [x] Dictate ten short phrases releasing the key the instant the last word ends: no clipped final word
- [x] Ten dictations, hold and tap-lock alternating: all paste. Check the log for "held the hook thread" and tell the implementer what it shows

**Implementation Note**: pause here for Dan's confirmation before Phase 4.

---

## Phase 4: Deletions

Branch: `chore/deletions-2`. Report section 5, minus the miner. One commit per item. Re-run each grep before cutting.

| # | Cut | Where | Check before cutting |
|---|---|---|---|
| 1 | The "Display coverage report" step. `addopts` already prints `term-missing` (`pyproject.toml:72-77`), so it runs the suite a second time | `ci.yml:80-81` | The remaining step's log on the PR shows the coverage table |
| 2 | `AudioRecorder.shutdown`, then `_stop_recorder`, which nothing else sets: the loop becomes `while True:` with a blocking `get()`, and `start()` loses the `.clear()` | `audio.py:40`, `:56-65`, `:85`, `:150-155`; `tests/test_audio.py:139-149` | `git grep -n "\.shutdown()\|_stop_recorder" -- whisper_dictate tests`. Keep Phase 3's `task_done()` and the `is_alive()` guard |
| 3 | `migrate_from_plaintext`: fold into its one caller, which already checks for a non-blank string, as `credentials.store_credential(SECURE_KEYS[key], plaintext_value)` inside the existing `try`, narrowed to `except (credentials.CredentialStorageError, ValueError)` | `credentials.py:108-128`; `settings_store.py:86-97`; `tests/test_credentials.py:150-165` and any migrate test after it | `git grep -n "migrate_from_plaintext"`. `tests/test_settings_store.py` migration cases must still pass, patched at `store_credential` |
| 4 | The three empty-**key** guards. Every caller passes the module constant. Keep the empty-**value** guard in `store_credential`: it is what stops a blank write to the keyring | `credentials.py:39-40`, `:67-68`, `:93-94`, and the `ValueError` lines in the three docstrings; `tests/test_credentials.py:25-28`, `:81-84`, `:127-130` | `git grep -n "store_credential\|retrieve_credential\|delete_credential" whisper_dictate/` shows only `settings_store.py` callers passing `SECURE_KEYS[...]` |
| 5 | The `test-coverage` target, an alias for `test` | `Makefile:15-16`, `:50`; `README.md:178-179`; `CONTRIBUTING.md:160-161`; `CLAUDE.MD` "Run all tests with coverage" | `git grep -n "test-coverage"` returns nothing afterwards, outside `plans/` and `advisor-plans/` |

### Success Criteria

#### Automated Verification:
- [x] The four check commands exit 0 before every commit
- [x] `git grep -n "migrate_from_plaintext\|def shutdown\|_stop_recorder\|test-coverage" -- . ':!plans' ':!advisor-plans'` returns nothing
- [x] CI's test jobs each show one pytest run; all five checks green
- [x] Coverage for `credentials.py` and `audio.py` stays at 100%

#### Manual Verification:
- [x] Quit from the pill after a dictation: the process exits within a second (the collector is a daemon thread; nothing joins it now)
- [x] With a settings file carrying a plaintext `llm_key` (the implementer prepares a copy and gives Dan the steps): launch, the key is in Credential Manager and gone from the JSON

---

## Phase 5: S1 in the exe, time-boxed

Branch: `build/bundle-llama`. One build. If S1 does not run in it, take the fallback; do not iterate on the spec.

### Changes Required

#### 1. Collect the llama.cpp DLLs
**File**: `packaging/pyinstaller/whisper_dictate_gui.spec`. Rename `_collect_nvidia_binaries` to `_collect_binaries` and add `"llama_cpp"` to its package list (`:22-26`). The existing `try/except` (`:28-33`) already covers the CI build, where `--no-group ml` means the package is absent. Extend the comment there to say so. `collect_dynamic_libs` places the files under `llama_cpp/lib`, which is where `llama_cpp` looks for them.

#### 2. Build and test
`uv run pyinstaller packaging/pyinstaller/whisper_dictate_gui.spec --noconfirm`. Confirm the archive has them: `uv run pyi-archive_viewer -l dist/whisper-dictate-gui.exe | Select-String "llama_cpp\\lib"`.

#### 3. Docs, whichever way it goes
**File**: `README.md`, after `:261`; **File**: `docs/build.md`, under "Artifacts" (`:30`).
- **If S1 works in the local build:** "Built-in S1-mini cleanup works in an exe built locally, where the ML group is installed. The GitHub Actions build leaves the ML group out, so its exe has Whisper and endpoint cleanup only; with cleanup set to built-in it warns and pastes the raw text."
- **Fallback, if it does not:** revert the spec change and write: "Built-in S1-mini cleanup needs the source install. In the exe it warns once and pastes the raw text; endpoint cleanup works."

**File**: `docs/build.md:38` — the workflow runs `uv sync --frozen --python 3.11 --no-group ml` (`build-windows.yml:36`). Make the sentence match, whichever branch is taken.

### Success Criteria

#### Automated Verification:
- [ ] PyInstaller exits 0
- [ ] Bundled branch only: the archive listing shows `llama.dll` and `ggml-cuda.dll` under `llama_cpp\lib`
- [ ] `git grep -n "no-group ml" docs/build.md` shows the corrected line
- [ ] The four check commands exit 0; CI green

#### Manual Verification:
- [ ] Launch `dist\whisper-dictate-gui.exe` with cleanup set to built-in and dictate. Either the log shows "S1-mini loaded on GPU" (or CPU) and the text is cleaned, or it shows "S1 cleanup failed" and the fallback sentence goes in
- [ ] Dan reads the README sentence and agrees it is what he wants users told
- [ ] Run `/repo-intake quick`: no tier 1 blocker, no tier 2 FAIL, N1 to N7 not reported

---

## Testing Strategy

### Unit Tests
- Phase 2's Resident tests are written first and must be seen to fail. They hold factories open with `threading.Event`; none depends on timing.
- `tests/test_gui_pipeline.py` patches `time.sleep` process-wide. New tests there synchronise with events and `join(timeout)`.
- Phase 3's audio test proves `stop()` waited (`unfinished_tasks == 0`), not merely that nothing was lost on one run.

### Integration Tests
- None added. `tests/test_integration.py` is untouched.

### Manual Testing
- Each phase lists its steps. The ones that matter: Phase 2's model change and the 0.1-minute TTL loop; Phase 3's back-to-back dictations with something on the clipboard.
- Per Dan's standing preference, the implementer sets each manual test up (a settings copy with a plaintext key, a closed port for the endpoint) and hands over exact steps.

## Performance Considerations

- A release during a load now costs a second load. That is the fix: the first one was for settings the user no longer wants.
- `stop()` blocks the Tk thread until the collector drains. The queue holds at most a few blocks at that point; the wait is microseconds.
- The delivery lock serialises pastes that would otherwise have corrupted each other. A second dictation can wait up to `paste_delay + restore_delay`, 0.75 s by default.
- CI test jobs take about half as long.

## Migration Notes

- No settings change, no file format change.
- Plaintext `llm_key` migration keeps working; only the wrapper around it goes.
- Anyone importing `credentials.migrate_from_plaintext` or `AudioRecorder.shutdown` from outside the package would break. `git grep` shows nobody does.

## References

- Intake report: `advisor-plans/intake-2026-09-21-2.md` (sections 3, 4, 5, 7)
- Previous plan, for ground rules and house style: `plans/2026-09-21-bring-into-the-fold.md`
- Resident test pattern: `tests/test_asr.py:128-144`
- Pipeline harness: `tests/test_gui_pipeline.py:58-125`
- Standards: rules 2.9, 2.12
