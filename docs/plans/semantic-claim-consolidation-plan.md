# Plan: Semantic Claim Consolidation in Observatory

**Status: Implemented through reviewed grouping; automatic consolidation and
verification reuse remain gated**

## Goal

Reduce duplicate normalized claims in Observatory when multiple source
occurrences express the same factual assertion with different wording, without
losing source provenance or incorrectly combining claims that differ by scope,
version, time, modality, or negation.

The intended result is:

```text
source occurrences
        |
        v
exact text identities
        |
        v
similar-claim search -> equivalence decision -> canonical claim group
                                               |
                                               v
                              occurrence-level verification history
```

## Implementation Status

The initial Observatory implementation now provides the additive identity layer,
candidate retrieval, structured decisions, human-reviewed groups, metrics, and a
verification-reuse simulation report with invalidation reasons. Automatic group
assignment exists only behind an evaluated policy gate, a durable evaluation-run
record, and kill switch. Verification reuse remains report-only.

Current evidence:

- Versioned labeled dataset: `data/semantic-claim-equivalence-v1.json`.
- Baseline report: `docs/notes/semantic-claim-consolidation-baseline.md`.
- Additive identity ADR: `docs/decisions/ADR-0026-additive-semantic-claim-identity.md`.
- Migration and rollback notes: `docs/notes/semantic-claim-consolidation-migration.md`.
- Reuse simulation report: `GET /api/v2/claim-consolidation/verification-reuse-opportunities`.

The plan is not evidence that automatic consolidation is production-authorized.
That authorization still requires representative live evaluation proving the
accepted false-merge budget and drift monitoring requirements in Phase 4. Reuse
authorization still requires agreement and cost-savings evidence from the Phase
5 simulation before any reuse policy is enabled.

Search finds plausible duplicates. A separate decision determines whether the
claims are actually equivalent. Every original claim occurrence and every
verification run remains immutable and traceable.

## Problem

Claim Assurance v2 currently assigns a normalized claim identity from a hash of
trimmed, lowercased claim text. This handles identical text, but not paraphrases.
For example, these assertions receive different normalized claim IDs:

- `rhai-cli is not part of the shipped RHOAI platform`
- `rhai-cli does not exist in the RHOAI component inventory`
- `The RHOAI 3.5-ea.2 component inventory does not include an rhai-cli component`

The recent `rhai-cli` investigation found eleven related occurrences mapped to
ten normalized claim IDs. Some may be truly equivalent; others may differ in
release or inventory scope. The current system has no durable way to express
that distinction.

This creates four risks:

1. The UI can overstate the number of independent findings.
2. Verification and explanation work may be repeated unnecessarily.
3. Recurrence metrics can count wording variants as separate failures.
4. A naive fix could over-merge related but materially different assertions.

## Terminology

- **Occurrence**: one assertion in one source location. Occurrences are never
  removed merely because their wording or meaning overlaps.
- **Text identity**: the existing `claims` row selected by exact normalized-text
  hash.
- **Canonical claim group**: a durable group of text identities judged to make
  the same assertion under compatible qualifiers.
- **Related claim**: a claim about the same subject that is useful for navigation
  but is not safe to treat as equivalent.
- **Candidate**: a pair of claims that search identified for comparison. A
  candidate is not a duplicate until a decision says it is.

## Design Principles

### Optimize for avoiding incorrect merges

Missing a duplicate produces extra work and noise. Incorrectly merging distinct
claims can reuse the wrong verdict and hide a real disagreement. Automatic
consolidation therefore requires high precision; uncertain cases go to review.

### Preserve immutable provenance

Do not rewrite or delete existing claims, occurrences, verification runs,
explanations, overrides, or evidence. Consolidation is an additive interpretation
layer over the existing Claim Assurance v2 records.

### Keep qualifiers in the identity decision

Claims must not be considered equivalent solely because their main nouns and
verbs are similar. The decision must compare at least:

- subject and asserted relationship;
- negation;
- product and version;
- temporal scope;
- modality, such as current fact versus proposal or requirement;
- inventory or deployment scope; and
- clarifications retained during extraction.

### Search proposes; policy decides

SQLite FTS5, Elasticsearch/Lucene, token similarity, or embeddings may retrieve
candidate claims. None of those scores alone authorizes consolidation.

### Separate consolidation from verification reuse

Equivalent wording does not automatically imply that an old verdict is valid
for a new occurrence. Verification reuse also requires compatible product
version, time, evidence context, verifier policy, and source-specific context.
This plan measures reuse opportunities first and enables reuse only in a later,
independently gated phase.

## Component and Skill Responsibilities

The claim skills are maintained with Observatory under `.claude/skills/` and
already enforce occurrence-level provenance. Consolidation must respect those
contracts:

- **`extract-claims`** continues to segment artifacts, extract claims, evaluate
  extraction quality, and submit immutable occurrences. It must not merge
  paraphrases inside model output or omit an occurrence because a similar claim
  already exists. Observatory starts candidate generation after ingestion.
- **`verify-claims`** continues to verify occurrence IDs and write immutable
  verification runs. Canonical group metadata may help select evidence or
  report repeated work, but phases 0 through 4 must not skip verification
  because another group member has a verdict.
- **`explain-claims`** continues to explain a specific occurrence and
  verification run. It may link related group members as forensic context, but
  similar wording alone is not evidence of a shared root cause or propagation.
- **Observatory** owns candidate indexing, durable equivalence decisions,
  canonical group membership, review APIs, UI projections, and metrics.
- **Workflow orchestration** decides when candidate generation or adjudication
  runs and records the retrieval and decision-policy revisions in receipts.

If model adjudication is implemented as an agent skill, add a dedicated
`consolidate-claims` skill with a narrow pair-comparison contract. Do not add
semantic merging to `extract-claims`; extraction answers what each source said,
while consolidation answers how assertions relate across sources.

## Proposed Data Model

Add tables without changing existing occurrence foreign keys:

```text
claim_canonical_groups
  id
  canonical_text
  subject_key
  qualifier_summary
  policy_revision
  created_at
  retired_at

claim_canonical_memberships
  id
  canonical_group_id
  normalized_claim_id
  decision_id
  created_at
  retired_at
  unique active membership per normalized_claim_id

claim_similarity_candidates
  id
  left_normalized_claim_id
  right_normalized_claim_id
  retrieval_method
  retrieval_score
  retrieval_revision
  status = pending | decided | dismissed
  created_at
  unique unordered pair per retrieval revision

claim_equivalence_decisions
  id
  candidate_id
  decision = equivalent | related | distinct | needs_review
  rationale
  compared_qualifiers
  decider_type = deterministic | model | human
  decider_revision
  confidence
  created_at
  supersedes_decision_id
```

The existing `claims` table remains the exact text-identity layer, and
`claim_occurrences.normalized_claim_id` continues to point to it. APIs may add
an effective `canonical_group_id` and canonical text through a join.

Membership changes are append-only: retire an old membership and add a new one
rather than silently rewriting history. Decisions retain the policy/model
revision that produced them.

## Consolidation Pipeline

### 1. Exact-match fast path

Keep the current text-hash behavior for identical text. Improve its deterministic
normalization only after regression tests define the intended treatment of
Unicode, repeated whitespace, and terminal punctuation.

Do not silently change hashes for existing rows. A hash-normalization change
requires a versioned backfill that records aliases between old and new text
identities.

### 2. Candidate retrieval

When a new text identity is created, retrieve a bounded shortlist of existing
claims:

1. Use an Observatory-local SQLite FTS5 index over claim text for lexical
   similarity and operational simplicity.
2. Filter or rerank candidates using structured fields such as claim type,
   product version, modality, and Jira/product context.
3. Include deterministic candidates that share uncommon subject aliases, such
   as `odh-cli`, `kubectl-odh`, and `rhai-cli`, when an alias map is available.
4. Record the query, method, score, and retrieval revision for reproducibility.

Start with FTS5 rather than coupling claim identity to the platform's external
Elasticsearch trace index. Evaluate embeddings only if the measured recall of
lexical retrieval is inadequate.

### 3. Equivalence decision

Compare each candidate pair using a structured contract. The decider must return:

- `equivalent`: same assertion with compatible qualifiers;
- `related`: shared subject or dependency, but not interchangeable;
- `distinct`: materially different assertion; or
- `needs_review`: insufficient confidence or ambiguous scope.

The comparison should test whether each claim entails the other under the same
qualifiers. One-way implication is `related`, not `equivalent`.

Apply deterministic exclusions before model judgment where safe. Examples
include incompatible explicit versions, fact versus proposal, and opposite
negation. Do not use simplistic word checks when the negative word appears in a
quoted name or subordinate clause.

### 4. Group assignment

For an `equivalent` decision:

1. Reuse an existing canonical group when only one side is already a member.
2. Create a new group when neither side is grouped.
3. Require review before joining two existing groups unless every cross-group
   qualifier is compatible.
4. Detect contradictory or non-transitive decisions and route them to review.

Canonical text is a readable label, not a replacement for the source assertion.
Choose it deterministically from a preferred existing member or create a
versioned, reviewed label. Never discard the original texts.

### 5. Read paths and UI

Add API projections and UI controls that show both levels:

- occurrence count;
- exact text-identity count;
- canonical group count;
- member texts and source locations;
- equivalence rationale and decision provenance;
- related-but-distinct claims; and
- unreviewed candidate count.

The default Claim Assurance list should make repeated occurrences understandable
without hiding them. Users must be able to expand a group and inspect every
occurrence and its effective verification.

## Verification Reuse Policy

Do not enable verification reuse in the initial release.

First, add a report that identifies verification runs which appear reusable
because they share:

- canonical group;
- product and version;
- temporal scope;
- evidence-context digest;
- verifier and policy revision; and
- no source-specific qualifier that changes the assertion.

After measuring those cases, define a separate cache policy. A reused result
must reference the original verification run and record why reuse was valid.
Never copy a verdict without provenance, and never let reuse remove an immutable
occurrence history.

## Implementation Phases

### Phase 0: Measure the baseline

1. Add a read-only audit that proposes likely duplicate groups from existing
   claims.
2. Manually label a representative sample as equivalent, related, distinct, or
   uncertain.
3. Include the `rhai-cli` cluster, version-sensitive assertions, negated claims,
   requirements, and repeated claims across artifact types.
4. Report duplicate-group rate, candidate volume, and estimated repeated
   verification work.

**Exit criteria:** a versioned labeled dataset and baseline report establish
how common the problem is and what errors matter.

### Phase 1: Add schema and read-only candidate generation

1. Add the claim FTS5 index and keep it synchronized on claim insert/update.
2. Add candidate and decision tables with API read paths.
3. Backfill candidate pairs without changing any effective claim grouping.
4. Add metrics for candidate generation duration, shortlist size, and failures.

**Exit criteria:** candidate generation runs idempotently against production-like
data and creates no user-visible identity changes.

### Phase 2: Shadow equivalence decisions

1. Implement the structured equivalence contract.
2. Run deterministic and model decisions in shadow mode.
3. Compare results with the labeled dataset and human review.
4. Tune retrieval and decision thresholds for high precision.

**Exit criteria:** the automatic `equivalent` class meets an agreed precision
target, proposed initially at 99%, with recall reported separately rather than
improved by weakening the safety threshold.

### Phase 3: Human-reviewed canonical groups

1. Add a review queue for `equivalent` and `needs_review` candidates.
2. Allow reviewers to create, join, split, and retire canonical groups.
3. Display canonical groups in the Claim Assurance UI while retaining an
   occurrence-level view.
4. Record all reviewer decisions and corrections.

**Exit criteria:** reviewed groups are durable, reversible, and fully traceable;
the `rhai-cli` case can be represented without losing scope differences.

### Phase 4: Gated automatic consolidation

1. Auto-assign only high-confidence pairs covered by the evaluated policy.
2. Send all other candidates to review or leave them ungrouped.
3. Add a kill switch that disables new automatic assignments without affecting
   existing provenance.
4. Monitor incorrect-merge corrections and distribution drift by artifact type.

**Exit criteria:** automatic grouping stays within the accepted false-merge
budget on live data and can be disabled or rolled back without rewriting claim
history.

### Phase 5: Evaluate verification reuse

1. Produce an opportunity report using the compatibility rules above.
2. Compare reused-result simulations with actual independent verdicts.
3. Define invalidation rules for evidence, product, context, verifier, and policy
   revisions.
4. Enable reuse only if simulations show equivalent outcomes and meaningful cost
   savings.

**Exit criteria:** any reuse policy has explicit provenance, invalidation,
agreement, and cost-savings evidence. It is acceptable to finish this phase with
reuse disabled.

## Evaluation Metrics

Track metrics overall and by artifact type, claim type, extractor revision, and
product version:

- percentage of text identities assigned to multi-member canonical groups;
- candidate retrieval recall on the labeled dataset;
- equivalence precision and recall;
- incorrect-merge rate and reviewer split rate;
- missed-duplicate rate;
- candidates requiring human review;
- occurrences, text identities, and canonical groups per source artifact;
- repeated verification runs within compatible canonical groups;
- verification agreement within canonical groups;
- estimated and realized model/token cost savings; and
- time from claim ingestion to consolidation decision.

Do not report a lower claim count as success by itself. The primary safety metric
is whether equivalent claims are grouped without collapsing meaningful
differences.

## Test Strategy

### Deterministic tests

- exact text and capitalization variants;
- whitespace, punctuation, and Unicode normalization;
- stable unordered candidate-pair identity;
- idempotent FTS synchronization and candidate backfill;
- membership retirement and decision supersession;
- group join/split behavior; and
- API projections preserving occurrence and verification IDs.

### Equivalence regression cases

- paraphrases with the same subject and assertion;
- same subject but different predicates;
- opposite negation;
- different explicit product versions;
- current fact versus future proposal or requirement;
- broad platform membership versus inventory-document membership;
- aliases such as `odh-cli`, `kubectl-odh`, and `rhai-cli`;
- one-way implication that must be `related`; and
- ambiguous cases that must abstain.

### Integration tests

- ingest new occurrences and generate candidates;
- review and assign a canonical group;
- query the group through API and UI;
- retain distinct occurrence verification histories;
- split a mistaken group without data loss; and
- rerun after retrieval or decision-policy revision.

## Rollout and Migration

- Use additive schema changes and leave existing claim IDs stable.
- Backfill in bounded batches with resumable receipts.
- Run candidate generation and equivalence decisions in shadow mode first.
- Require manual review before canonical groups affect dashboard counts.
- Version retrieval and decision policies so changed logic can be replayed.
- Keep the existing exact-text view available during rollout.
- Roll back by disabling canonical-group reads; no occurrence, verdict, or
  evidence data should require restoration.

## Security and Governance

- Treat claim and source text as potentially sensitive data; do not send it to
  an unapproved embedding or model service.
- Apply the same model-provider and Vertex AI policy used by existing claim
  stages.
- Record human and model decisions with actor/revision provenance.
- Prevent automatic consolidation when policy inputs are missing or malformed.
- Bound candidate query size and model comparisons to prevent ingestion-driven
  cost amplification.

## Open Decisions

1. Should `claims` remain the exact text-identity table permanently, or be
   renamed in a later migration to make its role clearer?
2. Is SQLite FTS5 sufficient for candidate recall at the expected claim volume?
3. Which model or deterministic entailment method should adjudicate candidate
   pairs?
4. What labeled dataset size is sufficient to authorize automatic grouping?
5. Which qualifiers are hard incompatibilities versus reviewable differences?
6. Should canonical groups cross products or major versions?
7. Should related claims be exposed as navigable edges in the UI?
8. Is verification reuse worth implementing after consolidation is measured?

## Initial Deliverables

1. Baseline duplicate audit and labeled `rhai-cli` regression cases.
2. Observatory task and ADR covering additive canonical-group identity.
3. Claim FTS5 candidate index with shadow-mode metrics.
4. Structured equivalence-decision schema and regression harness, plus a
   dedicated `consolidate-claims` skill if model adjudication is selected.
5. Human review workflow before any automatic consolidation.
