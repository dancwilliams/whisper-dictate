# ASR benchmark, 2026-11-22

67 clips from the corrections bank (every clip), 13.9 minutes of speech (median 9.1s).

| candidate | WER % | domain recall % | p50 s | p90 s | cold s | VRAM GB | garbage |
|---|---|---|---|---|---|---|---|
| parakeet-v2 | 9.6 | 20.0 | 0.09 | 0.15 | 1.4 | 25.00 | 0 |
| parakeet-v3 | 11.3 | 30.0 | 0.08 | 0.14 | 1.0 | 25.10 | 0 |

Lower WER wins, unless another candidate is within 1.0 point *and* has better
domain recall or a cold reload more than 3 s faster - a 5-minute idle TTL starts
35.5% of dictations cold. Any candidate with garbage on more than 2 clips is out.

WER is word-level edit distance over lowercased, unpunctuated text, against the
hand correction made in Fix last dictation. Domain recall counts the glossary
replacements that appear in a reference and survive into the hypothesis.
