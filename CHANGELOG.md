# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-05-06

### Security
- Replaced regex HTML sanitizer with nh3
- Locked down CORS to known origins
- Added CSP, HSTS, X-Frame-Options headers
- Added CSRF protection for HTML forms

### Architecture
- Decomposed app_v3.py into Flask Blueprints
- Decomposed generate_snapshot() into pipeline stages
- Added connection pooling for database
- Added Redis-backed rate limiting

### Testing
- Added comprehensive API integration tests
- Added pipeline stage unit tests

### DevOps
- Locked dependencies with requirements-lock.txt
- Added pre-commit hooks (black, ruff)
- Added mypy type checking
- Added security scanning to CI
