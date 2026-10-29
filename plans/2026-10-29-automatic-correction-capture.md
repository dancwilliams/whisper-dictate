# Automatic correction capture — Implementation Plan

Written against `main` at `0b1799c` on 2026-10-29. Line numbers are from that commit; if
one has moved, find the quoted code.

## Overview

Every correction Dan makes today has to go through Fix last dictation, which means
remembering to open it. Most real fixes happen somewhere else: in the message box, before
pressing Send. This plan has the app read the control it just pasted into, through Windows
UI Automation, watch it while Dan is still in it, and bank any word swap as a correction
exactly as the Fix dialog would. Two phases, one PR each.

Decisions made with Dan before writing (2026-10-28/29):

- **VS Code is out.** Monaco and the integrated terminal answer "The editor is not
  accessible at this time" unless VS Code runs in screen reader optimised mode, which
  turns word wrap off. Dan chose not to. Windows Terminal exposes its whole screen
  buffer, not a field, and is out too. That leaves Teams, WhatsApp, Chrome, Claude
  desktop and Word: about half of dictations by count, and the half where a message is
  read before it is sent.
- **Polling, not events.** One read a second of one element, on a background thread,
  until focus leaves the control, the field empties (message sent), or two minutes pass.
  UIA event subscriptions need COM callback objects on a dedicated thread for no gain at
  this rate.
- **Word swaps only.** An edit is banked only when it is a replacement of words, found
  the way Find corrections finds them (`glossary.propose_rules`), and every replaced word
  also appears in the raw Whisper text so the label maps back to what Whisper heard.
  Added or removed words are ignored. When less than 60% of the pasted words survive, it
  is a rewrite and nothing is banked. A wrong label trains Whisper to mishear; a missed
  one only fails to help.
- **On by default, three guards.** Runs only when history is on; stores only the pasted
  span and its edited form, never the surrounding field; the status line says
  "Correction captured" each time so it is never silent. The toggle sits under History
  in Settings.
- **comtypes** is added, Windows-only, like `pywin32-ctypes`. Raw ctypes would be a few
  hundred lines of vtable plumbing.

## Ground rules for the implementer

- `uv` for everything: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy whisper_dictate`. `make` is not installed; run the four commands.
- A running Whisper Dictate holds `.venv/Scripts/whisper-dictate.exe`. Ask Dan to quit the
  app (pill right-click, Quit) before the `uv sync` that adds `comtypes`. It runs as
  `pythonw`; stop it by command line, not by the whisper-dictate name.
- One branch and one PR per phase, targeting `main`. Do not start phase 2 until the
  phase 1 PR is merged. Never pass `--auto` to `gh pr merge`; watch checks, then merge.
- No AI attribution in commits or PR text. Commits are GPG-signed; if signing fails, stop
  and ask Dan to unlock the key. Never `--no-gpg-sign`.
- Never inject input (SendInput, pyautogui) on Dan's box to test this. Manual checks are
  Dan dictating; the phase 1 self-check reads whatever Dan has focused.
- Match the code around you. Comments explain why, not what. Keep to the ponytail
  ladder: stdlib first, shortest working diff.
- `CHANGELOG.md` gets an entry under `[Unreleased]` → `### Added` for phase 2.

## Current State Analysis

Measured on 2026-10-28 with a throwaway probe (`uia_probe.py`, scratchpad, not kept):

| Target | Share of 1,791 dictations | UI Automation read-back |
|---|---|---|
| Code.exe | 39% | No: Monaco and xterm return a placeholder sentence |
| ms-teams.exe | 17% | Yes: message box is an Edit with TextPattern (WebView2) |
| WhatsApp.Root.exe | 16% | Yes: message box is an Edit with TextPattern |
| chrome.exe | 10% | Yes: page content exposed once asked; inputs sit inside the Document |
| WindowsTerminal.exe | 5% | Screen buffer only; out of scope |
| claude.exe | 4% | Yes: ProseMirror prompt box is an Edit with TextPattern |
| WINWORD.EXE | 3% | Yes: body is a Document (`_WwG`) with TextPattern |

Two behaviours the design has to carry:

- **Chromium builds its tree on the first ask.** Teams showed nothing on the first
  `FindAll` and everything on the second. Electron apps (Claude desktop) stayed dark to
  every top-down route and only woke when asked through the *focused* window
  (`GetFocusedElement`), which is the route this feature uses anyway. Once on, the tree
  stayed on between runs.
- **`GetFocusedElement` took about 10 ms**, `FindAll` over a whole Teams window 60 ms,
  over Word 100-650 ms. The feature never does a `FindAll`.

### Key Discoveries

- **Delivery is the only place that knows the pasted text and the moment it landed.**
  `_deliver` (`gui.py:1665-1715`) sets the clipboard, calls `clipboard.send_paste()`
  under `_deliver_lock`, then sleeps `restore_delay` and restores. `self._last_entry`
  (`gui.py:1600`) already holds `raw`, `final` and `audio_file` by then, so the watcher
  has everything a correction needs. `_deliver` runs on the dictation worker thread.
- **The correction record is one call.** `history.record_correction(entry, corrected,
  cleanup_wrong)` (`history.py:122-160`) copies the WAV into `training/` and appends a
  JSONL line with `raw`, `final`, `corrected`, `cleanup_wrong`, `app`, `audio_file`. It
  raises nothing. `scripts/finetune_whisper.py:72-74` reads `corrected`, skips rows where
  it equals `raw`, and keeps the latest row per clip, so a clip fixed both automatically
  and by hand is not a conflict.
- **Word-swap mining exists.** `glossary.propose_rules(heard, typed)`
  (`glossary.py:458-476`) runs `difflib` over whitespace-split words with edge
  punctuation stripped and returns one `GlossaryRule(trigger, replacement)` per
  `replace` opcode, nothing for inserts or deletes. It is exactly the filter the
  "word swaps only" decision needs.
- **Settings are a tuple.** `SETTINGS` (`gui.py:99-125`) maps key → Tk variable → type
  and drives load, save and `_read_vars()`, which `_capture_dictation_config`
  (`gui.py:1446-1456`) copies for the worker. A new key is one tuple entry, one
  `BooleanVar` beside `var_history_enable` (`gui.py:248`), and one default in `config.py`
  beside `DEFAULT_HISTORY_ENABLE` (`config.py:47`).
- **The History block in Settings** is rows 6-9 of the Automation window
  (`gui.py:530-562`); Startup follows at rows 10-13. The amber warning label at row 9
  is where the privacy sentence lives.
- **Test harnesses.** `tests/test_gui_pipeline.py` patches the modules the pipeline
  reaches through by name (`:65`), and `make_app` (`:84-118`) must set every attribute
  `App.__init__` sets. `tests/test_history.py` has `TestRecordCorrection` (`:163`)
  with a helper that calls `record_correction(entry, **kw)` (`:168`).
- **mypy** runs with `ignore_missing_imports = true` (`pyproject.toml:99`), so comtypes
  needs no stubs. CI runs on `windows-latest` for lint, typecheck and test, so a
  module that imports comtypes at top level is fine; keep the import inside the
  function anyway so the pure helpers and their tests need no COM.
- **No input injection** is already a house rule (plan 2026-10-12, ground rules). The
  probe honoured it: UI Automation reads, it never sends.

## Desired End State

- After an auto-paste into a readable control, editing a word there and sending or
  moving on writes one line to `~/.whisper_dictate/corrections.jsonl` with
  `source: "auto"`, the raw Whisper text with the swap applied as `corrected`, the span
  Dan ended with as `edited`, and the clip copied to `training/`. The status line shows
  "Correction captured".
- Rewrites, additions, deletions and swaps that do not map onto the raw text bank
  nothing and say so in the log.
- The log carries one line per paste, `Read-back: <process> readable` or `not readable`,
  so after a week the real coverage is a `grep`, not an estimate.
- A tick under Settings → Automation → History turns it off. With history off it never
  runs.
- `uv run python -m whisper_dictate.readback` reads whatever control has focus after a
  countdown and prints whether it is readable, for checking a new app without dictating.

Verification: the automated criteria in each phase, plus Dan dictating into each of the
five apps and fixing one word.

## What We're NOT Doing

- VS Code or Windows Terminal, and no screen-reader-mode advice in the app.
- Reading when auto-paste is off or the paste failed: the app does not know where the
  text went.
- UIA event subscriptions, a COM apartment thread, or any `FindAll`.
- Storing the field's surrounding text, the window title, or anything but the pasted
  span and its edit. Same privacy rule as `history.py`'s docstring.
- Banking insertions, deletions or rewrites, even as "cleanup wrong" data.
- Changing the Fix dialog, `propose_rules`, the benchmark, or the fine-tune script.
- A viewer for captured corrections. `corrections.jsonl` is the record.
- Glossary rules from automatic captures. A rule stays a deliberate tick in the dialog.

## Implementation Approach

Phase 1 is the reader on its own: a module with pure helpers for finding the pasted span
and mapping the edit back, a UIA watcher, and a command-line self-check Dan can point at
any app. It ships with the dependency and no app change, so the risky part (COM, other
apps' trees) is exercised alone. Phase 2 wires it into delivery behind the setting, banks
the result, and documents it.

---

## Phase 1: The reader

### Overview

`whisper_dictate/readback.py`: given the pasted text, find the focused control, confirm
the text is in it, poll until the edit is finished, and return the edited span. Pure
helpers do the matching so they are testable without COM.

### Changes Required

#### 1. `pyproject.toml`

In `dependencies`, after `"openai>=3.16"`:

```toml
    # UI Automation client for reading back the control a dictation was pasted into.
    "comtypes>=1.4.17; sys_platform == 'win32'",
```

Ask Dan to quit the app, `uv sync`, commit `uv.lock`. Check it imports:
`uv run python -c "import comtypes.client; comtypes.client.GetModule('UIAutomationCore.dll'); print('ok')"`.
comtypes writes generated wrappers into `.venv/Lib/site-packages/comtypes/gen/` on first
use; that is expected.

#### 2. `whisper_dictate/readback.py` (new)

```python
"""Read back the control a dictation was pasted into, and notice what changed.

Windows UI Automation can read the text of most edit controls from another
process. After an auto-paste the app asks for the focused control, checks the
pasted text is in it, then polls once a second while Dan is still there. The
stretch of text the paste became is compared with what was pasted; a word swap
is a correction. Reading goes through the focused window because Electron
apps only build their accessibility tree when asked that way.

Privacy: the only text that leaves this module is the pasted span as Dan left
it. The rest of the field is read to find that span and dropped.
"""

from __future__ import annotations

import difflib
import logging
import re
import sys
import threading
import time
from typing import Any

from whisper_dictate import glossary

logger = logging.getLogger("whisper_dictate")

POLL_SECONDS = 1.0
WATCH_SECONDS = 120.0
# Chromium builds its accessibility tree after the first ask; give it a moment.
FIRST_READ_TRIES = 3
FIRST_READ_WAIT = 0.5
# Below this share of surviving words the edit is a rewrite, not a correction.
MIN_KEEP = 0.6
# How far, in words, a matching run may drift from where the paste would sit.
SLACK = 5

UIA_TEXT_PATTERN = 10014
UIA_VALUE_PATTERN = 10002


def edited_span(field: str, pasted: str) -> list[str] | None:
    """The words the pasted text became, or None when it is no longer there.

    Anchors on the longest run of matching words, projects where the paste
    would sit unchanged, and keeps the runs near that window: a common word
    matching elsewhere in a long document must not stretch the span.
    """
    fw, pw = field.split(), pasted.split()
    if not pw:
        return None
    blocks = [
        b
        for b in difflib.SequenceMatcher(None, fw, pw, autojunk=False).get_matching_blocks()
        if b.size
    ]
    if not blocks:
        return None
    anchor = max(blocks, key=lambda b: b.size)
    start = anchor.a - anchor.b
    near = [b for b in blocks if start - SLACK <= b.a and b.a + b.size <= start + len(pw) + SLACK]
    if sum(b.size for b in near) < MIN_KEEP * len(pw):
        return None
    first, last = near[0], near[-1]
    # shortcut: an edited edge word is assumed to stay one word; a 1-to-2 swap at
    # either end loses a word. Upgrade to char offsets if the bank shows it matters.
    lo = max(0, first.a - first.b)
    hi = min(len(fw), last.a + last.size + (len(pw) - last.b - last.size))
    return fw[lo:hi]


def map_to_raw(raw: str, final: str, edited: str) -> str | None:
    """Carry each word swap between the pasted and edited text onto the raw
    Whisper text. None when there is no swap, or a swap has nowhere to land
    (cleanup reworded it): the label would not be what Whisper heard."""
    rules = glossary.propose_rules(final, edited)
    if not rules:
        return None
    out = raw
    for rule in rules:
        pattern = re.compile(rf"(?<!\w){re.escape(rule.trigger)}(?!\w)", re.IGNORECASE)
        out, n = pattern.subn(rule.replacement, out, count=1)
        if n == 0:
            return None
    return out


class _Target:
    """One focused control and the pattern it reads through."""

    def __init__(self, uia: Any, element: Any, iface: Any):
        self.uia = uia
        self.element = element
        self.text = self.value = None
        try:
            self.text = element.GetCurrentPattern(UIA_TEXT_PATTERN).QueryInterface(
                iface.IUIAutomationTextPattern
            )
        except Exception:  # COMError or AttributeError: no text pattern
            try:
                self.value = element.GetCurrentPattern(UIA_VALUE_PATTERN).QueryInterface(
                    iface.IUIAutomationValuePattern
                )
            except Exception:
                pass

    def read(self) -> str | None:
        try:
            if self.text is not None:
                return str(self.text.DocumentRange.GetText(-1))
            if self.value is not None:
                return str(self.value.CurrentValue)
        except Exception as e:  # COMError: the control went away
            logger.debug(f"Read-back lost the control: {e!r}")
        return None

    def still_focused(self) -> bool:
        try:
            return bool(self.uia.CompareElements(self.element, self.uia.GetFocusedElement()))
        except Exception:
            return False


def _client() -> tuple[Any, Any]:
    import comtypes.client

    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as iface

    uia = comtypes.client.CreateObject(iface.CUIAutomation8, interface=iface.IUIAutomation)
    return uia, iface


def _find(uia: Any, iface: Any, pasted: str) -> _Target | None:
    for _ in range(FIRST_READ_TRIES):
        target = _Target(uia, uia.GetFocusedElement(), iface)
        text = target.read()
        if text is not None and " ".join(pasted.split()) in " ".join(text.split()):
            return target
        time.sleep(FIRST_READ_WAIT)
    return None


def _watch(target: _Target, pasted: str, stop: threading.Event) -> str | None:
    last = pasted.split()
    deadline = time.monotonic() + WATCH_SECONDS
    while not stop.wait(POLL_SECONDS) and time.monotonic() < deadline:
        if not target.still_focused():
            break
        text = target.read()
        if text is None or not text.strip():
            break  # sent, cleared, or gone: the last snapshot is the answer
        span = edited_span(text, pasted)
        if span is not None:
            last = span
    return None if last == pasted.split() else " ".join(last)


def run(pasted: str, stop: threading.Event, app: str = "") -> str | None:
    """Find the control `pasted` landed in and watch it until Dan moves on.

    Returns the edited span when it differs from the paste, None otherwise.
    Call on its own thread; it blocks for up to WATCH_SECONDS. Never raises.
    """
    if sys.platform != "win32":
        return None
    import comtypes

    comtypes.CoInitialize()
    try:
        uia, iface = _client()
        target = _find(uia, iface, pasted)
        if target is None:
            logger.info(f"Read-back: {app or '?'} not readable")
            return None
        logger.info(f"Read-back: {app or '?'} readable")
        return _watch(target, pasted, stop)
    except Exception as e:
        logger.warning(f"Read-back failed: {e!r}")
        return None
    finally:
        comtypes.CoUninitialize()


def main() -> None:
    """Self-check: count down, read the focused control, say whether it is readable."""
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
    print(f"Click into the box you want to check; reading in {delay:.0f}s")
    time.sleep(delay)
    import comtypes

    comtypes.CoInitialize()
    try:
        uia, iface = _client()
        target = _Target(uia, uia.GetFocusedElement(), iface)
        text = target.read()
        print("not readable" if text is None else f"readable, {len(text)} chars")
    finally:
        comtypes.CoUninitialize()


if __name__ == "__main__":
    main()
```

Notes for the implementer:

- `_find` normalises whitespace on both sides because Chromium editors turn a
  newline into a paragraph and Word returns `\r`.
- `comtypes.CoInitialize()` is per thread; `run` is called on a fresh daemon thread
  each time (phase 2), never on the Tk thread.
- `CompareElements` is the documented way to ask whether two element objects are the
  same control; runtime IDs would also work but need a SAFEARRAY round trip.
- Keep `edited_span` and `map_to_raw` free of COM so `tests/test_readback.py` runs in CI.

#### 3. `tests/test_readback.py` (new)

`edited_span` (word lists in, word list out):

- unchanged paste inside a longer field returns the pasted words;
- one middle word swapped returns the field's words with the swap;
- the first word swapped is included (`lo` projects back);
- text typed after the paste is not in the span;
- the paste deleted from the field returns None;
- a rewrite keeping two of ten words returns None;
- a paste of common words inside a 300-word document whose other sentences share
  those words still returns just the pasted sentence (the SLACK guard);
- an empty paste returns None.

`map_to_raw`:

- `("I met jon today.", "I met Jon today.", "I met John today.")` → `"I met John today."`
  (case-insensitive trigger, replacement as typed);
- a swap whose trigger is not in the raw text (cleanup reworded it) returns None;
- an insertion-only edit returns None;
- two swaps both land.

`_watch` and `_find` with a fake target: a small class with `read()` returning a
scripted sequence and `still_focused()` a scripted sequence; `stop` an Event.

- `_find`: first read None, second read contains the paste → returns a target
  (patch `_Target` to the fake and `time.sleep`);
- `_watch`: readings `[pasted, edited, ""]` returns the edited span (the empty read
  ends it and the last snapshot wins);
- `_watch`: readings `[pasted, pasted]` then focus lost returns None;
- `_watch`: `stop.set()` before the first poll returns None.

`run` on a non-win32 platform (monkeypatch `sys.platform`) returns None without
importing comtypes.

### Success Criteria

#### Automated Verification
- [x] `uv run pytest tests/test_readback.py` passes
- [x] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
      `uv run mypy whisper_dictate` exit 0
- [x] CI green on the PR (comtypes resolves on `windows-latest`; the lint job on
      ubuntu never imports it)

#### Manual Verification
- [x] `uv run python -m whisper_dictate.readback 10`, click into a Teams message box
      with a word in it: prints `readable, N chars`
- [x] Same with the Claude desktop prompt box, a WhatsApp message box, a Chrome text
      area, and a Word document
- [x] Same with the VS Code editor: prints `readable, 99 chars` (the placeholder
      sentence). This is why `_find` checks the paste is in the text rather than
      trusting "readable"

Manual checks passed 2026-10-29 in all five apps and VS Code. WhatsApp needed a
fallback: its WinUI host reports the WebView2 bridge pane as focused, so an
unreadable pane is searched, scoped to itself, for the descendant with keyboard
focus (`_focused`). Focus is checked on the element itself (`CurrentHasKeyboardFocus`)
instead of `CompareElements`, which would name the pane again.

**Implementation Note**: pause here for Dan's manual check before phase 2.

---

## Phase 2: Wire it into delivery

### Overview

A setting, a watcher thread started after a successful paste, the correction banked
with its source, the status line, and the docs.

### Changes Required

#### 1. `whisper_dictate/config.py`

After `DEFAULT_HISTORY_AUDIO_DAYS` (`config.py:48`):

```python
# After an auto-paste, read the box the text landed in and bank a changed
# word as a correction. Only the pasted span is kept; see readback.py.
DEFAULT_READBACK_ENABLE = True
```

#### 2. `whisper_dictate/history.py`

`record_correction` (`history.py:122`) grows two keyword arguments and writes them:

```python
def record_correction(
    entry: dict[str, Any],
    corrected: str,
    cleanup_wrong: bool = False,
    path: Path | None = None,
    audio_dir: Path | None = None,
    training_dir: Path | None = None,
    *,
    source: str = "manual",
    edited: str | None = None,
) -> bool:
```

In the appended dict, after `"cleanup_wrong"`:

```python
            # "manual" from the Fix dialog, "auto" from readback. `edited` is the
            # pasted span as the user left it; `corrected` is that swap carried
            # onto the raw text, which is what training reads.
            "source": source,
            "edited": edited,
```

The module docstring's privacy paragraph gains one sentence: "An automatic capture
keeps the pasted span and its edit, never the rest of the field."

#### 3. `whisper_dictate/gui.py`

- Import: `readback` joins the `from whisper_dictate import ...` list;
  `DEFAULT_READBACK_ENABLE` joins the config import (`gui.py:53-54`).
- `SETTINGS` (`gui.py:104-105`): after `("history_audio_days", ...)` add
  `("readback_enable", "var_readback_enable", bool)`.
- `__init__` (`gui.py:249`): `self.var_readback_enable = BooleanVar(value=DEFAULT_READBACK_ENABLE)`.
  Beside `self._deliver_lock` (`gui.py:185`): `self._readback_stop: threading.Event | None = None`.
- History block in the Automation window (`gui.py:530-562`): after the `hist_row`
  frame at row 8, insert

```python
            ttk.Checkbutton(
                frame,
                text="Learn from edits you make after a paste",
                variable=self.var_readback_enable,
            ).grid(row=9, column=0, sticky="w")
```

  The amber label moves from row 9 to row 10 and its text becomes
  `"Transcripts and recordings are written to ~\.whisper_dictate. They never leave this
  machine, and window titles are never stored. After a paste, only the box the text
  landed in is read, and only the pasted words are kept."`. Startup rows 10-13 become
  11-14.
- `_deliver` (`gui.py:1665-1715`): set `pasted_ok = False` before the `try` that
  sets the clipboard; inside the `if cfg["auto_paste"]:` branch replace the bare
  `clipboard.send_paste()` call with `pasted_ok = clipboard.send_paste()` and test
  `if not pasted_ok:` where it tests `if not clipboard.send_paste():` today. After the
  `finally` block that restores the clipboard, outside `_deliver_lock`, add

```python
        if pasted_ok:
            self._start_readback(text, cfg)
```

  Starting after the restore means the watcher never overlaps the `restore_delay`
  sleep, and `_find`'s retries cover the half-second that costs.

- New methods after `_deliver`:

```python
    def _start_readback(self, pasted: str, cfg: dict[str, Any]) -> None:
        """Watch the pasted-into control for an edit, on its own thread. Worker thread."""
        if not (cfg["readback_enable"] and cfg["history_enable"]):
            return
        entry = self._last_entry
        if not entry or not entry.get("raw"):
            return
        if self._readback_stop is not None:
            self._readback_stop.set()  # a new paste ends the last watch
        stop = self._readback_stop = threading.Event()
        threading.Thread(
            target=self._readback_worker, args=(entry, pasted, stop), daemon=True
        ).start()

    def _readback_worker(self, entry: dict[str, Any], pasted: str, stop: threading.Event) -> None:
        """Thread target. Blocks until Dan leaves the control; banks a word swap."""
        edited = readback.run(pasted, stop, entry.get("app", ""))
        if edited is None:
            return
        corrected = readback.map_to_raw(entry["raw"], pasted, edited)
        if corrected is None:
            logger.info("Read-back: edit was not a word swap, nothing banked")
            return
        history.record_correction(entry, corrected, source="auto", edited=edited)
        self._set_status("ready", "Correction captured")
```

  `_set_status` is already called from worker threads (`gui.py:1588`), so it is safe
  here. `entry["raw"]` is the Whisper text; `pasted` is `entry["final"]`.

#### 4. Tests

- `tests/test_gui_pipeline.py`: add `"readback"` to the patched module names (`:65`);
  in `make_app` add `app._readback_stop = None`; in `VAR_DEFAULTS` add
  `"var_readback_enable": True`. New tests in the delivery class:
  - `test_readback_starts_after_a_paste`: with history on, after `run(app)` (the
    existing helper that drives `_transcribe_and_clean`), `mods.readback.run` was called
    with the final text, an `Event`, and the app name. Patch `gui.threading.Thread` so
    `start()` runs the target inline.
  - `test_readback_skipped_when_off`: `var_readback_enable=False` → `run` not called.
    Same with `var_history_enable=False`, and with `send_paste` returning False.
  - `test_readback_banks_a_word_swap`: call `app._readback_worker(entry, "I met Jon", stop)`
    with `mods.readback.run.return_value = "I met John"` and
    `mods.readback.map_to_raw.return_value = "i met John"`: `record_correction` called
    with `source="auto", edited="I met John"`, status set to "Correction captured".
  - `test_readback_ignores_non_swaps`: `map_to_raw.return_value = None` →
    `record_correction` not called.
  - `test_second_paste_stops_the_first_watch`: call `_start_readback` twice with the
    Thread patched to not run; the first `Event` is set.
- `tests/test_history.py`, `TestRecordCorrection`: the line carries
  `source: "manual"` and `edited: null` by default, and `source: "auto"`,
  `edited: "..."` when passed.

#### 5. Docs

- `README.md:123-127`: a new bullet after the Fix last dictation one: "When
  **Learn from edits you make after a paste** is on (Settings → Automation → History),
  the app reads the box it pasted into, and if you change a word before sending or
  moving on, the fix is kept as a correction the same way. Only the pasted words are
  read back. Works in Teams, WhatsApp, Chrome, Claude desktop and Word; VS Code does
  not expose its editor."
- `README.md`, Tuning section (`:137`): "Every **Fix last dictation** you save, and
  every edit the app captures after a paste, is a training label".
- `CLAUDE.MD`: module table row
  `| readback.py | Read back the pasted-into control via UI Automation and bank word swaps | run(), edited_span(), map_to_raw() |`;
  settings JSON gains `"readback_enable": true` after `history_audio_days`; Data Flow
  step 7: "**Edits watched** (optional) → `readback.py` polls the pasted-into control
  and banks a word swap with `history.record_correction`".
- `docs/architecture.md`: module table row and the same data-flow line; `:47` bucket
  text unchanged (same files).
- `CHANGELOG.md` → `### Added`: "After a paste, the app can read the box it pasted
  into and keep a changed word as a correction (Settings → Automation → History)."

### Success Criteria

#### Automated Verification
- [x] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
      `uv run mypy whisper_dictate` exit 0
- [ ] CI green on the PR

#### Manual Verification
- [ ] Dictate into Teams, change one word, press Send: status reads "Correction
      captured", `corrections.jsonl` gains a line with `source: "auto"`, `edited` holds
      the sentence as sent, `corrected` is the raw text with the swap, and the WAV is in
      `training/`
- [ ] Same in WhatsApp, the Claude desktop prompt, a Chrome text area, and Word (in
      Word, click elsewhere in the document to end the watch)
- [ ] Dictate and send unchanged: nothing banked, no status change
- [ ] Dictate, delete the whole message, type something else: log says "not a word
      swap", nothing banked
- [ ] Dictate into VS Code: log says `Read-back: Code.exe not readable`, nothing else
      happens, VS Code shows no accessibility notice
- [ ] Untick the setting: no `Read-back:` lines in the log
- [ ] Fix last dictation still works on a dictation that was also captured
      automatically (two lines for one clip; training keeps the later one)

---

## Testing Strategy

### Unit Tests
- `edited_span`: anchoring, SLACK guard, edge-word swaps, rewrite and deletion → None.
- `map_to_raw`: case-insensitive landing, unmapped swap → None, no swap → None.
- `_find` / `_watch` with a fake target: retry, empty-field end, focus-loss end, stop.
- `record_correction`: `source` and `edited` in the line.
- GUI: watcher starts only after a successful auto-paste with both settings on; a swap
  is banked with `source="auto"`; a non-swap is not; a new paste stops the old watch.

### Integration Tests
- `test_gui_pipeline.py` drives `_transcribe_and_clean` end to end with `readback`
  mocked, as it does for `history` and `clipboard`.

### Manual Testing Steps
1. Phase 1 self-check in each of the five apps and in VS Code.
2. Phase 2: one real correction per app; one unchanged send; one rewrite; one VS Code
   dictation; setting off.
3. After a week: `grep "Read-back:" ~/.whisper_dictate/logs/whisper_dictate.log | sort | uniq -c`
   for the real coverage.

## Performance Considerations

- One `GetFocusedElement` (about 10 ms) and one `GetText` per second on one element,
  on a daemon thread, for at most two minutes per dictation. Word's 8.6k-character body
  and a word-level `SequenceMatcher` each second is a few milliseconds.
- Chromium keeps its accessibility tree on in the target app once asked. Teams and
  WhatsApp already have it on; Chrome and Claude desktop will from the first paste.
  That is the same cost a screen reader imposes and was not noticeable during probing.
- The watcher never runs on the Tk thread and never holds `_deliver_lock`.

## Migration Notes

- Existing `corrections.jsonl` rows have no `source` key; readers treat a missing one as
  manual. `finetune_whisper.py` and `bench_asr.py` read only `corrected` and
  `audio_file` and need no change.
- `readback_enable` is absent from existing settings files; `settings_store` falls back
  to the Tk variable's default, which is on.

## References

- Delivery: `whisper_dictate/gui.py:1665-1715`; last entry `gui.py:1600`
- Correction record: `whisper_dictate/history.py:122-160`; consumers
  `scripts/finetune_whisper.py:68-74`, `scripts/bench_asr.py:124`
- Word-swap mining: `whisper_dictate/glossary.py:458-476`
- Settings plumbing: `whisper_dictate/gui.py:99-125`, `:248-249`, `:1446-1456`;
  `whisper_dictate/config.py:47-48`
- Settings UI: `whisper_dictate/gui.py:530-580`
- Test harnesses: `tests/test_gui_pipeline.py:60-118`, `tests/test_history.py:163-168`
- Prior plan and house rules: `plans/2026-10-12-correction-loop-and-personal-finetune.md`
- Probe findings (2026-10-28): Teams, WhatsApp, Chrome, Claude desktop and Word readable
  through the focused element; VS Code returns "The editor is not accessible at this
  time. To enable screen reader optimized mode, use Shift+Alt+F1" from both Monaco and
  xterm; Electron trees wake only via `GetFocusedElement`
