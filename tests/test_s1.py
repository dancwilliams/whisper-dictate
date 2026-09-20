"""Tests for the built-in S1-mini cleanup."""

import sys
from unittest.mock import MagicMock

import pytest

from whisper_dictate import s1
from whisper_dictate.s1 import S1Cleaner, build_prompt


class TestBuildPrompt:
    """The prompt is the contract, so it is compared byte for byte.

    Any other system text makes the model emit one token and stop, and a chat
    template layer between us and the model is what broke this on Ollama.
    """

    def test_exact_bytes(self):
        assert build_prompt("hello there", "semi-formal", "prose", "email") == (
            "<|im_start|>system\n"
            "You are a text normalizer for speech-to-text transcripts. The input begins "
            "with a control line specifying the styling, structure, and context settings; "
            "clean the transcript to match those settings and output only the cleaned "
            "text.<|im_end|>\n"
            "<|im_start|>user\n"
            "[Styling: semi-formal] [Structure: prose] [Context: email]\n"
            "hello there<|im_end|>\n"
            "<|im_start|>assistant\n"
            "<think>\n\n</think>\n\n"
        )

    def test_the_think_block_is_empty_and_present(self):
        """The empty think block is how thinking is disabled."""
        assert build_prompt("x", "casual", "prose", "general").endswith(
            "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        )

    def test_control_line_carries_all_three_settings(self):
        prompt = build_prompt("x", "formal", "lists", "email")
        assert "[Styling: formal] [Structure: lists] [Context: email]\n" in prompt

    def test_transcript_follows_the_control_line(self):
        assert "[Context: general]\nthe transcript<|im_end|>" in build_prompt(
            "the transcript", "casual", "prose", "general"
        )


class TestS1Cleaner:
    def _install(self, monkeypatch, gpu_raises=False, generated="  Cleaned text.  "):
        llama_calls = []

        def llama(path, **kwargs):
            llama_calls.append((path, kwargs))
            if gpu_raises and kwargs.get("n_gpu_layers") != 0:
                raise RuntimeError("no CUDA device")
            instance = MagicMock()
            instance.return_value = {"choices": [{"text": generated}]}
            return instance

        llama_cpp = MagicMock()
        llama_cpp.Llama = llama
        hub = MagicMock()
        hub.hf_hub_download.return_value = "C:/models/s1-mini-q4_k_m.gguf"
        monkeypatch.setitem(sys.modules, "llama_cpp", llama_cpp)
        monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
        return llama_calls, hub

    def test_downloads_the_right_file_and_loads_on_gpu(self, monkeypatch):
        calls, hub = self._install(monkeypatch)
        cleaner = S1Cleaner()

        hub.hf_hub_download.assert_called_once_with(s1.S1_REPO, s1.S1_FILE, local_files_only=True)
        assert cleaner.on_gpu is True
        path, kwargs = calls[0]
        assert path == "C:/models/s1-mini-q4_k_m.gguf"
        assert kwargs["n_gpu_layers"] == -1
        assert kwargs["n_ctx"] == 4096

    def test_gpu_failure_retries_on_cpu(self, monkeypatch):
        """A GPU refusal must not cost the user cleanup entirely."""
        calls, _hub = self._install(monkeypatch, gpu_raises=True)
        cleaner = S1Cleaner()

        assert cleaner.on_gpu is False
        assert [kwargs["n_gpu_layers"] for _p, kwargs in calls] == [-1, 0]

    def test_falls_back_to_downloading_when_not_cached(self, monkeypatch):
        """Local-first, but a machine without the weights still gets them."""
        _calls, hub = self._install(monkeypatch)
        hub.hf_hub_download.side_effect = [OSError("not cached"), "C:/models/s1.gguf"]

        S1Cleaner()

        assert hub.hf_hub_download.call_count == 2
        assert hub.hf_hub_download.call_args_list[1].kwargs == {}

    def test_clean_strips_and_returns_the_text(self, monkeypatch):
        self._install(monkeypatch)
        assert S1Cleaner().clean("so um the thing") == "Cleaned text."

    def test_clean_is_greedy_and_stops_on_the_turn_marker(self, monkeypatch):
        self._install(monkeypatch)
        cleaner = S1Cleaner()
        cleaner.clean("some words here")

        _args, kwargs = cleaner.llm.call_args
        assert kwargs["temperature"] == 0
        assert kwargs["stop"] == ["<|im_end|>"]

    def test_token_budget_scales_with_the_input(self, monkeypatch):
        """Cleanup shortens text; half the input plus a floor is enough."""
        self._install(monkeypatch)
        cleaner = S1Cleaner()
        text = "x" * 200
        cleaner.clean(text)
        assert cleaner.llm.call_args.kwargs["max_tokens"] == 164

    def test_defaults_are_the_documented_settings(self, monkeypatch):
        self._install(monkeypatch)
        cleaner = S1Cleaner()
        cleaner.clean("words")
        prompt = cleaner.llm.call_args.args[0]
        assert "[Styling: semi-casual] [Structure: prose] [Context: general]" in prompt

    def test_style_arguments_reach_the_prompt(self, monkeypatch):
        self._install(monkeypatch)
        cleaner = S1Cleaner()
        cleaner.clean("words", "formal", "lists", "email")
        prompt = cleaner.llm.call_args.args[0]
        assert "[Styling: formal] [Structure: lists] [Context: email]" in prompt


def test_the_documented_settings_are_the_ones_offered():
    """The GUI builds its comboboxes from these; a typo would be a silent
    prompt the model was never trained on."""
    assert s1.STYLING == ("casual", "semi-casual", "semi-formal", "formal")
    assert s1.STRUCTURE == ("prose", "lists")
    assert s1.CONTEXT == ("general", "email")
    assert s1.DEFAULT_STYLING in s1.STYLING
    assert s1.DEFAULT_STRUCTURE in s1.STRUCTURE
    assert s1.DEFAULT_CONTEXT in s1.CONTEXT


@pytest.mark.skipif("--runslow" not in sys.argv, reason="downloads and runs the real model")
def test_real_model_cleans_a_dictation():
    from whisper_dictate.config import set_cuda_paths

    set_cuda_paths()
    cleaner = S1Cleaner()
    out = cleaner.clean(
        "so um i need to like send the the report by uh friday no wait make that thursday",
        "semi-formal",
        "prose",
        "general",
    )
    assert out == "So I need to send the report by Thursday."
