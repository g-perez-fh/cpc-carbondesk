"""Contract tests for the Gemini REST adapter in ``assistant.llm``.

These tests pin the migration contract from ``docs/gemini-migration-plan.md``:
``assistant.llm.complete(instructions, messages)`` posts once to the Gemini
``generateContent`` endpoint with the API key in the ``x-goog-api-key`` header
and returns only the answer text of the first candidate. Every failure that
makes an answer unusable must surface as ``LLMUnavailable`` so chat and monthly
summaries keep their fallback behavior, and no key, prompt or provider error
material may appear in the logs. Every request is mocked; nothing is sent live.
"""

import json
import logging
from unittest.mock import patch

import httpx
import pytest

from assistant import llm

API_KEY = "test-key-not-a-real-credential"
MODEL = "gemini-test-model"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
SECRET_PROMPT = "ACME-INTERNAL-SNAPSHOT-7788"
PROVIDER_ERROR = "API key not valid. Please pass a valid API key."


# Helpers -----------------------------------------------------------------------------


def gemini_answer(*texts, thought=""):
    """A ``generateContent`` body with one candidate; ``thought`` adds a thought part."""
    parts = [{"text": text} for text in texts]
    if thought:
        parts.append({"text": thought, "thought": True})
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts},
                "finishReason": "STOP",
                "index": 0,
            }
        ]
    }


def http_response(status_code=200, body=None, raw=None):
    """Build an ``httpx.Response`` the way the Gemini endpoint would send it."""
    content = raw if raw is not None else json.dumps(body if body is not None else {}).encode()
    request = httpx.Request("POST", ENDPOINT)
    return httpx.Response(status_code, content=content, request=request)


def mock_post(response=None, side_effect=None):
    """Patch ``assistant.llm.httpx.post``; this is how tests opt in to AI traffic."""
    kwargs = {}
    if response is not None:
        kwargs["return_value"] = response
    if side_effect is not None:
        kwargs["side_effect"] = side_effect
    return patch("assistant.llm.httpx.post", **kwargs)


def all_texts(node):
    """Collect every ``text`` value inside a Gemini Content structure."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [text for value in node.values() for text in all_texts(value)]
    if isinstance(node, list):
        return [text for item in node for text in all_texts(item)]
    return []


def joined_texts(node):
    """The text of a Content structure as one string, for substring checks."""
    return "".join(all_texts(node))


def single_call(mock):
    """Return ``(url, kwargs)`` of the one request the adapter made."""
    assert mock.call_count == 1, "the adapter must send exactly one HTTP request"
    args, kwargs = mock.call_args
    return (args[0] if args else kwargs["url"]), kwargs


def assert_no_leaks(caplog, *forbidden):
    leaked = [token for token in forbidden if token in caplog.text]
    assert not leaked, f"log output leaked secret or provider material: {leaked}"


# Configuration -----------------------------------------------------------------------


def test_is_configured_reflects_the_key(settings):
    settings.GEMINI_API_KEY = ""
    assert llm.is_configured() is False
    settings.GEMINI_API_KEY = API_KEY
    assert llm.is_configured() is True


@pytest.mark.parametrize("bad_key", ["", "   "])
def test_missing_or_whitespace_key_never_reaches_the_network(settings, bad_key):
    settings.GEMINI_API_KEY = bad_key
    assert llm.is_configured() is False
    with mock_post() as post:
        with pytest.raises(llm.LLMUnavailable):
            llm.complete(SECRET_PROMPT, [{"role": "user", "content": "hi"}])
    post.assert_not_called()


# Request format ----------------------------------------------------------------------


def test_request_carries_instructions_history_and_roles(settings):
    settings.GEMINI_API_KEY = API_KEY
    with mock_post(http_response(body=gemini_answer("Answer"))) as post:
        llm.complete(
            f"Company data: {SECRET_PROMPT}",
            [
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
                {"role": "user", "content": "Follow-up question"},
            ],
        )

    url, kwargs = single_call(post)
    payload = kwargs["json"]
    # Instructions stay separate from the conversation history.
    assert SECRET_PROMPT in joined_texts(payload["systemInstruction"])
    assert SECRET_PROMPT not in joined_texts(payload["contents"])
    # The app's "assistant" history maps onto Gemini's "model" role.
    assert [content["role"] for content in payload["contents"]] == ["user", "model", "user"]
    assert "Follow-up question" in joined_texts(payload["contents"][-1])
    # A bounded output budget is sent; the exact number is an implementation detail.
    max_output_tokens = payload.get("generationConfig", {}).get("maxOutputTokens")
    assert isinstance(max_output_tokens, int) and max_output_tokens > 0


def test_request_targets_gemini_endpoint_with_header_key(settings):
    settings.GEMINI_API_KEY = API_KEY
    settings.GEMINI_MODEL = MODEL
    settings.GEMINI_TIMEOUT_SECONDS = 7.5
    with mock_post(http_response(body=gemini_answer("Answer"))) as post:
        llm.complete("instructions", [{"role": "user", "content": "hi"}])

    url, kwargs = single_call(post)
    assert url == ENDPOINT
    # The key travels in the header, never in the URL.
    assert kwargs["headers"]["x-goog-api-key"] == API_KEY
    assert API_KEY not in url
    timeout = kwargs["timeout"]
    if isinstance(timeout, httpx.Timeout):
        timeout = timeout.read
    assert float(timeout) == pytest.approx(7.5)


# Successful responses ----------------------------------------------------------------


def test_first_candidate_parts_are_joined_and_thoughts_dropped(settings):
    settings.GEMINI_API_KEY = API_KEY
    body = gemini_answer(
        "Solar panels would cut Scope 2", " by about 20%.", thought="hidden reasoning"
    )
    body["candidates"].append(
        {"content": {"role": "model", "parts": [{"text": "WRONG-CANDIDATE-ANSWER"}]}}
    )
    with mock_post(http_response(body=body)):
        answer = llm.complete("instructions", [{"role": "user", "content": "hi"}])

    assert answer == "Solar panels would cut Scope 2 by about 20%."
    assert "WRONG-CANDIDATE-ANSWER" not in answer
    assert "hidden reasoning" not in answer


def test_missing_finish_reason_is_accepted(settings):
    settings.GEMINI_API_KEY = API_KEY
    body = gemini_answer("Answer")
    del body["candidates"][0]["finishReason"]
    with mock_post(http_response(body=body)):
        assert llm.complete("instructions", [{"role": "user", "content": "hi"}]) == "Answer"


# Network and HTTP failures -----------------------------------------------------------


def test_timeout_is_wrapped_and_not_leaked(settings, caplog):
    settings.GEMINI_API_KEY = API_KEY
    caplog.set_level(logging.DEBUG, logger="assistant")
    with mock_post(side_effect=httpx.TimeoutException("timed out after 7.5 seconds")):
        with pytest.raises(llm.LLMUnavailable) as excinfo:
            llm.complete(SECRET_PROMPT, [{"role": "user", "content": "hi"}])

    assert_no_leaks(caplog, API_KEY, SECRET_PROMPT, "timed out after 7.5 seconds")
    assert API_KEY not in str(excinfo.value)
    assert SECRET_PROMPT not in str(excinfo.value)


def test_connection_error_is_wrapped_and_not_leaked(settings, caplog):
    settings.GEMINI_API_KEY = API_KEY
    caplog.set_level(logging.DEBUG, logger="assistant")
    with mock_post(side_effect=httpx.ConnectError("connection refused")):
        with pytest.raises(llm.LLMUnavailable) as excinfo:
            llm.complete(SECRET_PROMPT, [{"role": "user", "content": "hi"}])

    assert_no_leaks(caplog, API_KEY, SECRET_PROMPT, "connection refused")
    assert API_KEY not in str(excinfo.value)
    assert SECRET_PROMPT not in str(excinfo.value)


@pytest.mark.parametrize(
    ("status_code", "provider_message"),
    [
        (401, PROVIDER_ERROR),
        (429, "Resource has been exhausted (e.g. check quota)."),
        (503, "The service is currently unavailable."),
    ],
)
def test_http_errors_are_wrapped_and_not_leaked(settings, caplog, status_code, provider_message):
    settings.GEMINI_API_KEY = API_KEY
    caplog.set_level(logging.DEBUG, logger="assistant")
    body = {"error": {"code": status_code, "message": provider_message, "status": "ERROR"}}
    with mock_post(http_response(status_code, body=body)):
        with pytest.raises(llm.LLMUnavailable) as excinfo:
            llm.complete(SECRET_PROMPT, [{"role": "user", "content": "hi"}])

    assert_no_leaks(caplog, API_KEY, SECRET_PROMPT, provider_message)
    assert API_KEY not in str(excinfo.value)


def test_invalid_json_is_wrapped_and_not_leaked(settings, caplog):
    settings.GEMINI_API_KEY = API_KEY
    caplog.set_level(logging.DEBUG, logger="assistant")
    with mock_post(http_response(raw=b"<html>502 Bad Gateway</html>")):
        with pytest.raises(llm.LLMUnavailable):
            llm.complete(SECRET_PROMPT, [{"role": "user", "content": "hi"}])

    assert_no_leaks(caplog, API_KEY, SECRET_PROMPT, "Bad Gateway")


# Blocked, truncated, malformed and empty replies --------------------------------------
# None of these may be presented as an answer, even when text is present.


def test_blocked_reply_is_rejected_even_when_text_is_present(settings, caplog):
    settings.GEMINI_API_KEY = API_KEY
    caplog.set_level(logging.DEBUG, logger="assistant")
    body = gemini_answer("HAD-TEXT-BUT-BLOCKED")
    body["promptFeedback"] = {"blockReason": "SAFETY"}
    with mock_post(http_response(body=body)):
        with pytest.raises(llm.LLMUnavailable):
            llm.complete(SECRET_PROMPT, [{"role": "user", "content": "hi"}])

    assert_no_leaks(caplog, API_KEY, SECRET_PROMPT, "HAD-TEXT-BUT-BLOCKED")


@pytest.mark.parametrize("finish_reason", ["MAX_TOKENS", "SAFETY", "RECITATION"])
def test_stopped_reply_is_rejected_even_when_text_is_present(settings, caplog, finish_reason):
    settings.GEMINI_API_KEY = API_KEY
    caplog.set_level(logging.DEBUG, logger="assistant")
    body = gemini_answer("HAD-TEXT-BUT-TRUNCATED")
    body["candidates"][0]["finishReason"] = finish_reason
    with mock_post(http_response(body=body)):
        with pytest.raises(llm.LLMUnavailable):
            llm.complete(SECRET_PROMPT, [{"role": "user", "content": "hi"}])

    assert_no_leaks(caplog, API_KEY, SECRET_PROMPT, "HAD-TEXT-BUT-TRUNCATED")


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"candidates": "invalid"},
        {"candidates": [None]},
        {"candidates": [{"content": None}]},
        {"candidates": [{"content": {"parts": "invalid"}}]},
        {"candidates": []},
        {"candidates": [{"content": {"role": "model", "parts": []}}]},
        {"candidates": [{"content": {"role": "model", "parts": [{}]}}]},
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "  \n  "}]}}]},
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"text": "reasoning", "thought": True}],
                    }
                }
            ]
        },
    ],
)
def test_malformed_and_empty_replies_fall_back(settings, body):
    settings.GEMINI_API_KEY = API_KEY
    with mock_post(http_response(body=body)):
        with pytest.raises(llm.LLMUnavailable):
            llm.complete(SECRET_PROMPT, [{"role": "user", "content": "hi"}])
