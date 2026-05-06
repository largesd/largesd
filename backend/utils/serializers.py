"""JSON response helpers and error formatters."""
from flask import jsonify


def json_response(data, status=200):
    """Return a JSON response with the given status code."""
    response = jsonify(data)
    response.status_code = status
    return response


def error_response(message, code, status=400, **extra):
    """Return a structured error JSON response."""
    payload = {'error': message, 'code': code}
    payload.update(extra)
    return json_response(payload, status)


def success_response(message=None, data=None, status=200):
    """Return a structured success JSON response."""
    payload = {}
    if message is not None:
        payload['message'] = message
    if data is not None:
        payload.update(data)
    return json_response(payload, status)
