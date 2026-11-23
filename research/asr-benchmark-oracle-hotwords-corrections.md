# ASR benchmark, 2026-11-22

67 clips from the corrections bank (every clip), 13.9 minutes of speech (median 9.1s).

| candidate | WER % | domain recall % | p50 s | p90 s | cold s | VRAM GB | garbage |
|---|---|---|---|---|---|---|---|
| whisper | 6.4 | 20.0 | 0.40 | 0.84 | 2.7 | 2.32 | 0 |
| whisper-oracle-hotwords | 10.7 | 95.0 | 0.37 | 0.75 | 2.5 | 2.32 | 1 |

Lower WER wins, unless another candidate is within 1.0 point *and* has better
domain recall or a cold reload more than 3 s faster - a 5-minute idle TTL starts
35.5% of dictations cold. Any candidate with garbage on more than 2 clips is out.

WER is word-level edit distance over lowercased, unpunctuated text, against the
hand correction made in Fix last dictation. Domain recall counts the glossary
replacements that appear in a reference and survive into the hypothesis.
