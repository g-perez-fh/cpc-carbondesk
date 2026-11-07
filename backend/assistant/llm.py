"""Thin wrapper around the OpenAI API so the rest of the app never depends on it directly."""

import logging

from django.conf import settings

from .exceptions import AIServiceUnavailableError

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(settings.OPENAI_API_KEY)


def complete(instructions: str, messages: list[dict]) -> str:
    """Return the model's reply to a list of {"role", "content"} messages."""
    if not is_configured():
        raise AIServiceUnavailableError("OPENAI_API_KEY is not set.")

    from openai import OpenAI, OpenAIError

    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_TIMEOUT_SECONDS)
    try:
        response = client.responses.create(
            model=settings.OPENAI_MODEL,
            instructions=instructions,
            input=messages,
            max_output_tokens=1000,
        )
    except OpenAIError as exc:
        logger.warning("OpenAI request failed: %s", exc.__class__.__name__)
        raise AIServiceUnavailableError("The AI service is unavailable.") from exc

    text = (response.output_text or "").strip()
    if not text:
        raise AIServiceUnavailableError("The AI service returned an empty answer.")
    return text
