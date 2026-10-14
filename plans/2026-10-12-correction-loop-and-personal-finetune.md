# Correction loop and personal Whisper fine-tune — Implementation Plan

Written against `main` at `bc65521` on 2026-10-12. Line numbers are from that commit; if
one has moved, find the quoted code.

## Overview

Every dictation is already recorded with its audio, but the one thing that would make
that data trainable, Dan's own correction, is thrown away the moment the Fix last
dictation dialog closes. This plan keeps it: each correction becomes a gold label beside
a copy of its WAV that is never pruned, the benchmark learns to score against those
labels, and a script turns them into a LoRA fine-tune of large-v3-turbo that the app can
select from its model dropdown. Four phases, one PR each, and each leaves something Dan
can use on its own.

Decisions made with Dan before writing:

- **Only corrected clips are kept past the 14-day window.** The rest keep expiring. A
  correction copies its WAV into a training folder that `prune_audio` never touches.
- **The Fix dialog edits the raw Whisper text**, with the final pasted text shown
  read-only underneath. A correction of the raw text is a verbatim label for Whisper and
  is the side of the pipeline glossary rules are actually applied to (`gui.py:1534`).
  Today the dialog mines rules from the cleaned text, which is the wrong side.
- **Last dictation only.** No history picker.
- **Proposed glossary rules start unticked.** Dan has more mishearings than real
  vocabulary; a correction is banked on Save, and a rule is an extra, deliberate tick.
- **A correction changes misheard words only.** Whisper's punctuation, casing and filler
  stay, so the label is verbatim and S1 keeps the cleaning job. The dialog says so.
- **The dialog names both texts**: "Heard by Whisper" over the edit box, "Pasted after
  cleanup" on the gray line. Wrong words in the box are Whisper's; a wrong gray line
  with a right box is S1's.
- **A "Cleanup was wrong" tick** banks the raw and pasted pair with a flag. Nothing in
  this plan consumes it; it is S1 data for a later plan.
- **Training mixes in uncorrected clips.** Dan expects a few corrections a day (the Wispr
  export shows 17 real edits in 4,250 rows, so the dialog must do better than in-app
  editing did). Training only on clips Whisper got wrong would teach it that every clip
  is hard, so each run samples about two uncorrected clips per correction from the live
  14-day window, labelled with their raw text. No retention change.
- **Two evaluation sets.** A tuned model must beat base on the corrections hold-out and
  stay within one WER point of base on the 200-clip Wispr set, which is never trained on.
- **Tuned model folders expire after 30 days**, except the one selected in Settings.
  Relying on Dan to delete 1.6 GB folders by hand is not a mechanism.

## Ground rules for the implementer

- `uv` for everything: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy whisper_dictate`. `make` is not installed; run the four commands.
- CI syncs with `--no-group ml`. `peft` goes in the `ml` group and is imported lazily
  inside the script, never at module top level in `whisper_dictate/`.
- A running Whisper Dictate holds `.venv/Scripts/whisper-dictate.exe`. Ask Dan to quit the
  app (pill right-click, Quit) before the `uv sync` that adds `peft`. It runs as
  `pythonw`; stop it by command line, not by the whisper-dictate name.
- One branch and one PR per phase, targeting `main`. Do not start a phase until the
  previous PR is merged. Never pass `--auto` to `gh pr merge`; watch checks, then merge.
- No AI attribution in commits or PR text. Commits are GPG-signed; if signing fails, stop
  and ask Dan to unlock the key. Never `--no-gpg-sign`.
- Match the code around you. Comments explain why, not what. Keep to the ponytail ladder:
  stdlib first, shortest working diff.
- Never inject input (SendInput, pyautogui) on Dan's box to test the dialog. Real-Tk
  tests in `tests/test_glossary_dialog.py` drive the widgets directly.
- `CHANGELOG.md` gets an entry under `[Unreleased]` → `### Added` for each user-visible
  change (phases 1 and 4), in the register already there.

## Current State Analysis

Measured on 2026-10-12 with `uv run --no-sync`:

| Item | Value |
|---|---|
| `history.jsonl` rows | 1,164 (2026-09-20 to 2026-10-12), 24,098 raw words |
| WAVs on disk | 996, 333 MB (about 170 rows already lost their audio to pruning) |
| Model in use | `large-v3-turbo`, cuda, float16; S1 cleanup; glossary on |
| GPU | RTX 5090, 32 GB; torch 2.14.0+cu130 sees it (capability 12.0) |
| transformers / ctranslate2 | 5.17.0 / 4.8.2 (the converter ships with ctranslate2) |
| peft | not installed; 0.21.2 is current on PyPI |
| Benchmark baseline | `research/asr-benchmark-2026.md`: large-v3-turbo 9.0% WER, 86.7% domain recall on the Wispr export |
| Wispr export | `C:\Users\Dan Williams\wispr-flow-export`: 4,250 rows, 200 with audio (41 min), 17 with a real edit |
| Live window | 998 clips with audio, 174 min, about 10 s per clip; 480 rows where S1 changed the text |

### Key Discoveries

- **The record call discards the one thing a correction needs.** `history.record()`
  returns the entry dict with `audio_file` (`history.py:90-112`); `gui.py:1576` ignores
  the return value and keeps only `self._last_final = final_text` (`gui.py:1591`). No
  raw text, no WAV name, survives to the dialog.
- **The dialog returns rules, not text.** `CorrectionDialog.__init__(parent, heard)`
  (`glossary_dialog.py:321`) pre-fills `heard`; `_on_add` (`:388`) sets `result` to the
  ticked `GlossaryRule`s and destroys the window. The typed text lives only in
  `_on_find` (`:377`). Cancel and the window close both set `result = None`.
- **The dialog is opened with the cleaned text.** `_open_correction_dialog`
  (`gui.py:1115-1129`) passes `self._last_final`. Rules are applied to the raw text at
  `gui.py:1534` and again to the final at `:1573`, so a trigger mined from S1's
  rewording may never match the raw transcript.
- **`propose_rules(heard, typed)`** (`glossary.py:458-476`) diffs on whitespace-split
  words with edge punctuation stripped and emits only `replace` opcodes.
- **Audio retention.** `record()` saves a WAV only when `audio_days > 0`
  (`history.py:94`); `prune_audio` deletes `*.wav` in `AUDIO_DIR` by mtime
  (`history.py:115-137`) and is called once at startup from `_auto_startup`
  (`gui.py:940-943`). It only globs `AUDIO_DIR`, so a sibling folder is safe from it.
- **The model combobox rejects anything outside `MODEL_INFO`.** `update_model_display`
  (`gui.py:415-436`) resets `var_model` to `tiny.en` when the saved id is not a key of
  `get_model_choices(device)`, and that runs on init (`gui.py:460`) and on every device
  change. `on_model_change` (`:438-449`) maps display text back to an id by scanning the
  same list. `get_model_display_name` already returns an unknown id unchanged
  (`config.py:213-215`). Nothing else in the package looks an id up in `MODEL_INFO`.
- **Below the GUI a path already works.** `load_model` passes `model_name` straight to
  `WhisperModel` (`transcription.py:91`); faster-whisper accepts a CTranslate2 folder.
  `WhisperBackend` keys its parked-model cache on `(model_name, device, compute_type)`
  (`asr.py:43-52`), so a path is just another key. `_capture_asr_config`
  (`gui.py:1187-1194`) and `_build_backend` (`:1207-1221`) take the string as is.
- **The benchmark is hard-wired to the Wispr export.** `EXPORT` (`bench_asr.py:34`),
  `load_clips` (`:85-111`) reads `history.jsonl` + `audio/` and takes its reference from
  `reference_for(row)` (`:66-82`, `editedText` vs `formattedText`). `WhisperCandidate`
  (`:230-251`) takes a `model_name` but `build()` (`:303-311`) only ever constructs the
  default. Scoring (`word_error_rate`, `term_recall`, `is_garbage`) is reusable as is.
- **Test harnesses.** `tests/test_gui_pipeline.py` builds the app with `App.__new__`
  and MagicMock vars (`:21-58`, `:83-118`); `history` is a MagicMock there, and the only
  record assertion is `assert_called_once()` (`:305-317`). Any attribute set in
  `App.__init__` must also be set in `make_app`. `tests/test_history.py` uses `tmp_path`
  with explicit `path=` / `audio_dir=`. `tests/test_glossary_dialog.py` has a real-Tk
  `root` fixture and drives `_on_find` / `_on_add` directly (`:74-100`).
- **Scripts share a directory, not a package.** `python scripts/x.py` puts `scripts/` on
  `sys.path`, so `bench_asr.py` can `import finetune_whisper` for the hold-out rule.
  Ruff runs over `.` and covers `scripts/`; mypy runs over `whisper_dictate` only.

## Desired End State

- Fixing a dictation writes one line to `~/.whisper_dictate/corrections.jsonl` and copies
  the clip into `~/.whisper_dictate/training/`, whether or not any glossary rule is added.
  A "Cleanup was wrong" tick writes the same line with `cleanup_wrong: true`.
- `uv run python scripts/bench_asr.py --corpus corrections` scores any model, including
  a local folder, against Dan's own corrections on a fixed hold-out split.
- `uv run python scripts/finetune_whisper.py` trains a LoRA on the non-hold-out
  corrections plus a sample of uncorrected live clips, merges it, converts to CTranslate2
  under `~/.whisper_dictate/models/`, and prints base-vs-tuned WER on the hold-out and
  on the Wispr set.
- The Speech recognition window lists every folder under `~/.whisper_dictate/models/` as
  a model choice, and the choice survives a restart and a device change. Folders older
  than 30 days are removed at startup, except the selected one.

Verification: the automated criteria in each phase, plus Dan running one real correction
and one real training run.

## What We're NOT Doing

- Tuning S1 or any cleanup model. The cleanup-wrong flag is recorded, not consumed.
- Keeping every recording. Uncorrected clips keep expiring at the configured days; the
  training mix reads whatever is in the window on the day it runs.
- A browser for older dictations. Fix last dictation stays last-only.
- Automatic retraining, scheduling, or anything that runs training from inside the app.
- Positive labels ("this one was right"). Only edited text is saved.
- Any upload. Everything stays under `~/.whisper_dictate/`.
- Changing the glossary rule mining (`propose_rules`) itself.

## Implementation Approach

Phase 1 is the data capture and ships on its own; from then on every correction is
banked. Phase 2 makes the existing benchmark read that bank, so the fine-tune in phase 3
has a before-and-after number from day one. Phase 4 is the small GUI change that lets
Dan actually select the result. Phases 2 to 4 can wait weeks for corrections to pile up;
phase 1 should not.

---

## Phase 1: Bank every correction

### Overview

Keep the raw text and WAV name from the last dictation, show the raw text in the dialog,
and save what Dan typed together with a copy of the clip.

### Changes Required

#### 1. `whisper_dictate/history.py`: a correction record

Add beside `AUDIO_DIR`:

```python
CORRECTIONS_FILE = HISTORY_DIR / "corrections.jsonl"
TRAINING_DIR = HISTORY_DIR / "training"
```

Add after `record()`:

```python
def record_correction(
    entry: dict[str, Any],
    corrected: str,
    cleanup_wrong: bool = False,
    path: Path | None = None,
    audio_dir: Path | None = None,
    training_dir: Path | None = None,
) -> bool:
    """Bank a hand correction as a training label.

    The clip is copied into the training folder, which prune_audio never
    touches: a corrected recording is the one kind worth keeping for good.
    Raises nothing, like record().
    """
    path = path or CORRECTIONS_FILE
    audio_dir = audio_dir or AUDIO_DIR
    training_dir = training_dir or TRAINING_DIR
    name = entry.get("audio_file")
    if name:
        try:
            training_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(audio_dir / name, training_dir / name)
        except OSError as e:
            logger.warning(f"Could not keep the corrected recording: {e}")
            name = None
    return append(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "app": entry.get("app", ""),
            "audio_file": name,
            "raw": entry.get("raw", ""),
            "final": entry.get("final", ""),
            "corrected": corrected,
            # S1 changed the meaning while Whisper was right. Not consumed by
            # anything yet; it is the seed of a cleanup dataset.
            "cleanup_wrong": cleanup_wrong,
        },
        path,
    )
```

`import shutil` joins the stdlib imports. Update the module docstring: one line saying
corrections and their clips live in `corrections.jsonl` and `training/` and are never
pruned.

#### 2. `whisper_dictate/glossary_dialog.py`: edit the raw text, return it

`CorrectionDialog` changes:

- Signature becomes `__init__(self, parent, heard: str, final: str = "")`. The top
  label reads "Fix only the misheard words. Leave punctuation and filler as Whisper
  wrote them; the fix is kept as training data." Above the Text box a `ttk.Label`
  "Heard by Whisper". The Text box is pre-filled with `heard` as now. When `final` is
  non-empty and differs from `heard`, add below the Text box a `ttk.Label` with
  `text=f"Pasted after cleanup: {final}"`, `wraplength="390p"`, `justify="left"`,
  `foreground="gray"`, and under it a `ttk.Checkbutton` "Cleanup was wrong" bound to
  `self.cleanup_wrong = BooleanVar(value=False)` (shift the rows below).
- `self.result: tuple[str, list[GlossaryRule], bool] | None = None`: the typed text
  stripped, the ticked rules, and the cleanup-wrong flag.
- The right-hand button is renamed "Save" and is enabled whenever the typed text differs
  from `heard` or the cleanup tick is set, not only after Find. Bind `<<Modified>>` on
  the Text widget and the Checkbutton's `command` to one `_on_edit` that computes
  `self.text.get("1.0", "end").strip() != self.heard or self.cleanup_wrong.get()`, sets
  the button state, and resets `edit_modified(False)`. Keep `_on_find` as it is apart
  from no longer touching the button state and creating each `BooleanVar(value=False)`:
  a proposed rule starts unticked, because most fixes are mishearings and a rule made
  from one of those does more harm than the mishearing did. Adding a rule is a
  deliberate tick.
- `_on_add` becomes `_on_save`: `self.result = (typed, [rule for var, rule in
  self._choices if var.get()], self.cleanup_wrong.get())`.

The class docstring becomes "Fix the last dictation by hand. The fix is banked as a
training label, and the changed words can also become glossary rules."

#### 3. `whisper_dictate/gui.py`: keep the entry, save the correction

- `gui.py:184`: replace `self._last_final = ""` with `self._last_entry: dict | None = None`.
- `gui.py:1575-1591`: assign the return value when history is on, and build a minimal
  entry when it is off so the dialog still works:

```python
        entry = None
        if cfg["history_enable"]:
            entry = history.record(...)            # existing call, unchanged kwargs
        self._last_entry = entry or {"raw": text, "final": final_text, "audio_file": None}
```

  Remove `self._last_final = final_text`.
- `_open_correction_dialog` (`gui.py:1115-1129`):

```python
    def _open_correction_dialog(self) -> None:
        """Correct the last dictation by hand. The fix is banked as a training
        label; any changed words can also become glossary rules."""
        entry = self._last_entry
        if not entry:
            self._set_status("ready", "Nothing dictated yet")
            return
        dialog = CorrectionDialog(self, entry["raw"], entry["final"])
        self.wait_window(dialog)
        if dialog.result is None:
            return
        corrected, rules, cleanup_wrong = dialog.result
        history.record_correction(entry, corrected, cleanup_wrong)
        for rule in rules:
            self.glossary_manager.upsert_rule(rule)
        if rules and not self.glossary_manager.save():
            messagebox.showerror("Glossary", f"Could not save glossary to {glossary.GLOSSARY_FILE}")
            return
        self._set_status("ready", f"Correction saved, {len(rules)} glossary rule(s) added")
```

  `record_correction` is called before the glossary save so a glossary failure never
  loses the label.

#### 4. Tests

- `tests/test_history.py`, new class `TestRecordCorrection`, `tmp_path` throughout:
  - writes one valid JSONL line with `raw`, `final`, `corrected`, `cleanup_wrong`,
    `audio_file`, `app` and no other keys from the entry (no window title can leak: pass
    an entry with an extra `title` key and assert it is absent); `cleanup_wrong` is
    False by default and True when passed;
  - copies the WAV into `training_dir` and leaves the original in `audio_dir`;
  - a missing WAV (entry names a file that was pruned) still writes the line with
    `audio_file: null` and does not raise;
  - `prune_audio(1, audio_dir)` after a correction deletes the original and leaves the
    training copy (reuse `_aged` from `TestPruneAudio`).
- `tests/test_glossary_dialog.py`, `TestCorrectionDialog`:
  - update `test_find_then_add_returns_ticked_rules` to call `_on_save` and assert
    `dialog.result == ("meet me at ValidaTek, near GitHub", [...])`, ticking the one rule
    it expects first;
  - `test_proposed_rules_start_unticked`: after `_on_find`, every `var.get()` is False and
    `_on_save` returns an empty rule list;
  - `test_save_enabled_by_an_edit_without_find`: insert text, call `_on_edit()`, assert
    the button is `normal` and `_on_save` returns the text with an empty rule list;
  - `test_unchanged_text_keeps_save_disabled` replaces `test_no_changes_disables_add`;
  - `test_shows_final_when_it_differs`: `CorrectionDialog(root, "raw", "Final.")` has a
    label whose text starts with "Pasted after cleanup:" and a Checkbutton;
    `CorrectionDialog(root, "same", "same")` has neither. Check with
    `[w for w in dialog.winfo_children() if isinstance(w, ttk.Label)]`.
  - `test_cleanup_tick_alone_enables_save`: with the text untouched, set
    `dialog.cleanup_wrong` True, call `_on_edit()`, assert Save is `normal` and
    `_on_save` returns `(heard, [], True)`.
- `tests/test_gui_pipeline.py`: in `make_app` add `app._last_entry = None`. New test
  `test_last_entry_holds_raw_and_audio_file`: with `var_history_enable=True` and
  `mods.history.record.return_value = {"raw": "r", "final": "f", "audio_file": "x.wav"}`,
  after `run(app)` assert `app._last_entry["audio_file"] == "x.wav"`. With history off,
  assert `app._last_entry == {"raw": <raw>, "final": <final>, "audio_file": None}`.

#### 5. Docs

- `README.md:123-124`: the dialog shows what Whisper heard above what was pasted;
  fix only the misheard words and press Save. The correction is kept in
  `~/.whisper_dictate/corrections.jsonl` with a copy of the recording in `training/`,
  Find corrections still offers glossary rules (unticked by default), and "Cleanup was
  wrong" records a case where the cleanup step, not Whisper, changed the meaning.
- `CLAUDE.MD` File Paths: add the two new paths. Module table row for `history.py`: add
  `record_correction()`.
- `docs/architecture.md:47`: `history.jsonl + audio/ + corrections.jsonl + training/`.
- `CHANGELOG.md` → `### Added`: "Fixing a dictation now keeps the correction and its
  recording as training data under `~/.whisper_dictate`."

### Success Criteria

#### Automated Verification
- [x] `uv run pytest` passes with the new tests
- [x] `uv run ruff check .` and `uv run ruff format --check .` exit 0
- [x] `uv run mypy whisper_dictate` exits 0
- [x] CI green on the PR

#### Manual Verification
- [x] Dictate once, open Fix last dictation from the pill: the box is headed "Heard by
      Whisper" and a gray "Pasted after cleanup:" line shows the cleaned text
- [x] Tick "Cleanup was wrong" without editing and press Save: a line with
      `cleanup_wrong: true` lands in `corrections.jsonl`
- [x] Change one word and press Save without Find: a line lands in `corrections.jsonl`
      and the WAV appears in `training/`, status reads "Correction saved, 0 glossary rule(s) added"
- [x] Find corrections shows every swap unticked; ticking one and pressing Save adds just that rule
- [x] With "Keep a local record" off, the dialog still opens and saves a text-only line

**Implementation Note**: pause here for Dan's manual check before phase 2. Phases 2 to
4 need a stock of corrections to be meaningful; a couple of weeks of use is fine.

---

## Phase 2: Benchmark against your own corrections

### Overview

Teach `scripts/bench_asr.py` to read the corrections bank and to score any Whisper model
by name or folder, on a fixed hold-out split shared with the training script.

### Changes Required

#### 1. `scripts/finetune_whisper.py` (hold-out rule only, in this phase)

Create the file with the docstring, the paths and one function; phase 3 fills in the rest:

```python
HOME = Path.home() / ".whisper_dictate"
CORRECTIONS = HOME / "corrections.jsonl"
TRAINING = HOME / "training"
MODELS = HOME / "models"


def is_holdout(name: str) -> bool:
    """One clip in five is never trained on. Keyed on the file name so both
    scripts agree and the split does not move as the bank grows."""
    return zlib.crc32(name.encode()) % 5 == 0
```

#### 2. `scripts/bench_asr.py`

- Argument `--corpus {wispr,corrections}` default `wispr`; `--split {holdout,all}`
  default `holdout`; `--model` repeatable, default `["large-v3-turbo"]`, each a size name
  or a folder. Keep `--candidates` for the Wispr corpus; for `corrections` the candidates
  are one `whisper` run per `--model`.
- `load_clips` grows a branch for the corrections corpus: rows come from `CORRECTIONS`,
  audio from `TRAINING`, reference is `row["corrected"]`, and with `--split holdout` only
  `is_holdout(name)` rows are kept. Import `from finetune_whisper import CORRECTIONS,
  TRAINING, is_holdout` (same directory).
- `load_terms` for the corrections corpus: the glossary rules' replacements, read
  from `~/.whisper_dictate/whisper_dictate_glossary.json` through
  `glossary.GlossaryManager` so domain recall is scored on Dan's real vocabulary.
- `build(name, hotwords, model=...)`: `WhisperCandidate(model_name=model)`; the result
  name in the table is the model's `Path(model).name`.
- `table()` header says which corpus and split it ran on. The results file is written to
  `research/asr-benchmark-<corpus>-<date>.md` so Wispr runs are not overwritten.

#### 3. Tests

None beyond ruff: the scripts are not under test today and `bench_asr.py` has no test.
`is_holdout` gets a `selftest()` in `finetune_whisper.py` following the pattern in
`mine_wispr_history.py`: assert the function is deterministic and that over 1,000 names
the hold-out share is between 15% and 25%. Run with `--selftest`.

### Success Criteria

#### Automated Verification
- [x] `uv run python scripts/finetune_whisper.py --selftest` prints ok
- [x] `uv run ruff check .` exits 0
- [ ] `uv run python scripts/bench_asr.py --corpus corrections --limit 5` runs on the
      stock model and writes a results file

#### Manual Verification
- [ ] The hold-out clip count is roughly a fifth of the corrections bank
- [ ] The Wispr corpus still runs unchanged: `uv run python scripts/bench_asr.py --limit 20`

---

## Phase 3: Fine-tune and convert

### Overview

A LoRA fine-tune of large-v3-turbo on the non-hold-out corrections, merged and converted
to a CTranslate2 folder the app can load, with a base-vs-tuned benchmark at the end.

### Changes Required

#### 1. `pyproject.toml`

Add `"peft>=0.21.2"` to the `ml` group. Ask Dan to quit the app, then `uv sync`. Commit
`uv.lock`. First thing after the sync, check the pair actually imports together before
writing any training code:

```
uv run python -c "import peft, transformers; from transformers import WhisperForConditionalGeneration; print(peft.__version__)"
```

If peft 0.21 and transformers 5.17 disagree, pin whichever older peft the error names and
record it in the PR.

#### 2. `scripts/finetune_whisper.py`

A plain torch loop, no `Trainer`: with a few hundred clips it is forty lines, and it does
not move when transformers changes its training API. All ML imports are inside `main()`
so `--selftest` and the phase 2 import from `bench_asr.py` need no torch.

```
uv run python scripts/finetune_whisper.py [--base large-v3-turbo] [--epochs 3] [--lr 1e-4]
                                           [--rank 16] [--name personal-<date>] [--min-clips 100]
                                           [--mix-ratio 2]
```

Steps:

1. Load `CORRECTIONS`, drop rows with `cleanup_wrong` and no text change (the raw text
   was right, there is nothing to learn), keep rows whose WAV exists in `TRAINING` and
   `not is_holdout`. Below `--min-clips`, print how many there are and exit 1: a tune on
   thirty clips mostly measures noise.
   Then the mix: read `~/.whisper_dictate/history.jsonl`, keep rows whose WAV still
   exists in `audio/` and whose `audio_file` is not in the corrections file, and take a
   `random.Random(0).sample` of `--mix-ratio` (default 2) times the correction count,
   labelled with `raw`. These are clips Dan accepted as heard; they anchor the model to
   what it already gets right. `ponytail:` a raw label can itself be wrong, so this is a
   regulariser, not a signal; weight it down or drop it if the hold-out says so.
2. `WhisperProcessor.from_pretrained("openai/whisper-large-v3-turbo")`;
   `WhisperForConditionalGeneration.from_pretrained(..., dtype=torch.bfloat16).cuda()`.
   `processor.tokenizer.set_prefix_tokens(language="en", task="transcribe")`.
3. `peft.LoraConfig(r=rank, lora_alpha=2*rank, lora_dropout=0.05,
   target_modules=["q_proj", "v_proj"])`, `get_peft_model`. Print trainable parameter
   count.
4. Dataset: each clip → `processor.feature_extractor(audio, sampling_rate=16000)` log-mel
   (30 s window, clips longer than 30 s are skipped with a count printed) and
   `processor.tokenizer(corrected).input_ids` as labels. Batch 8, pad labels with -100.
   Shuffle each epoch. The whole bank fits in RAM; no streaming.
5. AdamW on the LoRA params, linear warm-up over the first 10% of steps, bf16 autocast,
   `model(input_features=..., labels=...)`.loss, gradient clip 1.0. Print loss every 20
   steps and the hold-out WER (greedy decode through the peft model) at each epoch end so
   overfitting is visible.
6. `model.merge_and_unload().save_pretrained(MODELS / f"{name}-hf")`;
   `processor.save_pretrained` to the same folder.
7. `subprocess.run([sys.executable, "-m", "ctranslate2.converters.transformers",
   "--model", hf_dir, "--output_dir", MODELS / name, "--copy_files", "tokenizer.json",
   "preprocessor_config.json", "--quantization", "float16", "--force"], check=True)`.
   Delete the `-hf` folder afterwards unless `--keep-hf`.
8. Run `bench_asr.run_candidate` for the base name and for `MODELS / name` on two sets
   and print both tables: the corrections hold-out (did it learn the hard cases) and the
   Wispr corpus (did it regress on ordinary speech). (Import `bench_asr` lazily here; it
   is a sibling script.) The gate, printed under the tables: tuned WER below base on the
   hold-out and no more than 1.0 point above base on Wispr. The Wispr clips are never in
   the training set.

`ponytail:` comments on the fixed 30 s window and the one-split hold-out, naming the
upgrade (chunking long clips; k-fold) if the bank ever makes them matter.

#### 3. Docs

- `README.md`: a short "Tuning Whisper to your voice" section after the glossary one:
  what gets banked, the command, where the model lands, and that it appears in the
  dropdown (phase 4).
- `docs/transcription-optimization.md`: one paragraph pointing at the section.
- `CLAUDE.MD` Dependencies: `peft` in the `ml` group, with the quit-the-app note.

### Success Criteria

#### Automated Verification
- [ ] `uv run ruff check .` exits 0
- [ ] `uv run python scripts/finetune_whisper.py --selftest` still prints ok with torch
      not imported (assert `"torch" not in sys.modules` inside selftest)
- [ ] `uv run python scripts/finetune_whisper.py --min-clips 1 --epochs 1 --name smoke`
      finishes, produces `~/.whisper_dictate/models/smoke/model.bin`, and
      `WhisperModel(str(path), device="cuda", compute_type="float16")` transcribes one
      training clip

#### Manual Verification
- [ ] A real run on the bank prints hold-out and Wispr tables with base and tuned rows
- [ ] The gate passes: tuned WER below base on the hold-out and within 1.0 point on
      Wispr. If it does not, the plan's answer is "more corrections", not more epochs;
      record the numbers in `research/asr-benchmark-corrections-<date>.md` either way
- [ ] Peak VRAM during training stays well under the 32 GB (expect under 12 GB)

---

## Phase 4: Pick the tuned model in the app

### Overview

List every folder under `~/.whisper_dictate/models/` in the model dropdown, and expire
the ones nobody selected. The rest of the pipeline already accepts a path.

### Changes Required

#### 1. `whisper_dictate/config.py`

```python
MODELS_DIR = Path.home() / ".whisper_dictate" / "models"


def get_model_choices(device: str, models_dir: Path | None = None) -> list[tuple[str, str]]:
    """Get list of (model_id, display_name) tuples for dropdown.

    Built-in sizes first, then every tuned model folder, keyed by its path so
    faster-whisper loads it directly."""
    choices = [(model_id, get_model_display_name(model_id, device)) for model_id in MODEL_INFO]
    models_dir = models_dir or MODELS_DIR
    if models_dir.is_dir():
        for folder in sorted(models_dir.iterdir()):
            if (folder / "model.bin").is_file():
                choices.append((str(folder), f"Tuned: {folder.name}"))
    return choices
```

#### 2. `whisper_dictate/history.py`: expire old tuned models

Beside `prune_audio`, the same shape:

```python
MODEL_DAYS = 30


def prune_models(keep: str, days: int = MODEL_DAYS, models_dir: Path | None = None) -> int:
    """Delete tuned model folders older than `days`, never the one in use.

    Each run leaves 1.6 GB behind and a person does not remember to clear them.
    `keep` is the model setting as saved, so a built-in name matches nothing.
    """
    models_dir = models_dir or config.MODELS_DIR
    if days <= 0 or not models_dir.is_dir():
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for folder in models_dir.iterdir():
        weights = folder / "model.bin"
        if not weights.is_file() or str(folder) == keep:
            continue
        if weights.stat().st_mtime < cutoff:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    if removed:
        logger.info(f"Removed {removed} tuned model(s) older than {days} days")
    return removed
```

`config.MODELS_DIR` is imported from `config`; `history.py` imports nothing from the
package today, so there is no cycle.

#### 3. `whisper_dictate/gui.py`

- `_auto_startup` (`gui.py:940-943`): beside the `prune_audio` thread, call
  `history.prune_models(self.var_model.get())` on the same daemon thread. It runs whether
  or not history is enabled.
- No change to `update_model_display` or `on_model_change`: a path that is in the
  choices list survives both, and `MODEL_INFO.get(path)` is `None` so the description
  label goes blank. Check that `width=45` on the combobox (`gui.py:393-396`) still fits
  "Tuned: personal-2026-10-26"; widen to 50 if not.

#### 4. Tests

- `tests/test_config.py`: `get_model_choices("cuda", models_dir=tmp_path)` with one
  folder holding `model.bin` and one empty folder returns the six built-ins plus exactly
  one `(str(folder), "Tuned: <name>")`; a missing dir returns the built-ins only.
- `tests/test_history.py`, `TestPruneModels` using `_aged`: an old folder is removed, a
  fresh one stays, the old folder whose path equals `keep` stays, a folder without
  `model.bin` is ignored, a missing dir returns 0.

#### 5. Docs

- `README.md` tuning section: the model shows up as "Tuned: <name>" in Settings → Speech
  recognition, and tuned models not selected are removed after 30 days.
- `CHANGELOG.md` → `### Added`: "Fine-tuned Whisper models under
  `~/.whisper_dictate/models` appear in the model list; unused ones expire after 30 days."

### Success Criteria

#### Automated Verification
- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
      `uv run mypy whisper_dictate` all exit 0

#### Manual Verification
- [ ] "Tuned: <name>" appears in the dropdown, selecting it loads without a warning, and
      a dictation goes through
- [ ] Flip device to CPU and back: the selection is kept
- [ ] Restart the app: the tuned model is still selected and the pill reports it loading
- [ ] Back-date a second tuned folder's `model.bin` by 31 days, restart: it is gone, the
      selected one is not

---

## Testing Strategy

### Unit Tests
- `record_correction`: JSONL shape, privacy (no title), WAV copy, missing WAV, prune
  leaves the copy alone, cleanup-wrong flag.
- `CorrectionDialog`: result tuple, Save enabled by an edit or the tick, rules start
  unticked, both labels present.
- `get_model_choices`: folder discovery. `prune_models`: age, keep, ignore.

### Integration Tests
- `test_gui_pipeline.py`: `_last_entry` is populated on the worker with and without
  history.

### Manual Testing Steps
1. Dictate, fix one word, Save. Check `corrections.jsonl` and `training/`.
2. Wait for the bank to pass `--min-clips`, run the fine-tune, read the hold-out table.
3. Select the tuned model, dictate, compare.

## Performance Considerations

- `record_correction` copies one WAV (a few hundred KB) on the Tk thread when the dialog
  closes. Not worth a thread.
- Training: large-v3-turbo in bf16 is about 1.6 GB of weights; LoRA rank 16 on q/v
  projections adds a few MB. Batch 8 of 30 s features is comfortably inside 32 GB.
- The converted model is the same size as the stock turbo (about 1.6 GB); first load
  costs the same cold time the benchmark already measures.

## Migration Notes

- Existing `history.jsonl` rows are untouched. Only corrections made after phase 1 are
  banked; there is no way to recover corrections made before it.
- Nothing changes in `whisper_dictate_settings.json` until phase 4, where `model` may
  hold a path. Older builds would reset it to `tiny.en`, which is the behaviour today.

## References

- Record call: `whisper_dictate/gui.py:1575-1591`
- Dialog: `whisper_dictate/glossary_dialog.py:318-394`, mining `whisper_dictate/glossary.py:458-476`
- Model choices and reset: `whisper_dictate/config.py:223-225`, `whisper_dictate/gui.py:415-449`
- Path into faster-whisper: `whisper_dictate/transcription.py:91`, `whisper_dictate/asr.py:43-52`
- Benchmark: `scripts/bench_asr.py`, results `research/asr-benchmark-2026.md`
- Script style to copy: `scripts/mine_wispr_history.py` (`selftest`, stdlib-only CLI)
- House rules: `plans/2026-09-21-second-intake-fixes.md` ground rules section
