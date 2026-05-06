"""
Integration tests for CSRF protection (double-submit cookie pattern).

Acceptance criteria:
  • All state-changing HTML forms include and validate CSRF token
  • Missing/invalid CSRF token returns 403
  • API routes with Bearer auth remain functional without CSRF token
"""
import os
import sys
import shutil
import tempfile
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


def _get_csrf_token(client):
    """Fetch an HTML page to set the CSRF cookie, then return the token value."""
    client.get("/login.html")
    cookie = client.get_cookie("csrf_token")
    return cookie.value if cookie else ""


def _make_temp_db_env(base_env):
    """Return env dict with a temporary DEBATE_DB_PATH."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_csrf.db")
    env = dict(base_env)
    env["DEBATE_DB_PATH"] = db_path
    return env, temp_dir


def test_html_page_sets_csrf_cookie():
    """Serving an HTML page must set the csrf_token cookie."""
    env, temp_dir = _make_temp_db_env({
        "DISABLE_JOB_WORKER": "1",
        "SECRET_KEY": "test-secret-key-auth-session-32-bytes",
        "ALLOWED_ORIGINS": "",
    })
    try:
        app_module = _reload_app_v3_with_env(**env)
        client = app_module.app.test_client()

        resp = client.get("/login.html")
        assert resp.status_code == 200

        cookie = client.get_cookie("csrf_token")
        assert cookie is not None, "HTML response must set csrf_token cookie"
        assert cookie.value, "csrf_token cookie must have a non-empty value"
        assert cookie.secure is False, "Secure flag should be False in test (development) mode"
        assert cookie.http_only is False, "csrf_token cookie must be readable by JavaScript"
        print("✓ HTML page sets CSRF cookie with correct attributes")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_register_without_csrf_token_returns_403():
    """POST to /api/auth/register without CSRF token must return 403."""
    env, temp_dir = _make_temp_db_env({
        "DISABLE_JOB_WORKER": "1",
        "SECRET_KEY": "test-secret-key-auth-session-32-bytes",
        "ALLOWED_ORIGINS": "",
    })
    try:
        app_module = _reload_app_v3_with_env(**env)
        client = app_module.app.test_client()

        resp = client.post("/api/auth/register", json={
            "email": "csrf.test@example.com",
            "password": "password123",
            "display_name": "CSRF Test",
        })
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        data = resp.get_json()
        assert data.get("code") == "CSRF_INVALID"
        print("✓ Register without CSRF token returns 403")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_register_with_invalid_csrf_token_returns_403():
    """POST to /api/auth/register with mismatched CSRF token must return 403."""
    env, temp_dir = _make_temp_db_env({
        "DISABLE_JOB_WORKER": "1",
        "SECRET_KEY": "test-secret-key-auth-session-32-bytes",
        "ALLOWED_ORIGINS": "",
    })
    try:
        app_module = _reload_app_v3_with_env(**env)
        client = app_module.app.test_client()

        # First set a legitimate cookie by visiting a page
        _get_csrf_token(client)
        # Then send a different token in the header
        resp = client.post(
            "/api/auth/register",
            headers={"X-CSRF-Token": "totally-wrong-token"},
            json={
                "email": "csrf.invalid@example.com",
                "password": "password123",
                "display_name": "CSRF Invalid",
            },
        )
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        data = resp.get_json()
        assert data.get("code") == "CSRF_INVALID"
        print("✓ Register with invalid CSRF token returns 403")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_register_with_valid_csrf_token_succeeds():
    """POST to /api/auth/register with valid CSRF token must succeed."""
    env, temp_dir = _make_temp_db_env({
        "DISABLE_JOB_WORKER": "1",
        "SECRET_KEY": "test-secret-key-auth-session-32-bytes",
        "ALLOWED_ORIGINS": "",
    })
    try:
        app_module = _reload_app_v3_with_env(**env)
        client = app_module.app.test_client()

        csrf_token = _get_csrf_token(client)
        resp = client.post(
            "/api/auth/register",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "email": "csrf.valid@example.com",
                "password": "password123",
                "display_name": "CSRF Valid",
            },
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.get_data(as_text=True)}"
        data = resp.get_json()
        assert "access_token" in data
        print("✓ Register with valid CSRF token succeeds")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_login_without_csrf_token_returns_403():
    """POST to /api/auth/login without CSRF token must return 403."""
    env, temp_dir = _make_temp_db_env({
        "DISABLE_JOB_WORKER": "1",
        "SECRET_KEY": "test-secret-key-auth-session-32-bytes",
        "ALLOWED_ORIGINS": "",
    })
    try:
        app_module = _reload_app_v3_with_env(**env)
        client = app_module.app.test_client()

        # First register a user so we can attempt login
        csrf_token = _get_csrf_token(client)
        client.post(
            "/api/auth/register",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "email": "login.csrf@example.com",
                "password": "password123",
                "display_name": "Login CSRF",
            },
        )

        # Now attempt login without CSRF token
        resp = client.post("/api/auth/login", json={
            "email": "login.csrf@example.com",
            "password": "password123",
        })
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        data = resp.get_json()
        assert data.get("code") == "CSRF_INVALID"
        print("✓ Login without CSRF token returns 403")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_login_with_valid_csrf_token_succeeds():
    """POST to /api/auth/login with valid CSRF token must succeed."""
    env, temp_dir = _make_temp_db_env({
        "DISABLE_JOB_WORKER": "1",
        "SECRET_KEY": "test-secret-key-auth-session-32-bytes",
        "ALLOWED_ORIGINS": "",
    })
    try:
        app_module = _reload_app_v3_with_env(**env)
        client = app_module.app.test_client()

        # Register a user
        csrf_token = _get_csrf_token(client)
        client.post(
            "/api/auth/register",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "email": "login.valid@example.com",
                "password": "password123",
                "display_name": "Login Valid",
            },
        )

        # Login with CSRF token
        csrf_token = _get_csrf_token(client)
        resp = client.post(
            "/api/auth/login",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "email": "login.valid@example.com",
                "password": "password123",
            },
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.get_data(as_text=True)}"
        data = resp.get_json()
        assert "access_token" in data
        print("✓ Login with valid CSRF token succeeds")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_bearer_auth_routes_skip_csrf_validation():
    """Authenticated API routes must work without CSRF token."""
    env, temp_dir = _make_temp_db_env({
        "DISABLE_JOB_WORKER": "1",
        "SECRET_KEY": "test-secret-key-auth-session-32-bytes",
        "ALLOWED_ORIGINS": "",
        "ADMIN_ACCESS_MODE": "authenticated",
    })
    try:
        app_module = _reload_app_v3_with_env(**env)
        client = app_module.app.test_client()

        # Register a user
        csrf_token = _get_csrf_token(client)
        reg = client.post(
            "/api/auth/register",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "email": "bearer.csrf@example.com",
                "password": "password123",
                "display_name": "Bearer CSRF",
            },
        )
        assert reg.status_code == 201
        token = reg.get_json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # Attempt an authenticated POST without CSRF token
        resp = client.post(
            "/api/debate-proposals",
            headers=auth_headers,
            json={
                "motion": "Resolved: CSRF should be skipped for Bearer auth.",
                "moderation_criteria": "Standard civility.",
                "debate_frame": "Evaluate the motion.",
            },
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.get_data(as_text=True)}"
        print("✓ Bearer auth routes skip CSRF validation")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_safe_methods_skip_csrf_validation():
    """GET/HEAD/OPTIONS requests must not require CSRF token."""
    env, temp_dir = _make_temp_db_env({
        "DISABLE_JOB_WORKER": "1",
        "SECRET_KEY": "test-secret-key-auth-session-32-bytes",
        "ALLOWED_ORIGINS": "",
    })
    try:
        app_module = _reload_app_v3_with_env(**env)
        client = app_module.app.test_client()

        resp = client.get("/api/health")
        assert resp.status_code == 200

        resp = client.head("/api/health")
        assert resp.status_code == 200

        resp = client.options("/api/health")
        assert resp.status_code == 200
        print("✓ Safe HTTP methods skip CSRF validation")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_auth_endpoints_set_csrf_cookie():
    """Login and register responses must set a fresh csrf_token cookie."""
    env, temp_dir = _make_temp_db_env({
        "DISABLE_JOB_WORKER": "1",
        "SECRET_KEY": "test-secret-key-auth-session-32-bytes",
        "ALLOWED_ORIGINS": "",
    })
    try:
        app_module = _reload_app_v3_with_env(**env)
        client = app_module.app.test_client()

        csrf_token = _get_csrf_token(client)
        resp = client.post(
            "/api/auth/register",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "email": "cookie.check@example.com",
                "password": "password123",
                "display_name": "Cookie Check",
            },
        )
        assert resp.status_code == 201

        cookie = client.get_cookie("csrf_token")
        assert cookie is not None, "Register response must set csrf_token cookie"
        assert cookie.value, "Register response csrf_token must be non-empty"
        print("✓ Auth endpoints set CSRF cookie")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
