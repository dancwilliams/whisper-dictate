"""Tests for glossary management and application."""

from pathlib import Path
from unittest.mock import patch

import pytest

from whisper_dictate import glossary
from whisper_dictate.glossary import (
    GlossaryManager,
    GlossaryRule,
    apply_glossary,
    load_glossary_manager,
    load_saved_glossary,
    write_saved_glossary,
)


class TestGlossaryPersistence:
    """Test glossary loading and saving using structured JSON."""

    def test_load_saved_glossary_json_round_trip(self, tmp_path: Path) -> None:
        rules = [
            GlossaryRule(trigger="valida tech", replacement="ValidaTek"),
            GlossaryRule(
                trigger="uscis", replacement="USCIS", match_type="word", word_boundary=True
            ),
        ]
        glossary_file = tmp_path / "glossary.json"
        manager = GlossaryManager(rules)
        with patch("whisper_dictate.glossary.GLOSSARY_FILE", glossary_file):
            assert manager.save() is True
            loaded_text = load_saved_glossary()
        assert "valida tech => ValidaTek" in loaded_text
        assert "uscis => USCIS" in loaded_text

    def test_load_glossary_from_legacy_text(self, tmp_path: Path) -> None:
        glossary_file = tmp_path / "whisper_dictate_glossary.json"
        glossary_file.write_text("Alpha => first\nBeta = second", encoding="utf-8")
        with patch("whisper_dictate.glossary.GLOSSARY_FILE", glossary_file):
            manager = load_glossary_manager()
        assert [r.trigger for r in manager.rules] == ["Alpha", "Beta"]
        assert [r.replacement for r in manager.rules] == ["first", "second"]

    def test_write_saved_glossary_serializes_to_json(self, tmp_path: Path) -> None:
        glossary_file = tmp_path / "glossary.json"
        with patch("whisper_dictate.glossary.GLOSSARY_FILE", glossary_file):
            assert write_saved_glossary("team ai => TeamAI") is True
            content = glossary_file.read_text(encoding="utf-8")
        assert '"trigger": "team ai"' in content
        assert '"replacement": "TeamAI"' in content


class TestGlossaryApplication:
    """Test matching behavior and priority."""

    @pytest.fixture
    def manager(self) -> GlossaryManager:
        return GlossaryManager(
            [
                GlossaryRule(trigger="department of homeland security", replacement="DHS"),
                GlossaryRule(trigger="homeland security", replacement="Homeland Security"),
                GlossaryRule(trigger="epic", replacement="EPIC", match_type="word"),
                GlossaryRule(trigger=r"gpt-\d+", replacement="GPT-X", match_type="regex"),
            ]
        )

    def test_longer_phrases_are_prioritized(self, manager: GlossaryManager) -> None:
        text = "The Department of Homeland Security oversees homeland security matters."
        result = apply_glossary(text, manager)
        assert result.startswith("The DHS oversees Homeland Security")

    def test_word_boundaries_are_respected(self, manager: GlossaryManager) -> None:
        text = "epic work near the epicenter"
        result = apply_glossary(text, manager)
        assert result.startswith("EPIC work")
        assert "epicenter" in result  # unchanged because of boundaries

    def test_regex_rules_can_match_patterns(self, manager: GlossaryManager) -> None:
        text = "We compared gpt-4 and gpt-3.5 in benchmarks"
        result = apply_glossary(text, manager)
        assert result.count("GPT-X") == 2


class TestGlossaryRuleManipulation:
    """Test adding, updating, and removing rules."""

    def test_upsert_rule_adds_new_rule(self) -> None:
        """Test that upsert_rule adds a new rule when trigger doesn't exist."""
        manager = GlossaryManager([GlossaryRule(trigger="alpha", replacement="first")])

        new_rule = GlossaryRule(trigger="beta", replacement="second")
        manager.upsert_rule(new_rule)

        assert len(manager.rules) == 2
        triggers = [r.trigger for r in manager.rules]
        assert "beta" in triggers

    def test_upsert_rule_updates_existing_rule(self) -> None:
        """Test that upsert_rule replaces rule with same trigger (case-insensitive)."""
        manager = GlossaryManager([GlossaryRule(trigger="alpha", replacement="first")])

        # Update with different case
        updated_rule = GlossaryRule(trigger="ALPHA", replacement="FIRST", case_sensitive=True)
        manager.upsert_rule(updated_rule)

        assert len(manager.rules) == 1
        assert manager.rules[0].replacement == "FIRST"
        assert manager.rules[0].case_sensitive is True

    def test_upsert_rule_case_insensitive_matching(self) -> None:
        """Test that upsert matches triggers case-insensitively."""
        manager = GlossaryManager([GlossaryRule(trigger="Test", replacement="old")])

        manager.upsert_rule(GlossaryRule(trigger="test", replacement="new"))

        assert len(manager.rules) == 1
        assert manager.rules[0].replacement == "new"

    def test_remove_rule_by_trigger(self) -> None:
        """Test removing a rule by trigger text."""
        manager = GlossaryManager(
            [
                GlossaryRule(trigger="alpha", replacement="first"),
                GlossaryRule(trigger="beta", replacement="second"),
                GlossaryRule(trigger="gamma", replacement="third"),
            ]
        )

        manager.remove_rule("beta")

        assert len(manager.rules) == 2
        triggers = [r.trigger for r in manager.rules]
        assert "beta" not in triggers
        assert "alpha" in triggers
        assert "gamma" in triggers

    def test_remove_rule_case_insensitive(self) -> None:
        """Test that remove_rule works case-insensitively."""
        manager = GlossaryManager([GlossaryRule(trigger="Test", replacement="value")])

        manager.remove_rule("test")

        assert len(manager.rules) == 0

    def test_remove_rule_nonexistent_trigger(self) -> None:
        """Test that removing non-existent trigger doesn't error."""
        manager = GlossaryManager([GlossaryRule(trigger="alpha", replacement="first")])

        manager.remove_rule("nonexistent")

        assert len(manager.rules) == 1


class TestGlossaryCSV:
    """Test CSV import and export functionality."""

    def test_export_csv_with_rules(self) -> None:
        """Test exporting glossary rules to CSV format."""
        manager = GlossaryManager(
            [
                GlossaryRule(trigger="alpha", replacement="first", match_type="word"),
                GlossaryRule(trigger="beta", replacement="second", case_sensitive=True),
            ]
        )

        csv_output = manager.export_csv()

        assert (
            "trigger,replacement,match_type,case_sensitive,word_boundary,description" in csv_output
        )
        assert "alpha,first,word,false,true," in csv_output
        assert "beta,second,phrase,true,true," in csv_output

    def test_export_csv_empty_glossary(self) -> None:
        """Test that exporting empty glossary returns empty string."""
        manager = GlossaryManager([])

        csv_output = manager.export_csv()

        assert csv_output == ""

    def test_export_csv_includes_description(self) -> None:
        """Test that CSV export includes description field."""
        manager = GlossaryManager(
            [GlossaryRule(trigger="test", replacement="TEST", description="Test rule")]
        )

        csv_output = manager.export_csv()

        assert "Test rule" in csv_output

    def test_import_csv_basic(self) -> None:
        """Test importing rules from CSV text."""
        csv_text = """trigger,replacement,match_type,case_sensitive,word_boundary
alpha,first,word,false,true
beta,second,phrase,true,false"""

        manager = GlossaryManager([])
        manager.import_csv(csv_text)

        assert len(manager.rules) == 2

        # Check first rule
        alpha_rule = next(r for r in manager.rules if r.trigger == "alpha")
        assert alpha_rule.replacement == "first"
        assert alpha_rule.match_type == "word"
        assert alpha_rule.case_sensitive is False
        assert alpha_rule.word_boundary is True

        # Check second rule
        beta_rule = next(r for r in manager.rules if r.trigger == "beta")
        assert beta_rule.replacement == "second"
        assert beta_rule.case_sensitive is True
        assert beta_rule.word_boundary is False

    def test_import_csv_skips_empty_rows(self) -> None:
        """Test that CSV import skips rows with empty trigger or replacement."""
        csv_text = """trigger,replacement
alpha,first
,missing_trigger
missing_replacement,
,"""

        manager = GlossaryManager([])
        manager.import_csv(csv_text)

        assert len(manager.rules) == 1
        assert manager.rules[0].trigger == "alpha"

    def test_import_csv_unknown_match_type_is_a_phrase(self) -> None:
        """A match type the app does not know must not reach GlossaryRule as-is."""
        csv_text = """trigger,replacement,match_type
alpha,first,regex
beta,second,bogus"""

        manager = GlossaryManager([])
        manager.import_csv(csv_text)

        assert [rule.match_type for rule in manager.rules] == ["regex", "phrase"]

    def test_import_csv_handles_missing_columns(self) -> None:
        """Test that CSV import uses defaults for missing columns."""
        csv_text = """trigger,replacement
alpha,first"""

        manager = GlossaryManager([])
        manager.import_csv(csv_text)

        assert len(manager.rules) == 1
        rule = manager.rules[0]
        assert rule.match_type == "phrase"  # default
        assert rule.case_sensitive is False  # default
        assert rule.word_boundary is True  # default

    def test_import_csv_upserts_existing_rules(self) -> None:
        """Test that CSV import updates existing rules with same trigger."""
        manager = GlossaryManager([GlossaryRule(trigger="alpha", replacement="old_value")])

        csv_text = """trigger,replacement,match_type
alpha,new_value,word"""

        manager.import_csv(csv_text)

        assert len(manager.rules) == 1
        assert manager.rules[0].replacement == "new_value"
        assert manager.rules[0].match_type == "word"

    def test_import_csv_round_trip(self) -> None:
        """Test that export/import cycle preserves rules."""
        original_rules = [
            GlossaryRule(
                trigger="alpha", replacement="first", match_type="word", case_sensitive=True
            ),
            GlossaryRule(trigger="beta", replacement="second", word_boundary=False),
            GlossaryRule(trigger="gamma", replacement="third", description="Test description"),
        ]
        manager1 = GlossaryManager(original_rules)

        csv_text = manager1.export_csv()
        manager2 = GlossaryManager([])
        manager2.import_csv(csv_text)

        assert len(manager2.rules) == 3
        for original in original_rules:
            imported = next(r for r in manager2.rules if r.trigger == original.trigger)
            assert imported.replacement == original.replacement
            assert imported.match_type == original.match_type
            assert imported.case_sensitive == original.case_sensitive
            assert imported.word_boundary == original.word_boundary


class TestGlossaryPromptFormatting:
    """Test formatting glossary rules for LLM prompts."""

    def test_format_for_prompt_basic(self) -> None:
        """Test basic prompt formatting."""
        manager = GlossaryManager(
            [
                GlossaryRule(trigger="alpha", replacement="first"),
                GlossaryRule(trigger="beta", replacement="second"),
            ]
        )

        prompt = manager.format_for_prompt()

        assert "alpha → first" in prompt
        assert "beta → second" in prompt

    def test_format_for_prompt_shows_match_type(self) -> None:
        """Test that non-default match types are shown in prompt."""
        manager = GlossaryManager(
            [
                GlossaryRule(trigger="test", replacement="TEST", match_type="word"),
                GlossaryRule(trigger="regex.*", replacement="REGEX", match_type="regex"),
            ]
        )

        prompt = manager.format_for_prompt()

        assert "test → TEST (match=word)" in prompt
        assert "regex.* → REGEX (match=regex)" in prompt

    def test_format_for_prompt_shows_case_sensitive(self) -> None:
        """Test that case-sensitive flag is shown in prompt."""
        manager = GlossaryManager(
            [
                GlossaryRule(trigger="test", replacement="TEST", case_sensitive=True),
            ]
        )

        prompt = manager.format_for_prompt()

        assert "case-sensitive" in prompt

    def test_format_for_prompt_shows_partial_match(self) -> None:
        """Test that partial match (no word boundary) is shown in prompt."""
        manager = GlossaryManager(
            [
                GlossaryRule(trigger="test", replacement="TEST", word_boundary=False),
            ]
        )

        prompt = manager.format_for_prompt()

        assert "partial-ok" in prompt

    def test_format_for_prompt_multiple_options(self) -> None:
        """Test formatting with multiple options on same rule."""
        manager = GlossaryManager(
            [
                GlossaryRule(
                    trigger="test",
                    replacement="TEST",
                    match_type="word",
                    case_sensitive=True,
                    word_boundary=False,
                ),
            ]
        )

        prompt = manager.format_for_prompt()

        assert "match=word" in prompt
        assert "case-sensitive" in prompt
        assert "partial-ok" in prompt

    def test_format_for_prompt_empty_glossary(self) -> None:
        """Test formatting empty glossary."""
        manager = GlossaryManager([])

        prompt = manager.format_for_prompt()

        assert prompt == ""


class TestGlossaryRuleSorting:
    """Test that rules are properly sorted by priority."""

    def test_rules_sorted_by_phrase_length(self) -> None:
        """Test that longer phrases are prioritized over shorter ones."""
        manager = GlossaryManager(
            [
                GlossaryRule(trigger="ai", replacement="AI"),
                GlossaryRule(trigger="team ai", replacement="TeamAI"),
                GlossaryRule(trigger="the team ai project", replacement="Project"),
            ]
        )

        # Verify longest phrase comes first
        assert manager.rules[0].trigger == "the team ai project"
        assert manager.rules[1].trigger == "team ai"
        assert manager.rules[2].trigger == "ai"

    def test_rules_sorted_by_character_length(self) -> None:
        """Test that longer strings are prioritized within same phrase length."""
        manager = GlossaryManager(
            [
                GlossaryRule(trigger="ai", replacement="AI"),
                GlossaryRule(trigger="test", replacement="TEST"),
            ]
        )

        # Both are single-word, so sort by character length
        assert len(manager.rules[0].trigger) >= len(manager.rules[1].trigger)

    def test_sorting_clears_compiled_patterns(self) -> None:
        """Test that sorting clears cached regex patterns."""
        rule = GlossaryRule(trigger="test", replacement="TEST")
        manager = GlossaryManager([rule])

        # Compile the pattern
        manager.rules[0].compile_pattern()
        assert manager.rules[0]._compiled is not None

        # Add another rule (triggers re-sort)
        manager.upsert_rule(GlossaryRule(trigger="another", replacement="ANOTHER"))

        # All patterns should be cleared
        for r in manager.rules:
            assert r._compiled is None


class TestGlossaryRuleSerialization:
    """Test rule serialization and deserialization."""

    def test_rule_to_dict(self) -> None:
        """Test converting rule to dictionary."""
        rule = GlossaryRule(
            trigger="test",
            replacement="TEST",
            match_type="word",
            case_sensitive=True,
            word_boundary=False,
            description="Test rule",
        )

        data = rule.to_dict()

        assert data["trigger"] == "test"
        assert data["replacement"] == "TEST"
        assert data["match_type"] == "word"
        assert data["case_sensitive"] is True
        assert data["word_boundary"] is False
        assert data["description"] == "Test rule"

    def test_rule_from_dict(self) -> None:
        """Test creating rule from dictionary."""
        data = {
            "trigger": "test",
            "replacement": "TEST",
            "match_type": "regex",
            "case_sensitive": True,
            "word_boundary": False,
            "description": "Test rule",
        }

        rule = GlossaryRule.from_dict(data)

        assert rule.trigger == "test"
        assert rule.replacement == "TEST"
        assert rule.match_type == "regex"
        assert rule.case_sensitive is True
        assert rule.word_boundary is False
        assert rule.description == "Test rule"

    def test_rule_from_dict_with_defaults(self) -> None:
        """Test creating rule from minimal dictionary uses defaults."""
        data = {"trigger": "test", "replacement": "TEST"}

        rule = GlossaryRule.from_dict(data)

        assert rule.trigger == "test"
        assert rule.replacement == "TEST"
        assert rule.match_type == "phrase"  # default
        assert rule.case_sensitive is False  # default
        assert rule.word_boundary is True  # default
        assert rule.description is None  # default


class TestPhoneticRules:
    """Opt-in phonetic matching, for the variants a recognizer invents."""

    def _manager(self, trigger="threatfax", replacement="threatfax"):
        return GlossaryManager(
            [GlossaryRule(trigger=trigger, replacement=replacement, match_type="phonetic")]
        )

    def test_one_rule_catches_every_spelling_the_recognizer_invents(self):
        m = self._manager()
        assert m.apply("send it to threat fax today") == "send it to threatfax today"
        assert m.apply("the Threat Fox dashboard") == "the threatfax dashboard"
        assert m.apply("a thread fax please") == "a threatfax please"

    def test_a_short_code_is_refused_with_the_words_it_would_hit(self):
        """Claude codes as KLT, and so do cloud and clod."""
        reason = glossary.phonetic_rejection("Claude")
        assert reason is not None
        assert "KLT" in reason

    def test_a_distinctive_code_is_accepted(self):
        assert glossary.phonetic_rejection("threatfax") is None
        assert glossary.phonetic_rejection("Capobianco") is None

    def test_an_invalid_phonetic_rule_is_dropped_on_construction(self):
        m = GlossaryManager(
            [GlossaryRule(trigger="Claude", replacement="Claude", match_type="phonetic")]
        )
        assert m.rules == []

    def test_ordinary_words_are_left_alone(self):
        m = self._manager()
        text = "the quick brown fox jumped over the lazy dog"
        assert m.apply(text) == text

    def test_a_different_sounding_phrase_is_not_matched(self):
        """Trey Fax codes TRFKS, threatfax codes 0RTFKS. Add an exact rule for
        that variant rather than loosening the match."""
        assert self._manager().apply("ask Trey Fax about it") == "ask Trey Fax about it"

    def test_exact_rules_run_before_phonetic_ones(self):
        m = GlossaryManager(
            [
                GlossaryRule(trigger="threat fax", replacement="EXACT"),
                GlossaryRule(trigger="threatfax", replacement="PHONETIC", match_type="phonetic"),
            ]
        )
        # The exact rule wins where it applies; phonetic sweeps what is left.
        assert m.apply("threat fax and thread fax") == "EXACT and PHONETIC"

    def test_punctuation_and_spacing_around_a_match_survive(self):
        assert self._manager().apply("Is (threat fax) up?") == "Is (threatfax) up?"

    def test_a_multi_word_match_beats_the_single_word_inside_it(self):
        m = GlossaryManager(
            [GlossaryRule(trigger="Wispr Flow", replacement="Wispr Flow", match_type="phonetic")]
        )
        assert m.apply("I used whisper flow yesterday") == "I used Wispr Flow yesterday"

    def test_empty_trigger_is_refused(self):
        assert glossary.phonetic_rejection("   ") is not None


class TestHotwords:
    """Per-application vocabulary for the Whisper backend."""

    def test_budget_stops_at_the_character_limit(self):
        assert glossary.budget(["alpha", "beta", "gamma"], chars=14) == ["alpha", "beta"]

    def test_budget_drops_duplicates(self):
        assert glossary.budget(["alpha", "alpha", "beta"]) == ["alpha", "beta"]

    def test_an_app_with_no_entry_gets_nothing(self):
        """Hotwords cost about 16 word errors per term rescued, and most
        dictations contain no domain term - so they are per-app only."""
        by_app = {"code": ["Traefik"]}
        assert glossary.hotwords_for_app("notepad.exe", by_app) is None

    def test_the_process_stem_is_matched_case_insensitively(self):
        by_app = {"code": ["Traefik", "OPNsense"]}
        assert glossary.hotwords_for_app("Code.exe", by_app) == "Traefik, OPNsense"

    def test_glossary_replacements_join_the_vocabulary(self):
        """Teaching the recognizer the right word beats patching it afterwards."""
        manager = GlossaryManager([GlossaryRule(trigger="sonar cube", replacement="SonarQube")])
        result = glossary.hotwords_for_app("code.exe", {"code": ["Traefik"]}, manager)
        assert result == "Traefik, SonarQube"

    def test_no_process_name_gets_nothing(self):
        assert glossary.hotwords_for_app(None, {"code": ["Traefik"]}) is None

    def test_the_default_budget_is_the_benchmarked_one(self):
        """800 chars leaves a long clip no decoding budget at all."""
        assert glossary.HOTWORD_CHAR_BUDGET == 400

    def test_a_missing_file_is_an_empty_map(self, tmp_path):
        assert glossary.load_hotwords_by_app(tmp_path / "absent.json") == {}

    def test_malformed_json_is_an_empty_map(self, tmp_path):
        path = tmp_path / "hotwords.json"
        path.write_text("{not json", encoding="utf-8")
        assert glossary.load_hotwords_by_app(path) == {}

    def test_loads_and_lowercases_keys(self, tmp_path):
        path = tmp_path / "hotwords.json"
        path.write_text('{"Code": ["Traefik"], "olk": ["Capobianco"]}', encoding="utf-8")
        assert glossary.load_hotwords_by_app(path) == {
            "code": ["Traefik"],
            "olk": ["Capobianco"],
        }
