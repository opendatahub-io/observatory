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


## 2026-07-16

Agent: codex

Completed:
- Implemented additive semantic claim consolidation for Claim Assurance v2:
  SQLite FTS5 candidate retrieval, reproducible candidates, structured
  equivalence decisions, canonical groups, append-only memberships, resumable
  receipts, policy gates, and metrics.
- Added review APIs and Hallucinations UI controls for candidate decisions,
  canonical group inspection, group creation, reviewed merging, splitting,
  retirement, related claims, source occurrences, and decision provenance.
- Added ingestion-time bounded candidate generation for newly created exact text
  identities while preserving immutable occurrence and verification histories.
- Added a versioned labeled dataset, baseline audit script/report, additive
  identity ADR, and migration/rollback notes.
- Added verification-reuse opportunity reporting; actual reuse remains disabled.
- Added rollback protection for failed reviewed group merges so rejected
  compatibility conflicts do not persist partial human decisions.
- Added durable consolidation evaluation records and required automatic policies
  to reference a recorded passing evaluation run before automatic assignment can
  run.
- Extended the verification-reuse opportunity report with simulation-only
  source/reused run provenance, agreement counts, estimated token/cost savings,
  and invalidation reasons while leaving reuse disabled.
- Extended `scripts/audit-claim-consolidation.py` to emit an
  API-recordable evaluation payload for labeled-dataset audits while preserving
  the non-authorizing zero-prediction baseline.
- Added Claim Consolidation UI panels for automatic-assignment evaluation runs
  and verification-reuse simulation/invalidation evidence without exposing any
  automation enablement control.
- Added `scripts/check-claim-consolidation-gates.py` and tests so operators can
  check automatic-assignment and reuse authorization evidence before changing a
  policy.
- Extended the gate checker to fetch the latest evaluation and reuse simulation
  directly from a running Observatory API with `--api-base-url`.
- Added `GET /api/v2/claim-consolidation/gate-status` for API-visible automatic
  assignment and verification-reuse authorization status.
- Added checked-in synthetic passing evaluation and reuse-report fixtures to
  exercise gate mechanics without treating them as production evidence.

Validation:
- `./.venv/bin/ruff check src/backend/crud/claim_consolidation.py src/backend/routers/claim_consolidation.py src/backend/schemas/claim_consolidation.py src/backend/database.py src/backend/metrics.py src/backend/routers/claim_assurance.py src/backend/crud/claim_assurance.py src/backend/crud/claim_triage.py src/backend/jobs/retention.py src/backend/crud/hallucinations.py src/tests/test_claim_consolidation.py scripts/audit-claim-consolidation.py` — passed
- `./.venv/bin/pytest src/tests/test_claim_consolidation.py src/tests/test_claim_assurance.py` — 18 passed
- `./.venv/bin/pytest src/tests/test_claim_consolidation.py` — 8 passed after
  adding the evaluation-run policy gate
- `./.venv/bin/pytest src/tests/test_claim_consolidation.py` — 8 passed after
  adding reuse simulation and invalidation assertions
- `./.venv/bin/pytest src/tests/test_claim_consolidation_audit.py src/tests/test_claim_consolidation.py src/tests/test_claim_assurance.py` — 19 passed
- `./.venv/bin/python scripts/audit-claim-consolidation.py --dataset data/semantic-claim-equivalence-v1.json --threshold 0.20 --evaluation-run-id semantic-claim-equivalence-v1-baseline --retrieval-revision token-overlap-threshold-0.20` — emitted recordable evaluation with null precision and zero automatic predictions
- `npm test -- ClaimConsolidation` — 1 passed
- `npm run build` — passed with the existing Vite chunk-size warning
- `./.venv/bin/pytest src/tests/test_claim_consolidation_gates.py` — 3 passed
- `./.venv/bin/pytest src/tests/test_claim_consolidation.py` — 9 passed after
  adding the gate-status endpoint
- `npm test -- ClaimConsolidation Hallucinations` — 5 passed
- `npm run build` — passed with the existing Vite chunk-size warning
- `./.venv/bin/python scripts/audit-claim-consolidation.py --dataset data/semantic-claim-equivalence-v1.json --threshold 0.20` — candidate retrieval recall 1.0, candidate volume 11, automatic equivalent predictions 0

Discovered:
- Automatic consolidation is not production-authorized by the baseline dataset;
  automatic precision is undefined because no automatic equivalent predictions
  are emitted.
- Full `./.venv/bin/pytest` currently reports 284 passing and 37 unrelated
  failures in OTLP routing, artifact parser/log expectations, GitLab collector
  mocks, org-pulse fixture expectations, and seed-count tests.
