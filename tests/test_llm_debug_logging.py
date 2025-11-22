"""Tests for LLM debug logging behavior."""

import logging

from whisper_dictate import llm_cleanup


class DummyResponse:
    def __init__(self, content: str):
        self.choices = [type("Choice", (), {"message": type("Msg", (), {"content": content})()})]


class DummyCompletions:
    def create(self, *, model, messages, temperature, timeout):  # noqa: D417
        assert model
        assert messages
        assert temperature is not None
        assert timeout is not None
        return DummyResponse("cleaned")


class DummyChat:
    def __init__(self):
        self.completions = DummyCompletions()


class DummyOpenAI:
    def __init__(self, *, base_url, api_key):  # noqa: D401
        self.base_url = base_url
        self.api_key = api_key
        self.chat = DummyChat()


def test_logs_full_prompt_when_debug_enabled(monkeypatch, caplog):
    monkeypatch.setattr(llm_cleanup, "OpenAI", DummyOpenAI)

    with caplog.at_level(logging.INFO):
        result = llm_cleanup.clean_with_llm(
            raw_text="hello world",
            endpoint="http://example/v1",
            model="test-model",
            api_key=None,
            prompt="system prompt",
            temperature=0.2,
            prompt_context="some context",
            debug_logging=True,
        )

    assert result == "cleaned"
    assert any("LLM prompt payload" in rec.message for rec in caplog.records)

