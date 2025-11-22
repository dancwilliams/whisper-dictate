"""LLM cleanup functionality for text refinement."""

import logging
from typing import Optional, Union

from whisper_dictate.glossary import GlossaryManager

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore


logger = logging.getLogger("whisper_dictate")


class LLMCleanupError(Exception):
    """Raised when LLM cleanup fails."""


def list_llm_models(endpoint: str, api_key: Optional[str], timeout: float = 10.0) -> list[str]:
    """
    Retrieve available models from an OpenAI-compatible endpoint.

    Args:
        endpoint: Base URL for the API
        api_key: API key (optional, can be None)
        timeout: Request timeout in seconds

    Returns:
        A list of model identifiers (may be empty)

    Raises:
        LLMCleanupError: If the client is unavailable or listing fails
    """
    if OpenAI is None:
        raise LLMCleanupError("OpenAI client not installed. Run: uv add openai")

    try:
        client = OpenAI(base_url=endpoint, api_key=api_key or "sk-no-key")
        response = client.models.list(timeout=timeout)
        models = [m.id for m in getattr(response, "data", []) if getattr(m, "id", None)]
        return sorted(set(models))
    except Exception as e:
        raise LLMCleanupError(f"Could not list models: {e}") from e


def clean_with_llm(
    raw_text: str,
    endpoint: str,
    model: str,
    api_key: Optional[str],
    prompt: str,
    temperature: float,
    prompt_context: Optional[str] = None,
    glossary: Optional[Union[str, GlossaryManager]] = None,
    debug_logging: bool = False,
    timeout: float = 15.0,
) -> Optional[str]:
    """
    Send raw_text to an OpenAI-compatible LLM for cleanup.
    
    Args:
        raw_text: Raw transcribed text to clean
        endpoint: Base URL for OpenAI-compatible API
        model: Model name to use
        api_key: API key (optional, can be None)
        prompt: System prompt for the LLM
        temperature: Temperature for generation
        prompt_context: Optional runtime context to append to the prompt
        glossary: Optional glossary text prepended to the prompt
        debug_logging: When True, log the full prompt payload before sending
        timeout: Request timeout in seconds
        
    Returns:
        Cleaned text, or None on failure
        
    Raises:
        LLMCleanupError: If cleanup fails and OpenAI is available
    """
    if not raw_text.strip():
        return ""
    
    if OpenAI is None:
        raise LLMCleanupError("OpenAI client not installed. Run: uv add openai")

    if isinstance(glossary, GlossaryManager):
        glossary_text = glossary.format_for_prompt().strip()
    else:
        glossary_text = (glossary or "").strip()
    system_prompt = prompt.rstrip()
    if glossary_text:
        system_prompt = f"Glossary entries (prioritized):\n{glossary_text}\n\n{system_prompt}"
    if prompt_context:
        system_prompt = (
            f"{system_prompt}\n\nContext about the active application:\n{prompt_context}"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": raw_text},
    ]

    if debug_logging:
        logger.info(
            "LLM prompt payload: endpoint=%s model=%s temperature=%s messages=%s",
            endpoint,
            model,
            temperature,
            messages,
        )

    try:
        client = OpenAI(base_url=endpoint, api_key=api_key or "sk-no-key")
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            timeout=timeout,
        )
        if resp.choices:
            text = resp.choices[0].message.content or ""
            return text.strip()
        return None
    except Exception as e:
        raise LLMCleanupError(f"LLM cleanup failed: {e}") from e

