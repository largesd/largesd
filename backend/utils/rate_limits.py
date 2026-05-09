"""Rate-limit helpers for the Flask app factory."""

from typing import Any

from flask import request


def _should_exempt_default_rate_limits() -> bool:
    """Apply the broad default limit only to mutating API requests."""
    return request.method in ("GET", "HEAD", "OPTIONS") or not request.path.startswith("/api/")


_RATE_LIMITS = {
    "posts.submit_post": "10 per hour; 30 per day",
    "snapshot.generate_snapshot": "5 per hour; 20 per day",
}


def apply_route_rate_limits(app: Any, limiter: Any) -> None:
    """Attach route-specific rate limits to view functions."""
    for endpoint, spec in _RATE_LIMITS.items():
        func = app.view_functions.get(endpoint)
        if func:
            app.view_functions[endpoint] = limiter.limit(spec)(func)
