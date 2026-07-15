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


## 2026-07-14

Agent: codex

Completed:
- Migrated `/hallucinations` from legacy mutable verdict/explanation reads to
  occurrence-oriented immutable Claim Assurance v2 triage endpoints.
- Added effective-verdict summaries and filters, occurrence-specific history,
  structured evidence, explanations, overrides, regression results, Jira
  filtering, direct occurrence URLs, and explicit partial-processing states.
- Updated `/claim-assurance` to show the same effective occurrence verdict
  counts while preserving every historical verification and explanation run.
- Rebuilt and redeployed Observatory; live v2 counts were 297 occurrences, 230
  supported, 12 contradicted, 3 insufficient-evidence, and 52 not verified.

Validation:
- `./.venv/bin/pytest -q src/tests/test_claim_assurance.py` — 10 passed
- `./.venv/bin/ruff check` on changed backend and test files — passed
- `npm test` — 5 passed
- `npm run build` — passed
- `make host-rebuild-observatory` — rollout completed
- Live smoke: v2 triage summary/list/explanations/history returned data and
  `/hallucinations` plus `/claim-assurance` returned HTTP 200.

Discovered:
- The full backend suite currently has 245 passing and 37 unrelated failures
  in OTLP routing, artifact parsing, collector mocks, and stale seed counts.
