"""Tests for LLM debug logging behavior."""

import logging

from whisper_dictate import llm_cleanup


class DummyChunk:
    def __init__(self, content: str = None, has_usage: bool = False):
        self.choices = [type("Choice", (), {"delta": type("Delta", (), {"content": content})()})]
        if has_usage:
            self.usage = type("Usage", (), {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})()
        else:
            self.usage = None


class DummyCompletions:
    def create(self, *, model, messages, temperature, timeout, stream=False, stream_options=None):  # noqa: D417
        assert model
        assert messages
        assert temperature is not None
        assert timeout is not None
        if stream:
            # Return an iterator of chunks
            return iter([DummyChunk("cleaned"), DummyChunk(None, has_usage=True)])
        return DummyChunk("cleaned")


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
    # Check for prompt logging
    assert any("LLM prompt payload" in rec.message for rec in caplog.records)
    # Check for statistics logging
    assert any("LLM statistics" in rec.message for rec in caplog.records)
    # Check for response logging (when debug enabled)
    assert any("LLM response" in rec.message for rec in caplog.records)

