"""Helpers for application-specific prompts."""

from __future__ import annotations

import logging
import re
import threading
from copy import deepcopy
from typing import Any

from whisper_dictate.app_context import ActiveContext

logger = logging.getLogger(__name__)

AppPromptRule = dict[str, str]
AppPromptMap = dict[str, list[AppPromptRule]]

# ReDoS protection limits
MAX_REGEX_LENGTH = 500  # Maximum characters in regex pattern
MAX_REPETITION_DEPTH = 1  # Maximum nested repetitions (0=none, 1=(a+)+)
REGEX_TIMEOUT_SECONDS = 0.5  # Maximum time for regex matching


class RegexValidationError(Exception):
    """Raised when a regex pattern is potentially dangerous."""

    pass


def normalize_app_prompts(data: Any) -> AppPromptMap:
    """Normalize raw settings data into a consistent app prompt map."""

    def _rule_from_value(value: Any) -> AppPromptRule | None:
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


def validate_regex_pattern(pattern: str) -> None:
    """Validate a regex pattern to prevent ReDoS attacks.

    Args:
        pattern: The regex pattern to validate

    Raises:
        RegexValidationError: If pattern is potentially dangerous
        re.error: If pattern has invalid syntax
    """
    # Check length
    if len(pattern) > MAX_REGEX_LENGTH:
        raise RegexValidationError(
            f"Regex pattern too long ({len(pattern)} > {MAX_REGEX_LENGTH} chars)"
        )

    # Check for excessive nesting of repetition operators
    # Patterns like (a+)+ or (a*)* can cause catastrophic backtracking
    # We track nesting depth of groups that contain repetitions
    group_stack = []  # Stack of (has_repetition_inside, has_repetition_after)
    max_nested_reps = 0

    i = 0
    while i < len(pattern):
        char = pattern[i]

        if char == "(":
            if i + 1 < len(pattern) and pattern[i + 1] != "?":
                # Start of capturing group
                group_stack.append([False, False])  # [has_rep_inside, has_rep_after]

        elif char == ")":
            if group_stack:
                has_rep_inside, _ = group_stack.pop()
                # Check if this group is followed by a repetition
                if i + 1 < len(pattern) and pattern[i + 1] in "*+?{":
                    # This group has a repetition after it
                    if has_rep_inside:
                        # We have (something_with_repetition)+ which is dangerous
                        # Count depth: how many groups with repetitions are we nested in?
                        depth = 1 + sum(1 for g in group_stack if g[0])
                        max_nested_reps = max(max_nested_reps, depth)
                    # Mark parent group as having repetition inside
                    if group_stack:
                        group_stack[-1][0] = True

        elif char in "*+?{":
            # Mark current group as having repetition inside
            if group_stack:
                group_stack[-1][0] = True

        elif char == "\\":
            # Skip escaped characters
            i += 1

        i += 1

    if max_nested_reps >= MAX_REPETITION_DEPTH:
        raise RegexValidationError(
            f"Regex has too many nested repetitions ({max_nested_reps} >= {MAX_REPETITION_DEPTH})"
        )

    # Try to compile to check for syntax errors
    re.compile(pattern)


def safe_regex_search(pattern: str, text: str, timeout: float = REGEX_TIMEOUT_SECONDS) -> bool:
    """Perform regex search with timeout protection against ReDoS.

    Args:
        pattern: The regex pattern to search for
        text: The text to search in
        timeout: Maximum time in seconds for the search

    Returns:
        True if pattern matches, False otherwise

    Note:
        Returns False on timeout or validation errors to fail safe
    """
    try:
        # Validate pattern first
        validate_regex_pattern(pattern)
    except (RegexValidationError, re.error) as e:
        logger.warning(f"Invalid regex pattern '{pattern}': {e}")
        return False

    # Perform match with timeout
    result = [False]  # Use list to avoid closure issues
    exception = [None]  # Capture any exception

    def do_match():
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            result[0] = compiled.search(text) is not None
        except Exception as e:
            exception[0] = e

    thread = threading.Thread(target=do_match, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        # Timeout occurred
        logger.warning(f"Regex '{pattern}' timed out after {timeout}s (potential ReDoS)")
        return False

    if exception[0]:
        logger.warning(f"Regex '{pattern}' raised exception: {exception[0]}")
        return False

    return result[0]


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
            # Use safe regex matching with timeout protection
            if safe_regex_search(regex, window_title):
                return prompt

        if not regex and default_prompt is None:
            default_prompt = prompt

    return default_prompt


def clone_rules(app_prompts: AppPromptMap) -> AppPromptMap:
    """Return a deep copy of app prompt rules for safe editing."""

    return deepcopy(app_prompts)
