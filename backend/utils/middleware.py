"""Request/response middleware and error handlers."""
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone

from flask import current_app, g, jsonify, request
from werkzeug.exceptions import BadRequest

from backend.utils.validators import ValidationError


def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token."""
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response):
    """Attach a double-submit CSRF token cookie to a response."""
    env = os.getenv('ENV', 'development')
    token = generate_csrf_token()
    response.set_cookie(
        'csrf_token',
        token,
        secure=env != 'development',
        httponly=False,           # Must be readable by JavaScript
        samesite='Lax',
        max_age=3600,             # 1 hour
    )
    return response


def _has_bearer_auth() -> bool:
    """Check whether the current request carries a Bearer token."""
    auth_header = request.headers.get('Authorization', '')
    return auth_header.lower().startswith('bearer ')


def _setup_csrf_protection(app):
    """Register CSRF before_request handler."""
    @app.before_request
    def csrf_protection():
        """Require a valid double-submit CSRF token for state-changing API requests.

        Exempt:
          - Safe HTTP methods (GET, HEAD, OPTIONS)
          - API requests that already carry a Bearer token
        """
        if not request.path.startswith('/api/'):
            return None
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return None
        if _has_bearer_auth():
            return None

        cookie_token = request.cookies.get('csrf_token')
        header_token = request.headers.get('X-CSRF-Token')

        if not cookie_token or not header_token or cookie_token != header_token:
            return jsonify({
                'error': 'CSRF token missing or invalid',
                'code': 'CSRF_INVALID'
            }), 403

        return None


def _setup_rate_limit_error_handler(app):
    """Register 429 rate limit error handler."""
    @app.errorhandler(429)
    def rate_limit_handler(e):
        """Return structured JSON for rate-limit errors instead of raw HTML."""
        retry_after = getattr(e, 'retry_after', None)
        response = jsonify({
            'error': 'Rate limit exceeded. Please slow down and retry.',
            'code': 'RATE_LIMITED',
            'retry_after': retry_after,
        })
        response.status_code = 429
        if retry_after:
            response.headers['Retry-After'] = str(retry_after)
        return response


def _setup_request_logging(app):
    """Register before_request / after_request logging with request_id."""
    @app.before_request
    def attach_request_id():
        g.request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))

    @app.after_request
    def add_request_id_header(response):
        response.headers['X-Request-ID'] = getattr(g, 'request_id', str(uuid.uuid4()))
        return response

    @app.after_request
    def log_request(response):
        logger = logging.getLogger('debate_system')
        logger.info(
            f"{request.method} {request.path} {response.status_code}",
            extra={
                'event_type': 'http_request',
                'request_id': getattr(g, 'request_id', None),
                'user_id': (getattr(g, 'user', None) or {}).get('user_id'),
                'status_code': response.status_code,
            }
        )
        return response


def _setup_error_handlers(app):
    """Register validation and generic error handlers."""
    @app.errorhandler(ValidationError)
    def handle_validation_error(error):
        return jsonify({'error': str(error), 'code': 'VALIDATION_ERROR'}), 400

    @app.errorhandler(BadRequest)
    def handle_bad_request(error):
        return jsonify({'error': 'Invalid request format', 'code': 'BAD_REQUEST'}), 400

    @app.errorhandler(404)
    def handle_not_found(error):
        return jsonify({'error': 'Not found', 'code': 'NOT_FOUND'}), 404

    @app.errorhandler(500)
    def handle_server_error(error):
        return jsonify({'error': 'Internal server error', 'code': 'SERVER_ERROR'}), 500


def setup_middleware(app):
    """Attach all middleware to the Flask app."""
    _setup_csrf_protection(app)
    _setup_rate_limit_error_handler(app)
    _setup_request_logging(app)
    _setup_error_handlers(app)
