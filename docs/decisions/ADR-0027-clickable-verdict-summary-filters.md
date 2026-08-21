# ADR-0027: Clickable Verdict Summary Filters

## Status

Accepted

## Context

The Claim Triage page shows high-level verdict counts above the occurrence
table. The same page also has a verdict filter in the occurrence table toolbar.
Today these controls are independent: the count cards communicate state, while
the table filter controls navigation. This makes common triage actions slower,
especially jumping directly to contradicted, insufficient-evidence, or pending
claims.

## Decision

Make summary cards that correspond directly to occurrence verdict filters
clickable. Clicking a verdict-backed card switches to the occurrence tab,
sets the table verdict filter, and resets pagination to the first page.

Supported mappings are:

- Occurrences → all verdicts
- Pending → pending / not verified
- Supported → supported
- Contradicted → contradicted
- Insufficient → insufficient_evidence
- N/A → not_applicable

Cards that do not map to the existing verdict filter, such as Verified,
Explained, Human review, and Jira keys, remain non-clickable until the page has
dedicated filters for those dimensions.

## Consequences

The summary area becomes a lightweight navigation surface without adding API
surface area or duplicating filter state. The selected card must visibly match
the active verdict filter so users can tell whether a count is currently
driving the table. Future non-verdict cards should only become clickable when
they have a concrete table filter or tab destination.
