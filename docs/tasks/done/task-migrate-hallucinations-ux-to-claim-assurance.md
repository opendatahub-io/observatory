# Task: Migrate Hallucinations UX to Claim-Assurance Data

## Goal

Make the `/hallucinations` triage experience display the effective verdicts,
explanations, and provenance stored by the immutable v2 claim-assurance system.
Keep `/claim-assurance` as the detailed extraction and history view, but remove
the current split in which the primary claims page reports all claims as pending.

## Context

Current verification and explanation jobs write only through:

- `POST /api/v2/claims/verification-runs`
- `POST /api/v2/claims/explanation-runs`

The Hallucinations page still reads `/api/hallucinations/*`, whose queries use
the legacy `claim_verdicts` and `claim_explanations` tables. In the deployed
environment on 2026-07-14, the legacy summary reported 260 pending claims and
zero verified claims while the v2 summary contained 740 supported, 21
contradicted, and 46 insufficient-evidence verification runs plus 38
explanation routes.

The migration must change the read and UX path. Do not seed legacy tables,
backfill projections into them, or add dual writes. Immutable v2 occurrences,
verification runs, explanation runs, evidence records, overrides, and
regression runs remain authoritative.

## UX Contract

- `/hallucinations` is the fast triage view over v2 claim occurrences.
- `/claim-assurance` remains the detailed extraction-run and provenance view.
- A claim occurrence shows its server-selected effective verdict while retaining
  access to all historical verification runs.
- The detail view exposes the effective explanation, remediation, evidence,
  alternatives, human-review state, overrides, and regression status without
  requiring the user to navigate through an extraction run first.
- Identical normalized claim text from different source occurrences must not be
  collapsed into one verdict. If a normalized-claim rollup is retained anywhere,
  it must show an explicit occurrence/verdict distribution rather than inventing
  a single aggregate verdict.
- Canonical v2 names (`supported`, `contradicted`, `insufficient_evidence`, and
  `not_applicable`) are used consistently in filters, badges, counts, and URLs.

## Acceptance Criteria

- [x] The Hallucinations summary cards and filters are computed from v2
      occurrences and effective verdicts, not `claim_verdicts`.
- [x] The claims table displays effective v2 verdict, confidence, severity,
      explanation category, improvement target, and human-review state where
      available.
- [x] Claim detail displays immutable verification history with structured
      evidence and nested explanation, override, and regression history.
- [x] The Explanations tab lists v2 explanation runs and supports category,
      improvement-target, Jira-key, and human-review filters.
- [x] Jira filtering and links operate on claim occurrences without collapsing
      distinct occurrences that share normalized text.
- [x] A direct URL can open or identify a specific occurrence and its history.
- [x] Empty and partially processed states distinguish “not verified,”
      “verified without explanation,” and “explanation requires human review.”
- [x] No new writes or backfills target `claim_verdicts` or
      `claim_explanations`; existing legacy data remains readable only for
      historical compatibility outside the migrated UX.
- [x] Backend tests cover effective-verdict selection, multiple occurrences of
      identical text, explanation history, filters, and legacy-only records.
- [x] Frontend tests cover verdict rendering, explanation rendering, history
      access, filters, deep links, and empty states.
- [x] The production frontend build succeeds and deployed smoke testing shows
      the same v2 counts on `/hallucinations` and `/claim-assurance`.

## Implementation Notes

Prefer adding occurrence-oriented v2 list/triage endpoints or teaching the
Hallucinations page to consume existing v2 endpoints. Do not make the legacy
CRUD layer synthesize mutable records. Effective-verdict selection belongs in
the claim-assurance backend so every consumer uses the same policy.

Likely files:

- `src/backend/crud/claim_assurance.py`
- `src/backend/routers/claim_assurance.py`
- `src/backend/schemas/claim_assurance.py`
- `src/frontend/src/pages/Hallucinations.tsx`
- `src/frontend/src/pages/ClaimAssurance.tsx`
- `src/tests/test_claim_assurance.py`
- frontend tests for the migrated pages

## Out of Scope

- Changing verification or explanation generation behavior
- Writing v2 results into legacy verdict or explanation tables
- Deleting legacy tables or endpoints
- Redesigning extraction assurance or receipt semantics

## blockedBy

None

## Status

Done

## Completion Notes

- Added occurrence-oriented v2 triage summary, list, issue, explanation, and
  facet endpoints. Effective runs are selected consistently by creation time
  and immutable run ID.
- Replaced the legacy Hallucinations reads with v2 occurrence triage, canonical
  verdicts, direct occurrence URLs, and complete verification/explanation
  histories. Legacy tables and endpoints were not modified.
- Updated Claim Assurance's headline verdict panel to consume the same
  effective-occurrence summary; historical runs remain visible in histories.
- Deployed smoke on 2026-07-14 reported 297 occurrences: 230 supported, 12
  contradicted, 3 insufficient-evidence, and 52 not verified. Both migrated
  pages returned the deployed application, and the v2 explanations endpoint
  returned 38 immutable historical runs.
