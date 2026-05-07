# Release Process

This document describes the versioning and release workflow for the debate_system project.

## Versioning Policy

This project follows [Semantic Versioning 2.0.0](https://semver.org/):

- **MAJOR** (X.y.z) — Incompatible API or data model changes
- **MINOR** (x.Y.z) — New features, backwards compatible
- **PATCH** (x.y.Z) — Bug fixes, backwards compatible

## Release Checklist

Before creating a new release, complete the following steps:

1. **Update version identifiers**
   - Edit `pyproject.toml` and bump the `version` field
   - Edit `VERSION` to match

2. **Update the changelog**
   - Add a new section to `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD`
   - Categorise changes under `### Added`, `### Changed`, `### Deprecated`, `### Removed`, `### Fixed`, or `### Security`

3. **Run the test suite**
   ```bash
   pytest
   ```

4. **Create a signed git tag**
   ```bash
   git tag -a vX.Y.Z -m "Release vX.Y.Z — <short summary>"
   ```

5. **Push the tag**
   ```bash
   git push origin vX.Y.Z
   ```

## Current Release

- **Version:** 0.3.0
- **Tag:** `v0.3.0`
- **Date:** 2026-05-06
- **Highlights:** Production hardening — security headers, CSRF protection, Flask Blueprints decomposition, Redis rate limiting, comprehensive API tests, pre-commit hooks, and CI security scanning.
