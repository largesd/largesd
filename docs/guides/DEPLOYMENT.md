# Deployment Guide

## Quick Start with Docker Compose

```bash
# 1. Set environment variables
cp .env.example .env
# Edit .env and set SECRET_KEY, OPENROUTER_API_KEY, etc.

# 2. Build and run
docker-compose up --build -d

# 3. Verify health
curl http://localhost:5000/api/health
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ENV` | No | `development` (default), `staging`, or `production` |
| `SECRET_KEY` | Yes (prod) | Strong random string for JWT signing |
| `ENABLE_RATE_LIMITER` | No | Enable Flask-Limiter protection for mutating `/api/` requests (default: `true`) |
| `LLM_PROVIDER` | No | `mock`, `openrouter`, `openrouter-multi` |
| `OPENROUTER_API_KEY` | Yes (if provider=openrouter) | OpenRouter API key |
| `OPENROUTER_MODEL` | Yes (if provider=openrouter) | Model ID (e.g. `anthropic/claude-3.5-sonnet`) |
| `NUM_JUDGES` | No | Number of judges (default: 5) |
| `FACT_CHECK_MODE` | No | `OFFLINE` or `ONLINE_ALLOWLIST` |
| `ADMIN_ACCESS_MODE` | No | `open`, `authenticated`, `restricted` |

## Production Checklist

- [ ] Set strong `SECRET_KEY`
- [ ] Set `ENV=production`
- [ ] Configure `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`
- [ ] Set `ADMIN_ACCESS_MODE=restricted` and fill `ADMIN_USER_EMAILS`
- [ ] Enable HTTPS / TLS termination
- [ ] Configure backup for `/app/data` volume
- [ ] Review mutating API rate limits in `app_v3.py`

## Scaling

To scale up judges for high-stakes debates, increase `NUM_JUDGES` in `.env` and restart:

```bash
docker-compose up -d
```

## Rollback

Snapshots are immutable. To "roll back" a decision, mark the snapshot with an incident and generate a new additive correction snapshot.
