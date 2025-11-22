"""Tests for glossary management."""

from pathlib import Path
from unittest.mock import patch

from whisper_dictate.glossary import (
    GLOSSARY_FILE,
    load_saved_glossary,
    write_saved_glossary,
)


class TestGlossary:
    """Test glossary loading and saving."""

    def test_load_saved_glossary_file_exists(self, tmp_path):
        glossary_text = "Alpha = first\nBeta = second"
        test_file = tmp_path / "whisper_dictate_glossary.txt"
        test_file.write_text(glossary_text, encoding="utf-8")

        with patch("whisper_dictate.glossary.GLOSSARY_FILE", test_file):
            result = load_saved_glossary("default")
            assert result == glossary_text

    def test_load_saved_glossary_empty_returns_default(self, tmp_path):
        test_file = tmp_path / "whisper_dictate_glossary.txt"
        test_file.write_text("   \n", encoding="utf-8")

        with patch("whisper_dictate.glossary.GLOSSARY_FILE", test_file):
            assert load_saved_glossary("default") == "default"

    def test_load_saved_glossary_missing_returns_default(self):
        with patch("whisper_dictate.glossary.GLOSSARY_FILE", Path("/no/glossary.txt")):
            assert load_saved_glossary("default") == "default"

    def test_write_saved_glossary_success(self, tmp_path):
        test_file = tmp_path / "whisper_dictate_glossary.txt"

        with patch("whisper_dictate.glossary.GLOSSARY_FILE", test_file):
            assert write_saved_glossary("entry") is True
            assert test_file.read_text(encoding="utf-8") == "entry"

    def test_write_saved_glossary_failure(self):
        with patch("whisper_dictate.glossary.GLOSSARY_FILE", Path("/invalid/path/glossary.txt")):
            with patch("pathlib.Path.write_text", side_effect=PermissionError("Access denied")):
                assert write_saved_glossary("entry") is False
