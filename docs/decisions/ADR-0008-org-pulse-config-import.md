# ADR-0008: Import from org-pulse-config.json with Job-Filtered Collection

## Status

Accepted

## Context

Observatory's original `data/seed.json` was hand-crafted and diverged from the org-pulse project's `org-pulse-config.json`, which is the authoritative pipeline registry. The org-pulse config has richer data: pipeline grouping (`group`), display ordering (`order`), explicit job names (`jobs`), and job glob patterns (`jobPatterns`).

The job patterns are critical for repos that host multiple logical pipelines. The `autofix` repo runs triage, bugfix, vLLM backport, and status summary as separate CI jobs — without job filtering, the collector can't distinguish which runs belong to which Observatory pipeline.

## Decision

1. **`org-pulse-config.json` is the preferred seed format.** The seeder auto-detects it (checks for nested `repo` objects) and falls back to `seed.json` if not present. The camelCase nested format is mapped to our snake_case flat schema at import time.

2. **Four new columns on `pipelines`:**
   - `group` — UI grouping (RFE, Strats, Bugs, Epics)
   - `display_order` — sort ordering within the status board
   - `jobs` — JSON array of exact CI job names to collect (e.g., `["autofix-rfe"]`)
   - `job_patterns` — JSON array of glob patterns matched with `fnmatch` (e.g., `["iterate-*", "triage-*"]`)

3. **Job-filtered collection.** When a pipeline has `jobs` or `job_patterns` configured, the GitLab collector fetches the jobs list for each CI pipeline and only creates a run if at least one job name matches. Pipelines without filters collect everything (backwards compatible). Same pattern for GitHub Actions (matches on workflow `name`).

## Consequences

Positive:
- Single source of truth for pipeline definitions shared with org-pulse
- Multiple logical pipelines can share a GitLab project without duplicate runs
- UI can group and order pipelines meaningfully
- Backwards compatible — pipelines without filters work as before

Negative:
- Job filtering adds API calls (one `GET /jobs` per CI pipeline when filters are active)
- Two seed formats to support (org-pulse-config.json and legacy seed.json)
- `org-pulse-config.json` must be kept in sync between Observatory and org-pulse
