"""Tests for glossary management and application."""

from pathlib import Path
from unittest.mock import patch

import pytest

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
            GlossaryRule(trigger="uscis", replacement="USCIS", match_type="word", word_boundary=True),
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
        assert "\"trigger\": \"team ai\"" in content
        assert "\"replacement\": \"TeamAI\"" in content


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
