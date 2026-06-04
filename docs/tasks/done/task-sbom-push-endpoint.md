# Task: SBOM Push Endpoint

## Goal

API endpoint for pipelines or external scanners to push pre-generated SBOMs.

## Acceptance Criteria

- [ ] `POST /api/sboms` accepts SPDX-JSON or CycloneDX-JSON SBOM documents
- [ ] Keyed by image digest (upsert — newer replaces older for same digest)
- [ ] `GET /api/sboms` lists known SBOMs (filterable by image_ref, date range)
- [ ] `GET /api/sboms/{digest}` returns full SBOM document
- [ ] Validates SBOM format before storing
- [ ] Tests

## Files Likely Involved

- backend/routers/sboms.py
- backend/schemas/sboms.py
- backend/crud/sboms.py
- tests/test_sbom_api.py

## Phase

6 — SBOMs + Vulnerability Scanning

## Status

Pending
