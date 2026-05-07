"""API integration tests for authentication endpoints."""

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
from datetime import UTC


def test_register_success(client, csrf_token):
    resp = client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "email": "new.user@example.com",
            "password": "password123",
            "display_name": "New User",
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["email"] == "new.user@example.com"
    assert "access_token" in data
    assert "user_id" in data


def test_register_duplicate_email(client, csrf_token):
    from tests.integration.conftest import _get_csrf_from_cookie

    payload = {
        "email": "dup@example.com",
        "password": "password123",
        "display_name": "Dup User",
    }
    r1 = client.post("/api/auth/register", headers={"X-CSRF-Token": csrf_token}, json=payload)
    assert r1.status_code == 201
    fresh_csrf = _get_csrf_from_cookie(client)
    r2 = client.post("/api/auth/register", headers={"X-CSRF-Token": fresh_csrf}, json=payload)
    assert r2.status_code == 409
    assert r2.get_json()["code"] == "EMAIL_EXISTS"


def test_register_invalid_email(client, csrf_token):
    resp = client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": csrf_token},
        json={"email": "not-an-email", "password": "password123", "display_name": "Bad"},
    )
    assert resp.status_code == 400
    assert "Invalid email format" in resp.get_json()["error"]


def test_register_missing_fields(client, csrf_token):
    resp = client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": csrf_token},
        json={"email": "a@b.com"},
    )
    assert resp.status_code == 400
    assert "VALIDATION_ERROR" == resp.get_json().get("code")


def test_register_password_too_short(client, csrf_token):
    resp = client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": csrf_token},
        json={"email": "short@example.com", "password": "short", "display_name": "Short"},
    )
    assert resp.status_code == 400
    assert "Password must be at least" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
def test_login_success(client, admin_user):
    from tests.integration.conftest import _get_csrf_from_cookie

    resp = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": _get_csrf_from_cookie(client)},
        json={"email": admin_user["email"], "password": "password123"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "access_token" in data
    assert data["email"] == admin_user["email"]


def test_login_invalid_credentials(client, admin_user):
    from tests.integration.conftest import _get_csrf_from_cookie

    resp = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": _get_csrf_from_cookie(client)},
        json={"email": admin_user["email"], "password": "wrongpassword"},
    )
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "INVALID_CREDENTIALS"


def test_login_missing_user(client, csrf_token):
    resp = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf_token},
        json={"email": "nobody@example.com", "password": "password123"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
def test_logout_success(client, auth_headers):
    resp = client.post("/api/auth/logout", headers=auth_headers)
    assert resp.status_code == 200
    assert "Logged out" in resp.get_json()["message"]


def test_logout_missing_token(client, csrf_token):
    resp = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# Current user (/api/auth/me)
# ---------------------------------------------------------------------------
def test_me_success(client, auth_headers, admin_user):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["user_id"] == admin_user["user_id"]
    assert data["email"] == admin_user["email"]


def test_me_missing_token(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "AUTH_REQUIRED"


def test_me_invalid_token(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalidtoken"})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "AUTH_INVALID"


def test_me_expired_token(client, auth_headers, admin_user):
    import os
    from datetime import datetime, timedelta

    import jwt

    expired_payload = {
        "user_id": admin_user["user_id"],
        "email": admin_user["email"],
        "display_name": "Admin",
        "exp": datetime.now(UTC) - timedelta(minutes=5),
        "iat": datetime.now(UTC) - timedelta(hours=1),
        "type": "access",
    }
    secret = os.environ["SECRET_KEY"]
    expired_token = jwt.encode(expired_payload, secret, algorithm="HS256")
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "AUTH_INVALID"
