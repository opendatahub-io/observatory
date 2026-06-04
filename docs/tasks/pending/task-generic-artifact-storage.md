# Task: Generic Artifact Storage

## Goal

Store raw CI job artifacts as blobs instead of requiring specific file schemas. Each pipeline produces different artifacts — there is no standard format across repos.

## Context

There are two artifact sources per pipeline:

### 1. CI Job Artifacts (ZIP attached to GitLab jobs)
The current parser only looks for `otel-summary.json`, `run-manifest.json`, and `mlflow/` paths. Real pipelines produce different files:
- **autofix**: `triage-pipeline.yml` (child pipeline definitions)
- **strat-security-reviews**: `artifacts/security-requirements/*.md`, `artifacts/security-reviews/*.md`

No pipeline currently produces the expected telemetry files.

### 2. Data Repos (separate git repos where pipelines push results)
- **rfe-assessor**: https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-assess-data
- **rfe-autofixer**: https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer-results
- **strat-pipeline**: https://gitlab.com/redhat/rhel-ai/agentic-ci/strat-pipeline-data
- **strat-security-reviews**: https://gitlab.cee.redhat.com/rhoai-security/strat-security-review-artifacts

These repos contain the real pipeline outputs (RFE reviews, strategy documents, security reviews). The pipeline pushes results here after each run. Only rfe-autofixer currently has its data repo configured in `pipeline_artifact_config`.

## Approach Options

1. **Store raw ZIPs as blobs** — download and store the full artifact ZIP per job. Let the frontend list and browse files. Simple, no schema assumptions.
2. **Store file index + selected files** — store a manifest of what's in the ZIP, plus extract and store individual files of interest (markdown, JSON, YAML).
3. **Per-pipeline parser plugins** — each pipeline config declares an artifact handler that knows how to parse its specific outputs.

## Acceptance Criteria

- [ ] Artifacts from real pipelines are stored and retrievable
- [ ] Frontend can browse/view artifacts for a pipeline run
- [ ] No assumption about specific filenames across repos

## Files Likely Involved

- src/backend/collector/artifacts.py
- src/backend/database.py (new table)
- src/frontend/src/pages/PipelineDetail.tsx (artifact browser UI)

## Status

Pending
