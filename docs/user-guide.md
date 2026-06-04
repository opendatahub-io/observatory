# Agentic CI Observatory -- User Guide

This guide covers every page in the Observatory UI. Use the sidebar to navigate between sections.

---

## Status Board (`/`)

The landing page shows every registered pipeline as a card, sorted worst-health-first.

### Health colors

| Color  | Meaning |
|--------|---------|
| Green  | Last run succeeded, last success within 1x expected interval, failure rate < 20% over the last 10 runs. |
| Yellow | Last run failed (but previous passed), OR last success is between 1-2x expected interval, OR failure rate 20-50%. |
| Red    | Failure streak >= 3, OR failure rate > 50%, OR no successful run within 2x expected interval, OR no runs found. |
| Grey   | Pipeline is marked `development` or `deprecated`, or has no expected interval configured (on-demand). |

### Card contents

Each card shows:
- Pipeline name and health dot
- Owner name
- Platform badge (GitLab / GitHub)
- Pipeline status (`production`, `development`, `deprecated`)
- Short description

Click a card to open the Pipeline Detail page.

### Filtering and sorting

- **Search box** -- filters by pipeline name or owner (case-insensitive).
- **Status buttons** -- toggle to show only `production`, `development`, or `deprecated` pipelines.
- **Platform buttons** -- toggle to show only `gitlab` or `github` pipelines.
- **Refresh** -- re-fetches the pipeline list from the API.

Cards are always sorted red > yellow > green > grey so the pipelines that need attention appear first.

---

## Pipeline Detail (`/pipelines/:slug`)

### Overview section

- Health status with the colored dot
- Repository URL (links to GitLab/GitHub)
- Cron schedule, expected interval, timeout
- Owner, platform, status

### Run history

A table of recent pipeline runs showing:
- **External ID** -- the CI platform's run/pipeline ID
- **Status** -- success, failed, running, etc.
- **Started / Finished** -- timestamps
- **Duration** -- in seconds
- **Ref** -- branch or tag that triggered the run
- **Web URL** -- link back to the CI platform's run page

Use the pagination controls (page, per_page) and filters (status, since, until) to narrow results.

### Duration chart

A line chart showing run durations over time. Spikes indicate runs that took significantly longer than usual -- investigate those for regressions or infrastructure issues.

### Configuration and metadata

Tabs or sections for:
- **Images** -- container images used by the pipeline
- **Skills** -- AI skill repos (repo URL, branch, purpose)
- **Shared libs** -- shared library repos used across pipelines
- **Jira contracts** -- which Jira projects the pipeline touches and what labels it applies
- **Telemetry config** -- how telemetry is collected (collector type, endpoint)
- **Artifact config** -- where results are pushed (results repo URL)

### Provenance diff (`/pipelines/:slug/diff`)

Compares provenance data (packages, containers) between two runs of the same pipeline. Use this to spot version drift -- for example, a dependency that was upgraded between runs.

---

## Telemetry Dashboard (`/telemetry`)

### Summary

Top-level aggregates across all pipelines (or filtered to one):
- **Total tokens** -- sum of input + output tokens across all runs
- **Total cost (USD)** -- sum of cost_usd from telemetry summaries
- **Run count** -- number of runs with telemetry data

### Cost trends

A time-series chart showing daily cost and token usage. Use this to:
- Spot cost spikes tied to specific pipelines or date ranges
- Track whether optimizations (prompt caching, model downgrades) are reducing spend

### Token breakdown

Per-model breakdown of input vs output tokens. Useful for understanding which models are consuming the most tokens and whether you should switch to a smaller model for certain tasks.

### Cost by pipeline

Bar chart showing total cost per pipeline. Pipelines running more frequently or using larger models will dominate.

### Filters

- **Pipeline** -- scope to a single pipeline slug
- **Since / Until** -- ISO 8601 date strings to narrow the time window

---

## Provenance Explorer (`/provenance`)

### Package inventory

`GET /api/provenance/packages` -- a cross-pipeline view of every Python package (or other manager) tracked across all runs.

Each row shows:
- **Package name** and **version**
- **Package manager** (pip, npm, etc.)
- **Pipeline** that uses it
- **Last seen** -- timestamp of the most recent run that reported this package

Use this to:
- Find all pipelines using a vulnerable package version
- Track version drift across pipelines

### Container inventory

`GET /api/provenance/containers` -- every container image referenced across all pipeline runs.

Each row shows:
- **Image ref** (e.g. `quay.io/rhai/runner:latest`)
- **Image digest** (sha256)
- **Platform**
- **Pipeline** that uses it
- **Last seen**

Click an image digest to view its SBOM (if available).

---

## Trace Explorer (`/traces/:runId`)

### Span waterfall

Displays all OpenTelemetry spans for a specific pipeline run as a waterfall chart. Spans are ordered by start time and nested by parent-child relationships.

Each span shows:
- **Operation name** -- the name of the span (e.g. `llm.chat`, `tool.execute`)
- **Service name** -- maps to the pipeline slug
- **Duration** -- in milliseconds
- **Status code** -- `OK`, `ERROR`, or `UNSET`
- **Timeline bar** -- visual representation of when the span ran relative to the trace

### Span attributes

Click a span to see its attributes. Common attributes for AI pipelines:
- `gen_ai.request.model` -- which LLM model was used
- `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` -- token counts
- `gen_ai.usage.cost` -- cost in USD for this span
- `llm.request.model` -- alternative attribute key for model name

### How traces get here

Traces are pushed to Observatory via the OTLP HTTP JSON endpoint at `POST /v1/traces`. The `service.name` resource attribute is matched against pipeline slugs to correlate spans to pipelines.

---

## Vulnerability Dashboard (`/vulnerabilities`)

### Overview

Shows all known vulnerabilities across every container image that has an SBOM stored in Observatory.

### Severity levels

- **Critical** -- actively exploited or trivially exploitable; fix immediately
- **High** -- significant risk; fix within days
- **Medium** -- moderate risk; fix within your normal patch cycle
- **Low** -- minimal risk; fix when convenient
- **Negligible** -- informational only

### Filtering

- **Severity filter** -- show only Critical, High, etc.
- Each row links to the affected SBOM and shows the vulnerable package, installed version, and fixed version (if known).

### What to do about findings

1. Check if a **fixed version** is listed -- if so, upgrade the package in the container image.
2. If no fix is available, evaluate whether the vulnerability is reachable in your workload.
3. For Critical/High findings with no fix, consider switching base images.
4. Rebuild and re-push the container image, then re-push the SBOM to Observatory. The next vulnerability scan will update the results.

### SBOM viewer (`/sboms/:digest`)

Drill into a specific container image's full SPDX SBOM document. Shows every package in the image with name, version, and license.

---

## Admin Page (`/admin`)

### Collector status

A table showing the collector state for each pipeline:
- **Last collected at** -- when the collector last scraped this pipeline
- **Last run external ID** -- the most recent run ID fetched
- **Last error** -- error message from the most recent failed scrape (if any)
- **Consecutive failures** -- how many scrapes in a row have failed; 3+ means something is broken

### Manual collection

Click **Trigger Collector Run** to fire a one-off collection cycle (`POST /api/collector/run`). The server returns 202 immediately and runs the cycle in the background.

Use this when:
- You just registered a new pipeline and want data immediately
- The scheduled collector is not due for a while and you need fresh data
- You are troubleshooting a collector failure and want to retry now
