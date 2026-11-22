# Audit follow-up — Implementation Plan

Written against `main` at `2b9df18` on 2026-11-21. Line numbers are from that commit; if
one has moved, find the quoted code.

## Overview

An outside audit of the app (2026-11-21) ended with a three-tier priority order: quick
stability wins, "smarter" features, bigger architectural bets. This plan follows that
order, but every item was first checked against the code, the real log, and the local
history. Several survived, a few were reshaped, and some were dropped because the
evidence on this machine says they would buy nothing. Nine phases, one PR each.

Decisions made while writing, each open to veto before a phase starts:

- **The hook fix is the top item, and it is real.** The log holds 11 genuine
  "held the hook thread" warnings since 2026-09-21, all on `release`, 126 to 1176 ms,
  six of them over the 300 ms `LowLevelHooksTimeout`.
- **No WASAPI switch.** Measured here: MME and WASAPI both open in 19 ms and deliver
  first audio at 263 ms. The audit's 300 ms to 20-50 ms claim does not hold on this box.
- **No auto-suggested glossary rules yet.** 66 banked corrections hold 72 distinct word
  swaps and none occurs twice. There is nothing to suggest.
- **No `DictationEngine` extraction and no live level meter.** Phase 1 fixes the
  threading faults the extraction was meant to cure in about 30 lines, and Phase 3's
  silence check gives the "wrong or muted mic" signal without a meter.
- **The architecture bets are gated on a measurement**, not built on faith: Phases 7
  and 8 each start with a number and say what number stops them.
- **The model subprocess is closed.** Measured 2026-11-21: after ten days up and 166
  model loads the idle app holds 568 MB of a 32.6 GB card, with no growth. Phase 9 only
  records that and checks for a native crash.

Revised 2026-11-21 after a question-by-question review with Dan. What changed: the
loudness gate dropped to 0.0005 (Phase 3); Phase 5 fixes spacing only; Phase 6 has its
own gate and keeps the edit result in memory; Phases 7 and 8 also score the corrections
bank; Phase 9 shrank to a write-up. Confirmed unchanged: no watchdog on the dictation
queue, a single Esc cancels, no Ollama warm-up, one glossary rule per trigger.

## Ground rules for the implementer

- `uv` for everything: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy whisper_dictate`. `make` is not installed; run the four commands.
- A running Whisper Dictate holds `.venv/Scripts/whisper-dictate.exe`. No phase here adds
  a dependency to the project; Phase 8 uses `uv run --with`, which needs no sync. If a
  `uv sync` becomes necessary anyway, ask Dan to quit the app first. It runs as `pythonw`;
  stop it by command line, not by the whisper-dictate name.
- One branch and one PR per phase, targeting `main`. Do not start a phase until the one
  before it is merged. Never pass `--auto` to `gh pr merge`; watch checks, then merge.
- No AI attribution in commits or PR text. Commits are GPG-signed; if signing fails, stop
  and ask Dan to unlock the key. Never `--no-gpg-sign`.
- Never inject input (SendInput, pyautogui) on Dan's box to test. Manual checks are Dan
  dictating.
- Match the code around you. Comments explain why, not what. Stdlib first, shortest
  working diff.
- Each user-visible change gets a `CHANGELOG.md` entry under `[Unreleased]`.

## Current State Analysis

What the audit claimed, and what checking found.

| Audit claim | Verdict | Evidence |
|---|---|---|
| Each stop spawns its own worker; S1 and Cohere have no lock | True | `gui.py:1456`, `s1.py:87`, `asr.py:116`; only Whisper is locked (`asr.py:62`) |
| Hook thread waits on Tk | True, 11 real stalls logged | `gui.py:1348`; log warnings from `gui.py:1352` |
| Mic open takes 264-577 ms on the Tk thread | False | `InputStream.start()` returns in 19 ms (113 ms cold); the 263 ms is the wait for the first callback, off the Tk thread |
| WASAPI opens faster than MME | False here | 263 ms vs 264 ms to first audio, four runs each |
| S1 failure turns cleanup off for good | True in code, never happened | `gui.py:1663` writes a persisted setting; all 46 logged failures since September are the test suite, the one real one is from the retired exe build |
| App-prompt process match is case-sensitive | True, and biting | `app_prompts.py:141,174`; a saved `notepad.exe` rule never matches the `Notepad.exe` Windows reports |
| Mic chosen by PortAudio index | True, not biting | `gui.py:1201`; the saved input is `0: Microsoft Sound Mapper - Input`, which is always index 0 |
| Backslash in a replacement breaks `re.sub` | True | `glossary.py:317`, `readback.py:96` |
| Log never rotates | True | `logging_config.py:42`; 3.2 MB in two months |
| WAV names collide within a second | True | `history.py:44` |
| Whisper hallucinates on silence | True | 20 dictations in history are the single word "you"; the 8 with audio have a median length of 0.4 s |
| S1 may drop or invent content | Rare but real | Of 1,921 cleaned dictations of 8+ words, 3 grew past 1.5x and 2 shrank below 0.5x; the 0.5th to 99.5th percentile is 0.78 to 1.06 |
| Static hotwords are loaded per app | Moot | `~/.whisper_dictate/hotwords_by_app.json` does not exist on this machine; hotwords are not in use |

Two more facts that shape the later phases:

- UI Automation reads the focused control only. In a chat app that is the compose box,
  not the conversation above it. `Code.exe` (35% of 2,573 dictations) and Windows
  Terminal (4%) are not readable at all; the log shows 203 failed read-backs in Code.
- The pipeline is already fast: warm ASR is 386 ms at the median and 966 ms at p95, and
  S1 cleanup is 50 ms at the median. Nothing here is waiting on a faster recognizer.

## Desired End State

- The keyboard hook never waits on Tk, and dictations run one at a time in order.
- The small correctness faults in the table are fixed.
- Silence no longer pastes "you", a runaway cleanup falls back to the raw text, Esc
  cancels a locked recording, and the last dictation can be copied from the pill.
- Glossary rules can be scoped to an application.
- A dictation pasted after existing text joins it with the right spacing.
- With a setting on, speaking over a selection edits the selection.
- Two written measurements say whether per-clip hotwords and Parakeet are worth
  building, and a third records why the model subprocess is not.

### Key Discoveries

- `Resident` already takes a factory and calls `unload()` on release (`asr.py:155-272`).
  A model subprocess, if ever built, fits behind it without touching the GUI. It is
  not being built: see Phase 9.
- With one dictation worker, `_last_entry` (`gui.py:1612`, read at `1733`) is always the
  current dictation's. No need to thread the entry through `_deliver`.
- PortAudio fixes its device list when it initialises, so indices only shift between
  launches. Resolving the saved name at use is cheap and enough.
- `tests/conftest.py` already keeps the suite out of the real log. Older test lines are
  still in it; treat any pre-fix `boom`, `no model` or `200 ms` line as noise.
- The suite's two `PytestUnhandledThreadExceptionWarning`s come from the `mods` fixture:
  `readback.run` is a `MagicMock`, so it returns a mock, not `None`, and the fake edit
  recurses through the synchronous `after` at `tests/test_gui_pipeline.py:98`.

## What We're NOT Doing

- **WASAPI, or `latency="low"`.** `blocksize=0, latency="low"` measured 223 ms against
  263 ms. Forty milliseconds is not worth small buffers while a model loads on another
  thread; a dropped block is a clipped word.
- **Auto-suggested glossary rules, auto-refreshed hotwords.** No repeated swap exists and
  no hotwords file exists. Revisit when `corrections.jsonl` shows a swap three times.
- **`DictationEngine` extraction, live level meter, recent-dictations submenu.** See the
  decisions above. Phase 3 adds one "Copy last dictation" menu item instead.
- **Chunked or streaming transcription.** p95 ASR is under a second.
- **A digits check on cleanup.** 4 of 274 dictations with digits lost a digit run, and
  "five" against "5" cannot be told from a real loss without reading them.
- **A model subprocess.** Measured and closed; Phase 9 records it.
- **A watchdog or a "Queued" state on the dictation queue.** A dictation waits behind
  the one before it, under a second at p95. A hung one blocks the rest until restart;
  accepted until a log shows it happening.
- **Lower-casing a continued sentence, and warming Ollama at the hotkey press.** Both
  considered in review and declined.
- **Moving `recorder.stop()` off the Tk thread.** After Phase 1 a busy Tk thread costs a
  late status update, not the hook.
- **Audit items outside its own priority order**, not verified for this plan: clipboard
  delay-rendered formats, the clipboard sequence-number check before restore, the 1-byte
  `ExcludeClipboardContentFromMonitorProcessing` value, `CoUninitialize` in `speaker.py`,
  `GetLastError` after `CreateMutexW` (`gui.py:1789`), `prune_models` path comparison
  (`history.py:211`), `n_ctx=4096` in `s1.py:64`, a cached OpenAI client. Each is small;
  ask for a follow-up plan if any is wanted.

## Implementation Approach

Tier 1 is Phases 1 and 2, tier 2 is Phases 3 to 7, tier 3 is Phases 8 and 9. Phases 1
to 3 are specified to the line. Phases 4 to 6 are specified to the function, and their
implementer should re-read the files first, since earlier phases will have moved them.
Phases 7 and 8 are experiments with a stated pass mark; a pass earns its own plan.
Phase 9 is a write-up of a question already settled.

---

## Phase 1: One dictation at a time, and a hook that never waits

### Overview

A queue feeds one dictation worker, a second queue takes hotkey events off the hook
thread, and an S1 failure stops disabling cleanup on disk.

### Changes Required

#### 1. Dictation queue and hook queue
**File**: `whisper_dictate/gui.py`

Add `import queue`. Beside `_unmute_on_stop` at line 149, a class default so apps built
with `App.__new__` in tests need no fixture change:

```python
    # Set when S1 failed to load or run. Until the app restarts or the cleanup
    # window closes, dictations go out raw; the saved setting is left alone.
    _s1_failed = False
```

In `__init__`, after `self._deliver_lock` (line 188):

```python
        # One dictation at a time, in the order spoken: llama.cpp and the Cohere
        # model are not thread-safe, and a short dictation must not overtake a long one.
        self._dictations: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        threading.Thread(target=self._dictation_loop, daemon=True).start()
        # Hotkey events wait for Tk on this thread, so the hook thread never does.
        self._hook_events: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        threading.Thread(target=self._hook_event_loop, daemon=True).start()
```

Replace line 1456 (`threading.Thread(target=self._dictation_worker, ...)`):

```python
        self._dictations.put(cfg)
```

Add beside `_dictation_worker`:

```python
    def _dictation_loop(self) -> None:
        """Thread target. Runs queued dictations one at a time."""
        while True:
            self._dictation_worker(self._dictations.get())
```

Replace `_post` (lines 1341-1354):

```python
    def _post(self, handler: Callable[[], None]) -> None:
        """Queue a hook-thread event. Never touches Tk: Windows drops a low-level
        hook whose procedure overruns LowLevelHooksTimeout."""
        self._hook_events.put(handler)

    def _hook_event_loop(self) -> None:
        """Thread target. Hands queued hotkey events to Tk, in order."""
        while True:
            self._run_on_tk(self._hook_events.get())

    def _run_on_tk(self, handler: Callable[[], None]) -> None:
        """after() from another thread waits until Tk is free; time the wait."""
        started = time.perf_counter()
        try:
            self.after(0, handler)
        except (RuntimeError, TclError):
            return  # the window is gone; the app is closing
        elapsed = time.perf_counter() - started
        if elapsed > SLOW_HOOK_POST_SECONDS:
            event = handler.__name__.removeprefix("_on_hotkey_")
            logger.warning(f"Tk was busy for {elapsed * 1000:.0f} ms when hotkey {event} arrived")
```

Rewrite the comment on `SLOW_HOOK_POST_SECONDS` (lines 96-98): it now marks a late
hotkey response, not a risk to the hook.

`_deliver_lock` stays. It is now uncontended, and removing it is churn in six tests.

#### 2. S1 failure is a session matter
**File**: `whisper_dictate/gui.py`

- Line 1663: replace `self.after(0, self.var_cleanup_backend.set, "off")` with
  `self._s1_failed = True`.
- Line 1562: `if backend == "s1" and not self._s1_failed:`.
- Line 1363: add `and not self._s1_failed` so a failed model is not re-warmed per press.
- `_close_window`, the `_llm_window` branch (line 346): add `self._s1_failed = False`,
  so closing Cleanup settings is the retry.

#### 3. Tests
**File**: `tests/test_gui_pipeline.py`, `pyproject.toml`

- `mods` fixture: add `m.readback.run.return_value = None`.
- `make_app`: add `app._dictations = MagicMock()` and `app._hook_events = MagicMock()`.
- Line 421: assert `app._s1_failed is True` and that `var_cleanup_backend.set` was not
  called. Add a test that a second dictation after a failure never calls `app.s1.get`.
- Lines 480-482: call `app._run_on_tk(app._on_hotkey_press)` and match the new message.
  Add a test that `_post` only enqueues: `app.after.assert_not_called()`.
- Add a test that `_stop_and_transcribe` puts exactly one cfg on `_dictations`.
- `pyproject.toml`, under `[tool.pytest.ini_options]`:
  `filterwarnings = ["error::pytest.PytestUnhandledThreadExceptionWarning"]`.

### Success Criteria

#### Automated Verification
- [x] `uv run pytest` passes with no warnings summary
- [x] `uv run ruff check .` and `uv run ruff format --check .` pass
- [x] `uv run mypy whisper_dictate` passes

#### Manual Verification
- [x] Twenty tap-to-lock dictations: the hotkey answers every time
- [x] Dictate a long sentence, then a short one before the first has pasted: both paste,
      in the order spoken
- [ ] After a day of use the log has no `held the hook thread` line. `Tk was busy`
      lines may appear; send them back, they name what to fix next

Manual checks 1 and 2 passed 2026-11-21. During the 20-dictation run, the log
recorded zero `held the hook thread` lines and two `Tk was busy` warnings
(`443 ms` and `491 ms` on `release`, both while `recorder.stop()` was running on
Tk), confirming the hook thread stayed clear. Pre-existing UI race observed on
tap-to-lock: `_on_first_audio` arrives after tap release (~263 ms) and
overwrites `Locked; press again to stop` with `Recording; release to stop`;
deferred to Phase 3 where `locked` is added.

**Implementation Note**: after automated verification passes, stop for Dan's manual
confirmation before Phase 2.

---

## Phase 2: Small correctness fixes

### Overview

Five independent fixes, one PR.

### Changes Required

#### 1. Case-insensitive process match
**File**: `whisper_dictate/app_prompts.py`

```python
def _rules_for(app_prompts: AppPromptMap, process_name: str) -> list[AppPromptRule] | None:
    """Windows reports `Notepad.exe` and `WINWORD.EXE`; a rule typed by hand is
    usually lower case. File names are not case-sensitive here, so neither is this."""
    wanted = process_name.lower()
    return next((rules for name, rules in app_prompts.items() if name.lower() == wanted), None)
```

Use it at lines 141 and 174 in place of `app_prompts.get(context.process_name)`. Stored
keys are untouched, so there is no migration and the dialog shows what was typed.

#### 2. Microphone by name
**File**: `whisper_dictate/gui.py`, `_parse_input_device_id` (lines 1183-1205)

Keep the early return for empty, `No input` and `Error` strings. Then:

```python
        index_text, _, name = device_string.partition(":")
        name = name.strip()
        try:
            index = int(index_text.strip())
        except ValueError:
            logger.warning(f"Could not parse device ID from: {device_string}")
            return None
        try:
            devices = sd.query_devices()
        except (sd.PortAudioError, RuntimeError):
            return index

        def matches(i: int) -> bool:
            return (
                0 <= i < len(devices)
                and devices[i].get("max_input_channels", 0) > 0
                and devices[i].get("name", "") == name
            )

        # Indices move when a headset or monitor comes or goes between launches.
        if not name or matches(index):
            return index
        for i in range(len(devices)):
            if matches(i):
                logger.warning(f"Input device moved from index {index} to {i}: {name}")
                return i
        logger.warning(f"Input device {name!r} is not connected; using the default")
        return None
```

The first match is the lowest index, which is the MME entry, the same one the dropdown
lists first.

#### 3. Literal replacements
**Files**: `whisper_dictate/glossary.py:317`, `whisper_dictate/readback.py:96`

A regex rule keeps its group references; every other rule's replacement is literal.

```python
                # A function is used verbatim; a string would have \1 and \n expanded.
                literal = rule.match_type != "regex"
                repl = (lambda _m, text=rule.replacement: text) if literal else rule.replacement
                result = rule.compile_pattern().sub(repl, result)
```

In `readback.py`: `pattern.subn(lambda _m: rule.replacement, out, count=1)`.

#### 4. Log rotation
**File**: `whisper_dictate/logging_config.py:42`

```python
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
```

with `from logging.handlers import RotatingFileHandler`. It subclasses `FileHandler`, so
the `conftest.py` fixture still removes it. The log viewer (`gui.py:852`) is left as it
is: it now reads 2 MB at most.

#### 5. Millisecond clip names
**File**: `whisper_dictate/history.py:43`

```python
def _stamp() -> str:
    now = time.time()
    return time.strftime("%Y%m%dT%H%M%S", time.localtime(now)) + f"{int(now * 1000) % 1000:03d}"
```

Nothing parses the name: the scripts read `audio_file` as an opaque string and pruning
goes by mtime.

#### 6. Tests
- `tests/test_app_prompts.py`: a `notepad.exe` rule resolves for `Notepad.exe`, prompt
  and style.
- `tests/test_gui_pipeline.py` or wherever `_parse_input_device_id` is covered: index
  still right; name moved to another index; name gone returns `None`.
- `tests/test_glossary.py`: a phrase rule with replacement `C:\new\1` comes out verbatim;
  a regex rule with `\1` still substitutes the group.
- `tests/test_readback.py`: `map_to_raw` with a backslash in the edited word.
- `tests/test_history.py`: two `_stamp()` calls in one second differ (patch `time.time`).
- `tests/test_logging_config.py`: the file handler is a `RotatingFileHandler`.

### Success Criteria

#### Automated Verification
- [x] `uv run pytest` passes
- [x] `uv run ruff check .` and `uv run ruff format --check .` pass
- [x] `uv run mypy whisper_dictate` passes

#### Manual Verification
- [x] Dictate into Notepad: the `notepad.exe` rule's style applies
- [x] After the first launch, `~/.whisper_dictate/logs/` holds `whisper_dictate.log.1`
      and a small new log
- [x] A new clip in `~/.whisper_dictate/audio/` has an 18-character stem (three more digits than before)

Manual checks passed 2026-11-21: `whisper_dictate.log` (3.3 MB) rotated to
`whisper_dictate.log.1` on launch beside a 2.3 KB active log, new clips saved
with 18-character millisecond stems (`20261121T113325366.wav`), and dictating
into `Notepad.exe` applied the lowercase `notepad.exe` rule's `email` context.

**Implementation Note**: stop for Dan's confirmation before Phase 3.

---

## Phase 3: Guards, cancel, and copy last

### Overview

Four small behaviours, each visible on the pill.

### Changes Required

#### 1. Silence never reaches the page
**File**: `whisper_dictate/gui.py`

Constants near `TAP_SECONDS`:

```python
# Whisper turns a bumped hotkey into the word "you". The 8 such clips on record
# have a median length of 0.4 s; the shortest real dictation is 0.9 s.
MIN_CLIP_SECONDS = 0.5
# Loudest 100 ms of the clip, as RMS. This is the muted-mic check, not the
# hallucination check: a dead input measures 0.0 and the quietest real dictation
# 0.0027, so the mark sits five-fold under speech.
SILENT_PEAK = 0.0005
SILENCE_WORDS = {"you"}
```

In `_transcribe_and_clean`, after the `audio_data is None` check (line 1493):

```python
        if len(audio_data) < MIN_CLIP_SECONDS * asr.SAMPLE_RATE:
            self._set_status("warning", "Too short; nothing dictated")
            return
        blocks = audio_data[: len(audio_data) // 1600 * 1600].reshape(-1, 1600)
        if np.sqrt((blocks**2).mean(axis=1)).max() < SILENT_PEAK:
            # Says what a level meter would: the wrong input, or a muted one.
            self._set_status("warning", "No sound from the microphone")
            return
```

At line 1547, widen `if not text:` to
`if not text or text.strip(" .!?").lower() in SILENCE_WORDS:`.

Of the 8 "you" clips with audio, the word rule catches all 8, the length rule 4, and
the loudness rule only the fully silent one. None of the three drops any of the 773
real clips.

`gui.py` needs `import numpy as np` if it does not have it.

#### 2. Cleanup that ran away
**File**: `whisper_dictate/s1.py`

```python
def plausible(raw: str, cleaned: str) -> bool:
    """Whether `cleaned` could be a tidied `raw`. S1 normalizes; it does not
    summarize or answer. Over 1,921 real dictations the word count stayed
    within 0.78x to 1.06x, so a result outside 0.5x to 1.5x, or one made mostly
    of new words, is the model misbehaving."""
    before, after = raw.split(), cleaned.split()
    if len(before) < 8:
        return True
    if not 0.5 <= len(after) / len(before) <= 1.5:
        return False
    bare = lambda words: Counter(w.strip(".,;:!?\"'()-").lower() for w in words)  # noqa: E731
    kept = sum((bare(before) & bare(after)).values())
    return kept >= 0.5 * len(after)
```

(Write `bare` as a nested `def` if ruff objects.) In `gui._clean_with_s1`, after the
`if not cleaned` check (line 1669):

```python
        if not s1.plausible(text, cleaned):
            self._set_status("warning", "Cleanup looked wrong; used raw text")
            logger.warning(f"S1 output rejected: {len(text.split())} words in, "
                           f"{len(cleaned.split())} out")
            return None
```

Word counts only in the log, never the text. The endpoint path is not guarded: a custom
prompt there may rightly expand or summarize.

#### 3. Esc cancels a locked recording
**File**: `whisper_dictate/hotkeys.py`

- `VK_ESCAPE = 0x1B`.
- `HotkeyManager.__init__`: `self.locked = False  # set by the app while a tap has locked recording on`.
- `_handle` returns `bool` (whether it consumed the key). First lines, before `resync`:

```python
        if self.locked and is_down and vk == VK_ESCAPE and self.on_cancel:
            self.locked = False
            self.on_cancel()
            return True
```

  Return `False` at every other exit.
- `_hook_proc`: `swallow = self._handle(kb.vkCode, is_down) or (self.chord is not None and self.chord.swallows(kb.vkCode))`.
  The Esc is eaten so the app underneath does not also act on it.

**File**: `whisper_dictate/gui.py`

- `_on_hotkey_release`, the tap branch (line 1377): set `self.hotkey_manager.locked = True`
  (guard for `None`) and change the message to `"Locked; press again to stop, Esc to cancel"`.
- `_on_first_audio`: if `self.hotkey_manager` and `self.hotkey_manager.locked`, keep the
  locked message instead of overwriting it with `"Recording; release to stop"` (a quick
  tap releases before PortAudio delivers the first audio block at ~263 ms).
- `_stop_and_transcribe` and `_on_hotkey_cancel`: set it back to `False`.

#### 4. Copy last dictation
**File**: `whisper_dictate/gui.py`

In `_setup_status_indicator` (line 931), after "Fix last dictation...":
`("Copy last dictation", self._copy_last_dictation)`.

```python
    def _copy_last_dictation(self) -> None:
        """For the paste that landed nowhere: focus moved, or the app ate it."""
        entry = self._last_entry
        if not entry:
            self._set_status("ready", "Nothing dictated yet")
            return
        try:
            # "pasted" is set only for a voice edit (Phase 6) and never reaches disk.
            clipboard.set_text(entry.get("pasted", entry["final"]))
        except clipboard.ClipboardError as e:
            self._set_status("error", "Clipboard locked")
            logger.warning(f"Could not copy the last dictation: {e}")
            return
        self._set_status("ready", "Last dictation copied")
```

#### 5. Tests and docs
- `tests/test_gui_pipeline.py`: `AUDIO` is 1,600 zeros and would now be rejected. Change
  it to one second at amplitude 0.1 (`np.full(16000, 0.1, dtype=np.float32)`). New tests:
  a 0.3 s clip never reaches `asr.get`; a silent 2 s clip reports "No sound"; a
  transcript of "You." is not delivered; an implausible S1 result falls back to raw;
  `_copy_last_dictation` with and without an entry.
- `tests/test_s1.py`: `plausible` at 7 words (always true), at 0.4x, at 1.6x, with half
  the words new, and a normal filler-removal case.
- `tests/test_hotkeys.py`: Esc while `locked` calls `on_cancel` once, returns `True` and
  clears `locked`; Esc while not locked reaches `Chord.feed` as before.
- `README.md`: Esc to cancel, Copy last dictation. `CHANGELOG.md`: four entries.

### Success Criteria

#### Automated Verification
- [x] `uv run pytest` passes
- [x] `uv run ruff check .` and `uv run ruff format --check .` pass
- [x] `uv run mypy whisper_dictate` passes

#### Manual Verification
- [x] Tap the hotkey twice quickly with nothing said: nothing is pasted
- [x] Mute the mic at the hardware, dictate: pill says "No sound from the microphone"
- [x] Tap to lock, press Esc: pill says "Cancelled", nothing pastes, and the focused
      app does not react to the Esc
- [x] Esc still works normally everywhere when no recording is locked
- [x] "Copy last dictation" on the pill puts the last text on the clipboard
- [ ] A week of use shows no false "Cleanup looked wrong"; if one appears, send the
      word counts from the log

Manual checks 1 through 5 passed 2026-11-21 (quick double-tap showed "No audio
captured" and pasted nothing; hardware mute showed "No sound from the
microphone"; tap-to-lock + Esc cancelled without passing Esc through; Esc worked
normally when unlocked; "Copy last dictation" restored the last dictation to
the clipboard).

**Implementation Note**: stop for Dan's confirmation before Phase 4.

---

## Phase 4: Glossary rules scoped to an application

### Overview

A rule may name the applications it applies in. Blank means everywhere, as now. This is
what makes `cloud → Claude` safe: on in Code and the terminal, off in WhatsApp.

### Changes Required

#### 1. The rule and the manager
**File**: `whisper_dictate/glossary.py`

- `GlossaryRule`: `apps: tuple[str, ...] = ()`, process stems in lower case (`code`,
  `windowsterminal`), the key shape `hotwords_for_app` already uses at line 429.
  `to_dict` writes a list; `from_dict` reads one, lower-cases and strips `.exe`.
- `GlossaryManager.for_app(process_name: str | None) -> GlossaryManager`: a new manager
  holding the rules whose `apps` is empty or contains the stem. `None` keeps only the
  unscoped rules.
- `import_csv` and `export_csv`: an `apps` column, stems joined with `;`.

No signature changes to `apply`, `apply_glossary`, `format_for_prompt` or
`clean_with_llm`: the caller hands them the scoped manager.

#### 2. The pipeline
**File**: `whisper_dictate/gui.py`, `_transcribe_and_clean`

After `self._refresh_glossary_cache()` (line 1551):

```python
        scoped = self.glossary_manager.for_app(
            active_context.process_name if active_context else None
        )
```

Use `scoped` in place of `self.glossary_manager` at lines 1552, 1555, 1574, 1593 and in
the skipped-rule loop at 1622. `hotwords_for_app` at line 1507 runs before the refresh;
give it `self.glossary_manager.for_app(...)` too.

#### 3. The dialog
**File**: `whisper_dictate/glossary_dialog.py`

In the rule editor, beside the options at lines 240-243: an entry labelled
"Only in apps (blank for everywhere)", comma-separated, read into `apps` at line 307.
Add an "Apps" column to the list at line 105.

#### 4. Tests and docs
- `tests/test_glossary.py`: a scoped rule fires in its app, for `Code.exe` and `code`
  alike, and not elsewhere; `for_app(None)` drops scoped rules; a file without `apps`
  loads as before; CSV round trip.
- `tests/test_glossary_dialog.py`: the entry round-trips.
- `tests/test_gui_pipeline.py`: `mods.glossary.load_glossary_manager.return_value.for_app.return_value`
  must be the same mock manager, or the existing glossary tests lose their rules.
- `README.md` glossary section, `CHANGELOG.md`.

Known limit, to state in the README: `upsert_rule` keys on the trigger alone, so one
trigger has one rule. A word cannot mean two things in two apps.

### Success Criteria

#### Automated Verification
- [ ] `uv run pytest` passes
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy whisper_dictate` passes

#### Manual Verification
- [ ] Add `cloud → Claude` scoped to `code`. Dictate "the cloud" in VS Code and in
      WhatsApp: only VS Code changes it
- [ ] Existing rules behave as before
- [ ] The glossary file on disk still loads after a downgrade to `main` (unknown keys
      are ignored by `from_dict`)

**Implementation Note**: stop for Dan's confirmation before Phase 5.

---

## Phase 5: Join the dictation to the text at the caret

### Overview

Two dictations into one box come out as `Hello there.And another thing.` today. Before
pasting, read the two characters ahead of the caret and add the missing space. Where the
control cannot be read, nothing changes. No word is ever altered: lower-casing a
sentence continuation was considered and dropped, since it would fire a few dozen times
in two months and is the only part that could make text wrong.

How often this matters: 405 of 2,573 dictations followed another in the same readable
app within 60 seconds (Teams 149, WhatsApp 102, Claude 66), no dictation ends in
whitespace, and 89% end in a full stop, question mark or exclamation mark.

### Step 0: prove the read (gate)

**File**: `whisper_dictate/readback.py`

```python
def before_caret(chars: int = 2) -> str | None:
    """The text just ahead of the caret in the focused control, "" at the start
    of the field, None when it cannot be known. Never raises."""
```

Built on the existing `_client()` and `_focused()`. Through the text pattern:
`GetSelection()`, element 0, `Clone()`, collapse to the start with
`MoveEndpointByRange(End, range, Start)`, then `MoveEndpointByUnit(Start, Character, -chars)`
and `GetText(chars)`. A control with only the value pattern has no caret to ask about:
return `None`. Wrap in `CoInitialize`/`CoUninitialize` as `run()` does.

Also add the read Phase 6 needs, so one session with Dan proves both:

```python
def selection(limit: int = 4000) -> str | None:
    """The selected text of the focused control. None when nothing is selected,
    the control is unreadable, or the selection is longer than `limit`. Never raises."""
```

Extend `main()` (line 235) to print `repr(before_caret())` and `repr(selection())`
beside the existing readability line. Run it against Teams, WhatsApp, Chrome, and the
Claude desktop app: with the caret after a word, after a full stop, and in an empty
box, then with a sentence selected.

**Two gates, judged separately.**

- Phase 5 goes ahead on the right two characters in at least three of the four apps.
  Fewer than that, stop: ship the two reads, the self-check and the `UNREADABLE_APPS`
  change below, and report the table.
- Phase 6 goes ahead on the right selected text in at least three of the four apps,
  whatever the caret result was. Fewer than that, Phase 6 is closed.

Also in this step: add `"code.exe"` to `UNREADABLE_APPS` (line 43). Monaco answers with
a placeholder sentence, so a caret read there would be wrong, and the log shows 203
read-backs that waited 1.5 s to find that out.

### Changes Required (after the gate)

#### 1. The join rule
**File**: `whisper_dictate/readback.py`

```python
def join_text(before: str | None, text: str) -> str:
    """`text` with a leading space when the caret sits hard against other text."""
```

- `before` is `None`, empty, or ends in whitespace: return `text` unchanged.
- `before` ends in an opening bracket or quote (`(`, `[`, `{`, `"`, `'`): unchanged.
- Otherwise return `" " + text`.

#### 2. Delivery
**File**: `whisper_dictate/gui.py`, `_deliver`

Before `clipboard.set_text(text)` (line 1695), when `cfg["smart_join"]` and
`cfg["auto_paste"]`: call `readback.before_caret` on a daemon thread, wait at most
250 ms, treat a timeout as `None`, and rebind `text = readback.join_text(before, text)`.
Subtract the time spent from the `paste_delay` sleep at line 1707 so the paste is not
later than today. The rebound `text` is what `_start_readback` receives, so the watcher
looks for what was actually pasted. Skip the read when the app is in `UNREADABLE_APPS`:
pass the process name into `_deliver` from the caller.

History and the transcript box keep the un-joined text.

#### 3. The setting
`smart_join`, default `True`: `config.py` (`DEFAULT_SMART_JOIN`), the `SETTINGS` tuple
(`gui.py:102`), a `BooleanVar`, a checkbox in the Automation window beside the read-back
one (line 560), `VAR_DEFAULTS` in the tests, the settings block in `CLAUDE.md`,
`README.md`, `CHANGELOG.md`.

#### 4. Tests
- `tests/test_readback.py`: `join_text` as a table: `None`, `""`, `"\n"`, `"d."`,
  `". "`, `"d "`, `"d,"`, `"("`; the text itself is never changed beyond the one space.
- `tests/test_gui_pipeline.py`: the joined text is what is set on the clipboard and
  handed to read-back; a `before_caret` that never returns does not delay the paste
  past `paste_delay`; setting off means `before_caret` is never called.

### Success Criteria

#### Automated Verification
- [ ] `uv run pytest` passes
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy whisper_dictate` passes
- [ ] `uv run python -m whisper_dictate.readback` prints a caret read

#### Manual Verification
- [ ] Gate table recorded in the PR description
- [ ] Two dictations in a row into Teams and into WhatsApp: one space between them
- [ ] Dictate after text that already ends in a space: no second space
- [ ] Dictate into an empty box and into VS Code: unchanged from today
- [ ] The paste feels no slower

**Implementation Note**: stop for Dan's confirmation before Phase 6.

---

## Phase 6: Speak over a selection to edit it

### Overview

With text selected and the setting on, the dictation is an instruction: "make this
friendlier", "turn this into bullets". The endpoint model rewrites the selection and the
paste replaces it. S1 cannot do this: its prompt contract is fixed (`s1.py:1-13`).
Requires the endpoint and model to be set; on this machine that is Ollama with
`qwen2.5:7b-instruct`.

Off by default. A selection plus a dictation already replaces the selection today; this
changes what it is replaced with.

**Gate**: this phase is built only if `readback.selection()` passed its own check in
Phase 5's Step 0, three apps of four. It does not depend on the caret read passing.

The model is not warmed ahead of time. Ollama unloads after its idle period, so the
first edit after a quiet spell waits for a 4.7 GB load; Dan accepted that over reading
the selection at every hotkey press.

### Changes Required

#### 1. Read the selection
**File**: `whisper_dictate/readback.py`

`selection()` already exists from Phase 5's Step 0. Nothing to add.

#### 2. The edit call
**File**: `whisper_dictate/llm_cleanup.py`

`edit_with_llm(selected, instruction, endpoint, model, api_key, temperature, timeout=30.0) -> str | None`,
beside `clean_with_llm` (line 46) and sharing its client and error handling. System
prompt: apply the instruction to the text, output only the rewritten text. Log token
counts as `clean_with_llm` does; never the text.

#### 3. The pipeline
**File**: `whisper_dictate/gui.py`, `_transcribe_and_clean`

After transcription and the glossary pass, when `cfg["voice_edit"]`, the endpoint and
model are set, and `readback.selection()` (same 250 ms budget as Phase 5) returns text:

- status `"Editing selection..."`;
- `edit_with_llm(selection, normalized_text, ...)`;
- on `None` or `LLMCleanupError`: status `"Edit failed; selection unchanged"` and
  **return without pasting**. Pasting the instruction over the selection would destroy it.
- otherwise deliver the result, with `smart_join` and read-back both skipped for this
  dictation.

History records the instruction as `raw` and `final`, with `cleanup_backend="edit"`.
Neither the selection nor the result is written to disk or to the log: the selection is
the user's document, which `history.py:9-13` promises not to keep. `_last_entry` holds
the instruction too, so Fix last dictation corrects what Whisper heard.

The result is kept in memory only, so a paste that lands nowhere can be recovered: after
`history.record` returns, set `self._last_entry["pasted"] = result`. Phase 3's
`_copy_last_dictation` already prefers that key. It cannot leak to disk:
`history.record` has written its line by then, and `record_correction`
(`history.py:152-169`) copies named fields only. It is gone when the app quits or the
next dictation replaces `_last_entry`.

#### 4. The setting
`voice_edit`, default `False`, wired like `smart_join`. The checkbox text says the
selected text is sent to the cleanup endpoint.

#### 5. Tests
- `tests/test_llm_cleanup.py`: `edit_with_llm` builds the two-part message; an API error
  raises `LLMCleanupError`.
- `tests/test_gui_pipeline.py`: selection plus setting on calls the edit and pastes the
  result; edit failure pastes nothing; setting off, or no selection, is a normal
  dictation; the history entry holds no selection text and no result;
  `_copy_last_dictation` after an edit copies the result; a correction banked from that
  entry has no `pasted` key.

### Success Criteria

#### Automated Verification
- [ ] `uv run pytest` passes
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy whisper_dictate` passes

#### Manual Verification
- [ ] Select a paragraph in Teams, say "make this shorter": it is replaced by a shorter one
- [ ] Stop Ollama, repeat: the selection is untouched and the pill says so
- [ ] With the setting off, dictating over a selection behaves as it does today
- [ ] `history.jsonl` for an edit holds the instruction and nothing of the paragraph
- [ ] "Copy last dictation" after an edit gives the rewritten text
- [ ] Time from stop to paste with Ollama warm is acceptable to Dan

**Implementation Note**: stop for Dan's confirmation before Phase 7.

---

## Phase 7: Would per-dictation hotwords help? (experiment)

### Overview

The audit proposed biasing Whisper with words read off the screen. Two things stand in
the way: static hotwords cost 1.2 WER points in the last benchmark
(`research/asr-benchmark-2026.md`), and the focused control is the compose box, so the
words worth having sit in the rest of the window, which would have to be scraped. Before
any of that, measure the best case.

### Changes Required

**File**: `scripts/bench_asr.py`

A candidate `whisper-oracle-hotwords`: for each clip, the hotwords are the domain terms
(`load_terms`, line 135) that occur in that clip's reference, plus ten terms that do
not, standing in for on-screen words nobody says. `run_candidate` (line 349) passes each
clip to an optional `prepare(clip)` on the candidate before `transcribe`. Register it in
`build()` (line 322).

The corrections corpus ignores `--candidates` today: `main()` forces one plain Whisper
run per model (lines 541-542). Make `--candidates` default to `None`; on the corrections
corpus keep the current behaviour when it is not given and honour it when it is. On the
Wispr corpus `None` means the old default list. Phase 8 relies on this too.

Two runs, each to its own file so neither overwrites the September baseline or the
other (the default name is `research/asr-benchmark-<corpus>-<date>.md`):

```powershell
uv run python scripts/bench_asr.py --candidates whisper,whisper-oracle-hotwords --out research/asr-benchmark-oracle-hotwords.md
uv run python scripts/bench_asr.py --corpus corrections --split all --candidates whisper,whisper-oracle-hotwords --out research/asr-benchmark-oracle-hotwords-corrections.md
```

The first is the 198 Wispr clips and decides. The second is all 66 of Dan's own
corrected clips: too few to decide a one-point difference (the held-out split is 10),
so it is a sanity check only.

### Gate

Whisper alone scored 9.0 WER and 86.7 domain recall on the Wispr clips; static hotwords
scored 10.2 and 90.3. Build the live feature only if the oracle scores **WER at or below
9.0 and recall above 90.3** there. That is the ceiling: real on-screen words can only do
worse. If it passes on Wispr but is clearly worse than plain Whisper on the corrections
clips, it does not pass without Dan looking at both tables. A pass earns a separate
plan, starting with what a whole-window read costs in time and what it means for the
privacy note in `history.py`. A fail closes the idea, in writing.

### Success Criteria

#### Automated Verification
- [ ] `uv run pytest` and `uv run ruff check .` pass
- [ ] Both bench commands complete and write their tables
- [ ] `--corpus corrections` with no `--candidates` still gives one row per `--model`

#### Manual Verification
- [ ] Both tables and the decision are in `research/asr-benchmark-oracle-hotwords.md`

---

## Phase 8: Parakeet through ONNX (experiment)

### Overview

Parakeet was ruled out in December 2025 because NeMo would not build on Windows
(`research/parakeet-windows-compatibility.md`). `onnx-asr` 0.12.0 on PyPI now runs it
from wheels: `onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3")`, then `recognize(...)`.

### Changes Required

**File**: `scripts/bench_asr.py`

`ParakeetCandidate`, modelled on `WhisperCandidate` (line 268), importing `onnx_asr`
inside `load()`. Bench `nemo-parakeet-tdt-0.6b-v2` (English only) and `-v3`. Run without
touching the project's dependencies:

```powershell
uv run --with "onnx-asr[gpu,hub]" python scripts/bench_asr.py --candidates whisper,parakeet-v2,parakeet-v3 --out research/asr-benchmark-parakeet.md
uv run --with "onnx-asr[gpu,hub]" python scripts/bench_asr.py --corpus corrections --split all --candidates whisper,parakeet-v2,parakeet-v3 --out research/asr-benchmark-parakeet-corrections.md
```

As in Phase 7, the Wispr run decides and the 66 corrections clips are a sanity check.
The second command needs Phase 7's `--candidates` change.

Check the installed package's README for how `recognize` takes a NumPy array and its
sample rate; only the file-path form was confirmed for this plan. `onnxruntime-gpu`
needs CUDA 12 and cuDNN 9 on the path; if the CUDA provider will not load, run on CPU
and say so in the write-up. CPU numbers still answer the accuracy question.

### Gate

The benchmark's own rule (`research/asr-benchmark-2026.md:11`): lower WER wins unless
within 1.0 point. Parakeet earns a backend plan only at **WER below 8.0**, or within 1.0
of Whisper's 9.0 with domain recall above 86.7, on the Wispr clips. A pass there with a
clearly worse score on the corrections clips does not stand without Dan looking at both
tables. There is no tuned Whisper to beat: `~/.whisper_dictate/models` holds only a
`smoke` folder, and the live model is plain `large-v3-turbo`. Weigh in the write-up what it would
cost: no hotwords, and `scripts/finetune_whisper.py` with its 66 banked corrections does
not carry over. Speed is not a reason: Whisper's p50 on this corpus is 0.09 s.

### Success Criteria

#### Automated Verification
- [ ] `uv run pytest` and `uv run ruff check .` pass (the candidate imports nothing at
      module level)
- [ ] Both bench commands complete

#### Manual Verification
- [ ] Both tables, the decision and the reasoning are in
      `research/asr-benchmark-parakeet.md`

---

## Phase 9: Close the model-subprocess question (write-up)

### Overview

The audit's largest proposal was to move ASR and S1 into a child process and kill it on
idle, to get back the CUDA context `asr.py:276` says is held for life and to keep a
native crash away from the hotkey. The first half was measured while this plan was
reviewed, and it does not pay.

Measured 2026-11-21 on the running app (pid started 2026-11-11 13:01, 236.7 hours up,
166 Whisper loads in that time), with Windows' `\GPU Process Memory(pid_*)\Dedicated Usage`
counter:

| State | Dedicated GPU memory |
|---|---|
| Whisper large-v3-turbo and S1 loaded | 3,908 MB |
| Both released by the idle timer, eight seconds later | 568 MB |

The card is an RTX 5090 with 32,607 MB, so the idle app holds 1.7% of it. The old leak
was 64 MB per load (`asr.py:31-32`): 166 loads would have been about 10.6 GB. The
park-and-reload workaround is holding, and there is no growth to win back. A subprocess
would return about half a gigabyte and add a process start and a CUDA start to every
cold dictation.

Decision, made with Dan: **not built.** This phase only writes that down and checks the
one thing that could reopen it.

### Steps

1. Write the table and reasoning above to `research/idle-vram-2026-11.md`.
2. Search Windows Event Viewer (Application log, source `Application Error`, faulting
   application `pythonw.exe`) back to 2026-09-18, the first line of the app log, for a
   crash with no matching Python traceback in `~/.whisper_dictate/logs/`. Record the
   count and dates in the same file.

### What reopens it

A native crash of the app, found in step 2 or later. Or idle memory that climbs: the
same counter reading well above 568 MB after a comparable uptime. If it is reopened,
the shape is a `Resident` factory that spawns the child with `multiprocessing` and
returns a proxy whose `transcribe` and `clean` go over a pipe and whose `unload()`
terminates the child; `gui.py` does not change and `_parked` is deleted. A move to ONNX
Runtime after Phase 8 would change the numbers and need a fresh reading.

### Success Criteria

#### Manual Verification
- [ ] `research/idle-vram-2026-11.md` holds the measurement, the Event Viewer result and
      the decision

---

## Testing Strategy

### Unit Tests
Listed per phase. The pipeline tests build `App` with `App.__new__` and mocks
(`tests/test_gui_pipeline.py:84-121`); every new attribute a phase adds to `__init__`
needs a line there or a class-level default.

### Integration Tests
None new. `tests/test_integration.py` covers context, prompts, glossary and cleanup and
must keep passing unchanged through Phases 1 to 3.

### Manual Testing Steps
Per phase, by Dan dictating. Nothing here may be tested by injecting input.

## Performance Considerations

- Phase 1 adds no polling: both queues block on `get()`.
- Phase 3's silence check is one pass over the clip, well under a millisecond.
- Phases 5 and 6 add a UI Automation call before the paste, capped at 250 ms and
  absorbed into the existing 150 ms `paste_delay` where it finishes in time.
- Phase 6 adds a full LLM round trip, on by choice only.

## Migration Notes

- Phase 2: the first launch rolls the 3.2 MB log to `whisper_dictate.log.1`. Clip names
  grow by three digits; old clips keep their names and still resolve.
- Phase 4: `apps` is a new optional key in the glossary file. Old files load unchanged;
  an older build ignores the key.
- Phases 5 and 6: two new settings, absent from old files and defaulted on load.
- A setting already written as `"cleanup_backend": "off"` by the old failure path is not
  restored by Phase 1. On this machine it is `s1`.

## References

- Audit: T3 thread "Dictation Tool Audit and Improvements", 2026-11-21, section 4
- Hook timing: `whisper_dictate/gui.py:96-98,1341-1354`, `whisper_dictate/hotkeys.py:274-288`
- Residency: `whisper_dictate/asr.py:155-272`
- Read-back and its limits: `whisper_dictate/readback.py`,
  `plans/2026-10-29-automatic-correction-capture.md`
- Benchmark and its decision rule: `research/asr-benchmark-2026.md`,
  `scripts/bench_asr.py`
- Measurements taken for this plan (2026-11-21, throwaway scripts, not kept): mic open
  on MME and WASAPI; cleanup word ratios over `history.jsonl`; clip length and loudness
  of the "you" dictations; repeated swaps in `corrections.jsonl`
