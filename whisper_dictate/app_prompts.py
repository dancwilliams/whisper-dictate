"""Helpers for application-specific prompts."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any

from whisper_dictate.app_context import ActiveContext
from whisper_dictate.s1 import CONTEXT, STRUCTURE, STYLING

logger = logging.getLogger(__name__)

AppPromptRule = dict[str, str]
AppPromptMap = dict[str, list[AppPromptRule]]

# A rule may set the S1-mini control line as well as, or instead of, a prompt:
# Outlook wants email shape, a terminal does not. Only values the model was
# trained on are kept; anything else is dropped rather than silently sent.
STYLE_KEYS = {"styling": STYLING, "structure": STRUCTURE, "context": CONTEXT}


def normalize_app_prompts(data: Any) -> AppPromptMap:
    """Normalize raw settings data into a consistent app prompt map."""

    def _rule_from_value(value: Any) -> AppPromptRule | None:
        if isinstance(value, str) and value.strip():
            return {"prompt": value}
        if not isinstance(value, dict):
            return None

        rule: AppPromptRule = {}
        prompt = value.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            rule["prompt"] = prompt
        for key, allowed in STYLE_KEYS.items():
            setting = value.get(key)
            if isinstance(setting, str) and setting in allowed:
                rule[key] = setting
        if not rule:
            return None

        window_regex = value.get("window_title_regex", "")
        if isinstance(window_regex, str) and window_regex.strip():
            rule["window_title_regex"] = window_regex
        return rule

    normalized: AppPromptMap = {}
    if not isinstance(data, dict):
        return normalized

    for process, rules in data.items():
        if not isinstance(process, str):
            continue
        process_rules: list[AppPromptRule] = []

        if isinstance(rules, list):
            for item in rules:
                rule = _rule_from_value(item)
                if rule:
                    process_rules.append(rule)
        else:
            rule = _rule_from_value(rules)
            if rule:
                process_rules.append(rule)

        if process_rules:
            normalized[process] = process_rules

    return normalized


def rules_to_entries(app_prompts: AppPromptMap) -> list[dict[str, str]]:
    """Flatten app prompt rules into an editable list for dialogs."""

    entries: list[dict[str, str]] = []
    for process, rules in app_prompts.items():
        for rule in rules:
            entry = {
                "process_name": process,
                "window_title_regex": rule.get("window_title_regex", ""),
                "prompt": rule.get("prompt", ""),
            }
            for key in STYLE_KEYS:
                entry[key] = rule.get(key, "")
            entries.append(entry)
    return entries


def entries_to_rules(entries: list[dict[str, str]]) -> AppPromptMap:
    """Convert dialog entries back into the persisted rule mapping."""

    rules: AppPromptMap = {}
    for entry in entries:
        process = entry.get("process_name", "").strip()
        prompt = entry.get("prompt", "").strip()
        styles = {
            key: entry.get(key, "").strip()
            for key in STYLE_KEYS
            if entry.get(key, "").strip() in STYLE_KEYS[key]
        }
        # A rule that only sets the control line is worth keeping: "email shape
        # in Outlook" needs no prompt at all.
        if not process or not (prompt or styles):
            continue
        rule: AppPromptRule = {"prompt": prompt} if prompt else {}
        rule.update(styles)
        regex = entry.get("window_title_regex", "").strip()
        if regex:
            rule["window_title_regex"] = regex
        rules.setdefault(process, []).append(rule)
    return rules


def _title_matches(pattern: str, title: str) -> bool:
    """Match a saved window-title pattern against the active window's title.

    The pattern is checked when the rule is saved. A settings file edited by
    hand can still carry one that will not compile, and that must cost this
    rule, not the dictation.

    ponytail: no time limit on the match. Pattern and title are both the user's
    own, on their own machine, and a window title is short; the worst a
    pathological pattern costs is a fraction of a second of their own CPU.
    Add a limit only if a trace ever shows one that matters.
    """
    try:
        return re.search(pattern, title, re.IGNORECASE) is not None
    except re.error as e:
        logger.warning(f"Skipping invalid window-title regex {pattern!r}: {e}")
        return False


def resolve_app_prompt(app_prompts: AppPromptMap, context: ActiveContext | None) -> str | None:
    """Return the best-matching prompt for the given active context."""

    if context is None or not context.process_name:
        return None

    rules = app_prompts.get(context.process_name)
    if not rules:
        return None

    window_title = context.window_title or ""
    default_prompt: str | None = None

    for rule in rules:
        prompt = rule.get("prompt")
        if not prompt:
            continue

        regex = rule.get("window_title_regex")
        if regex and window_title:
            if _title_matches(regex, window_title):
                return prompt

        if not regex and default_prompt is None:
            default_prompt = prompt

    return default_prompt


def resolve_app_style(app_prompts: AppPromptMap, context: ActiveContext | None) -> dict[str, str]:
    """Return the S1-mini control-line settings for the active context.

    Mirrors resolve_app_prompt's matching order - a window-title match beats the
    process-wide rule - and returns only the keys the matching rule actually
    sets, so the caller's defaults fill the rest.
    """
    if context is None or not context.process_name:
        return {}

    rules = app_prompts.get(context.process_name)
    if not rules:
        return {}

    window_title = context.window_title or ""
    fallback: dict[str, str] = {}

    for rule in rules:
        styles = {key: rule[key] for key in STYLE_KEYS if key in rule}
        if not styles:
            continue

        regex = rule.get("window_title_regex")
        if regex and window_title:
            if _title_matches(regex, window_title):
                return styles

        if not regex and not fallback:
            fallback = styles

    return fallback


def clone_rules(app_prompts: AppPromptMap) -> AppPromptMap:
    """Return a deep copy of app prompt rules for safe editing."""

    return deepcopy(app_prompts)
