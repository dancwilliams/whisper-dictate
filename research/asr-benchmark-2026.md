# ASR benchmark, 2026-09-19

198 clips from the Wispr Flow export, 41.0 minutes of speech (median 8.3s).

| candidate | WER % | domain recall % | p50 s | p90 s | cold s | VRAM GB | garbage |
|---|---|---|---|---|---|---|---|
| cohere | 15.5 | 84.1 | 0.16 | 0.41 | 7.8 | 5.55 | 0 |
| whisper | 9.0 | 86.7 | 0.09 | 0.27 | 2.0 | 2.26 | 2 |
| whisper-hotwords | 10.2 | 90.3 | 0.09 | 0.23 | 1.5 | 2.26 | 2 |

Lower WER wins, unless another candidate is within 1.0 point *and* has better
domain recall or a cold reload more than 3 s faster - a 5-minute idle TTL starts
35.5% of dictations cold. Any candidate with garbage on more than 2 clips is out.

WER is word-level edit distance over lowercased, unpunctuated text, against the
user's own edit where it still resembles the dictation and the formatted text
otherwise. Domain recall counts the mined hotword terms that appear in a
reference and survive into the hypothesis.

## Hotword budget sweep

Whisper encodes hotwords into its prompt context, which competes with the audio
for the decoding budget. Separate runs of `whisper-hotwords`, scored against the
same fixed 86-term vocabulary:

| hotword chars | terms given | WER % | domain recall % | garbage | clips that failed |
|---|---|---|---|---|---|
| 0 (plain whisper) | 0 | 9.0 | 86.7 | 2 | 0 |
| 200 | 23 | 11.4 | 89.4 | 2 | 0 |
| 400 | 43 | 10.2 | 90.3 | 2 | 0 |
| 800 | 86 | 12.0 | 90.3 | 3 | 1 |

At 800 chars a long clip has no decoding budget left at all and faster-whisper
raises "The maximum decoding length must be > 0". 400 chars buys the whole
recall gain at the smallest WER cost and never fails, so it is the budget used
in the table above and the one Phase 6 should ship.

## Reading this

Whisper large-v3-turbo has the lowest WER by 1.2 points over its own
hotword-biased variant and 6.5 over Cohere, at a third of Cohere's cold reload
and 40% of its VRAM. Cohere never produced garbage, where both Whisper variants
did on 2 of 198 clips.

The trade the table does not settle: hotwords cost 1.2 WER points and buy 3.6
points of domain-term recall. Whether the vocabulary matters more than the
general error rate is a judgement about how the tool is actually used, and is
Dan's to make.
