#!/usr/bin/env python3
"""Mine a Wispr Flow export for glossary rules, hotwords and snippets.

Reads history.jsonl (formattedText vs editedText = what you fixed by hand) and
dictionary/wispr-dictionary-full.csv (observedSource = the misrecognition Flow
itself saw), and writes files whisper-dictate can consume:

    glossary.csv         Edit -> Glossary... -> Import CSV
    hotwords.txt         faster-whisper `hotwords=` (global, ranked)
    hotwords_by_app.json same, scoped to the active process
    snippets.csv         text expansions, kept separate on purpose

Read-only on the export. Stdlib only.

    uv run python scripts/mine_wispr_history.py "/mnt/c/Users/Dan Williams/wispr-flow-export"
    uv run python scripts/mine_wispr_history.py --selftest
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

# Internal dots/@ keep emails and initialisms whole; trailing punctuation is never
# part of the word, or every sentence-final edit reads as a vocabulary fix.
WORD = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9'._@&-]*[A-Za-z0-9])?")

# Edits of these are formatting, not vocabulary — the normalizer's job, not the glossary's.
FILLERS = {
    "um",
    "uh",
    "er",
    "ah",
    "so",
    "like",
    "just",
    "really",
    "okay",
    "ok",
    "yeah",
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "of",
    "to",
    "in",
    "is",
    "it",
    "that",
    "this",
    "i",
    "you",
    "we",
    "they",
    "was",
    "were",
    "be",
    "been",
    "have",
    "has",
}

# Triggers that are ordinary English: rewriting these globally damages real speech
# ("traffic" -> "Traefik" ruins every sentence about road traffic). The recognizer
# learns these terms from hotwords instead, where a collision costs nothing.
# ponytail: hand-kept stoplist; swap for a word-frequency list if review noise persists.
COMMON_WORDS = FILLERS | {
    "traffic",
    "cloud",
    "nuke",
    "test",
    "skills",
    "gun",
    "said",
    "there",
    "their",
    "cause",
    "course",
    "point",
    "power",
    "right",
    "sound",
    "state",
    "thread",
}

# Hotwords are encoded into Whisper's sot_prev context and silently truncated at
# max_length // 2 (~220 tokens). Budget in chars, ~4 chars/token.
# ponytail: char/4 token estimate; swap in the real tokenizer if terms ever get cut.
HOTWORD_CHAR_BUDGET = 200 * 4


def tokens(text: str) -> list[str]:
    return WORD.findall(text or "")


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def extract_pairs(before: str, after: str, max_span: int = 3) -> list[tuple[str, str]]:
    """Return (misheard, corrected) pairs from one hand-edited dictation.

    Only short, local substitutions that still *sound* alike count. A low
    similarity means the user changed their mind, not that the recognizer erred.
    """
    a, b = tokens(before), tokens(after)
    if not a or not b:
        return []
    # The user kept typing after the paste; the diff is no longer about this dictation.
    if SequenceMatcher(None, a, b).ratio() < 0.5:
        return []

    pairs = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b).get_opcodes():
        if op != "replace" or i2 - i1 > max_span or j2 - j1 > max_span:
            continue
        wrong, right = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if not wrong or not right or wrong.lower() == right.lower():
            continue
        if all(t.lower() in FILLERS for t in a[i1:i2]):
            continue
        if similar(wrong, right) < 0.5:
            continue
        pairs.append((wrong, right))
    return pairs


def risky(trigger: str, replacement: str) -> bool:
    """True when firing this rule globally would damage ordinary text.

    Flow's observedSource pairs are recognition hints, not safe substitutions:
    it saw "test" where "memtest" was meant. As a whole-word rewrite that ruins
    every real "test". Short or self-contained triggers go to hotwords instead,
    where teaching the recognizer the word costs nothing.
    """
    t = re.sub(r"[^a-z0-9]", "", trigger.lower())
    r = re.sub(r"[^a-z0-9]", "", replacement.lower())
    return len(t) < 5 or t in r or r in t or t in COMMON_WORDS


def load_dictionary(export: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str]], Counter]:
    """Return (rules, snippets, term_frequency) from Flow's own dictionary."""
    rules: list[tuple[str, str]] = []
    snippets: list[tuple[str, str]] = []
    freq: Counter = Counter()
    path = export / "dictionary" / "wispr-dictionary-full.csv"
    if not path.exists():
        return rules, snippets, freq

    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            phrase = (row.get("phrase") or "").strip()
            replacement = (row.get("replacement") or "").strip()
            observed = (row.get("observedSource") or "").strip()
            if not phrase:
                continue
            freq[phrase] += int(row.get("frequencyUsed") or 0) + 1
            if row.get("isSnippet") == "1":
                snippets.append((phrase, replacement))
            elif replacement:
                rules.append((phrase, replacement))
            if observed and observed.lower() != phrase.lower():
                # Flow recorded the exact misrecognition it saw.
                rules.append((observed, phrase))
    return rules, snippets, freq


def mine(export: Path, min_count: int) -> dict:
    dict_rules, snippets, dict_freq = load_dictionary(export)
    dict_risky = [
        (t, r, "flow dictionary, unsafe as a global rule") for t, r in dict_rules if risky(t, r)
    ]
    dict_rules = [(t, r) for t, r in dict_rules if not risky(t, r)]
    known = {right.lower() for _, right in dict_rules} | {t.lower() for t in dict_freq}

    pair_counts: Counter = Counter()
    cased: dict[tuple[str, str], Counter] = defaultdict(Counter)
    by_app: dict[str, Counter] = defaultdict(Counter)
    rows = edited = 0

    with (export / "history.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows += 1
            before, after = row.get("formattedText"), row.get("editedText")
            if not before or not after or before == after:
                continue
            edited += 1
            app = (row.get("app") or "unknown").strip()
            for wrong, right in extract_pairs(before, after):
                key = (wrong.lower(), right.lower())
                pair_counts[key] += 1
                cased[key][(wrong, right)] += 1
                by_app[app][right] += 1

    # A single occurrence is enough when Flow's own dictionary already knows the term.
    accepted, review = [], []
    for k, n in pair_counts.most_common():
        if n < min_count and k[1] not in known:
            continue
        pair = cased[k].most_common(1)[0][0]
        (review if risky(*pair) else accepted).append((*pair, f"mined x{n}"))

    # Snippet triggers ("my personal email address") are expansion keys, not
    # vocabulary — they would waste the hotword budget teaching Whisper a phrase
    # it already hears correctly.
    terms: Counter = Counter(
        {t: n for t, n in dict_freq.items() if t not in {p for p, _ in snippets}}
    )
    for k, n in pair_counts.items():
        terms[cased[k].most_common(1)[0][0][1]] += n

    review = dict_risky + review
    return {
        "rows": rows,
        "edited": edited,
        "mined_rules": accepted,
        "dict_rules": dict_rules,
        "review": review,
        "snippets": snippets,
        "terms": terms,
        "by_app": by_app,
    }


def budget(terms: list[str], chars: int = HOTWORD_CHAR_BUDGET) -> list[str]:
    """Trim a ranked term list to what Whisper's hotword context will actually hold."""
    out: list[str] = []
    used = 0
    for t in terms:
        if used + len(t) + 2 > chars:
            break
        out.append(t)
        used += len(t) + 2
    return out


def write(out: Path, data: dict, top_per_app: int) -> None:
    out.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    with (out / "glossary.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["trigger", "replacement", "match_type", "case_sensitive", "word_boundary"])
        # A snippet is just a glossary rule whose trigger is long and distinctive.
        snippet_rules = [(p, r) for p, r in data["snippets"] if r]
        for trigger, replacement, *_ in data["dict_rules"] + data["mined_rules"] + snippet_rules:
            if trigger.lower() in seen:
                continue
            seen.add(trigger.lower())
            w.writerow([trigger, replacement, "phrase", "false", "true"])

    ranked = [t for t, _ in data["terms"].most_common()]
    (out / "hotwords.txt").write_text(", ".join(budget(ranked)), encoding="utf-8")

    per_app = {
        app: budget([t for t, _ in c.most_common(top_per_app)])
        for app, c in data["by_app"].items()
        if c
    }
    (out / "hotwords_by_app.json").write_text(json.dumps(per_app, indent=2), encoding="utf-8")

    with (out / "review.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["trigger", "replacement", "why_not_auto_applied"])
        w.writerows(data["review"])

    with (out / "snippets.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["phrase", "replacement"])
        w.writerows(data["snippets"])


def selftest() -> None:
    assert extract_pairs("send it to threat fax", "send it to threatfax") == [
        ("threat fax", "threatfax")
    ]
    # Filler-only edits belong to the normalizer, not the glossary.
    assert extract_pairs("um so I need that", "so I need that") == []
    # KNOWN CEILING: a same-sounding change of mind is indistinguishable from a
    # misrecognition without a lexicon, so it survives extraction. min_count and
    # the review-before-import step are what catch it.
    # ponytail: no lexicon; add one only if review noise is actually annoying.
    assert extract_pairs("ship it on Friday", "ship it on Thursday") == [("Friday", "Thursday")]
    # Wholesale rewrites are discarded.
    assert extract_pairs("the cat sat down", "completely different words here now") == []
    # Case-only fixes are the normalizer's job too.
    assert extract_pairs("call dan today", "call Dan today") == []
    assert budget(["alpha", "beta"], chars=8) == ["alpha"]
    # A trigger contained in its own replacement would rewrite ordinary text.
    assert risky("test", "memtest") and risky("GPT", "ChatGPT") and risky("skills", "claude-skills")
    # An ordinary English word as a trigger rewrites ordinary speech.
    assert risky("traffic", "Traefik") and risky("Cloud", "Claude")
    assert not risky("infysical.threatfacts.com", "infisical.threatfax.com")
    # Snippets reach glossary.csv; rules without a replacement do not.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        write(
            out,
            {
                "dict_rules": [],
                "mined_rules": [],
                "review": [],
                "terms": Counter(),
                "by_app": {},
                "snippets": [("my personal email", "me@example.com"), ("empty trigger", "")],
            },
            60,
        )
        rows = list(csv.DictReader((out / "glossary.csv").open(encoding="utf-8", newline="")))
    assert [(r["trigger"], r["replacement"], r["match_type"]) for r in rows] == [
        ("my personal email", "me@example.com", "phrase")
    ]
    print("selftest ok")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("export", nargs="?", type=Path, help="wispr-flow-export directory")
    p.add_argument("-o", "--out", type=Path, default=Path("wispr-mined"))
    p.add_argument("--min-count", type=int, default=2, help="occurrences before a new rule is kept")
    p.add_argument("--top-per-app", type=int, default=60)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        selftest()
        return 0
    if not args.export:
        p.error("export directory required (or --selftest)")

    data = mine(args.export, args.min_count)
    write(args.out, data, args.top_per_app)

    print(f"{data['rows']} dictations, {data['edited']} hand-edited")
    print(
        f"{len(data['dict_rules'])} rules from Flow's dictionary, "
        f"{len(data['mined_rules'])} mined from your edits"
    )
    print(f"{len(data['snippets'])} snippets, {len(data['terms'])} distinct terms")
    print(f"{len(data['review'])} pairs held back for review (unsafe as global rules)")
    print(f"-> {args.out}/")
    for trigger, replacement, *_ in data["mined_rules"][:15]:
        print(f"   {trigger!r} -> {replacement!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
