"""Helpers for application-specific prompts."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional

from whisper_dictate.app_context import ActiveContext

AppPromptRule = Dict[str, str]
AppPromptMap = Dict[str, List[AppPromptRule]]


def normalize_app_prompts(data: Any) -> AppPromptMap:
    """Normalize raw settings data into a consistent app prompt map."""

    def _rule_from_value(value: Any) -> Optional[AppPromptRule]:
        if isinstance(value, str) and value.strip():
            return {"prompt": value}
        if isinstance(value, dict) and isinstance(value.get("prompt"), str):
            rule: AppPromptRule = {"prompt": value["prompt"]}
            window_regex = value.get("window_title_regex", "")
            if isinstance(window_regex, str) and window_regex.strip():
                rule["window_title_regex"] = window_regex
            return rule
        return None

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
            entries.append(
                {
                    "process_name": process,
                    "window_title_regex": rule.get("window_title_regex", ""),
                    "prompt": rule.get("prompt", ""),
                }
            )
    return entries


def entries_to_rules(entries: list[dict[str, str]]) -> AppPromptMap:
    """Convert dialog entries back into the persisted rule mapping."""

    rules: AppPromptMap = {}
    for entry in entries:
        process = entry.get("process_name", "").strip()
        prompt = entry.get("prompt", "").strip()
        if not process or not prompt:
            continue
        rule: AppPromptRule = {"prompt": prompt}
        regex = entry.get("window_title_regex", "").strip()
        if regex:
            rule["window_title_regex"] = regex
        rules.setdefault(process, []).append(rule)
    return rules


def resolve_app_prompt(app_prompts: AppPromptMap, context: Optional[ActiveContext]) -> Optional[str]:
    """Return the best-matching prompt for the given active context."""

    if context is None or not context.process_name:
        return None

    rules = app_prompts.get(context.process_name)
    if not rules:
        return None

    window_title = context.window_title or ""
    default_prompt: Optional[str] = None

    for rule in rules:
        prompt = rule.get("prompt")
        if not prompt:
            continue

        regex = rule.get("window_title_regex")
        if regex and window_title:
            try:
                if re.search(regex, window_title, re.IGNORECASE):
                    return prompt
            except re.error:
                # Ignore invalid regex patterns
                continue

        if not regex and default_prompt is None:
            default_prompt = prompt

    return default_prompt


def clone_rules(app_prompts: AppPromptMap) -> AppPromptMap:
    """Return a deep copy of app prompt rules for safe editing."""

    return deepcopy(app_prompts)
