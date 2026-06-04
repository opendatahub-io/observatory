# ADR-0020: GitLab Job Trace Collection

## Status

Accepted

## Context

The `claude-stderr.log` files in CI job artifacts are all zero bytes — Claude Code's stderr is empty when running non-interactively with `--output-format stream-json`. The actual reasoning trace (thinking blocks, tool calls, Claude's responses) goes through `stream-claude.py` to stdout, which GitLab captures as the job trace log.

The GitLab Jobs API (`GET /projects/{id}/jobs/{job_id}/trace`) returns the full CI job log including:
- Claude's thinking blocks (`🧠 Thinking ...`)
- Claude's responses (`💬 Claude ...`)
- Every tool call with the actual command (`🔧 Bash $ ...`)
- Tool results and subagent output
- OTEL collector setup and summary
- System setup (package installation, Claude Code installation)

A single job trace is ~360KB / 3,200 lines and contains the complete decision chain — what the agent thought, what tools it called, what it said, and why.

This is the missing piece for hallucination root cause analysis. When a claim is refuted, the job trace shows exactly how the agent arrived at the incorrect assertion.

## Decision

Add job trace downloading to `collect-artifacts.py`. For each CI job that has artifacts, also download the job trace via the GitLab API and save it to `./var/artifacts/{slug}/ci-jobs/{pipeline-id}/{job-id}-{job-name}/job-trace.log`.

### Implementation

- Add trace download after artifact ZIP extraction in `collect_ci_artifacts()`
- Skip if `job-trace.log` already exists (idempotent)
- Strip ANSI escape codes for readability
- The trace endpoint returns plain text, no parsing needed

### Directory layout (updated)

```
./var/artifacts/{slug}/ci-jobs/{pipeline-id}/{job-id}-{job-name}/
  ├── claude-otel.jsonl          # OTEL metrics + events (from ZIP)
  ├── claude-stderr.log          # Empty (from ZIP)
  ├── job-trace.log              # NEW: full CI job log from GitLab API
  └── ... other artifact files
```

## Consequences

Positive:
- Complete reasoning trace for every agent run — thinking, tool calls, responses
- Root cause analysis for hallucinations — trace back from a refuted claim to the exact agent decision that produced it
- No changes to the CI pipelines needed — the data already exists in GitLab
- Relatively small files (~360KB each)

Negative:
- One additional API call per job during collection
- Job traces contain ANSI escape codes that need stripping
- Traces may be unavailable for very old jobs (GitLab retention policy)
- Contains runner infrastructure details (docker image pulls, git operations) mixed with agent output
