# Plan: Migrate Observatory Chat to Claim Assurance v2

## Goal

Make Observatory's built-in chat agent understand and query the immutable
Claim Assurance v2 model. Questions about a claim number, verdict,
explanation, evidence, override, or regression must resolve against claim
occurrences and their server-selected effective runs rather than the legacy
mutable Hallucinations tables.

This is a read-path and agent-tool migration. Do not dual-write, backfill, or
project v2 results into `claim_verdicts` or `claim_explanations`.

## Current State and Problem

The chat tool named `query_claims` currently imports
`backend.crud.hallucinations` and reads the legacy tables:

- `claims`
- `claim_sources`
- `claim_jira_keys`
- `claim_verdicts`
- `claim_explanations`

Its tool description also advertises the legacy verdict names `refuted`,
`insufficient`, and `inconclusive`. The chat system prompt does not explain
normalized claims versus source occurrences or immutable verification history.

Consequently, chat can collapse identical text from distinct occurrences,
interpret an occurrence number as a normalized legacy claim ID, report stale
or absent verdicts, and cannot inspect structured evidence, explanations,
human overrides, or regression runs. File-browsing tools may incidentally find
JSON artifacts, but that is not an authoritative database integration.

Authoritative v2 reads already exist in:

- `backend.crud.claim_triage`
- `backend.crud.claim_assurance`
- `/api/v2/claims/triage/*`
- `/api/v2/claims/occurrences/{occurrence_id}/history`

## Required Semantics

1. A user-facing "claim number" means `claim_occurrences.id` unless the user
   explicitly asks for a normalized claim ID.
2. Search and list results remain occurrence-specific. Never collapse two
   occurrences merely because they share `normalized_claim_id` or text.
3. Effective verification and explanation IDs come from the shared server
   policy: newest by `created_at`, then immutable run ID. The model must not
   select a run itself.
4. Use only canonical verdicts in tool contracts and answers:
   `supported`, `contradicted`, `insufficient_evidence`, and
   `not_applicable`. `pending` is a query state meaning no verification run.
5. Historical verification and explanation runs remain visible and ordered.
6. Human overrides are governance decisions. They do not replace or mutate the
   effective factual verdict.
7. A claim may be verified without an explanation. Chat must report that state
   accurately instead of inventing a root cause.
8. Chat answers should include a direct UI path when useful:
   `/hallucinations?occurrence={id}`.

## Tool Surface

### 1. Migrate `query_claims`

Keep the existing tool name for conversational compatibility, but change its
implementation to v2 occurrence triage.

Recommended input contract:

```json
{
  "occurrence_id": 208,
  "search": "shipped RHOAI platform",
  "claim_type": "factual",
  "verdict": "contradicted",
  "pipeline_slug": "rfe-reviews",
  "source": "RHAIRFE-1-review.md",
  "jira_key": "RHAIRFE-1",
  "limit": 20,
  "offset": 0
}
```

Return occurrence IDs, normalized claim IDs, claim text/type, source locator,
pipeline, Jira keys, effective verification fields, effective explanation
route, human-review state, override count, processing state, total count, and
the direct UI path. Include a top-level marker such as
`data_authority: "claim_assurance_v2"`.

The existing `pipeline_slug` filter must continue to work. Add it to the shared
triage query rather than reimplementing a separate chat-only SQL policy. Treat
`occurrence_id` as an exact filter and keep free-text numeric search behavior
unambiguous.

### 2. Add `get_claim_occurrence_history`

Input:

```json
{"occurrence_id": 208}
```

Use `get_occurrence_history` and return:

- occurrence and source provenance;
- Jira keys and processing state;
- effective verification and explanation IDs;
- every immutable verification run with evidence;
- nested explanation runs with category, improvement target, alternatives,
  remediation, regression test, evidence, and regression executions;
- human overrides bound to their verification runs;
- direct UI path.

Return a clear not-found error for an unknown occurrence. Bound the serialized
payload so it fits the chat tool-result limit without silently dropping the
effective run. If history must be abbreviated, return explicit counts and a
`truncated` marker, preserving effective IDs and the newest runs.

### 3. Add `query_claim_explanations`

Expose immutable v2 explanation runs with filters for category, improvement
target, Jira key, and human-review requirement. Use
`list_triage_explanations`; do not query `claim_explanations`.

### 4. Add `get_claim_assurance_summary`

Return the effective occurrence summary from `get_triage_summary`. If the
historical-run summary is also returned, label it distinctly so chat cannot
confuse effective occurrence counts with total immutable run counts.

## System Prompt Changes

Update `backend.chat.agent._BASE_SYSTEM_PROMPT` to state:

- Claim Assurance v2 is authoritative for current claim questions.
- A normalized claim is reusable text identity; an occurrence is a specific
  assertion in a specific source.
- Effective results are selected by the backend while older runs are audit
  history.
- Overrides govern progression but do not rewrite factual verdicts.
- An absent explanation means no causal explanation run exists; it is not
  evidence that the claim has no cause.
- Prefer structured claim tools over browsing artifact files. Use files only
  for forensic context not represented in the database.

The prompt should direct the model to call history after a list result whenever
the user asks "why," requests evidence, asks about a changed verdict, or names
a specific occurrence.

## Implementation Guidance

Likely files:

- `src/backend/chat/tools.py`
- `src/backend/chat/agent.py`
- `src/backend/crud/claim_triage.py`
- `src/backend/crud/claim_assurance.py` only if a bounded history projection is
  best implemented in the shared layer
- `src/tests/test_chat.py` or a new focused chat-tool test module
- existing Claim Assurance tests when shared query parameters change

Prefer calling shared CRUD functions in-process. Do not make the chat backend
call its own HTTP endpoints, duplicate effective-run SQL, or expose arbitrary
SQL execution to the model.

Remove the chat module's dependency on `backend.crud.hallucinations` for claim
questions. Legacy endpoints and tables may remain for historical compatibility
outside this chat path.

## Delivery Sequence

1. Extend the shared occurrence triage query with exact occurrence and pipeline
   filters, with API parameters if generally useful.
2. Migrate `query_claims` and its schema to occurrence-oriented v2 results.
3. Add occurrence-history, explanation-query, and effective-summary tools.
4. Update the system prompt with v2 identity and effective-history semantics.
5. Add deterministic tool-handler and prompt-contract tests.
6. Run backend tests, lint, frontend production build, and deployed chat smoke
   tests while observing emitted `tool_use` and `tool_result` events.

## Test Plan

Use a temporary v2 database fixture containing:

- two distinct occurrences with identical normalized text;
- multiple verification runs for one occurrence with differing verdicts;
- an effective contradicted run with structured evidence;
- an explanation with alternatives, remediation, human-review state, and a
  regression run;
- a human override bound to the effective verification;
- a pending occurrence;
- a legacy-only claim/verdict that must not affect v2 chat results.

Required tests:

1. `query_claims` returns both duplicate occurrences separately.
2. Exact occurrence lookup returns the requested occurrence, not the same
   numeric normalized claim ID.
3. Canonical verdict and Jira/pipeline/source filters operate on effective v2
   data.
4. Pending means no verification run.
5. History marks the same effective IDs as the list and summary policy.
6. History retains old verification and explanation runs and structured
   evidence.
7. Overrides are returned separately and do not change the effective verdict.
8. Explanation filters return immutable v2 explanation runs.
9. Legacy-only records do not appear as authoritative chat claim results.
10. Unknown occurrence IDs return a useful structured error.
11. Tool results remain under the configured size limit or explicitly report
    truncation without losing effective-state fields.
12. Tool definitions and the system prompt contain canonical v2 vocabulary and
    no legacy verdict instructions.

Do not require a live LLM for unit tests. Test tool handlers directly. A
deployed smoke test may exercise the model and must confirm from SSE events that
the correct structured tools were invoked.

## Acceptance Criteria

- [ ] Chat claim tools no longer read `claim_verdicts` or
      `claim_explanations`.
- [ ] `query_claims` returns occurrence-specific v2 effective state and
      canonical verdicts.
- [ ] Chat can retrieve occurrence 111 and explain that run 667 is effective
      while earlier supported runs remain history.
- [ ] Chat can retrieve occurrence 208, report run 764 as the effective
      contradicted verdict, show the conflicting older run, and distinguish the
      human override from the factual verdict.
- [ ] Chat reports occurrence 208 as verified without explanation rather than
      fabricating a causal route.
- [ ] Chat can query immutable explanations, remediation, evidence, overrides,
      and regression status when those records exist.
- [ ] Duplicate normalized text remains separate by occurrence.
- [ ] Direct Hallucinations occurrence links are included in structured tool
      results.
- [ ] Unit tests cover the v2 tool and prompt contracts without calling an LLM.
- [ ] Focused backend tests and Ruff pass.
- [ ] The production frontend build passes.
- [ ] Deployed chat smoke tests demonstrate v2 tool use for occurrence, verdict,
      evidence, explanation, and override questions.

## Out of Scope

- Changing extraction, verification, or explanation generation behavior
- Creating missing explanations from chat
- Letting chat create human overrides or regression runs
- Deleting legacy Hallucinations tables or endpoints
- Adding arbitrary SQL or unrestricted internal HTTP access to the chat agent

## Rollback

The change is additive except for swapping the implementation of
`query_claims`. Roll back the chat tool and prompt changes if necessary; no
database migration or data rollback should be required. Do not restore legacy
claim reads as a silent fallback because that would reintroduce ambiguous IDs
and stale verdicts. If v2 data is unavailable, return an explicit unavailable
or empty authoritative-result response.
