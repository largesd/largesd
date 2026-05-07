"""pytest fixtures for integration API tests."""

import importlib
import os
import shutil
import tempfile

import pytest


@pytest.fixture
def app():
    """Create a fresh Flask app with an isolated temporary database."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")

    env_keys = [
        "DEBATE_DB_PATH",
        "SECRET_KEY",
        "ADMIN_ACCESS_MODE",
        "ADMIN_USER_EMAILS",
        "ADMIN_USER_IDS",
        "DISABLE_JOB_WORKER",
        "ENABLE_RATE_LIMITER",
        "ALLOWED_ORIGINS",
        "ENV",
        "LLM_PROVIDER",
        "PROCESSOR_DEST_EMAIL",
    ]
    old_env = {k: os.environ.get(k) for k in env_keys}

    os.environ["DEBATE_DB_PATH"] = db_path
    os.environ["SECRET_KEY"] = "test-secret-key-32-bytes-long!!!"
    os.environ["ADMIN_ACCESS_MODE"] = "authenticated"
    os.environ["ADMIN_USER_EMAILS"] = ""
    os.environ["ADMIN_USER_IDS"] = ""
    os.environ["DISABLE_JOB_WORKER"] = "1"
    os.environ["ENABLE_RATE_LIMITER"] = "false"
    os.environ["ALLOWED_ORIGINS"] = ""
    os.environ["ENV"] = "development"
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["PROCESSOR_DEST_EMAIL"] = "processor@example.com"

    import backend.app_v3 as app_v3

    app_v3 = importlib.reload(app_v3)
    application = app_v3.create_app()
    application.config["TESTING"] = True

    yield application

    # Teardown
    try:
        app_v3.extensions.debate_engine.shutdown()
    except Exception:
        pass
    shutil.rmtree(temp_dir, ignore_errors=True)
    for key in env_keys:
        if old_env[key] is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_env[key]


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf_token(client):
    """Obtain a valid CSRF token cookie via an HTML page request."""
    client.get("/login.html")
    cookie = client.get_cookie("csrf_token")
    return cookie.value if cookie else ""


@pytest.fixture
def admin_user(client):
    """Register the first user (auto-promoted to admin) and return auth info."""
    client.get("/login.html")
    csrf = _get_csrf_from_cookie(client)
    resp = client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": csrf},
        json={
            "email": "admin@example.com",
            "password": "password123",
            "display_name": "Admin User",
        },
    )
    data = resp.get_json()
    return {
        "user_id": data["user_id"],
        "email": data["email"],
        "token": data["access_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


def _get_csrf_from_cookie(client):
    """Read the current csrf_token cookie value."""
    cookie = client.get_cookie("csrf_token")
    return cookie.value if cookie else ""


@pytest.fixture
def regular_user(client, admin_user):
    """Register a non-admin user and return auth info."""
    # admin_user fixture already seeded the first admin, so this user will NOT become admin
    fresh_csrf = _get_csrf_from_cookie(client)
    resp = client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": fresh_csrf},
        json={
            "email": "user@example.com",
            "password": "password123",
            "display_name": "Regular User",
        },
    )
    data = resp.get_json()
    return {
        "user_id": data["user_id"],
        "email": data["email"],
        "token": data["access_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


@pytest.fixture
def auth_headers(admin_user):
    """Return Authorization header for the admin user."""
    return admin_user["headers"]


@pytest.fixture
def regular_auth_headers(regular_user):
    """Return Authorization header for the regular user."""
    return regular_user["headers"]
