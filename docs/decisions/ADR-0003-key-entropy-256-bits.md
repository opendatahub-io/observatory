# ADR-0003: API Key Entropy — 256 Bits

## Status

Accepted

## Context

The RFC (Section 5.1) specifies 128-bit minimum entropy with 256-bit recommendation for production. Our initial implementation uses `secrets.token_hex(16)` (128 bits).

Observatory API keys protect push endpoints that ingest telemetry, OTLP traces, MLflow data, and SBOMs. A compromised key could inject false data into pipeline health dashboards. The keys are long-lived (months to years) and the cost of upgrading entropy is zero (one constant change).

## Decision

Use 256-bit entropy: `secrets.token_hex(32)` producing 64 hex chars + `obs_` prefix = 68 character keys.

Key format: `obs_` + 64 hex chars (e.g., `obs_a1b2c3d4...64 chars...`).

**Why:** Per the RFC, 128 bits is the floor for brute-force resistance, but 256 bits provides margin against future attacks and database compromise scenarios where offline cracking is possible. The cost difference is zero — slightly longer keys that are never typed by hand.

## Consequences

- Keys are 68 chars instead of 36 — still fine for env vars, CI secrets, and headers
- Existing 128-bit keys (if any were created) continue to work — validation is hash-based, not length-based
