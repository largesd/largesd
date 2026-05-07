# CSRF Protection

This document describes the Cross-Site Request Forgery (CSRF) protection mechanism used by the debate_system backend.

## Overview

The system uses a **double-submit cookie pattern** for CSRF protection on state-changing API requests that do not use Bearer authentication.

## How It Works

### 1. Token Generation

A cryptographically secure token is generated with `secrets.token_urlsafe(32)` and set as a cookie:

```
Set-Cookie: csrf_token=<token>;
  Secure=<true in prod, false in dev>;
  HttpOnly=False;
  SameSite=Lax;
  Max-Age=3600
```

**Cookie attributes:**
- `Secure`: `true` in production, `false` in development
- `HttpOnly: false` — the cookie must be readable by JavaScript so the frontend can read it and send it back
- `SameSite: Lax` — protects against cross-site POST requests while allowing top-level navigation
- `Max-Age: 3600` — 1 hour expiration

### 2. Token Distribution

The `csrf_token` cookie is set on:
- All HTML page responses (via middleware)
- Login responses
- Register responses
- Logout responses

### 3. Token Validation

For every mutating API request (`POST`, `PUT`, `DELETE`, `PATCH`), the backend:

1. Reads `csrf_token` from the cookie
2. Reads `X-CSRF-Token` from the request header
3. Compares them with constant-time equality
4. Rejects the request with `403 CSRF_INVALID` if either is missing or mismatched

**Exemptions:**
- Safe HTTP methods: `GET`, `HEAD`, `OPTIONS`
- API requests carrying a `Bearer` token in the `Authorization` header
- Non-API routes (static files, HTML pages)

## Frontend Integration

JavaScript must read the `csrf_token` cookie and include it in requests:

```javascript
function getCsrfToken() {
  const match = document.cookie.match(/csrf_token=([^;]+)/);
  return match ? match[1] : '';
}

fetch('/api/auth/register', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-CSRF-Token': getCsrfToken(),
  },
  body: JSON.stringify({ email, password, display_name }),
});
```

## API vs. Browser Flow

| Context | CSRF Required? | How |
|---------|---------------|-----|
| Browser HTML forms / fetch | Yes | Include `X-CSRF-Token` header |
| API clients (Bearer token) | No | Send `Authorization: Bearer <token>` |
| `curl` / scripts (no browser) | Yes | First `GET` a page to receive the cookie, then include header |

## Testing

Run CSRF integration tests:

```bash
python -m pytest tests/integration/test_csrf.py -v
```

Test coverage:
- HTML pages set the `csrf_token` cookie with correct attributes
- Register/login without CSRF token return `403`
- Register/login with invalid CSRF token return `403`
- Register/login with valid CSRF token succeed
- Bearer-authenticated routes skip CSRF validation
- Safe HTTP methods (`GET`, `HEAD`, `OPTIONS`) skip CSRF validation
- Auth endpoints refresh the CSRF cookie on response

## Security Considerations

1. **No state storage:** The token is not stored server-side; validation relies solely on the double-submit comparison.
2. **Token rotation:** A fresh token is issued on every auth response, reducing the window for replay.
3. **SameSite=Lax:** Prevents CSRF from cross-site POST requests in modern browsers.
4. **Secure flag:** Enforced in production to prevent transmission over plain HTTP.
5. **Breach recovery:** Compromising a single CSRF token does not compromise user credentials; it only allows forged requests for the duration of the token lifetime (1 hour) from the same browser session.
