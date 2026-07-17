# Semantic Claim Consolidation Migration and Rollback

## Scope

Semantic claim consolidation is an additive layer over Claim Assurance v2. It
does not rewrite `claims`, `claim_occurrences`, `claim_verification_runs`,
evidence, explanations, or overrides.

## Schema Additions

- `claims_fts` is an external-content SQLite FTS5 index over exact text
  identities in `claims`.
- `claim_similarity_candidates` stores reproducible unordered candidate pairs
  by retrieval revision.
- `claim_equivalence_decisions` stores deterministic, model-shadow, and human
  decisions with rationale, qualifier comparison, actor/revision provenance,
  confidence, and supersession.
- `claim_canonical_groups` stores reviewed canonical labels and policy revision.
- `claim_canonical_memberships` stores append-only active or retired membership
  rows with a partial uniqueness constraint for one active group per exact text
  identity.
- `claim_consolidation_receipts` records bounded candidate-generation progress.
- `claim_consolidation_evaluations` records labeled-dataset evaluation runs,
  precision/recall counts, false-merge rate, and drift summaries used to
  authorize automatic policies.
- `claim_consolidation_policies` controls automatic assignment. The default is
  disabled and kill-switched. Enabled policies must reference a recorded
  evaluation run that matches the dataset revision and precision threshold.

## Backfill

Run candidate generation in bounded batches with a stable retrieval revision:

```bash
curl -X POST http://localhost:8000/api/v2/claim-consolidation/candidates/generate \
  -H 'Content-Type: application/json' \
  -d '{"run_key":"semantic-backfill-v1","retrieval_revision":"sqlite-fts5-v1","batch_size":500,"shortlist_size":25}'
```

Receipts make this resumable. Reusing a `run_key` with a different retrieval
revision is rejected.

## Evaluation and Authorization Gates

Record evaluation evidence before enabling automatic assignment. The checked-in
baseline can be converted to an evaluation payload, but it does not authorize
automation because it has no automatic equivalent predictions:

```bash
uv run python scripts/audit-claim-consolidation.py \
  --dataset data/semantic-claim-equivalence-v1.json \
  --threshold 0.20 \
  --evaluation-run-id semantic-claim-equivalence-v1-baseline \
  --retrieval-revision token-overlap-threshold-0.20 \
  > /tmp/semantic-evaluation.json
```

Check automatic-assignment and reuse gates before recording or acting on live
evidence:

```bash
uv run python scripts/check-claim-consolidation-gates.py \
  --evaluation-report /tmp/semantic-evaluation.json \
  --reuse-report /tmp/reuse-report.json \
  --minimum-precision 0.99 \
  --maximum-false-merge-rate 0.01 \
  --minimum-reuse-agreement 1.0 \
  --minimum-saved-tokens 1
```

Against a running Observatory API, the same gate check can fetch the latest
recorded evaluation and current reuse simulation directly:

```bash
uv run python scripts/check-claim-consolidation-gates.py \
  --api-base-url http://localhost:8000 \
  --minimum-precision 0.99 \
  --maximum-false-merge-rate 0.01 \
  --minimum-reuse-agreement 1.0 \
  --minimum-saved-tokens 1
```

The API also exposes the same computed status for dashboards and automation:

```bash
curl 'http://localhost:8000/api/v2/claim-consolidation/gate-status?minimum_precision=0.99&maximum_false_merge_rate=0.01&minimum_reuse_agreement=1.0&minimum_saved_tokens=1'
```

To exercise the passing gate path without a populated deployment, use the
synthetic evidence fixtures:

```bash
uv run python scripts/check-claim-consolidation-gates.py \
  --evaluation-report data/semantic-claim-consolidation-synthetic-evaluation.json \
  --reuse-report data/semantic-claim-consolidation-synthetic-reuse-report.json
```

Those fixtures are only for testing gate mechanics. They are not representative
evidence and must not be used to authorize production automatic consolidation or
verification reuse.

If the gate check reports `authorized: false`, keep automatic assignment and
verification reuse disabled. If it reports `authorized: true` for automatic
assignment using representative evidence, post the `evaluation_record` to
`POST /api/v2/claim-consolidation/evaluations`, then update the policy with the
same `evaluation_run_id`, dataset revision, and precision. Verification reuse
remains disabled until a separate reuse policy is defined and reviewed.

## Rollback

Rollback is operationally a read-path rollback:

1. Stop automatic assignment by setting the policy kill switch or leaving
   automatic assignment disabled.
2. Hide or ignore canonical-group projections in API consumers and UI.
3. Leave the additive consolidation tables in place for auditability.

No occurrence, exact text identity, verification run, evidence row, explanation,
or override needs restoration for rollback.

## Current Authorization State

Automatic consolidation is not authorized by the baseline dataset alone. The
baseline audit produced no automatic equivalent predictions, so automatic
precision is undefined. Verification reuse is disabled and exposed only as an
opportunity report. The reuse report simulates source verification runs,
candidate reused runs, agreement with actual independent verdicts, estimated
saved tokens/cost, and invalidation reasons for version, time, evidence,
verifier, repository, and configuration differences.
