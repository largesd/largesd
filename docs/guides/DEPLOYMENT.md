# Deployment Guide

## Quick Start with Docker Compose

The recommended way to run the debate_system in production is via Docker Compose.

### 1. Prerequisites

- Docker Engine 20.10+
- Docker Compose 1.29+
- A strong `SECRET_KEY` (generate with `openssl rand -hex 32`)

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
# Required for all deployments
SECRET_KEY=your-strong-random-key-here
ENV=production

# Required for real LLM evaluation
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxx
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet

# Admin access (recommended: restricted)
ADMIN_ACCESS_MODE=restricted
ADMIN_USER_EMAILS=admin@example.com,ops@example.com

# CORS (must be explicit in production)
ALLOWED_ORIGINS=https://app.example.com
```

### 3. Build and Run

```bash
docker-compose up --build -d
```

Services:
- **app**: Flask application on port `5000`
- **redis**: Redis 7 Alpine for rate limiter state

### 4. Verify Health

```bash
curl http://localhost:5000/api/health
```

Expected response:

```json
{
  "status": "healthy",
  "version": "3.0",
  "auth_enabled": true,
  "timestamp": "..."
}
```

### 5. View Logs

```bash
docker-compose logs -f app
```

### 6. Stop

```bash
docker-compose down
```

To remove volumes (database data):

```bash
docker-compose down -v
```

## Environment Variable Reference

### Core Runtime

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ENV` | No | `development` | `development`, `staging`, or `production` |
| `SECRET_KEY` | Yes (prod) | `dev-secret-key-change-in-production` | Strong random string for JWT signing |
| `JWT_EXPIRATION_HOURS` | No | `24` | JWT token lifetime in hours |
| `ENABLE_RATE_LIMITER` | No | `true` | Enable Flask-Limiter on mutating `/api/` requests |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection for shared rate-limit state |
| `DEBATE_DB_PATH` | No | `data/debate_system.db` | SQLite database path |
| `ALLOWED_ORIGINS` | No | *(empty)* | Comma-separated CORS allowlist |

### Model + Scoring

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | No | `mock` | `mock`, `openai`, `openrouter`, `openrouter-multi` |
| `NUM_JUDGES` | No | `5` | Number of judges for scoring replicates |
| `FACT_CHECK_MODE` | No | `OFFLINE` | `OFFLINE` or `ONLINE_ALLOWLIST` |
| `OPENROUTER_API_KEY` | Yes (if provider=openrouter) | — | OpenRouter API key |
| `OPENROUTER_MODEL` | Yes (if provider=openrouter) | — | Model ID (e.g. `anthropic/claude-3.5-sonnet`) |
| `OPENROUTER_TIMEOUT_SECONDS` | No | `60` | OpenRouter request timeout |
| `ALLOW_MOCK_FALLBACK` | No | `false` | Allow mock fallback on LLM failure |
| `SITE_URL` | No | — | Site URL for OpenRouter rankings |
| `SITE_NAME` | No | — | Site name for OpenRouter rankings |
| `OPENAI_API_KEY` | Yes (if provider=openai) | — | OpenAI API key |

### Admin Access

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ADMIN_ACCESS_MODE` | No | `authenticated` | `open`, `authenticated`, or `restricted` |
| `ADMIN_USER_EMAILS` | No | — | Comma-separated allowed admin emails (restricted mode) |
| `ADMIN_USER_IDS` | No | — | Comma-separated allowed admin user IDs (restricted mode) |

### Email Ingestion (IMAP)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `IMAP_HOST` | No | `imap.gmail.com` | IMAP server hostname |
| `IMAP_PORT` | No | `993` | IMAP server port |
| `IMAP_USER` | No | — | IMAP username |
| `IMAP_PASSWORD` | No | — | IMAP password or app-specific password |
| `IMAP_FOLDER` | No | `INBOX` | IMAP folder to poll |
| `IMAP_USE_SSL` | No | `true` | Use SSL for IMAP connection |

### Email Acknowledgments (SMTP)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SMTP_HOST` | No | `smtp.gmail.com` | SMTP server hostname |
| `SMTP_PORT` | No | `587` | SMTP server port |
| `SMTP_USER` | No | — | SMTP username |
| `SMTP_PASSWORD` | No | — | SMTP password |

### GitHub Publishing

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_REPO` | No | — | Repository in `owner/repo` format |
| `GITHUB_TOKEN` | No | — | GitHub personal access token |
| `GITHUB_BRANCH` | No | `main` | Target branch |
| `GITHUB_RESULTS_PATH` | No | `data/consolidated_results.json` | File path in repo |
| `GITHUB_AUTHOR_NAME` | No | `Blind Debate Adjudicator` | Git commit author name |
| `GITHUB_AUTHOR_EMAIL` | No | `bot@debate.local` | Git commit author email |

### Processor Behavior

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROCESSOR_DEST_EMAIL` | No | — | Destination email for acknowledgments |
| `SENDER_WHITELIST` | No | — | Comma-separated allowed sender emails |
| `MARK_PROCESSED` | No | `true` | Mark processed emails in IMAP |
| `POLL_INTERVAL` | No | `60` | Polling interval in seconds |

## SSL/TLS Requirements

### Production Setup

The application is designed to run behind a TLS-terminating reverse proxy.

#### Option A: Nginx Reverse Proxy

```nginx
server {
    listen 443 ssl http2;
    server_name debate.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';
    ssl_prefer_server_ciphers on;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Critical:** The proxy must set `X-Forwarded-Proto: https` so that Flask-Talisman emits the HSTS header.

#### Option B: Cloudflare / AWS ALB

Ensure the load balancer or CDN:
1. Terminates TLS
2. Forwards `X-Forwarded-Proto: https` to the origin
3. Does not strip security headers

### Certificate Requirements

- Valid TLS 1.2+ certificate
- HSTS preloading recommended for public deployments
- Auto-renewal (Let's Encrypt + certbot or managed certificates)

## Production Checklist

Before deploying to production:

- [ ] Set strong `SECRET_KEY` (≥ 32 random bytes)
- [ ] Set `ENV=production`
- [ ] Configure `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` (or use `LLM_PROVIDER=mock` for demo)
- [ ] Set `ADMIN_ACCESS_MODE=restricted` and fill `ADMIN_USER_EMAILS`
- [ ] Set explicit `ALLOWED_ORIGINS`
- [ ] Enable HTTPS / TLS termination at the reverse proxy
- [ ] Configure `X-Forwarded-Proto: https` forwarding
- [ ] Enable `ENABLE_RATE_LIMITER=true` and ensure Redis is reachable
- [ ] Configure backup for `/app/data` volume (SQLite database)
- [ ] Review rate limits in `app_v3.py` for your expected traffic
- [ ] Set up log aggregation (the app emits structured JSON logs)
- [ ] Run security scan: `bandit -r backend/`

## Scaling

To scale up judges for high-stakes debates, increase `NUM_JUDGES` in `.env` and restart:

```bash
docker-compose up -d
```

For horizontal scaling (multiple app instances):
1. Use PostgreSQL instead of SQLite (see `migrations/001_initial_postgresql.sql`)
2. Ensure Redis is shared across all instances for rate limiter state
3. Run Alembic migrations on the shared PostgreSQL database

## Rollback

Snapshots are immutable. To "roll back" a decision:
1. Mark the snapshot with an incident via the governance API
2. Generate a new additive correction snapshot

Database backups:
- SQLite: copy `data/debate_system.db` or snapshot the Docker volume
- PostgreSQL: use standard `pg_dump` tools
