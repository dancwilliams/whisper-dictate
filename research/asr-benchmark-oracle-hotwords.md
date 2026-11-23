# Would per-dictation hotwords help? Oracle benchmark, 2026-11-22

The audit proposed biasing Whisper with words read off the screen. This measures
the best case first. `whisper-oracle-hotwords` gives each clip the domain terms its
reference really contains, plus ten terms it does not, standing in for on-screen
words nobody says. A real screen read can only do worse than this.

Gate (from `plans/2026-11-21-audit-follow-up.md`, Phase 7): on the Wispr clips,
WER at or below 9.0 and domain recall above 90.3, the September scores of plain
Whisper and of static hotwords.

## Wispr Flow export (decides)

198 clips, 41.0 minutes of speech (median 8.3s).

| candidate | WER % | domain recall % | p50 s | p90 s | cold s | VRAM GB | garbage |
|---|---|---|---|---|---|---|---|
| whisper | 8.7 | 86.7 | 0.35 | 0.83 | 2.5 | 2.32 | 2 |
| whisper-oracle-hotwords | 11.3 | 92.9 | 0.37 | 0.81 | 2.0 | 2.32 | 2 |

## Corrections bank, every clip (sanity check only)

67 clips, 13.9 minutes of speech (median 9.1s). Domain terms here are the
glossary's replacements.

| candidate | WER % | domain recall % | p50 s | p90 s | cold s | VRAM GB | garbage |
|---|---|---|---|---|---|---|---|
| whisper | 6.4 | 20.0 | 0.40 | 0.84 | 2.7 | 2.32 | 0 |
| whisper-oracle-hotwords | 10.7 | 95.0 | 0.37 | 0.75 | 2.5 | 2.32 | 1 |

Latency is about four times the September figure on both rows: the running app
shared the GPU. It does not bear on the question.

## The gate, as written: fail

11.3 WER is above 9.0. Recall clears 90.3 easily.

## Where the WER went

Nearly all of the loss is two clips where the hotwords sent Whisper into a
repetition loop. Both are clips `is_garbage` already flags:

| clip | length | reference words | plain words out | oracle words out | loop |
|---|---|---|---|---|---|
| Wispr `20260903T154735Z` | 3.3 s | 2 | 2 | 112 | "we, we, we, ..." |
| Wispr `20260908T185945Z` | 71.3 s | 100 | 101 | 241 | one sentence repeated |
| Corrections `20261024T210925` | 73.7 s | 112 | 113 | 194 | one phrase repeated |

Those three clips account for 340 of the oracle's errors. On the other clips the
oracle makes 116 fewer errors than plain Whisper on Wispr, and 6 fewer on the
corrections bank. Per clip it is worse on 14 and better on 22 (Wispr).

The app decodes at temperature 0.0 only, so faster-whisper's
`compression_ratio_threshold` has no fallback temperature to retry at, and a loop
goes straight through. A live feature would need a guard: when the output is
garbage, decode again without hotwords. At temperature 0 that rerun gives plain
Whisper's output for the clip, so the guard can be scored from the per-clip rows
without another run:

| candidate | Wispr WER % | Wispr recall % | garbage | corrections WER % | corrections recall % |
|---|---|---|---|---|---|
| whisper | 8.7 | 86.7 (98/113) | 2 | 6.4 | 20.0 (4/20) |
| whisper-oracle-hotwords | 11.3 | 92.9 (105/113) | 2 | 10.7 | 95.0 (19/20) |
| oracle + loop guard | **6.5** | **92.9** | 0 | 6.0 | 95.0 |

The guard fell back on 2 Wispr clips and 1 corrections clip. Plain Whisper's own
two garbage clips are different ones; the oracle did not loop on either.

## The same guard on the September static hotwords

The September decision turned hotwords off because they cost 1.2 WER points.
Re-scoring `research/asr-benchmark-2026.csv` with the same guard:

| candidate | WER % | domain recall % | guard fell back |
|---|---|---|---|
| whisper | 9.0 | 86.7 | |
| whisper-hotwords (400 chars, static) | 10.2 | 90.3 | |
| whisper-hotwords + loop guard | **7.3** | **90.3** | 2 clips |

So the static hotwords' WER cost was also two loops. With the guard, the static
list already beats plain Whisper on both counts, and it needs no screen read.

## Caveats

- The oracle knows which terms are about to be said. A whole-window read gives
  hundreds of words, not the right handful plus ten. The guarded 6.5 is a ceiling.
- Term matching is a substring test on normalized text, the one `term_recall`
  scores by, so a short term can be "present" inside a longer word. The oracle
  inherits that, and the score is exact against it.
- The guard was scored from the rows, not run. That holds if a temperature-0
  decode without hotwords repeats the plain run's output; that was not
  checked. A built guard should be benchmarked for real.
- The corrections bank's references are hand corrections, which skew toward
  clips where a term went wrong. That is why plain recall there is 20%. In the
  app the glossary repairs most of those terms after transcription.

## Decision

Dan, 2026-11-22: the screen-word feature is closed. The loop guard with the
static hotword list is worth its own small plan later.

The reasoning: do not build the screen-word feature. Write a small plan for the
loop guard with the static hotword list first. It is a few lines in
`transcription.py`, it would be measured with this same script, and the
September numbers say it gains 1.7 WER points and 3.6 recall points with no
screen read and no new privacy question. If the static list plus the guard falls
short in use, measure screen words against it then, with a realistic number of
distractors in place of ten.

## Reproducing

```powershell
uv run python scripts/bench_asr.py --candidates whisper,whisper-oracle-hotwords --out research/asr-benchmark-oracle-hotwords.md
uv run python scripts/bench_asr.py --corpus corrections --split all --candidates whisper,whisper-oracle-hotwords --out research/asr-benchmark-oracle-hotwords-corrections.md
```

The first command rewrites this whole file with its table; the analysis here is by hand,
so give it another `--out`. The per-clip CSVs hold dictation text and stay local.
