# Observatory REST API Reference

Complete reference for the Observatory backend API. Base URL: `http://localhost:8000`.

All endpoints return JSON unless noted. No authentication is required for read endpoints. Write endpoints that ingest telemetry or claims require an API key via `X-API-Key` header.

Date parameters (`since`, `until`) accept ISO-8601 strings (e.g. `2026-07-01T00:00:00Z`).

---

## Pipelines

### GET /api/pipelines

List all registered pipelines with health status.

Response:
```json
{
  "pipelines": [
    {
      "id": 1,
      "slug": "rfe-autofixer",
      "name": "RFE Review Pipeline",
      "description": "...",
      "owner": "...",
      "repo_url": "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer",
      "platform": "gitlab",
      "platform_project_id": "80884610",
      "cron": "...",
      "expected_interval_minutes": 60,
      "timeout_minutes": 120,
      "status": "production",
      "group": "...",
      "display_order": 1,
      "jobs": ["assess-rfe"],
      "job_patterns": null,
      "health": "green",
      "images": [...],
      "skills": [...],
      "shared_libs": [...],
      "jira_contracts": [...],
      "telemetry_config": [...],
      "artifact_config": [...]
    }
  ]
}
```

Health values: `green` (recent success), `yellow` (recent failure or overdue), `red` (consecutive failures), `grey` (no data).

### GET /api/pipelines/{slug}

Get a single pipeline by slug with all metadata sub-resources (images, skills, shared_libs, jira_contracts, telemetry_config, artifact_config).

### GET /api/pipelines/{slug}/health

Returns `{"slug": "...", "health": "green|yellow|red|grey"}`.

### POST /api/pipelines

Create a pipeline.

Body:
```json
{
  "slug": "my-pipeline",
  "name": "My Pipeline",
  "repo_url": "https://gitlab.com/org/repo",
  "platform": "gitlab",
  "description": "optional",
  "owner": "optional",
  "platform_project_id": "optional",
  "expected_interval_minutes": 60,
  "jobs": ["job-name"],
  "job_patterns": ["pattern-*"]
}
```

### PUT /api/pipelines/{slug}

Update a pipeline. All fields optional.

### DELETE /api/pipelines/{slug}

Delete a pipeline and all associated data. Returns 204.

---

## Pipeline Metadata Sub-Resources

Each pipeline has six sub-resource types, all following the same pattern:

- `GET /api/pipelines/{slug}/{resource}` — list
- `POST /api/pipelines/{slug}/{resource}` — create (201)
- `DELETE /api/pipelines/{slug}/{resource}/{id}` — delete (204)

| Resource path | Create body fields |
|---|---|
| `images` | `ref` (required), `name` (optional) |
| `skills` | `repo_url` (required), `branch`, `purpose` |
| `shared-libs` | `repo_url` (required), `purpose` |
| `jira-contracts` | `project` (required), `labels_applied: list[str]` |
| `telemetry-config` | `collector_type`, `endpoint`, `summary_script`, `status` |
| `artifact-config` | `results_repo`, `status` |

---

## Pipeline Runs

### GET /api/pipelines/{slug}/runs

List runs for a pipeline with pagination and filters.

Query parameters:
| Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | 1 | Page number (1-based) |
| `per_page` | int | 20 | Results per page (max 100) |
| `status` | string | — | Filter by status: `success`, `failed`, `running`, `canceled` |
| `since` | string | — | Only runs started after this ISO-8601 timestamp |
| `until` | string | — | Only runs started before this ISO-8601 timestamp |

Response:
```json
{
  "runs": [
    {
      "id": 42,
      "pipeline_id": 1,
      "external_id": "2697604958",
      "job": "assess-rfe",
      "queued_at": "2026-07-22T15:07:00Z",
      "started_at": "2026-07-22T15:11:44Z",
      "finished_at": "2026-07-22T15:45:00Z",
      "duration_seconds": 1996,
      "status": "success",
      "ref": "main",
      "web_url": "https://gitlab.com/.../-/pipelines/2697604958",
      "artifacts_scraped": true
    }
  ],
  "total": 352,
  "page": 1,
  "per_page": 20
}
```

### GET /api/runs/{run_id}

Get a single run by its internal (database) ID.

---

## Collector

### GET /api/collector/status

Returns the collector state for every pipeline — when it last ran, whether it errored, and consecutive failure count.

Response:
```json
[
  {
    "id": 1,
    "pipeline_id": 1,
    "pipeline_name": "RFE Review Pipeline",
    "pipeline_slug": "rfe-autofixer",
    "last_collected_at": "2026-07-22T15:28:42Z",
    "last_run_external_id": null,
    "last_error": null,
    "consecutive_failures": 0
  }
]
```

### POST /api/collector/run

Trigger a one-off collector cycle. Returns 202 immediately; collection runs in the background.

---

## Telemetry

### GET /api/telemetry/summary

Aggregate telemetry across all pipelines (or filtered).

Query parameters: `pipeline` (slug), `since`, `until`.

Response includes: `total_tokens`, `input_tokens`, `output_tokens`, `cost_usd`, `run_count`.

### GET /api/telemetry/trends

Daily trend data points for token usage and cost.

Query parameters: `pipeline`, `since`, `until`.

### GET /api/telemetry/cost

Cost breakdown by pipeline, model, and skill.

Query parameters: `since`, `until`.

### GET /api/pipelines/{slug}/telemetry

Telemetry rows scoped to a single pipeline.

Query parameters: `since`, `until`.

### GET /api/telemetry/run-metrics

Run-level metrics: average duration, pass rate, failure rate.

Query parameters: `pipeline`, `since`, `until`.

### GET /api/telemetry/run-trends

Run status trends over time (daily counts by status).

Query parameters: `pipeline`, `since`, `until`.

### GET /api/telemetry/run-breakdown

Run counts and pass rates broken down by pipeline.

Query parameters: `since`, `until`.

### GET /api/telemetry/dimensions

Dimension summaries for telemetry data (e.g. token usage by model, by skill).

### GET /api/telemetry/spans/{run_id}

All OpenTelemetry spans for a given pipeline run.

Response: `{"spans": [{"trace_id": "...", "span_id": "...", "operation_name": "...", "duration_ms": 1234, ...}]}`.

---

## Artifacts

### GET /api/pipelines/{slug}/runs/{run_id}/artifacts

List artifact files for a run.

**Source types** (`job_artifacts.source`):
| Source | Description |
|---|---|
| `ci_job` | Files extracted from GitLab CI artifact ZIPs |
| `job_trace` | Raw console log downloaded from GitLab's job trace endpoint |
| `data_repo` | Files collected from a data repository |

Response:
```json
{
  "artifacts": [
    {
      "id": 1,
      "source": "ci_job",
      "source_ref": "12345",
      "file_path": "claude-otel.jsonl",
      "file_size": 48291,
      "mime_type": "application/jsonl"
    }
  ],
  "total": 2
}
```

### GET /api/artifacts/{artifact_id}/content

Download raw artifact content. Returns the file with its original MIME type. For `job_trace` artifacts, this returns the full console log as `text/plain` (ANSI codes stripped).

### GET /api/pipelines/{slug}/artifacts/latest

Get artifacts from the most recent run for a pipeline.

---

## Traces (Job Log Analysis)

Trace data is parsed from GitLab job console logs (the raw `job trace` endpoint). The raw log is stored as a `job_artifacts` row with `source='job_trace'` and can be retrieved via `GET /api/artifacts/{id}/content`. The parser extracts structured events, packages, and metadata into the `trace_events`, `trace_packages`, and `trace_metadata` tables.

**Event types** (`trace_events.event_type`):
| Type | Description |
|---|---|
| `command` | Shell commands (`$ ...` lines from CI scripts) |
| `tool_call` | Claude Code tool invocations (`🔧 Bash $ ...`) |
| `error` | Lines containing ERROR, FATAL, Traceback, Exception, or FAILED |
| `section_start` | GitLab CI section start markers |
| `section_end` | GitLab CI section end markers |

**Packages** (`trace_packages`): extracted from microdnf `Installing: name;version;arch;repo` lines and pip `Successfully installed` lines.

**Metadata** (`trace_metadata`): `gitlab_runner_version`, `container_image`, `container_digest`, `exit_code`.

### GET /api/pipelines/{slug}/runs/{run_id}/trace

Get parsed trace events for a run.

Query parameters:
| Param | Type | Default | Description |
|---|---|---|---|
| `type` | string | — | Filter by event type (e.g. `tool_call`, `command`, `error`) |
| `source` | string | — | Filter by source (e.g. `job_trace`) |
| `limit` | int | 200 | Max events (up to 1000) |
| `offset` | int | 0 | Pagination offset |

Response:
```json
{
  "events": [
    {
      "id": 1,
      "source": "job_trace",
      "event_type": "tool_call",
      "timestamp": "2026-07-10T16:13:17.996618Z",
      "content": "Bash: cd /tmp && uv sync --extra dev",
      "line_number": 155
    }
  ],
  "total": 81
}
```

### GET /api/pipelines/{slug}/runs/{run_id}/trace/summary

Summary of a run's trace: event counts by type, packages installed, and metadata (container image, runner version, etc.).

### GET /api/pipelines/{slug}/runs/{run_id}/trace/packages

Packages extracted from the trace (installed during the run via dnf/microdnf or pip).

### GET /api/traces/summary

Aggregate trace summary across all pipelines.

### GET /api/traces/tools

Tool usage summary across all traces (which tools are called, how often).

### GET /api/traces/packages

Package inventory across all traces.

---

## Provenance (Run Reproducibility)

### GET /api/pipelines/{slug}/runs/{run_id}/provenance

Full provenance for a run: commands executed, packages installed, containers used.

Response:
```json
{
  "commands": [
    {"step_order": 1, "command": "pip install ...", "exit_code": 0, "duration_ms": 5000}
  ],
  "packages": [
    {"manager": "pip", "name": "httpx", "version": "0.27.0"}
  ],
  "containers": [
    {"image_ref": "registry.access.redhat.com/ubi9/ubi-minimal:latest", "image_digest": "sha256:..."}
  ]
}
```

### GET /api/pipelines/{slug}/runs/{run_id}/commands

Commands only.

### GET /api/pipelines/{slug}/runs/{run_id}/packages

Packages only. Optional query param: `manager` (e.g. `pip`, `dnf`).

### GET /api/pipelines/{slug}/runs/{run_id}/containers

Containers only.

### GET /api/provenance/packages

Cross-pipeline package inventory (all packages seen across all runs).

### GET /api/provenance/containers

Cross-pipeline container inventory.

---

## OpenTelemetry Explorer

### GET /api/otel/logs/summary

OTEL log record summary. Query params: `pipeline`, `since`, `until`.

### GET /api/otel/logs

Query OTEL log records.

Query parameters:
| Param | Type | Default | Description |
|---|---|---|---|
| `pipeline_run_id` | int | — | Filter to a specific run |
| `trace_id` | string | — | Filter by trace ID |
| `severity` | string | — | Filter by severity (e.g. `ERROR`, `WARN`) |
| `search` | string | — | Full-text search in log body |
| `since` | string | — | Start time filter |
| `until` | string | — | End time filter |
| `limit` | int | 50 | Max results (up to 200) |
| `offset` | int | 0 | Pagination offset |

### GET /api/otel/logs/{log_id}

Get a single OTEL log record.

### GET /api/otel/metrics/summary

OTEL metrics summary. Query params: `pipeline`, `since`, `until`.

### GET /api/otel/metrics/names

List all distinct metric names.

### GET /api/otel/metrics/series

Time-series data for a specific metric.

Required query param: `metric_name`. Optional: `since`, `until`.

---

## CI Definitions

### GET /api/pipelines/{slug}/ci-jobs

Get parsed CI job definitions and includes for a pipeline (from `.gitlab-ci.yml`).

Response:
```json
{
  "jobs": [
    {
      "name": "assess-rfe",
      "stage": "assess",
      "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest",
      "tags": ["aipcc-small-x86_64"],
      "variables": [{"key": "CLAUDE_PROMPT", "value": "...", "masked": false}],
      "scripts": [{"phase": "script", "step_order": 1, "command": "bash scripts/run-claude.sh"}]
    }
  ],
  "includes": [
    {"include_type": "project", "project": "org/repo", "file": "template.yml", "ref": "main"}
  ]
}
```

### GET /api/ci-jobs/images

Cross-pipeline inventory of container images used in CI jobs.

### GET /api/ci-jobs/tags

Cross-pipeline inventory of runner tags used in CI jobs.

---

## SBOMs and Vulnerabilities

### GET /api/sboms

List all stored SBOMs (metadata only).

### GET /api/sboms/{digest}

Get a full SBOM by image digest (digest may contain `/` — use path encoding).

### GET /api/sboms/{digest}/vulnerabilities

Get vulnerabilities for a specific SBOM.

### POST /api/sboms

Push/upsert an SBOM. Requires API key.

Body:
```json
{
  "image_digest": "sha256:abc123...",
  "image_ref": "quay.io/org/image:tag",
  "format": "spdx-json",
  "sbom": { "...spdx document..." },
  "generator": "syft",
  "generated_at": "2026-07-22T00:00:00Z"
}
```

### GET /api/provenance/vulnerabilities

Cross-SBOM vulnerability summary. Optional query param: `severity` (e.g. `CRITICAL`, `HIGH`).

---

## Claim Assurance (v2)

The claim assurance system tracks factual claims made by AI agents, verifies them against source material, and explains failures.

### Extraction

#### POST /api/v2/claims/extraction-runs

Ingest a complete extraction run with source units and claim occurrences. Requires API key.

Body:
```json
{
  "run_key": "unique-run-key",
  "source_file": "path/to/artifact.md",
  "pipeline_slug": "rfe-autofixer",
  "artifact_type": "rfe-autofixer",
  "extractor_revision": "v2.1",
  "repository_revision": "abc123",
  "model": "claude-opus-4-6",
  "harness": "claude-code",
  "configuration": {},
  "units": [
    {
      "unit_key": "section-1",
      "unit_kind": "section",
      "source_locator": "artifact.md#section-1",
      "original_text": "The full original text...",
      "heading_path": ["Top", "Sub"],
      "preceding_context": ["prior paragraph"],
      "following_context": ["next paragraph"],
      "classification": "verifiable",
      "selected_text": "The selected verifiable portion...",
      "selection_rationale": "Contains factual claim about...",
      "ambiguity_status": "clear",
      "occurrences": [
        {
          "claim_text": "Normalized atomic claim text",
          "original_text": "Original phrasing from source",
          "claim_type": "factual",
          "modality": "assertion",
          "jira_keys": ["RHOAI-1234"]
        }
      ]
    }
  ]
}
```

#### GET /api/v2/claims/extraction-runs

List extraction runs. Query params: `limit` (1-200), `offset`.

#### GET /api/v2/claims/extraction-runs/{run_id}

Get extraction run detail with source units and occurrences.

### Verification

#### GET /api/v2/claims/occurrences

List claim occurrences available for verification.

Query parameters:
| Param | Type | Default | Description |
|---|---|---|---|
| `jira_key` | string | — | Filter by linked Jira key |
| `pending_only` | bool | true | Only show unverified occurrences |
| `limit` | int | 200 | Max results (up to 1000) |

#### POST /api/v2/claims/verification-runs

Submit a verification verdict. Requires API key.

Body:
```json
{
  "claim_occurrence_id": 42,
  "verifier_revision": "v2.1",
  "repository_revision": "abc123",
  "model": "claude-opus-4-6",
  "evidence_context_digest": "sha256:...",
  "verdict": "supported",
  "severity": "low",
  "confidence": 85,
  "evidence_summary": "Confirmed by source docs...",
  "evidence": [
    {
      "evidence_type": "source_document",
      "uri": "https://docs.example.com/page",
      "excerpt": "relevant quote...",
      "relationship": "supports",
      "authority": "official_docs"
    }
  ]
}
```

Verdict values: `supported`, `contradicted`, `insufficient_evidence`, `not_applicable`.

#### GET /api/v2/claims/occurrences/{occurrence_id}/effective-verdict

Get the effective verdict for an occurrence, accounting for human overrides.

#### GET /api/v2/claims/occurrences/{occurrence_id}/history

Full event history for an occurrence (extractions, verifications, explanations, overrides).

### Explanation

#### POST /api/v2/claims/explanation-runs

Submit a forensic explanation for a failed verification. Requires API key.

Body:
```json
{
  "verification_run_id": 10,
  "explainer_revision": "v2.1",
  "category": "stale_context",
  "improvement_target": "skill",
  "explanation": "The claim was based on outdated documentation...",
  "contributing_factors": "Skill repo had stale cached copy...",
  "alternative_explanations": "Could also be model hallucination...",
  "remediation": "Update the skill's reference docs",
  "regression_test": "Re-run with updated docs and verify claim flips to supported",
  "human_review_required": false,
  "evidence": [...]
}
```

Category values: `stale_context`, `missing_context`, `retrieval_failure`, `model_hallucination`, `model_reasoning_error`, `ambiguous_source`, `conflicting_sources`, `prompt_induced`, `tool_error`, `other`.

### Overrides and Regression

#### POST /api/v2/claims/human-overrides

Record a human override of an automated verdict.

Body: `{claim_occurrence_id, verification_run_id, actor, decision, rationale}`.

#### POST /api/v2/claims/regression-runs

Record a regression test result after a fix.

Body: `{explanation_run_id, dataset_fqn, implementation_revision, status, metrics, run_uri}`.

#### POST /api/v2/claims/stage-receipts

Record a stage receipt event (tracks cache hits to avoid redundant work).

### Triage Views

#### GET /api/v2/claims/summary

High-level counts: total claims, verdicts by type, pending verifications.

#### GET /api/v2/claims/triage/summary

Triage-focused summary statistics.

#### GET /api/v2/claims/triage/types

Claim type breakdown.

#### GET /api/v2/claims/triage/occurrences

List occurrences with full filtering.

Query parameters:
| Param | Type | Default | Description |
|---|---|---|---|
| `type` | string | — | Filter by claim type |
| `exclude_types` | string | — | Exclude claim types (comma-separated) |
| `verdict` | string | — | Filter by verdict |
| `jira_key` | string | — | Filter by Jira key |
| `search` | string | — | Full-text search |
| `source` | string | — | Filter by source file |
| `pipeline_slug` | string | — | Filter by pipeline |
| `sort` | string | — | Sort field |
| `sort_dir` | string | `desc` | Sort direction |
| `limit` | int | 50 | Max results (1-200) |
| `offset` | int | 0 | Pagination offset |

#### GET /api/v2/claims/triage/issues

Aggregated issue view sorted by verdict severity.

Query params: `sort` (default `contradicted`), `sort_dir`, `limit`, `offset`.

#### GET /api/v2/claims/triage/explanations

List explanations with filters.

Query params: `category`, `improvement_target`, `jira_key`, `human_review_required` (bool), `limit`, `offset`.

#### GET /api/v2/claims/triage/explanation-facets

Available filter facets for explanations (categories, improvement targets).

---

## Claim Consolidation

Groups semantically equivalent claims to avoid redundant verification.

### GET /api/v2/claim-consolidation/summary

Consolidation statistics (groups, candidates, decisions).

### GET /api/v2/claim-consolidation/metrics

Precision/recall metrics for consolidation quality.

### GET /api/v2/claim-consolidation/gate-status

Check if consolidation meets quality gate thresholds.

Query params: `minimum_precision` (default 0.99), `maximum_false_merge_rate` (0.01), `minimum_reuse_agreement` (1.0), `minimum_saved_tokens` (1), `require_zero_reuse_disagreements` (true).

### GET /api/v2/claim-consolidation/candidates

List similarity candidates.

Query params: `status` (`pending`|`decided`|`dismissed`), `decision` (`equivalent`|`related`|`distinct`|`needs_review`), `limit`, `offset`.

### GET /api/v2/claim-consolidation/groups

List canonical claim groups.

Query params: `include_retired` (bool, default false), `limit`, `offset`.

### GET /api/v2/claim-consolidation/groups/{group_id}

Get a canonical group with its member claims.

### GET /api/v2/claim-consolidation/evaluations

List consolidation evaluations. Query param: `limit` (1-200).

### GET /api/v2/claim-consolidation/verification-reuse-opportunities

Report on verification reuse opportunities (how many verifications can be skipped due to consolidation).

### POST /api/v2/claim-consolidation/candidates/generate

Generate similarity candidates. Body: `{run_key, retrieval_revision, claim_id?, batch_size, shortlist_size}`.

### POST /api/v2/claim-consolidation/decisions/shadow

Run automated equivalence decisions. Body: `{decision_revision, limit}`.

### POST /api/v2/claim-consolidation/candidates/{candidate_id}/decisions

Record a human equivalence decision. Body: `{decision, rationale, compared_qualifiers, decider_revision, confidence, actor}`.

### POST /api/v2/claim-consolidation/groups

Create a canonical group. Body: `{canonical_text, normalized_claim_ids, subject_key?, qualifier_summary, policy_revision, actor}`.

### POST /api/v2/claim-consolidation/groups/{group_id}/split

Split claims out of a group. Body: `{normalized_claim_ids, actor, new_canonical_text?, policy_revision}`.

### POST /api/v2/claim-consolidation/groups/{group_id}/retire

Retire a group. Body: `{actor, rationale}`.

### PUT /api/v2/claim-consolidation/policies/{revision}

Create/update a consolidation policy.

### POST /api/v2/claim-consolidation/automatic/{policy_revision}

Apply automatic group assignments. Query param: `limit` (1-1000).

---

## Hallucinations (v1, legacy)

Legacy endpoints for the original hallucination tracking system. Prefer the v2 Claim Assurance endpoints above.

### GET /api/hallucinations/summary

Dashboard summary: total claims, verdict breakdown.

### GET /api/hallucinations/claims

List claims with filters.

Query parameters: `pipeline`, `type`, `exclude_types`, `verdict`, `jira_key`, `search`, `source`, `sort`, `sort_dir`, `limit` (max 200), `offset`.

### GET /api/hallucinations/claims/{claim_id}

Claim detail with verdict and explanation.

### GET /api/hallucinations/by-type

Claim counts grouped by type.

### GET /api/hallucinations/issues

Issues aggregated by verdict status. Query params: `sort`, `sort_dir`, `limit`, `offset`.

### GET /api/hallucinations/explanations

List explanations. Query params: `category`, `jira_key`, `search`, `sort`, `sort_dir`, `limit`, `offset`.

### GET /api/hallucinations/explanations/categories

Available explanation categories.

### GET /api/hallucinations/claims/{claim_id}/log

Returns the raw verification log as `text/markdown`.

### GET /api/hallucinations/source-file

Returns source artifact content as `text/markdown`. Required query param: `path`.

### GET /api/pipelines/{slug}/hallucinations

Hallucination summary scoped to a pipeline.

### GET /api/hallucinations/jira/{jira_key}

All claims linked to a Jira key.

### POST /api/claims/ingest

Ingest claims. Body: `{source_file, pipeline_slug, claims: [{claim_text, claim_type?, jira_keys?: []}]}`.

### POST /api/claims/verdicts

Store verdicts. Body: `{verdicts: [{claim_hash, verdict, confidence, evidence_summary, evidence_source?, evidence_detail?}]}`.

### POST /api/claims/explanations

Store explanations. Body: `{explanations: [{claim_hash, category, explanation, sources_used?}]}`.

### DELETE /api/hallucinations/all

Delete all claims and related data. Returns deletion counts.

---

## MLflow-Compatible API

The Observatory implements a subset of the MLflow REST API for experiment and metric tracking.

Base path: `/mlflow/api/2.0/mlflow`.

### POST /mlflow/api/2.0/mlflow/experiments/create

Create an experiment. Requires API key. Body: `{name}`.

### GET|POST /mlflow/api/2.0/mlflow/experiments/search

Search experiments. Query params: `filter`, `max_results`.

### POST /mlflow/api/2.0/mlflow/runs/create

Create a run. Requires API key. Body: `{experiment_id, start_time?, run_name?, tags?}`.

### POST /mlflow/api/2.0/mlflow/runs/update

Update a run. Requires API key. Body: `{run_id, status?, end_time?, run_name?}`.

### GET /mlflow/api/2.0/mlflow/runs/get

Get a run with metrics and params. Query param: `run_id` (required).

### POST /mlflow/api/2.0/mlflow/runs/search

Search runs. Body: `{experiment_ids?, filter?, max_results}`.

### POST /mlflow/api/2.0/mlflow/runs/log-metric

Log a metric. Requires API key. Body: `{run_id, key, value, timestamp?, step}`.

### POST /mlflow/api/2.0/mlflow/runs/log-param

Log a parameter. Requires API key. Body: `{run_id, key, value}`.

---

## OTLP Ingestion

Receives OpenTelemetry Protocol data over HTTP/JSON.

### POST /otel/v1/traces

Ingest OTLP trace spans. Body: standard OTLP `{resourceSpans: [...]}`.

### POST /otel/v1/logs

Ingest OTLP log records. Body: standard OTLP `{resourceLogs: [...]}`.

### POST /otel/v1/metrics

Ingest OTLP metric data points. Body: standard OTLP `{resourceMetrics: [...]}`.

---

## Knowledge Base

### GET /api/v1/kb/categories

List all KB categories.

### POST /api/v1/kb/categories

Create a category. Body: `{name, description?, sort_order}`.

### PUT /api/v1/kb/categories/{category_id}

Update a category.

### DELETE /api/v1/kb/categories/{category_id}

Delete a category. Returns 204.

### GET /api/v1/kb/articles

List articles. Query params: `category`, `status`, `tag`, `limit` (max 200), `offset`.

### POST /api/v1/kb/articles

Create an article. Body: `{title, body, category_id?, tags?: [], status?, slug?}`.

### GET /api/v1/kb/articles/{article_id}

Get an article.

### PUT /api/v1/kb/articles/{article_id}

Update an article.

### DELETE /api/v1/kb/articles/{article_id}

Delete an article. Returns 204.

### GET /api/v1/kb/search

Full-text search articles. Query params: `q` (required), `limit` (max 100).

---

## Chat

### POST /api/v1/chat/conversations

Create a conversation. Body: `{title?}`.

### GET /api/v1/chat/conversations

List conversations. Query params: `limit` (max 100), `offset`.

### GET /api/v1/chat/conversations/{conversation_id}

Get a conversation with messages.

### DELETE /api/v1/chat/conversations/{conversation_id}

Delete a conversation. Returns 204.

### POST /api/v1/chat/conversations/{conversation_id}/messages

Send a message and stream the response. Body: `{content}`. Returns SSE (`text/event-stream`).

---

## Data Sources

### GET /api/v1/data-sources

List data sources. Query params: `status`, `source_type`.

### POST /api/v1/data-sources

Create a data source. Body: `{name, source_type, endpoint?, description?, config?: {}, status?}`.

### GET /api/v1/data-sources/{source_id}

Get a data source.

### PUT /api/v1/data-sources/{source_id}

Update a data source.

### DELETE /api/v1/data-sources/{source_id}

Delete a data source. Returns 204.

---

## Admin

### GET /api/admin/db-health

Database health: file size and row counts for key tables.

### POST /api/admin/seed

Seed/update pipelines from `org-pulse-config.json`. Idempotent.

### POST /api/admin/purge

Run data retention purge. Returns counts of deleted rows.

### POST /api/admin/backfill-traces

Reset `artifacts_scraped` for runs missing job traces so the next collector cycle re-downloads them. Returns `{"reset": N}`. Follow up with `POST /api/collector/run` to trigger scraping.

Query parameters:
| Param | Type | Default | Description |
|---|---|---|---|
| `pipeline` | string | — | Scope to a pipeline slug |
| `status` | string | — | Scope to a run status (e.g. `failed`) |
| `since` | string | — | Only runs started after (ISO-8601) |
| `until` | string | — | Only runs started before (ISO-8601) |
| `limit` | int | 500 | Max runs to reset (1-5000) |

### POST /api/admin/wipe-runtime-data

Delete all collected/runtime data. Returns counts.

### GET /api/admin/logs

Get buffered log entries. Query params: `level`, `since` (float timestamp).

### GET /api/admin/logs/stream

SSE endpoint for real-time log tailing. Returns `text/event-stream`.

### POST /api/admin/api-keys

Create an API key. Body: `{name, scopes: [], expires_at?}`. Returns the plaintext key (shown only once).

### GET /api/admin/api-keys

List API keys (prefix only).

### DELETE /api/admin/api-keys/{key_id}

Revoke an API key. Returns 204.

### POST /api/admin/credentials

Create a platform credential. Body: `{name, platform, base_url, token, scopes?, expires_at?}`. Token is encrypted at rest.

### GET /api/admin/credentials

List credentials (no tokens exposed).

### PUT /api/admin/credentials/{cred_id}

Update a credential. Body: `{name?, token?, scopes?, expires_at?}`.

### DELETE /api/admin/credentials/{cred_id}

Revoke a credential. Returns 204.

### POST /api/admin/credentials/{cred_id}/test

Test a credential with a lightweight API call. Returns `{success: bool, message: str}`.

---

## Health

### GET /healthz

Liveness check. Returns `{"status": "ok"}`.

### GET /metrics

Prometheus metrics endpoint (provided by `prometheus-fastapi-instrumentator`).

---

## Common Recipes for Pipeline Debugging

### Check if pipelines are collecting data

```bash
curl -s http://localhost:8000/api/collector/status | jq '.[] | {slug: .pipeline_slug, last: .last_collected_at, err: .last_error, failures: .consecutive_failures}'
```

### Find recent failures for a pipeline

```bash
curl -s 'http://localhost:8000/api/pipelines/rfe-autofixer/runs?status=failed&per_page=10' | jq '.runs[] | {id: .id, started: .started_at, url: .web_url}'
```

### Get the trace for a failed run

```bash
# Get parsed error events for run ID 42
curl -s 'http://localhost:8000/api/pipelines/rfe-autofixer/runs/42/trace?type=error' | jq '.events'

# Get Claude tool calls for a run
curl -s 'http://localhost:8000/api/pipelines/rfe-autofixer/runs/42/trace?type=tool_call' | jq '.events'

# Get the raw console log (find the job_trace artifact ID, then download)
ARTIFACT_ID=$(curl -s 'http://localhost:8000/api/pipelines/rfe-autofixer/runs/42/artifacts' | jq '.artifacts[] | select(.source=="job_trace") | .id')
curl -s "http://localhost:8000/api/artifacts/$ARTIFACT_ID/content"
```

### Check what packages a run installed

```bash
curl -s 'http://localhost:8000/api/pipelines/rfe-autofixer/runs/42/provenance' | jq '.packages'
```

### Search for contradicted claims by pipeline

```bash
curl -s 'http://localhost:8000/api/v2/claims/triage/occurrences?pipeline_slug=rfe-autofixer&verdict=contradicted&limit=10' | jq '.occurrences'
```

### Get the full event history for a claim

```bash
curl -s 'http://localhost:8000/api/v2/claims/occurrences/42/history' | jq '.'
```

### Check telemetry costs for last 7 days

```bash
curl -s 'http://localhost:8000/api/telemetry/cost?since=2026-07-15T00:00:00Z' | jq '.'
```

### Trigger a collection and monitor

```bash
curl -s -X POST http://localhost:8000/api/collector/run
# Then poll status:
curl -s http://localhost:8000/api/collector/status | jq '.[].last_collected_at'
```
