"""In-process transcript cleanup with superwhisper's S1-mini.

The model's prompt contract is fixed and unforgiving: one system sentence, then
a control line naming the styling, structure and context, and an assistant turn
that opens with an empty think block. Any other system text and the model emits
a single token and stops (measured 2026-09-18), which is what made it look
broken behind a chat template - Ollama also files the output into `reasoning`
and leaves `content` empty. Building the prompt by hand avoids every layer that
could rewrite it.

llama_cpp and huggingface_hub are imported inside S1Cleaner, not at module
import, so the rest of the app runs without them.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("whisper_dictate")

S1_REPO, S1_FILE = "superwhisper/s1-mini-GGUF", "s1-mini-q4_k_m.gguf"
S1_SYSTEM = (
    "You are a text normalizer for speech-to-text transcripts. The input begins with a "
    "control line specifying the styling, structure, and context settings; clean the "
    "transcript to match those settings and output only the cleaned text."
)
STYLING = ("casual", "semi-casual", "semi-formal", "formal")
STRUCTURE = ("prose", "lists")
CONTEXT = ("general", "email")

DEFAULT_STYLING, DEFAULT_STRUCTURE, DEFAULT_CONTEXT = "semi-casual", "prose", "general"


def build_prompt(text: str, styling: str, structure: str, context: str) -> str:
    """Assemble the exact prompt the model was trained on.

    The empty think block is the documented way to disable thinking. This string
    is the contract: tests compare it byte for byte, because it is what broke
    when a template layer got between us and the model.
    """
    return (
        f"<|im_start|>system\n{S1_SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n[Styling: {styling}] [Structure: {structure}] [Context: {context}]\n"
        f"{text}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


class S1Cleaner:
    """S1-mini held in-process, on the GPU when llama.cpp can have it."""

    def __init__(self) -> None:
        from huggingface_hub import hf_hub_download
        from llama_cpp import Llama

        # The cached file first: hf_hub_download revalidates over the network
        # otherwise, so cleanup would depend on a connection it does not need.
        try:
            path = hf_hub_download(S1_REPO, S1_FILE, local_files_only=True)
        except OSError:
            logger.info("S1-mini is not cached; downloading")
            path = hf_hub_download(S1_REPO, S1_FILE)
        try:
            self.llm = Llama(path, n_gpu_layers=-1, n_ctx=4096, verbose=False)
            self.on_gpu = True
        except Exception as e:
            # A GPU refusal is not a reason to lose cleanup; CPU is ~1 s for an
            # email-length dictation.
            logger.warning(f"S1-mini could not use the GPU ({type(e).__name__}); using CPU")
            self.llm = Llama(path, n_gpu_layers=0, n_ctx=4096, verbose=False)
            self.on_gpu = False
        logger.info(f"S1-mini loaded on {'GPU' if self.on_gpu else 'CPU'}")

    def clean(
        self,
        text: str,
        styling: str = DEFAULT_STYLING,
        structure: str = DEFAULT_STRUCTURE,
        context: str = DEFAULT_CONTEXT,
    ) -> str:
        """Normalize one transcript. Greedy, so the same input gives the same output.

        ponytail: inputs over ~1000 tokens are not chunked; the p99 dictation is
        59 s of speech, about 200 tokens, and the longest ever recorded was 197 s,
        about 650. Add sentence chunking if one is ever cut off.
        """
        out: Any = self.llm(
            build_prompt(text, styling, structure, context),
            max_tokens=len(text) // 2 + 64,
            temperature=0,
            stop=["<|im_end|>"],
        )
        return str(out["choices"][0]["text"]).strip()
