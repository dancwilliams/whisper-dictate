#!/usr/bin/env python3
"""Fine-tune Whisper on your own corrections.

Every Fix last dictation lands in corrections.jsonl with a copy of its clip in
training/. This trains a LoRA on those labels (plus a sample of uncorrected
clips from the live window, so the model is not taught that every clip is
hard), merges it into large-v3-turbo, converts the result to a CTranslate2
folder under ~/.whisper_dictate/models/, and prints base-vs-tuned WER on the
corrections hold-out and on the Wispr export.

    uv run python scripts/finetune_whisper.py
    uv run python scripts/finetune_whisper.py --epochs 5 --name personal-2026-11-01
    uv run python scripts/finetune_whisper.py --selftest

One clip in five is held out by file name (is_holdout), which bench_asr.py
imports so the benchmark and the trainer never disagree on which clips are
held back. Stdlib only at import time; everything ML is loaded inside main().
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
import zlib
from pathlib import Path

HOME = Path.home() / ".whisper_dictate"
CORRECTIONS = HOME / "corrections.jsonl"
TRAINING = HOME / "training"
MODELS = HOME / "models"
HISTORY = HOME / "history.jsonl"
AUDIO = HOME / "audio"

SAMPLE_RATE = 16000
# Whisper's input is a fixed 30 s log-mel window.
# ponytail: longer clips are skipped, not chunked; chunk them if the count printed
# at load time ever matters.
MAX_SECONDS = 30
BATCH = 8


def is_holdout(name: str) -> bool:
    """One clip in five is never trained on. Keyed on the file name so both
    scripts agree and the split does not move as the bank grows.
    ponytail: one fixed split; k-fold if the bank stays small enough for one
    fifth of it to be a noisy number."""
    return zlib.crc32(name.encode()) % 5 == 0


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_bank() -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]:
    """(train, holdout) as (wav path, label). A clip corrected twice keeps the
    last fix; a cleanup-wrong tick with no text change has nothing to teach."""
    latest: dict[str, str] = {}
    for row in read_jsonl(CORRECTIONS):
        name, raw, corrected = row.get("audio_file"), row.get("raw", ""), row.get("corrected", "")
        if name and corrected.strip() and corrected.strip() != raw.strip():
            latest[name] = corrected.strip()
    train, holdout = [], []
    for name, label in sorted(latest.items()):
        path = TRAINING / name
        if path.exists():
            (holdout if is_holdout(name) else train).append((path, label))
    return train, holdout


def load_mix(count: int, exclude: set[str]) -> list[tuple[Path, str]]:
    """Uncorrected clips from the live window, labelled with their raw text.
    Dan accepted these as heard, so they anchor the model to what it already
    gets right.
    ponytail: a raw label can itself be wrong, so this is a regulariser, not a
    signal; lower --mix-ratio if the hold-out says so."""
    pool = []
    for row in read_jsonl(HISTORY):
        name, raw = row.get("audio_file"), (row.get("raw") or "").strip()
        if name and raw and name not in exclude and (AUDIO / name).exists():
            pool.append((AUDIO / name, raw))
    return random.Random(0).sample(pool, min(count, len(pool)))


def selftest() -> None:
    # bench_asr imports this module for the split; it must not drag torch in.
    assert "torch" not in sys.modules
    assert is_holdout("20261014T051535.wav") == is_holdout("20261014T051535.wav")
    names = [f"2026{i:08d}T120000.wav" for i in range(1000)]
    share = sum(map(is_holdout, names)) / len(names)
    assert 0.15 <= share <= 0.25, share
    print("ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--base", default="large-v3-turbo", help="Whisper size to tune")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--rank", type=int, default=16, help="LoRA rank")
    parser.add_argument("--name", default=f"personal-{time.strftime('%Y-%m-%d')}")
    parser.add_argument("--min-clips", type=int, default=100, help="corrections needed to train")
    parser.add_argument(
        "--mix-ratio", type=float, default=2, help="uncorrected clips per correction"
    )
    parser.add_argument("--keep-hf", action="store_true", help="keep the merged HF folder")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0

    train, holdout = load_bank()
    if len(train) < args.min_clips:
        print(f"{len(train)} training corrections in {CORRECTIONS}; need {args.min_clips}")
        return 1
    mix = load_mix(int(args.mix_ratio * len(train)), {p.name for p, _ in train + holdout})
    print(f"{len(train)} corrections + {len(mix)} uncorrected clips; {len(holdout)} held out")

    import bench_asr
    import torch
    from ctranslate2.converters import TransformersConverter
    from peft import LoraConfig, get_peft_model
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    hf_id = f"openai/whisper-{args.base}"
    processor = WhisperProcessor.from_pretrained(hf_id)
    processor.tokenizer.set_prefix_tokens(language="en", task="transcribe")
    model = WhisperForConditionalGeneration.from_pretrained(hf_id, dtype=torch.bfloat16).cuda()
    sot = model.config.decoder_start_token_id

    def encode(clips: list[tuple[Path, str]]) -> list[tuple[torch.Tensor, list[int], str]]:
        """(log-mel features, label token ids, label text) per clip."""
        out, skipped = [], 0
        for path, label in clips:
            audio = bench_asr.read_wav(path)
            if len(audio) > MAX_SECONDS * SAMPLE_RATE:
                skipped += 1
                continue
            mel = processor.feature_extractor(audio, sampling_rate=SAMPLE_RATE, return_tensors="np")
            ids = processor.tokenizer(label).input_ids
            # The model prepends <|startoftranscript|> itself when it shifts labels right.
            if ids[0] == sot:
                ids = ids[1:]
            out.append((torch.from_numpy(mel.input_features[0]).to(torch.bfloat16), ids, label))
        if skipped:
            print(f"skipped {skipped} clips longer than {MAX_SECONDS} s")
        return out

    def batches(items: list, size: int):
        for i in range(0, len(items), size):
            yield items[i : i + size]

    def holdout_wer(model, examples: list[tuple[torch.Tensor, list[int], str]]) -> float:
        model.eval()
        errors = words = 0
        with torch.no_grad():
            for batch in batches(examples, BATCH):
                features = torch.stack([f for f, _, _ in batch]).cuda()
                ids = model.generate(
                    input_features=features, language="en", task="transcribe", max_new_tokens=200
                )
                for text, (_, _, reference) in zip(
                    processor.batch_decode(ids, skip_special_tokens=True), batch
                ):
                    e, n = bench_asr.word_error_rate(
                        bench_asr.normalize(reference), bench_asr.normalize(text)
                    )
                    errors, words = errors + e, words + n
        model.train()
        return 100.0 * errors / words if words else float("nan")

    data = encode(train + mix)
    eval_set = encode(holdout)

    model = get_peft_model(
        model,
        LoraConfig(
            r=args.rank,
            lora_alpha=2 * args.rank,
            lora_dropout=0.05,
            target_modules=["q_proj", "v_proj"],
        ),
    )
    model.print_trainable_parameters()

    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=args.lr)
    steps = args.epochs * ((len(data) + BATCH - 1) // BATCH)
    warmup = max(1, steps // 10)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda s: (
            (s + 1) / warmup if s < warmup else max(0.0, (steps - s) / max(1, steps - warmup))
        ),
    )
    model.train()
    step = 0
    for epoch in range(1, args.epochs + 1):
        random.Random(epoch).shuffle(data)
        for batch in batches(data, BATCH):
            features = torch.stack([f for f, _, _ in batch]).cuda()
            width = max(len(ids) for _, ids, _ in batch)
            labels = torch.tensor(
                [ids + [-100] * (width - len(ids)) for _, ids, _ in batch], device="cuda"
            )
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = model(input_features=features, labels=labels).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            step += 1
            if step % 20 == 0 or step == steps:
                print(f"step {step}/{steps} loss {loss.item():.3f}", flush=True)
        wer = holdout_wer(model, eval_set) if eval_set else float("nan")
        print(f"epoch {epoch}/{args.epochs} hold-out WER {wer:.1f}%", flush=True)
    print(f"peak VRAM {torch.cuda.max_memory_allocated() / 1e9:.1f} GB")

    hf_dir, out_dir = MODELS / f"{args.name}-hf", MODELS / args.name
    merged = model.merge_and_unload()
    merged.save_pretrained(hf_dir)
    processor.save_pretrained(hf_dir)
    # Transformers 5 names its file processor_config.json; the converter wants this one.
    processor.feature_extractor.save_pretrained(hf_dir)
    del model, merged, data, eval_set
    torch.cuda.empty_cache()

    TransformersConverter(
        str(hf_dir), copy_files=["tokenizer.json", "preprocessor_config.json"]
    ).convert(str(out_dir), quantization="float16", force=True)
    if not args.keep_hf:
        shutil.rmtree(hf_dir, ignore_errors=True)
    print(f"-> {out_dir}")

    # Did it learn the hard cases, and did it stay good at ordinary speech? The
    # Wispr clips are never trained on.
    gate = []
    for corpus, clips in [
        ("corrections", bench_asr.load_clips(bench_asr.EXPORT, corpus="corrections")),
        ("wispr", bench_asr.load_clips(bench_asr.EXPORT)),
    ]:
        if not clips:
            print(f"\nno {corpus} clips to benchmark")
            continue
        terms = bench_asr.load_terms(bench_asr.EXPORT, corpus)
        results = [
            bench_asr.run_candidate("whisper", clips, terms, "", model=m, label=Path(m).name)
            for m in (args.base, str(out_dir))
        ]
        print("\n" + bench_asr.table(results, clips, corpus))
        base, tuned = (r.wer for r in results)
        gate.append(tuned < base if corpus == "corrections" else tuned <= base + 1.0)
    print(
        "\ngate: "
        + (
            "PASS"
            if gate and all(gate)
            else "FAIL (below base on the hold-out, within 1.0 point on Wispr)"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
