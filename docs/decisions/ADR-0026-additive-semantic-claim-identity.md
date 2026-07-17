# ADR-0026: Additive Semantic Claim Identity

## Status

Accepted

## Context

Claim Assurance identifies exact text variants by a normalized-text hash.
Paraphrases therefore appear as independent findings, but merging them into the
existing identity would destroy the distinction between source assertions and
could reuse verdicts across incompatible versions, time scopes, or modalities.

## Decision

Keep `claims` as the permanent exact-text identity and add an independent,
versioned canonical-group layer. SQLite FTS5 retrieves bounded candidate pairs;
retrieval scores never authorize grouping. Structured equivalence decisions
compare subject, relationship, negation, product/version, time, modality,
inventory scope, and retained clarifications.

Occurrences, verification runs, explanations, evidence, overrides, decisions,
and memberships remain immutable. Membership corrections retire the active row
and append a replacement. Human-reviewed grouping is enabled before gated
automatic assignment. Verification reuse remains a separately evaluated policy
and is disabled by this decision.

Changed retrieval and decision policies are replayed under new revisions.
Automatic assignment requires an evaluated precision gate and a runtime kill
switch; disabling canonical reads returns the product to exact-text behavior
without restoring data.

## Consequences

The system can report occurrence, text-identity, and canonical-group counts
without hiding provenance. Candidate generation stays local and operationally
simple. Storage and review work increase, and canonical group membership cannot
be treated as proof that evidence or verdicts are reusable for every occurrence.
