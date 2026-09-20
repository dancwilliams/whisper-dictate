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

## Decision, 2026-09-19

**Primary: Whisper large-v3-turbo. Fallback: Cohere.** Whisper has the lowest
WER, a third of Cohere's cold reload and 40% of its VRAM; Cohere stays as the
fallback for when Whisper cannot be loaded.

**Hotwords: off globally.** The percentages flatter the trade. In absolute terms
over the 198 clips, the 400-char hotword string:

- rescued 4 domain-term occurrences (98 -> 102 of 113) and broke one (`N8N`,
  which plain Whisper got right)
- cost about 63 additional word errors (467 -> 530 over 5,192 reference words)

That is roughly 16 extra word errors for each domain term recovered. Only 85 of
198 clips contain a domain term at all, so 57% of dictations would pay the cost
for no benefit.

The terms missed by both candidates - Traefik, Capobianco, OPNsense, Wispr Flow,
Yessir - are the ones the glossary already has exact rules for. The string layer
fixes those at no cost to the error rate, which is what it is for.

Phase 6 should apply the 400-char budget per application instead, where the
vocabulary actually occurs, and leave general dictation unbiased.

## Phonetic glossary rules, measured 2026-09-20

Phonetic rules match on a single Metaphone code by exact equality. Measured
against the same 198 clips, with the 12 terms in Dan's glossary whose codes are
long enough to qualify:

| glossary | domain-term recall | clips changed |
|---|---|---|
| exact rules only | 91.2% (103/113) | - |
| exact + 12 phonetic rules | 91.2% (103/113) | 0 |

**The phonetic rules change nothing on this corpus.** Every domain-term error the
recognizer actually makes is either already fixed by an exact rule, or involves a
term too short to be phonetic at all: `Claude` codes as `KLT` and `yessir` as
`YSR`, both under the five-symbol floor that keeps them from rewriting ordinary
speech.

They are kept because they are free and safe rather than because they are
pulling weight. Their value is speculative: a future variant that happens to
share a code gets fixed without a new rule.

### Why the match is not loosened

The obvious complaint is that `threat facts` - what Whisper actually writes for
`threatfax` - codes as `0RTFKTS`, one symbol from `0RTFKS`, and is missed.
Allowing a one-symbol difference was measured over the same corpus:

| matching | false positives on real text |
|---|---|
| exact equality (shipped) | none |
| one-symbol difference | `Couldn't` -> Claude.MD, `Copying` -> Capobianco, `kept being` -> Capobianco, `out GPT-6` -> ChatGPT, `through DFW So` -> threatfax |

Rewriting "Couldn't" into a filename is far worse than missing a variant, so the
match stays exact. The remedy for a near-miss is an ordinary exact rule, which
is what the hostname entries in the glossary already are.

### Testing a phonetic rule

Use a term whose recognizer errors differ in *sound*, not by an inserted
consonant, and one that no exact rule already covers - otherwise the exact rule
fires first and the test proves nothing. `sonar cube` is a poor test for this
reason: an exact rule already catches it.
