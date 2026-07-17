# Task: Semantic Claim Consolidation

Status: current

## Objective

Execute `docs/plans/semantic-claim-consolidation-plan.md` so differently worded
equivalent claims can be reviewed and grouped without changing immutable claim
occurrences or verification histories.

## blockedBy

None.

## Acceptance Criteria

- A versioned baseline audit and labeled regression dataset measure candidate
  retrieval and equivalence quality, including the `rhai-cli` cases.
- Additive, idempotent schema supports FTS retrieval, candidates, decisions,
  canonical groups, append-only memberships, and resumable receipts.
- Candidate generation and structured shadow decisions are reproducible,
  bounded, observable, and safe across incompatible qualifiers.
- Review APIs and UI support deciding candidates and creating, joining,
  splitting, and retiring groups with complete provenance.
- Automatic assignment is disabled by default, gated by evaluated policy, and
  can be stopped without rewriting history.
- A verification-reuse opportunity report exists, while actual reuse remains
  disabled unless separately authorized by measured evidence.
- Backend and frontend tests cover candidate generation, decisions, group
  lifecycle, occurrence projections, and preservation of verification history.

## Notes

- Existing `claims` IDs remain the exact-text identity layer.
- Existing user changes in `PLAN.md` and `.claude/skills/` are preserved.
- Implemented additive FTS5 candidate retrieval, candidates, decisions,
  canonical groups, append-only memberships, receipts, policy gates, and
  consolidation metrics.
- Implemented review APIs/UI for candidate decisions, group creation, merging,
  splitting, retirement, source-occurrence inspection, related claims, and
  decision provenance.
- Implemented ingestion-time bounded candidate generation for new claims and a
  read-only verification-reuse opportunity report. Reuse remains disabled.
- Automatic assignment remains disabled by default and requires an evaluated
  policy with the kill switch off. Enabled policies must reference a durable
  evaluation run whose dataset revision and precision match the policy gate. It
  skips existing group merges and refuses known qualifier conflicts.
- Current baseline audit at threshold `0.20` reports candidate retrieval recall
  `1.0`, candidate volume `11`, five equivalent labels, and zero automatic
  equivalent predictions; automatic precision is therefore not established.
- Full `./.venv/bin/pytest` is not green for unrelated pre-existing areas:
  OTLP `/v1/traces` tests return 405, artifact parser/log expectations fail,
  and seed/org-pulse counts differ from fixtures. Focused consolidation and
  claim-assurance tests pass.
- Added `claim_consolidation_evaluations` so Phase 4 authorization evidence is
  persisted and visible in consolidation metrics before automatic assignment can
  run.
- Extended the verification-reuse report with simulation-only provenance,
  agreement/disagreement counts, estimated saved token/cost totals, and
  invalidation buckets. Reuse execution remains disabled.
- Extended the baseline audit output with an API-recordable evaluation payload
  so labeled-dataset measurements can be stored directly. The current baseline
  record remains non-authorizing because automatic precision is null.
- Added reviewer-facing UI panels for recorded automatic-assignment evaluations
  and verification-reuse simulation/invalidation evidence. The UI exposes gate
  state but does not enable automatic assignment or reuse.
- Added `scripts/check-claim-consolidation-gates.py` so operators can evaluate
  automatic-assignment and verification-reuse authorization evidence before any
  policy change. It accepts saved JSON reports or fetches the latest evidence
  from a running Observatory API. The current baseline fails the gate by design.
- Added `GET /api/v2/claim-consolidation/gate-status` to expose the same
  computed authorization status to dashboards and automation.
- Added synthetic passing evaluation and reuse-report fixtures for exercising
  gate mechanics without a live deployment. They are explicitly non-production
  evidence.
