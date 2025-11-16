"""LLM cleanup functionality for text refinement."""

from typing import Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore


class LLMCleanupError(Exception):
    """Raised when LLM cleanup fails."""


def clean_with_llm(
    raw_text: str,
    endpoint: str,
    model: str,
    api_key: Optional[str],
    prompt: str,
    temperature: float,
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
    
    try:
        client = OpenAI(base_url=endpoint, api_key=api_key or "sk-no-key")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": raw_text},
            ],
            temperature=temperature,
            timeout=timeout,
        )
        if resp.choices:
            text = resp.choices[0].message.content or ""
            return text.strip()
        return None
    except Exception as e:
        raise LLMCleanupError(f"LLM cleanup failed: {e}") from e

