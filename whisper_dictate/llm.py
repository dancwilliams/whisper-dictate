"""Helpers for optional LLM post-processing."""

from __future__ import annotations

from typing import Optional

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore[assignment]


def clean_with_llm(
    raw_text: str,
    endpoint: str,
    model: str,
    api_key: Optional[str],
    prompt: str,
    temperature: float,
    timeout: float = 15.0,
) -> Optional[str]:
    """Send ``raw_text`` to an OpenAI-compatible endpoint for cleanup."""

    if not raw_text.strip():
        return ""
    if OpenAI is None:
        print("(LLM) openai client not available. Install with: uv add openai")
        return None

    try:
        client = OpenAI(base_url=endpoint, api_key=api_key or "sk-no-key-needed")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": raw_text},
            ],
            temperature=temperature,
            timeout=timeout,
        )
        if not response.choices:
            return None
        choice = response.choices[0].message.content or ""
        return choice.strip() or None
    except Exception as exc:  # pragma: no cover - network failure paths
        print(f"(LLM) error: {exc}")
        return None
