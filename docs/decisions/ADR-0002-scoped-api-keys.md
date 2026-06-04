# ADR-0002: Scoped API Keys with Limited Blast Radius

## Status

Accepted

## Context

Observatory protects push endpoints (OTLP, MLflow, SBOM) with a single global `OBSERVATORY_API_KEY` environment variable. Every pipeline and external system shares one key. If a key leaks from one pipeline's CI config, an attacker can push data as any pipeline.

Pipeline owners need keys scoped to their repos. Shared infrastructure (e.g., the agentic-ci library) needs multi-repo keys. All keys need secure storage (hashed, not plaintext).

## Decision

Implement a database-backed API key management system with per-key scopes.

**Key properties:**
- Format: `obs_` prefix + 32 hex chars — greppable in logs and CI configs
- Storage: SHA-256 hash only — plaintext shown once at creation, never stored
- Scopes: JSON array of pipeline slugs (`["rfe-review"]`) or `["*"]` for unrestricted
- Lifecycle: optional expiration, revocable, last-used tracking
- Backwards compatible: `OBSERVATORY_API_KEY` env var works as a fallback global key

**Auth flow:** hash incoming key → DB lookup → check active/expiry/scope → allow or reject (401 invalid, 403 scope mismatch).

**Scope enforcement:** OTLP receiver extracts target pipeline from `service.name`. MLflow and SBOM endpoints without inherent pipeline context require `["*"]` scope.

## Consequences

Positive:
- Key compromise limited to scoped pipelines
- Audit trail via last_used_at
- Keys revocable without restarting the service
- Pipeline owners can self-serve key creation via admin UI

Negative:
- Auth adds a DB query per push request (mitigated: SQLite is fast for single-row lookups)
- Key management is another thing to operate (mitigated: admin UI makes it visual)
- Existing single-key deployments need migration (mitigated: env var fallback preserves compatibility)
