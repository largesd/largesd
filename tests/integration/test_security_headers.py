"""
Integration tests for security headers middleware.

Acceptance criteria:
  • All responses include X-Frame-Options, X-Content-Type-Options, CSP, HSTS
  • CSP blocks external script injection
"""
import os
import sys
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


def test_all_security_headers_present_on_https_request():
    """All required security headers must be present when request indicates HTTPS."""
    os.environ["DISABLE_JOB_WORKER"] = "1"
    os.environ["SECRET_KEY"] = "test-secret-key-auth-session-32-bytes"
    os.environ["ALLOWED_ORIGINS"] = ""

    app_module = _reload_app_v3_with_env()
    client = app_module.app.test_client()

    resp = client.get(
        "/api/health",
        headers={"X-Forwarded-Proto": "https"},
    )
    assert resp.status_code == 200

    # Core security headers
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in resp.headers
    assert "Strict-Transport-Security" in resp.headers

    # HSTS value
    hsts = resp.headers.get("Strict-Transport-Security")
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts

    print("✓ All required security headers present on HTTPS-indicated request")


def test_csp_blocks_external_script_injection():
    """CSP must restrict script sources to self and unsafe-inline only."""
    os.environ["DISABLE_JOB_WORKER"] = "1"
    os.environ["SECRET_KEY"] = "test-secret-key-auth-session-32-bytes"
    os.environ["ALLOWED_ORIGINS"] = ""

    app_module = _reload_app_v3_with_env()
    client = app_module.app.test_client()

    resp = client.get("/api/health")
    assert resp.status_code == 200

    csp = resp.headers.get("Content-Security-Policy")
    assert csp is not None

    # default-src should be 'self' to block unknown external resources
    assert "default-src 'self'" in csp

    # script-src should not allow arbitrary external domains (no * or https: without host)
    assert "script-src" in csp
    assert "'self'" in csp
    # Explicitly ensure no wildcard script source
    assert "script-src *" not in csp

    # frame-ancestors should be 'none' to prevent clickjacking
    assert "frame-ancestors 'none'" in csp

    # form-action should be 'self' to prevent form hijacking
    assert "form-action 'self'" in csp

    print("✓ CSP policy restricts external script injection")


def test_referrer_policy_and_feature_policy_present():
    """Referrer-Policy and Feature-Policy headers must be set correctly."""
    os.environ["DISABLE_JOB_WORKER"] = "1"
    os.environ["SECRET_KEY"] = "test-secret-key-auth-session-32-bytes"
    os.environ["ALLOWED_ORIGINS"] = ""

    app_module = _reload_app_v3_with_env()
    client = app_module.app.test_client()

    resp = client.get("/api/health")
    assert resp.status_code == 200

    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    feature_policy = resp.headers.get("Feature-Policy")
    assert feature_policy is not None
    assert "geolocation 'none'" in feature_policy
    assert "microphone 'none'" in feature_policy
    assert "camera 'none'" in feature_policy

    print("✓ Referrer-Policy and Feature-Policy headers present and correct")


def test_hsts_not_sent_without_https_indication():
    """HSTS should not be sent on plain HTTP requests (no X-Forwarded-Proto: https)."""
    os.environ["DISABLE_JOB_WORKER"] = "1"
    os.environ["SECRET_KEY"] = "test-secret-key-auth-session-32-bytes"
    os.environ["ALLOWED_ORIGINS"] = ""

    app_module = _reload_app_v3_with_env()
    client = app_module.app.test_client()

    resp = client.get("/api/health")
    assert resp.status_code == 200

    # In production behind a proxy, X-Forwarded-Proto: https will be set,
    # so HSTS will be present. Without it, HSTS is omitted for safety.
    assert "Strict-Transport-Security" not in resp.headers

    # Other security headers should still be present
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in resp.headers

    print("✓ HSTS omitted on plain HTTP; other headers still present")
