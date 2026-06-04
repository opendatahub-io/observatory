# Task: Hallucination Detection Proof of Concept

## Goal

Extract claims from a small sample of artifacts (3-5 files from different pipelines), verify them against source material in the same artifact directory, and evaluate the quality of extraction and verification before scaling up.

## Approach

Standalone local script following the same pattern as `collect-artifacts.py` and `ingest-telemetry.py`:

1. `scripts/extract-claims.py` reads artifact markdown from `./var/artifacts/`
2. Calls Vertex AI (Claude) for LLM-based claim decomposition
3. Writes structured JSON results to `./var/claims/{pipeline-slug}/{source-file}.claims.json`
4. DB ingestion is a separate later step (`scripts/ingest-claims.py`)

Uses the Anthropic Python SDK with Vertex AI backend. Needs `anthropic[vertex]` pip package + GCP credentials.

## Acceptance Criteria

- [ ] Script extracts claims from a single RFE assessment result file
- [ ] Script extracts claims from a single security review file
- [ ] Claims are classified by type (factual, architectural, security, scope)
- [ ] At least one verification strategy works (compare claims against source text in the same directory)
- [ ] Output is structured JSON files in ./var/claims/
- [ ] Results are reviewed for quality — are the right claims being extracted? Are verdicts accurate?
- [ ] make extract-claims target

## Files Involved

- scripts/extract-claims.py (new)
- Sample artifacts from ./var/artifacts/

## Notes

Source material is co-located with outputs:
- Security reviews: `*-strat-text.md` (source) + `*-security-review.md` (output with claims)
- RFE assessments: original RFE text is quoted in the assessment markdown
- No Jira API needed — everything is in the artifact files

## Status

Pending
