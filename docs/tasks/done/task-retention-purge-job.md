# Task: Data Retention and Purge Job

## Goal

Background job that enforces data retention policies by purging old records.

## Acceptance Criteria

- [ ] `telemetry_spans` older than 90 days purged
- [ ] `run_commands`, `run_packages`, `run_containers` older than 180 days purged
- [ ] `pipeline_runs`, `telemetry_summaries`, `container_sboms` kept indefinitely
- [ ] `sbom_vulnerabilities` replaced on re-scan (not accumulated)
- [ ] Runs on schedule (e.g. daily)
- [ ] Logs what was purged (row counts)
- [ ] Configurable retention periods via environment variables

## Files Likely Involved

- backend/jobs/retention.py

## Phase

7 — Polish + Deployment

## Status

Pending
