# Parakeet through ONNX, 2026-11-22

Parakeet was ruled out in December 2025 because NeMo would not build on Windows
(`parakeet-windows-compatibility.md`). `onnx-asr` 0.12.0 now runs it from wheels, so this
measures it against Whisper large-v3-turbo on the same clips.

Gate (from `plans/2026-11-21-audit-follow-up.md`, Phase 8): on the Wispr clips, WER below
8.0, or within 1.0 of Whisper's 9.0 with domain recall above 86.7. A pass with a clearly
worse score on the corrections clips does not stand without Dan looking at both tables.

## Wispr Flow export (decides)

198 clips, 41.0 minutes of speech (median 8.3s).

| candidate | WER % | domain recall % | p50 s | p90 s | cold s | VRAM GB | garbage |
|---|---|---|---|---|---|---|---|
| whisper (Phase 7 run, same day) | 8.7 | 86.7 | 0.35 | 0.83 | 2.5 | 2.32 | 2 |
| parakeet-v2 | 8.6 | 87.6 | 0.08 | 0.16 | 1.3 | see below | 0 |
| parakeet-v3 | 10.3 | 86.7 | 0.08 | 0.14 | 1.0 | see below | 1 |

## Corrections bank, every clip (sanity check only)

67 clips, 13.9 minutes of speech (median 9.1s).

| candidate | WER % | domain recall % | p50 s | p90 s | cold s | VRAM GB | garbage |
|---|---|---|---|---|---|---|---|
| whisper (Phase 7 run, same day) | 6.4 | 20.0 | 0.40 | 0.84 | 2.7 | 2.32 | 0 |
| parakeet-v2 | 9.6 | 20.0 | 0.09 | 0.15 | 1.4 | see below | 0 |
| parakeet-v3 | 11.3 | 30.0 | 0.08 | 0.14 | 1.0 | see below | 0 |

The Whisper rows are from `asr-benchmark-oracle-hotwords.md`, run earlier the same day on
the same clips and model. Whisper and Parakeet could not run in one process: with
`onnxruntime-gpu` installed over the project's CPU `onnxruntime`, CTranslate2 stalled on
its first encode. Whisper's latency there is inflated by the running app sharing the GPU.

## The gate, as written: v2 passes on Wispr, and the corrections bank says otherwise

v2 is 0.1 points under Whisper with recall 87.6 against 86.7, so it clears "within 1.0
with better recall". The recall gain is one term (99 of 113 against 98). v3 fails.

On the corrections bank v2 is 3.2 points worse, which is "clearly worse", so the pass
needs Dan's look.

## Where the difference is

Clip by clip on the Wispr export, against plain Whisper:

| | total errors | better on | worse on |
|---|---|---|---|
| whisper | 452 | | |
| parakeet-v2 | 447 | 30 clips | 68 clips |
| parakeet-v3 | 537 | 18 clips | 74 clips |

v2's whole lead is one clip: `20260905T171734Z` (56.9 s), where Whisper looped (215 words
out for 128 in, 68.8% WER) and Parakeet did not, 79 errors fewer. Without that clip v2
makes 74 more errors than Whisper over the other 197, and is worse on more than twice as
many clips as it is better. The corrections bank agrees: v2 is worse on 32 clips and
better on 10.

So Parakeet does not loop where Whisper sometimes does, and that is worth having, but
on ordinary clips Whisper is the better recognizer of Dan's speech. The loop is the same
failure the Phase 7 write-up proposes a guard for.

## What a switch would cost

- **No hotwords.** Parakeet has no biasing API. The loop guard plus static hotwords
  scored 7.3 WER from the September rows (Phase 7), better than either model here.
- **No fine-tuning path.** `scripts/finetune_whisper.py` and its 66 banked corrections do
  not carry over.
- **GPU memory.** The device-level reading was 25 GB for both models over the full runs,
  against 4.3 GB in a 5-clip smoke run. That is onnxruntime's CUDA memory arena growing
  for the longest clips, not the weights (2.4 GB on disk, fp32); a capped arena or the
  int8 export would bring it down, but as shipped it is ten times Whisper's 2.32 GB.
- **CUDA 13.** `onnxruntime-gpu` 1.32 needs CUDA 13 and cuDNN 9. It runs here only by
  importing the `ml` group's torch first; the app's CUDA 12 wheels do not serve it.

Speed is not a reason: Parakeet's p50 is 0.08 s against Whisper's 0.09 s in September on
an unshared GPU, and its cold load is about a second faster, under the 3 s the benchmark
rule counts.

## Decision

Pending Dan.

Recommended: do not build a Parakeet backend. Its pass rests on one Whisper loop, it is
worse on most clips in both corpora, and switching gives up hotwords and fine-tuning. The
loop guard planned after Phase 7 addresses the same failure inside Whisper.

## Reproducing

```powershell
uv run --with "onnx-asr[gpu,hub]" python scripts/bench_asr.py --candidates parakeet-v2,parakeet-v3 --out research/asr-benchmark-parakeet.md
uv run --with "onnx-asr[gpu,hub]" python scripts/bench_asr.py --corpus corrections --split all --candidates parakeet-v2,parakeet-v3 --out research/asr-benchmark-parakeet-corrections.md
```

Do not put `whisper` in the same `--with` run (see above). The first command rewrites this
whole file with its table; give it another `--out`. The per-clip CSVs hold dictation text
and stay local.
