"""Server-side calls to Django. No database access belongs in the frontend."""

import os

import httpx

from frontend import session

# Assistant answers can take a while, so allow more than the backend's AI timeout.
TIMEOUT = httpx.Timeout(45.0, connect=5.0)


class ApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def backend_url():
    return os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


async def backend_is_ready():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{backend_url()}/api/health/")
            response.raise_for_status()
            return response.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


async def request(method, path, *, json=None, params=None, auth=True, files=None, data=None):
    """Call ``/api/<path>`` and return the decoded JSON body (None when empty).

    Raises ``ApiError`` with a readable message for connection and HTTP errors.
    Use ``files`` for multipart uploads such as CSV imports.
    """
    headers = {}
    token = session.token() if auth else None
    if token:
        headers["Authorization"] = f"Token {token}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.request(
                method,
                f"{backend_url()}/api/{path.lstrip('/')}",
                json=json,
                params=params,
                headers=headers,
                files=files,
                data=data,
            )
    except httpx.HTTPError as exc:
        raise ApiError("The backend is not reachable. Please try again later.") from exc

    if response.status_code == 401 and auth:
        session.sign_out()
        raise ApiError("Your session has expired. Please log in again.", 401)
    if response.is_error:
        raise ApiError(error_message(response), response.status_code)
    if not response.content:
        return None
    return response.json()


async def get(path, **kwargs):
    return await request("GET", path, **kwargs)


async def post(path, **kwargs):
    return await request("POST", path, **kwargs)


async def patch(path, **kwargs):
    return await request("PATCH", path, **kwargs)


async def delete(path, **kwargs):
    return await request("DELETE", path, **kwargs)


def error_message(response):
    """Turn a DRF error body such as {"field": ["msg"]} into one sentence.

    Subsystem errors ({"error": code, "detail": message}) show only their message.
    """
    fallback = f"Request failed ({response.status_code})."
    try:
        body = response.json()
    except ValueError:
        return fallback
    if isinstance(body, dict) and "error" in body and "detail" in body:
        return str(body["detail"])
    return _flatten(body) or fallback


def _flatten(body):
    if isinstance(body, dict):
        parts = []
        for key, value in body.items():
            label = "" if key in {"detail", "non_field_errors"} else f"{key.replace('_', ' ')}: "
            parts.append(label + _flatten(value))
        return " ".join(parts)
    if isinstance(body, list):
        return " ".join(_flatten(item) for item in body)
    return str(body)
