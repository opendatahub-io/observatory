# Task: SBOM Generation Background Job

## Goal

Background job that runs `syft` against new container image digests seen in `run_containers` to auto-generate SBOMs.

## Context

This is the pull/fallback path for SBOMs — when pipelines don't push their own, Observatory generates them. Requires `syft` available in the container.

## Acceptance Criteria

- [ ] Detects new image digests in `run_containers` that don't have a corresponding `container_sboms` entry
- [ ] Runs `syft` to generate SPDX-JSON SBOM
- [ ] Stores result in `container_sboms`
- [ ] Runs on schedule (e.g. hourly) or triggered after collector completes
- [ ] Handles unreachable images gracefully (private registries, etc.)
- [ ] Logs which images were processed and which failed

## Files Likely Involved

- backend/jobs/sbom_generator.py
- Dockerfile (add syft binary)

## Phase

6 — SBOMs + Vulnerability Scanning

## Status

Pending
