# M8: Hallucination Detection

**Phase:** Post-launch feature
**Status:** Not Started

## Definition

A claim extraction and verification system that identifies verifiable factual statements in pipeline artifact outputs, checks them against source material already present in the artifacts, and presents results in a triage UI.

## Key Results

- [ ] Claims extracted from artifact markdown files via LLM decomposition
- [ ] Claims verified against source material in the same artifact directory
- [ ] Database stores claims and verdicts with traceability
- [ ] API endpoints for claims with filtering by pipeline, type, verdict
- [ ] `/hallucinations` page with dashboard and claim browser
- [ ] Pipeline detail page shows hallucination summary
