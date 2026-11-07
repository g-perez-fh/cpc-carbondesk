import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from frontend import api
from frontend.api import ApiError, backend_is_ready, error_message


@pytest.mark.parametrize(
    "status, payload, expected",
    [
        (200, {"status": "ok"}, True),
        (503, {"status": "unavailable"}, False),
        (200, {"status": "unknown"}, False),
    ],
)
def test_backend_readiness(status, payload, expected):
    response = httpx.Response(status, json=payload, request=httpx.Request("GET", "http://backend"))
    with patch("frontend.api.httpx.AsyncClient.get", new_callable=AsyncMock) as get:
        get.return_value = response
        assert asyncio.run(backend_is_ready()) is expected


def test_backend_connection_failure():
    with patch("frontend.api.httpx.AsyncClient.get", new_callable=AsyncMock) as get:
        get.side_effect = httpx.ConnectError("unreachable")
        assert asyncio.run(backend_is_ready()) is False


def _response(status, payload=None):
    request = httpx.Request("GET", "http://backend/api/x/")
    if payload is None:
        return httpx.Response(status, request=request)
    return httpx.Response(status, json=payload, request=request)


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"detail": "Not allowed."}, "Not allowed."),
        ({"non_field_errors": ["Invalid username or password."]}, "Invalid username or password."),
        ({"target_year": ["Must be later."]}, "target year: Must be later."),
    ],
)
def test_error_messages_are_readable(payload, expected):
    assert error_message(_response(400, payload)) == expected


def test_request_sends_token_and_decodes_json():
    with (
        patch("frontend.api.session") as session,
        patch("frontend.api.httpx.AsyncClient.request", new_callable=AsyncMock) as send,
    ):
        session.token.return_value = "abc"
        send.return_value = _response(200, [{"id": 1}])
        assert asyncio.run(api.get("accounts/sites/")) == [{"id": 1}]
    assert send.call_args.kwargs["headers"] == {"Authorization": "Token abc"}
    assert send.call_args.args[1].endswith("/api/accounts/sites/")


def test_request_forwards_multipart_files():
    with (
        patch("frontend.api.session") as session,
        patch("frontend.api.httpx.AsyncClient.request", new_callable=AsyncMock) as send,
    ):
        session.token.return_value = "abc"
        send.return_value = _response(201, {"created": 2})
        files = {"file": ("activities.csv", b"date\n", "text/csv")}
        result = asyncio.run(api.post("emissions/activities/import/", files=files))
    assert result == {"created": 2}
    assert send.call_args.kwargs["files"] == files


def test_expired_session_signs_out():
    with (
        patch("frontend.api.session") as session,
        patch("frontend.api.httpx.AsyncClient.request", new_callable=AsyncMock) as send,
    ):
        session.token.return_value = "expired"
        send.return_value = _response(401, {"detail": "Invalid token."})
        with pytest.raises(ApiError) as error:
            asyncio.run(api.get("accounts/me/"))
    assert error.value.status == 401
    session.sign_out.assert_called_once()


def test_empty_response_returns_none():
    with (
        patch("frontend.api.session") as session,
        patch("frontend.api.httpx.AsyncClient.request", new_callable=AsyncMock) as send,
    ):
        session.token.return_value = None
        send.return_value = _response(204)
        assert asyncio.run(api.post("accounts/logout/")) is None
    assert send.call_args.kwargs["headers"] == {}
