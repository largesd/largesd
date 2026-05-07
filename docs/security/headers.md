# Security Headers

This document describes the security headers applied to all HTTP responses by the debate_system backend.

## Overview

All responses include the following security headers via **Flask-Talisman**:

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type sniffing attacks |
| `X-Frame-Options` | `DENY` | Prevents clickjacking (pages cannot be embedded in frames) |
| `Content-Security-Policy` | See below | Restricts sources for scripts, styles, images, etc. |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | HSTS — enforces HTTPS for 1 year |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limits referrer leakage on cross-origin requests |
| `Feature-Policy` | `geolocation 'none'; microphone 'none'; camera 'none'` | Disables sensitive browser APIs |

## Content Security Policy (CSP)

```
default-src 'self';
script-src 'self';
style-src 'self';
img-src 'self' data: https:;
font-src 'self' https:;
connect-src 'self';
frame-ancestors 'none';
base-uri 'self';
form-action 'self'
```

### Notes

- No `'unsafe-inline'` is used for `script-src` or `style-src`. All frontend JavaScript and CSS are served from static files.
- `frame-ancestors 'none'` is the modern CSP replacement for `X-Frame-Options` and prevents all frame embedding.
- External images are allowed only over `https:` and `data:` URIs.
- `connect-src 'self'` restricts fetch/XHR/WebSocket to the same origin.

## HSTS (HTTPS Enforcement)

- `force_https` is set to `False` in code because the application is designed to run behind a TLS-terminating reverse proxy (e.g., Nginx, AWS ALB, Cloudflare).
- The proxy must forward the `X-Forwarded-Proto: https` header so that Talisman knows the original request was secure and can emit the `Strict-Transport-Security` header.
- In production, configure the reverse proxy to set `X-Forwarded-Proto: https` for all incoming requests.
- On plain HTTP requests (no `X-Forwarded-Proto: https`), HSTS is intentionally omitted for safety.

## Rate Limiting Headers

When rate limits are enabled (`ENABLE_RATE_LIMITER=true`), the following headers are included on limited responses:

| Header | Description |
|--------|-------------|
| `Retry-After` | Seconds until the client can retry |

## Testing

Run the security headers integration tests:

```bash
python -m pytest tests/integration/test_security_headers.py -v
```

Tests verify that:
- All required headers are present on API responses
- CSP blocks external script injection (scripts from unknown origins are denied)
- HSTS is emitted when the request indicates a secure origin (`X-Forwarded-Proto: https`)
- HSTS is omitted on plain HTTP requests
- Referrer-Policy and Feature-Policy are correctly set
