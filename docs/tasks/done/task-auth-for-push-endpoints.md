# Task: Authentication for Push Endpoints

## Goal

Protect push endpoints (OTLP, MLflow, SBOM) with API key or OAuth authentication.

## Acceptance Criteria

- [ ] Push endpoints require authentication (OTLP, MLflow, SBOM push)
- [ ] API key auth via header (simplest path: `X-API-Key` header)
- [ ] API keys stored in config/secrets (not in database)
- [ ] Unauthenticated requests return 401
- [ ] Read-only API endpoints remain open (or optionally protected)
- [ ] Documentation for pipeline owners on how to authenticate

## Files Likely Involved

- backend/auth.py
- backend/routers/otlp.py (add dependency)
- backend/routers/mlflow.py (add dependency)
- backend/routers/sboms.py (add dependency)

## Phase

7 — Polish + Deployment

## Status

Pending
