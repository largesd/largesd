"""JSON response helpers and error formatters."""

from typing import Any

from flask import Response, jsonify


def json_response(data: Any, status: int = 200) -> Response:
    """Return a JSON response with the given status code."""
    response = jsonify(data)
    response.status_code = status
    return response


def error_response(message: str, code: str, status: int = 400, **extra: Any) -> Response:
    """Return a structured error JSON response."""
    payload: dict[str, Any] = {"error": message, "code": code}
    payload.update(extra)
    return json_response(payload, status)


def success_response(
    message: str | None = None, data: dict[str, Any] | None = None, status: int = 200
) -> Response:
    """Return a structured success JSON response."""
    payload: dict[str, Any] = {}
    if message is not None:
        payload["message"] = message
    if data is not None:
        payload.update(data)
    return json_response(payload, status)
