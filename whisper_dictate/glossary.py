"""Glossary management, persistence, and application logic."""

from __future__ import annotations

import csv
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Literal, cast, get_args

logger = logging.getLogger("whisper_dictate")

MatchType = Literal["word", "phrase", "regex", "phonetic"]


def as_match_type(value: object) -> MatchType:
    """Narrow text from a CSV cell or a combobox; anything unknown is a phrase."""
    return cast(MatchType, value) if value in get_args(MatchType) else "phrase"


# Tokens for phonetic matching. Internal dots and apostrophes keep hostnames and
# contractions whole; trailing punctuation is never part of a word.
WORD = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9'._-]*[A-Za-z0-9])?")

# A phonetic rule fires on a Metaphone code, not on spelling, so it catches the
# variants a recognizer invents. Short codes are far too eager: "Claude" is KLT,
# and so are cloud and clod. Every false positive found while testing had a code
# of four symbols or fewer; every code of five or more was distinctive.
MIN_PHONETIC_CODE = 5

# The longest span of tokens a phonetic rule will try to match: "threat fax" is
# two, "Wispr Flow" is two, and nothing useful was longer.
MAX_PHONETIC_SPAN = 3

# Store structured glossary rules in a JSON file alongside other app data
GLOSSARY_FILE = Path.home() / ".whisper_dictate/whisper_dictate_glossary.json"

# Per-application vocabulary for the Whisper backend, keyed by process stem
# ("code", "olk"). Written by scripts/mine_wispr_history.py and copied here.
HOTWORDS_BY_APP_FILE = Path.home() / ".whisper_dictate/hotwords_by_app.json"

# Whisper encodes hotwords into its prompt context, where they compete with the
# audio for the decoding budget. Benchmarked over 198 real dictations: 400 chars
# gains the whole domain-term recall improvement at the smallest cost to the word
# error rate, and 800 leaves a long clip no budget at all - faster-whisper then
# raises "The maximum decoding length must be > 0".
# See research/asr-benchmark-2026.md.
HOTWORD_CHAR_BUDGET = 400


@dataclass
class GlossaryRule:
    """A single glossary replacement rule."""

    trigger: str
    replacement: str
    match_type: MatchType = "phrase"
    case_sensitive: bool = False
    word_boundary: bool = True
    description: str | None = None
    _compiled: re.Pattern[str] | None = field(init=False, default=None, repr=False)
    _code: str | None = field(init=False, default=None, repr=False)

    def to_dict(self) -> dict:
        """Serialize the rule to a JSON-friendly dict."""

        return {
            "trigger": self.trigger,
            "replacement": self.replacement,
            "match_type": self.match_type,
            "case_sensitive": self.case_sensitive,
            "word_boundary": self.word_boundary,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GlossaryRule:
        """Create a rule from a persisted dictionary."""

        return cls(
            trigger=data.get("trigger", ""),
            replacement=data.get("replacement", ""),
            match_type=data.get("match_type", "phrase"),
            case_sensitive=bool(data.get("case_sensitive", False)),
            word_boundary=bool(data.get("word_boundary", True)),
            description=data.get("description"),
        )

    def phonetic_code(self) -> str:
        """The Metaphone code this rule matches on, cached."""
        if self._code is None:
            self._code = phonetic_code(self.trigger)
        return self._code

    def compile_pattern(self) -> re.Pattern[str]:
        """Compile and cache a regex pattern for the rule."""

        if self._compiled:
            return self._compiled

        flags = 0 if self.case_sensitive else re.IGNORECASE
        if self.match_type == "regex":
            self._compiled = re.compile(self.trigger, flags)
            return self._compiled

        escaped = re.escape(self.trigger.strip())
        if self.word_boundary:
            pattern = rf"\b{escaped}\b"
        else:
            pattern = escaped

        self._compiled = re.compile(pattern, flags)
        return self._compiled


def phonetic_code(text: str) -> str:
    """Metaphone of the text with spaces removed, so "threat fax" codes as one
    word and matches the recognizer's "threatfax"."""
    from jellyfish import metaphone

    return metaphone("".join(WORD.findall(text or "")))


def phonetic_rejection(trigger: str) -> str | None:
    """Why this trigger cannot be a phonetic rule, or None if it can.

    Returned as a sentence for the dialog to show: refusing without saying which
    ordinary words would collide teaches the user nothing.
    """
    code = phonetic_code(trigger)
    if not code:
        return "There is nothing to sound out in that trigger."
    if len(code) < MIN_PHONETIC_CODE:
        return (
            f"The code `{code}` is too short - it would match far more than you mean. "
            f"Phonetic rules need {MIN_PHONETIC_CODE} symbols or more; use an exact "
            f"rule for this one."
        )
    return None


class GlossaryManager:
    """Manage glossary rules, persistence, and application."""

    def __init__(self, rules: Iterable[GlossaryRule] | None = None):
        self.rules: list[GlossaryRule] = [
            rule
            for rule in (rules or [])
            if rule.trigger.strip()
            and rule.replacement.strip()
            and not (rule.match_type == "phonetic" and phonetic_rejection(rule.trigger))
        ]
        self._sort_rules()

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> GlossaryManager:
        """Load glossary rules from disk.

        JSON is preferred, but we also parse legacy "trigger => replacement" text.
        """

        path = path or GLOSSARY_FILE

        if not path.is_file():
            return cls()

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:  # pragma: no cover
            # OSError: File access errors
            # UnicodeDecodeError: Invalid UTF-8 encoding
            logger.error(f"Could not read saved glossary: {e}")
            return cls()

        content = content.strip()
        if not content:
            return cls()

        # Prefer structured JSON
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return cls(GlossaryRule.from_dict(item) for item in data)
        except json.JSONDecodeError:
            pass

        # Fallback to legacy text format
        return cls(_parse_legacy_rules(content))

    def save(self, path: Path | None = None) -> bool:
        """Persist glossary rules to disk as JSON."""

        path = path or GLOSSARY_FILE

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                [rule.to_dict() for rule in self.rules], indent=2, ensure_ascii=False
            )
            path.write_text(payload, encoding="utf-8")
            return True
        except (OSError, UnicodeEncodeError, TypeError, ValueError) as e:  # pragma: no cover
            # OSError: File/directory write errors
            # UnicodeEncodeError: Invalid character encoding
            # TypeError: Non-serializable values in rules
            # ValueError: Invalid JSON structure
            logger.error(f"Could not save glossary: {e}")
            return False

    # ------------------------------------------------------------------
    # Rule manipulation
    # ------------------------------------------------------------------
    def upsert_rule(self, rule: GlossaryRule) -> None:
        """Add or replace a rule with the same trigger (case-insensitive)."""

        for idx, existing in enumerate(self.rules):
            if existing.trigger.lower() == rule.trigger.lower():
                self.rules[idx] = rule
                self._sort_rules()
                return
        self.rules.append(rule)
        self._sort_rules()

    def remove_rule(self, trigger: str) -> None:
        """Remove a rule by trigger text (case-insensitive)."""

        lowered = trigger.lower()
        self.rules = [rule for rule in self.rules if rule.trigger.lower() != lowered]

    def import_csv(self, csv_text: str) -> None:
        """Import rules from CSV text (trigger,replacement,match_type,case_sensitive,word_boundary)."""

        reader = csv.DictReader(csv_text.splitlines())
        for row in reader:
            trigger = (row.get("trigger") or "").strip()
            replacement = (row.get("replacement") or "").strip()
            if not trigger or not replacement:
                continue
            rule = GlossaryRule(
                trigger=trigger,
                replacement=replacement,
                match_type=as_match_type(row.get("match_type")),
                case_sensitive=str(row.get("case_sensitive", "")).lower() == "true",
                word_boundary=str(row.get("word_boundary", "true")).lower() != "false",
            )
            self.upsert_rule(rule)

    def export_csv(self) -> str:
        """Export rules as CSV text."""

        if not self.rules:
            return ""

        buffer = StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=[
                "trigger",
                "replacement",
                "match_type",
                "case_sensitive",
                "word_boundary",
                "description",
            ],
        )
        writer.writeheader()
        for rule in self.rules:
            writer.writerow(
                {
                    "trigger": rule.trigger,
                    "replacement": rule.replacement,
                    "match_type": rule.match_type,
                    "case_sensitive": str(rule.case_sensitive).lower(),
                    "word_boundary": str(rule.word_boundary).lower(),
                    "description": rule.description or "",
                }
            )
        return buffer.getvalue().strip()

    def _sort_rules(self) -> None:
        """Prioritize longer triggers first to avoid partial matches."""

        self.rules.sort(key=lambda r: (-len(r.trigger.split()), -len(r.trigger)))
        for rule in self.rules:
            rule._compiled = None
            rule._code = None

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    def apply(self, text: str) -> str:
        """Apply glossary replacements to text.

        Exact rules run first: where spelling already matches, no guessing is
        needed. Phonetic rules then sweep whatever is left.
        """

        if not text or not self.rules:
            return text

        result = text
        for rule in self.rules:
            if rule.match_type == "phonetic":
                continue
            try:
                result = rule.compile_pattern().sub(rule.replacement, result)
            except re.error as e:
                # A hand-edited file can carry a pattern the dialog would have
                # refused, or a replacement with a group reference that has no
                # group. One rule is not worth the dictation.
                logger.warning(f"Skipping glossary rule {rule.trigger!r}: {e}")
        return self._apply_phonetic(result)

    def _apply_phonetic(self, text: str) -> str:
        """Replace spans that sound like a phonetic rule's trigger.

        ponytail: single Metaphone code, exact equality. "Trey Fax" (TRFKS) will
        not match threatfax (0RTFKS); add an exact rule for such variants rather
        than loosening the match.
        """
        by_code: dict[str, GlossaryRule] = {}
        for rule in self.rules:
            if rule.match_type == "phonetic":
                by_code.setdefault(rule.phonetic_code(), rule)
        if not by_code:
            return text

        spans = [(m.start(), m.end(), m.group()) for m in WORD.finditer(text)]
        out: list[str] = []
        cursor = index = 0
        while index < len(spans):
            for width in range(min(MAX_PHONETIC_SPAN, len(spans) - index), 0, -1):
                window = spans[index : index + width]
                code = phonetic_code("".join(w[2] for w in window))
                matched: GlossaryRule | None = (
                    by_code.get(code) if len(code) >= MIN_PHONETIC_CODE else None
                )
                if matched is None:
                    continue
                out.append(text[cursor : window[0][0]])
                out.append(matched.replacement)
                cursor = window[-1][1]
                index += width
                break
            else:
                index += 1
        out.append(text[cursor:])
        return "".join(out)

    def format_for_prompt(self) -> str:
        """Render a concise prompt block describing the glossary rules."""

        lines: list[str] = []
        for rule in self.rules:
            options: list[str] = []
            if rule.match_type != "phrase":
                options.append(f"match={rule.match_type}")
            if rule.case_sensitive:
                options.append("case-sensitive")
            if not rule.word_boundary:
                options.append("partial-ok")
            suffix = f" ({', '.join(options)})" if options else ""
            lines.append(f"{rule.trigger} → {rule.replacement}{suffix}")

        return "\n".join(lines)


# ----------------------------------------------------------------------
# Backwards-compatible helpers for existing UI/tests
# ----------------------------------------------------------------------
def budget(terms: Iterable[str], chars: int = HOTWORD_CHAR_BUDGET) -> list[str]:
    """Trim a ranked term list to what Whisper's prompt context will hold."""
    out: list[str] = []
    used = 0
    for term in terms:
        term = term.strip()
        if not term or term in out:
            continue
        if used + len(term) + 2 > chars:
            break
        out.append(term)
        used += len(term) + 2
    return out


def load_hotwords_by_app(path: Path | None = None) -> dict[str, list[str]]:
    """Read the per-application vocabulary, or an empty map if there is none."""
    path = path or HOTWORDS_BY_APP_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(app).lower(): [str(t) for t in terms if str(t).strip()]
        for app, terms in data.items()
        if isinstance(terms, list)
    }


def hotwords_for_app(
    process_name: str | None,
    by_app: dict[str, list[str]],
    manager: GlossaryManager | None = None,
    chars: int = HOTWORD_CHAR_BUDGET,
) -> str | None:
    """Vocabulary to bias the recognizer towards in this application.

    Per-app only, deliberately. Benchmarked globally, hotwords cost about 16
    extra word errors for each domain term they rescue, and 57% of dictations
    contain no domain term at all - so they are applied only where the
    vocabulary actually occurs. An app with no entry gets nothing.
    """
    if not process_name:
        return None
    stem = Path(process_name).stem.lower()
    terms = by_app.get(stem) or by_app.get(process_name.lower())
    if not terms:
        return None
    # What the glossary would rewrite the text to is worth teaching the
    # recognizer directly; getting it right first is better than patching it.
    if manager:
        terms = list(terms) + [rule.replacement for rule in manager.rules]
    trimmed = budget(terms, chars)
    return ", ".join(trimmed) if trimmed else None


def load_glossary_manager() -> GlossaryManager:
    """Load the glossary manager from disk."""

    return GlossaryManager.load()


def apply_glossary(text: str, manager: GlossaryManager | None) -> str:
    """Apply glossary normalization when a manager is present."""

    if manager is None:
        return text
    return manager.apply(text)


# ----------------------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------------------
def _parse_legacy_rules(text: str) -> list[GlossaryRule]:
    """Parse simple `trigger => replacement` lines into rules."""

    rules: list[GlossaryRule] = []
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        if "=>" in cleaned:
            trigger, replacement = cleaned.split("=>", 1)
        elif "=" in cleaned:
            trigger, replacement = cleaned.split("=", 1)
        else:
            continue
        trigger = trigger.strip()
        replacement = replacement.strip()
        if trigger and replacement:
            rules.append(GlossaryRule(trigger=trigger, replacement=replacement))
    return rules
