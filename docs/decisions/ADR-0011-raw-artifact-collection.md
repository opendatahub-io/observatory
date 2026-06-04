# ADR-0011: Raw Artifact Collection to Filesystem

## Status

Accepted

## Context

Pipeline artifacts come from two sources: CI job artifact ZIPs and data repositories. The data repos can be massive (70k+ files for rfe-autofixer-results). Trying to fetch individual files via the GitLab API, parse them, and store them in SQLite during the collector cycle is too slow and couples collection with ingestion.

The previous approach (ADR implicit in the artifact collector code) tried to do everything in one step: download, parse, and insert into the database during the collector loop. This doesn't scale — a 70k-file repo takes hundreds of API calls just to list the tree, and fetching each file individually is impractical.

## Decision

Separate collection from ingestion:

1. **Collection** — a standalone script (`scripts/collect-artifacts.sh` or Python equivalent) that dumps raw artifacts to the local filesystem:
   - `./var/artifacts/{pipeline-slug}/ci-jobs/{job-id}/` — extracted ZIP contents from CI jobs
   - `./var/artifacts/{pipeline-slug}/data-repo/` — shallow git clone of the results repo
   - In containers, this maps to a volume mount at `/var/observatory/artifacts/`

2. **Ingestion** (future) — a separate step that reads from `./var/artifacts/` and populates the database. This is deferred — the raw data on disk is immediately useful for browsing and debugging.

This mirrors how the org-pulse project handles large data — collect first, process later.

## Consequences

Positive:
- Git clone is orders of magnitude faster than file-by-file API fetches (one operation vs 70k API calls)
- Raw data is immediately available on disk for debugging, grep, and ad-hoc analysis
- Collection and ingestion can evolve independently
- Volume mount in containers makes data persistent across restarts

Negative:
- Requires git binary on the host (available in dev, needs to be in the container image)
- Disk usage grows with repo size — need retention/cleanup strategy
- Two-step process instead of fully automated
