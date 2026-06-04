# ADR-0012: Pipeline Definition Collection

## Status

Accepted

## Context

Observatory collects pipeline *outputs* (run history, artifacts, data repo results) but not the pipeline *definitions* themselves. To understand what a pipeline does — its container images, build steps, commands, package dependencies, shared libraries, and harness configuration — we need to scrape the source repos that define the pipelines.

This data lives in multiple places per pipeline:
- `.gitlab-ci.yml` — job definitions, stages, images, scripts, variables
- `Dockerfile` / `Containerfile` — base images, installed packages, build steps
- `pyproject.toml` / `requirements.txt` / `setup.cfg` — Python dependencies
- `package.json` — Node dependencies
- Skill repos and shared libs (referenced in org-pulse-config) — the agent skills and reusable CI tooling
- Container image references — what images jobs run in

The org-pulse-config.json already declares some of this (skills, shared_libs, images) but it's manually maintained and incomplete. The ground truth is in the repos themselves.

## Decision

Extend the `collect-artifacts.py` script to also clone/pull each pipeline's source repo (not just the data repo) and extract key definition files. Store them under `./var/definitions/{pipeline-slug}/`.

### What to collect per pipeline repo:

1. **CI config**: `.gitlab-ci.yml`, `.github/workflows/*.yml`
2. **Container definitions**: `Dockerfile*`, `Containerfile*`, `.container/`
3. **Dependency manifests**: `pyproject.toml`, `requirements*.txt`, `setup.cfg`, `setup.py`, `package.json`, `go.mod`, `Cargo.toml`
4. **Harness/runner config**: `Makefile`, `Taskfile.yml`, `scripts/`, `ci/`
5. **Skill repo definitions**: clone each `skillRepos[].repo` URL and collect the same files

### Directory layout:

```
./var/definitions/
  rfe-autofixer/
    source-repo/          # shallow clone of the pipeline repo
    skills/
      rfe-creator/        # shallow clone of skill repo
    shared-libs/
      ai-agentic-lib/     # shallow clone of shared lib repo
```

### Extracted metadata (future ingestion):

From `.gitlab-ci.yml`, parse and store:
- Job names, stages, and their execution order
- Container images per job (`image:` directive)
- Script commands per job (`script:`, `before_script:`, `after_script:`)
- Variables and environment
- Artifact definitions
- Include/extend references

This parsing is deferred to the ingestion phase (per ADR-0011). The collection phase just captures raw files.

## Consequences

Positive:
- Complete picture of what each pipeline does — not just what it produces
- Can detect drift between declared config (org-pulse-config) and actual CI definitions
- Enables future features: dependency graph, image inventory, command audit, cost attribution
- Skill and shared-lib repos are captured for cross-pipeline analysis

Negative:
- More repos to clone — increases disk and network usage
- Some repos may be private or require additional tokens
- CI config can be complex (includes, extends, anchors) — parsing is non-trivial (deferred)
