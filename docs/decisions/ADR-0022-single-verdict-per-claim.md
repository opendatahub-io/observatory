# ADR-0022: Single Verdict Per Claim with Aggregated Evidence

## Status

Accepted

## Context

Claims can appear in multiple source files. For example, "Gen AI Studio currently performs guardrail checks by routing requests through Llama Stack" was extracted from three different strategy documents (RHAISTRAT-1299 twice, RHAISTRAT-1582 once). The verification script joined `claim_sources` to get one row per (claim, source_file) pair, producing three separate verification runs for the same claim — each with different evidence and potentially different verdicts:

- Run 1: **supported (99%)** — source file contained the original RFE text with the exact quote
- Run 2: **supported (97%)** — same evidence, different run
- Run 3: **insufficient (92%)** — different source file that didn't contain the relevant context

This inconsistency makes the hallucination dashboard unreliable — the same claim shows multiple conflicting verdicts depending on which source file happened to be verified.

## Decision

Verify each claim exactly once, aggregating evidence from ALL its source files into a single verification call.

### Changes

1. **Query**: `GROUP_CONCAT(DISTINCT cs.source_file)` groups by `c.id` instead of joining one row per source file
2. **Evidence gathering**: `process_claim` iterates all source files, merges their evidence (co-located files, arch-query, NFR checklist) into one combined evidence block
3. **Deduplication**: Evidence sources and arch-query results are deduplicated after merging
4. **One verdict**: A single `claim_verdicts` row per claim, informed by the best available evidence from all sources

### Before

```
Claim 3128 → source_file_1 → verify → supported (99%)
Claim 3128 → source_file_2 → verify → supported (97%)
Claim 3128 → source_file_3 → verify → insufficient (92%)
```

### After

```
Claim 3128 → [source_file_1, source_file_2, source_file_3] → verify once → supported (99%)
```

## Consequences

Positive:
- Consistent verdicts — each claim has exactly one verdict
- Better evidence — more source files means more context for the judge
- Fewer API calls — one per claim instead of one per (claim, source_file) pair
- Cleaner UI — no duplicate rows with conflicting verdicts

Negative:
- Larger evidence blocks may hit token limits on complex claims with many sources
- Loses per-source-file granularity (which specific file supported the claim)
- Evidence truncation at 50k chars may cut relevant content from later source files
