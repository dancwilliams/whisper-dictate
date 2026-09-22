"""Tests for per-application prompt resolution."""

from whisper_dictate import app_prompts
from whisper_dictate.app_context import ActiveContext


def _make_context(process: str | None, window: str | None) -> ActiveContext:
    return ActiveContext(window_title=window, process_name=process)


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
        # Entries also carry the S1 control-line keys, empty when unset.
        trimmed = [
            {k: e[k] for k in ("process_name", "window_title_regex", "prompt")} for e in result
        ]
        assert {
            "process_name": "notepad.exe",
            "window_title_regex": "",
            "prompt": "Notepad prompt",
        } in trimmed
        assert {
            "process_name": "code.exe",
            "window_title_regex": ".*\\.py",
            "prompt": "Code prompt",
        } in trimmed
        assert all(e["styling"] == "" and e["context"] == "" for e in result)

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
        original = {"app.exe": [{"prompt": "Original", "window_title_regex": "test"}]}
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


class TestWindowTitlePatterns:
    """A saved pattern is the user's own; a bad one costs its rule, not the dictation."""

    def test_invalid_pattern_skips_the_rule(self, caplog):
        rules = {"notepad.exe": [{"prompt": "P", "window_title_regex": "(unclosed"}]}
        ctx = _make_context("notepad.exe", "anything")

        assert app_prompts.resolve_app_prompt(rules, ctx) is None
        assert "Skipping invalid window-title regex '(unclosed'" in caplog.text

    def test_invalid_pattern_falls_through_to_the_process_rule(self):
        rules = {
            "notepad.exe": [
                {"prompt": "Broken", "window_title_regex": "(unclosed"},
                {"prompt": "Default"},
            ]
        }
        ctx = _make_context("notepad.exe", "anything")

        assert app_prompts.resolve_app_prompt(rules, ctx) == "Default"

    def test_invalid_pattern_skips_the_style_rule(self, caplog):
        rules = {"notepad.exe": [{"styling": "formal", "window_title_regex": "(unclosed"}]}
        ctx = _make_context("notepad.exe", "anything")

        assert app_prompts.resolve_app_style(rules, ctx) == {}
        assert "Skipping invalid window-title regex" in caplog.text

    def test_an_optional_group_with_a_quantifier_inside_is_legitimate(self):
        """The nesting heuristic this replaced refused this: a `+` inside a `?` group."""
        rules = {"winword.exe": [{"prompt": "P", "window_title_regex": r"(\w+ )?Report - Word"}]}
        ctx = _make_context("winword.exe", "Quarterly Report - Word")

        assert app_prompts.resolve_app_prompt(rules, ctx) == "P"

    def test_matching_is_case_insensitive(self):
        rules = {"notepad.exe": [{"prompt": "P", "window_title_regex": "todo"}]}

        assert app_prompts.resolve_app_prompt(rules, _make_context("notepad.exe", "My TODO")) == "P"


class TestPerAppStyle:
    """The S1-mini control line, resolved per application."""

    def _context(self, process, title=None):
        return ActiveContext(process_name=process, window_title=title)

    def test_style_keys_survive_normalize(self):
        rules = app_prompts.normalize_app_prompts(
            {"olk.exe": {"prompt": "", "styling": "semi-formal", "context": "email"}}
        )
        # An empty prompt is not a rule; the control line alone is.
        assert rules["olk.exe"] == [{"styling": "semi-formal", "context": "email"}]

    def test_invalid_style_values_are_dropped(self):
        """A setting the model was never trained on must not reach the prompt."""
        rules = app_prompts.normalize_app_prompts(
            {"olk.exe": [{"prompt": "p", "styling": "shouty", "structure": "lists"}]}
        )
        assert rules["olk.exe"] == [{"prompt": "p", "structure": "lists"}]

    def test_a_rule_with_only_styles_is_kept(self):
        """ "Email shape in Outlook" needs no prompt at all."""
        entries = [
            {
                "process_name": "olk.exe",
                "window_title_regex": "",
                "prompt": "",
                "styling": "semi-formal",
                "structure": "prose",
                "context": "email",
            }
        ]
        assert app_prompts.entries_to_rules(entries) == {
            "olk.exe": [{"styling": "semi-formal", "structure": "prose", "context": "email"}]
        }

    def test_an_entry_with_neither_prompt_nor_style_is_dropped(self):
        entries = [{"process_name": "olk.exe", "window_title_regex": "", "prompt": ""}]
        assert app_prompts.entries_to_rules(entries) == {}

    def test_round_trip_through_entries(self):
        rules = {"olk.exe": [{"prompt": "p", "styling": "formal", "context": "email"}]}
        assert app_prompts.entries_to_rules(app_prompts.rules_to_entries(rules)) == rules

    def test_resolve_returns_only_the_keys_the_rule_sets(self):
        rules = {"olk.exe": [{"context": "email"}]}
        assert app_prompts.resolve_app_style(rules, self._context("olk.exe")) == {
            "context": "email"
        }

    def test_window_title_match_beats_the_process_wide_rule(self):
        rules = {
            "code.exe": [
                {"styling": "casual"},
                {"window_title_regex": r".*\.md", "styling": "formal"},
            ]
        }
        assert app_prompts.resolve_app_style(rules, self._context("code.exe", "notes.md")) == {
            "styling": "formal"
        }
        assert app_prompts.resolve_app_style(rules, self._context("code.exe", "main.py")) == {
            "styling": "casual"
        }

    def test_unknown_process_gets_nothing(self):
        rules = {"olk.exe": [{"context": "email"}]}
        assert app_prompts.resolve_app_style(rules, self._context("notepad.exe")) == {}

    def test_no_context_gets_nothing(self):
        assert app_prompts.resolve_app_style({"olk.exe": [{"context": "email"}]}, None) == {}

    def test_prompt_only_rules_contribute_no_style(self):
        rules = {"notepad.exe": [{"prompt": "just a prompt"}]}
        assert app_prompts.resolve_app_style(rules, self._context("notepad.exe")) == {}
