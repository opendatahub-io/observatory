# ADR-0013: CI Definition Ingestion

## Status

Accepted

## Context

Observatory collects raw pipeline definitions to `./var/definitions/` (ADR-0011, ADR-0012) but this data is only on the filesystem. There is no way to query across pipelines ("which pipelines use this image?", "what runner tags are in use?", "which jobs install Claude via curl?"). The existing metadata tables (`pipeline_images`, `pipeline_skills`) are populated from manually-maintained org-pulse-config.json and don't reflect the actual `.gitlab-ci.yml` definitions.

## Decision

Parse `.gitlab-ci.yml` files from collected definitions into structured database tables. A standalone ingestion script (`scripts/ingest-definitions.py`) reads YAML from `./var/definitions/`, parses job definitions, and inserts structured records into five new tables: `ci_jobs`, `ci_job_tags`, `ci_job_variables`, `ci_job_scripts`, `ci_includes`.

This follows the collection/ingestion separation from ADR-0011: raw files are collected to the filesystem, then a separate step parses and stores structured data.

The schema is intentionally flat — no stage ordering table, no dependency graph, no rule evaluation. These can be added later if needed. The goal is to answer practical questions about pipeline infrastructure.

## Consequences

Positive:
- Cross-pipeline queries: "which images?", "which runners?", "what Claude model?"
- Pipeline detail pages show actual CI job definitions, not manually-maintained metadata
- Drift detection: compare org-pulse-config declarations against actual CI configs
- Foundation for cost modeling, compliance auditing, infrastructure planning

Negative:
- YAML parsing is fragile — GitLab CI has complex features (includes, extends, anchors, rules) that are hard to fully resolve
- Only parses local `extends` — remote includes are recorded but not fetched/merged
- Requires re-running ingestion when CI configs change
