#!/usr/bin/env python3
"""Benchmark ASR candidates on Dan's own recorded dictations.

The choice of recognizer is made here, on 200 real clips from the Wispr Flow
export, not on a leaderboard. Each candidate is scored on word error rate,
recall of the domain terms that actually matter, latency, VRAM, how long a cold
reload costs, and how often it emits garbage.

    uv run python scripts/bench_asr.py
    uv run python scripts/bench_asr.py --candidates whisper,whisper-hotwords
    uv run python scripts/bench_asr.py --limit 20        # a quick pass

Stdlib + numpy; the candidates themselves are imported lazily, so a missing
torch only costs you that candidate.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import time
import wave
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

EXPORT = Path(r"C:\Users\Dan Williams\wispr-flow-export")
SAMPLE_RATE = 16000

# Whisper encodes hotwords into its prompt context and truncates at
# max_length // 2 (~220 tokens). Budget in chars, ~4 chars/token.
HOTWORD_CHAR_BUDGET = 800

WORD = re.compile(r"[a-z0-9']+")


# ----------------------------------------------------------------------------
# Corpus
# ----------------------------------------------------------------------------
@dataclass
class Clip:
    path: Path
    reference: str
    seconds: float


def read_wav(path: Path) -> np.ndarray:
    """16 kHz mono int16 on disk -> float32 in [-1, 1], which is what both
    backends want."""
    with wave.open(str(path), "rb") as fh:
        frames = fh.readframes(fh.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def normalize(text: str) -> list[str]:
    """Lowercase, drop punctuation. Scoring formatting differences would measure
    the formatter, not the recognizer."""
    return WORD.findall((text or "").lower())


def reference_for(row: dict) -> str | None:
    """What the clip should have said.

    editedText is the user's own correction and so the better reference - but it
    sometimes contains unrelated typing that happened after the paste. A low
    token-sequence similarity to formattedText means the edit was no longer about
    this dictation, so fall back.
    """
    formatted = (row.get("formattedText") or "").strip()
    edited = (row.get("editedText") or "").strip()
    if not formatted and not edited:
        return None
    if edited and formatted:
        if SequenceMatcher(None, normalize(formatted), normalize(edited)).ratio() >= 0.5:
            return edited
        return formatted
    return edited or formatted


def load_clips(export: Path, limit: int | None = None) -> list[Clip]:
    audio_dir = export / "audio"
    clips: list[Clip] = []
    with (export / "history.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = row.get("audio_file")
            if not name:
                continue
            path = audio_dir / Path(name).name
            if not path.exists():
                continue
            reference = reference_for(row)
            if not reference:
                continue
            with wave.open(str(path), "rb") as wf:
                seconds = wf.getnframes() / wf.getframerate()
            clips.append(Clip(path=path, reference=reference, seconds=seconds))
            if limit and len(clips) >= limit:
                break
    return clips


def load_terms(export: Path) -> list[str]:
    """Every mined domain term.

    This is the scoring vocabulary, and it stays fixed however much of it a
    candidate is actually given - otherwise shrinking the hotword budget would
    shrink the denominator and flatter the result.
    """
    path = export / "mined" / "hotwords.txt"
    if not path.exists():
        return []
    return [t.strip() for t in path.read_text(encoding="utf-8").split(",") if t.strip()]


def load_hotwords(export: Path, budget: int = HOTWORD_CHAR_BUDGET) -> str:
    """The prefix of the term list that fits in Whisper's prompt context."""
    terms = load_terms(export)
    out: list[str] = []
    used = 0
    for term in terms:
        if used + len(term) + 2 > budget:
            break
        out.append(term)
        used += len(term) + 2
    return ", ".join(out)


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------
def word_error_rate(reference: list[str], hypothesis: list[str]) -> tuple[int, int]:
    """Levenshtein distance over words. Returns (errors, reference length)."""
    previous = list(range(len(hypothesis) + 1))
    for i, r in enumerate(reference, start=1):
        current = [i]
        for j, h in enumerate(hypothesis, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (r != h),  # substitution
                )
            )
        previous = current
    return previous[-1], len(reference)


def is_garbage(text: str) -> bool:
    """Empty output, or a 4-gram repeated four times or more - the shape a
    looping recognizer produces."""
    words = normalize(text)
    if not words:
        return True
    if len(words) < 16:
        return False
    counts: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - 3):
        gram = tuple(words[i : i + 4])
        counts[gram] = counts.get(gram, 0) + 1
        if counts[gram] >= 4:
            return True
    return False


def term_recall(terms: list[str], reference: str, hypothesis: str) -> tuple[int, int]:
    """Of the domain terms present in the reference, how many survive into the
    hypothesis. Returns (found, expected)."""
    ref, hyp = " ".join(normalize(reference)), " ".join(normalize(hypothesis))
    found = expected = 0
    for term in terms:
        needle = " ".join(normalize(term))
        if not needle or needle not in ref:
            continue
        expected += 1
        found += needle in hyp
    return found, expected


# ----------------------------------------------------------------------------
# Candidates
# ----------------------------------------------------------------------------
@dataclass
class Result:
    name: str
    errors: int = 0
    ref_words: int = 0
    terms_found: int = 0
    terms_expected: int = 0
    garbage: int = 0
    latencies: list[float] = field(default_factory=list)
    peak_vram_gb: float = 0.0
    cold_seconds: float = 0.0
    rows: list[dict] = field(default_factory=list)
    failed: str | None = None
    errored: list[str] = field(default_factory=list)

    @property
    def wer(self) -> float:
        return 100.0 * self.errors / self.ref_words if self.ref_words else float("nan")

    @property
    def recall(self) -> float:
        return (
            100.0 * self.terms_found / self.terms_expected if self.terms_expected else float("nan")
        )

    def percentile(self, p: float) -> float:
        if not self.latencies:
            return float("nan")
        ordered = sorted(self.latencies)
        index = min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))
        return ordered[index]


class WhisperCandidate:
    """faster-whisper, optionally biased with mined hotwords."""

    def __init__(self, model_name: str = "large-v3-turbo", hotwords: str | None = None):
        self.model_name = model_name
        self.hotwords = hotwords
        self.model = None

    def load(self) -> None:
        from whisper_dictate.config import set_cuda_paths

        set_cuda_paths()
        from whisper_dictate import transcription

        self.model = transcription.load_model(self.model_name, "cuda", "float16")

    def transcribe(self, audio: np.ndarray) -> str:
        from whisper_dictate import transcription

        return transcription.transcribe_audio(
            self.model, audio, language="en", hotwords=self.hotwords
        )

    def unload(self) -> None:
        self.model = None


class CohereCandidate:
    """CohereLabs/cohere-transcribe-03-2026. No vocabulary biasing API."""

    MODEL_ID = "CohereLabs/cohere-transcribe-03-2026"

    def __init__(self) -> None:
        self.model = None
        self.processor = None

    def load(self) -> None:
        import torch
        from transformers import AutoProcessor, CohereAsrForConditionalGeneration

        self.processor = AutoProcessor.from_pretrained(self.MODEL_ID)
        self.model = (
            CohereAsrForConditionalGeneration.from_pretrained(self.MODEL_ID, dtype=torch.bfloat16)
            .to("cuda")
            .eval()
        )

    def transcribe(self, audio: np.ndarray) -> str:
        import torch

        inputs = self.processor(audio, "en", sampling_rate=SAMPLE_RATE, return_tensors="pt")

        def place(value):
            if not hasattr(value, "to"):
                return value
            # Float features must match the model dtype; token ids must stay integral.
            return (
                value.to("cuda", torch.bfloat16) if value.is_floating_point() else value.to("cuda")
            )

        inputs = {k: place(v) for k, v in inputs.items()}
        with torch.inference_mode():
            ids = self.model.generate(**inputs, max_new_tokens=448)
        return self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip()

    def unload(self) -> None:
        self.model = self.processor = None


def build(name: str, hotwords: str) -> object:
    if name == "cohere":
        return CohereCandidate()
    if name == "whisper":
        return WhisperCandidate()
    if name == "whisper-hotwords":
        return WhisperCandidate(hotwords=hotwords)
    raise SystemExit(f"unknown candidate: {name}")


# ----------------------------------------------------------------------------
# Running
# ----------------------------------------------------------------------------
def free_vram_bytes() -> int:
    """Device-level free VRAM. torch.max_memory_allocated only sees torch's own
    allocations, and ctranslate2 allocates outside it, so ask the device."""
    try:
        import torch

        if torch.cuda.is_available():
            free, _total = torch.cuda.mem_get_info()
            return int(free)
    except (ImportError, RuntimeError):
        pass
    return 0


def run_candidate(name: str, clips: list[Clip], terms: list[str], hotwords: str) -> Result:
    result = Result(name=name)
    candidate = build(name, hotwords)

    try:
        import torch

        torch.cuda.reset_peak_memory_stats()
    except (ImportError, RuntimeError):
        pass

    baseline_free = free_vram_bytes()
    cold_start = time.monotonic()
    try:
        candidate.load()
    except Exception as e:  # a candidate that cannot load is reported, not fatal
        result.failed = f"{type(e).__name__}: {e}"
        return result

    for index, clip in enumerate(clips):
        audio = read_wav(clip.path)
        started = time.monotonic()
        try:
            text = candidate.transcribe(audio)
        except Exception as e:
            # One clip a candidate cannot handle is a data point, not a reason to
            # lose the other 197. It counts as garbage, which is what the user gets.
            result.errored.append(f"{clip.path.name}: {type(e).__name__}: {e}")
            text = ""
        elapsed = time.monotonic() - started
        if index == 0:
            # Cold reload cost: a fresh load through to the first result. 35.5%
            # of dictations start cold at a 5-minute idle TTL.
            result.cold_seconds = time.monotonic() - cold_start

        result.latencies.append(elapsed)
        errors, ref_len = word_error_rate(normalize(clip.reference), normalize(text))
        result.errors += errors
        result.ref_words += ref_len
        found, expected = term_recall(terms, clip.reference, text)
        result.terms_found += found
        result.terms_expected += expected
        garbage = is_garbage(text)
        result.garbage += garbage
        result.rows.append(
            {
                "candidate": name,
                "clip": clip.path.name,
                "seconds": round(clip.seconds, 2),
                "latency": round(elapsed, 3),
                "wer": round(100.0 * errors / ref_len, 1) if ref_len else "",
                "garbage": int(garbage),
                "reference": clip.reference,
                "hypothesis": text,
            }
        )
        if (index + 1) % 25 == 0 or index + 1 == len(clips):
            print(f"  {index + 1}/{len(clips)} clips", flush=True)

    # Device-level delta: whatever this candidate is holding while resident.
    # Other GPU tenants moving during the run show up here too.
    result.peak_vram_gb = max(0, baseline_free - free_vram_bytes()) / 1e9
    candidate.unload()
    return result


def table(results: list[Result], clips: list[Clip]) -> str:
    total_audio = sum(c.seconds for c in clips)
    lines = [
        f"# ASR benchmark, {time.strftime('%Y-%m-%d')}",
        "",
        f"{len(clips)} clips from the Wispr Flow export, "
        f"{total_audio / 60:.1f} minutes of speech "
        f"(median {statistics.median(c.seconds for c in clips):.1f}s).",
        "",
        "| candidate | WER % | domain recall % | p50 s | p90 s | cold s | VRAM GB | garbage |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.failed:
            lines.append(f"| {r.name} | did not run: {r.failed} | | | | | | |")
            continue
        lines.append(
            f"| {r.name} | {r.wer:.1f} | {r.recall:.1f} | {r.percentile(0.5):.2f} | "
            f"{r.percentile(0.9):.2f} | {r.cold_seconds:.1f} | {r.peak_vram_gb:.2f} | "
            f"{r.garbage} |"
        )
    failures = [(r.name, r.errored) for r in results if r.errored]
    if failures:
        lines += ["", "## Clips a candidate could not transcribe", ""]
        for name, errors in failures:
            lines.append(f"**{name}** - {len(errors)} of {len(clips)}:")
            lines += [f"- `{e}`" for e in errors[:5]]
            if len(errors) > 5:
                lines.append(f"- ...and {len(errors) - 5} more")
            lines.append("")
    lines += [
        "",
        "Lower WER wins, unless another candidate is within 1.0 point *and* has better",
        "domain recall or a cold reload more than 3 s faster - a 5-minute idle TTL starts",
        "35.5% of dictations cold. Any candidate with garbage on more than 2 clips is out.",
        "",
        "WER is word-level edit distance over lowercased, unpunctuated text, against the",
        "user's own edit where it still resembles the dictation and the formatted text",
        "otherwise. Domain recall counts the mined hotword terms that appear in a",
        "reference and survive into the hypothesis.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=EXPORT)
    parser.add_argument("--candidates", default="cohere,whisper,whisper-hotwords")
    parser.add_argument("--limit", type=int, default=None, help="use only the first N clips")
    parser.add_argument(
        "--hotword-chars",
        type=int,
        default=HOTWORD_CHAR_BUDGET,
        help="hotword budget; too large and a long clip has no decoding budget left",
    )
    parser.add_argument("--out", type=Path, default=Path("research/asr-benchmark-2026.md"))
    parser.add_argument("--csv", type=Path, default=Path("research/asr-benchmark-2026.csv"))
    args = parser.parse_args()

    clips = load_clips(args.export, args.limit)
    if not clips:
        raise SystemExit(f"no clips found under {args.export}")
    hotwords = load_hotwords(args.export, args.hotword_chars)
    terms = load_terms(args.export)
    print(f"{len(clips)} clips, {sum(c.seconds for c in clips) / 60:.1f} minutes of speech")
    print(
        f"{len(terms)} domain terms scored; {len(hotwords)} chars of hotwords "
        f"given to the recognizer\n"
    )

    results = []
    for name in [n.strip() for n in args.candidates.split(",") if n.strip()]:
        print(f"{name}...")
        result = run_candidate(name, clips, terms, hotwords)
        results.append(result)
        if result.failed:
            print(f"  did not run: {result.failed}")
        else:
            print(
                f"  WER {result.wer:.1f}%  recall {result.recall:.1f}%  "
                f"p50 {result.percentile(0.5):.2f}s  cold {result.cold_seconds:.1f}s  "
                f"VRAM {result.peak_vram_gb:.2f}GB  garbage {result.garbage}"
            )
            if result.errored:
                print(f"  {len(result.errored)} clips failed outright")

    report = table(results, clips)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report + "\n", encoding="utf-8")

    with args.csv.open("w", encoding="utf-8", newline="") as fh:
        writer = None
        for result in results:
            for row in result.rows:
                if writer is None:
                    writer = csv.DictWriter(fh, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)

    print()
    print(report)
    print(f"\n-> {args.out} and {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
