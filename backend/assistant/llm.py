"""Thin wrapper around the Gemini REST API so the rest of the app never depends on it directly."""

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# Official REST endpoint: https://ai.google.dev/api/generate-content
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MAX_OUTPUT_TOKENS = 4096


class LLMUnavailable(Exception):
    """Raised when no model is configured or the request fails; callers fall back."""


def is_configured() -> bool:
    return bool(settings.GEMINI_API_KEY.strip())


def complete(instructions: str, messages: list[dict]) -> str:
    """Return the model's reply to a list of {"role", "content"} messages."""
    if not is_configured():
        raise LLMUnavailable("GEMINI_API_KEY is not set.")

    payload = {
        "systemInstruction": {"parts": [{"text": instructions}]},
        "contents": [
            {"role": _gemini_role(message["role"]), "parts": [{"text": message["content"]}]}
            for message in messages
        ],
        "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS},
    }
    url = f"{GEMINI_API_BASE_URL}/models/{settings.GEMINI_MODEL}:generateContent"
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"x-goog-api-key": settings.GEMINI_API_KEY.strip()},
            timeout=settings.GEMINI_TIMEOUT_SECONDS,
        )
    except httpx.RequestError as exc:
        logger.warning("Gemini request failed: %s", exc.__class__.__name__)
        raise LLMUnavailable("The AI service is unavailable.") from exc

    if response.status_code != 200:
        # Log the status code only; provider bodies could contain prompts or other sensitive data.
        logger.warning("Gemini request failed: HTTP %s", response.status_code)
        raise LLMUnavailable("The AI service is unavailable.")

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning("Gemini request failed: %s", exc.__class__.__name__)
        raise LLMUnavailable("The AI service is unavailable.") from exc

    text = _answer_text(data)
    if not text:
        raise LLMUnavailable("The AI service returned an empty answer.")
    return text


def _gemini_role(role: str) -> str:
    """Map the app's roles to Gemini's; their chat roles are 'user' and 'model'."""
    return "model" if role == "assistant" else "user"


def _answer_text(data: object) -> str:
    """Answer text from the first candidate, joined from its parts without thought parts.

    Returns "" when the JSON shape is unexpected, the prompt or answer was blocked,
    or no non-thought text was returned; callers treat that as an unusable answer.
    """
    if not isinstance(data, dict):
        return ""
    feedback = data.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        return ""
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return ""
    # Never present blocked or truncated output as a complete answer.
    if candidate.get("finishReason") not in (None, "STOP"):
        return ""
    content = candidate.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    texts = [
        part["text"]
        for part in parts
        if isinstance(part, dict) and not part.get("thought") and isinstance(part.get("text"), str)
    ]
    return "".join(texts).strip()
