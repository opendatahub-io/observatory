# Phase 8: Claim Assurance and Improvement Loop

Implement the Claimify-aligned claim assurance design from the integrating
`ai-first-pipeline` repository. Add source occurrences, staged extraction
results, extraction evaluation, immutable verification and explanation runs,
structured evidence, UI provenance, and feedback routing while preserving
legacy API reads during migration.

Delivery order:

1. Additive persistence and v2 API contracts.
2. Deterministic segmentation and staged extraction ingestion.
3. Extraction entailment, coverage, and decontextualization evaluation.
4. Immutable verification/explanation history and effective-result policy.
5. Claim assurance UI and workflow gate summaries.
6. Legacy backfill, regression corpus, and compatibility verification.

Database changes use the existing idempotent schema initialization and explicit
backfill functions until an Alembic migration framework is introduced.

The effective verdict policy selects the newest verification run by creation
time and ID. Earlier verification and explanation runs remain immutable and
queryable as the audit history.
