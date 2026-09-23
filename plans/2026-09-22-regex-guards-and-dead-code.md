# Regex guards and dead code — Implementation Plan

Written against `main` at `e10e32f`. Source: `advisor-plans/intake-2026-09-22.md` (the
third intake report; sections 4, 5 and 7). The plan was drafted from that run's
`ponytail-audit` before the report was written; the report's bug IDs (G1, G2) and deletion
list were aligned to it, and phase 2 (G3, G4) was added when `improve` ran afterwards.
House style and ground rules follow `plans/2026-09-21-second-intake-fixes.md`.

## Overview

The intake found two things that matter and a short tail of rounding.

The first — G1 and G2 in the report, deletion item 1: `app_prompts.py` carries 115 lines of hand-rolled ReDoS defence — a
character-by-character regex nesting parser plus a thread-per-match timeout — guarding two
call sites that match a window title against a pattern the user typed into their own
settings dialog. Meanwhile `glossary.py` compiles the user's regexes with no guard at all,
and *neither* dialog checks a pattern when it is saved.

So the repo has both halves wrong, in opposite directions: ceremony where nothing threatens
it, nothing where a bad pattern really does cost a dictation. This plan puts both on one
rule:

> **Validate when the rule is saved. Catch `re.error` where it is used. No timeout thread.**

The second — G3: `save_settings` strips the API key from the settings file whether or not
the keyring store succeeded. When Credential Manager is unavailable the key is silently
lost: not in the keyring, not in the file, and the app says nothing. The previous fix plan
fixed exactly this on the *migration* path (`3906342`, "dropping it first would lose the
key") and not on the save path one function down, which a failed migration then falls
through to. G4, a small cross-thread race on the audio buffer, rides along.

Three phases, one PR each. Phase 1 is the regex rule; phase 2 is G3 and G4; phase 3 is
dead data and stranded lines.

## Ground rules for the implementer

- `uv` for everything: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy whisper_dictate`. `make` is optional on this box; run the four commands.
- CI excludes the heavy ML wheels (`--no-group ml`). Locally the `.venv` has them; do not re-sync with different groups and leave the venv changed.
- One branch and one PR per phase, targeting `main`. `main` requires five green checks. Do not start a phase until the previous PR is merged.
- No AI attribution in commits or PR text. Commits are GPG-signed; if signing fails, stop and tell Dan to cache the key. Never `--no-gpg-sign`.
- Match the code around you. Comments explain why, not what.
- Line numbers are from `e10e32f`. If a line has moved, find the quoted code.
- `CHANGELOG.md` gets an entry under `[Unreleased]` for each user-visible change, in the register already there: symptom, then cause, then what it does now.

## Current State Analysis

Measured 2026-09-22 with `uv run --no-sync`:

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | exit 0, 46 files |
| `mypy whisper_dictate` | exit 0, 21 source files |
| `pytest` | 360 passed, 3 skipped, 4.46 s, 65% |
| `gitleaks detect` (8.30.1) | exit 0, 184 commits, no leaks |
| CI on `main` | green (`e10e32f`, run 35722171077) |

### Key Discoveries

- **The guard's own test is wrong about its threat.** `tests/test_app_prompts.py:399-417`
  calls `(a+)+` against `"a"*25 + "X"` "input that triggers catastrophic backtracking".
  Measured: `re.search("(a+)+", "a"*25+"X")` returns a match in **0.065 ms**. Unanchored,
  it succeeds at position 0 and never backtracks. Catastrophic backtracking needs a
  *failing* match — `re.search("(a+)+$", "a"*24+"X")` takes **598 ms**. The validator
  rejects both, so the suite has been proving that a harmless pattern is blocked.
- **The timeout does not stop a ReDoS.** `safe_regex_search` (`app_prompts.py:194-238`)
  runs the match on a daemon thread and calls `thread.join(timeout=0.5)`. A thread cannot
  be killed from outside: the join returns, the function returns `False`, and the runaway
  match keeps burning a core for as long as it takes. It stops *waiting*, not burning. The
  docstring's "fail safe" is true of the return value only.
- **There is no trust boundary here.** Both call sites (`app_prompts.py:263`, `:296`) match
  `context.window_title` — bounded by Windows, read via `GetWindowTextW` — against
  `rule["window_title_regex"]`, which comes from the user's own settings file, typed into
  their own dialog. Nothing crosses from anyone else.
- **`validate_regex_pattern` is a partial reimplementation of a regex parser** — 50 lines
  walking the pattern character by character tracking group nesting, to decide something
  `re` already knows while parsing.
- **The mirror-image gap: `glossary.py` guards nothing.** `GlossaryRule.compile_pattern`
  (`glossary.py:99-117`) calls `re.compile(self.trigger, flags)` for a `regex` rule, and
  `apply()` (`glossary.py:312`) calls it inside the dictation path with no `try`. Neither
  is `rule.replacement` guarded: `pattern.sub(r"\9", text)` raises
  `re.error: invalid group reference 9` (measured).
- **`re.error` is not a `ValueError`.** Its MRO is `(re.error, Exception, BaseException,
  object)`, so the worker's `except (TranscriptionError, OSError, RuntimeError, ValueError)`
  (`gui.py:1420`) would not catch it — and the two `apply_glossary` calls (`gui.py:1457`,
  `:1496`) sit outside that `try` anyway.
- **What a bad glossary regex actually costs today.** The last-resort handler added in the
  previous plan (`gui.py:1378-1385`) catches it, so the pill does not stick. The dictation
  is lost instead: status "Dictation failed; see the log", audio gone, every time, until
  the offending rule is found by hand. The log names the exception, not the rule.
- **Neither dialog validates a pattern at save.** `AppPromptEntryDialog._on_save`
  (`app_prompt_dialog.py:265-286`) checks the process name and that a prompt or style is
  set, then stores `window_title_regex` unread. `GlossaryRuleDialog._on_save`
  (`glossary_dialog.py:281-300`) checks trigger and replacement are non-empty and runs
  `phonetic_rejection` for phonetic rules — and nothing for `regex` rules.
- **The house pattern for save-time validation already exists.**
  `phonetic_rejection(trigger) -> str | None` (`glossary.py:128`) returns a reason string
  the dialog shows with `messagebox.showerror`. That is the shape to copy.
- `app_prompt_dialog.py` already imports `re` (`:5`, for `re.escape` at `:142`), so its
  validation needs no new import. `glossary_dialog.py` does not import `re`.
- ~~**`MODEL_INFO`'s `speed` and `description` are read by nothing.**~~ Wrong: `gui.py:434-439`
  reads both for the model description label. The grep that said otherwise was truncated
  by `head`. Retracted in phase 3.
- The `isinstance(disk_mb_value, (int, float))` guard and its `"? MB"` branch
  (`config.py:215-221`) exist only because `MODEL_INFO` is typed
  `dict[str, dict[str, str | int | float]]`. Every literal in the file is an int.
- **`save_settings` loses the key on a keyring failure.** `_store_secure_settings`
  (`settings_store.py:101-118`) catches `CredentialStorageError` at `:113`, logs at
  WARNING, and returns nothing. `save_settings` (`:52-77`) then builds
  `settings_to_save` without any `SECURE_KEYS` entry at `:61`, writes it at `:67`, and
  returns `True`. `App._save_settings` (`gui.py:1025-1042`) checks only that boolean and
  only logs. `_migrate_secure_settings` (`:80-97`) was fixed for this in `3906342` — it
  stores first and deletes on success, with the test
  `tests/test_settings_store.py:265-271` — but on failure it leaves the plaintext in the
  dict, the GUI loads it into `var_llm_key`, and the next save loses it through `:61`.
- `_save_settings` runs from three places: the settings-window close (`gui.py:350`,
  `:1096`), `_on_close` (`:1047`), and `main()`'s `finally` after the mainloop (`:1659`).
  A `messagebox` in the last of those has no live Tk to show in.
- **The audio buffer is read on the worker and cleared on Tk.** `_stop_and_transcribe`
  (`gui.py:1357-1364`) stops the recorder, captures `cfg`, and spawns the worker; the
  worker's first line is `self.recorder.get_buffer()` (`:1393`). `AudioRecorder.start()`
  begins with `self._audio_buffer = []` (`audio.py:78-79`) on the Tk thread. Each access
  holds `_buffer_lock`; the sequence does not.
- `_capture_dictation_config` (`gui.py:1366-1371`) is documented "Main thread only" and
  is the one place that already copies everything the worker needs. The pipeline harness
  sets `app.recorder.get_buffer.return_value` (`tests/test_gui_pipeline.py:100`) and its
  `run()` helper calls `_transcribe_and_clean(app._capture_dictation_config())` (`:118-120`),
  so reading the buffer inside `_capture_dictation_config` keeps every harness test valid
  unchanged.

## Desired End State

One rule governs every user-authored regex in the app, in both places, and it is the rule
the rest of the repo already follows:

- A pattern that will not compile cannot be saved — the dialog says so, in the same shape
  `phonetic_rejection` already uses, with the `re` module's own message.
- A pattern that reaches the matcher anyway — a hand-edited JSON file, a settings file from
  an older build — is skipped with a log line naming the rule, and costs nothing else.
- A bad glossary rule, trigger or replacement, no longer costs the dictation.
- `app_prompts.py` has no ReDoS vocabulary in it, and no thread.
- An API key that cannot be stored in Credential Manager is never silently lost: the
  file is still written without it (policy: the key never goes to disk), the save reports
  failure, and while a window is open the user is told to keep a copy.
- The audio buffer is read on the thread that stopped the recorder, before anything can
  start it again.

## What We're NOT Doing

- **Not deleting `scripts/mine_wispr_history.py`.** The audit listed it again (report
  section 5, item 2, struck through); `plans/2026-09-21-second-intake-fixes.md:17` already
  ruled it stays. Recorded decision, not a finding.
- **Not adding a time limit anywhere**, including a replacement one. The accepted ceiling
  is written into the code as a `ponytail:` comment (standards 3.3), so the next reader
  knows it was a decision.
- **Not touching phonetic matching**, `MIN_PHONETIC_CODE`, or `phonetic_rejection`.
- **Not extracting a shared validator** across `app_prompts` and `glossary`. It is one
  `re.compile` in a `try` at each end; centralising three lines across a module boundary
  that does not otherwise exist costs more than it saves. If a third caller appears, then
  centralise.
- **Not refactoring the two dialogs toward a common base class.** They are parallel by
  convention, which is standards 3.4, not duplication.
- **Not writing the API key to the settings file as a fallback** when the keyring fails.
  `CLAUDE.MD` states the key is never written there; a broken keyring does not change the
  policy, it makes the failure something the user has to hear about.
- Not trimming `.gitignore` beyond the dead-tool blocks named in Phase 3.
- Not sweeping files outside `a91c9e9..HEAD` for bugs; `improve` was scoped to the diff
  (report section 2).

## Implementation Approach

Phase 1 first and alone, because it both deletes and adds behaviour and wants the reviewer's
full attention. Phase 2 next, because G3 is data loss. Phase 3 is independent and can be
skipped or split without affecting either.

Within phases 1 and 2: write the new tests before touching the module, so each is seen
failing first. Phase 2's G3 test is the mirror of `test_failed_migration_keeps_the_plaintext_key`
(`tests/test_settings_store.py:265`), which is the shape to copy.

---

## Phase 1: One rule for user-authored regexes

Branch: `fix/regex-guards`.

### Changes Required

#### 1. Delete the ReDoS machinery

**File**: `whisper_dictate/app_prompts.py`

- Delete `:24-33` — the `# ReDoS protection limits` comment, `MAX_REGEX_LENGTH`,
  `MAX_REPETITION_DEPTH`, `REGEX_TIMEOUT_SECONDS`, and `class RegexValidationError`.
- Delete `:128-239` — `validate_regex_pattern` and `safe_regex_search` entire.
- Delete `import threading` (`:7`). `re` stays; it is used by the replacement below.

#### 2. Replace them with a matcher that is honest about what it does

**File**: `whisper_dictate/app_prompts.py`, where `safe_regex_search` was:

```python
def _title_matches(pattern: str, title: str) -> bool:
    """Match a saved window-title pattern against the active window's title.

    The pattern is checked when the rule is saved. A settings file edited by
    hand can still carry one that will not compile, and that must cost this
    rule, not the dictation.

    ponytail: no time limit on the match. Pattern and title are both the user's
    own, on their own machine, and a window title is short; the worst a
    pathological pattern costs is a fraction of a second of their own CPU.
    Add a limit only if a trace ever shows one that matters.
    """
    try:
        return re.search(pattern, title, re.IGNORECASE) is not None
    except re.error as e:
        logger.warning(f"Skipping invalid window-title regex {pattern!r}: {e}")
        return False
```

Then change the two call sites to use it, and drop the stale comment at the first:

- `:263` — `if safe_regex_search(regex, window_title):` → `if _title_matches(regex, window_title):`, and delete the line above it, `# Use safe regex matching with timeout protection`.
- `:296` — the same substitution.

#### 3. Reject a bad pattern when the app-prompt rule is saved

**File**: `whisper_dictate/app_prompt_dialog.py`, in `AppPromptEntryDialog._on_save`
(`:265`). After the existing prompt/style check and before building `self.result`:

```python
        window_regex = self.var_window_regex.get().strip()
        if window_regex:
            try:
                re.compile(window_regex)
            except re.error as e:
                messagebox.showerror("App prompt", f"Window title regex: {e}")
                return
```

and use the local in the result dict (`:281`) instead of re-reading the var:

```python
            "window_title_regex": window_regex,
```

#### 4. Reject a bad pattern when the glossary rule is saved

**File**: `whisper_dictate/glossary_dialog.py`, in `GlossaryRuleDialog._on_save` (`:281`).
Add `import re` to the stdlib block (`:5`), and after the phonetic check:

```python
        if self.var_match_type.get() == "regex":
            try:
                re.compile(trigger)
            except re.error as e:
                messagebox.showerror("Glossary", f"Not a valid regular expression: {e}")
                return
```

#### 5. A bad glossary rule costs its own rule, not the dictation

**File**: `whisper_dictate/glossary.py`, in `GlossaryManager.apply` (`:309-313`). The loop
body becomes:

```python
        for rule in self.rules:
            if rule.match_type == "phonetic":
                continue
            try:
                result = rule.compile_pattern().sub(rule.replacement, result)
            except re.error as e:
                # A hand-edited file can carry a pattern the dialog would have
                # refused, or a replacement with a group reference that has no
                # group. One rule is not worth the dictation.
                logger.warning(f"Skipping glossary rule {rule.trigger!r}: {e}")
```

`sub` is inside the `try` deliberately: an invalid backreference in `replacement` raises
from `sub`, not from `compile`.

#### 6. Tests

**File**: `tests/test_app_prompts.py`

- Delete `class TestRegexValidation` (`:315-356`), `class TestSafeRegexSearch` (`:358-394`)
  and `class TestResolveAppPromptWithSafeRegex` (`:396-436`) — every one tests a deleted
  function, and the last one asserts the wrong thing about `(a+)+`.
- Add, in their place, one class for the new behaviour:
  - a rule whose `window_title_regex` is `"(unclosed"` resolves to `None` rather than
    raising, and the warning is logged (`caplog`);
  - a rule whose regex is valid and matches still wins over the process-wide rule — assert
    the existing precedence did not change;
  - the same two for `resolve_app_style`.
- Add a test that a *legitimate* pattern the old validator would have rejected now works:
  `{"window_title_regex": r"(\w+ )?Report - Word"}` matches `"Quarterly Report - Word"`. The
  old validator refused it: a `+` inside a `?` group counts as nested repetition. This is the
  regression the deletion is for.

**File**: `tests/test_glossary.py`

- A `regex` rule with trigger `"(unclosed"` is skipped by `apply()`, the surrounding rules
  still apply, and the warning names the trigger.
- A rule whose `replacement` is `r"\9"` is skipped the same way.

**File**: `tests/test_app_prompt_dialog.py` / dialog tests — only if a dialog test module
already constructs `AppPromptEntryDialog`; both dialog modules sit at 12-13% coverage and
the existing suite does not drive them. If there is no harness, do not build one: the
save-time check is four lines of stdlib, and note in the PR that it is covered by hand
(manual step below). Do not lower the bar quietly — say which it was.

#### 7. Changelog

Under `[Unreleased]` → `### Fixed`:

> - A glossary rule with an invalid regular expression, or a replacement naming a group
>   that does not exist, failed the whole dictation: the audio was discarded and the status
>   read "Dictation failed; see the log". The bad rule is now skipped and named in the log,
>   and neither dialog will save a pattern that does not compile.

Under `### Changed`:

> - Per-app window-title patterns are no longer screened by a length limit and a nesting
>   heuristic that also refused legitimate patterns such as `(\w+ )?Report - Word`. They are
>   checked when the rule is saved instead.

### Success Criteria

#### Automated Verification:
- [x] `git grep -n "safe_regex_search\|validate_regex_pattern\|RegexValidationError\|MAX_REGEX_LENGTH\|MAX_REPETITION_DEPTH\|REGEX_TIMEOUT_SECONDS" -- whisper_dictate tests` returns nothing
- [x] `git grep -n "^import threading" whisper_dictate/app_prompts.py` returns nothing
- [x] `uv run ruff check .` exits 0
- [x] `uv run ruff format --check .` exits 0
- [x] `uv run mypy whisper_dictate` exits 0
- [x] `uv run pytest` exits 0, with no test count lower than 360 minus the 12 deleted tests plus the new ones
- [x] `uv run python -c "from whisper_dictate import app_prompts, app_context as c; print(app_prompts.resolve_app_prompt({'w.exe':[{'prompt':'P','window_title_regex':r'(\w+ )?Report - Word'}]}, c.ActiveContext(process_name='w.exe', window_title='Quarterly Report - Word')))"` prints `P`
- [x] CI green on the PR

#### Manual Verification:
- [x] Edit → Per-app prompts… → Add. Type `notepad.exe`, a prompt, and `(unclosed` as the window title regex. Save is refused with a message naming the problem; the dialog stays open
- [x] Change it to `(\w+ )?Report - Word` and save. The rule appears in the list
- [x] Edit → Glossary → Add a rule, match type `regex`, trigger `(unclosed`. Save is refused
- [x] Hand-edit `~/.whisper_dictate/whisper_dictate_glossary.json` to give a regex rule the trigger `(unclosed`, restart, dictate. The dictation completes normally; the log has one "Skipping glossary rule" line naming the trigger
- [x] Dictate into Notepad with a matching per-app rule and confirm the per-app prompt is still chosen (precedence unchanged)

---

## Phase 2: The key survives a keyring failure; the buffer is read before it can be cleared

Branch: `fix/key-and-buffer`. G3 and G4 in the report.

### Changes Required

#### 1. `save_settings` reports a key it could not store (G3)

**File**: `whisper_dictate/settings_store.py`

`_store_secure_settings` (`:101-118`) returns the settings keys it failed to store, and
logs them at ERROR, not WARNING — this is the user's key going away:

```python
def _store_secure_settings(settings: dict[str, Any]) -> list[str]:
    """Store secure settings in credential manager.

    Returns:
        The settings keys that could not be stored. Their values are not in
        the keyring and will not be in the file either; the caller has to say so.
    """
    failed: list[str] = []
    for key in SECURE_KEYS:
        # An absent key is a partial save, not a cleared field: leave it stored.
        value = settings.get(key)
        if not isinstance(value, str):
            continue
        credential_key = SECURE_KEYS[key]
        try:
            if value.strip():
                credentials.store_credential(credential_key, value)
            else:
                credentials.delete_credential(credential_key)
        except (credentials.CredentialStorageError, ValueError) as e:
            logger.error(f"Could not store {key} in the credential manager: {e}")
            failed.append(key)
    return failed
```

`save_settings` (`:52-77`) still writes the file — losing the other settings too would be
worse — but returns `False` when any key failed. The docstring and the first two lines of
the `try` become:

```python
    """Persist settings to disk. Returns True on success, False otherwise.

    Secure settings (API keys) are stored in the system credential manager and
    never written to the JSON file. If one cannot be stored, the file is still
    written without it and this returns False: the value is now nowhere.
    """
    try:
        failed = _store_secure_settings(settings)
        settings_to_save = {k: v for k, v in settings.items() if k not in SECURE_KEYS}
        ...
        os.replace(tmp, SETTINGS_FILE)
        return not failed
```

#### 2. The GUI tells the user, when it can (G3)

**File**: `whisper_dictate/gui.py`, `_save_settings` (`:1041-1042`). Replace the two lines
with:

```python
        if not settings_store.save_settings(settings):
            logger.warning("Settings were not fully saved")
            # From main()'s finally there is no window left to show this in.
            if self.winfo_exists():
                messagebox.showwarning(
                    "Settings",
                    "Some settings could not be saved; see the log.\n\n"
                    "If you entered an API key, keep a copy of it: it may not "
                    "survive a restart.",
                )
```

`messagebox` is already imported (`gui.py` uses it at `:1344`). The wording covers both
failure kinds — a file write error and a keyring error — without the GUI having to tell
them apart; the log has the specifics. `var_llm_key` keeps its value for the rest of the
session, so the user can open Settings and try again once Credential Manager is back.

#### 3. The buffer is read where the recorder was stopped (G4)

**File**: `whisper_dictate/gui.py`

In `_capture_dictation_config` (`:1366-1371`), read the buffer alongside the settings.
The docstring changes to say so:

```python
    def _capture_dictation_config(self) -> dict[str, Any]:
        """Copy every setting, and the audio, a dictation uses out of Tk. Main thread only.

        The buffer is read here and not on the worker: a key-down before the
        worker's first line would clear it (audio.py start()).
        """
        cfg = self._read_vars()
        cfg["initial_prompt"] = cfg["initial_prompt"] or None
        cfg["llm_key"] = cfg["llm_key"] or None
        cfg["audio"] = self.recorder.get_buffer()
        return cfg
```

In `_transcribe_and_clean` (`:1393`), `audio_data = self.recorder.get_buffer()` becomes
`audio_data = cfg["audio"]`.

`_stop_and_transcribe` (`:1357-1364`) is unchanged: it already calls `recorder.stop()`,
then `_capture_dictation_config()`, then spawns the worker, in that order, on the Tk
thread — which is exactly the order the fix needs.

#### 4. Tests

**File**: `tests/test_settings_store.py`, beside `test_failed_migration_keeps_the_plaintext_key`
(`:265-271`), using the same `creds` fixture:

- `creds.store_credential.side_effect = CredentialStorageError(...)`; `save_settings({"model": "base", "llm_key": "sk-plain"})` returns `False`, and the file on disk contains `model` and not `llm_key` — the key is not written as a fallback.
- The same with a *successful* store returns `True` (guards the return value change).
- `_store_secure_settings` returns `["llm_key"]` on failure and `[]` on success.

**File**: `tests/test_gui_pipeline.py`

- The harness (`:79-112`) already sets `app.recorder.get_buffer.return_value = AUDIO`,
  and every test that reaches `_transcribe_and_clean` gets its `cfg` from
  `_capture_dictation_config` — `run()` at `:118-120` and the no-Tk test at `:265-270`
  both do — so the existing pipeline tests cover the new read path with no change. The
  one exception, `:297`, passes `{}` to `_dictation_worker` and asserts the error state,
  which a `KeyError` on `cfg["audio"]` still satisfies.
- Add one test: `_capture_dictation_config()` returns a dict whose `"audio"` is what
  `recorder.get_buffer` returned, and `get_buffer` was called exactly once by then — so
  the read happened on the capturing thread, not later.
- Check `:370` (`app.recorder.get_buffer.assert_called_once()`) still holds; it should,
  the call moved but did not multiply.
- The tests that drive `_save_settings` (`:402`, `:433`, `:449`) mock `save_settings`
  with a default `MagicMock`, whose return is truthy, so the new dialog branch is not
  taken and they pass unchanged. Add one test with `save_settings.return_value = False`:
  `messagebox.showwarning` is called once. Check whether the harness's `mods` fixture
  already patches `gui.messagebox`; if not, patch it in the test, or it blocks on a real
  dialog.

#### 5. Changelog

Under `[Unreleased]` → `### Fixed`:

> - An API key that could not be stored in Windows Credential Manager was silently lost:
>   the settings file is never allowed to hold it, and nothing said the store had failed.
>   The save now reports it and, while a window is open, says to keep a copy.
> - Pressing the hotkey again in the instant after releasing it could clear the audio
>   before the transcriber read it. The buffer is now read on the same thread that
>   stopped the recorder, before anything can start it again.

### Success Criteria

#### Automated Verification:
- [x] `git grep -n "def _store_secure_settings" whisper_dictate/settings_store.py` shows a `-> list[str]` return
- [x] `git grep -n "recorder.get_buffer()" whisper_dictate/gui.py` shows two hits: the cancel path's discard (`_on_hotkey_cancel`) and `_capture_dictation_config`; none in `_transcribe_and_clean`
- [x] `uv run pytest tests/test_settings_store.py -q` exits 0 and the new G3 test is present and passing
- [x] `uv run pytest tests/test_gui_pipeline.py -q` exits 0
- [x] The four check commands exit 0; CI green on the PR

#### Manual Verification:
- [x] Break the keyring for one run: `uv run --no-sync python -c "import keyring; from keyring.backends import fail; keyring.set_keyring(fail.Keyring())"` proves the backend can be forced; the implementer sets `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring` in the environment and launches the app. Open Settings, enter any value in the API key field, close the window. A warning dialog appears naming the log and the key; the log has one ERROR line for `llm_key`; `whisper_dictate_settings.json` does not contain `llm_key`
- [x] Unset the variable, relaunch, enter the key again, close Settings. No dialog; `Get-Command cmdkey` → `cmdkey /list` shows the `whisper_dictate` entry
- [x] Dictate normally. The text still arrives; nothing about the buffer change is visible, which is the point

---

## Phase 3: Dead data and stranded lines

Branch: `chore/dead-data`. Independent of phases 1 and 2; nothing here changes behaviour.

### Changes Required

#### 1. ~~Drop the two `MODEL_INFO` fields nothing reads~~ Retracted

`speed` and `description` are read at `gui.py:434-439`, for the label under the model
dropdown. The intake grep missed it (report section 5, item 3). Both fields stay and go
into the `TypedDict` below; the label code loses its `.get(..., "")` fallbacks the same
way `get_model_display_name` does.

#### 2. Type `MODEL_INFO` so the runtime guard is unnecessary

**File**: `whisper_dictate/config.py`. Give it a `TypedDict` (stdlib, `typing`):

```python
class ModelInfo(TypedDict):
    display_name: str
    disk_mb: int
    vram_gb: int
    ram_gb: float
    speed: str
    description: str


MODEL_INFO: dict[str, ModelInfo] = {
```

Then `get_model_display_name` (`:202-225`) loses every fallback, because the type now says
the keys are there:

```python
def get_model_display_name(model_id: str, device: str) -> str:
    """Get formatted display name with resource requirements for model dropdown."""
    info = MODEL_INFO.get(model_id)
    if info is None:
        return model_id

    req = f"~{info['vram_gb']} GB VRAM" if device == "cuda" else f"~{info['ram_gb']} GB RAM"
    disk_mb = info["disk_mb"]
    disk_str = f"{disk_mb / 1000:.1f} GB" if disk_mb >= 1000 else f"{disk_mb} MB"
    return f"{info['display_name']} ({disk_str}, {req})"
```

The `isinstance` check, the `"? MB"` branch and the three `.get(..., '?')` defaults all go.
Check `tests/test_config.py` for a test asserting the unknown-model path still returns the
bare `model_id` — keep it passing.

#### 3. `clean` no longer has a spec to clean

**File**: `Makefile:3`. Drop `*.spec` from the `rm -rf` list; the PyInstaller spec went with
PR #73. Leave `build` and `dist` — hatchling still produces them.

#### 4. Drop the one-line public alias

**File**: `whisper_dictate/gui_components.py:183-185`. Delete `reset_position`.
**File**: `whisper_dictate/gui.py:765`. Call `self.indicator._reset_position()`.

If that private call reads wrong to the reviewer, keep the alias instead and say so — it is
three lines either way.

#### 5. Trim `.gitignore` to tools this repo could plausibly use

**File**: `.gitignore` (214 lines, the stock GitHub Python template). Remove the blocks for
tooling this project does not and will not use: Django, Flask, Scrapy, Celery, SageMath,
PyBuilder, PDM/PEP582, Pyre, pytype, Cython, `.ipynb_checkpoints`, and the JetBrains and
Spyder sections. Keep: Python bytecode, `build/`, `dist/`, `*.egg-info`, `.venv`,
`.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.coverage`, `htmlcov/`, the Environments
block (`:144-152`), `.vscode`.

While in there: widen `.env` (`:145`) to `.env*`. It currently ignores that exact filename
only, so a `.env.local` would be tracked. Rule 1.2 is N/A for this repo — the API key goes
to Credential Manager (`credentials.py`), not a dotenv file — so this is future-proofing,
not a fix. One character.

#### 6. Changelog

Nothing user-visible in this phase. No entry.

### Success Criteria

#### Automated Verification:
- [x] ~~`speed`/`description` grep returns nothing~~ retracted: both fields stay, `gui.py:434-439` reads them
- [x] `git grep -n "isinstance(disk_mb_value" whisper_dictate/config.py` returns nothing
- [x] `git grep -n "^\.env" .gitignore` shows `.env*` and `.envrc`
- [x] `git status --porcelain` is empty after the `.gitignore` edit — nothing newly untracked
- [x] The four check commands exit 0; CI green on the PR

#### Manual Verification:
- [x] Open Speech recognition settings. The model dropdown still reads e.g. `Small (465 MB, ~2 GB VRAM)` on CUDA and `~1 GB RAM` on CPU
- [x] Switch device between cpu and cuda and confirm the requirement text follows

---

## Testing Strategy

### Unit Tests
- Phase 1's new tests are written and seen failing before `app_prompts.py` is touched.
- The `(\w+ )?Report - Word` test is the one that would have caught the old validator's
  false positive. Keep it even though it looks trivial — it is the reason for the change.
- The glossary tests drive `GlossaryManager.apply()` directly with a hand-built rule list;
  no file I/O and no dialog needed.
- Phase 2's G3 test is written first and seen failing: today `save_settings` returns
  `True` on a failed store, and the assertion that it returns `False` is the whole test.
  The companion assertion — the file does not contain the key — passes today too and is
  there to stop a future "fix" that writes it to disk.

### Integration Tests
- None added. `tests/test_integration.py` and `tests/test_gui_pipeline.py` are untouched.

### Manual Testing
- Per Dan's standing preference, the implementer sets each manual test up — a glossary JSON
  with a deliberately broken rule, copied aside first — and hands over exact steps.
- The two dialogs are at 12-13% coverage and the suite does not drive them; the save-time
  rejections are verified by hand, and the PR says so plainly rather than implying the
  suite covers them.

## Performance Considerations

- One thread per window-title match disappears. Previously every dictation with a per-app
  rule that had a regex started, joined and abandoned a thread — twice, once in
  `resolve_app_prompt` and once in `resolve_app_style`.
- The accepted ceiling: a pathological pattern the user wrote themselves can now spend
  real time in `re.search` on the dictation worker thread (`gui.py:1404`, `:1540`), never
  the Tk thread — so the worst case is one slow or stuck dictation, one core, and a pill
  that says "Transcribing..." until the rule is edited. Measured for a plausible shape,
  `(a+)+$` against 24 characters, is 598 ms; a window title is short and the pattern is
  their own. Recorded as a `ponytail:` comment at the site.
- `glossary.apply()` gains one `try` around a loop body that already ran per rule.
- `get_buffer()` moves from the worker to the Tk thread, directly after `stop()`, which
  already blocks there for the queue drain. It is one `np.concatenate` over a few seconds
  of float32 — microseconds. Nothing the user can feel.

## Migration Notes

- No settings change and no file format change. A settings file containing a regex the old
  validator would have rejected now starts working — that is the intent, and the changelog
  says so.
- Anyone importing `app_prompts.safe_regex_search`, `validate_regex_pattern`,
  `RegexValidationError` or the three `MAX_*`/`*_TIMEOUT_SECONDS` constants from outside the
  package would break. `git grep` shows only the deleted tests do.
- `save_settings` now returns `False` in one more case: a secure key that could not be
  stored. Callers that treated `True` as "everything is on disk" were already wrong, since
  the key was never on disk; they now hear about it. `_store_secure_settings` gains a return
  value; it has one caller.
- `cfg` gains an `"audio"` key. `_transcribe_and_clean` is the only reader.

## References

- Intake report: `advisor-plans/intake-2026-09-22.md` — section 4 (G1 to G4), section 5
  (deletion items 1, 3 to 7; item 2 ruled out), section 7 (fix order, which is this plan's
  three phases).
- The migration-path fix this plan extends to the save path: commit `3906342`,
  `whisper_dictate/settings_store.py:80-97`, `tests/test_settings_store.py:265-271`.
- Previous plan, for ground rules and house style: `plans/2026-09-21-second-intake-fixes.md`
- Save-time rejection pattern to copy: `whisper_dictate/glossary.py:128` and
  `whisper_dictate/glossary_dialog.py:288-292`
- Last-resort worker handler, which is why a bad rule costs the dictation and not the pill:
  `whisper_dictate/gui.py:1378-1385`
- Standards: 3.1 (the ladder), 3.3 (`ponytail:` comments name their ceiling), 3.4
  (match the patterns already in the repo), 3.5 (fix where all callers route through), and
  the "never trimmed in the name of 3.x" clause — read here as not applying, because the
  pattern and the text it matches are both the user's own and cross no trust boundary.
