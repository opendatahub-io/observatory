# Session Log

## 2026-06-01

Agent: claude-opus-4-6

Completed:
- Scaffolded agent work ledger directory structure
- Created AGENTS.md with project conventions
- Created 7 phase plan docs (docs/plans/phase-01 through phase-07)
- Created 6 milestone docs (M1-bootstrap through M6-production)
- Decomposed all phases into 38 task files in docs/tasks/pending/
- Rewrote PLAN.md as an index linking to phases, milestones, and tasks
- Added provenance (commands, packages, containers, SBOMs, vulnerabilities) to data model and plan

Discovered:
- Original PLAN.md was a symlink to another repo — created PLAN.md as a standalone file

Next:
- Begin Phase 1 implementation when ready


## 2026-07-02

Agent: codex

Completed:
- Added Admin full runtime data wipe endpoint and UI action.
- Preserved pipeline configuration, pipeline metadata, API keys, and platform credentials during wipe.
- Added API coverage for runtime deletion and configuration preservation.

Discovered:
- Existing retention purge is age-based and still returns OTEL log/metric counts; updated stale retention test expectation.

Validation:
- uv run pytest src/tests/test_admin_api.py src/tests/test_retention.py
- npm --prefix src/frontend run build


## 2026-07-12

Agent: codex

Completed:
- Added additive claim-assurance persistence, idempotent legacy backfill, and
  v2 APIs for extraction, verification, explanation, evidence, overrides,
  regression runs, receipts, histories, and metrics.
- Added element-level coverage and decontextualization comparison provenance.
- Added the Claim Assurance UI with source decisions, occurrences, evidence,
  version histories, improvement routes, overrides, and replay status.
- Added a backup/rollback migration runbook and lifecycle API tests.

Validation:
- `pytest -q src/tests/test_claim_assurance.py src/tests/test_admin_api.py` — 9 passed
- `ruff check` for changed backend/test files
- `npm --prefix src/frontend run build`

Discovered:
- The broader checkout has unrelated existing failures in OTLP routing,
  artifact parsing expectations, collector mocks, and stale seed-count tests;
  focused legacy admin compatibility and claim-assurance suites pass.
