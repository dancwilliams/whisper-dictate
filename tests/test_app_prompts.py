"""Tests for per-application prompt resolution."""

import re

import pytest

from whisper_dictate import app_context, app_prompts
from whisper_dictate.app_context import ActiveContext


def _make_context(process: str | None, window: str | None) -> ActiveContext:
    return ActiveContext(window_title=window, process_name=process, cursor_position=None)


def test_resolve_app_prompt_prefers_window_specific_rule():
    prompts = {
        "notepad.exe": [
            {"window_title_regex": "todo", "prompt": "Todo prompt"},
            {"prompt": "Default notepad prompt"},
        ]
    }
    ctx = _make_context("notepad.exe", "My TODO list")

    result = app_prompts.resolve_app_prompt(prompts, ctx)

    assert result == "Todo prompt"


def test_resolve_app_prompt_falls_back_to_process_default():
    prompts = {"word.exe": [{"prompt": "Word prompt"}]}
    ctx = _make_context("word.exe", "Document1 - Word")

    result = app_prompts.resolve_app_prompt(prompts, ctx)

    assert result == "Word prompt"


def test_resolve_app_prompt_returns_none_when_no_match():
    prompts = {"excel.exe": [{"prompt": "Excel prompt"}]}
    ctx = _make_context("notepad.exe", "Untitled - Notepad")

    result = app_prompts.resolve_app_prompt(prompts, ctx)

    assert result is None


def test_resolve_app_prompt_handles_missing_context():
    prompts = {"notepad.exe": [{"prompt": "Default"}]}

    result = app_prompts.resolve_app_prompt(prompts, None)

    assert result is None


def test_resolve_app_prompt_ignores_invalid_regex():
    prompts = {
        "edge.exe": [
            {"window_title_regex": "[", "prompt": "Broken"},
            {"prompt": "Fallback"},
        ]
    }
    ctx = _make_context("edge.exe", "Welcome")

    result = app_prompts.resolve_app_prompt(prompts, ctx)

    assert result == "Fallback"


class TestNormalizeAppPrompts:
    """Test normalization of app prompt data."""

    def test_normalize_string_prompt(self):
        """Test normalizing a simple string prompt."""
        data = {"notepad.exe": "Simple prompt"}
        result = app_prompts.normalize_app_prompts(data)

        assert result == {"notepad.exe": [{"prompt": "Simple prompt"}]}

    def test_normalize_dict_prompt(self):
        """Test normalizing a dict prompt with window regex."""
        data = {
            "code.exe": {
                "prompt": "Code prompt",
                "window_title_regex": ".*\\.py",
            }
        }
        result = app_prompts.normalize_app_prompts(data)

        assert result == {
            "code.exe": [
                {
                    "prompt": "Code prompt",
                    "window_title_regex": ".*\\.py",
                }
            ]
        }

    def test_normalize_list_of_prompts(self):
        """Test normalizing a list of prompts."""
        data = {
            "browser.exe": [
                "Default browser prompt",
                {"prompt": "Specific prompt", "window_title_regex": "Gmail"},
            ]
        }
        result = app_prompts.normalize_app_prompts(data)

        assert result == {
            "browser.exe": [
                {"prompt": "Default browser prompt"},
                {
                    "prompt": "Specific prompt",
                    "window_title_regex": "Gmail",
                },
            ]
        }

    def test_normalize_skips_empty_prompts(self):
        """Test that empty or whitespace-only prompts are skipped."""
        data = {
            "app.exe": ["", "  ", "Valid prompt"],
        }
        result = app_prompts.normalize_app_prompts(data)

        assert result == {"app.exe": [{"prompt": "Valid prompt"}]}

    def test_normalize_skips_invalid_data(self):
        """Test that invalid data structures are skipped."""
        data = {
            "app1.exe": 123,  # Not a string, dict, or list
            "app2.exe": [None, {"no_prompt_key": "value"}],
            123: "Invalid process name",  # Non-string key
        }
        result = app_prompts.normalize_app_prompts(data)

        assert result == {}

    def test_normalize_preserves_window_regex_with_whitespace(self):
        """Test that window title regex preserves original formatting."""
        data = {
            "app.exe": {
                "prompt": "Test",
                "window_title_regex": "  regex  ",
            }
        }
        result = app_prompts.normalize_app_prompts(data)

        # The function checks if regex.strip() is truthy but doesn't strip it
        assert result == {
            "app.exe": [
                {
                    "prompt": "Test",
                    "window_title_regex": "  regex  ",
                }
            ]
        }

    def test_normalize_empty_window_regex_not_included(self):
        """Test that empty window regex is not included in output."""
        data = {
            "app.exe": {
                "prompt": "Test",
                "window_title_regex": "",
            }
        }
        result = app_prompts.normalize_app_prompts(data)

        assert result == {"app.exe": [{"prompt": "Test"}]}

    def test_normalize_non_dict_input(self):
        """Test that non-dict input returns empty map."""
        assert app_prompts.normalize_app_prompts(None) == {}
        assert app_prompts.normalize_app_prompts([]) == {}
        assert app_prompts.normalize_app_prompts("string") == {}


class TestRulesToEntries:
    """Test conversion from rules to entries."""

    def test_rules_to_entries_basic(self):
        """Test basic conversion of rules to entries."""
        rules = {
            "notepad.exe": [{"prompt": "Notepad prompt"}],
            "code.exe": [{"prompt": "Code prompt", "window_title_regex": ".*\\.py"}],
        }
        result = app_prompts.rules_to_entries(rules)

        assert len(result) == 2
        assert {
            "process_name": "notepad.exe",
            "window_title_regex": "",
            "prompt": "Notepad prompt",
        } in result
        assert {
            "process_name": "code.exe",
            "window_title_regex": ".*\\.py",
            "prompt": "Code prompt",
        } in result

    def test_rules_to_entries_multiple_rules_per_process(self):
        """Test conversion with multiple rules for same process."""
        rules = {
            "browser.exe": [
                {"prompt": "Default"},
                {"prompt": "Gmail", "window_title_regex": "Gmail"},
            ]
        }
        result = app_prompts.rules_to_entries(rules)

        assert len(result) == 2
        assert result[0]["process_name"] == "browser.exe"
        assert result[1]["process_name"] == "browser.exe"

    def test_rules_to_entries_empty_map(self):
        """Test conversion of empty rules map."""
        assert app_prompts.rules_to_entries({}) == []


class TestEntriesToRules:
    """Test conversion from entries to rules."""

    def test_entries_to_rules_basic(self):
        """Test basic conversion of entries to rules."""
        entries = [
            {
                "process_name": "notepad.exe",
                "window_title_regex": "",
                "prompt": "Notepad prompt",
            },
            {
                "process_name": "code.exe",
                "window_title_regex": ".*\\.py",
                "prompt": "Code prompt",
            },
        ]
        result = app_prompts.entries_to_rules(entries)

        assert result == {
            "notepad.exe": [{"prompt": "Notepad prompt"}],
            "code.exe": [{"prompt": "Code prompt", "window_title_regex": ".*\\.py"}],
        }

    def test_entries_to_rules_groups_by_process(self):
        """Test that entries for same process are grouped."""
        entries = [
            {"process_name": "app.exe", "window_title_regex": "", "prompt": "Prompt 1"},
            {"process_name": "app.exe", "window_title_regex": "test", "prompt": "Prompt 2"},
        ]
        result = app_prompts.entries_to_rules(entries)

        assert len(result["app.exe"]) == 2
        assert {"prompt": "Prompt 1"} in result["app.exe"]
        assert {"prompt": "Prompt 2", "window_title_regex": "test"} in result["app.exe"]

    def test_entries_to_rules_skips_invalid_entries(self):
        """Test that invalid entries are skipped."""
        entries = [
            {"process_name": "", "prompt": "No process"},
            {"process_name": "app.exe", "prompt": ""},
            {"process_name": "  ", "prompt": "  "},
            {"process_name": "valid.exe", "prompt": "Valid"},
        ]
        result = app_prompts.entries_to_rules(entries)

        assert result == {"valid.exe": [{"prompt": "Valid"}]}

    def test_entries_to_rules_strips_whitespace(self):
        """Test that whitespace is stripped from entries."""
        entries = [
            {
                "process_name": "  app.exe  ",
                "window_title_regex": "  regex  ",
                "prompt": "  prompt  ",
            }
        ]
        result = app_prompts.entries_to_rules(entries)

        assert result == {"app.exe": [{"prompt": "prompt", "window_title_regex": "regex"}]}

    def test_entries_to_rules_empty_list(self):
        """Test conversion of empty entries list."""
        assert app_prompts.entries_to_rules([]) == {}


class TestCloneRules:
    """Test deep cloning of app prompt rules."""

    def test_clone_rules_creates_independent_copy(self):
        """Test that cloned rules are independent."""
        original = {
            "app.exe": [{"prompt": "Original", "window_title_regex": "test"}]
        }
        cloned = app_prompts.clone_rules(original)

        # Modify cloned
        cloned["app.exe"][0]["prompt"] = "Modified"
        cloned["new.exe"] = [{"prompt": "New"}]

        # Original should be unchanged
        assert original["app.exe"][0]["prompt"] == "Original"
        assert "new.exe" not in original

    def test_clone_rules_empty_map(self):
        """Test cloning empty rules map."""
        original = {}
        cloned = app_prompts.clone_rules(original)

        assert cloned == {}
        assert cloned is not original


class TestRegexValidation:
    """Test regex pattern validation for ReDoS protection."""

    def test_validate_regex_pattern_valid(self):
        """Test validation of safe regex patterns."""
        # Should not raise
        app_prompts.validate_regex_pattern("simple")
        app_prompts.validate_regex_pattern(".*\\.txt")
        app_prompts.validate_regex_pattern("(group)")
        app_prompts.validate_regex_pattern("[a-z]+")

    def test_validate_regex_pattern_too_long(self):
        """Test rejection of overly long patterns."""
        long_pattern = "a" * (app_prompts.MAX_REGEX_LENGTH + 1)

        with pytest.raises(
            app_prompts.RegexValidationError, match="Regex pattern too long"
        ):
            app_prompts.validate_regex_pattern(long_pattern)

    def test_validate_regex_pattern_nested_repetitions(self):
        """Test rejection of patterns with excessive nested repetitions."""
        # Pattern with catastrophic backtracking: (a+)+
        dangerous_pattern = "(a+)+"

        with pytest.raises(
            app_prompts.RegexValidationError, match="too many nested repetitions"
        ):
            app_prompts.validate_regex_pattern(dangerous_pattern)

    def test_validate_regex_pattern_deeply_nested(self):
        """Test rejection of deeply nested repetition patterns."""
        # Pattern with 4 levels of nesting: ((((a)*)*)*)*
        dangerous_pattern = "((((a)*)*)*)*"

        with pytest.raises(
            app_prompts.RegexValidationError, match="too many nested repetitions"
        ):
            app_prompts.validate_regex_pattern(dangerous_pattern)

    def test_validate_regex_pattern_invalid_syntax(self):
        """Test rejection of syntactically invalid patterns."""
        with pytest.raises(re.error):
            app_prompts.validate_regex_pattern("(unclosed")

        with pytest.raises(re.error):
            app_prompts.validate_regex_pattern("[invalid")


class TestSafeRegexSearch:
    """Test safe regex searching with timeout protection."""

    def test_safe_regex_search_match(self):
        """Test safe regex search with matching pattern."""
        assert app_prompts.safe_regex_search("hello", "hello world") is True
        assert app_prompts.safe_regex_search("HELLO", "hello world") is True  # Case insensitive
        assert app_prompts.safe_regex_search(".*world", "hello world") is True

    def test_safe_regex_search_no_match(self):
        """Test safe regex search with non-matching pattern."""
        assert app_prompts.safe_regex_search("goodbye", "hello world") is False
        assert app_prompts.safe_regex_search("^world", "hello world") is False

    def test_safe_regex_search_invalid_pattern(self):
        """Test safe regex search with invalid pattern returns False."""
        # Pattern too long
        long_pattern = "a" * (app_prompts.MAX_REGEX_LENGTH + 1)
        assert app_prompts.safe_regex_search(long_pattern, "text") is False

        # Nested repetitions
        assert app_prompts.safe_regex_search("(a+)+", "aaaa") is False

        # Invalid syntax
        assert app_prompts.safe_regex_search("(unclosed", "text") is False

    def test_safe_regex_search_timeout(self):
        """Test safe regex search with pattern that would cause ReDoS."""
        # This pattern can cause catastrophic backtracking
        # (a+)+ with input like "aaaaaaaaaaaaaaaaaaaaaaaaaX"
        dangerous_pattern = "(a+)+"
        dangerous_input = "a" * 25 + "X"

        # Should return False due to validation, not timeout
        # (pattern is blocked before timeout can occur)
        assert app_prompts.safe_regex_search(dangerous_pattern, dangerous_input) is False


class TestResolveAppPromptWithSafeRegex:
    """Test that resolve_app_prompt uses safe regex matching."""

    def test_resolve_app_prompt_with_dangerous_regex(self):
        """Test that dangerous regex patterns don't cause DoS."""
        rules = {
            "notepad.exe": [
                {
                    "prompt": "Dangerous",
                    "window_title_regex": "(a+)+",  # Would cause ReDoS
                }
            ]
        }

        context = app_context.ActiveContext(
            process_name="notepad.exe",
            window_title="a" * 25 + "X",  # Input that triggers catastrophic backtracking
            cursor_position=None,
        )

        # Should return None quickly (pattern blocked), not hang
        result = app_prompts.resolve_app_prompt(rules, context)
        assert result is None  # Pattern validation fails, no match

    def test_resolve_app_prompt_with_long_regex(self):
        """Test that overly long regex patterns are rejected."""
        long_pattern = "a" * (app_prompts.MAX_REGEX_LENGTH + 1)
        rules = {
            "notepad.exe": [
                {
                    "prompt": "Long pattern",
                    "window_title_regex": long_pattern,
                }
            ]
        }

        context = app_context.ActiveContext(
            process_name="notepad.exe", window_title="test", cursor_position=None
        )

        # Should return None (pattern validation fails)
        result = app_prompts.resolve_app_prompt(rules, context)
        assert result is None
