# Task: Claim Assurance and Improvement Loop

Status: done

## Objective

Implement the Claimify-aligned extraction, evaluation, verification,
explanation, provenance, and improvement loop described in
`docs/plans/phase-08-claim-assurance.md` and the integrating repository's
`docs/plans/claimify-aligned-claim-assurance-plan.md`.

## Acceptance Criteria

- Source units and claim occurrences retain stable source context.
- Selection, ambiguity, decomposition, and extraction evaluation are durable.
- Verification and explanation runs are immutable and versioned.
- Evidence records are structured and reproducible.
- Legacy claim APIs remain readable during migration.
- UI and workflows expose assurance status and improvement routing.
- Regression and API tests cover the complete lifecycle.

## Result

Added additive v2 persistence and APIs, legacy backfill, element-level
coverage and decontextualization evidence, immutable histories, human override
and regression audit records, receipt/resource metrics, and a Claim Assurance
UI tracing source decisions through improvement replay status.

Database changes follow the repository's idempotent schema initialization.
`docs/claim-assurance-migration.md` documents backup-based rollback.
