"""
Integration tests for CORS origin restriction.

Acceptance criteria:
  • CORS restricted to explicit origin list in all environments
  • No wildcard (*) origin in production
  • Integration tests verify origin blocking
"""
import os
import sys
import warnings
import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _reload_app_v3_with_env(**env_overrides):
    """Reload backend.app_v3 with the supplied environment overrides."""
    for key, value in env_overrides.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    import backend.app_v3 as app_v3
    app_module = importlib.reload(app_v3)
    app_module.app.config["TESTING"] = True
    return app_module


def test_cors_preflight_allowed_origin():
    """Preflight request from an allowed origin must succeed with CORS headers."""
    os.environ["ALLOWED_ORIGINS"] = "http://localhost:5000,http://localhost:3000"
    os.environ["DISABLE_JOB_WORKER"] = "1"
    os.environ["SECRET_KEY"] = "test-secret-key-auth-session-32-bytes"

    app_module = _reload_app_v3_with_env()
    client = app_module.app.test_client()

    resp = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Flask-CORS returns 200 for allowed preflight
    assert resp.status_code == 200
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
    assert "GET" in resp.headers.get("Access-Control-Allow-Methods", "")
    print("✓ Allowed origin preflight returns 200 with CORS headers")


def test_cors_preflight_disallowed_origin():
    """Preflight request from a disallowed origin must not receive CORS headers."""
    os.environ["ALLOWED_ORIGINS"] = "http://localhost:5000"
    os.environ["DISABLE_JOB_WORKER"] = "1"
    os.environ["SECRET_KEY"] = "test-secret-key-auth-session-32-bytes"

    app_module = _reload_app_v3_with_env()
    client = app_module.app.test_client()

    resp = client.options(
        "/api/health",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Flask-CORS does not add ACAO for disallowed origins
    assert "Access-Control-Allow-Origin" not in resp.headers
    print("✓ Disallowed origin preflight has no CORS headers")


def test_cors_missing_allowed_origins_warning():
    """When ALLOWED_ORIGINS is missing a warning must be emitted at import time."""
    # Ensure the variable is absent
    if "ALLOWED_ORIGINS" in os.environ:
        del os.environ["ALLOWED_ORIGINS"]

    os.environ["DISABLE_JOB_WORKER"] = "1"
    os.environ["SECRET_KEY"] = "test-secret-key-auth-session-32-bytes"

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        app_module = _reload_app_v3_with_env()
        # Force any deferred warnings to surface
        assert len(w) >= 1
        assert any(
            "ALLOWED_ORIGINS not set" in str(warning.message) for warning in w
        ), f"Expected warning about missing ALLOWED_ORIGINS, got: {[str(wi.message) for wi in w]}"
        print("✓ Warning emitted when ALLOWED_ORIGINS is missing")

    # Verify CORS is effectively disabled (no ACAO header for any origin)
    client = app_module.app.test_client()
    resp = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "Access-Control-Allow-Origin" not in resp.headers
    print("✓ CORS disabled when ALLOWED_ORIGINS is missing")
