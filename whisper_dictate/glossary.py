"""Glossary management, persistence, and application logic."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Literal

MatchType = Literal["word", "phrase", "regex"]

# Store structured glossary rules in a JSON file alongside other app data
GLOSSARY_FILE = Path.home() / ".whisper_dictate/whisper_dictate_glossary.json"


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


class GlossaryManager:
    """Manage glossary rules, persistence, and application."""

    def __init__(self, rules: Iterable[GlossaryRule] | None = None):
        self.rules: list[GlossaryRule] = [
            rule for rule in (rules or []) if rule.trigger.strip() and rule.replacement.strip()
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
            print(f"(Glossary) Could not read saved glossary: {e}")
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
            print(f"(Glossary) Could not save glossary: {e}")
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
                match_type=row.get("match_type") or "phrase",
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

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    def apply(self, text: str) -> str:
        """Apply glossary replacements to text."""

        if not text or not self.rules:
            return text

        result = text
        for rule in self.rules:
            pattern = rule.compile_pattern()
            result = pattern.sub(rule.replacement, result)
        return result

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

    def to_legacy_text(self) -> str:
        """Represent rules in the simple `trigger => replacement` format."""

        return "\n".join(f"{r.trigger} => {r.replacement}" for r in self.rules)


# ----------------------------------------------------------------------
# Backwards-compatible helpers for existing UI/tests
# ----------------------------------------------------------------------
def load_saved_glossary(default: str = "") -> str:
    """Return glossary as legacy text for the editor."""

    manager = GlossaryManager.load()
    text = manager.to_legacy_text().strip()
    return text if text else default


def load_glossary_manager() -> GlossaryManager:
    """Load the glossary manager from disk."""

    return GlossaryManager.load()


def write_saved_glossary(glossary_text: str) -> bool:
    """Persist glossary text (legacy format) as structured JSON."""

    rules = _parse_legacy_rules(glossary_text)
    manager = GlossaryManager(rules)
    return manager.save()


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
