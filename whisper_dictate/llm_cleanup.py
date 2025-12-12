"""LLM cleanup functionality for text refinement."""

import logging
import time

from whisper_dictate.glossary import GlossaryManager

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore


logger = logging.getLogger("whisper_dictate")


class LLMCleanupError(Exception):
    """Raised when LLM cleanup fails."""


def list_llm_models(endpoint: str, api_key: str | None, timeout: float = 10.0) -> list[str]:
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
    api_key: str | None,
    prompt: str,
    temperature: float,
    prompt_context: str | None = None,
    glossary: str | GlossaryManager | None = None,
    app_prompt: str | None = None,
    debug_logging: bool = False,
    timeout: float = 15.0,
) -> str | None:
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
        app_prompt: Optional application-specific prompt appended to the system prompt
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
    if app_prompt:
        system_prompt = (
            f"{system_prompt}\n\nApplication-specific instructions:\n{app_prompt.strip()}"
        )
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

        # Start timing
        start_time = time.perf_counter()
        first_token_time = None

        # Use streaming to capture time to first token
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            timeout=timeout,
            stream=True,
            stream_options={"include_usage": True},
        )

        # Collect response and measure first token time
        collected_text = []
        usage_info = None

        for chunk in stream:
            # Capture time to first token
            if first_token_time is None and chunk.choices:
                if chunk.choices[0].delta.content:
                    first_token_time = time.perf_counter()

            # Collect content
            if chunk.choices:
                content = chunk.choices[0].delta.content
                if content:
                    collected_text.append(content)

            # Capture usage information (typically in the last chunk)
            if hasattr(chunk, "usage") and chunk.usage is not None:
                usage_info = chunk.usage

        # Calculate total time
        end_time = time.perf_counter()
        total_time = end_time - start_time
        time_to_first_token = (first_token_time - start_time) if first_token_time else None

        # Assemble the response text
        text = "".join(collected_text).strip()

        # Log statistics
        if usage_info:
            input_tokens = getattr(usage_info, "prompt_tokens", 0)
            output_tokens = getattr(usage_info, "completion_tokens", 0)
            total_tokens = getattr(usage_info, "total_tokens", input_tokens + output_tokens)

            # Calculate token rate (tokens per second)
            token_rate = output_tokens / total_time if total_time > 0 else 0

            logger.info(
                "LLM statistics: time_to_first_token=%.3fs total_time=%.3fs "
                "input_tokens=%d output_tokens=%d total_tokens=%d token_rate=%.1f tok/s",
                time_to_first_token if time_to_first_token else 0,
                total_time,
                input_tokens,
                output_tokens,
                total_tokens,
                token_rate,
            )
        else:
            # Log timing even if usage info not available
            logger.info(
                "LLM statistics: time_to_first_token=%.3fs total_time=%.3fs "
                "(token usage not available)",
                time_to_first_token if time_to_first_token else 0,
                total_time,
            )

        # Also log the output text if debug logging is enabled
        if debug_logging:
            logger.info("LLM response: %s", text)

        return text if text else None
    except Exception as e:
        raise LLMCleanupError(f"LLM cleanup failed: {e}") from e
