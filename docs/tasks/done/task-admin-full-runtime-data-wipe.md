# Task: Admin Full Runtime Data Wipe

## Goal

Add an Admin action that clears collected Observatory data regardless of retention windows.

## Context

The existing Admin "Run Purge Now" action runs the retention job. It only deletes aged records and intentionally keeps recent telemetry, provenance, SBOMs, hallucination data, traces, artifacts, and other accumulated data. Operators need a separate reset action for local/dev environments where the database should be returned to an empty collected-data state without deleting pipeline configuration or access credentials.

## Acceptance Criteria

- [x] Backend exposes an Admin endpoint for full runtime data wipe.
- [x] Wipe deletes runtime/collected data regardless of age.
- [x] Wipe includes telemetry spans, OTEL logs/metrics, summaries, dimensions, provenance rows, job artifacts, traces, CI definitions, MLflow rows, SBOM/vulnerability rows, hallucination rows, collector state, chat, and knowledge base content.
- [x] Wipe preserves pipeline configuration, API keys, platform credentials, and pipeline metadata.
- [x] Endpoint returns per-table deleted-row counts.
- [x] Admin UI has a clearly separate destructive action with confirmation.
- [x] API tests cover deletion and preservation behavior.

## Files Likely Involved

- src/backend/jobs/retention.py
- src/backend/routers/admin.py
- src/frontend/src/pages/Admin.tsx
- src/tests/test_admin_api.py

## Status

Done

## Notes

- 2026-07-02: Existing `/api/admin/purge` is age-based retention only. Existing `DELETE /api/hallucinations/all` clears claims but does not cover other runtime data.

- 2026-07-02: Added `POST /api/admin/wipe-runtime-data`, Admin UI action, and focused API test coverage. Validation: `uv run pytest src/tests/test_admin_api.py src/tests/test_retention.py`; `npm --prefix src/frontend run build`.
