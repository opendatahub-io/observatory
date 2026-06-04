# Pipeline Architecture Notes

Captured 2026-06-03 from analysis of pipeline source repos in `./var/definitions/`.

## Common Pattern

All agentic CI pipelines follow the same execution pattern:

1. GitLab CI triggers a job on a tagged runner (`aipcc-small-x86_64` or `itup-alm-x86`)
2. Job runs on `registry.access.redhat.com/ubi9/ubi-minimal:latest` — a bare RHEL 9 image with no pre-installed tooling
3. A bootstrap script (`scripts/run-claude.sh`) installs Claude Code and dependencies at runtime
4. Claude Code connects to **Vertex AI** (Google Cloud) as the LLM backend — not the Anthropic API directly
5. The agent executes a prompt (`$CLAUDE_PROMPT`) with skill repos checked out as context
6. Results are pushed to a data repo via `scripts/push-results.py` (when `$RESULTS_REPO` is set)
7. Two artifacts are always captured: `claude-otel.jsonl` (telemetry) and `claude-stderr.log`

### Exception: autofix pipeline

The `autofix` pipeline uses a pre-built image `quay.io/aipcc/agentic-ci/podman:latest` instead of ubi-minimal. This image includes podman for container-in-container execution. The Containerfiles for these images live in the `ai-agentic-lib` shared library repo.

## Shared `.claude` Job Template

Every pipeline defines a `.claude` (or `.claude-base`) YAML anchor with:

```yaml
.claude:
  tags: [aipcc-small-x86_64]
  image: registry.access.redhat.com/ubi9/ubi-minimal:latest
  variables:
    CLAUDE_CODE_USE_VERTEX: "1"
    ANTHROPIC_VERTEX_PROJECT_ID: "$GCP_PROJECT_ID"
    CLOUD_ML_REGION: "global"
    DISABLE_AUTOUPDATER: "1"
    CLAUDE_CODE_SUBAGENT_MODEL: "claude-opus-4-6"
    JIRA_SERVER: "https://redhat.atlassian.net"
    JIRA_TOKEN: "$JIRA_API_TOKEN"
    GOOGLE_APPLICATION_CREDENTIALS: "/tmp/gcp-key.json"
  artifacts:
    when: always
    paths: [claude-otel.jsonl, claude-stderr.log]
    expire_in: 30 days
```

Individual jobs `extends: .claude` and set their own `$CLAUDE_PROMPT` and `$RESULTS_REPO`.

## Runners

### `aipcc-small-x86_64` (gitlab.com)

Used by: rfe-autofixer, rfe-assessor, epic-decomposer, strat-pipeline, autofix

All gitlab.com pipelines share this runner pool. The tag suggests "small" x86_64 instances provisioned by the AIPCC (AI Platform CC) team. These runners must support either:
- **Bare container execution** — most pipelines run directly on `ubi-minimal` and bootstrap everything in `before_script`
- **Podman-in-container** — the autofix pipeline uses `quay.io/aipcc/agentic-ci/podman:latest` which runs `podman run` inside the CI job to launch the Claude runner container (`quay.io/aipcc/agentic-ci/claude-runner:latest`)

The podman-based approach (used by autofix + ai-agentic-lib consumers) uses `--userns=keep-id:uid=1000,gid=1000` for rootless container execution. This requires the runner to support nested container execution (privileged or sysbox-based).

### `itup-alm-x86` (gitlab.cee.redhat.com)

Used by: strat-security-reviews

Internal Red Hat runner pool on the corporate GitLab instance. Same execution model as `aipcc-small-x86_64` — runs `ubi-minimal` and bootstraps Claude at runtime.

### Queue Impact

All gitlab.com agentic CI jobs compete for the same `aipcc-small-x86_64` runner pool. When multiple pipelines trigger simultaneously (e.g., rfe-assessor and autofix both on schedule), jobs queue behind each other. This is visible in the "Queued" column on the pipeline detail page — long queue times indicate runner contention.

## Two Execution Models

The pipelines use two distinct approaches to running Claude Code:

### Model 1: Direct Install (most pipelines)

```
ubi-minimal → setup-claude-ci.sh → curl install Claude → run-claude.sh → Claude CLI
```

- Used by: rfe-autofixer, rfe-assessor, epic-decomposer, strat-pipeline, strat-security-reviews
- Claude Code installed fresh from `https://claude.ai/install.sh` every run
- No version pinning — always gets the latest Claude Code
- Skills cloned from GitHub at runtime via `$CLAUDE_REPO`
- OTEL telemetry captured by a local Python collector (`otel-collector.py`)

### Model 2: Pre-built Container via Podman (autofix, ai-agentic-lib consumers)

```
podman image → podman run claude-runner:latest → Claude CLI (pre-installed)
```

- Used by: autofix (and any repo that includes `ci/claude-runner.gitlab-ci.yml`)
- Runs inside `quay.io/aipcc/agentic-ci/podman:latest` which has podman
- Launches `quay.io/aipcc/agentic-ci/claude-runner:latest` as a nested container
- Claude Code + all skills from [skills-registry](https://github.com/opendatahub-io/skills-registry) pre-installed
- Image rebuilt daily with date-stamped tags (`YYYYMMDD`)
- GCP credentials mounted read-only from host
- `agentic-ci` Python CLI (`pip install agentic-ci`) handles container lifecycle

### Pre-built Runner Image Contents

`quay.io/aipcc/agentic-ci/claude-runner:latest` (built from `ai-agentic-lib/images/`):

Base: `registry.access.redhat.com/ubi10/ubi-minimal:10.1`

| Category | Tools |
|----------|-------|
| Runtime | python3, git |
| HTTP | curl, jq |
| Build | make, which, tar, xz |
| VCS CLIs | gh (v2.92.0), glab (v1.99.0) |
| Linting | shellcheck (v0.11.0), ruff (v0.15.14) |
| Python | uv (v0.11.16) |
| Library | agentic-ci (v0.2.15) |

Pre-installed skills: odh-ai-helpers, rfe-creator, assess-rfe, rhoai-security-reviewer, test-plan, quality-tooling, agent-eval-harness, meeting-quality-skills

All binary tools pinned with SHA256 checksums.

## Container Images

| Image | Used by | Source |
|-------|---------|--------|
| `registry.access.redhat.com/ubi9/ubi-minimal:latest` | All pipelines (except autofix) | Red Hat UBI |
| `quay.io/aipcc/agentic-ci/podman:latest` | autofix | `ai-agentic-lib/images/ci/Containerfile.podman` |
| `registry.access.redhat.com/ubi9/python-311:latest` | strat-security-reviews (lint job) | Red Hat UBI |

## Repos per Pipeline

| Pipeline | Source Repo | Skill Repos | Shared Libs | Data Repo |
|----------|-----------|-------------|-------------|-----------|
| rfe-autofixer | `agentic-ci/rfe-autofixer` | `opendatahub-io/rfe-creator` | `agentic-ci/ai-agentic-lib` | `agentic-ci/rfe-autofixer-results` |
| rfe-assessor | `agentic-ci/rfe-assessor` | — | — | `agentic-ci/rfe-assess-data` |
| strat-pipeline | `agentic-ci/strat-pipeline` | — | — | `agentic-ci/strat-pipeline-data` |
| strat-security-reviews | `rhoai-security/strat-security-reviews` | — | — | `rhoai-security/strat-security-review-artifacts` |
| autofix | `agentic-ci/autofix` | — | — | — |
| epic-decomposer | `agentic-ci/epic-decomposer` | — | — | — |

## Artifacts Produced

### CI Job Artifacts (in ZIP)

| Pipeline | Artifact Files | Purpose |
|----------|---------------|---------|
| rfe-autofixer | `claude-otel.jsonl`, `claude-stderr.log` | Telemetry + debug log |
| rfe-assessor | `claude-otel.jsonl`, `claude-stderr.log` | Telemetry + debug log |
| strat-pipeline | `claude-otel.jsonl`, `claude-stderr.log` | Telemetry + debug log |
| strat-security-reviews | `artifacts/security-requirements/*.md`, `artifacts/security-reviews/*.md` | Review documents |
| autofix | `triage-pipeline.yml`, `child-pipeline.yml` | Dynamic child pipeline definitions |
| epic-decomposer | `claude-otel.jsonl`, `claude-stderr.log` | Telemetry + debug log |

### Data Repos (pushed results)

| Pipeline | Content | Scale |
|----------|---------|-------|
| rfe-autofixer | RFE review/fix results per Jira issue | ~70k files |
| rfe-assessor | RFE assessment results per Jira issue | ~26k files |
| strat-pipeline | Strategy documents and review outputs | ~3k files |
| strat-security-reviews | Security review artifacts | ~15 files |

## Bootstrap Chain

Each job runs on a bare `ubi-minimal` image and bootstraps everything at runtime:

### 1. `scripts/setup-claude-ci.sh` (called from `before_script`)

```bash
microdnf install -y --nodocs git-core shadow-utils util-linux python3 python3-pip diffutils
useradd -m claude-ci
curl -fsSL https://claude.ai/install.sh | runuser -l claude-ci -c bash
echo "$GCP_SERVICE_ACCOUNT_KEY" | base64 -d > /tmp/gcp-key.json
```

- Installs system packages into the bare UBI image
- Creates a non-root `claude-ci` user
- Installs Claude Code CLI fresh from `https://claude.ai/install.sh` on every run
- Writes GCP service account credentials for Vertex AI

### 2. `before_script` (per-job)

- Clones the skill repo (`$CLAUDE_REPO`) to `/tmp/claude-workdir`
- Runs any skill-specific bootstrap scripts (e.g., `bootstrap-assess-rfe.sh`)
- Clones the data/results repo for snapshot history

### 3. `scripts/run-claude.sh` (main script)

- Starts a local OTEL collector (`otel-collector.py`) to capture token/cost metrics
- Runs `claude -p "$CLAUDE_PROMPT"` with:
  - `--model claude-opus-4-6`
  - `--dangerously-skip-permissions`
  - `--effort high`
  - `--output-format stream-json`
- Streams output through `stream-claude.py` for real-time logging
- After completion, runs `otel-summary.py` to print token/cost summary
- Copies `claude-otel.jsonl` and `claude-stderr.log` to CI artifact directory

### 4. `scripts/push-results.py` (post-run, when `$RESULTS_REPO` is set)

- Pushes the agent's output artifacts to the data/results repo via git

## Key Observations

- Claude Code is installed **fresh on every CI job** — no version pinning, no caching
- All pipelines use **Vertex AI** (GCP), not the Anthropic API directly
- The subagent model is `claude-opus-4-6` across all pipelines
- OTEL telemetry is captured locally via a custom Python collector, not sent to an external endpoint
- The `--dangerously-skip-permissions` flag is used in CI (expected — non-interactive)

## Key Scripts

- `scripts/setup-claude-ci.sh` — system package install + Claude Code install + GCP creds
- `scripts/run-claude.sh` — OTEL setup, runs Claude, captures output
- `scripts/stream-claude.py` — real-time stream processing of Claude's JSON output
- `scripts/otel-collector.py` — local OTLP HTTP receiver that writes to JSONL
- `scripts/otel-summary.py` — parses OTEL JSONL and prints token/cost summary
- `scripts/push-results.py` — pushes artifacts to data/results repo
- `ai-agentic-lib` — shared CI job templates, container image definitions, Jira CLI tools
