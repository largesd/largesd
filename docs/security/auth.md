# Authentication

This document describes the authentication flow and token handling in the debate_system backend.

## Overview

The system uses **JWT (JSON Web Tokens)** with Bearer token authentication. Passwords are hashed with **bcrypt** (not PBKDF2).

## Authentication Flow

### 1. Registration

```
POST /api/auth/register
Content-Type: application/json
X-CSRF-Token: <token>

{
  "email": "user@example.com",
  "password": "secure-password-123",
  "display_name": "User Name"
}
```

Response (`201 Created`):
```json
{
  "user_id": 1,
  "email": "user@example.com",
  "display_name": "User Name",
  "is_admin": false,
  "access_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Validation rules:**
- Email: valid format, 5–255 characters, must be unique
- Password: 8–128 characters
- Display name: 2–100 characters

### 2. Login

```
POST /api/auth/login
Content-Type: application/json
X-CSRF-Token: <token>

{
  "email": "user@example.com",
  "password": "secure-password-123"
}
```

Response (`200 OK`):
```json
{
  "user_id": 1,
  "email": "user@example.com",
  "display_name": "User Name",
  "is_admin": false,
  "access_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

### 3. Authenticated Requests

Include the token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

### 4. Logout

```
POST /api/auth/logout
Authorization: Bearer <token>
```

The server does not maintain a token blacklist; the client discards the token.

## JWT Token Details

### Payload Structure

```json
{
  "user_id": 1,
  "email": "user@example.com",
  "display_name": "User Name",
  "is_admin": false,
  "exp": "2026-05-07T01:27:00Z",
  "iat": "2026-05-06T01:27:00Z",
  "type": "access"
}
```

### Configuration

| Setting | Default | Environment Variable |
|---------|---------|----------------------|
| Algorithm | HS256 | — |
| Secret key | `dev-secret-key-change-in-production` | `SECRET_KEY` |
| Expiration | 24 hours | `JWT_EXPIRATION_HOURS` |

**Production requirements:**
- `SECRET_KEY` must be a strong random string (≥ 32 bytes recommended)
- Default `SECRET_KEY` is rejected in non-development environments at startup

### Token Validation

The `login_required` decorator:
1. Extracts the `Bearer` token from the `Authorization` header
2. Decodes and verifies the signature with `SECRET_KEY`
3. Checks expiration (`exp` claim)
4. Stores user info in Flask `g.user`

Errors:
- Missing header → `401 AUTH_REQUIRED`
- Invalid or expired token → `401 AUTH_INVALID`
- Malformed `Authorization` header → `401 AUTH_REQUIRED`

## Auth Decorators

| Decorator | Purpose |
|-----------|---------|
| `@login_required` | Requires valid JWT; sets `g.user` |
| `@optional_auth` | Sets `g.user` if token present, allows anonymous |
| `@admin_required` | Enforces `ADMIN_ACCESS_MODE` policy (see below) |

## Admin Access Policy

Controlled by `ADMIN_ACCESS_MODE` environment variable:

| Mode | Behavior |
|------|----------|
| `open` | No auth checks (local-only) |
| `authenticated` | Any logged-in user with `is_admin=True` |
| `restricted` | Only users in `ADMIN_USER_EMAILS` or `ADMIN_USER_IDS` allowlists |

**Default:** `restricted`

**Warning:** If set to `open` or `authenticated`, a `RuntimeWarning` is emitted at startup.

## Password Security

- Hashing algorithm: **bcrypt** (via `bcrypt.hashpw`)
- Salt rounds: handled automatically by bcrypt
- Verification: `bcrypt.checkpw`
- Plaintext passwords are never stored or logged

## Identity Blindness

In alignment with the MSD specification §2.A:
- Debate views (posts, snapshots, verdicts) never expose `user_id` or `email`
- The frontend displays no usernames, avatars, or reputation signals
- Auth is only required for administrative or personal-history actions

# Authentication Policy

## Viewing vs Writing
- Viewing public debate content does not require authentication.
- All write-intent actions require authentication:
  - debate proposals
  - direct API posts
  - email-mode posts
  - frame petitions
  - appeals
  - snapshot/admin mutations where applicable

## Email-mode Submissions
- Email-mode submissions require a signed, payload-bound token generated
  after login via POST /api/debate/email-submission-draft.
- The token is embedded in the BDA Submission v3 body as `Auth-Token`.
- Direct emails without a valid token are rejected by the processor.
- Tokens are bound to debate_id, submission_id, side, topic_id, and
  payload_hash. Editing the email body invalidates the token.
- Token TTL defaults to 24 hours and is configurable.

## Debate Proposals
- Debate proposals are submitted exclusively via the authenticated API.
- There is no email-mode proposal submission. Proposals follow the same
  login-gated flow as direct API posts.

## Identity-Blind Surfaces
- Authentication is for abuse reduction and auditability.
- Public debate surfaces (posts, results, dossiers) do not expose author
  identity or user_id.

## Legacy Mode
- Legacy v1/v2 email submissions are rejected by default.
- Do not enable legacy mode (EMAIL_SUBMISSION_AUTH_ALLOW_LEGACY) in
  public deployments.

## Secret Rotation
- Rotating SECRET_KEY (or EMAIL_SUBMISSION_SECRET) invalidates all
  in-flight email submission tokens immediately.
- Because the default TTL is short (24h), this is usually acceptable.
- Operators should rotate secrets during low-activity windows.

## Testing

Run auth integration tests:

```bash
python -m pytest tests/integration/api/test_auth.py -v
```

Tests cover:
- Registration with valid/invalid inputs
- Login with correct/incorrect credentials
- Token expiration handling
- Protected route access with and without tokens
- Admin access under all three `ADMIN_ACCESS_MODE` settings
